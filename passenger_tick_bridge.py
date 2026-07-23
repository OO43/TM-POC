# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Glue: wrap perception cues as CameraObservation, update PassengerWorld, attach tick snapshot.

Does not overwrite ``observed_cues`` — existing backends keep current inputs until fusion phase.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any

from adapters.room_test_env import room_test_dual_camera_enabled
from cabin_topology import DEFAULT_ZONE1_CAMERA_ID, CabinZoneId, ZONES_WITHOUT_ACTIVE_SENSOR, all_cabin_zones
from camera_observation_contract import CameraObservation
from passenger_projection import (
    MULTI_PASSENGER_RESERVE_IDS,
    PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID,
)
from passenger_world import passenger_world_singleton
from observed_cues import ObservedCues
from vehicle_passenger_safety_candidates import (
    derive_safety_candidates,
    safety_candidates_to_jsonable,
    vehicle_context_from_can_map,
)


def inactive_cabin_zones_for_room_test() -> frozenset[CabinZoneId]:
    """Logical Zone 3 stays inactive; Zone 2 becomes active when dual-camera ROOM_TEST is enabled."""
    if room_test_dual_camera_enabled():
        return frozenset({CabinZoneId.ZONE_3_UPPER_DECK_REAR})
    return ZONES_WITHOUT_ACTIVE_SENSOR


def _zone1_camera_id() -> str:
    raw = os.environ.get("TRAVELMATE_FRONT_CAMERA_ID", "").strip()
    if raw:
        return raw
    raw_dual = os.environ.get("ROOM_TEST_DUAL_CAMERA_ID_ZONE1", "").strip()
    return raw_dual if raw_dual else DEFAULT_ZONE1_CAMERA_ID


def _zone1_single_camera_fallback_id() -> str:
    return _zone1_camera_id()


def attach_cabin_architecture_to_tick(
    tick: dict[str, Any],
    *,
    cues: ObservedCues,
    camera_perception_status: str,
    dual_observation_rows: list[tuple[str, CabinZoneId, float, ObservedCues, str]] | None = None,
) -> None:
    """Augment adapter tick dict with explicit topology / passengers / contextual candidates."""
    inactive_set = inactive_cabin_zones_for_room_test()

    if dual_observation_rows:
        observations = [
            CameraObservation(
                camera_id=cid,
                zone_id=zone,
                captured_at_mono=mono_snap,
                cues=cue_s,
                perception_lane_status=str(stat or ""),
            )
            for cid, zone, mono_snap, cue_s, stat in dual_observation_rows
        ]
    else:
        mono = time.monotonic()
        observations = [
            CameraObservation(
                camera_id=_zone1_single_camera_fallback_id(),
                zone_id=CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
                captured_at_mono=mono,
                cues=cues,
                perception_lane_status=str(camera_perception_status or ""),
            )
        ]

    world = passenger_world_singleton()
    world.update_from_observations(
        observations,
        dual_camera_mode=dual_observation_rows is not None,
    )

    ents = world.entities()
    vc = vehicle_context_from_can_map(tick.get("can") or {})
    cands = derive_safety_candidates(ents, vc)

    inactive = sorted(int(z.value) for z in inactive_set)

    snap = world.snapshot_jsonable()
    snap["reserved_multi_passenger_slot_ids"] = list(MULTI_PASSENGER_RESERVE_IDS)
    if room_test_dual_camera_enabled():
        snap["cross_zone_tracked_slot_id"] = PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID

    arch_note = (
        "zone_3_declared_inactive; zone_1_and_2_active_under_ROOM_TEST_DUAL_CAMERA"
        if room_test_dual_camera_enabled()
        else "zone_2_and_3_defined_inactive_by_design_until_cameras_installed"
    )

    tick["cabin_topology"] = {
        "zones": [
            {
                "zone_id": int(z.value),
                "active_sensor": z not in inactive_set,
            }
            for z in all_cabin_zones()
        ],
        "zones_without_live_sensor_now": inactive,
        "architecture_note": arch_note,
    }
    tick["camera_observations"] = [
        {
            "camera_id": o.camera_id,
            "zone_id": int(o.zone_id.value),
            "captured_at_mono": o.captured_at_mono,
            "perception_lane_status": o.perception_lane_status,
            "cues_preview_keys": list(asdict(o.cues).keys()),
        }
        for o in observations
    ]
    tick["passenger_world"] = snap
    tick["passenger_safety_candidates"] = safety_candidates_to_jsonable(cands)
