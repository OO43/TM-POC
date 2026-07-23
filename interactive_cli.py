# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — interactive human-as-adapter CLI (PoC).

Simulates full tick payloads: observed cues, consent (policy only), CAN, density,
passenger app hooks, optional emergency. Uses the same evaluation as main via
tick_driver_eval.evaluate_driver_tick (no duplicate arbitration logic).

Use ``python interactive_cli.py --fake-adapters`` to drive the same flow from
``adapters.adapter_manager.collect_tick_inputs()`` (no field prompts).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import fields as dc_fields

from backend_session import BackendSession
from ble_proximity import VehicleZone
from driver_alert_text import render_alert_cleared, render_driver_alert
from emergency import EmergencyEvent
from journey_phase import JourneyPhase
from observed_cues import ObservedCues
from thresholds import AlertType, SupportCategory
from tick_driver_eval import evaluate_driver_tick

# Consent tokens: policy only; heart_condition maps to same threshold row as medical_sensitivity.
_CONSENT_ALIASES: dict[str, SupportCategory] = {
    "medical_sensitivity": SupportCategory.MEDICAL_SENSITIVITY,
    "heart_condition": SupportCategory.MEDICAL_SENSITIVITY,
    "pregnancy_support": SupportCategory.PREGNANCY_SUPPORT,
    "child_support": SupportCategory.CHILD_SUPPORT,
    "elderly_support": SupportCategory.ELDERLY_SUPPORT,
    "visual_impairment": SupportCategory.VISUAL_IMPAIRMENT,
    "mobility_support": SupportCategory.MOBILITY_SUPPORT,
}


def _parse_float_or_yn(raw: str, previous: float) -> float:
    s = raw.strip().lower()
    if not s:
        return previous
    if s in ("y", "yes", "true", "1"):
        return 1.0
    if s in ("n", "no", "false", "0"):
        return 0.0
    try:
        v = float(s)
    except ValueError:
        print(f"    Invalid value {raw!r}; keeping {previous:g}.")
        return previous
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _prompt_line(label: str, previous: str) -> str:
    s = input(f"  {label} [{previous}] (empty=keep): ").strip()
    return s if s else previous


def _prompt_float(label: str, previous: float) -> float:
    s = input(f"  {label} [{previous:g}] 0-1 or y/n (empty=keep): ").strip()
    return _parse_float_or_yn(s, previous) if s else previous


def _prompt_yn(label: str, previous: bool) -> bool:
    prev = "y" if previous else "n"
    s = _prompt_line(label, prev).lower()
    if not s or s == prev:
        return previous
    return s in ("y", "yes", "true", "1")


def _prompt_observed_cues(prev: dict[str, float]) -> dict[str, float]:
    print("Observed cues [0-1 or y/n; empty keeps previous]:")
    out = dict(prev)
    for f in dc_fields(ObservedCues):
        out[f.name] = _prompt_float(f.name.replace("_", " "), out.get(f.name, 0.0))
    return out


def _prompt_support_categories(prev: frozenset[SupportCategory]) -> frozenset[SupportCategory]:
    print(
        "Consent flags (policy only, comma-separated; empty=keep).\n"
        "  medical_sensitivity, heart_condition, pregnancy_support, child_support,\n"
        "  elderly_support, visual_impairment, mobility_support"
    )
    prev_s = ",".join(sorted(x.value for x in prev if x is not SupportCategory.UNDECLARED))
    s = input(f"  Active consent [{prev_s or 'none'}]: ").strip()
    if not s:
        return prev
    cats: set[SupportCategory] = set()
    for part in s.split(","):
        key = part.strip().lower().replace(" ", "_")
        if not key or key == "none":
            continue
        if key not in _CONSENT_ALIASES:
            print(f"    (ignored unknown token: {part.strip()!r})")
            continue
        cats.add(_CONSENT_ALIASES[key])
    return frozenset(cats) if cats else frozenset()


