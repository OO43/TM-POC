# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — single-tick driver evaluation (shared by main harness and interactive CLI).

Extracted so interactive mode uses the same arbitration, risk gates, and policy rules as main.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields, replace
from typing import Literal, Sequence

from alert_routing import resolve_support_for_thresholds, select_operational_alert_type
from ble_proximity import BLEProximityContext, VehicleZone
from can_context import CANContext, derive_motion_level
from density_context import DensityContext, derive_density_level
from emergency import EmergencyEvent, SimulatedEmergencyInputs, resolve_simulated_emergency
from event_contexts import DriverEventContext, PassengerEventContext
from journey_phase import JourneyPhase
from instability_escalation import update_instability_escalation
from observed_cues import ObservedCues, derive_behaviour_level_for_risk, derive_behaviour_level_from_cues
from policy_arbitration import (
    bypasses_compounded_risk_gating,
    is_vehicle_stationary_for_diversion,
    pick_highest_priority_alert,
    strict_overcapacity,
)
from medical_slow_collapse_emergency import update_medical_slow_collapse_tracker
from policy_floor_emergency import merge_tick_emergency_inputs_with_floor_policy
from scenario_classification import select_operational_alert_unified
from thresholds import AlertType, SupportCategory, ThresholdParams, get_threshold_params
from exit_vulnerable_door import (
    compute_vulnerable_passenger_near_door,
    exit_crowded_assist_advisory_eligible,
    exit_crowded_assist_conditions,
    high_density_for_exit_assist,
    update_exit_crowded_assist_dwell,
)
from cabin_presence_gate import (
    passenger_present_for_alert_path,
    reset_cabin_inferencers_when_no_passenger_visible,
)
from navigation_aid_behavioral_gate import apply_navigation_aid_behavioral_gate
from vulnerability_advisory_clearance import vulnerability_assistance_cleared_by_stable_cabin
from vulnerability_inference import (
    update_vulnerability_state,
    vulnerability_advisory_eligible,
)
from passenger_remaining_onboard_policy import (
    remaining_onboard_advisory_eligible,
    reset_passenger_remaining_onboard_ack_state,
)


def _support_categories_from_tick(tick: dict) -> set[SupportCategory]:
    raw = tick.get("support_categories")
    if raw is not None:
        out = {SupportCategory(x) for x in raw}
        return out if out else {SupportCategory.UNDECLARED}
    if "support_category" in tick:
        return {SupportCategory(tick["support_category"])}
    return {SupportCategory.UNDECLARED}


def _journey_phase_from_tick(tick: dict) -> JourneyPhase:
    if "journey_phase" in tick:
        return JourneyPhase(tick["journey_phase"])
    if tick.get("journey_terminal"):
        return JourneyPhase.END_OF_ROUTE
    if tick.get("approaching_stop"):
        return JourneyPhase.APPROACHING_STOP
    return JourneyPhase.IN_MOTION


def _can_context_from_tick(tick: dict) -> CANContext:
    raw = tick.get("can")
    if raw is not None:
        return CANContext(
            speed=float(raw.get("speed", 0.0)),
            braking_intensity=float(raw.get("braking_intensity", 0.0)),
            turn_intensity=float(raw.get("turn_intensity", 0.0)),
            doors_open=bool(raw.get("doors_open", False)),
            ramp_deployed=bool(raw.get("ramp_deployed", False)),
            vehicle_stationary=bool(raw.get("vehicle_stationary", False)),
        )
    m = float(tick.get("motion", 0.0))
    return CANContext(
        speed=m,
        braking_intensity=min(1.0, m * 0.6),
        turn_intensity=min(1.0, m * 0.4),
        doors_open=False,
        ramp_deployed=False,
        vehicle_stationary=False,
    )


def _driver_event_from_tick(tick: dict) -> DriverEventContext:
    raw = tick.get("driver_event") or {}
    reason = raw.get("diversion_reason")
    return DriverEventContext(
        diversion_active=bool(raw.get("diversion_active", False)),
        diversion_reason=str(reason) if reason is not None else None,
    )


