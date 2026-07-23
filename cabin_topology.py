# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Fixed logical cabin zones (explicit model; not inferred from geometry at runtime).

Zone 1 is the only zone with a live sensor in the current PoC (integrated front webcam).
Zones 2 and 3 are defined for future cameras and must remain valid, inactive states.

Note: intra-frame thirds ``door`` / ``mid`` / ``rear`` from the Zone 1 camera describe
spatial bands *within that single sensor's view*, not Logical Zone 2/3 until those cameras exist.
"""

from __future__ import annotations

from enum import IntEnum


class CabinZoneId(IntEnum):
    """Logical zones (stable IDs for APIs and persistence)."""

    ZONE_1_FRONT_ENTRY_EXIT = 1
    ZONE_2_MID_CABIN = 2
    ZONE_3_UPPER_DECK_REAR = 3


def all_cabin_zones() -> tuple[CabinZoneId, ...]:
    return (
        CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
        CabinZoneId.ZONE_2_MID_CABIN,
        CabinZoneId.ZONE_3_UPPER_DECK_REAR,
    )


# Zones that have no physical camera connected in the **default single-camera** deployment.
# When ``ROOM_TEST_DUAL_CAMERA`` is enabled at runtime, Zone 2 is active; callers use
# ``inactive_cabin_zones_for_room_test()`` in ``passenger_tick_bridge`` instead of this frozenset.
ZONES_WITHOUT_ACTIVE_SENSOR: frozenset[CabinZoneId] = frozenset(
    {
        CabinZoneId.ZONE_2_MID_CABIN,
        CabinZoneId.ZONE_3_UPPER_DECK_REAR,
    }
)

# Default camera identity strings (API / JSON); override with ROOM_TEST_DUAL_CAMERA_ID_ZONE* env.
DEFAULT_ZONE1_CAMERA_ID = "cam_zone1_integrated_front"
DEFAULT_ZONE2_CAMERA_ID = "cam_zone2_mid_cabin"
