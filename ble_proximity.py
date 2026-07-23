# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — optional BLE zone hint (PoC).

BLE proximity is **optional** and **consent-gated** in a full system. Here it only
carries an approximate **vehicle zone** and confidence — no identity, no tracking
trajectories, no MAC addresses in logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VehicleZone(str, Enum):
    FRONT_DOOR = "front_door"
    AISLE = "aisle"
    WHEELCHAIR_BAY = "wheelchair_bay"
    STAIRS = "stairs"
    UPPER_DECK = "upper_deck"
    REAR = "rear"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BLEProximityContext:
    enabled: bool
    zone: VehicleZone
    confidence: float  # [0, 1]
