# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — operational alert selection from observable context (PoC).

Legacy path: behaviour + motion + density + consent + journey phase (no detailed cues).
See scenario_classification.py for unified cue-based selection.
"""

from __future__ import annotations

from journey_phase import JourneyPhase
from scenario_classification import highest_priority_alert
from thresholds import AlertType, SupportCategory


def _highest_priority(candidates: list[AlertType]) -> AlertType | None:
    return highest_priority_alert(candidates)


def resolve_support_for_thresholds(
    support_categories: set[SupportCategory],
    alert: AlertType,
) -> SupportCategory:
    """Single support row for threshold lookup when multiple consent flags may be declared."""
    if alert in (
        AlertType.PASSENGER_STOP_REQUEST,
        AlertType.ROUTE_DIVERSION_ACTIVE,
    ):
        return SupportCategory.UNDECLARED
    cleaned = {c for c in support_categories if c is not SupportCategory.UNDECLARED}
    if not cleaned:
        return SupportCategory.UNDECLARED
    if alert is AlertType.EXIT_PREPARATION and SupportCategory.VISUAL_IMPAIRMENT in cleaned:
        return SupportCategory.VISUAL_IMPAIRMENT
    if alert in (
        AlertType.WHEELCHAIR_BAY_OBSTRUCTION,
        AlertType.WHEELCHAIR_UNSAFE_POSITION,
        AlertType.WHEELCHAIR_UNSTABLE_IN_BAY,
    ) and SupportCategory.WHEELCHAIR in cleaned:
        return SupportCategory.WHEELCHAIR
    if alert in (AlertType.PUSHCHAIR_INSTABILITY, AlertType.PUSHCHAIR_UNSAFE_POSITION) and (
        SupportCategory.PUSHCHAIR in cleaned
    ):
        return SupportCategory.PUSHCHAIR
    if alert is AlertType.CHILD_HIGH_MOVEMENT and SupportCategory.CHILD_SUPPORT in cleaned:
        return SupportCategory.CHILD_SUPPORT
    if alert is AlertType.BLOCKED_EXIT_VULNERABLE:
        for c in (
            SupportCategory.MOBILITY_SUPPORT,
            SupportCategory.MEDICAL_SENSITIVITY,
            SupportCategory.PREGNANCY_SUPPORT,
            SupportCategory.ELDERLY_SUPPORT,
            SupportCategory.VISUAL_IMPAIRMENT,
            SupportCategory.NEURODIVERSITY_SUPPORT,
        ):
            if c in cleaned:
                return c
    if alert is AlertType.SEAT_ASSISTANCE_REQUIRED:
        for c in (
            SupportCategory.MOBILITY_SUPPORT,
            SupportCategory.MEDICAL_SENSITIVITY,
            SupportCategory.PREGNANCY_SUPPORT,
            SupportCategory.ELDERLY_SUPPORT,
        ):
            if c in cleaned:
                return c
    return min(cleaned, key=lambda c: c.value)


def select_operational_alert_type(
    behaviour: float,
    motion: float,
    density: float,
    support_categories: set[SupportCategory],
    journey_phase: JourneyPhase,
) -> AlertType | None:
    """
    Pure selection: no risk score, no thresholds.
    Legacy coarse inputs (no ObservedCues struct).
    """
    sup = support_categories
    c: list[AlertType] = []

    if journey_phase is JourneyPhase.END_OF_ROUTE:
        if behaviour >= 0.32 or density >= 0.42:
            c.append(AlertType.JOURNEY_END_CHECK)

    if journey_phase is JourneyPhase.APPROACHING_STOP and SupportCategory.VISUAL_IMPAIRMENT in sup:
        if density >= 0.35 or behaviour >= 0.28:
            c.append(AlertType.EXIT_PREPARATION)

    if SupportCategory.WHEELCHAIR in sup:
        if density >= 0.48 and motion >= 0.38:
            c.append(AlertType.WHEELCHAIR_BAY_OBSTRUCTION)

    if SupportCategory.PUSHCHAIR in sup:
        if motion >= 0.46 and behaviour >= 0.36:
            c.append(AlertType.PUSHCHAIR_INSTABILITY)

    if journey_phase in (JourneyPhase.IN_MOTION, JourneyPhase.APPROACHING_STOP):
        if motion >= 0.52 and behaviour >= 0.42:
            c.append(AlertType.STANDING_MOTION_RISK)

    if behaviour >= 0.48 and motion >= 0.44:
        c.append(AlertType.INSTABILITY_RISK)

    unique = list(dict.fromkeys(c))
    return _highest_priority(unique)
