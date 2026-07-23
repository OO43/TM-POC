# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import unittest
from unittest.mock import patch

from emergency import EmergencyEvent, SimulatedEmergencyInputs, resolve_simulated_emergency
from medical_slow_collapse_emergency import (
    reset_medical_slow_collapse_tracker,
    update_medical_slow_collapse_tracker,
)
from observed_cues import ObservedCues


class TestMedicalCollapseResolve(unittest.TestCase):
    def test_medical_event_priority_over_fall(self) -> None:
        inp = SimulatedEmergencyInputs(
            passenger_collapse_or_fall=True,
            medical_collapse_slow_descent=True,
        )
        ev = resolve_simulated_emergency(inp)
        self.assertEqual(ev, EmergencyEvent.MEDICAL_COLLAPSE_SLOW_DESCENT)


class TestMedicalSlowCollapseTracker(unittest.TestCase):
    def setUp(self) -> None:
        reset_medical_slow_collapse_tracker()

    def test_no_vulnerability_no_trigger(self) -> None:
        o = ObservedCues(floor_level_posture=0.58)
        self.assertFalse(update_medical_slow_collapse_tracker(o, vulnerability_confirmed=False))

    def test_gradual_descent_then_floor_dwell_triggers(self) -> None:
        """Fixed monotonic steps so persistence accumulates without real-time sleep."""
        reset_medical_slow_collapse_tracker()
        t = 0.0
        steps: list[float] = [0.0]
        for _ in range(80):
            t += 0.12
            steps.append(t)

        floor_v = 0.14
        triggered = False
        with patch(
            "medical_slow_collapse_emergency.time.monotonic",
            side_effect=iter(steps),
        ):
            for i in range(80):
                if i < 45:
                    floor_v = min(0.56, floor_v + 0.012)
                else:
                    floor_v = 0.56
                o = ObservedCues(
                    floor_level_posture=floor_v,
                    unstable_posture=0.12,
                    leaning_without_support=0.1,
                    rapid_erratic_motion=0.04,
                    repetitive_agitated_motion=0.03,
                    aggressive_motion_pattern=0.02,
                    distress_motion_pattern=0.05,
                    frequent_balance_correction=0.08,
                    prolonged_standing=0.1,
                )
                if update_medical_slow_collapse_tracker(o, vulnerability_confirmed=True):
                    triggered = True
                    break
        self.assertTrue(triggered)


if __name__ == "__main__":
    unittest.main()
