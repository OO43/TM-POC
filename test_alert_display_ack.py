# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

from __future__ import annotations

import unittest

from alert_display_http_server import AlertDisplayPublishHub


class TestAlertDisplayAckQueue(unittest.TestCase):
    def test_consume_drains_single_request(self) -> None:
        hub = AlertDisplayPublishHub()
        self.assertFalse(hub.consume_emergency_acknowledgment_requested())
        hub.request_emergency_acknowledgment_via_http()
        self.assertTrue(hub.consume_emergency_acknowledgment_requested())
        self.assertFalse(hub.consume_emergency_acknowledgment_requested())

    def test_repost_after_consume(self) -> None:
        hub = AlertDisplayPublishHub()
        hub.request_emergency_acknowledgment_via_http()
        self.assertTrue(hub.consume_emergency_acknowledgment_requested())
        hub.request_emergency_acknowledgment_via_http()
        self.assertTrue(hub.consume_emergency_acknowledgment_requested())


if __name__ == "__main__":
    unittest.main()
