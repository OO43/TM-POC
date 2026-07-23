# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Passenger-centric abstraction: evaluated over time and zones without identity recognition.

Values are synthesized from fused sensor evidence (timing + cue continuity).
``passenger_id`` is an anonymous slot identifier, not biometric identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cabin_topology import CabinZoneId


class PassengerMobilityType(str, Enum):
    NONE = "none"
    CANE = "cane"
    WALKER = "walker"
    WHEELCHAIR = "wheelchair"


class PassengerPostureState(str, Enum):
    UNKNOWN = "unknown"
    STANDING = "standing"
    SEATED = "seated"
    FLOOR_LEVEL = "floor_level"


class PassengerIntent(str, Enum):
    UNKNOWN = "unknown"
    IDLE = "idle"
    MOVING = "moving"
    EXITING = "exiting"


class PassengerVulnerabilityStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_VULNERABLE = "not_vulnerable"
    ASSIST_CONTEXT_ELEVATED = "assist_context_elevated"


@dataclass
class PassengerEntity:
    passenger_id: str
    current_zone: CabinZoneId
    vulnerability_status: PassengerVulnerabilityStatus
    mobility_type: PassengerMobilityType
    posture_state: PassengerPostureState
    intent: PassengerIntent
    last_seen_timestamp: float
    provenance_notes: tuple[str, ...] = field(default_factory=tuple)
    #: Anonymous risk / continuity breadcrumbs (no biometrics).
    risk_history: tuple[str, ...] = field(default_factory=tuple)
