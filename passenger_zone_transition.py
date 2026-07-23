# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Placeholder for continuity-based zone transitions (no biometric identity).

Later: Zone 3 → Zone 2 → Zone 1 exit paths using timestamps + motion agreement
between camera streams. For now callers may append records for instrumentation only.
"""

from __future__ import annotations

from dataclasses import dataclass

from cabin_topology import CabinZoneId


@dataclass(frozen=True)
class ZoneTransitionPlaceholder:
    """Recorded intent to model a crossed logical boundary between observations."""

    passenger_slot_id: str
    from_zone: CabinZoneId
    to_zone: CabinZoneId
    inferred_at_mono: float
    confidence: float
    rationale: str


_TRANSITION_LOG: list[ZoneTransitionPlaceholder] = []


def record_zone_transition_candidate(
    *,
    passenger_slot_id: str,
    from_zone: CabinZoneId,
    to_zone: CabinZoneId,
    inferred_at_mono: float,
    confidence: float,
    rationale: str,
) -> None:
    """
    Stub: append-only log for Phase‑3 scaffolding (multi-camera fusion will consume later).

    No effect on alerts or inference today.
    """
    _TRANSITION_LOG.append(
        ZoneTransitionPlaceholder(
            passenger_slot_id=passenger_slot_id,
            from_zone=from_zone,
            to_zone=to_zone,
            inferred_at_mono=inferred_at_mono,
            confidence=confidence,
            rationale=rationale,
        )
    )


def peek_recent_transitions(limit: int = 16) -> tuple[ZoneTransitionPlaceholder, ...]:
    """Diagnostics / logging only."""
    return tuple(_TRANSITION_LOG[-limit:])


def reset_zone_transition_placeholder_log() -> None:
    """Test harness."""
    global _TRANSITION_LOG
    _TRANSITION_LOG = []