def _passenger_event_from_tick(tick: dict) -> PassengerEventContext:
    raw = tick.get("passenger_event") or {}
    return PassengerEventContext(
        stop_request=bool(raw.get("stop_request", False)),
        source=str(raw.get("source", "app")),
        consented=bool(raw.get("consented", False)),
    )


def _emergency_inputs_from_tick(tick: dict) -> SimulatedEmergencyInputs:
    raw = tick.get("emergency", {})
    return SimulatedEmergencyInputs(
        passenger_collapse_or_fall=bool(raw.get("passenger_collapse_or_fall", False)),
        fire_or_smoke=bool(raw.get("fire_or_smoke", False)),
        medical_collapse_slow_descent=bool(
            raw.get("medical_collapse_slow_descent", False)
        ),
        altercation=bool(raw.get("altercation", False)),
        severe_distress=bool(raw.get("severe_distress", False)),
    )


def _observed_cues_from_tick(tick: dict) -> ObservedCues | None:
    raw = tick.get("observed_cues")
    if raw is None:
        return None
    kw = {f.name: float(raw.get(f.name, 0.0)) for f in dc_fields(ObservedCues)}
    return ObservedCues(**kw)


def _density_ctx_from_tick(tick: dict) -> DensityContext | None:
    raw = tick.get("density_context")
    if not raw:
        return None
    return DensityContext(
        passengers_onboard=int(raw["passengers_onboard"]),
        vehicle_capacity=int(raw["vehicle_capacity"]),
    )


def _passenger_density_from_tick(tick: dict, density_ctx: DensityContext | None) -> float:
    if density_ctx is not None:
        return derive_density_level(density_ctx)
    return float(tick["density"])


def _passenger_behaviour_from_tick(tick: dict, observed: ObservedCues | None) -> float:
    if observed is not None:
        return derive_behaviour_level_from_cues(observed)
    return float(tick["behaviour"])


def _ble_from_tick(tick: dict) -> BLEProximityContext | None:
    raw = tick.get("ble")
    if not raw:
        return None
    return BLEProximityContext(
        enabled=bool(raw.get("enabled", False)),
        zone=VehicleZone(raw.get("zone", "unknown")),
        confidence=float(raw.get("confidence", 0.0)),
    )


def _system_faults_from_tick(tick: dict) -> dict[str, bool]:
    return dict(tick.get("system_faults") or {})


def evaluate_risk(
    behaviour: float,
    motion: float,
    density: float,
    consent_enhanced_supervision: bool,
    params: ThresholdParams,
) -> float:
    compounded = (behaviour * motion * density) ** (1.0 / 3.0)
    sensitivity = (
        params.consent_sensitivity_multiplier if consent_enhanced_supervision else 1.0
    )
    return min(1.0, compounded * sensitivity)


def should_trigger_driver_alert(
    behaviour: float,
    motion: float,
    density: float,
    risk_score: float,
    params: ThresholdParams,
) -> bool:
    if risk_score < params.risk_threshold:
        return False
    elevated = sum(
        1
        for x in (behaviour, motion, density)
        if x >= params.factor_elevation_floor
    )
    return elevated >= params.min_elevated_factors


