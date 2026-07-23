# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import unittest

from can_context import CANContext
from density_context import DensityContext
from room_test_context_override import (
    apply_vehicle_context_patch,
    merge_can_context,
    merge_density_context,
    reset_room_test_context_override_for_tests,
)


class TestRoomTestContextOverride(unittest.TestCase):
    def setUp(self) -> None:
        reset_room_test_context_override_for_tests()

    def tearDown(self) -> None:
        reset_room_test_context_override_for_tests()

    def test_speed_kmh_merge(self) -> None:
        apply_vehicle_context_patch({"speed_kmh": 45.0})
        base = CANContext(0.0, 0.1, 0.1, False, False, True)
        m = merge_can_context(base)
        self.assertAlmostEqual(m.speed, 0.5, places=5)
        self.assertAlmostEqual(m.braking_intensity, 0.1)

    def test_density_passengers_merge(self) -> None:
        apply_vehicle_context_patch({"passengers_onboard": 15})
        base = DensityContext(passengers_onboard=2, vehicle_capacity=50)
        m = merge_density_context(base)
        self.assertEqual(m.passengers_onboard, 15)
        self.assertEqual(m.vehicle_capacity, 50)


if __name__ == "__main__":
    unittest.main()
