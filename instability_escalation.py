# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Temporal cues for instability *escalation* beyond a sustained vulnerable baseline.

When functional vulnerability is confirmed, steady or low-amplitude balance behaviour is treated
as baseline posture — instability requires acceleration, widening sway, abrupt shifts, or
severity that clear the baseline. Perception cues are unchanged; only evaluation differs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from observed_cues import ObservedCues
from vulnerability_inference import VulnerabilitySource


@dataclass(frozen=True)
class InstabilityEscalationSnapshot:
    """Raised when motion cues worsen vs the prior tick beyond steady-state noise."""

    escalation_active: bool


class _InstabilityEscalationTracker:
    __slots__ = ("_last_mono", "_prev_fbc", "_prev_lean", "_prev_u")

    def __init__(self) -> None:
        self._last_mono: float | None = None
        self._prev_u: float | None = None
        self._prev_fbc: float | None = None
        self._prev_lean: float | None = None

    def update(
        self,
        observed: ObservedCues,
        vulnerability_confirmed: bool,
        vulnerability_source: VulnerabilitySource = VulnerabilitySource.NONE,
    ) -> InstabilityEscalationSnapshot:
        now = time.monotonic()
        dt = 0.05 if self._last_mono is None else max(1e-3, now - self._last_mono)
        self._last_mono = now

        c = observed.clamped()
        u = float(c.unstable_posture)
        fbc = float(c.frequent_balance_correction)
        lean = float(c.leaning_without_support)

        if self._prev_u is None:
            self._prev_u, self._prev_fbc, self._prev_lean = u, fbc, lean
            return InstabilityEscalationSnapshot(False)

        du = u - self._prev_u
        dfbc = fbc - self._prev_fbc
        dlean = lean - self._prev_lean

        aid = vulnerability_source is VulnerabilitySource.MOBILITY_AID
        if aid:
            # Cane / mobility aid: steady lean and correction count as baseline; detect loss of control.
            abrupt = abs(du) >= 0.082 or abs(dfbc) >= 0.10 or abs(dlean) >= 0.072
            sway_widen = du >= 0.030 and u >= 0.22 and u > self._prev_u
            correction_intensifying = dfbc >= 0.042 and fbc >= 0.24
            severe_absolute = u >= 0.50 or fbc >= 0.72 or lean >= 0.58
        else:
            # Abrupt single-tick change (not steady micro-wobble).
            abrupt = abs(du) >= 0.11 or abs(dfbc) >= 0.13 or abs(dlean) >= 0.09
            # Widening sway: instability signal rising from an already-elevated level.
            sway_widen = du >= 0.038 and u >= 0.24 and u > self._prev_u
            # Increasing correction demand vs prior tick (frequency / amplitude build).
            correction_intensifying = dfbc >= 0.048 and fbc >= 0.26
            # Severity well above typical vulnerable baseline even without strong deltas.
            severe_absolute = u >= 0.54 or fbc >= 0.76 or lean >= 0.62

        active = vulnerability_confirmed and (
            abrupt or sway_widen or correction_intensifying or severe_absolute
        )

        self._prev_u, self._prev_fbc, self._prev_lean = u, fbc, lean
        return InstabilityEscalationSnapshot(escalation_active=bool(active))


_tracker: _InstabilityEscalationTracker | None = None
_last_snapshot: InstabilityEscalationSnapshot = InstabilityEscalationSnapshot(False)


def reset_instability_escalation() -> None:
    """Test harness: clear tracker and last snapshot."""
    global _tracker, _last_snapshot
    _tracker = None
    _last_snapshot = InstabilityEscalationSnapshot(False)


def update_instability_escalation(
    observed: ObservedCues | None,
    vulnerability_confirmed: bool,
    vulnerability_source: VulnerabilitySource = VulnerabilitySource.NONE,
) -> InstabilityEscalationSnapshot:
    global _tracker, _last_snapshot
    if observed is None:
        return _last_snapshot
    if _tracker is None:
        _tracker = _InstabilityEscalationTracker()
    _last_snapshot = _tracker.update(
        observed, vulnerability_confirmed, vulnerability_source
    )
    return _last_snapshot


def peek_instability_escalation() -> InstabilityEscalationSnapshot:
    return _last_snapshot
