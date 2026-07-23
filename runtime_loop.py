# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — edge PC runtime loop (PoC).

Human demo cadence: one evaluation tick every ``TICK_INTERVAL_SECONDS`` (default 120s;
ROOM_TEST can set ``ROOM_TEST_TICK_SECONDS`` or ``ROOM_TEST_TICK_SEC`` to e.g. 1 for validation).
Pulls one tick from ``adapter_manager`` (fake or future real adapters), runs the same
``evaluate_driver_tick`` path as the harness, logs outcomes, and exits cleanly on Ctrl+C.

No camera, OpenCV, AI, or hardware SDKs in this module.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from alert_display_http_server import maybe_start_alert_display_server
from adapters.adapter_manager import collect_tick_inputs
from adapters.camera_adapter import room_test_schedule_live_camera_perception_start_delay
from adapters.room_test_env import (
    phase1_validation_enabled,
    room_test_enabled,
    room_test_interactive_enabled,
)
from backend_session import BackendSession, backend_output_to_jsonable
from demo_flags import travelmate_demo_enabled
from driver_alert_text import render_driver_alert
from emergency import EmergencyEvent
from thresholds import AlertType, SupportCategory
from room_test_phase1_validation import Phase1TerminalState, run_phase1_validation_tick
from room_test_tick_log import RoomTestTickLogState, log_room_test_tick
from tick_driver_eval import DriverTickOutcome, evaluate_driver_tick

_TRAVELMATE_DEMO = travelmate_demo_enabled()
_ROOM_TEST = room_test_enabled()
_ROOM_TEST_INTERACTIVE = room_test_interactive_enabled()
_PHASE1_VALIDATE = phase1_validation_enabled()


