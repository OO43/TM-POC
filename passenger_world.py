# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Keeps PassengerEntity aggregates across ticks; cameras update this world layer only.

Alerts should read entities here (via tick snapshot) combined with CAN context —
not decode raw camera payloads for policy decisions downstream.
"""

from __future__ import annotations

import os

from adapters.room_test_env import passenger_zone_continuity_gap_seconds
from cabin_topology import CabinZoneId, ZONES_WITHOUT_ACTIVE_SENSOR
from camera_observation_contract import CameraObservation
from passenger_projection import (
    PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID,
    PRIMARY_ZONE1_FOCUS_SLOT_ID,
    merge_passenger_entities_dual_visible_zone1_priority,
    merge_passenger_entities_zone2_to_zone1_transition,
    passenger_entity_from_zone1_observation,
    passenger_entity_from_zone2_observation,
    passenger_entity_to_jsonable,
)
from passenger_entity import PassengerEntity


def _presence_cue_threshold() -> float:
    raw = os.environ.get("ROOM_TEST_PRESENCE_CUE_THRESHOLD", "").strip()
    if not raw:
        return 0.08
    try:
        return max(0.01, min(0.99, float(raw)))
    except ValueError:
        return 0.08


def _presence_signal(cues) -> float:
    c = cues.clamped()
    return max(
        float(c.prolonged_standing),
        float(c.unstable_posture),
        float(c.rapid_erratic_motion),
        float(c.floor_level_posture),
        float(c.frequent_balance_correction),
        float(c.leaning_without_support),
    )


def _latest_obs_for_zone(observations: list[CameraObservation], zone: CabinZoneId) -> CameraObservation | None:
    best: CameraObservation | None = None
    for o in observations:
        if o.zone_id != zone:
            continue
        if best is None or o.captured_at_mono >= best.captured_at_mono:
            best = o
    return best


class PassengerWorld:
    __slots__ = ("_entities",)

    def __init__(self) -> None:
        self._entities: dict[str, PassengerEntity] = {}

    def update_from_observations(
        self,
        observations: list[CameraObservation],
        *,
        dual_camera_mode: bool = False,
    ) -> None:
        """
        Ingest observations from active sensors.

        Dual cameras (``dual_camera_mode=True``): continuity across Zone 2 → Zone 1 without
        biometrics — timing + cue presence only. Single-camera mode: Zone 1 last-writer as before.
        """
        if dual_camera_mode:
            self._update_dual_camera(observations)
            return

        zone1_latest: CameraObservation | None = None
        for o in observations:
            if o.zone_id in ZONES_WITHOUT_ACTIVE_SENSOR:
                continue
            if o.zone_id != CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT:
                continue
            if zone1_latest is None or o.captured_at_mono >= zone1_latest.captured_at_mono:
                zone1_latest = o
        if zone1_latest is None:
            return
        pe = passenger_entity_from_zone1_observation(
            cues=zone1_latest.cues,
            at_mono=zone1_latest.captured_at_mono,
        )
        self._entities[PRIMARY_ZONE1_FOCUS_SLOT_ID] = pe

    def _update_dual_camera(self, observations: list[CameraObservation]) -> None:
        z1_obs = _latest_obs_for_zone(observations, CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT)
        z2_obs = _latest_obs_for_zone(observations, CabinZoneId.ZONE_2_MID_CABIN)

        thr = _presence_cue_threshold()
        present1 = bool(z1_obs is not None and _presence_signal(z1_obs.cues) >= thr)
        present2 = bool(z2_obs is not None and _presence_signal(z2_obs.cues) >= thr)

        if not present1 and not present2:
            return

        slot = PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID
        prev = self._entities.get(slot)

        if present2 and not present1:
            assert z2_obs is not None
            self._entities[slot] = passenger_entity_from_zone2_observation(
                cues=z2_obs.cues,
                at_mono=z2_obs.captured_at_mono,
                passenger_id=slot,
            )
            return

        assert z1_obs is not None

        projected_z1 = passenger_entity_from_zone1_observation(
            cues=z1_obs.cues,
            at_mono=z1_obs.captured_at_mono,
            passenger_id=slot,
        )

        if present1 and not present2:
            if (
                prev is not None
                and prev.current_zone == CabinZoneId.ZONE_2_MID_CABIN
                and (projected_z1.last_seen_timestamp - prev.last_seen_timestamp)
                <= passenger_zone_continuity_gap_seconds()
            ):
                self._entities[slot] = merge_passenger_entities_zone2_to_zone1_transition(
                    previous_zone2=prev,
                    zone1_projection=projected_z1,
                )
            else:
                self._entities[slot] = projected_z1
            return

        assert z2_obs is not None
        projected_z2 = passenger_entity_from_zone2_observation(
            cues=z2_obs.cues,
            at_mono=z2_obs.captured_at_mono,
            passenger_id=slot,
        )
        mono_final = max(z1_obs.captured_at_mono, z2_obs.captured_at_mono)
        self._entities[slot] = merge_passenger_entities_dual_visible_zone1_priority(
            zone1_entity=projected_z1,
            zone2_entity=projected_z2,
            at_mono=mono_final,
        )

    def entities(self) -> dict[str, PassengerEntity]:
        return dict(self._entities)

    def snapshot_jsonable(self) -> dict:
        return {
            "entities": [passenger_entity_to_jsonable(e) for e in self._entities.values()],
            "entity_count": len(self._entities),
        }


_world: PassengerWorld | None = None


def passenger_world_singleton() -> PassengerWorld:
    global _world
    if _world is None:
        _world = PassengerWorld()
    return _world


def reset_passenger_world_for_tests() -> None:
    """Test harness: clear fused entities."""
    global _world
    _world = PassengerWorld()
