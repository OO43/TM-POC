# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — global alert priority and policy-only overrides (PoC).

Emergency is handled in main.py before any type here. Lower index = higher priority.
"""

from __future__ import annotations

from thresholds import AlertType

# Full arbitration order (simulated ``EmergencyEvent`` still wins in evaluate_driver_tick
# before routine arbitration). ``EMERGENCY_ESCALATION`` is first so floor-linked operational
# escalation (if present) outranks routine scenarios.
FULL_ALERT_PRIORITY: tuple[AlertType, ...] = (
    AlertType.EMERGENCY_ESCALATION,
    AlertType.PASSENGER_STOP_REQUEST,
    AlertType.BLOCKED_EXIT_VULNERABLE,
    AlertType.CAPACITY_EXCEEDED,
    AlertType.ROUTE_DIVERSION_ACTIVE,
    AlertType.CHILD_HIGH_MOVEMENT,
    AlertType.WHEELCHAIR_UNSAFE_POSITION,
    AlertType.WHEELCHAIR_UNSTABLE_IN_BAY,
    AlertType.WHEELCHAIR_BAY_OBSTRUCTION,
    AlertType.PUSHCHAIR_UNSAFE_POSITION,
    AlertType.PUSHCHAIR_INSTABILITY,
    AlertType.SEAT_ASSISTANCE_REQUIRED,
    AlertType.JOURNEY_END_CHECK,
    AlertType.EXIT_PREPARATION,
    AlertType.INSTABILITY_RISK,
    AlertType.STANDING_MOTION_RISK,
    AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY,
    AlertType.VULNERABILITY_ASSISTANCE_ADVISORY,
    AlertType.CROWDING_ADVISORY,
    AlertType.SYSTEM_SUPPORT_ALERT,
    AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY,
)

_PRIORITY_INDEX: dict[AlertType, int] = {a: i for i, a in enumerate(FULL_ALERT_PRIORITY)}

BYPASS_COMPOUNDED_RISK_GATING: frozenset[AlertType] = frozenset(
    {
        AlertType.EMERGENCY_ESCALATION,
        AlertType.PASSENGER_STOP_REQUEST,
        AlertType.ROUTE_DIVERSION_ACTIVE,
        AlertType.CAPACITY_EXCEEDED,
        AlertType.VULNERABILITY_ASSISTANCE_ADVISORY,
        AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY,
        AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY,
    }
)


def pick_highest_priority_alert(candidates: list[AlertType]) -> AlertType | None:
    if not candidates:
        return None
    return min(candidates, key=lambda a: _PRIORITY_INDEX[a])


def bypasses_compounded_risk_gating(alert: AlertType) -> bool:
    """Policy / explicit events that must show without thresholded risk."""
    return alert in BYPASS_COMPOUNDED_RISK_GATING


def is_vehicle_stationary_for_diversion(can_vehicle_stationary: bool, motion_level: float) -> bool:
    """Tablet contract: diversion only when stopped (explicit CAN flag or near-zero motion)."""
    if can_vehicle_stationary:
        return True
    return motion_level < 0.05


def strict_overcapacity(passengers_onboard: int, vehicle_capacity: int) -> bool:
    """Policy: onboard strictly greater than nominal capacity."""
    return passengers_onboard > vehicle_capacity
