# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI - driver-facing alert strings (PoC).

Actionable, neutral language. Never names medical conditions, pregnancy, disability
labels, or neurodiversity as detected traits - only operational requests.

Copy is kept intentionally short for glanceability while stationary or in motion brief.
"""

from __future__ import annotations

from emergency import EmergencyEvent
from thresholds import AlertType, SupportCategory


def _emergency_headline(ev: EmergencyEvent) -> str:
    """One short noun phrase — no procedural boilerplate."""
    table = {
        EmergencyEvent.PASSENGER_COLLAPSE_OR_FALL: "Passenger collapse or fall",
        EmergencyEvent.FIRE_OR_SMOKE: "Fire or smoke",
        EmergencyEvent.MEDICAL_COLLAPSE_SLOW_DESCENT: "Medical slow-motion collapse",
        EmergencyEvent.ALTERCATION: "Altercation",
        EmergencyEvent.SEVERE_DISTRESS: "Severe distress",
    }
    return table.get(ev, ev.value.replace("_", " "))


def render_driver_alert(
    *,
    alert_type: AlertType | None,
    scenario_matched: bool,
    should_alert: bool,
    emergency_sticky: EmergencyEvent | None,
    emergency_immediate: EmergencyEvent | None,
    support_categories: set[SupportCategory] | None = None,
) -> str:
    """Single line for console; emergency overrides all."""
    if emergency_sticky is not None:
        return f"EMERGENCY – {_emergency_headline(emergency_sticky)}"
    if emergency_immediate is not None:
        return f"EMERGENCY – {_emergency_headline(emergency_immediate)}"

    if alert_type is AlertType.NONE:
        return "No passenger in foreground."

    if not scenario_matched or alert_type is None:
        return "Routine — no matched scenario."

    if not should_alert:
        return "Routine — within risk limits."

    if (
        should_alert
        and support_categories is not None
        and SupportCategory.MEDICAL_SENSITIVITY in support_categories
        and alert_type
        in (AlertType.INSTABILITY_RISK, AlertType.STANDING_MOTION_RISK)
    ):
        return "Gentle speed — smoother braking."

    lines = {
        AlertType.BLOCKED_EXIT_VULNERABLE: "Blocked exit — vulnerable rider near door.",
        AlertType.CHILD_HIGH_MOVEMENT: "Child motion high — smoother driving.",
        AlertType.WHEELCHAIR_UNSAFE_POSITION: "Wheelchair position unsafe — reposition when safe.",
        AlertType.WHEELCHAIR_UNSTABLE_IN_BAY: "Wheelchair unstable — smooth steering and braking.",
        AlertType.WHEELCHAIR_BAY_OBSTRUCTION: "Wheelchair bay blocked — clear access.",
        AlertType.PUSHCHAIR_UNSAFE_POSITION: "Pushchair unsafe position — slow down.",
        AlertType.PUSHCHAIR_INSTABILITY: "Pushchair instability — smoother driving.",
        AlertType.SEAT_ASSISTANCE_REQUIRED: "Standing rider — seat assist if possible.",
        AlertType.JOURNEY_END_CHECK: "Route end — quick cabin check.",
        AlertType.EXIT_PREPARATION: "Stopping soon — softer braking.",
        AlertType.STANDING_MOTION_RISK: "Standing riders — softer driving.",
        AlertType.INSTABILITY_RISK: "Instability risk — drive smoothly.",
        AlertType.VULNERABILITY_ASSISTANCE_ADVISORY: (
            "Instability risk advisory — smooth speed changes."
        ),
        AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY: (
            "Vulnerable rider — assistance at exit · crowded door."
        ),
        AlertType.CROWDING_ADVISORY: "Cabin crowded — clear paths.",
        AlertType.CAPACITY_EXCEEDED: "Over capacity — do not depart.",
        AlertType.PASSENGER_STOP_REQUEST: "STOP — passenger exit.",
        AlertType.ROUTE_DIVERSION_ACTIVE: "Route change — passenger notice.",
        AlertType.SYSTEM_SUPPORT_ALERT: "Passenger displays — check when safe.",
        AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY: "Passenger still onboard.",
        AlertType.EMERGENCY_ESCALATION: "Operator escalation.",
    }
    return lines.get(
        alert_type,
        "Drive conditions — heightened attention.",
    )


def render_alert_cleared() -> str:
    return "Routine — alert cleared."
