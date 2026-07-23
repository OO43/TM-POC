# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — backend runtime session: display stack + bus readiness + transition-only sound cues.

Sound cues fire only on state transitions; steady-state ticks report sound_cue NONE.
Does not perform detection (uses ``evaluate_driver_tick`` + ``AlertDisplayStack`` outputs).
"""

from __future__ import annotations

from typing import Any, TypedDict

from alert_display_state import AlertDisplayContract, AlertDisplayStack
from sound_cues import SoundCue, sound_cue_priority
from tick_driver_eval import DriverTickOutcome


class BackendOutputContract(AlertDisplayContract):
    """Tablet / HMI / audio: stacked alerts plus readiness and at-most-one cue per tick."""

    pending_alert_count: int
    emergency_active: bool
    sound_cue: str
    bus_ready: bool


def emergency_active_from_outcome(out: DriverTickOutcome) -> bool:
    """True while the driver-eval path is in an emergency (sticky or immediate) state."""
    return out.kind in ("sticky_pending", "immediate")


def routine_blocks_bus_ready(out: DriverTickOutcome) -> bool:
    """
    Routine-only situations that keep the bus from “ready” even when no stacked
    alert row exists (e.g. scenario matched but risk-gated, or diversion blocked).
    Uses existing ``DriverTickOutcome`` flags only; does not change detection.
    """
    if out.kind != "routine":
        return False
    if out.diversion_blocked:
        return True
    if out.scenario_matched and not out.should_alert:
        return True
    return False


def compute_demo_tablet_bus_ready(tick: dict, out: DriverTickOutcome) -> bool:
    """
    Demo / tablet HMI only: readiness follows subsystem health, not alert backlog.

    Still blocks on emergency and on ``system_faults`` / ``adapter_health`` (same
    interpretation as production). Set only when ``tick["demo_tablet_readiness"]``
    is true (demo input layer).
    """
    if emergency_active_from_outcome(out):
        return False
    sf = tick.get("system_faults") or {}
    if isinstance(sf, dict) and any(bool(v) for v in sf.values()):
        return False
    ah = tick.get("adapter_health")
    if isinstance(ah, dict) and len(ah) > 0 and not all(bool(v) for v in ah.values()):
        return False
    return True


def compute_bus_ready(
    tick: dict,
    display: AlertDisplayContract,
    out: DriverTickOutcome,
) -> bool:
    """
    Strict readiness: no stacked alerts, no emergency eval path, no routine
    “pending observation” (matched but gated / diversion blocked), no faults,
    and optional adapter health all true.

    ``adapter_health``: optional dict[str, bool]; if absent, adapters are assumed OK (PoC).
    ``system_faults``: any True value is treated as blocking for readiness.

    When ``tick["demo_tablet_readiness"]`` is true (demo mode inputs only), readiness
    uses :func:`compute_demo_tablet_bus_ready` so alerts do not block the tablet line.
    """
    if tick.get("demo_tablet_readiness"):
        return compute_demo_tablet_bus_ready(tick, out)
    if display["alerts_pending"]:
        return False
    if emergency_active_from_outcome(out):
        return False
    if routine_blocks_bus_ready(out):
        return False
    sf = tick.get("system_faults") or {}
    if isinstance(sf, dict) and any(bool(v) for v in sf.values()):
        return False
    ah = tick.get("adapter_health")
    if isinstance(ah, dict) and len(ah) > 0 and not all(bool(v) for v in ah.values()):
        return False
    return True


def backend_output_to_jsonable(contract: BackendOutputContract) -> dict[str, Any]:
    return dict(contract)


class BackendSession:
    """
    One session per backend / runtime process. Drives ``AlertDisplayStack`` and emits
    at most one ``SoundCue`` per ``step`` (highest-priority transition wins).
    """

    __slots__ = (
        "_defer_ready_after_startup",
        "_display",
        "_prev_alerts_pending",
        "_prev_bus_ready",
        "_prev_stop_request",
        "_ready_sound_done",
        "_startup_sound_done",
    )

    def __init__(self) -> None:
        self._display = AlertDisplayStack()
        self._prev_bus_ready = False
        self._prev_alerts_pending = False
        self._prev_stop_request = False
        self._startup_sound_done = False
        self._ready_sound_done = False
        self._defer_ready_after_startup = False

    def step(self, tick: dict, out: DriverTickOutcome) -> BackendOutputContract:
        display = self._display.step(tick, out)
        bus_ready = compute_bus_ready(tick, display, out)
        pending = display["alerts_pending"]
        em_active = emergency_active_from_outcome(out)
        pending_count = len(display["ordered_alerts"])
        alert_just_cleared = self._prev_alerts_pending and not pending

        candidates: list[SoundCue] = []

        if not self._startup_sound_done:
            candidates.append(SoundCue.STARTUP)

        # Demo-only: one INFO cue when a consented passenger episode starts (input flag).
        if self._startup_sound_done and tick.get("demo_consent_intro_tick"):
            candidates.append(SoundCue.INFO)

        if pending and not self._prev_alerts_pending:
            if out.kind != "routine":
                candidates.append(SoundCue.EMERGENCY)
            else:
                candidates.append(SoundCue.SAFETY)

        # Demo tablet story: cue when passenger stop request becomes true (even if other cues also fire).
        demo_story = bool(tick.get("demo_ui_story"))
        if demo_story and self._startup_sound_done:
            pe = tick.get("passenger_event") or {}
            sr = bool(pe.get("stop_request", False))
            if sr and not self._prev_stop_request:
                candidates.append(SoundCue.SAFETY)
            if not bus_ready and self._prev_bus_ready:
                candidates.append(SoundCue.NOT_READY)

        # No READY on the tick alerts drop to zero (clear must be silent).
        # Demo tablet readiness: READY may follow health-only bus_ready rising edge even if alerts moved.
        demo_tablet = bool(tick.get("demo_tablet_readiness"))
        allow_ready_despite_alert_clear = demo_tablet or not alert_just_cleared
        if (
            self._startup_sound_done
            and not self._ready_sound_done
            and bus_ready
            and allow_ready_despite_alert_clear
        ):
            rising = not self._prev_bus_ready
            if rising or self._defer_ready_after_startup:
                candidates.append(SoundCue.READY)

        if SoundCue.STARTUP in candidates and not self._startup_sound_done:
            candidates = [
                c
                for c in candidates
                if c not in (SoundCue.READY, SoundCue.NOT_READY)
            ]

        sound_out = SoundCue.NONE
        best_rank = 0
        for c in candidates:
            r = sound_cue_priority(c)
            if r > best_rank:
                best_rank = r
                sound_out = c

        if sound_out is SoundCue.STARTUP:
            self._startup_sound_done = True
            if bus_ready:
                self._defer_ready_after_startup = True
        elif sound_out is SoundCue.READY:
            self._ready_sound_done = True
            self._defer_ready_after_startup = False

        if not bus_ready:
            self._defer_ready_after_startup = False
            # Allow READY again after a later False → True stabilization cycle.
            self._ready_sound_done = False

        self._prev_bus_ready = bus_ready
        self._prev_alerts_pending = pending
        pe2 = tick.get("passenger_event") or {}
        self._prev_stop_request = bool(pe2.get("stop_request", False))

        return BackendOutputContract(
            primary_alert=display["primary_alert"],
            ordered_alerts=display["ordered_alerts"],
            alerts_pending=display["alerts_pending"],
            camera_auto_display_allowed=display["camera_auto_display_allowed"],
            pending_alert_count=pending_count,
            emergency_active=em_active,
            sound_cue=sound_out.value,
            bus_ready=bus_ready,
        )
