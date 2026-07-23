# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — unified scenario → AlertType (single winner per tick).

Emergency is handled only in main.py (higher priority than any value here).
Does not compute risk; does not apply thresholds.
Global non-emergency priority and policy-only kinds: policy_arbitration.py.
"""

from __future__ import annotations

from ble_proximity import BLEProximityContext, VehicleZone
from density_context import DensityContext
from journey_phase import JourneyPhase
from instability_escalation import InstabilityEscalationSnapshot
from observed_cues import ObservedCues, derive_behaviour_level_for_risk
from policy_arbitration import pick_highest_priority_alert
from thresholds import AlertType, SupportCategory
from vulnerability_inference import VulnerabilitySource


_VULNERABLE_FOR_EXIT = frozenset(
    {
        SupportCategory.ELDERLY_SUPPORT,
        SupportCategory.PREGNANCY_SUPPORT,
        SupportCategory.MEDICAL_SENSITIVITY,
        SupportCategory.MOBILITY_SUPPORT,
        SupportCategory.WHEELCHAIR,
        SupportCategory.VISUAL_IMPAIRMENT,
        SupportCategory.NEURODIVERSITY_SUPPORT,
    }
)


def _ble_reinforces_priority_zone(
    ble: BLEProximityContext | None,
) -> tuple[float, float]:
    """Boost effective near_priority_space / near_door if BLE agrees (optional)."""
    if ble is None or not ble.enabled or ble.confidence < 0.35:
        return (0.0, 0.0)
    z = ble.zone
    if z is VehicleZone.WHEELCHAIR_BAY:
        return (0.25 * ble.confidence, 0.0)
    if z in (VehicleZone.FRONT_DOOR, VehicleZone.REAR):
        return (0.0, 0.20 * ble.confidence)
    return (0.0, 0.0)


def select_operational_alert_unified(
    observed: ObservedCues,
    journey_phase: JourneyPhase,
    support_categories: set[SupportCategory],
    density_level: float,
    motion_level: float,
    *,
    density_ctx: DensityContext | None = None,
    ble: BLEProximityContext | None = None,
    system_faults: dict[str, bool] | None = None,
    vulnerability_confirmed: bool = False,
    instability_escalation: InstabilityEscalationSnapshot | None = None,
    vulnerability_source: VulnerabilitySource = VulnerabilitySource.NONE,
) -> AlertType | None:
    """
    Returns one AlertType by global priority, or None (baseline monitoring only).
    """
    o = observed.clamped()
    sup = support_categories
    cands: list[AlertType] = []

    sf = system_faults or {}
    if sf.get("audio_fault") or sf.get("display_fault"):
        cands.append(AlertType.SYSTEM_SUPPORT_ALERT)

    d_boost_p, d_boost_door = _ble_reinforces_priority_zone(ble)
    eff_priority = min(1.0, o.near_priority_space + d_boost_p)
    eff_door = min(1.0, o.near_door_area + d_boost_door)

    if density_level >= 0.78 and (
        o.distress_motion_pattern >= 0.22
        or o.aggressive_motion_pattern >= 0.30
        or eff_door >= 0.5
    ):
        cands.append(AlertType.CROWDING_ADVISORY)

    if sup & _VULNERABLE_FOR_EXIT:
        if eff_door >= 0.42 and density_level >= 0.58:
            if (
                o.distress_motion_pattern >= 0.18
                or o.prolonged_standing >= 0.38
                or o.unstable_posture >= 0.32
            ):
                cands.append(AlertType.BLOCKED_EXIT_VULNERABLE)

    if SupportCategory.CHILD_SUPPORT in sup:
        if o.rapid_erratic_motion >= 0.42 and motion_level >= 0.45:
            cands.append(AlertType.CHILD_HIGH_MOVEMENT)

    if o.large_mobility_device_present >= 0.45:
        if eff_priority < 0.35 and (
            o.near_stairs_or_upper_deck >= 0.4 or motion_level >= 0.55
        ):
            cands.append(AlertType.WHEELCHAIR_UNSAFE_POSITION)
        if eff_priority >= 0.4 and o.unstable_posture >= 0.38:
            cands.append(AlertType.WHEELCHAIR_UNSTABLE_IN_BAY)
        if o.prolonged_standing >= 0.42 and density_level >= 0.52 and motion_level >= 0.35:
            cands.append(AlertType.WHEELCHAIR_BAY_OBSTRUCTION)

    if o.small_wheeled_carriage_present >= 0.45:
        if o.near_stairs_or_upper_deck >= 0.45 or (
            o.unstable_posture >= 0.35 and motion_level >= 0.4
        ):
            cands.append(AlertType.PUSHCHAIR_UNSAFE_POSITION)
        if o.unstable_posture >= 0.36 and motion_level >= 0.42:
            cands.append(AlertType.PUSHCHAIR_INSTABILITY)

    _seat_sup = frozenset(
        {
            SupportCategory.ELDERLY_SUPPORT,
            SupportCategory.MOBILITY_SUPPORT,
            SupportCategory.MEDICAL_SENSITIVITY,
            SupportCategory.PREGNANCY_SUPPORT,
        }
    )
    if sup & _seat_sup:
        if o.leaning_without_support >= 0.4 and o.prolonged_standing >= 0.35:
            cands.append(AlertType.SEAT_ASSISTANCE_REQUIRED)

    if journey_phase is JourneyPhase.END_OF_ROUTE:
        if (
            o.prolonged_standing >= 0.32
            or o.unstable_posture >= 0.28
            or o.floor_level_posture >= 0.28
        ):
            cands.append(AlertType.JOURNEY_END_CHECK)

    if journey_phase is JourneyPhase.APPROACHING_STOP:
        if o.navigation_aid_in_use >= 0.35 and SupportCategory.VISUAL_IMPAIRMENT in sup:
            cands.append(AlertType.EXIT_PREPARATION)

    # Standing-while-moving is assistive context for *confirmed vulnerable* passengers only;
    # generic passengers must not get motion/posture-alone STANDING alerts.
    if vulnerability_confirmed and journey_phase in (JourneyPhase.IN_MOTION, JourneyPhase.APPROACHING_STOP):
        if o.prolonged_standing >= 0.44 and motion_level >= 0.38:
            cands.append(AlertType.STANDING_MOTION_RISK)

    esc_active = (
        instability_escalation.escalation_active if instability_escalation is not None else False
    )
    b = derive_behaviour_level_for_risk(
        o,
        vulnerability_confirmed=vulnerability_confirmed,
        instability_escalation_active=esc_active,
        vulnerability_source=vulnerability_source.value,
    )
    scen_instability_motion = max(
        o.rapid_erratic_motion,
        o.repetitive_agitated_motion,
        o.distress_motion_pattern,
        o.aggressive_motion_pattern,
    )

    if vulnerability_confirmed:
        if vulnerability_source is VulnerabilitySource.MOBILITY_AID:
            # Mobility-aid users: instability_risk requires escalation or clear wobble under motion,
            # not generic posture / compounded behaviour thresholds alone.
            if esc_active:
                if journey_phase in (JourneyPhase.IN_MOTION, JourneyPhase.APPROACHING_STOP) and motion_level >= 0.33:
                    cands.append(AlertType.INSTABILITY_RISK)
                elif (
                    journey_phase is JourneyPhase.BOARDING
                    and motion_level >= 0.35
                    and o.unstable_posture >= 0.30
                ):
                    cands.append(AlertType.INSTABILITY_RISK)
            if journey_phase in (JourneyPhase.IN_MOTION, JourneyPhase.APPROACHING_STOP) and motion_level >= 0.34:
                if o.unstable_posture >= 0.41 and scen_instability_motion >= 0.20:
                    cands.append(AlertType.INSTABILITY_RISK)
        else:
            # Device- or posture-classified vulnerability: baseline-relative but may still use
            # strong compounded behaviour when escalation cues align.
            if scen_instability_motion >= 0.28:
                if journey_phase in (JourneyPhase.IN_MOTION, JourneyPhase.APPROACHING_STOP) and motion_level >= 0.38:
                    cands.append(AlertType.INSTABILITY_RISK)
                elif journey_phase is JourneyPhase.BOARDING and motion_level >= 0.35:
                    cands.append(AlertType.INSTABILITY_RISK)
            if esc_active:
                if journey_phase in (JourneyPhase.IN_MOTION, JourneyPhase.APPROACHING_STOP) and motion_level >= 0.33:
                    cands.append(AlertType.INSTABILITY_RISK)
                elif (
                    journey_phase is JourneyPhase.BOARDING
                    and motion_level >= 0.35
                    and o.unstable_posture >= 0.30
                ):
                    cands.append(AlertType.INSTABILITY_RISK)
            if journey_phase in (JourneyPhase.IN_MOTION, JourneyPhase.APPROACHING_STOP) and motion_level >= 0.34:
                if o.unstable_posture >= 0.41 and scen_instability_motion >= 0.20:
                    cands.append(AlertType.INSTABILITY_RISK)
            if b >= 0.58 and motion_level >= 0.42:
                cands.append(AlertType.INSTABILITY_RISK)
    else:
        # Non-vulnerable: routine standing, leaning, and mild balance correction must not
        # select INSTABILITY_RISK — only stronger kinematic / compounded behaviour patterns.
        if scen_instability_motion >= 0.36 and motion_level >= 0.40:
            cands.append(AlertType.INSTABILITY_RISK)
        if b >= 0.64 and motion_level >= 0.48:
            cands.append(AlertType.INSTABILITY_RISK)
        if journey_phase is JourneyPhase.BOARDING:
            if o.unstable_posture >= 0.52 and motion_level >= 0.42:
                cands.append(AlertType.INSTABILITY_RISK)

    unique = list(dict.fromkeys(cands))
    return pick_highest_priority_alert(unique)


def highest_priority_alert(candidates: list[AlertType]) -> AlertType | None:
    return pick_highest_priority_alert(candidates)
