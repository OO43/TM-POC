# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Cabin / foreground presence for alert gating (PoC).

Perception must not drive vulnerability, instability, or passenger-facing emergencies when
no human foreground is visible. Adapters set ``camera_perception_status`` (e.g.
``no_foreground``) or an explicit ``passenger_present`` tick field.
"""

from __future__ import annotations

from exit_vulnerable_door import (
    passenger_present_for_situated_context,
    reset_exit_crowded_assist_dwell,
    reset_vulnerable_door_association,
)
from instability_escalation import reset_instability_escalation
from policy_floor_emergency import reset_floor_emergency_accumulator
from vulnerability_inference import reset_vulnerability_inference


def passenger_present_for_alert_path(tick: dict) -> bool:
    """
    True only when foreground / occupancy cues allow passenger-scenario attribution.

    - Optional explicit ``tick["passenger_present"]`` (bool) overrides (harness / sim).
    - Otherwise ``camera_perception_status`` from vision: ``no_foreground`` => False.
    - Missing camera fields => True (backward compatible with JSON harness without camera).
    """
    explicit = tick.get("passenger_present")
    if explicit is not None:
        return bool(explicit)

    status = str(tick.get("camera_perception_status") or "json_ok")
    return passenger_present_for_situated_context(status)


def reset_cabin_inferencers_when_no_passenger_visible() -> None:
    """Drop stale temporal vulnerability / doorway / emergency-accumulator state."""
    reset_vulnerability_inference()
    reset_instability_escalation()
    reset_floor_emergency_accumulator()
    reset_vulnerable_door_association()
    reset_exit_crowded_assist_dwell()
