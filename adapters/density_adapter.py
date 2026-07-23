# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — occupancy / load adapter (PoC).

Later: connect to door counters, APC, or crowd-estimation services. Outputs
``DensityContext`` only.

No decision logic or capacity policy enforcement exists in this module; policy
is applied in the engine when consuming the tick dict.
"""

from __future__ import annotations

from adapters.room_test_env import read_json_object, room_test_density_state_path, room_test_enabled
from density_context import DensityContext
from room_test_context_override import merge_density_context


def _intish(x: object, default: int) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def read_density_context() -> DensityContext:
    """
    Return onboard count vs nominal capacity for one tick.

    Fake PoC: fixed counts. Room test: ``room_density_state.json`` (or env path);
    missing file → fixed nominal defaults (no ramp, no timeline).
    """
    if not room_test_enabled():
        return DensityContext(passengers_onboard=55, vehicle_capacity=50)
    obj = read_json_object(room_test_density_state_path())
    if obj is None:
        return merge_density_context(DensityContext(passengers_onboard=8, vehicle_capacity=50))
    base = DensityContext(
        passengers_onboard=max(0, _intish(obj.get("passengers_onboard"), 0)),
        vehicle_capacity=max(1, _intish(obj.get("vehicle_capacity"), 50)),
    )
    return merge_density_context(base)
