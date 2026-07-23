# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — CAN / vehicle bus adapter (PoC).

Later: connect to decoded OBD-II, J1939, or OEM CAN frames (wheel speed, brake
pressure, steering/yaw, door switches, ramp ECU). Outputs ``CANContext`` only.

No decision logic, risk scoring, or alerting exists in this module.
"""

from __future__ import annotations

from adapters.room_test_env import read_json_object, room_test_can_json_path, room_test_enabled
from can_context import CANContext
from room_test_context_override import merge_can_context


def _boolish(x: object, default: bool = False) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        return x.strip().lower() in ("1", "true", "yes", "on")
    return default


def _floatish(x: object, default: float) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def read_can_context() -> CANContext:
    """
    Return the current vehicle snapshot for one evaluation tick.

    Fake PoC: deterministic normalized values. Room test: ``room_can_state.json``
    (or ``ROOM_TEST_CAN_JSON``); missing file → stationary, low motion. Values
    change only when the file is edited or merged via ``room_test_set_can.py``.
    """
    if not room_test_enabled():
        return CANContext(
            speed=0.6,
            braking_intensity=0.4,
            turn_intensity=0.15,
            doors_open=False,
            ramp_deployed=False,
            vehicle_stationary=False,
        )
    obj = read_json_object(room_test_can_json_path())
    if obj is None:
        return merge_can_context(
            CANContext(
                speed=0.0,
                braking_intensity=0.0,
                turn_intensity=0.0,
                doors_open=False,
                ramp_deployed=False,
                vehicle_stationary=True,
            )
        )
    base = CANContext(
        speed=_floatish(obj.get("speed"), 0.0),
        braking_intensity=_floatish(obj.get("braking_intensity"), 0.0),
        turn_intensity=_floatish(obj.get("turn_intensity"), 0.0),
        doors_open=_boolish(obj.get("doors_open"), False),
        ramp_deployed=_boolish(obj.get("ramp_deployed"), False),
        vehicle_stationary=_boolish(obj.get("vehicle_stationary"), True),
    )
    return merge_can_context(base)
