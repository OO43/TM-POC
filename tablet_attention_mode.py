# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Tablet / HMI Attention band derived from onboard count in the runtime tick.

Deterministic thresholds (informational only — does not gate alerts):

- passengers_onboard < 10 → MODERATE
- 10 ≤ passengers_onboard < 20 → BUSY
- passengers_onboard ≥ 20 → CROWDED
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

AttentionModeKey = Literal["moderate", "busy", "crowded"]


def attention_mode_payload_from_passengers_onboard(
    passengers_onboard: int,
    *,
    vehicle_capacity: int,
) -> dict[str, Any]:
    """
    Returns JSON-serializable attention section for tablet UI bundles.

    All fields are informational; alerting remains in ``evaluate_driver_tick``.
    """
    n = max(0, int(passengers_onboard))
    cap = max(0, int(vehicle_capacity))

    if n < 10:
        mode_key: AttentionModeKey = "moderate"
        label = "MODERATE"
        meaning = "Typical load — baseline awareness (information only)."
        accent = "calm_secondary_neutral_green_blue"
    elif n < 20:
        mode_key = "busy"
        label = "BUSY"
        meaning = "More activity onboard — sustained awareness (information only)."
        accent = "calm_secondary_amber_static"
    else:
        mode_key = "crowded"
        label = "CROWDED"
        meaning = "High density cabin — readiness for slower reactions (information only)."
        accent = "calm_secondary_soft_red_optional_pulse"

    return {
        "mode_key": mode_key,
        "label": label,
        "meaning_short": meaning,
        "accent": accent,
        "passengers_onboard": n,
        "vehicle_capacity": cap,
        "source": "runtime_tick_density_context_passengers_onboard",
        "rules_reference": (
            "Server-only tiers: onboard<10 MODERATE; 10≤onboard<20 BUSY; onboard≥20 CROWDED. "
            "Not an alert tier; UI renders server labels."
        ),
    }


def attention_mode_payload_from_tick(tick: Mapping[str, Any]) -> dict[str, Any]:
    dc = tick.get("density_context") or {}
    try:
        onboard = int(dc.get("passengers_onboard", 0))
    except (TypeError, ValueError):
        onboard = 0
    try:
        cap = int(dc.get("vehicle_capacity", 0))
    except (TypeError, ValueError):
        cap = 0
    return attention_mode_payload_from_passengers_onboard(
        onboard, vehicle_capacity=cap
    )


def vehicle_panel_payload_from_tick(tick: Mapping[str, Any]) -> dict[str, Any]:
    cm = tick.get("can") or {}
    speed_kmh = float(cm.get("speed_kmh", 0.0))
    return {
        "speed": float(cm.get("speed", 0.0)),
        "speed_kmh": speed_kmh,
        "braking_intensity": float(cm.get("braking_intensity", 0.0)),
        "turn_intensity": float(cm.get("turn_intensity", 0.0)),
        "doors_open": bool(cm.get("doors_open", False)),
        "ramp_deployed": bool(cm.get("ramp_deployed", False)),
        "vehicle_stationary": bool(cm.get("vehicle_stationary", False)),
        "source": "runtime_tick_can_map",
        "display_note": "Mirrored CAN fields · glance only.",
    }


def tertiary_panel_payload_from_tick(tick: Mapping[str, Any]) -> dict[str, Any]:
    de = tick.get("driver_event") or {}
    can_ok = bool(tick.get("room_test_can_bus_connected", True))
    return {
        "can_bus_ui_label": "CAN Bus",
        "can_bus_connected": can_ok,
        "can_bus_status": "connected" if can_ok else "disconnected",
        "diversion_active": bool(de.get("diversion_active", False)),
        "diversion_control_note": "Diversion routing — desktop / OPS (placeholder).",
    }