def _truthy_enter_pause_toggle() -> bool:
    raw = os.environ.get("ROOM_TEST_ENTER_PAUSE_TOGGLE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _room_test_enter_pause_available(*, log: logging.Logger) -> bool:
    if not _truthy_enter_pause_toggle():
        return False
    if not _ROOM_TEST:
        log.warning(
            "ROOM_TEST_ENTER_PAUSE_TOGGLE ignored (ROOM_TEST / TRAVELMATE_ROOM_TEST not enabled)."
        )
        return False
    if _ROOM_TEST_INTERACTIVE:
        log.warning(
            "ROOM_TEST_ENTER_PAUSE_TOGGLE incompatible with ROOM_TEST_INTERACTIVE (stdin is busy). "
            "Use a second terminal for control and unset ROOM_TEST_INTERACTIVE here."
        )
        return False
    if _TRAVELMATE_DEMO:
        log.warning(
            "ROOM_TEST_ENTER_PAUSE_TOGGLE disabled while TRAVELMATE_DEMO uses stdin "
            "(emergency ack). Use TRAVELMATE_DEMO_EMERGENCY_ACK_FILE instead, or omit demo env."
        )
        return False
    return True


def _stdin_enter_pause_listener(pause_holder: dict) -> None:
    """Toggle ``pause_holder[\"paused\"]`` each time stdin receives a line (Enter on empty line)."""
    try:
        for _line in iter(sys.stdin.readline, ""):
            paused = pause_holder.setdefault("paused", False)
            pause_holder["paused"] = not paused
            if pause_holder["paused"]:
                print("\n[ROOM_TEST paused] Tick loop halted. Press Enter again to resume.", flush=True)
            else:
                print("[ROOM_TEST resumed]", flush=True)
    except Exception:
        pass


def _wait_while_paused(pause_holder: dict) -> None:
    while pause_holder.get("paused"):
        time.sleep(0.05)


def _sleep_allowing_pause(sleep_s: float, pause_holder: dict | None) -> None:
    if sleep_s <= 0 or pause_holder is None:
        time.sleep(max(0.0, sleep_s))
        return
    remaining = sleep_s
    chunk = min(0.1, remaining)
    while remaining > 0:
        _wait_while_paused(pause_holder)
        step = min(chunk, remaining)
        t0 = time.monotonic()
        time.sleep(step)
        remaining -= time.monotonic() - t0


def _tick_interval_seconds() -> int:
    """ROOM_TEST: prefer ``ROOM_TEST_TICK_SECONDS`` / ``ROOM_TEST_TICK_SEC`` (min 1s)."""
    if _ROOM_TEST:
        for key in ("ROOM_TEST_TICK_SECONDS", "ROOM_TEST_TICK_SEC"):
            raw = os.environ.get(key, "").strip()
            if raw:
                try:
                    return max(1, int(raw))
                except ValueError:
                    pass
        return int(os.environ.get("TRAVELMATE_TICK_INTERVAL_SEC", "120"))
    if _TRAVELMATE_DEMO:
        return int(os.environ.get("TRAVELMATE_DEMO_TICK_SEC", "20"))
    return int(os.environ.get("TRAVELMATE_TICK_INTERVAL_SEC", "120"))


TICK_INTERVAL_SECONDS = _tick_interval_seconds()
_LOGGER_NAME = "travelmate.runtime"
_PUBLIC_STATUS_JSON = Path(__file__).resolve().parent / "public" / "status.json"

_demo_emergency_ack_queue: queue.Queue[bool] = queue.Queue(maxsize=8)


def _demo_stdin_ack_listener() -> None:
    """Background: accept ``ack`` / ``a`` + Enter to acknowledge sticky emergency (non-blocking for loop)."""
    for line in iter(sys.stdin.readline, ""):
        s = line.strip().lower()
        if s in ("ack", "a", "acknowledge", "y", "yes"):
            try:
                _demo_emergency_ack_queue.put_nowait(True)
            except queue.Full:
                pass


def _poll_demo_emergency_ack() -> bool:
    if not _TRAVELMATE_DEMO:
        return False
    got = False
    try:
        while True:
            _demo_emergency_ack_queue.get_nowait()
            got = True
    except queue.Empty:
        pass
    fp = os.environ.get("TRAVELMATE_DEMO_EMERGENCY_ACK_FILE", "").strip()
    if fp:
        p = Path(fp)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        if p.exists():
            try:
                p.unlink()
                got = True
            except OSError:
                pass
    return got


def _write_public_status_snapshot(tick: dict, output: dict, *, tick_seq: int) -> None:
    """Read-only demo snapshot for ``public/index.html`` (overwritten each tick)."""
    dc = tick.get("density_context") or {}
    try:
        onboard = int(dc["passengers_onboard"])
        capacity = int(dc["vehicle_capacity"])
    except (KeyError, TypeError, ValueError):
        onboard, capacity = 0, 0

    primary_row = output["primary_alert"]
    primary_type = primary_row["alert_type"] if primary_row is not None else None
    primary_display = primary_row["message"] if primary_row is not None else None
    evac = tick.get("demo_evacuate_line")
    if isinstance(evac, str) and evac.strip():
        primary_display = evac.strip()
    if (
        tick.get("demo_ui_story")
        and not output["bus_ready"]
        and primary_type is None
    ):
        primary_type = AlertType.SYSTEM_SUPPORT_ALERT.value
        primary_display = render_driver_alert(
            alert_type=AlertType.SYSTEM_SUPPORT_ALERT,
            scenario_matched=True,
            should_alert=True,
            emergency_sticky=None,
            emergency_immediate=None,
            support_categories=_support_categories_from_tick(tick),
        )
    snapshot = {
        "tick_seq": int(tick_seq),
        "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "primary_alert": primary_type,
        "primary_display": primary_display or primary_type,
        "alert_queue": [row["alert_type"] for row in output["ordered_alerts"]],
        "pending_alert_count": output["pending_alert_count"],
        "bus_ready": output["bus_ready"],
        "sound_cue": output["sound_cue"],
        "passengers_onboard": onboard,
        "vehicle_capacity": capacity,
        "emergency_active": output["emergency_active"],
        "active_consent": list(tick.get("demo_active_consent") or []),
    }
    parent = _PUBLIC_STATUS_JSON.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, separators=(",", ":"))
    tmp = _PUBLIC_STATUS_JSON.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, _PUBLIC_STATUS_JSON)


def _support_categories_from_tick(tick: dict) -> set[SupportCategory]:
    raw = tick.get("support_categories")
    if not raw:
        return {SupportCategory.UNDECLARED}
    s = {SupportCategory(x) for x in raw}
    return s if s else {SupportCategory.UNDECLARED}


def _compact_driver_line(message: str) -> str:
    if message.startswith("No action required"):
        if "cleared" in message:
            return "No action required (alert cleared)."
        return "No action required"
    return message


def _alert_type_label(out: DriverTickOutcome) -> str:
    if out.kind == "sticky_pending":
        return "emergency_pending"
    if out.kind == "immediate":
        return "emergency_immediate"
    if out.final_winner is not None:
        return out.final_winner.value
    return "NONE"


