# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — emergency event classification (PoC).

Emergency items name observable safety situations only. They are not medical
diagnoses and do not identify individuals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EmergencyEvent(str, Enum):
    """Simulated emergency classes from observable cues (non-biometric, non-diagnostic)."""

    PASSENGER_COLLAPSE_OR_FALL = "passenger_collapse_or_fall"
    FIRE_OR_SMOKE = "fire_or_smoke"
    MEDICAL_COLLAPSE_SLOW_DESCENT = "medical_collapse_slow_descent"
    ALTERCATION = "altercation"
    SEVERE_DISTRESS = "severe_distress"


@dataclass(frozen=True)
class SimulatedEmergencyInputs:
    """
    PoC stand-in for upstream detectors (no cameras/ML here).
    Each flag means: an observable cue for that situation is present.
    """

    passenger_collapse_or_fall: bool = False
    fire_or_smoke: bool = False
    medical_collapse_slow_descent: bool = False
    altercation: bool = False
    severe_distress: bool = False


# If multiple flags are true, pick one deterministically (PoC only).
_EMERGENCY_PRIORITY: tuple[EmergencyEvent, ...] = (
    EmergencyEvent.FIRE_OR_SMOKE,
    EmergencyEvent.MEDICAL_COLLAPSE_SLOW_DESCENT,
    EmergencyEvent.PASSENGER_COLLAPSE_OR_FALL,
    EmergencyEvent.ALTERCATION,
    EmergencyEvent.SEVERE_DISTRESS,
)

_EVENT_TO_FIELD: dict[EmergencyEvent, str] = {
    EmergencyEvent.PASSENGER_COLLAPSE_OR_FALL: "passenger_collapse_or_fall",
    EmergencyEvent.FIRE_OR_SMOKE: "fire_or_smoke",
    EmergencyEvent.MEDICAL_COLLAPSE_SLOW_DESCENT: "medical_collapse_slow_descent",
    EmergencyEvent.ALTERCATION: "altercation",
    EmergencyEvent.SEVERE_DISTRESS: "severe_distress",
}


def resolve_simulated_emergency(inputs: SimulatedEmergencyInputs) -> EmergencyEvent | None:
    """Return the active emergency for this tick, or None. Does not use risk scores."""
    for event in _EMERGENCY_PRIORITY:
        if getattr(inputs, _EVENT_TO_FIELD[event]):
            return event
    return None