def _prompt_journey_phase(prev: JourneyPhase) -> JourneyPhase:
    print(
        "Journey phase: in_motion | approaching_stop | end_of_route | boarding (empty=keep)"
    )
    s = input(f"  Phase [{prev.value}]: ").strip().lower()
    if not s:
        return prev
    try:
        return JourneyPhase(s)
    except ValueError:
        print("    Invalid phase; keeping previous.")
        return prev


def _compact_driver_message(msg: str) -> str:
    if msg.startswith("No action required"):
        if "cleared" in msg:
            return "No action required (previous alert cleared)."
        return "No action required"
    return msg


def _print_emergency_summary(driver_message: str) -> None:
    short = _compact_driver_message(driver_message)
    print()
    print("--------------------------------")
    print("Selected alert: EMERGENCY")
    print("Alert active: YES")
    print("Driver message:")
    print(short)
    print("--------------------------------")


def _support_categories_from_tick(tick: dict) -> set[SupportCategory]:
    raw = tick.get("support_categories")
    if not raw:
        return {SupportCategory.UNDECLARED}
    out = {SupportCategory(x) for x in raw}
    return out if out else {SupportCategory.UNDECLARED}


def evaluate_tick_and_print(
    tick: dict,
    *,
    emergency_sticky: EmergencyEvent | None,
    alert_active: bool,
    backend_session: BackendSession | None = None,
) -> tuple[EmergencyEvent | None, bool]:
    """
    Run evaluate_driver_tick and print the same summaries as manual interactive mode.
    Does not modify decision logic.
    """
    support_categories = _support_categories_from_tick(tick)
    em_ack = bool(tick.get("driver_acknowledge_emergency", False))
    cleared_by_ack = False
    es = emergency_sticky
    if es is not None and em_ack:
        es = None
        cleared_by_ack = True

    out = evaluate_driver_tick(
        tick,
        emergency_sticky=es,
        cleared_by_ack=cleared_by_ack,
    )
    es = out.emergency_sticky_next

    if backend_session is not None:
        backend_session.step(tick, out)

    if out.kind == "sticky_pending":
        msg = render_driver_alert(
            alert_type=None,
            scenario_matched=False,
            should_alert=False,
            emergency_sticky=es,
            emergency_immediate=None,
            support_categories=support_categories,
        )
        _print_emergency_summary(msg)
        return es, alert_active

    if out.kind == "immediate":
        msg = render_driver_alert(
            alert_type=None,
            scenario_matched=False,
            should_alert=False,
            emergency_sticky=None,
            emergency_immediate=out.emergency_immediate,
            support_categories=support_categories,
        )
        _print_emergency_summary(msg)
        return es, alert_active

    msg = render_driver_alert(
        alert_type=out.operational_alert,
        scenario_matched=out.scenario_matched,
        should_alert=out.should_alert,
        emergency_sticky=None,
        emergency_immediate=None,
        support_categories=support_categories,
    )

    if out.show_diversion_passenger_notify:
        print(
            "\nSIMULATED NOTIFY (consented passengers): Route change in effect - "
            "please allow extra time; listen for driver announcements."
        )
    if out.diversion_blocked:
        print(
            "\nPOLICY: Diversion ignored - vehicle not stationary; "
            "would be logged to compliance in full harness."
        )

    _print_tick_summary(
        final_winner=out.final_winner,
        should_alert=out.should_alert,
        driver_message=msg,
    )

    if out.should_alert and not alert_active:
        alert_active = True
    elif out.should_alert and alert_active:
        pass
    elif not out.should_alert and alert_active:
        print(_compact_driver_message(render_alert_cleared()))
        alert_active = False

    return es, alert_active


