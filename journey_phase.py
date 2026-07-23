# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — journey phase (PoC).

Phase is operational context from AVL/schedule/stop proximity, not passenger diagnosis.
It narrows which operational alerts are *considered* (e.g. exit prep near stops); thresholds
still decide whether an alert actually fires.
"""

from enum import Enum


class JourneyPhase(str, Enum):
    """Vehicle journey segment for supervisory routing."""

    BOARDING = "boarding"
    IN_MOTION = "in_motion"
    APPROACHING_STOP = "approaching_stop"
    END_OF_ROUTE = "end_of_route"
