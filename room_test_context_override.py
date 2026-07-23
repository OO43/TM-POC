# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
ROOM_TEST-only mutable overrides merged after JSON file adapters.

Production / non–ROOM_TEST: this module is never consulted by adapters.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any

from can_context import CANContext
from density_context import DensityContext
from room_test_sim_limits import (
    MAX_BRAKING_INTENSITY,
    MAX_REALISTIC_SPEED_KMH,
    MAX_TURN_INTENSITY,
    clamp01,
    speed_kmh_to_normalized,
)

_LOG = logging.getLogger(__name__)

_lock = threading.Lock()
_override: dict[str, Any] = {}

_ALLOWED_CAN_DENSITY = frozenset(
    {
        "speed_kmh",
        "braking_intensity",
        "turn_intensity",
        "vehicle_stationary",
        "doors_open",
        "ramp_deployed",
        "passengers_onboard",
        "vehicle_capacity",
        "can_bus_connected",
    }
)


def reset_room_test_context_override_for_tests() -> None:
    with _lock:
        _override.clear()


def snapshot_override() -> dict[str, Any]:
    with _lock:
        return dict(_override)


def apply_vehicle_context_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """
    Merge allowed keys into the override store. Returns the full override snapshot.

    Logs each application at INFO (audit for simulation).
    """
    if not isinstance(patch, dict):
        raise TypeError("patch must be a dict")
    applied: dict[str, Any] = {}
    with _lock:
        for k, v in patch.items():
            if k not in _ALLOWED_CAN_DENSITY:
                continue
            if k in ("vehicle_stationary", "doors_open", "ramp_deployed", "can_bus_connected"):
                _override[k] = bool(v)
            elif k == "speed_kmh":
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                _override[k] = max(0.0, min(fv, MAX_REALISTIC_SPEED_KMH))
            elif k in ("braking_intensity", "turn_intensity"):
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                _override[k] = max(0.0, fv)
            elif k == "passengers_onboard":
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                _override[k] = max(0, iv)
            elif k == "vehicle_capacity":
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                _override[k] = max(1, iv)
            applied[k] = _override[k]
        snap = dict(_override)
    if applied:
        _LOG.info(
            "ROOM_TEST vehicle context override applied keys=%s (full_override=%s)",
            sorted(applied.keys()),
            snap,
        )
    return snap


def merge_can_context(base: CANContext) -> CANContext:
    with _lock:
        o = dict(_override)
    if not o:
        return base
    speed = base.speed
    if "speed_kmh" in o:
        speed = speed_kmh_to_normalized(float(o["speed_kmh"]))
    braking = clamp01(float(o["braking_intensity"])) if "braking_intensity" in o else base.braking_intensity
    turn = clamp01(float(o["turn_intensity"])) if "turn_intensity" in o else base.turn_intensity
    stationary = bool(o["vehicle_stationary"]) if "vehicle_stationary" in o else base.vehicle_stationary
    doors = bool(o["doors_open"]) if "doors_open" in o else base.doors_open
    ramp = bool(o["ramp_deployed"]) if "ramp_deployed" in o else base.ramp_deployed
    return CANContext(
        speed=clamp01(speed),
        braking_intensity=braking,
        turn_intensity=turn,
        doors_open=doors,
        ramp_deployed=ramp,
        vehicle_stationary=stationary,
    )


def merge_density_context(base: DensityContext) -> DensityContext:
    with _lock:
        o = dict(_override)
    if not o:
        return base
    pax = base.passengers_onboard
    cap = base.vehicle_capacity
    if "passengers_onboard" in o:
        pax = max(0, int(o["passengers_onboard"]))
    if "vehicle_capacity" in o:
        cap = max(1, int(o["vehicle_capacity"]))
    return DensityContext(passengers_onboard=pax, vehicle_capacity=cap)


def can_bus_connected_effective() -> bool:
    """Default connected when unset."""
    with _lock:
        if "can_bus_connected" not in _override:
            return True
        return bool(_override["can_bus_connected"])


def room_test_control_bundle_for_tablet(tick: Mapping[str, Any]) -> dict[str, Any]:
    """
    Read-only snapshot for tablet test panel (limits + effective tick values + override keys).

    Alerting is unaffected; this is for ROOM_TEST UI sync only.
    """
    cm = tick.get("can") or {}
    dc = tick.get("density_context") or {}
    try:
        pax = int(dc.get("passengers_onboard", 0))
    except (TypeError, ValueError):
        pax = 0
    try:
        cap = int(dc.get("vehicle_capacity", 50))
    except (TypeError, ValueError):
        cap = 50
    return {
        "active": True,
        "limits": {
            "speed_kmh_max": MAX_REALISTIC_SPEED_KMH,
            "braking_intensity_max": MAX_BRAKING_INTENSITY,
            "turn_intensity_max": MAX_TURN_INTENSITY,
        },
        "effective": {
            "speed_kmh": float(cm.get("speed_kmh", 0.0)),
            "braking_intensity": float(cm.get("braking_intensity", 0.0)),
            "turn_intensity": float(cm.get("turn_intensity", 0.0)),
            "vehicle_stationary": bool(cm.get("vehicle_stationary", False)),
            "doors_open": bool(cm.get("doors_open", False)),
            "ramp_deployed": bool(cm.get("ramp_deployed", False)),
            "passengers_onboard": pax,
            "vehicle_capacity": max(1, cap),
            "can_bus_connected": bool(tick.get("room_test_can_bus_connected", True)),
        },
        "override_snapshot": snapshot_override(),
    }
