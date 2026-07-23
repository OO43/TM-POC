# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
End-of-service advisory: density count is zero but perception still suggests a person.

Uses only tick / CAN / density / ObservedCues already produced by adapters — no camera math.
Optional ``tick["driver_ack_passenger_remaining_onboard"]`` suppresses repeats until context clears.
"""

from __future__ import annotations

from typing import Any

from can_context import CANContext
from density_context import DensityContext
from observed_cues import ObservedCues

_ACK_SUPPRESS: bool = False


def reset_passenger_remaining_onboard_ack_state() -> None:
    """Test harness."""
    global _ACK_SUPPRESS
    _ACK_SUPPRESS = False


def _consume_optional_ack(tick: dict[str, Any]) -> None:
    global _ACK_SUPPRESS
    if bool(tick.get("driver_ack_passenger_remaining_onboard", False)):
        _ACK_SUPPRESS = True


def _cues_suggest_human_presence(observed: ObservedCues) -> bool:
    c = observed.clamped()
    signals = (
        c.floor_level_posture,
        c.leaning_without_support,
        c.unstable_posture,
        c.navigation_aid_in_use,
        c.large_mobility_device_present,
        c.small_wheeled_carriage_present,
        c.frequent_balance_correction,
        c.near_door_area,
        c.prolonged_standing,
        c.rapid_erratic_motion,
        c.repetitive_agitated_motion,
        c.distress_motion_pattern,
    )
    return max(signals, default=0.0) >= 0.14


def _perception_foreground_not_empty(tick: dict[str, Any]) -> bool:
    status = str(tick.get("camera_perception_status") or "json_ok").strip().lower()
    return status != "no_foreground"


def human_presence_signal(tick: dict[str, Any], observed: ObservedCues | None) -> bool:
    """
    Zone-agnostic presence proxy: explicit tick flag, non-empty foreground label, or cue bundle.

    Future multi-camera fusion can OR additional tick fields here without changing adapters.
    """
    explicit = tick.get("passenger_present")
    if explicit is False:
        return False
    if explicit is True:
        return True
    if _perception_foreground_not_empty(tick):
        return True
    if observed is not None and _cues_suggest_human_presence(observed):
        return True
    return False


def stationary_zero_density_count(
    can_context: CANContext,
    density_ctx: DensityContext | None,
) -> bool:
    if density_ctx is None:
        return False
    if int(density_ctx.passengers_onboard) != 0:
        return False
    if not bool(can_context.vehicle_stationary):
        return False
    if abs(float(can_context.speed)) > 1e-9:
        return False
    return True


def remaining_onboard_advisory_eligible(
    tick: dict[str, Any],
    observed: ObservedCues | None,
    *,
    can_context: CANContext,
    density_ctx: DensityContext | None,
    exit_advisory: bool,
    vuln_advisory: bool,
    final_winner_classic: Any,
    policy_candidates: list[Any],
    should_alert_classic: bool,
) -> bool:
    """
    True only when all trigger conditions hold and higher-priority outputs are absent.

    ``final_winner_classic`` / ``should_alert_classic`` are the pre-override arbitration results.
    """
    global _ACK_SUPPRESS
    _consume_optional_ack(tick)

    base = stationary_zero_density_count(can_context, density_ctx) and human_presence_signal(
        tick, observed
    )
    if not base:
        _ACK_SUPPRESS = False
        return False
    if _ACK_SUPPRESS:
        return False
    if exit_advisory or vuln_advisory:
        return False
    if final_winner_classic is not None or should_alert_classic:
        return False
    if policy_candidates:
        return False
    return True
