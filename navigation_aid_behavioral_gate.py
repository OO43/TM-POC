# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Behavioral navigation / cane gate (PoC).

``navigation_aid_in_use`` exposed to policy must reflect **mobility cane usage**, not carried
sticks, umbrellas, or brooms. Perception should output:

- ``navigation_aid_candidate`` — raw elongated-object / stick-like score (may false-positive).
- ``navigation_aid_in_use`` — legacy alias: if ``candidate`` is 0, candidate is read from this.
- ``nav_aid_floor_contact`` — thin object, repeated floor contact.
- ``nav_aid_gait_coupling`` — object motion coupled to step cadence.
- ``nav_aid_vertical_load`` — vertical stabilization / load-bearing shaft use.
- ``nav_aid_unilateral_bias`` — prefer one side (asymmetric vs symmetric carry).

All four behavioral signals must be present above threshold **concurrently** for a sustained
interval (seconds). Only then is ``navigation_aid_in_use`` set to the fused score
(candidate × behavioral product). Carried sticks without behavioral evidence → 0.
"""

from __future__ import annotations

import time
from dataclasses import replace

from observed_cues import ObservedCues

_MIN_EACH = 0.28
_PERSIST_SEC = 0.48
# Batch harness / fast loops: monotonic dt can be tiny; floor integration step (nominal ~12 Hz).
_FLOOR_DT_OK = 0.082
_CAP_DT = 0.22

_gate_last_mono: float | None = None
_persist_accum_sec = 0.0
# Last output of apply() in the current evaluation (mirrors must not call apply() again).
_last_gated_observed: ObservedCues | None = None


def reset_navigation_aid_behavioral_gate() -> None:
    """Test harness / room reset."""
    global _gate_last_mono, _persist_accum_sec, _last_gated_observed
    _gate_last_mono = None
    _persist_accum_sec = 0.0
    _last_gated_observed = None


def last_gated_observed_cues() -> ObservedCues | None:
    """Gated cues from the most recent ``apply_navigation_aid_behavioral_gate`` (same thread)."""
    return _last_gated_observed


def apply_navigation_aid_behavioral_gate(observed: ObservedCues | None) -> ObservedCues | None:
    """
    Return a copy of ``observed`` with ``navigation_aid_in_use`` replaced by the gated value.

    When behavioral dimensions are all absent (zeros), stick-like candidates are **suppressed**
    so ``navigation_aid_in_use`` becomes 0.0.
    """
    global _gate_last_mono
    global _persist_accum_sec
    global _last_gated_observed

    if observed is None:
        _last_gated_observed = None
        return None

    c = observed.clamped()
    raw = float(c.navigation_aid_candidate) if c.navigation_aid_candidate > 1e-6 else float(
        c.navigation_aid_in_use
    )

    f_floor = float(c.nav_aid_floor_contact)
    f_gait = float(c.nav_aid_gait_coupling)
    f_load = float(c.nav_aid_vertical_load)
    f_side = float(c.nav_aid_unilateral_bias)
    behavioral = (f_floor, f_gait, f_load, f_side)
    b_min = min(behavioral) if behavioral else 0.0
    all_ok = (
        f_floor >= _MIN_EACH
        and f_gait >= _MIN_EACH
        and f_load >= _MIN_EACH
        and f_side >= _MIN_EACH
    )

    now = time.monotonic()
    if _gate_last_mono is None:
        dt = _FLOOR_DT_OK
    else:
        dt = max(1e-4, now - _gate_last_mono)
    _gate_last_mono = now

    if all_ok:
        step = min(_CAP_DT, max(dt, _FLOOR_DT_OK))
        _persist_accum_sec = min(2.5, _persist_accum_sec + step)
    else:
        _persist_accum_sec = max(0.0, _persist_accum_sec - dt * 3.2)

    persist_ready = _persist_accum_sec >= _PERSIST_SEC and all_ok

    if persist_ready:
        prod = _clamp01(raw * b_min * b_min)
        effective = prod if prod >= 0.18 else 0.0
    else:
        effective = 0.0

    out = replace(
        c,
        navigation_aid_in_use=effective,
    )
    _last_gated_observed = out
    return out


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))