def _driver_message_for_outcome(
    out: DriverTickOutcome,
    *,
    support_categories: set[SupportCategory],
) -> str:
    if out.kind == "sticky_pending":
        return render_driver_alert(
            alert_type=None,
            scenario_matched=False,
            should_alert=False,
            emergency_sticky=out.emergency_sticky_next,
            emergency_immediate=None,
            support_categories=support_categories,
        )
    if out.kind == "immediate":
        return render_driver_alert(
            alert_type=None,
            scenario_matched=False,
            should_alert=False,
            emergency_sticky=None,
            emergency_immediate=out.emergency_immediate,
            support_categories=support_categories,
        )
    return render_driver_alert(
        alert_type=out.operational_alert,
        scenario_matched=out.scenario_matched,
        should_alert=out.should_alert,
        emergency_sticky=None,
        emergency_immediate=None,
        support_categories=support_categories,
    )


def _should_alert_effective(out: DriverTickOutcome) -> bool:
    if out.kind != "routine":
        return True
    return out.should_alert


def _configure_logging() -> logging.Logger:
    log = logging.getLogger(_LOGGER_NAME)
    level = logging.DEBUG if _TRAVELMATE_DEMO else logging.INFO
    log.setLevel(level)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        # `converter=` in Formatter.__init__ requires Python 3.12+; assign after init for 3.10/3.11.
        fmt = logging.Formatter(
            fmt="%(asctime)sZ %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        fmt.converter = time.gmtime
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def run_forever() -> None:
    log = _configure_logging()
    ts_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    demo_tag = "TRAVELMATE_DEMO timeline+consent | " if _TRAVELMATE_DEMO else ""
    room_tag = "ROOM_TEST file adapters | " if _ROOM_TEST else ""
    interactive_tag = "ROOM_TEST_INTERACTIVE stdin | " if _ROOM_TEST_INTERACTIVE else ""
    phase1_tag = "PHASE1_VALIDATE trace | " if (_ROOM_TEST and _PHASE1_VALIDATE) else ""
    banner = (
        f"TravelMate AI edge runtime (PoC) | {phase1_tag}{interactive_tag}{room_tag}{demo_tag}1 tick / {TICK_INTERVAL_SECONDS}s | "
        "adapters via collect_tick_inputs() | "
        f"started_utc={ts_start} | Ctrl+C to stop"
    )
    print(banner)
    log.info("startup %s", banner)
    log.info(
        "tablet snapshot: %s (rewritten every %ss); serve the public/ folder over HTTP and open index.html",
        _PUBLIC_STATUS_JSON,
        TICK_INTERVAL_SECONDS,
    )
    if _ROOM_TEST:
        log.info(
            "ROOM_TEST tick spacing: %ss (set ROOM_TEST_TICK_SECONDS=1 for 1s validation cadence)",
            TICK_INTERVAL_SECONDS,
        )
    if _ROOM_TEST and _PHASE1_VALIDATE:
        log.info(
            "ROOM_TEST_PHASE1_VALIDATE: Phase-1 cues only (others forced 0.0); "
            "terminal lines PHASE1_CUES / PHASE1_MIRROR / PHASE1_ALERT; "
            "mirror calls do not change evaluate_driver_tick()"
        )
    if _ROOM_TEST:
        log.info(
            "ROOM_TEST: density and CAN are manual-only (room_density_state.json, "
            "room_can_state.json or env overrides); backend never ramps or timeline-writes them; "
            "ROOM_TEST_JSON logs include source + observer_validation"
        )
        if _TRAVELMATE_DEMO:
            log.info(
                "ROOM_TEST+TRAVELMATE_DEMO: demo timeline merge is OFF; consent episodes "
                "touch support_categories / demo UI flags only, not CAN or density"
            )
    log.info(
        "Optional Phase‑3 display: set TRAVELMATE_ALERT_DISPLAY_HTTP=1 (Flask: requirements_alert_display.txt) "
        "for GET /alerts + /ui + POST /acknowledge_emergency on 0.0.0.0:8765 (stack mirror; POST arms runtime ack)"
    )

    if _ROOM_TEST_INTERACTIVE:
        from room_test_interactive import print_interactive_banner, run_room_test_interactive_stdin

        log.info(
            "ROOM_TEST_INTERACTIVE: prompts share this terminal with tick logs (they may scroll away). "
            "Prefer a second terminal: python room_test_control_terminal.py (unset ROOM_TEST_INTERACTIVE here)."
        )
        print_interactive_banner()
        threading.Thread(
            target=run_room_test_interactive_stdin,
            args=(log,),
            name="travelmate.room_test_interactive",
            daemon=True,
        ).start()
        log.info(
            "ROOM_TEST_INTERACTIVE: sequential prompts (density, vehicle_capacity, speed, …); "
            "empty Enter keeps each [shown] value"
        )
        if _TRAVELMATE_DEMO:
            log.warning(
                "ROOM_TEST_INTERACTIVE: stdin is reserved for density/CAN; emergency ack must use "
                "TRAVELMATE_DEMO_EMERGENCY_ACK_FILE (not ack in this terminal)"
            )

    elif _TRAVELMATE_DEMO:
        threading.Thread(
            target=_demo_stdin_ack_listener,
            name="travelmate.demo_emergency_ack",
            daemon=True,
        ).start()
        print(
            "Demo emergency ack: type ack or a + Enter in this window (or create/delete ack file — "
            "see TRAVELMATE_DEMO_EMERGENCY_ACK_FILE). Does not pause the tick loop."
        )
        log.info(
            "demo emergency ack: stdin (ack/a/yes) or file env TRAVELMATE_DEMO_EMERGENCY_ACK_FILE"
        )

    enter_pause_holder: dict | None = None
    if _room_test_enter_pause_available(log=log):
        enter_pause_holder = {"paused": False}
        threading.Thread(
            target=_stdin_enter_pause_listener,
            args=(enter_pause_holder,),
            name="travelmate.room_test_enter_pause",
            daemon=True,
        ).start()
        print(
            "ROOM_TEST: Press Enter in this window to pause the tick loop; Enter again to resume "
            "(ROOM_TEST_ENTER_PAUSE_TOGGLE)."
        )
        log.info(
            "ROOM_TEST_ENTER_PAUSE_TOGGLE: stdin toggles pause/resume (empty line / any line + Enter)"
        )

    emergency_sticky: EmergencyEvent | None = None
    tick_seq = 0
    alert_display_hub = maybe_start_alert_display_server(log=log)
    backend = BackendSession()
    demo_suppress_fire_after_ack = False
    rt_log_state = RoomTestTickLogState() if _ROOM_TEST else None
    phase1_terminal_state = Phase1TerminalState() if _ROOM_TEST and _PHASE1_VALIDATE else None

    consent_apply = None
    if _TRAVELMATE_DEMO:
        from demo_simulator import apply_demo_consent_tick, demo_consent_debug_label, demo_timeline_debug_label

        consent_apply = apply_demo_consent_tick
        if _ROOM_TEST:
            log.info(
                "ROOM_TEST+TRAVELMATE_DEMO: consent episodes rotate support_categories / demo UI only; "
                "density and CAN stay on room_*_state.json (no demo ramp / timeline)"
            )
        else:
            log.info(
                "demo passenger ramp: see DEMO_TESTING.txt (env TRAVELMATE_DEMO_PASSENGER_RAMP_SEC / _DELTA / _START)"
            )

    paused_before_enter_toggle = (
        bool(enter_pause_holder.get("paused", False))
        if enter_pause_holder is not None
        else False
    )
    room_test_schedule_live_camera_perception_start_delay(log=log)

    try:
        while True:
            if enter_pause_holder is not None:
                now_paused = bool(enter_pause_holder.get("paused", False))
                if paused_before_enter_toggle and not now_paused:
                    room_test_schedule_live_camera_perception_start_delay(log=log)
                paused_before_enter_toggle = now_paused
            if enter_pause_holder is not None:
                _wait_while_paused(enter_pause_holder)
            loop_t0 = time.monotonic()
            tick_seq += 1

            tick = collect_tick_inputs()
            if _TRAVELMATE_DEMO and consent_apply is not None:
                tick = consent_apply(tick, time.monotonic())
                t_ph, t_prof = demo_timeline_debug_label()
                c_ph, c_cat = demo_consent_debug_label()
                log.debug(
                    "DEMO: timeline phase=%s profile=%s consent=%s consent_phase=%s",
                    t_ph,
                    t_prof,
                    c_cat or "",
                    c_ph,
                )

            fire_raw = bool((tick.get("emergency") or {}).get("fire_or_smoke"))
            if _TRAVELMATE_DEMO and not fire_raw:
                demo_suppress_fire_after_ack = False

            tick_driver_em_ack = bool(tick.get("driver_acknowledge_emergency", False))
            demo_route_ack = _poll_demo_emergency_ack()
            http_display_em_ack = (
                alert_display_hub.consume_emergency_acknowledgment_requested()
                if alert_display_hub is not None
                else False
            )
            em_ack = tick_driver_em_ack or demo_route_ack or http_display_em_ack
            if _TRAVELMATE_DEMO and em_ack and fire_raw:
                demo_suppress_fire_after_ack = True
                tick.setdefault("emergency", {})["fire_or_smoke"] = False
            if _TRAVELMATE_DEMO and demo_suppress_fire_after_ack:
                tick.setdefault("emergency", {})["fire_or_smoke"] = False

            cleared_by_ack = False
            es = emergency_sticky
            if es is not None and em_ack:
                ack_ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                channels: list[str] = []
                if http_display_em_ack:
                    channels.append("http_alert_display_ui")
                if tick_driver_em_ack:
                    channels.append("tick_driver_acknowledge_emergency")
                if demo_route_ack:
                    channels.append("demo_stdin_or_demo_ack_file")
                log.info(
                    "emergency_acknowledged ts_utc=%s tick_seq=%s emergency_class=%s source_channels=%s",
                    ack_ts_utc,
                    tick_seq,
                    es.value,
                    ",".join(channels) if channels else "unknown",
                )
                es = None
                cleared_by_ack = True

            out = evaluate_driver_tick(
                tick,
                emergency_sticky=es,
                cleared_by_ack=cleared_by_ack,
            )
            emergency_sticky = out.emergency_sticky_next

            output = backend.step(tick, out)
            if alert_display_hub is not None:
                alert_display_hub.publish(output, tick_seq, tick)
            primary = (
                output["primary_alert"]["alert_type"]
                if output["primary_alert"] is not None
                else "NONE"
            )
            queue_types = [row["alert_type"] for row in output["ordered_alerts"]]
            log.info(
                "tick=%d primary=%s pending=%d queue=%s sound=%s bus_ready=%s emergency=%s",
                tick_seq,
                primary,
                output["pending_alert_count"],
                queue_types,
                output["sound_cue"],
                output["bus_ready"],
                output["emergency_active"],
            )
            if rt_log_state is not None:
                log_room_test_tick(
                    log,
                    rt_log_state,
                    tick_seq=tick_seq,
                    tick=tick,
                    out=out,
                    backend_output=output,
                )
            if phase1_terminal_state is not None:
                run_phase1_validation_tick(
                    tick_seq=tick_seq,
                    tick=tick,
                    out=out,
                    backend_output=output,
                    terminal_state=phase1_terminal_state,
                    log=log,
                )
            log.debug(
                "display_contract %s",
                json.dumps(backend_output_to_jsonable(output), separators=(",", ":")),
            )
            if output["pending_alert_count"] > 1:
                log.debug(
                    "multi_alert_queue tick=%d pending=%d primary=%s queue=%s",
                    tick_seq,
                    output["pending_alert_count"],
                    primary,
                    queue_types,
                )

            _write_public_status_snapshot(tick, output, tick_seq=tick_seq)

            support_categories = _support_categories_from_tick(tick)
            driver_msg = _driver_message_for_outcome(
                out, support_categories=support_categories
            )
            alert_label = _alert_type_label(out)
            short_msg = _compact_driver_line(driver_msg)
            alert_active = _should_alert_effective(out)

            if out.show_diversion_passenger_notify:
                log.info(
                    "simulated_passenger_notify template=route_diversion_active tick=%d",
                    tick_seq,
                )
            if out.diversion_blocked:
                log.info(
                    "policy diversion_blocked_vehicle_motion tick=%d motion=%.4f stationary=%s",
                    tick_seq,
                    out.vehicle_motion_level,
                    out.can_vehicle_stationary,
                )

            log.info(
                "tick=%d alert_type=%s alert_active=%s driver=%r",
                tick_seq,
                alert_label,
                alert_active,
                short_msg,
            )
            print(
                f"tick={tick_seq} alert={alert_label} active={'YES' if alert_active else 'NO'} | {short_msg}"
            )

            elapsed = time.monotonic() - loop_t0
            sleep_s = max(0.0, TICK_INTERVAL_SECONDS - elapsed)
            _sleep_allowing_pause(sleep_s, enter_pause_holder)

    except KeyboardInterrupt:
        log.info("shutdown signal received (KeyboardInterrupt); exiting cleanly.")
        print("\nShutdown complete.")
        sys.exit(0)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()
