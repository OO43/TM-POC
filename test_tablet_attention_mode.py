# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import unittest

from tablet_attention_mode import attention_mode_payload_from_tick


class TestAttentionModeThresholds(unittest.TestCase):
    def test_moderate_bound(self) -> None:
        tick = {"density_context": {"passengers_onboard": 9, "vehicle_capacity": 50}}
        p = attention_mode_payload_from_tick(tick)
        self.assertEqual(p["mode_key"], "moderate")
        self.assertEqual(p["label"], "MODERATE")

    def test_busy_lower_bound(self) -> None:
        tick = {"density_context": {"passengers_onboard": 10, "vehicle_capacity": 50}}
        p = attention_mode_payload_from_tick(tick)
        self.assertEqual(p["mode_key"], "busy")
        self.assertEqual(p["label"], "BUSY")

    def test_busy_upper(self) -> None:
        tick = {"density_context": {"passengers_onboard": 19, "vehicle_capacity": 50}}
        p = attention_mode_payload_from_tick(tick)
        self.assertEqual(p["mode_key"], "busy")

    def test_crowded_lower_bound(self) -> None:
        tick = {"density_context": {"passengers_onboard": 20, "vehicle_capacity": 50}}
        p = attention_mode_payload_from_tick(tick)
        self.assertEqual(p["mode_key"], "crowded")
        self.assertEqual(p["label"], "CROWDED")


if __name__ == "__main__":
    unittest.main()
