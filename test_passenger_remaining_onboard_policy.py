# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import unittest
from dataclasses import asdict

from cabin_presence_gate import reset_cabin_inferencers_when_no_passenger_visible
from observed_cues import ObservedCues
from passenger_remaining_onboard_policy import (
    human_presence_signal,
    remaining_onboard_advisory_eligible,
    reset_passenger_remaining_onboard_ack_state,
    stationary_zero_density_count,
)
from thresholds import AlertType, SupportCategory
from tick_driver_eval import evaluate_driver_tick
from can_context import CANContext
from density_context import DensityContext


def _stationary_can() -> dict:
    return {
        "speed": 0.0,
        "braking_intensity": 0.0,
        "turn_intensity": 0.0,
        "doors_open": False,
        "ramp_deployed": False,
        "vehicle_stationary": True,
    }


def _baseline_tick(**overrides: object) -> dict:
    o = asdict(ObservedCues())
    tick: dict = {
        "consent_enhanced_supervision": False,
        "support_categories": [SupportCategory.UNDECLARED.value],
        "camera_perception_status": "json_ok",
        "observed_cues": o,
        "density_context": {"passengers_onboard": 0, "vehicle_capacity": 40},
        "can": _stationary_can(),
        "passenger_event": {"stop_request": False, "source": "app", "consented": False},
        "driver_event": {"diversion_active": False},
        "emergency": {
            "passenger_collapse_or_fall": False,
            "medical_collapse_slow_descent": False,
            "fire_or_smoke": False,
            "altercation": False,
            "severe_distress": False,
        },
    }
    tick.update(overrides)  # type: ignore[arg-type]
    return tick


class TestPassengerRemainingPolicyHelpers(unittest.TestCase):
    def test_stationary_zero_density(self) -> None:
        can = CANContext(
            speed=0.0,
            braking_intensity=0.0,
            turn_intensity=0.0,
            doors_open=False,
            ramp_deployed=False,
            vehicle_stationary=True,
        )
        d0 = DensityContext(passengers_onboard=0, vehicle_capacity=40)
        self.assertTrue(stationary_zero_density_count(can, d0))
        self.assertFalse(
            stationary_zero_density_count(
                can,
                DensityContext(passengers_onboard=1, vehicle_capacity=40),
            )
        )

    def test_human_presence_explicit_false(self) -> None:
        self.assertFalse(
            human_presence_signal({"passenger_present": False}, None),
        )

    def test_human_presence_json_ok(self) -> None:
        self.assertTrue(human_presence_signal({"camera_perception_status": "json_ok"}, None))


class TestPassengerRemainingEligibility(unittest.TestCase):
    def test_suppressed_when_exit_advisory_flags(self) -> None:
        reset_passenger_remaining_onboard_ack_state()
        can = CANContext(0.0, 0.0, 0.0, False, False, True)
        d0 = DensityContext(0, 40)
        self.assertFalse(
            remaining_onboard_advisory_eligible(
                {"camera_perception_status": "json_ok"},
                None,
                can_context=can,
                density_ctx=d0,
                exit_advisory=True,
                vuln_advisory=False,
                final_winner_classic=None,
                policy_candidates=[],
                should_alert_classic=False,
            )
        )


class TestEvaluateDriverTickPassengerRemaining(unittest.TestCase):
    def setUp(self) -> None:
        reset_cabin_inferencers_when_no_passenger_visible()
        reset_passenger_remaining_onboard_ack_state()

    def test_fires_when_stationary_zero_density_and_foreground(self) -> None:
        out = evaluate_driver_tick(
            _baseline_tick(),
            emergency_sticky=None,
            cleared_by_ack=False,
        )
        self.assertTrue(out.should_alert)
        self.assertEqual(out.final_winner, AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY)
        self.assertIn(
            AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY,
            out.passing_operational_types,
        )

    def test_cleared_when_vehicle_moves(self) -> None:
        out = evaluate_driver_tick(
            _baseline_tick(
                can={
                    "speed": 5.0,
                    "braking_intensity": 0.0,
                    "turn_intensity": 0.0,
                    "doors_open": False,
                    "ramp_deployed": False,
                    "vehicle_stationary": False,
                },
            ),
            emergency_sticky=None,
            cleared_by_ack=False,
        )
        self.assertNotEqual(out.final_winner, AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY)

    def test_cleared_when_density_positive(self) -> None:
        out = evaluate_driver_tick(
            _baseline_tick(
                density_context={"passengers_onboard": 2, "vehicle_capacity": 40},
            ),
            emergency_sticky=None,
            cleared_by_ack=False,
        )
        self.assertNotEqual(out.final_winner, AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY)

    def test_suppressed_when_higher_priority_system_support_wins(self) -> None:
        out = evaluate_driver_tick(
            _baseline_tick(system_faults={"audio_fault": True}),
            emergency_sticky=None,
            cleared_by_ack=False,
        )
        self.assertNotEqual(out.final_winner, AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY)

    def test_ack_suppresses_until_base_clears(self) -> None:
        t1 = _baseline_tick()
        first = evaluate_driver_tick(t1, emergency_sticky=None, cleared_by_ack=False)
        self.assertEqual(first.final_winner, AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY)

        t2 = _baseline_tick(driver_ack_passenger_remaining_onboard=True)
        second = evaluate_driver_tick(t2, emergency_sticky=None, cleared_by_ack=False)
        self.assertIsNone(second.final_winner)

        t3 = _baseline_tick()
        third = evaluate_driver_tick(t3, emergency_sticky=None, cleared_by_ack=False)
        self.assertIsNone(third.final_winner)

        t4 = _baseline_tick(
            can={
                "speed": 1.0,
                "braking_intensity": 0.0,
                "turn_intensity": 0.0,
                "doors_open": False,
                "ramp_deployed": False,
                "vehicle_stationary": False,
            },
        )
        evaluate_driver_tick(t4, emergency_sticky=None, cleared_by_ack=False)

        t5 = _baseline_tick()
        fifth = evaluate_driver_tick(t5, emergency_sticky=None, cleared_by_ack=False)
        self.assertEqual(fifth.final_winner, AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY)


if __name__ == "__main__":
    unittest.main()
