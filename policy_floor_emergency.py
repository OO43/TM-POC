# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Floor-related **policy-only** bridge to simulated emergency inputs (PoC).

``floor_level_posture`` (cabin perception) must be able to declare
``passenger_collapse_or_fall`` after **sustained** high confidence, **globally**:
independent of journey phase, vehicle motion, instability scenarios, or other
operational-alert priority. Thresholds here are intentionally conservative to
reduce false trips from brief crouch / bend; they are not lowered relative to
prior ad-hoc journey-end checks (those used ``>= 0.28`` for a **non-emergency**
hint only).

``evaluate_driver_tick`` merges these flags before ``resolve_simulated_emergency``.
"""

from __future__ import annotations

import time

from dataclasses import fields as dc_fields

from emergency import SimulatedEmergencyInputs
from observed_cues import ObservedCues


def _emergency_inputs_from_tick_dict(tick: dict) -> SimulatedEmergencyInputs:
    raw = tick.get("emergency", {})
    return SimulatedEmergencyInputs(
        passenger_collapse_or_fall=bool(raw.get("passenger_collapse_or_fall", False)),
        fire_or_smoke=bool(raw.get("fire_or_smoke", False)),
        medical_collapse_slow_descent=bool(
            raw.get("medical_collapse_slow_descent", False)
        ),
        altercation=bool(raw.get("altercation", False)),
        severe_distress=bool(raw.get("severe_distress", False)),
    )


def _observed_cues_from_tick_dict(tick: dict) -> ObservedCues | None:
    raw = tick.get("observed_cues")
    if raw is None:
        return None
    kw = {f.name: float(raw.get(f.name, 0.0)) for f in dc_fields(ObservedCues)}
    return ObservedCues(**kw)

# Sustained strong floor cue before declaring collapse (seconds).
_FLOOR_COLLAPSE_PERSIST_SEC = 1.25
# Activation band; hysteresis low band avoids flicker at boundary.
_FLOOR_COLLAPSE_ON = 0.58
_FLOOR_COLLAPSE_OFF = 0.48

_accum_sec = 0.0
_last_mono: float | None = None


def reset_floor_emergency_accumulator() -> None:
    """Test / harness: clear persistence state."""
    global _accum_sec, _last_mono
    _accum_sec = 0.0
    _last_mono = None


def _tick_floor_collapse_active(observed: ObservedCues | None) -> bool:
    """True when sustained high floor-level posture indicates passenger on floor."""
    global _accum_sec, _last_mono
    now = time.monotonic()
    dt = 0.05 if _last_mono is None else max(0.0, now - _last_mono)
    _last_mono = now

    if observed is None:
        _accum_sec = max(0.0, _accum_sec - 1.1 * dt)
        return False

    fl = float(observed.floor_level_posture)
    if fl >= _FLOOR_COLLAPSE_ON:
        _accum_sec += dt
    elif fl <= _FLOOR_COLLAPSE_OFF:
        _accum_sec = max(0.0, _accum_sec - 1.4 * dt)
    else:
        _accum_sec = max(0.0, _accum_sec - 0.08 * dt)
    return _accum_sec >= _FLOOR_COLLAPSE_PERSIST_SEC


def merge_tick_emergency_inputs_with_floor_policy(tick: dict) -> SimulatedEmergencyInputs:
    """
    OR simulated tick flags with sustained floor-collapse policy (never clears
    explicit upstream emergency flags).
    """
    base = _emergency_inputs_from_tick_dict(tick)
    observed = _observed_cues_from_tick_dict(tick)
    floor = _tick_floor_collapse_active(observed)
    return SimulatedEmergencyInputs(
        passenger_collapse_or_fall=bool(base.passenger_collapse_or_fall or floor),
        fire_or_smoke=base.fire_or_smoke,
        medical_collapse_slow_descent=base.medical_collapse_slow_descent,
        altercation=base.altercation,
        severe_distress=base.severe_distress,
    )