def _print_tick_summary(
    *,
    final_winner: AlertType | None,
    should_alert: bool,
    driver_message: str,
) -> None:
    sel = final_winner.value if final_winner is not None else "NONE"
    active = "YES" if should_alert else "NO"
    short = _compact_driver_message(driver_message)
    print()
    print("--------------------------------")
    print(f"Selected alert: {sel}")
    print(f"Alert active: {active}")
    print("Driver message:")
    print(short)
    print("--------------------------------")


def run_interactive_loop() -> None:
    print("TravelMate AI - interactive adapter simulator (PoC)")
    print("Commands: run a tick with your inputs; 'q' to quit; 'h' for help.\n")

    emergency_sticky: EmergencyEvent | None = None
    alert_active = False
    tick_index = 0
    backend_session = BackendSession()

    cues: dict[str, float] = {f.name: 0.0 for f in dc_fields(ObservedCues)}
    can = {
        "speed": 0.0,
        "braking_intensity": 0.0,
        "turn_intensity": 0.0,
        "doors_open": False,
        "ramp_deployed": False,
        "vehicle_stationary": True,
    }
    onboard, capacity = 20, 50
    journey = JourneyPhase.IN_MOTION
    support: frozenset[SupportCategory] = frozenset()
    consent_enhanced = False

    while True:
        cmd = input("\n[Enter]=new tick  h=help  q=quit > ").strip().lower()
        if cmd == "q":
            print("Goodbye.")
            return
        if cmd == "h":
            print(
                "Each tick prompts for observed cues, consent, CAN, density, journey,\n"
                "passenger stop (app), optional extras. Backend picks ONE alert by priority.\n"
                "Repeat the same high-risk inputs after clearing to see alerts reappear."
            )
            continue

        tick_index += 1
        print(f"\n=== Interactive tick {tick_index} ===")

        cues = _prompt_observed_cues(cues)
        support = _prompt_support_categories(support)
        consent_enhanced = _prompt_yn(
            "Consent-enhanced supervision (stricter thresholds; policy only)", consent_enhanced
        )

        print("CAN (normalized 0-1 for PoC):")
        can["speed"] = _prompt_float("speed", float(can["speed"]))
        can["braking_intensity"] = _prompt_float("braking_intensity", float(can["braking_intensity"]))
        can["turn_intensity"] = _prompt_float("turn_intensity", float(can["turn_intensity"]))
        can["doors_open"] = _prompt_yn("doors_open", bool(can["doors_open"]))
        can["ramp_deployed"] = _prompt_yn("ramp_deployed", bool(can["ramp_deployed"]))
        can["vehicle_stationary"] = _prompt_yn("vehicle_stationary", bool(can["vehicle_stationary"]))

        print("Density context:")
        def _parse_int(prev: int, label: str) -> int:
            s = _prompt_line(label, str(prev)).strip()
            if not s:
                return prev
            try:
                return int(s)
            except ValueError:
                print(f"    Invalid integer; keeping {prev}.")
                return prev

        onboard = _parse_int(onboard, "passengers_onboard")
        capacity = _parse_int(capacity, "vehicle_capacity")
        if capacity <= 0:
            capacity = 50
        if onboard < 0:
            onboard = 0

        journey = _prompt_journey_phase(journey)

        print("Passenger app (simulated):")
        stop_req = _prompt_yn("passenger_stop_request", False)
        stop_consented = _prompt_yn("passenger consented to share stop request with operator", False)

        print("Optional: driver diversion (tablet):")
        div_active = _prompt_yn("diversion_active", False)

        print("Optional: emergency cues (y/n):")
        em_fall = _prompt_yn("passenger_collapse_or_fall", False)
        em_med = _prompt_yn("medical_collapse_slow_descent (explicit sim flag)", False)
        em_fire = _prompt_yn("fire_or_smoke", False)
        em_alt = _prompt_yn("altercation", False)
        em_dist = _prompt_yn("severe_distress", False)
        em_ack = _prompt_yn("driver_acknowledge_emergency (clear sticky)", False)

        print("Optional: BLE proximity adapter (empty=off):")
        use_ble = _prompt_yn("enable BLE hints", False)
        ble_payload: dict | None = None
        if use_ble:
            z_raw = _prompt_line("BLE zone (wheelchair_bay|front_door|rear|unknown)", "wheelchair_bay")
            try:
                z = VehicleZone(z_raw.strip().lower())
            except ValueError:
                print("    Unknown zone; using unknown.")
                z = VehicleZone.UNKNOWN
            ble_conf = _prompt_float("BLE confidence", 0.75)
            ble_payload = {"enabled": True, "zone": z.value, "confidence": ble_conf}

        print("Optional: system faults:")
        disp_fault = _prompt_yn("display_fault", False)
        aud_fault = _prompt_yn("audio_fault", False)
        system_faults: dict[str, bool] = {}
        if disp_fault:
            system_faults["display_fault"] = True
        if aud_fault:
            system_faults["audio_fault"] = True

        tick: dict = {
            "observed_cues": cues,
            "can": dict(can),
            "density_context": {"passengers_onboard": onboard, "vehicle_capacity": capacity},
            "density": onboard / float(capacity),
            "behaviour": 0.0,
            "consent_enhanced_supervision": consent_enhanced,
            "support_categories": (
                [c.value for c in sorted(support, key=lambda x: x.value)]
                if support
                else [SupportCategory.UNDECLARED.value]
            ),
            "journey_phase": journey.value,
            "passenger_event": {
                "stop_request": stop_req,
                "source": "app",
                "consented": stop_consented,
            },
            "driver_event": {"diversion_active": div_active},
            "emergency": {
                "passenger_collapse_or_fall": em_fall,
                "medical_collapse_slow_descent": em_med,
                "fire_or_smoke": em_fire,
                "altercation": em_alt,
                "severe_distress": em_dist,
            },
            "driver_acknowledge_emergency": em_ack,
        }
        if ble_payload is not None:
            tick["ble"] = ble_payload
        if system_faults:
            tick["system_faults"] = system_faults

        emergency_sticky, alert_active = evaluate_tick_and_print(
            tick,
            emergency_sticky=emergency_sticky,
            alert_active=alert_active,
            backend_session=backend_session,
        )


