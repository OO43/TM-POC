# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Situational binding: functional vulnerability + door proximity + cabin presence.

Door association uses temporal persistence and smoothed cues (not one-frame thresholds),
moderate door-third dominance (not necessarily max zone), and gradual decay.
Uses the same monotonic clock as other ROOM_TEST state; no identity tracking.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

from observed_cues import ObservedCues
from thresholds import AlertType
from vulnerability_inference import VulnerabilitySnapshot


# ── Door association (smoothed; independent of scenario arbitration thresholds) ──
_EMA_NEAR_DOOR_TAU_SEC = 0.42
_EMA_ZONE_TAU_SEC = 0.55
# Smoothed near_door cue must support exit intent (not a single-frame spike).
_EMA_NEAR_DOOR_MIN = 0.32
# Cue-only fallback when zone weights are unavailable / negligible.
_EMA_NEAR_DOOR_MIN_CUE_ONLY = 0.36
_ZONE_SUM_MIN_FOR_DOMINANCE = 0.12
_DOOR_ZONE_FLOOR = 0.26
# Door third competitive with strongest other third without being strict max.
_DOOR_DOMINANCE_MARGIN = 0.11
# Seconds of sustained intent before vulnerable_passenger_near_door is true.
_DOOR_INTENT_PERSIST_SEC = 1.75
# Gradual decay of persistence when intent weakens (mid-zone fluctuation).
_PERSIST_DECAY_PER_SEC = 0.68
_PERSIST_CAP_SEC = 5.0
# Faster bleed when vulnerability or presence drops.
_PERSIST_FAST_DECAY_PER_SEC = 1.35

# Minimum load ratio (passengers_onboard / vehicle_capacity) for crowded-exit assist — unchanged.
_HIGH_DENSITY_RATIO_MIN = 0.72

# Seconds conditions must hold continuously before advisory (hesitation / dwell).
EXIT_ASSIST_DWELL_SEC_DEFAULT = 4.2

_exit_dwell_tracker: "ExitCrowdedAssistDwell | None" = None
_door_assoc_tracker: "VulnerableDoorAssociationTracker | None" = None


def reset_exit_crowded_assist_dwell() -> None:
    """Test harness: clear dwell accumulator."""
    global _exit_dwell_tracker
    _exit_dwell_tracker = None


def reset_vulnerable_door_association() -> None:
    """Test harness: clear door association smoother / persistence."""
    global _door_assoc_tracker
    _door_assoc_tracker = None


def exit_assist_dwell_seconds() -> float:
    raw = os.environ.get("TRAVELMATE_EXIT_ASSIST_DWELL_SEC", "").strip()
    if not raw:
        return EXIT_ASSIST_DWELL_SEC_DEFAULT
    try:
        v = float(raw)
    except ValueError:
        return EXIT_ASSIST_DWELL_SEC_DEFAULT
    return max(1.0, min(30.0, v))


def passenger_present_for_situated_context(camera_perception_status: str) -> bool:
    """
    True when the cabin pipeline does not report an empty foreground mask.

    ``no_foreground`` means no passenger blob — do not attribute door proximity to someone present.
    """
    return camera_perception_status != "no_foreground"


def _smooth_toward(prev: float, target: float, dt: float, tau_sec: float) -> float:
    if tau_sec <= 1e-6:
        return target
    a = 1.0 - math.exp(-dt / tau_sec)
    return prev + a * (target - prev)


def moderate_door_zone_dominance(door_ema: float, mid_ema: float, rear_ema: float) -> bool:
    """
    Door band is meaningfully engaged vs other thirds — not required to be the unique maximum.
    """
    if door_ema < _DOOR_ZONE_FLOOR:
        return False
    mx_other = max(mid_ema, rear_ema)
    return door_ema + _DOOR_DOMINANCE_MARGIN >= mx_other


