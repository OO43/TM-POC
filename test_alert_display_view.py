# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import unittest

from alert_display_view import alert_rows_from_backend_output, coarse_alert_type
from thresholds import AlertType


class TestCoarseAlertType(unittest.TestCase):
    def test_emergency_prefix_and_ack(self) -> None:
        self.assertEqual(coarse_alert_type("emergency_fire_or_smoke", False), "emergency")
        self.assertEqual(coarse_alert_type("instability_risk", True), "emergency")

    def test_advisory_vs_instability(self) -> None:
        self.assertEqual(
            coarse_alert_type(AlertType.VULNERABILITY_ASSISTANCE_ADVISORY.value, False),
            "advisory",
        )
        self.assertEqual(
            coarse_alert_type(AlertType.INSTABILITY_RISK.value, False),
            "instability",
        )


class TestAlertRowsFromBackendOutput(unittest.TestCase):
    def test_maps_ordered_alerts(self) -> None:
        out = {
            "ordered_alerts": [
                {
                    "alert_type": "vulnerability_assistance_advisory",
                    "priority": 24,
                    "message": "Assist text",
                    "time_raised": "2026-05-04T12:00:00Z",
                    "requires_ack": False,
                    "zone": None,
                }
            ]
        }
        rows = alert_rows_from_backend_output(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "vulnerability_assistance_advisory")
        self.assertEqual(rows[0]["alert_type"], "advisory")
        self.assertTrue(rows[0]["active"])
        self.assertFalse(rows[0]["sticky"])


if __name__ == "__main__":
    unittest.main()
