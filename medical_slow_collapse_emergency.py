# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Medical collapse (slow descent) — inferred emergency lane (PoC).

Distinct from abrupt fall / high-instability cues: gradual lowering to a floor‑level posture
with calm motion, vulnerability confirmed, and no recovery stabilization after becoming low.

Does not depend on aggressive_motion_pattern, compounded instability, or CAN motion level.
"""

from __future__ import annotations

import time

from observed_cues import ObservedCues

_calm_motion_max = 0.20
_gradual_floor_rise_min = 0.012
_gradual_floor_rise_max = 0.11
_sudden_floor_jump = 0.22

_min_gradual_descent_sec = 1.05
_floor_level_on = 0.52

_min_floor_dwell_no_recovery_sec = 2.18
_recovery_fbc = 0.38
_recovery_erratic_low = 0.26


_last_mono: float | None = None
_prev_floor: float | None = None
_descent_sec_accum = 0.0
_floor_dwell_accum = 0.0


def reset_medical_slow_collapse_tracker() -> None:
    global _last_mono, _prev_floor, _descent_sec_accum, _floor_dwell_accum
    _last_mono = None
    _prev_floor = None
    _descent_sec_accum = 0.0
    _floor_dwell_accum = 0.0


def _activity_score(c: ObservedCues) -> float:
    return max(
        float(c.rapid_erratic_motion),
        float(c.repetitive_agitated_motion),
        float(c.aggressive_motion_pattern),
        float(c.distress_motion_pattern) * 0.82,
    )


def update_medical_slow_collapse_tracker(
    observed: ObservedCues | None, vulnerability_confirmed: bool
) -> bool:
    """
    Return True when the slow medical-collapse trajectory has completed this tick
    (vulnerability-restricted gradual descent → low posture → sustained no-recovery dwell).
    """
    global _last_mono, _prev_floor, _descent_sec_accum, _floor_dwell_accum

    now = time.monotonic()
    dt = 0.05 if _last_mono is None else max(1e-4, now - _last_mono)
    _last_mono = now

    if observed is None or not vulnerability_confirmed:
        _prev_floor = None
        _descent_sec_accum = 0.0
        _floor_dwell_accum = 0.0
        return False

    c = observed.clamped()
    calm = _activity_score(c) < _calm_motion_max
    floor = float(c.floor_level_posture)

    recovery = (
        float(c.frequent_balance_correction) >= _recovery_fbc
        or float(c.rapid_erratic_motion) >= _recovery_erratic_low
        or (
            floor >= _floor_level_on
            and float(c.prolonged_standing) >= 0.48
            and float(c.unstable_posture) < 0.22
        )
    )

    dfloor = 0.0 if _prev_floor is None else floor - _prev_floor
    sudden_jump = _prev_floor is not None and dfloor > _sudden_floor_jump

    gradual_step = (
        _prev_floor is not None
        and _gradual_floor_rise_min < dfloor < _gradual_floor_rise_max
        and calm
    )

    if sudden_jump:
        _descent_sec_accum = 0.0
        _floor_dwell_accum = 0.0

    elif calm and gradual_step:
        _descent_sec_accum = min(8.0, _descent_sec_accum + dt)
    else:
        _descent_sec_accum = max(0.0, _descent_sec_accum - dt * 0.5)

    _prev_floor = floor

    at_low = floor >= _floor_level_on
    gradual_met = _descent_sec_accum >= _min_gradual_descent_sec

    if at_low and gradual_met and calm:
        if recovery:
            _floor_dwell_accum = max(0.0, _floor_dwell_accum - dt * 3.8)
        else:
            _floor_dwell_accum = min(6.0, _floor_dwell_accum + dt)
    elif not at_low:
        _floor_dwell_accum = max(0.0, _floor_dwell_accum - dt * 1.05)
    elif not gradual_met:
        _floor_dwell_accum = max(0.0, _floor_dwell_accum - dt * 0.9)

    return (
        _floor_dwell_accum >= _min_floor_dwell_no_recovery_sec
        and at_low
        and gradual_met
        and calm
        and not recovery
    )
