# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Camera-as-sensor contract: observations are tagged; they do not select alerts.

Each frame/tick product from a camera pipeline is wrapped with ``camera_id``,
``zone_id`` (fixed assignment for that sensor), and ``captured_at_mono``.
"""

from __future__ import annotations

from dataclasses import dataclass

from cabin_topology import CabinZoneId
from observed_cues import ObservedCues


@dataclass(frozen=True)
class CameraObservation:
    camera_id: str
    zone_id: CabinZoneId
    captured_at_mono: float
    cues: ObservedCues
    perception_lane_status: str
