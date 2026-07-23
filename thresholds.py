# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — threshold configuration (PoC).

All support values represent consent-declared accommodation preferences only.
They do not diagnose conditions and are not used as standalone alert triggers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from itertools import product
from pathlib import Path


class SupportCategory(str, Enum):
    """Optional consent-declared support context. Not a detection label."""

    UNDECLARED = "undeclared"
    VISUAL_IMPAIRMENT = "visual_impairment"
    MOBILITY_SUPPORT = "mobility_support"
    WHEELCHAIR = "wheelchair"
    PUSHCHAIR = "pushchair"
    ELDERLY_SUPPORT = "elderly_support"
    PREGNANCY_SUPPORT = "pregnancy_support"
    MEDICAL_SENSITIVITY = "medical_sensitivity"
    NEURODIVERSITY_SUPPORT = "neurodiversity_support"
    CHILD_SUPPORT = "child_support"


class AlertType(str, Enum):
    """Operational safety / accessibility alert kinds (non-diagnostic)."""

    # No selected operational alert (empty cabin / monitoring-only baseline).
    NONE = "none"

    # Extended operational kinds (scenario + policy arbitration; see policy_arbitration.py)
    BLOCKED_EXIT_VULNERABLE = "blocked_exit_vulnerable"
    CHILD_HIGH_MOVEMENT = "child_high_movement"
    WHEELCHAIR_UNSAFE_POSITION = "wheelchair_unsafe_position"
    WHEELCHAIR_UNSTABLE_IN_BAY = "wheelchair_unstable_in_bay"
    PUSHCHAIR_UNSAFE_POSITION = "pushchair_unsafe_position"
    SEAT_ASSISTANCE_REQUIRED = "seat_assistance_required"
    CROWDING_ADVISORY = "crowding_advisory"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    PASSENGER_STOP_REQUEST = "passenger_stop_request"
    ROUTE_DIVERSION_ACTIVE = "route_diversion_active"
    SYSTEM_SUPPORT_ALERT = "system_support_alert"
    # Lowest-priority informational: density zero but perception still suggests a person.
    PASSENGER_REMAINING_ONBOARD_ADVISORY = "passenger_remaining_onboard_advisory"

    INSTABILITY_RISK = "instability_risk"
    # Softer assistance-oriented advisory (lower priority than INSTABILITY_RISK; never emergency).
    VULNERABILITY_ASSISTANCE_ADVISORY = "vulnerability_assistance_advisory"
    # Crowded-door exit assist: vulnerability + door proximity + dwell (assistive only).
    VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY = "vulnerable_exit_crowd_assistance_advisory"
    STANDING_MOTION_RISK = "standing_motion_risk"
    PUSHCHAIR_INSTABILITY = "pushchair_instability"
    WHEELCHAIR_BAY_OBSTRUCTION = "wheelchair_bay_obstruction"
    EXIT_PREPARATION = "exit_preparation"
    JOURNEY_END_CHECK = "journey_end_check"
    EMERGENCY_ESCALATION = "emergency_escalation"


@dataclass(frozen=True)
class ThresholdParams:
    """Per (support context, alert kind) gate: compounded risk and factor rules."""

    risk_threshold: float
    min_elevated_factors: int
    consent_sensitivity_multiplier: float
    factor_elevation_floor: float


def _default_params() -> ThresholdParams:
    """Baseline defaults; override via threshold_overrides.json (optional)."""
    return ThresholdParams(
        risk_threshold=0.55,
        min_elevated_factors=2,
        consent_sensitivity_multiplier=1.12,
        factor_elevation_floor=0.4,
    )


def _project_dir() -> Path:
    return Path(__file__).resolve().parent


@dataclass(frozen=True)
class RoomTestTiming:
    """
    Advisory dwell timings for room validation (seconds).

    Loaded from ``threshold_overrides.json`` → ``room_test_timing``. Not consumed
    by ``evaluate_driver_tick``; exposed on ticks and logs for observers/tools.
    """

    boarding_dwell_secs: float
    exit_dwell_secs: float
    standing_dwell_secs: float


def _load_room_test_timing_from_json() -> RoomTestTiming:
    path = _project_dir() / "threshold_overrides.json"
    defaults = RoomTestTiming(
        boarding_dwell_secs=120.0,
        exit_dwell_secs=180.0,
        standing_dwell_secs=120.0,
    )
    if not path.is_file():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    rt = raw.get("room_test_timing")
    if not isinstance(rt, dict):
        return defaults
    return RoomTestTiming(
        boarding_dwell_secs=float(rt.get("boarding_dwell_secs", defaults.boarding_dwell_secs)),
        exit_dwell_secs=float(rt.get("exit_dwell_secs", defaults.exit_dwell_secs)),
        standing_dwell_secs=float(rt.get("standing_dwell_secs", defaults.standing_dwell_secs)),
    )


ROOM_TEST_TIMING: RoomTestTiming = _load_room_test_timing_from_json()


def get_room_test_timing() -> RoomTestTiming:
    return ROOM_TEST_TIMING


def _load_overrides_from_json() -> dict[tuple[SupportCategory, AlertType], ThresholdParams]:
    path = _project_dir() / "threshold_overrides.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[SupportCategory, AlertType], ThresholdParams] = {}
    base = _default_params()
    for row in raw.get("overrides", []):
        sc = SupportCategory(row["support_category"])
        at = AlertType(row["alert_type"])
        out[(sc, at)] = ThresholdParams(
            risk_threshold=float(row.get("risk_threshold", base.risk_threshold)),
            min_elevated_factors=int(row.get("min_elevated_factors", base.min_elevated_factors)),
            consent_sensitivity_multiplier=float(
                row.get("consent_sensitivity_multiplier", base.consent_sensitivity_multiplier)
            ),
            factor_elevation_floor=float(
                row.get("factor_elevation_floor", base.factor_elevation_floor)
            ),
        )
    return out


def build_threshold_table() -> dict[tuple[SupportCategory, AlertType], ThresholdParams]:
    table = {pair: _default_params() for pair in product(SupportCategory, AlertType)}
    for key, params in _load_overrides_from_json().items():
        table[key] = params
    return table


THRESHOLD_TABLE: dict[tuple[SupportCategory, AlertType], ThresholdParams] = build_threshold_table()


def get_threshold_params(
    support: SupportCategory,
    alert: AlertType,
) -> ThresholdParams:
    return THRESHOLD_TABLE[(support, alert)]
