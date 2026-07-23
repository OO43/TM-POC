# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — optional demo-only **input** shaping (PoC).

Two layers (both active only when ``TRAVELMATE_DEMO`` / ``DEMO_MODE`` is set):

1. **Timeline** — merged inside ``adapters.adapter_manager.collect_tick_inputs()`` via
   ``merge_demo_timeline_inputs()`` so fake adapter outputs follow a repeating A→E phase
   machine. Does not import production adapters or ``evaluate_driver_tick``.

2. **Consent episodes** — merged in ``runtime_loop`` after collection via
   ``apply_demo_consent_tick()`` (policy-only categories, separate timer).

Environment (defaults in parentheses):

  • ``TRAVELMATE_DEMO_PHASE_SEC`` — duration of phases A, B, C, E (10).
  • ``TRAVELMATE_DEMO_DENSITY_DROP_INTERVAL_SEC`` — seconds between −5 passenger steps in
    phase D (defaults to same as phase duration; set to 120 for a slower density ramp).
  • Consent: ``TRAVELMATE_DEMO_FIRST_CONSENT_SEC`` (30), ``TRAVELMATE_DEMO_CONSENT_INTERVAL_SEC``
    (600), ``TRAVELMATE_DEMO_CONSENT_ACTIVE_SEC`` (18), ``TRAVELMATE_DEMO_POST_CLEAR_SEC`` (5).
  • Tablet readiness: ``TRAVELMATE_DEMO_ADAPTER_HEALTH_DELAY_SEC`` (10) then all subsystem OK;
    optional ``TRAVELMATE_DEMO_FAULT_INTERVAL_SEC`` (0=off), ``TRAVELMATE_DEMO_FAULT_DURATION_SEC`` (10).
  • Passenger ramp (tablet density): ``TRAVELMATE_DEMO_PASSENGER_RAMP`` (1) — every
    ``TRAVELMATE_DEMO_PASSENGER_RAMP_SEC`` (120) subtract ``TRAVELMATE_DEMO_PASSENGER_RAMP_DELTA`` (10)
    from ``TRAVELMATE_DEMO_PASSENGER_RAMP_START`` (50) until 0, then full demo reset. Set ramp to 0 to disable.
  • Tablet UI story (default on): ``TRAVELMATE_DEMO_UI_STORY`` (1) — first ``TRAVELMATE_DEMO_ADAPTER_HEALTH_DELAY_SEC``
    (10) seconds: bus not ready, calm, no alerts; then alerts mainly when onboard > 10; periodic fire/smoke.
    Recurring bus-not-ready windows: ``TRAVELMATE_DEMO_STORY_UNREADY_WINDOWS`` (0=off).
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

_log = logging.getLogger("travelmate.demo")

# --- Timeline -----------------------------------------------------------------

_PHASE_SEC = float(os.environ.get("TRAVELMATE_DEMO_PHASE_SEC", "10"))
_DENSITY_DROP_INTERVAL_SEC = float(
    os.environ.get(
        "TRAVELMATE_DEMO_DENSITY_DROP_INTERVAL_SEC",
        os.environ.get("TRAVELMATE_DEMO_PHASE_SEC", "10"),
    )
)

_ADAPTER_HEALTH_DELAY_SEC = float(
    os.environ.get("TRAVELMATE_DEMO_ADAPTER_HEALTH_DELAY_SEC", "10")
)
_DEMO_FAULT_INTERVAL_SEC = float(os.environ.get("TRAVELMATE_DEMO_FAULT_INTERVAL_SEC", "0"))
_DEMO_FAULT_DURATION_SEC = float(os.environ.get("TRAVELMATE_DEMO_FAULT_DURATION_SEC", "10"))

_DEMO_ADAPTER_KEYS: tuple[str, ...] = ("camera", "can", "ble", "audio", "display")

_RAMP_INTERVAL_SEC = float(os.environ.get("TRAVELMATE_DEMO_PASSENGER_RAMP_SEC", "120"))
_RAMP_DELTA = max(1, int(os.environ.get("TRAVELMATE_DEMO_PASSENGER_RAMP_DELTA", "10")))
_RAMP_START = max(0, int(os.environ.get("TRAVELMATE_DEMO_PASSENGER_RAMP_START", "50")))


