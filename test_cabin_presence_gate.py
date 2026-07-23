# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import unittest

from cabin_presence_gate import passenger_present_for_alert_path, reset_cabin_inferencers_when_no_passenger_visible
from emergency import EmergencyEvent
from thresholds import AlertType
from tick_driver_eval import evaluate_driver_tick
from vulnerability_inference import update_vulnerability_state

from observed_cues import ObservedCues


class TestPassengerPresentForAlertPath(unittest.TestCase):
    def test_no_foreground_false(self) -> None:
        tick = {"camera_perception_status": "no_foreground"}
        self.assertFalse(passenger_present_for_alert_path(tick))

    def test_explicit_true_overrides_no_foreground(self) -> None:
        tick = {"passenger_present": True, "camera_perception_status": "no_foreground"}
        self.assertTrue(passenger_present_for_alert_path(tick))

    def test_explicit_false_overrides_foreground_ok(self) -> None:
        tick = {"passenger_present": False, "camera_perception_status": "json_ok"}
        self.assertFalse(passenger_present_for_alert_path(tick))


class TestEvaluateDriverTickEmptyCabin(unittest.TestCase):
    def setUp(self) -> None:
        reset_cabin_inferencers_when_no_passenger_visible()

    def _minimal_empty_tick(self) -> dict:
        return {
            "consent_enhanced_supervision": False,
            "camera_perception_status": "no_foreground",
        }

    def test_suppresses_advisory_policy_baseline(self) -> None:
        out = evaluate_driver_tick(
            self._minimal_empty_tick(),
            emergency_sticky=None,
            cleared_by_ack=False,
        )
        self.assertEqual(out.kind, "routine")
        self.assertFalse(out.should_alert)
        self.assertFalse(out.policy_bypass)
        self.assertIsNone(out.final_winner)
        self.assertEqual(out.operational_alert, AlertType.NONE)
        self.assertFalse(out.vulnerability_advisory_active)
        self.assertFalse(out.vulnerability_confirmed)
        self.assertIsNone(out.emergency_immediate)

    def test_clears_emergency_sticky_when_no_foreground(self) -> None:
        out = evaluate_driver_tick(
            self._minimal_empty_tick(),
            emergency_sticky=EmergencyEvent.FIRE_OR_SMOKE,
            cleared_by_ack=False,
        )
        self.assertEqual(out.kind, "routine")
        self.assertIsNone(out.emergency_sticky_next)

    def test_inferencer_reset_drops_prior_vulnerability_confirmation(self) -> None:
        reset_cabin_inferencers_when_no_passenger_visible()
        cane = ObservedCues(
            navigation_aid_candidate=0.55,
            navigation_aid_in_use=0.55,
            nav_aid_floor_contact=0.82,
            nav_aid_gait_coupling=0.82,
            nav_aid_vertical_load=0.82,
            nav_aid_unilateral_bias=0.82,
        )
        snap = update_vulnerability_state(cane)
        self.assertTrue(snap.confirmed)

        empty = evaluate_driver_tick(
            self._minimal_empty_tick(),
            emergency_sticky=None,
            cleared_by_ack=False,
        )
        self.assertFalse(empty.vulnerability_confirmed)


if __name__ == "__main__":
    unittest.main()
