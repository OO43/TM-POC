# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cabin_topology import CabinZoneId, ZONES_WITHOUT_ACTIVE_SENSOR, all_cabin_zones
from camera_observation_contract import CameraObservation
from observed_cues import ObservedCues
from passenger_entity import (
    PassengerIntent,
    PassengerMobilityType,
    PassengerPostureState,
    PassengerVulnerabilityStatus,
)
from passenger_projection import (
    PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID,
    passenger_entity_from_zone1_observation,
)
from passenger_world import passenger_world_singleton, reset_passenger_world_for_tests
from passenger_tick_bridge import attach_cabin_architecture_to_tick, inactive_cabin_zones_for_room_test
from vehicle_passenger_safety_candidates import VehicleOperationContext, derive_safety_candidates


class TestCabinTopology(unittest.TestCase):
    def test_three_fixed_zones(self) -> None:
        self.assertEqual(len(all_cabin_zones()), 3)
        self.assertIn(CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT, all_cabin_zones())
        self.assertIn(CabinZoneId.ZONE_2_MID_CABIN, ZONES_WITHOUT_ACTIVE_SENSOR)
        self.assertIn(CabinZoneId.ZONE_3_UPPER_DECK_REAR, ZONES_WITHOUT_ACTIVE_SENSOR)


class TestTickBridge(unittest.TestCase):
    def setUp(self) -> None:
        reset_passenger_world_for_tests()

    def test_attach_adds_topology_and_passengers(self) -> None:
        tick: dict = {
            "observed_cues": {},
            "camera_perception_status": "json_ok",
            "can": {
                "speed": 0.0,
                "braking_intensity": 0.0,
                "turn_intensity": 0.0,
                "doors_open": False,
                "ramp_deployed": False,
                "vehicle_stationary": True,
            },
        }
        cues = ObservedCues(navigation_aid_in_use=0.55, near_door_area=0.6, unstable_posture=0.25)
        attach_cabin_architecture_to_tick(tick, cues=cues, camera_perception_status="json_ok")
        self.assertIn("cabin_topology", tick)
        self.assertEqual(len(tick["cabin_topology"]["zones"]), 3)
        self.assertIn("passenger_world", tick)
        self.assertGreaterEqual(tick["passenger_world"]["entity_count"], 1)


class TestProjectionExitIntent(unittest.TestCase):
    def test_zone1_exit_bias(self) -> None:
        cues = ObservedCues(
            navigation_aid_in_use=0.2,
            near_door_area=0.72,
            unstable_posture=0.2,
            prolonged_standing=0.35,
        )
        pe = passenger_entity_from_zone1_observation(cues=cues, at_mono=1.0)
        self.assertEqual(pe.current_zone, CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT)
        self.assertEqual(pe.intent, PassengerIntent.EXITING)


class TestDualCameraPassengerContinuity(unittest.TestCase):
    """Logic validation: anonymous continuity Zone 2 → Zone 1 (no biometrics)."""

    def setUp(self) -> None:
        reset_passenger_world_for_tests()

    def test_dual_mode_topology_only_zone3_inactive(self) -> None:
        with patch.dict(os.environ, {"ROOM_TEST": "1", "ROOM_TEST_DUAL_CAMERA": "1"}):
            inactive = inactive_cabin_zones_for_room_test()
            self.assertNotIn(CabinZoneId.ZONE_2_MID_CABIN, inactive)
            self.assertIn(CabinZoneId.ZONE_3_UPPER_DECK_REAR, inactive)

    def test_zone2_only_tracked_slot(self) -> None:
        world = passenger_world_singleton()
        cues2 = ObservedCues(
            prolonged_standing=0.4,
            unstable_posture=0.25,
            navigation_aid_in_use=0.5,
        )
        obs2 = CameraObservation(
            camera_id="2",
            zone_id=CabinZoneId.ZONE_2_MID_CABIN,
            captured_at_mono=100.0,
            cues=cues2,
            perception_lane_status="ok",
        )
        world.update_from_observations([obs2], dual_camera_mode=True)
        ent = world.entities()[PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID]
        self.assertEqual(ent.current_zone, CabinZoneId.ZONE_2_MID_CABIN)
        self.assertEqual(ent.vulnerability_status, PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED)

    def test_zone2_then_zone1_same_entity_slot_preserves_context(self) -> None:
        world = passenger_world_singleton()
        cues2 = ObservedCues(
            prolonged_standing=0.4,
            unstable_posture=0.25,
            navigation_aid_in_use=0.5,
        )
        obs2 = CameraObservation(
            camera_id="2",
            zone_id=CabinZoneId.ZONE_2_MID_CABIN,
            captured_at_mono=100.0,
            cues=cues2,
            perception_lane_status="ok",
        )
        world.update_from_observations([obs2], dual_camera_mode=True)

        cues1 = ObservedCues(
            near_door_area=0.62,
            prolonged_standing=0.34,
            unstable_posture=0.15,
            navigation_aid_in_use=0.5,
        )
        obs1 = CameraObservation(
            camera_id="1",
            zone_id=CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
            captured_at_mono=101.0,
            cues=cues1,
            perception_lane_status="ok",
        )
        world.update_from_observations([obs1], dual_camera_mode=True)
        ent = world.entities()[PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID]
        self.assertEqual(ent.current_zone, CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT)
        self.assertEqual(ent.vulnerability_status, PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED)
        self.assertEqual(ent.mobility_type, PassengerMobilityType.CANE)
        self.assertIn("continuity:z2_to_z1", ent.risk_history)


class TestSafetyCandidates(unittest.TestCase):
    def test_wheelchair_ramp_candidate(self) -> None:
        from passenger_entity import PassengerEntity, PassengerVulnerabilityStatus

        pe = PassengerEntity(
            passenger_id="t",
            current_zone=CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
            vulnerability_status=PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED,
            mobility_type=PassengerMobilityType.WHEELCHAIR,
            posture_state=PassengerPostureState.STANDING,
            intent=PassengerIntent.EXITING,
            last_seen_timestamp=1.0,
        )
        vc = VehicleOperationContext(
            speed=0.0,
            vehicle_stationary=True,
            doors_open=True,
            ramp_deployed=False,
        )
        cands = derive_safety_candidates({"t": pe}, vc)
        kinds = [c.kind for c in cands]
        self.assertIn("wheelchair_exit_ramp_required", kinds)

    def test_mid_zone_smooth_when_moving(self) -> None:
        from passenger_entity import PassengerEntity, PassengerVulnerabilityStatus

        pe = PassengerEntity(
            passenger_id="mid",
            current_zone=CabinZoneId.ZONE_2_MID_CABIN,
            vulnerability_status=PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED,
            mobility_type=PassengerMobilityType.NONE,
            posture_state=PassengerPostureState.STANDING,
            intent=PassengerIntent.MOVING,
            last_seen_timestamp=1.0,
        )
        vc = VehicleOperationContext(
            speed=0.6,
            vehicle_stationary=False,
            doors_open=False,
            ramp_deployed=False,
        )
        cands = derive_safety_candidates({"mid": pe}, vc)
        kinds = [c.kind for c in cands]
        self.assertIn("unstable_or_assist_mid_or_upper_zone_while_moving", kinds)


if __name__ == "__main__":
    unittest.main()