def _passenger_ramp_enabled() -> bool:
    return os.environ.get("TRAVELMATE_DEMO_PASSENGER_RAMP", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _ui_story_enabled() -> bool:
    return os.environ.get("TRAVELMATE_DEMO_UI_STORY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


_STORY_CYCLE_SEC = max(120.0, float(os.environ.get("TRAVELMATE_DEMO_STORY_CYCLE_SEC", "540")))
_STORY_EM_AT = float(os.environ.get("TRAVELMATE_DEMO_STORY_EMERGENCY_AT", "95"))
_STORY_EM_HOLD = max(1.0, float(os.environ.get("TRAVELMATE_DEMO_STORY_EMERGENCY_HOLD_SEC", "10")))
_STORY_UR_AT = float(os.environ.get("TRAVELMATE_DEMO_STORY_UNREADY_AT", "260"))
_STORY_UR_HOLD = max(1.0, float(os.environ.get("TRAVELMATE_DEMO_STORY_UNREADY_HOLD_SEC", "22")))
_STORY_UNREADY_WINDOWS = os.environ.get(
    "TRAVELMATE_DEMO_STORY_UNREADY_WINDOWS", "0"
).strip().lower() in ("1", "true", "yes")


class DemoTimelineSimulator:
    """
    Repeating demo cadence: stacked policy + scenario stress (profile 0), then other
    profiles, then calm / density recovery. Mutates ticks only via ``apply_to_tick``.
    """

    __slots__ = (
        "_capacity",
        "_d_next_drop_mono",
        "_fault_end_mono",
        "_next_fault_mono",
        "_onboard",
        "_origin_mono",
        "_phase",
        "_phase_start_mono",
        "_profile_idx",
        "_ramp_next_mono",
        "_ramp_onboard",
        "_freeze_for_ramp_this_tick",
    )

    def __init__(self) -> None:
        self._origin_mono: float | None = None
        self._phase: str = "A"
        self._phase_start_mono: float = 0.0
        self._profile_idx: int = 0
        self._capacity: int = 50
        self._onboard: int = 55
        self._d_next_drop_mono: float = 0.0
        self._fault_end_mono: float | None = None
        self._next_fault_mono: float | None = None
        self._ramp_onboard: int | None = None
        self._ramp_next_mono: float | None = None
        self._freeze_for_ramp_this_tick: bool = False

    @property
    def timeline_phase(self) -> str:
        return self._phase

    @property
    def profile_index(self) -> int:
        return self._profile_idx % 3

    def apply_to_tick(self, tick: dict[str, Any], now_mono: float) -> None:
        if self._origin_mono is None:
            self._origin_mono = now_mono
            self._phase = "A"
            self._phase_start_mono = now_mono
            self._bootstrap_onboard()
            self._d_next_drop_mono = now_mono + _DENSITY_DROP_INTERVAL_SEC

        in_em = False
        in_ur = False
        if _ui_story_enabled():
            in_em, in_ur = self._story_cycle_flags(now_mono)
            self._freeze_for_ramp_this_tick = bool(in_em or in_ur)
            self._patch_tick_minimal_story(tick)
        else:
            self._freeze_for_ramp_this_tick = False
            self._advance(now_mono)
            self._patch_tick(tick)
            self._apply_tablet_readiness_inputs(tick, now_mono)

        self._apply_passenger_ramp_overlay(tick, now_mono)

        if _ui_story_enabled():
            self._apply_ui_story_tick(tick, now_mono, in_em=in_em, in_ur=in_ur)

        pe = tick.get("passenger_event") or {}
        dc = tick.get("density_context") or {}
        _log.debug(
            "DEMO: timeline phase=%s profile=%d onboard=%s/%s stop_request=%s ramp=%s",
            self._phase,
            self.profile_index,
            dc.get("passengers_onboard"),
            dc.get("vehicle_capacity"),
            pe.get("stop_request"),
            self._ramp_onboard if _passenger_ramp_enabled() else "off",
        )

    def _bootstrap_onboard(self) -> None:
        self._onboard = 55

    def _advance(self, now: float) -> None:
        if self._phase == "D":
            interval = max(0.001, _DENSITY_DROP_INTERVAL_SEC)
            while now >= self._d_next_drop_mono and self._onboard > self._capacity:
                self._onboard = max(0, self._onboard - 5)
                self._d_next_drop_mono += interval
            if self._onboard <= self._capacity:
                self._enter("E", now)
            return

        if self._phase == "E":
            if now - self._phase_start_mono >= _phase_sec():
                self._profile_idx += 1
                self._bootstrap_onboard()
                self._enter("A", now)
            return

        if now - self._phase_start_mono >= _phase_sec():
            nxt = {"A": "B", "B": "C", "C": "D"}.get(self._phase)
            if nxt == "D":
                self._enter("D", now)
                self._d_next_drop_mono = now + max(0.001, _DENSITY_DROP_INTERVAL_SEC)
            elif nxt:
                self._enter(nxt, now)

    def _enter(self, ph: str, now: float) -> None:
        self._phase = ph
        self._phase_start_mono = now

    def _patch_tick(self, tick: dict[str, Any]) -> None:
        dc = tick.setdefault("density_context", {})
        dc["vehicle_capacity"] = self._capacity
        dc["passengers_onboard"] = self._onboard
        tick["density"] = self._onboard / float(self._capacity)

        oc = tick.setdefault("observed_cues", {})
        for k in list(oc.keys()):
            oc[k] = 0.0

        can = tick.setdefault("can", {})
        can.update(
            {
                "speed": 0.12,
                "braking_intensity": 0.08,
                "turn_intensity": 0.05,
                "doors_open": False,
                "ramp_deployed": False,
                "vehicle_stationary": False,
            }
        )

        pe = tick.setdefault("passenger_event", {})
        pe.setdefault("source", "app")
        pe["consented"] = True
        pe["stop_request"] = False

        tick["journey_phase"] = "in_motion"
        tick["support_categories"] = ["undeclared"]

        prof = self.profile_index
        ph = self._phase
        if prof == 0:
            self._patch_profile0(ph, tick, oc, can, pe)
        elif prof == 1:
            self._patch_profile1(ph, tick, oc, can, pe)
        else:
            self._patch_profile2(ph, tick, oc, can, pe)

        if ph == "E" and self._onboard > self._capacity:
            self._onboard = self._capacity
            dc["passengers_onboard"] = self._onboard
            tick["density"] = self._onboard / float(self._capacity)

    def _apply_tablet_readiness_inputs(self, tick: dict[str, Any], now_mono: float) -> None:
        """
        Demo tablet contract: ``demo_tablet_readiness`` + ``adapter_health`` / ``system_faults``
        only (interpreted in ``compute_demo_tablet_bus_ready``). Does not touch alert logic.
        """
        tick["demo_tablet_readiness"] = True
        origin = self._origin_mono or now_mono
        delay = max(0.0, _ADAPTER_HEALTH_DELAY_SEC)

        if now_mono < origin + delay:
            tick["adapter_health"] = {k: False for k in _DEMO_ADAPTER_KEYS}
            tick["system_faults"] = {}
            return

        healthy_ah = {k: True for k in _DEMO_ADAPTER_KEYS}
        if _DEMO_FAULT_INTERVAL_SEC <= 0.0:
            tick["adapter_health"] = healthy_ah
            tick["system_faults"] = {}
            return

        interval = max(0.001, _DEMO_FAULT_INTERVAL_SEC)
        duration = max(0.001, _DEMO_FAULT_DURATION_SEC)

        if self._fault_end_mono is not None and now_mono >= self._fault_end_mono:
            self._fault_end_mono = None

        if self._next_fault_mono is None:
            self._next_fault_mono = origin + delay + interval

        if self._fault_end_mono is None and now_mono >= self._next_fault_mono:
            self._fault_end_mono = now_mono + duration
            self._next_fault_mono = now_mono + interval

        in_fault = self._fault_end_mono is not None and now_mono < self._fault_end_mono
        ah = dict(healthy_ah)
        sf: dict[str, bool] = {}
        if in_fault:
            sf["display_fault"] = True
            ah["display"] = False
        tick["adapter_health"] = ah
        tick["system_faults"] = sf

    def _full_reset_for_ramp_cycle(self, now: float) -> None:
        """After passenger ramp hits zero: restart timeline, health clock, and ramp counter."""
        self._origin_mono = now
        self._phase = "A"
        self._phase_start_mono = now
        self._profile_idx = 0
        self._bootstrap_onboard()
        self._d_next_drop_mono = now + max(0.001, _DENSITY_DROP_INTERVAL_SEC)
        self._fault_end_mono = None
        self._next_fault_mono = None
        self._ramp_onboard = _RAMP_START
        self._ramp_next_mono = now + max(0.001, _RAMP_INTERVAL_SEC)
        self._freeze_for_ramp_this_tick = False

    def _story_cycle_flags(self, now_mono: float) -> tuple[bool, bool]:
        origin = self._origin_mono or now_mono
        delay = max(0.0, _ADAPTER_HEALTH_DELAY_SEC)
        t_adj = now_mono - origin - delay
        if t_adj < 0:
            return False, False
        r = t_adj % _STORY_CYCLE_SEC
        in_em = _STORY_EM_AT <= r < _STORY_EM_AT + _STORY_EM_HOLD
        in_ur = False
        if _STORY_UNREADY_WINDOWS:
            in_ur = (not in_em) and (_STORY_UR_AT <= r < _STORY_UR_AT + _STORY_UR_HOLD)
        return in_em, in_ur

    def _patch_tick_minimal_story(self, tick: dict[str, Any]) -> None:
        dc = tick.setdefault("density_context", {})
        dc["vehicle_capacity"] = self._capacity
        dc["passengers_onboard"] = self._onboard
        tick["density"] = self._onboard / float(self._capacity)
        oc = tick.setdefault("observed_cues", {})
        for k in list(oc.keys()):
            oc[k] = 0.0
        can = tick.setdefault("can", {})
        can.update(
            {
                "speed": 0.1,
                "braking_intensity": 0.06,
                "turn_intensity": 0.04,
                "doors_open": False,
                "ramp_deployed": False,
                "vehicle_stationary": False,
            }
        )
        pe = tick.setdefault("passenger_event", {})
        pe.setdefault("source", "app")
        pe["consented"] = True
        pe["stop_request"] = False
        tick["journey_phase"] = "in_motion"
        tick["support_categories"] = ["undeclared"]

    def _story_calm_operational(self, tick: dict[str, Any]) -> None:
        oc = tick.setdefault("observed_cues", {})
        for k in list(oc.keys()):
            oc[k] = 0.0
        can = tick.setdefault("can", {})
        can.update(
            {
                "speed": 0.08,
                "braking_intensity": 0.05,
                "turn_intensity": 0.03,
                "doors_open": False,
                "ramp_deployed": False,
                "vehicle_stationary": False,
            }
        )
        pe = tick.setdefault("passenger_event", {})
        pe.setdefault("source", "app")
        pe["consented"] = True
        pe["stop_request"] = False
        tick["journey_phase"] = "in_motion"
        tick["support_categories"] = ["undeclared"]

    def _story_apply_passenger_band(self, tick: dict[str, Any], p: int) -> None:
        tick.pop("demo_evacuate_line", None)
        if p <= 0:
            self._story_calm_operational(tick)
            return
        if p == 1:
            self._story_calm_operational(tick)
            tick["journey_phase"] = "end_of_route"
            oc = tick.setdefault("observed_cues", {})
            oc["prolonged_standing"] = 0.37
            oc["unstable_posture"] = 0.32
            tick["demo_evacuate_line"] = (
                "Last destination — evacuate passengers before departure."
            )
            return
        if p <= 10:
            self._story_calm_operational(tick)
            return
        tick["journey_phase"] = "in_motion"
        tick["support_categories"] = ["undeclared"]
        pe = tick.setdefault("passenger_event", {})
        pe["consented"] = True
        pe["stop_request"] = True
        can = tick.setdefault("can", {})
        can.update(
            {
                "speed": 0.58,
                "braking_intensity": 0.42,
                "turn_intensity": 0.35,
                "doors_open": False,
                "ramp_deployed": False,
                "vehicle_stationary": False,
            }
        )
        oc = tick.setdefault("observed_cues", {})
        oc["unstable_posture"] = 0.52
        oc["frequent_balance_correction"] = 0.48
        oc["prolonged_standing"] = 0.41

    def _apply_ui_story_tick(
        self,
        tick: dict[str, Any],
        now_mono: float,
        *,
        in_em: bool,
        in_ur: bool,
    ) -> None:
        if not _ui_story_enabled():
            tick.pop("demo_ui_story", None)
            tick.pop("demo_evacuate_line", None)
            return

        tick["demo_tablet_readiness"] = True
        tick["demo_ui_story"] = True
        origin = self._origin_mono or now_mono
        em = tick.setdefault("emergency", {})

        if in_em:
            for k in (
                "passenger_collapse_or_fall",
                "fire_or_smoke",
                "altercation",
                "severe_distress",
            ):
                em[k] = k == "fire_or_smoke"
            tick["adapter_health"] = {k: True for k in _DEMO_ADAPTER_KEYS}
            tick["system_faults"] = {}
            self._story_calm_operational(tick)
            tick.pop("demo_evacuate_line", None)
            return

        for k in (
            "passenger_collapse_or_fall",
            "fire_or_smoke",
            "altercation",
            "severe_distress",
        ):
            em[k] = False

        if in_ur:
            tick["adapter_health"] = {k: False for k in _DEMO_ADAPTER_KEYS}
            tick["system_faults"] = {"display_fault": True}
            dc = tick.setdefault("density_context", {})
            dc["passengers_onboard"] = 0
            dc["vehicle_capacity"] = self._capacity
            tick["density"] = 0.0
            self._story_calm_operational(tick)
            tick.pop("demo_evacuate_line", None)
            return

        if now_mono < origin + _ADAPTER_HEALTH_DELAY_SEC:
            tick["adapter_health"] = {k: False for k in _DEMO_ADAPTER_KEYS}
            tick["system_faults"] = {}
            self._story_calm_operational(tick)
            tick.pop("demo_evacuate_line", None)
            return

        tick["adapter_health"] = {k: True for k in _DEMO_ADAPTER_KEYS}
        tick["system_faults"] = {}

        dc = tick.setdefault("density_context", {})
        p = int(dc.get("passengers_onboard", 0))
        self._story_apply_passenger_band(tick, p)

    def _apply_passenger_ramp_overlay(self, tick: dict[str, Any], now_mono: float) -> None:
        """
        Visible passenger count for the tablet: step down on a wall clock until 0, then full reset.
        Overrides density_context written by the phase machine for this tick only.
        """
        if not _passenger_ramp_enabled() or _RAMP_START <= 0:
            return

        origin = self._origin_mono or now_mono
        interval = max(0.001, _RAMP_INTERVAL_SEC)

        if self._ramp_onboard is None:
            self._ramp_onboard = _RAMP_START
            self._ramp_next_mono = origin + interval

        hit_zero = False
        freeze = _ui_story_enabled() and self._freeze_for_ramp_this_tick
        while (
            not freeze
            and now_mono >= self._ramp_next_mono
            and self._ramp_onboard > 0
        ):
            self._ramp_onboard = max(0, self._ramp_onboard - _RAMP_DELTA)
            self._ramp_next_mono += interval
            if self._ramp_onboard == 0:
                hit_zero = True
                break

        dc = tick.setdefault("density_context", {})
        dc["vehicle_capacity"] = self._capacity
        dc["passengers_onboard"] = int(self._ramp_onboard)
        tick["density"] = dc["passengers_onboard"] / float(self._capacity)

        if hit_zero:
            _log.debug(
                "DEMO: passenger_ramp reached 0; resetting demo (next start=%s)",
                _RAMP_START,
            )
            self._full_reset_for_ramp_cycle(now_mono)

    def _instability_stress(self, oc: dict[str, float], can: dict[str, Any]) -> None:
        # Keep prolonged_standing below STANDING_MOTION_RISK (0.44) so INSTABILITY_RISK can win.
        oc["unstable_posture"] = 0.52
        oc["frequent_balance_correction"] = 0.48
        oc["prolonged_standing"] = 0.41
        can.update(
            {"speed": 0.58, "braking_intensity": 0.42, "turn_intensity": 0.35}
        )

    def _calm(self, oc: dict[str, float], can: dict[str, Any]) -> None:
        can.update(
            {"speed": 0.1, "braking_intensity": 0.06, "turn_intensity": 0.04}
        )

    def _patch_profile0(
        self,
        ph: str,
        tick: dict[str, Any],
        oc: dict[str, float],
        can: dict[str, Any],
        pe: dict[str, Any],
    ) -> None:
        tick["support_categories"] = ["undeclared"]
        if ph == "A":
            pe["stop_request"] = True
            pe["consented"] = True
            self._instability_stress(oc, can)
        elif ph == "B":
            pe["stop_request"] = False
            self._instability_stress(oc, can)
        elif ph == "C":
            pe["stop_request"] = False
            self._calm(oc, can)
        elif ph in ("D", "E"):
            pe["stop_request"] = False
            self._calm(oc, can)

    def _patch_profile1(
        self,
        ph: str,
        tick: dict[str, Any],
        oc: dict[str, float],
        can: dict[str, Any],
        pe: dict[str, Any],
    ) -> None:
        tick["support_categories"] = ["elderly_support"]
        pe["stop_request"] = False
        if ph == "A":
            tick["journey_phase"] = "approaching_stop"
            oc["near_door_area"] = 1.0
            oc["distress_motion_pattern"] = 0.22
            oc["prolonged_standing"] = 0.42
            can.update(
                {"speed": 0.38, "braking_intensity": 0.28, "turn_intensity": 0.12}
            )
        elif ph == "B":
            tick["journey_phase"] = "approaching_stop"
            oc["near_door_area"] = 0.22
            oc["distress_motion_pattern"] = 0.2
            oc["prolonged_standing"] = 0.4
            can.update(
                {"speed": 0.38, "braking_intensity": 0.28, "turn_intensity": 0.12}
            )
        elif ph in ("C", "D", "E"):
            self._calm(oc, can)

    def _patch_profile2(
        self,
        ph: str,
        tick: dict[str, Any],
        oc: dict[str, float],
        can: dict[str, Any],
        pe: dict[str, Any],
    ) -> None:
        tick["support_categories"] = ["wheelchair"]
        pe["stop_request"] = False
        if ph == "A":
            oc["large_mobility_device_present"] = 0.55
            oc["near_priority_space"] = 0.12
            oc["near_stairs_or_upper_deck"] = 0.48
            can.update(
                {"speed": 0.62, "braking_intensity": 0.35, "turn_intensity": 0.28}
            )
        elif ph == "B":
            oc["large_mobility_device_present"] = 0.55
            oc["near_priority_space"] = 0.12
            oc["near_stairs_or_upper_deck"] = 0.15
            can.update(
                {"speed": 0.62, "braking_intensity": 0.35, "turn_intensity": 0.28}
            )
        elif ph == "C":
            oc["large_mobility_device_present"] = 0.3
            self._calm(oc, can)
        elif ph in ("D", "E"):
            oc["large_mobility_device_present"] = 0.08
            self._calm(oc, can)


def _phase_sec() -> float:
    return max(0.001, _PHASE_SEC)


_timeline_singleton: DemoTimelineSimulator | None = None


def merge_demo_timeline_inputs(tick: dict[str, Any], now_mono: float) -> None:
    """Apply repeating demo phases by mutating ``tick`` (adapter output shape)."""
    global _timeline_singleton
    if _timeline_singleton is None:
        _timeline_singleton = DemoTimelineSimulator()
    _timeline_singleton.apply_to_tick(tick, now_mono)


def demo_timeline_debug_label() -> tuple[str, int]:
    if _timeline_singleton is None:
        return ("-", -1)
    return (_timeline_singleton.timeline_phase, _timeline_singleton.profile_index)


# --- Consent episodes (policy-only categories) --------------------------------

_CONSENT_CYCLE: tuple[str, ...] = (
    "mobility_support",
    "visual_impairment",
    "medical_sensitivity",
    "child_support",
    "pregnancy_support",
    "elderly_support",
)

_FIRST_CONSENT_DELAY_SEC = float(os.environ.get("TRAVELMATE_DEMO_FIRST_CONSENT_SEC", "30"))
_CONSENT_INTERVAL_SEC = float(os.environ.get("TRAVELMATE_DEMO_CONSENT_INTERVAL_SEC", "600"))
_CONSENT_ACTIVE_SEC = float(os.environ.get("TRAVELMATE_DEMO_CONSENT_ACTIVE_SEC", "18"))
_POST_CLEAR_SEC = float(os.environ.get("TRAVELMATE_DEMO_POST_CLEAR_SEC", "5"))


def _deep_merge_cues(target: dict[str, Any], patch: dict[str, float]) -> None:
    oc = target.setdefault("observed_cues", {})
    for k, v in patch.items():
        oc[k] = float(v)


class DemoConsentSimulator:
    """Consent episode timer; runs after timeline merge in the runtime loop."""

    __slots__ = (
        "_cat_index",
        "_next_episode_mono",
        "_origin_mono",
        "_phase",
        "_phase_start_mono",
        "_session_category",
    )

    def __init__(self) -> None:
        self._origin_mono: float | None = None
        self._phase: str = "idle"
        self._phase_start_mono: float = 0.0
        self._next_episode_mono: float = 0.0
        self._cat_index: int = 0
        self._session_category: str | None = None

    def apply(self, base_tick: dict[str, Any], now_mono: float) -> dict[str, Any]:
        if self._origin_mono is None:
            self._origin_mono = now_mono
            self._next_episode_mono = now_mono + _FIRST_CONSENT_DELAY_SEC

        self._transition_idle_to_intro(now_mono)

        if self._phase == "intro":
            cat = self._session_category
            assert cat is not None
            self._phase = "active"
            self._phase_start_mono = now_mono
            return self._build_consent_tick(base_tick, cat, intro=True)

        if self._phase == "active":
            assert self._session_category is not None
            if now_mono - self._phase_start_mono >= _CONSENT_ACTIVE_SEC:
                self._phase = "post_clear"
                self._phase_start_mono = now_mono
                self._session_category = None
                return self._baseline_tick(base_tick)
            return self._build_consent_tick(base_tick, self._session_category, intro=False)

        if self._phase == "post_clear":
            out = self._baseline_tick(base_tick)
            if now_mono - self._phase_start_mono >= _POST_CLEAR_SEC:
                self._phase = "idle"
                self._next_episode_mono = now_mono + _CONSENT_INTERVAL_SEC
            return out

        o = copy.deepcopy(base_tick)
        o["demo_active_consent"] = []
        o["demo_consent_intro_tick"] = False
        o["demo_phase"] = "idle"
        return o

    def debug_label(self) -> tuple[str, str | None]:
        return self._phase, self._session_category

    def _transition_idle_to_intro(self, now_mono: float) -> None:
        if self._phase != "idle":
            return
        if now_mono < self._next_episode_mono:
            return
        self._phase = "intro"
        self._session_category = _CONSENT_CYCLE[self._cat_index % len(_CONSENT_CYCLE)]
        self._cat_index += 1

    def _baseline_tick(self, base_tick: dict[str, Any]) -> dict[str, Any]:
        o = copy.deepcopy(base_tick)
        o["demo_active_consent"] = []
        o["demo_consent_intro_tick"] = False
        o["demo_phase"] = "post_clear"
        return o

    def _build_consent_tick(
        self,
        base_tick: dict[str, Any],
        category: str,
        *,
        intro: bool,
    ) -> dict[str, Any]:
        from adapters.room_test_env import room_test_enabled

        o = copy.deepcopy(base_tick)
        o["support_categories"] = [category]
        o["demo_active_consent"] = [category]
        o["demo_consent_intro_tick"] = intro
        o["demo_phase"] = "intro" if intro else "active"
        if room_test_enabled():
            # Consent appearance / UI fields only; CAN, density, cues, BLE, journey_phase,
            # passenger_event stay authoritative from ROOM_TEST adapters and files.
            return o

        can = dict(o.get("can") or {})
        dc = dict(o.get("density_context") or {})
        pe = dict(o.get("passenger_event") or {})
        o["can"] = can
        o["density_context"] = dc
        pe["stop_request"] = False
        o["passenger_event"] = pe

        if category == "mobility_support":
            o["journey_phase"] = "approaching_stop"
            can.update({"speed": 0.35, "braking_intensity": 0.28, "turn_intensity": 0.12})
            dc["passengers_onboard"] = 35
            dc["vehicle_capacity"] = 50
            o["density"] = 35 / 50.0
            _deep_merge_cues(
                o,
                {
                    "near_door_area": 1.0,
                    "distress_motion_pattern": 0.22,
                    "prolonged_standing": 0.42,
                },
            )
        elif category == "visual_impairment":
            o["journey_phase"] = "approaching_stop"
            can.update({"speed": 0.22, "braking_intensity": 0.18, "turn_intensity": 0.08})
            _deep_merge_cues(
                o,
                {
                    "navigation_aid_candidate": 0.42,
                    "navigation_aid_in_use": 0.42,
                    "nav_aid_floor_contact": 0.82,
                    "nav_aid_gait_coupling": 0.82,
                    "nav_aid_vertical_load": 0.82,
                    "nav_aid_unilateral_bias": 0.82,
                },
            )
            o["ble"] = {"enabled": True, "zone": "rear", "confidence": 0.72}
        elif category == "medical_sensitivity":
            o["journey_phase"] = "in_motion"
            can.update({"speed": 0.68, "braking_intensity": 0.52, "turn_intensity": 0.28})
            _deep_merge_cues(
                o,
                {
                    "unstable_posture": 0.48,
                    "frequent_balance_correction": 0.44,
                },
            )
        elif category == "child_support":
            o["journey_phase"] = "in_motion"
            can.update({"speed": 0.66, "braking_intensity": 0.32, "turn_intensity": 0.24})
            _deep_merge_cues(o, {"rapid_erratic_motion": 0.56})
        elif category == "pregnancy_support":
            o["journey_phase"] = "in_motion"
            can.update({"speed": 0.4, "braking_intensity": 0.28, "turn_intensity": 0.15})
            _deep_merge_cues(
                o,
                {
                    "leaning_without_support": 0.43,
                    "prolonged_standing": 0.4,
                },
            )
        elif category == "elderly_support":
            o["journey_phase"] = "approaching_stop"
            can.update({"speed": 0.32, "braking_intensity": 0.22, "turn_intensity": 0.12})
            dc["passengers_onboard"] = 48
            dc["vehicle_capacity"] = 50
            o["density"] = 48 / 50.0
            _deep_merge_cues(
                o,
                {
                    "near_door_area": 0.56,
                    "distress_motion_pattern": 0.22,
                    "prolonged_standing": 0.42,
                },
            )
        else:
            o["journey_phase"] = "in_motion"

        return o


_consent_singleton: DemoConsentSimulator | None = None


def apply_demo_consent_tick(base_tick: dict[str, Any], now_mono: float) -> dict[str, Any]:
    global _consent_singleton
    if _consent_singleton is None:
        _consent_singleton = DemoConsentSimulator()
    return _consent_singleton.apply(base_tick, now_mono)


def demo_consent_debug_label() -> tuple[str, str | None]:
    global _consent_singleton
    if _consent_singleton is None:
        return ("idle", None)
    return _consent_singleton.debug_label()