def _collect_passing_operational_alert_types(
    policy_candidates: Sequence[AlertType],
    scenario_selected: AlertType | None,
    support_categories: set[SupportCategory],
    passenger_behaviour: float,
    passenger_density: float,
    vehicle_motion: float,
    consent_enhanced_supervision: bool,
) -> tuple[AlertType, ...]:
    """
    Every operational AlertType that would be gated "on" this tick under existing
    rules: policy bypass kinds if their policy condition fired (they appear in
    ``policy_candidates``), plus the scenario kind if it matches and passes the
    same compounded-risk gate used in ``evaluate_driver_tick`` for that type.

    Does not change detection thresholds or scenario selection; only enumerates
    all passing kinds for stacked UI / backend contracts.
    """
    ordered_union: list[AlertType] = []
    seen: set[AlertType] = set()
    for a in policy_candidates:
        if a not in seen:
            ordered_union.append(a)
            seen.add(a)
    if scenario_selected is not None and scenario_selected not in seen:
        ordered_union.append(scenario_selected)

    passing: list[AlertType] = []
    for at in ordered_union:
        if bypasses_compounded_risk_gating(at):
            passing.append(at)
            continue
        if at != scenario_selected:
            continue
        ts = resolve_support_for_thresholds(support_categories, at)
        tp = get_threshold_params(ts, at)
        risk_score = evaluate_risk(
            passenger_behaviour,
            vehicle_motion,
            passenger_density,
            consent_enhanced_supervision,
            tp,
        )
        if should_trigger_driver_alert(
            passenger_behaviour,
            vehicle_motion,
            passenger_density,
            risk_score,
            tp,
        ):
            passing.append(at)
    return tuple(passing)


@dataclass(frozen=True)
class DriverTickOutcome:
    """Result of one tick; `kind` selects which fields apply."""

    kind: Literal["sticky_pending", "immediate", "routine"]
    emergency_sticky_next: EmergencyEvent | None
    emergency_immediate: EmergencyEvent | None
    cleared_by_ack: bool
    # Routine-only (defaults for emergency paths):
    final_winner: AlertType | None = None
    operational_alert: AlertType = AlertType.INSTABILITY_RISK
    scenario_matched: bool = False
    should_alert: bool = False
    policy_bypass: bool = False
    risk_score: float = 0.0
    policy_candidates: tuple[AlertType, ...] = ()
    threshold_support: SupportCategory = SupportCategory.UNDECLARED
    sup_display: str = ""
    journey_phase_value: str = ""
    consent_enhanced_supervision: bool = False
    diversion_allowed: bool = False
    diversion_blocked: bool = False
    show_diversion_passenger_notify: bool = False
    vehicle_motion_level: float = 0.0
    can_vehicle_stationary: bool = False
    # Routine path only: all operational kinds passing gates this tick (stacked display).
    passing_operational_types: tuple[AlertType, ...] = ()
    vulnerability_confidence: float = 0.0
    vulnerability_confirmed: bool = False
    # VulnerabilitySource value as string: none | mobility_aid | mobility_device | persistent_posture
    vulnerability_source: str = "none"
    vulnerability_advisory_active: bool = False
    vulnerable_passenger_near_door: bool = False
    exit_assistance_advisory_active: bool = False


