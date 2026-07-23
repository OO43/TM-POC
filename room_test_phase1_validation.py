# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
ROOM_TEST Phase-1 end-to-end validation helpers (logging / terminal only).

- Zeroes non–Phase-1 observed cue fields (adapter output shaping only).
- Prints per-tick cue snapshots and a read-only mirror of scenario selection inputs.
- Prints single-line PHASE1_ALERT transitions (does not alter evaluate_driver_tick).

Enable: ROOM_TEST=1 and ROOM_TEST_PHASE1_VALIDATE=1

Phase-1B (``ROOM_TEST_LIVE_CAMERA``): terminal lines use condensed ``PHASE1_CUES`` keys
below; ``PHASE1_MIRROR`` is suppressed; ``PHASE1_ALERT`` only on state transitions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, fields as dc_fields
from typing import TYPE_CHECKING, Any

import tick_driver_eval as tde
from navigation_aid_behavioral_gate import last_gated_observed_cues
from alert_routing import select_operational_alert_type
from can_context import CANContext, derive_motion_level
from observed_cues import ObservedCues
from policy_arbitration import is_vehicle_stationary_for_diversion, strict_overcapacity
from instability_escalation import peek_instability_escalation
from scenario_classification import select_operational_alert_unified
from thresholds import AlertType
from vulnerability_inference import peek_vulnerability_snapshot

from adapters.room_test_env import room_test_live_camera_enabled

if TYPE_CHECKING:
    from tick_driver_eval import DriverTickOutcome

PHASE1_CUE_FIELDS: frozenset[str] = frozenset(
    {
        "near_door_area",
        "prolonged_standing",
        "unstable_posture",
        "floor_level_posture",
        "frequent_balance_correction",
        "leaning_without_support",
        "navigation_aid_in_use",
        "navigation_aid_candidate",
        "nav_aid_floor_contact",
        "nav_aid_gait_coupling",
        "nav_aid_vertical_load",
        "nav_aid_unilateral_bias",
    }
)


def apply_phase1_observed_cue_mask(tick: dict) -> None:
    """Force all ObservedCues keys except Phase-1 set to 0.0 (ROOM_TEST instrumentation)."""
    raw = tick.get("observed_cues")
    if not isinstance(raw, dict):
        return
    for f in dc_fields(ObservedCues):
        if f.name not in PHASE1_CUE_FIELDS:
            raw[f.name] = 0.0


def mirror_scenario_selected(tick: dict) -> AlertType | None:
    """Observation-only replay of scenario selection (same helpers as evaluate_driver_tick)."""
    observed = tde._observed_cues_from_tick(tick)
    support_categories = tde._support_categories_from_tick(tick)
    journey_phase = tde._journey_phase_from_tick(tick)
    density_ctx = tde._density_ctx_from_tick(tick)
    passenger_density = tde._passenger_density_from_tick(tick, density_ctx)
    can_context = tde._can_context_from_tick(tick)
    vehicle_motion = derive_motion_level(can_context)
    ble_ctx = tde._ble_from_tick(tick)
    system_faults = tde._system_faults_from_tick(tick)

    if observed is not None:
        gated = last_gated_observed_cues()
        if gated is not None:
            observed = gated
        vu = peek_vulnerability_snapshot()
        esc = peek_instability_escalation()
        return select_operational_alert_unified(
            observed,
            journey_phase,
            support_categories,
            passenger_density,
            vehicle_motion,
            density_ctx=density_ctx,
            ble=ble_ctx,
            system_faults=system_faults,
            vulnerability_confirmed=vu.confirmed,
            vulnerability_source=vu.source,
            instability_escalation=esc,
        )
    passenger_behaviour = tde._passenger_behaviour_from_tick(tick, observed)
    return select_operational_alert_type(
        passenger_behaviour,
        vehicle_motion,
        passenger_density,
        support_categories,
        journey_phase,
    )


def mirror_policy_candidate_flags(tick: dict, can_ctx: CANContext, motion_level: float) -> dict[str, bool]:
    """Boolean mirror of evaluate_driver_tick policy_candidates construction (logging only)."""
    pe = tde._passenger_event_from_tick(tick)
    density_ctx = tde._density_ctx_from_tick(tick)
    de = tde._driver_event_from_tick(tick)
    stationary_flag = bool(can_ctx.vehicle_stationary)
    diversion_allowed = is_vehicle_stationary_for_diversion(stationary_flag, motion_level)

    stop_req = bool(pe.stop_request and pe.consented)
    over_cap = bool(
        density_ctx is not None
        and strict_overcapacity(density_ctx.passengers_onboard, density_ctx.vehicle_capacity)
    )
    div_active = bool(de.diversion_active and diversion_allowed)
    div_blocked = bool(de.diversion_active and not diversion_allowed)

    return {
        "passenger_stop_request_policy": stop_req,
        "capacity_exceeded_policy": over_cap,
        "route_diversion_candidate": div_active,
        "route_diversion_blocked": div_blocked,
    }


def _primary_signature(output: dict[str, Any], out: "DriverTickOutcome") -> str:
    """Single string for PHASE1_ALERT transition detection."""
    if out.kind == "sticky_pending":
        return "EMERGENCY_STICKY"
    if out.kind == "immediate":
        return "EMERGENCY_IMMEDIATE"

    pa = output.get("primary_alert")
    if isinstance(pa, dict) and pa.get("alert_type") is not None:
        return str(pa["alert_type"])
    return "NONE"


