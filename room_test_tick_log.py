# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Per-tick logging for room validation runs.

Compares successive adapter snapshots and alert queues to emit observer-oriented
lines (including heuristic ``clearing_hint`` strings). Does not drive policy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from tick_driver_eval import DriverTickOutcome


def _summarize_tick(tick: dict) -> dict[str, Any]:
    oc = tick.get("observed_cues") or {}
    can = tick.get("can") or {}
    pe = tick.get("passenger_event") or {}
    dc = tick.get("density_context") or {}
    cz = tick.get("camera_zones") or {}
    return {
        "observed_cues": {k: float(v) for k, v in oc.items()} if isinstance(oc, dict) else {},
        "can": {
            "speed": float(can.get("speed", 0.0)),
            "braking_intensity": float(can.get("braking_intensity", 0.0)),
            "turn_intensity": float(can.get("turn_intensity", 0.0)),
            "doors_open": bool(can.get("doors_open", False)),
            "ramp_deployed": bool(can.get("ramp_deployed", False)),
            "vehicle_stationary": bool(can.get("vehicle_stationary", False)),
        },
        "density_context": {
            "passengers_onboard": int(dc.get("passengers_onboard", 0)),
            "vehicle_capacity": int(dc.get("vehicle_capacity", 1)),
        },
        "density_ratio": float(tick.get("density", 0.0)),
        "passenger_event": {
            "stop_request": bool(pe.get("stop_request", False)),
            "consented": bool(pe.get("consented", False)),
            "source": pe.get("source", ""),
        },
        "camera_zones": {
            "door": float(cz.get("door", 0.0)),
            "mid": float(cz.get("mid", 0.0)),
            "rear": float(cz.get("rear", 0.0)),
        },
        "camera_zone_primary": tick.get("camera_zone_primary"),
        "consent_enhanced_supervision": bool(tick.get("consent_enhanced_supervision", False)),
    }


def _norm_cue_delta_hints(prev: dict[str, float], curr: dict[str, float]) -> list[str]:
    eps = 0.04
    hints: list[str] = []
    for key in (
        "floor_level_posture",
        "unstable_posture",
        "prolonged_standing",
        "rapid_erratic_motion",
    ):
        p, c = float(prev.get(key, 0.0)), float(curr.get(key, 0.0))
        if p > eps and c <= eps:
            hints.append(f"cue_{key}_normalized")
        elif c + eps < p:
            hints.append(f"cue_{key}_decreased")
    return hints


def _motion_hints(prev: dict[str, Any], curr: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    ps, cs = float(prev["can"]["speed"]), float(curr["can"]["speed"])
    if ps > 0.25 and cs <= 0.25:
        hints.append("can_speed_returned_low")
    if prev["can"]["vehicle_stationary"] is False and curr["can"]["vehicle_stationary"] is True:
        hints.append("can_vehicle_now_stationary")
    return hints


def _density_hints(prev: dict[str, Any], curr: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    po_p = int(prev["density_context"]["passengers_onboard"])
    po_c = int(curr["density_context"]["passengers_onboard"])
    cap_p = max(1, int(prev["density_context"]["vehicle_capacity"]))
    cap_c = max(1, int(curr["density_context"]["vehicle_capacity"]))
    r_p, r_c = po_p / cap_p, po_c / cap_c
    if r_c + 0.02 < r_p:
        hints.append("density_ratio_decreased")
    if po_c < po_p:
        hints.append("passengers_onboard_decreased")
    return hints


def _collect_clearing_hints(
    prev: dict[str, Any] | None,
    curr: dict[str, Any],
    dropped_alerts: list[str],
) -> dict[str, Any]:
    if not dropped_alerts or prev is None:
        return {"dropped": dropped_alerts, "clearing_hints": [], "input_deltas": []}
    hints: list[str] = []
    if prev["passenger_event"]["stop_request"] and not curr["passenger_event"]["stop_request"]:
        hints.append("passenger_stop_request_cleared")
    hints.extend(_norm_cue_delta_hints(prev["observed_cues"], curr["observed_cues"]))
    hints.extend(_motion_hints(prev, curr))
    hints.extend(_density_hints(prev, curr))
    # Generic fallback when we saw queue shrink but no specific hint matched
    if not hints and dropped_alerts:
        hints.append("scenario_inputs_changed_operational_re_evaluation")
    return {
        "dropped": dropped_alerts,
        "clearing_hints": hints,
        "input_snapshot_prev": prev,
        "input_snapshot_curr": curr,
    }


@dataclass
class RoomTestTickLogState:
    prev_input_summary: dict[str, Any] | None = None
    prev_queue: tuple[str, ...] = ()
    prev_primary: str | None = None


def log_room_test_tick(
    log: logging.Logger,
    state: RoomTestTickLogState,
    *,
    tick_seq: int,
    tick: dict,
    out: DriverTickOutcome,
    backend_output: dict,
) -> None:
    """Emit one structured ROOM_TEST line and human-readable summary."""
    primary_row = backend_output.get("primary_alert")
    primary = primary_row["alert_type"] if primary_row is not None else None
    queue = tuple(row["alert_type"] for row in backend_output.get("ordered_alerts") or [])

    curr_summary = _summarize_tick(tick)
    added = [a for a in queue if a not in state.prev_queue]
    dropped = [a for a in state.prev_queue if a not in queue]

    clearing_block = _collect_clearing_hints(state.prev_input_summary, curr_summary, dropped)

    src = tick.get("room_test_input_sources") or {}
    payload = {
        "room_test_tick": tick_seq,
        "adapter_inputs": curr_summary,
        "camera_zones": curr_summary["camera_zones"],
        "camera_zone_primary": curr_summary["camera_zone_primary"],
        "density_source": (src.get("density") or {}).get("control", "manual"),
        "can_source": (src.get("can") or {}).get("control", "manual"),
        "room_test_input_sources": src,
        "observer_validation": {
            "density_is_manual_file_authoritative": True,
            "can_is_manual_file_authoritative": True,
            "backend_does_not_auto_generate_density_or_can": bool(
                src.get("values_not_auto_generated", True)
            ),
            "demo_timeline_does_not_modify_density_or_can": not bool(
                (src.get("density") or {}).get("demo_timeline_may_modify", False)
            )
            and not bool((src.get("can") or {}).get("demo_timeline_may_modify", False)),
        },
        "alerts": {
            "primary": primary,
            "queue": list(queue),
            "added": added,
            "dropped": dropped,
            "pending": int(backend_output.get("pending_alert_count", 0)),
        },
        "outcome": {
            "kind": out.kind,
            "should_alert": getattr(out, "should_alert", None),
            "operational_alert": out.operational_alert.value if out.operational_alert else None,
        },
        "clearing": clearing_block,
        "room_test_timing": tick.get("room_test_timing"),
    }
    log.info("ROOM_TEST_JSON %s", json.dumps(payload, separators=(",", ":")))

    if added or dropped:
        log.info(
            "ROOM_TEST_ALERT_DELTA tick=%d added=%s dropped=%s hints=%s",
            tick_seq,
            added,
            dropped,
            clearing_block.get("clearing_hints", []),
        )

    state.prev_input_summary = curr_summary
    state.prev_queue = queue
    state.prev_primary = primary