def evaluate_driver_tick(
    tick: dict,
    *,
    emergency_sticky: EmergencyEvent | None,
    cleared_by_ack: bool,
) -> DriverTickOutcome:
    """
    Same decision outcomes as main.py for one tick (no logging or printing).

    Caller must clear `emergency_sticky` when the operator acknowledges (and pass
    `cleared_by_ack=True` on that tick) so audit logging stays in main.
    """
    es = emergency_sticky

    support_categories = _support_categories_from_tick(tick)
    sup_display = ",".join(sorted(s.value for s in support_categories)) or "undeclared"
    journey_phase = _journey_phase_from_tick(tick)
    consent_enhanced_supervision = bool(tick["consent_enhanced_supervision"])

    if not passenger_present_for_alert_path(tick):
        reset_cabin_inferencers_when_no_passenger_visible()
        reset_passenger_remaining_onboard_ack_state()
        can_ctx_empty = _can_context_from_tick(tick)
        vehicle_motion_empty = derive_motion_level(can_ctx_empty)
        driver_event_empty = _driver_event_from_tick(tick)
        diversion_allowed_empty = is_vehicle_stationary_for_diversion(
            can_ctx_empty.vehicle_stationary, vehicle_motion_empty
        )
        diversion_blocked_empty = bool(driver_event_empty.diversion_active) and (
            not diversion_allowed_empty
        )
        return DriverTickOutcome(
            kind="routine",
            emergency_sticky_next=None,
            emergency_immediate=None,
            cleared_by_ack=cleared_by_ack,
            final_winner=None,
            operational_alert=AlertType.NONE,
            scenario_matched=False,
            should_alert=False,
            policy_bypass=False,
            risk_score=0.0,
            policy_candidates=(),
            threshold_support=SupportCategory.UNDECLARED,
            sup_display=sup_display,
            journey_phase_value=journey_phase.value,
            consent_enhanced_supervision=consent_enhanced_supervision,
            diversion_allowed=diversion_allowed_empty,
            diversion_blocked=diversion_blocked_empty,
            show_diversion_passenger_notify=False,
            vehicle_motion_level=vehicle_motion_empty,
            can_vehicle_stationary=can_ctx_empty.vehicle_stationary,
            passing_operational_types=(),
            vulnerability_confidence=0.0,
            vulnerability_confirmed=False,
            vulnerability_source="none",
            vulnerability_advisory_active=False,
            vulnerable_passenger_near_door=False,
            exit_assistance_advisory_active=False,
        )

    if es is not None:
        return DriverTickOutcome(
            kind="sticky_pending",
            emergency_sticky_next=es,
            emergency_immediate=None,
            cleared_by_ack=cleared_by_ack,
            sup_display=sup_display,
            journey_phase_value=journey_phase.value,
            consent_enhanced_supervision=consent_enhanced_supervision,
            passing_operational_types=(),
            vulnerability_confidence=0.0,
            vulnerability_confirmed=False,
            vulnerability_source="none",
            vulnerability_advisory_active=False,
            vulnerable_passenger_near_door=False,
            exit_assistance_advisory_active=False,
        )

    observed = _observed_cues_from_tick(tick)
    if observed is not None:
        observed = apply_navigation_aid_behavioral_gate(observed)
    density_ctx = _density_ctx_from_tick(tick)
    passenger_density = _passenger_density_from_tick(tick, density_ctx)
    can_context = _can_context_from_tick(tick)
    vehicle_motion = derive_motion_level(can_context)
    ble_ctx = _ble_from_tick(tick)
    system_faults = _system_faults_from_tick(tick)
    diversion_allowed = is_vehicle_stationary_for_diversion(
        can_context.vehicle_stationary, vehicle_motion
    )
    driver_event = _driver_event_from_tick(tick)
    passenger_event = _passenger_event_from_tick(tick)

    vu_snap = update_vulnerability_state(observed)

    base_emergency = merge_tick_emergency_inputs_with_floor_policy(tick)
    inferred_medical = update_medical_slow_collapse_tracker(
        observed, vu_snap.confirmed
    )
    emergency_inputs = replace(
        base_emergency,
        medical_collapse_slow_descent=bool(
            base_emergency.medical_collapse_slow_descent or inferred_medical
        ),
    )
    emergency_event = resolve_simulated_emergency(emergency_inputs)

    if emergency_event is not None and not cleared_by_ack:
        return DriverTickOutcome(
            kind="immediate",
            emergency_sticky_next=emergency_event,
            emergency_immediate=emergency_event,
            cleared_by_ack=cleared_by_ack,
            sup_display=sup_display,
            journey_phase_value=journey_phase.value,
            consent_enhanced_supervision=consent_enhanced_supervision,
            passing_operational_types=(),
            vulnerability_confidence=vu_snap.confidence,
            vulnerability_confirmed=vu_snap.confirmed,
            vulnerability_source=vu_snap.source.value,
            vulnerability_advisory_active=False,
            vulnerable_passenger_near_door=False,
            exit_assistance_advisory_active=False,
        )

    esc_snap = update_instability_escalation(
        observed, vu_snap.confirmed, vu_snap.source
    )
    if observed is not None:
        passenger_behaviour = derive_behaviour_level_for_risk(
            observed,
            vulnerability_confirmed=vu_snap.confirmed,
            instability_escalation_active=esc_snap.escalation_active,
            vulnerability_source=vu_snap.source.value,
        )
    else:
        passenger_behaviour = _passenger_behaviour_from_tick(tick, observed)

    policy_candidates: list[AlertType] = []
    diversion_blocked = False
    if passenger_event.stop_request and passenger_event.consented:
        policy_candidates.append(AlertType.PASSENGER_STOP_REQUEST)
    if density_ctx is not None and strict_overcapacity(
        density_ctx.passengers_onboard, density_ctx.vehicle_capacity
    ):
        policy_candidates.append(AlertType.CAPACITY_EXCEEDED)
    if driver_event.diversion_active:
        if diversion_allowed:
            policy_candidates.append(AlertType.ROUTE_DIVERSION_ACTIVE)
        else:
            diversion_blocked = True

    if observed is not None:
        scenario_selected = select_operational_alert_unified(
            observed,
            journey_phase,
            support_categories,
            passenger_density,
            vehicle_motion,
            density_ctx=density_ctx,
            ble=ble_ctx,
            system_faults=system_faults,
            vulnerability_confirmed=vu_snap.confirmed,
            vulnerability_source=vu_snap.source,
            instability_escalation=esc_snap,
        )
    else:
        scenario_selected = select_operational_alert_type(
            passenger_behaviour,
            vehicle_motion,
            passenger_density,
            support_categories,
            journey_phase,
        )

    arbitration_inputs = list(policy_candidates)
    if scenario_selected is not None:
        arbitration_inputs.append(scenario_selected)
    final_winner = pick_highest_priority_alert(arbitration_inputs)

    scenario_matched = final_winner is not None
    operational_alert = (
        final_winner if final_winner is not None else AlertType.INSTABILITY_RISK
    )
    threshold_support = resolve_support_for_thresholds(support_categories, operational_alert)
    threshold_params = get_threshold_params(threshold_support, operational_alert)

    risk_score = evaluate_risk(
        passenger_behaviour,
        vehicle_motion,
        passenger_density,
        consent_enhanced_supervision,
        threshold_params,
    )

    policy_bypass = final_winner is not None and bypasses_compounded_risk_gating(final_winner)
    should_alert = policy_bypass or (
        scenario_matched
        and should_trigger_driver_alert(
            passenger_behaviour,
            vehicle_motion,
            passenger_density,
            risk_score,
            threshold_params,
        )
    )

    show_diversion_passenger_notify = (
        should_alert and final_winner is AlertType.ROUTE_DIVERSION_ACTIVE
    )

    passing_operational_types = _collect_passing_operational_alert_types(
        policy_candidates,
        scenario_selected,
        support_categories,
        passenger_behaviour,
        passenger_density,
        vehicle_motion,
        consent_enhanced_supervision,
    )

    sc_alert = should_alert
    fw_classic = final_winner

    camera_perception_status = str(tick.get("camera_perception_status") or "json_ok")
    _cz_raw = tick.get("camera_zones")
    if isinstance(_cz_raw, dict):
        camera_zones_for_door = {
            k: float(_cz_raw.get(k, 0.0)) for k in ("door", "mid", "rear")
        }
    else:
        camera_zones_for_door = None
    vulnerable_passenger_near_door = compute_vulnerable_passenger_near_door(
        vu_snap,
        observed,
        camera_perception_status=camera_perception_status,
        camera_zones=camera_zones_for_door,
    )
    vuln_advisory_stable_clear = vulnerability_assistance_cleared_by_stable_cabin(
        observed,
        vulnerability_confirmed=vu_snap.confirmed,
        instability_escalation_active=esc_snap.escalation_active,
        vehicle_motion_level=vehicle_motion,
        vulnerable_passenger_near_door=vulnerable_passenger_near_door,
    )
    doors_open = bool(can_context.doors_open)
    dwell_gates = (
        vulnerable_passenger_near_door
        and doors_open
        and bool(can_context.vehicle_stationary)
        and high_density_for_exit_assist(passenger_density)
    )
    _, dwell_exceeded = update_exit_crowded_assist_dwell(dwell_gates)
    exit_conditions_met = exit_crowded_assist_conditions(
        vulnerable_passenger_near_door=vulnerable_passenger_near_door,
        doors_open=doors_open,
        vehicle_stationary=bool(can_context.vehicle_stationary),
        density_ratio=passenger_density,
        dwell_exceeded=dwell_exceeded,
    )
    exit_advisory = exit_crowded_assist_advisory_eligible(
        exit_conditions_met=exit_conditions_met,
        should_alert_classic=sc_alert,
        final_winner=fw_classic,
    )
    vuln_advisory = vulnerability_advisory_eligible(
        observed=observed,
        snapshot=vu_snap,
        should_alert_classic=sc_alert,
        final_winner=fw_classic,
    ) and not vuln_advisory_stable_clear

    remaining_eligible = remaining_onboard_advisory_eligible(
        tick,
        observed,
        can_context=can_context,
        density_ctx=density_ctx,
        exit_advisory=exit_advisory,
        vuln_advisory=vuln_advisory,
        final_winner_classic=fw_classic,
        policy_candidates=policy_candidates,
        should_alert_classic=sc_alert,
    )

    if exit_advisory:
        should_alert = True
        scenario_matched = True
        operational_alert = AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY
        final_winner = AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY
        policy_bypass = True
        threshold_support = resolve_support_for_thresholds(
            support_categories, AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY
        )
        passing_operational_types = passing_operational_types + (
            AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY,
        )
    elif vuln_advisory:
        should_alert = True
        scenario_matched = True
        operational_alert = AlertType.VULNERABILITY_ASSISTANCE_ADVISORY
        final_winner = AlertType.VULNERABILITY_ASSISTANCE_ADVISORY
        policy_bypass = True
        threshold_support = resolve_support_for_thresholds(
            support_categories, AlertType.VULNERABILITY_ASSISTANCE_ADVISORY
        )
        passing_operational_types = passing_operational_types + (
            AlertType.VULNERABILITY_ASSISTANCE_ADVISORY,
        )
    elif remaining_eligible:
        should_alert = True
        scenario_matched = True
        operational_alert = AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY
        final_winner = AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY
        policy_bypass = True
        threshold_support = resolve_support_for_thresholds(
            support_categories, AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY
        )
        passing_operational_types = passing_operational_types + (
            AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY,
        )

    return DriverTickOutcome(
        kind="routine",
        emergency_sticky_next=None,
        emergency_immediate=None,
        cleared_by_ack=cleared_by_ack,
        final_winner=final_winner,
        operational_alert=operational_alert,
        scenario_matched=scenario_matched,
        should_alert=should_alert,
        policy_bypass=policy_bypass,
        risk_score=risk_score,
        policy_candidates=tuple(policy_candidates),
        threshold_support=threshold_support,
        sup_display=sup_display,
        journey_phase_value=journey_phase.value,
        consent_enhanced_supervision=consent_enhanced_supervision,
        diversion_allowed=diversion_allowed,
        diversion_blocked=diversion_blocked,
        show_diversion_passenger_notify=show_diversion_passenger_notify,
        vehicle_motion_level=vehicle_motion,
        can_vehicle_stationary=can_context.vehicle_stationary,
        passing_operational_types=passing_operational_types,
        vulnerability_confidence=vu_snap.confidence,
        vulnerability_confirmed=vu_snap.confirmed,
        vulnerability_source=vu_snap.source.value,
        vulnerability_advisory_active=vuln_advisory and not exit_advisory,
        vulnerable_passenger_near_door=vulnerable_passenger_near_door,
        exit_assistance_advisory_active=exit_advisory,
    )