class VulnerableDoorAssociationTracker:
    """
    Accumulates exit-association evidence over wall-clock seconds; decays gradually on weak frames.
    """

    __slots__ = (
        "_ema_d",
        "_ema_m",
        "_ema_nd",
        "_ema_r",
        "_last_mono",
        "_persist_sec",
    )

    def __init__(self) -> None:
        self._last_mono: float | None = None
        self._ema_nd = 0.0
        z0 = 1.0 / 3.0
        self._ema_d = z0
        self._ema_m = z0
        self._ema_r = z0
        self._persist_sec = 0.0

    def update(
        self,
        snapshot: VulnerabilitySnapshot,
        observed: ObservedCues | None,
        *,
        camera_perception_status: str,
        camera_zones: dict[str, float] | None,
    ) -> bool:
        now = time.monotonic()
        dt = 0.05 if self._last_mono is None else max(1e-3, now - self._last_mono)
        self._last_mono = now

        if observed is None or not snapshot.confirmed:
            self._persist_sec = max(0.0, self._persist_sec - dt * _PERSIST_FAST_DECAY_PER_SEC)
            return False
        if not passenger_present_for_situated_context(camera_perception_status):
            self._persist_sec = max(0.0, self._persist_sec - dt * _PERSIST_FAST_DECAY_PER_SEC)
            return False

        o = observed.clamped()
        self._ema_nd = _smooth_toward(self._ema_nd, float(o.near_door_area), dt, _EMA_NEAR_DOOR_TAU_SEC)

        zd = zm = zr = 0.0
        if camera_zones:
            zd = float(camera_zones.get("door", 0.0))
            zm = float(camera_zones.get("mid", 0.0))
            zr = float(camera_zones.get("rear", 0.0))
            self._ema_d = _smooth_toward(self._ema_d, zd, dt, _EMA_ZONE_TAU_SEC)
            self._ema_m = _smooth_toward(self._ema_m, zm, dt, _EMA_ZONE_TAU_SEC)
            self._ema_r = _smooth_toward(self._ema_r, zr, dt, _EMA_ZONE_TAU_SEC)

        zone_total = self._ema_d + self._ema_m + self._ema_r
        has_usable_zones = zone_total >= _ZONE_SUM_MIN_FOR_DOMINANCE

        if has_usable_zones:
            near_ok = self._ema_nd >= _EMA_NEAR_DOOR_MIN
            dom_ok = moderate_door_zone_dominance(self._ema_d, self._ema_m, self._ema_r)
            intent = near_ok and dom_ok
        else:
            # No reliable spatial thirds: stricter smoothed door cue only + same persistence.
            intent = self._ema_nd >= _EMA_NEAR_DOOR_MIN_CUE_ONLY

        if intent:
            self._persist_sec = min(_PERSIST_CAP_SEC, self._persist_sec + dt)
        else:
            self._persist_sec = max(0.0, self._persist_sec - dt * _PERSIST_DECAY_PER_SEC)

        return self._persist_sec >= _DOOR_INTENT_PERSIST_SEC - 1e-9


def compute_vulnerable_passenger_near_door(
    snapshot: VulnerabilitySnapshot,
    observed: ObservedCues | None,
    *,
    camera_perception_status: str,
    camera_zones: dict[str, float] | None = None,
) -> bool:
    """
    True only after sustained, smoothed door/exit intent — not vulnerability alone, not one frame.

    Still requires ``snapshot.confirmed`` (functional vulnerability) and cabin presence.
    """
    global _door_assoc_tracker
    if _door_assoc_tracker is None:
        _door_assoc_tracker = VulnerableDoorAssociationTracker()
    return _door_assoc_tracker.update(
        snapshot,
        observed,
        camera_perception_status=camera_perception_status,
        camera_zones=camera_zones,
    )


def high_density_for_exit_assist(passenger_density_ratio: float) -> bool:
    return passenger_density_ratio >= _HIGH_DENSITY_RATIO_MIN


@dataclass(frozen=True)
class ExitAssistGateSnapshot:
    vulnerable_passenger_near_door: bool
    dwell_seconds_accumulated: float
    dwell_exceeded: bool


class ExitCrowdedAssistDwell:
    """Accumulates real time only while *all* gating inputs are simultaneously true."""

    __slots__ = ("_accum_sec", "_last_mono")

    def __init__(self) -> None:
        self._last_mono: float | None = None
        self._accum_sec = 0.0

    def update(self, all_gates_true: bool) -> tuple[float, bool]:
        now = time.monotonic()
        dt = 0.05 if self._last_mono is None else max(1e-3, now - self._last_mono)
        self._last_mono = now
        need = exit_assist_dwell_seconds()
        if all_gates_true:
            self._accum_sec = min(need * 1.5, self._accum_sec + dt)
        else:
            self._accum_sec = 0.0
        exceeded = self._accum_sec >= need - 1e-9
        return (self._accum_sec, exceeded)


def update_exit_crowded_assist_dwell(all_gates_true: bool) -> tuple[float, bool]:
    global _exit_dwell_tracker
    if _exit_dwell_tracker is None:
        _exit_dwell_tracker = ExitCrowdedAssistDwell()
    return _exit_dwell_tracker.update(all_gates_true)


def exit_crowded_assist_advisory_eligible(
    *,
    exit_conditions_met: bool,
    should_alert_classic: bool,
    final_winner: AlertType | None,
) -> bool:
    """
    Same stacking rules as generic vulnerability assist: do not override higher-priority winners
    or an already-active classic alert.
    """
    if not exit_conditions_met:
        return False
    if should_alert_classic:
        return False
    if final_winner not in (
        None,
        AlertType.INSTABILITY_RISK,
        AlertType.STANDING_MOTION_RISK,
    ):
        return False
    return True


def exit_crowded_assist_conditions(
    *,
    vulnerable_passenger_near_door: bool,
    doors_open: bool,
    vehicle_stationary: bool,
    density_ratio: float,
    dwell_exceeded: bool,
) -> bool:
    """Final advisory latch: crowded stop exit assist (assistive, non-emergency)."""
    if not vulnerable_passenger_near_door:
        return False
    if not doors_open or not vehicle_stationary:
        return False
    if not high_density_for_exit_assist(density_ratio):
        return False
    return dwell_exceeded