def run_fake_adapter_loop() -> None:
    """Drive ticks from ``collect_tick_inputs()``; only menu key uses ``input()``."""
    from adapters.adapter_manager import collect_tick_inputs

    print("TravelMate AI - fake adapter mode (PoC)")
    print("Uses adapters.adapter_manager.collect_tick_inputs() (no field prompts).")
    print("Commands: [Enter]=run fake tick  h=help  q=quit\n")

    logging.basicConfig(level=logging.WARNING, format="WARNING %(name)s: %(message)s")

    emergency_sticky: EmergencyEvent | None = None
    alert_active = False
    tick_index = 0
    backend_session = BackendSession()

    while True:
        cmd = input("\n[Enter]=fake tick  h=help  q=quit > ").strip().lower()
        if cmd == "q":
            print("Goodbye.")
            return
        if cmd == "h":
            print(
                "Each tick calls fake CAN, camera, density, BLE, passenger app, and "
                "driver tablet adapters, then evaluates with the same engine as manual mode."
            )
            continue

        tick_index += 1
        print(f"\n=== Fake adapter tick {tick_index} ===")
        tick = collect_tick_inputs()
        emergency_sticky, alert_active = evaluate_tick_and_print(
            tick,
            emergency_sticky=emergency_sticky,
            alert_active=alert_active,
            backend_session=backend_session,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="TravelMate interactive CLI (PoC)")
    parser.add_argument(
        "--fake-adapters",
        action="store_true",
        help="Use fake hardware adapters (no manual cue/consent prompts)",
    )
    args = parser.parse_args()
    if args.fake_adapters:
        run_fake_adapter_loop()
    else:
        run_interactive_loop()


if __name__ == "__main__":
    main()