def _reason_short(out: "DriverTickOutcome", scenario_mirror: AlertType | None) -> str:
    if out.kind != "routine":
        return f"path={out.kind}"
    mir = scenario_mirror.value if scenario_mirror else "NONE"
    fw = out.final_winner.value if out.final_winner else "NONE"
    return (
        f"path=routine scenario_mirror={mir} final_winner={fw} should_alert={out.should_alert} "
        f"scenario_matched={out.scenario_matched} risk_score={out.risk_score:.3f} bypass={out.policy_bypass}"
    )


@dataclass
class Phase1TerminalState:
    prev_sig: str | None = None


def run_phase1_validation_tick(
    *,
    tick_seq: int,
    tick: dict,
    out: "DriverTickOutcome",
    backend_output: dict[str, Any],
    terminal_state: Phase1TerminalState,
    log: logging.Logger | None,
) -> None:
    """Per-tick console trace + PHASE1_TRANSITION lines (ROOM_TEST Phase-1 validation)."""
    can_raw = tick.get("can") or {}
    can_summary = {
        "speed": float(can_raw.get("speed", 0.0)),
        "braking_intensity": float(can_raw.get("braking_intensity", 0.0)),
        "turn_intensity": float(can_raw.get("turn_intensity", 0.0)),
        "doors_open": bool(can_raw.get("doors_open", False)),
        "ramp_deployed": bool(can_raw.get("ramp_deployed", False)),
        "vehicle_stationary": bool(can_raw.get("vehicle_stationary", False)),
    }

    observed_raw = dict(tick.get("observed_cues") or {})
    cues_line = json.dumps(observed_raw, sort_keys=True, separators=(",", ":"))

    can_ctx = tde._can_context_from_tick(tick)
    motion_level = derive_motion_level(can_ctx)
    scenario_mirror = mirror_scenario_selected(tick)
    policy_flags = mirror_policy_candidate_flags(tick, can_ctx, motion_level)

    queue_types = [
        row.get("alert_type")
        for row in (backend_output.get("ordered_alerts") or [])
        if isinstance(row, dict)
    ]

    trace_payload = {
        "tick": tick_seq,
        "observed_cues": observed_raw,
        "vehicle": {**can_summary, "motion_level": motion_level},
        "policy_flags_mirror": policy_flags,
        "mirror_scenario_selected": scenario_mirror.value if scenario_mirror else None,
        "outcome": {
            "kind": out.kind,
            "final_winner": out.final_winner.value if out.final_winner else None,
            "operational_alert": out.operational_alert.value if out.operational_alert else None,
            "should_alert": out.should_alert,
            "scenario_matched": out.scenario_matched,
            "risk_score": out.risk_score,
            "policy_bypass": out.policy_bypass,
            "passing_operational_types": [x.value for x in out.passing_operational_types],
            "primary_queue_alert_types": queue_types,
            "vulnerability_confidence": out.vulnerability_confidence,
            "vulnerability_confirmed": out.vulnerability_confirmed,
            "vulnerability_source": out.vulnerability_source,
            "vulnerability_advisory_active": out.vulnerability_advisory_active,
            "vulnerable_passenger_near_door": out.vulnerable_passenger_near_door,
            "exit_assistance_advisory_active": out.exit_assistance_advisory_active,
        },
    }
    if log is not None:
        log.info("PHASE1_TRACE %s", json.dumps(trace_payload, separators=(",", ":")))

    live_b = room_test_live_camera_enabled()
    p1_keys = sorted(PHASE1_CUE_FIELDS)
    if live_b:
        parts = []
        for k in p1_keys:
            parts.append(f"{k}={float(observed_raw.get(k, 0.0)):.3f}")
        print(f"PHASE1_CUES tick={tick_seq} " + " ".join(parts), flush=True)
    else:
        print(f"PHASE1_CUES tick={tick_seq} {cues_line}", flush=True)

    if not live_b:
        mir = scenario_mirror.value if scenario_mirror else "NONE"
        print(
            f"PHASE1_MIRROR tick={tick_seq} scenario_mirror={mir} motion={motion_level:.4f} "
            f"policy_flags_mirror={policy_flags}",
            flush=True,
        )

    cur = _primary_signature(backend_output, out)
    if terminal_state.prev_sig is None:
        terminal_state.prev_sig = cur
        if not live_b:
            print(f"PHASE1_ALERT INITIAL:{cur} | {_reason_short(out, scenario_mirror)}", flush=True)
        return

    if cur == terminal_state.prev_sig:
        return

    prev = terminal_state.prev_sig
    if prev != "NONE" and cur == "NONE":
        print("PHASE1_ALERT ALERT CLEARED", flush=True)
        print(f"PHASE1_ALERT NO_ALERT | {_reason_short(out, scenario_mirror)}", flush=True)
    elif prev == "NONE" and cur != "NONE":
        print(f"PHASE1_ALERT ALERT: {cur} | {_reason_short(out, scenario_mirror)}", flush=True)
    else:
        print(
            f"PHASE1_ALERT CHANGE: {prev} -> {cur} | {_reason_short(out, scenario_mirror)}",
            flush=True,
        )
    terminal_state.prev_sig = cur
