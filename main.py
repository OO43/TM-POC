# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI PoC - main entry.

Long runs: the IDE/terminal scrollback may hide earlier ticks; the logic still runs.
Capture the full console output:
  python main.py --log
    -> also writes travelmate_last_run.txt beside this file.
  python main.py --interactive
    -> human-as-adapter CLI (full cue + consent control); see interactive_cli.py.
  python main.py --display-contract
    -> after each tick, print JSON stacked alert contract (primary + queue + camera flag).
  python main.py > run.txt 2>&1
    -> PowerShell: full stdout/stderr to run.txt.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend_session import BackendSession, backend_output_to_jsonable
from can_context import CANContext, derive_motion_level
from density_context import DensityContext
from driver_alert_text import render_alert_cleared, render_driver_alert
from emergency import EmergencyEvent, resolve_simulated_emergency
from journey_phase import JourneyPhase
from observed_cues import ObservedCues
from policy_arbitration import is_vehicle_stationary_for_diversion
from policy_floor_emergency import merge_tick_emergency_inputs_with_floor_policy
from test_harness import example_test_matrix
from thresholds import AlertType, SupportCategory
from tick_driver_eval import (
    _ble_from_tick,
    _can_context_from_tick,
    _density_ctx_from_tick,
    _driver_event_from_tick,
    _journey_phase_from_tick,
    _observed_cues_from_tick,
    _passenger_behaviour_from_tick,
    _passenger_density_from_tick,
    _passenger_event_from_tick,
    _support_categories_from_tick,
    _system_faults_from_tick,
    evaluate_driver_tick,
)

# Multi-passenger / zone semantics: situation_context.py (documentation).


class _TeeStdout:
    """Write to console and a file so long runs are not lost to terminal scrollback."""

    def __init__(self, file_obj: object, original) -> None:
        self._file = file_obj
        self._original = original

    def write(self, data: str) -> int:
        self._original.write(data)
        self._file.write(data)
        return len(data)

    def flush(self) -> None:
        self._original.flush()
        self._file.flush()


# Full adapter-style test matrix (replace with a subset to shorten runs).
SIMULATED_TICKS: list[dict] = example_test_matrix()


# Compliance audit trail: no names, IDs, or biometric samples (PoC)
COMPLIANCE_LOG_PATH = Path(__file__).resolve().parent / "travelmate_compliance.log"
EMERGENCY_COMPLIANCE_LOG_PATH = Path(__file__).resolve().parent / "travelmate_emergency.log"


def log_compliance_event(event: str, **fields: str | int | float | bool) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    line = f"{ts} event={event}" + (f" {extra}" if extra else "") + "\n"
    with COMPLIANCE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def log_emergency_event(event: str, **fields: str | int | float | bool) -> None:
    """Privacy-preserving emergency-only audit trail (no identity, no biometrics)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    line = f"{ts} event={event}" + (f" {extra}" if extra else "") + "\n"
    with EMERGENCY_COMPLIANCE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


def main() -> None:
    print_display_contract = "--display-contract" in sys.argv
    print("TravelMate AI PoC - startup (full harness)")
    print(
        f"Running {len(SIMULATED_TICKS)} tick(s). "
        "If the console scrolls too far, run: python main.py --log"
    )
    log_compliance_event("session_start", component="travelmate_poc")
    print(f"Compliance log (append-only): {COMPLIANCE_LOG_PATH}")
    print(f"Emergency compliance log (append-only): {EMERGENCY_COMPLIANCE_LOG_PATH}")

    alert_active = False
    emergency_sticky: EmergencyEvent | None = None
    backend_session = BackendSession()

    for i, tick in enumerate(SIMULATED_TICKS, start=1):
        observed = _observed_cues_from_tick(tick)
        density_ctx = _density_ctx_from_tick(tick)
        passenger_density = _passenger_density_from_tick(tick, density_ctx)
        passenger_behaviour = _passenger_behaviour_from_tick(tick, observed)
        can_context = _can_context_from_tick(tick)
        vehicle_motion = derive_motion_level(can_context)
        consent_enhanced_supervision = bool(tick["consent_enhanced_supervision"])
        driver_acknowledge_emergency = bool(tick.get("driver_acknowledge_emergency", False))
        support_categories = _support_categories_from_tick(tick)
        journey_phase = _journey_phase_from_tick(tick)
        ble_ctx = _ble_from_tick(tick)
        system_faults = _system_faults_from_tick(tick)

        cleared_by_ack = False
        if emergency_sticky is not None and driver_acknowledge_emergency:
            log_emergency_event(
                "emergency_acknowledged",
                tick=i,
                emergency_class=emergency_sticky.value,
            )
            print(
                "DRIVER: Emergency acknowledged by operator. "
                "Further escalation / external notify only after acknowledgment (simulated)."
            )
            log_emergency_event(
                "emergency_escalation_permitted",
                tick=i,
                emergency_class=emergency_sticky.value,
            )
            emergency_sticky = None
            cleared_by_ack = True

        print()
        print(f"--- Tick {i} ---")
        if observed is not None:
            print(f"Observed cues (simulated perception): {tick.get('observed_cues', {})}")
        driver_event = _driver_event_from_tick(tick)
        passenger_event = _passenger_event_from_tick(tick)
        diversion_allowed = is_vehicle_stationary_for_diversion(
            can_context.vehicle_stationary, vehicle_motion
        )
        print(
            f"CAN (simulated): speed={can_context.speed:.2f}, "
            f"braking={can_context.braking_intensity:.2f}, turn={can_context.turn_intensity:.2f}, "
            f"doors_open={can_context.doors_open}, ramp_deployed={can_context.ramp_deployed}, "
            f"vehicle_stationary={can_context.vehicle_stationary}"
        )
        print(
            f"Policy hooks: diversion_allowed={diversion_allowed} (tablet contract), "
            f"driver_diversion_active={driver_event.diversion_active}, "
            f"passenger_stop_request={passenger_event.stop_request} consented={passenger_event.consented}"
        )
        print(f"Derived motion level [0,1]: {vehicle_motion:.4f}")
        if density_ctx is not None:
            print(
                f"Density context: onboard={density_ctx.passengers_onboard}/"
                f"{density_ctx.vehicle_capacity} -> level={passenger_density:.4f}"
            )
        else:
            print(f"Density level: {passenger_density:.4f}")
        print(
            f"Behaviour aggregate (situation): {passenger_behaviour:.4f} | "
            f"consent_enhanced={consent_enhanced_supervision}"
        )
        sup_display = ",".join(sorted(s.value for s in support_categories)) or "undeclared"
        print(f"Consent-declared support (policy only): {sup_display}")
        print(f"Journey phase: {journey_phase.value}")
        if ble_ctx:
            print(
                f"BLE zone (optional): enabled={ble_ctx.enabled}, "
                f"zone={ble_ctx.zone.value}, conf={ble_ctx.confidence:.2f}"
            )
        if system_faults:
            print(f"System faults (simulated): {system_faults}")
        print(f"Driver ack (emergency): {driver_acknowledge_emergency}")

        emergency_inputs = merge_tick_emergency_inputs_with_floor_policy(tick)
        emergency_event = resolve_simulated_emergency(emergency_inputs)
        print(
            f"Emergency cue flags: fall={emergency_inputs.passenger_collapse_or_fall}, "
            f"fire={emergency_inputs.fire_or_smoke}, altercation={emergency_inputs.altercation}, "
            f"distress={emergency_inputs.severe_distress} | resolved={emergency_event}"
        )

        out = evaluate_driver_tick(
            tick,
            emergency_sticky=emergency_sticky,
            cleared_by_ack=cleared_by_ack,
        )
        emergency_sticky = out.emergency_sticky_next

        backend_output = backend_session.step(tick, out)
        if print_display_contract:
            print("--- backend_output_contract ---")
            print(json.dumps(backend_output_to_jsonable(backend_output), indent=2))
        _primary = (
            backend_output["primary_alert"]["alert_type"]
            if backend_output["primary_alert"] is not None
            else "NONE"
        )
        _queue = [r["alert_type"] for r in backend_output["ordered_alerts"]]
        print(
            f"tick={i} primary={_primary} pending={backend_output['pending_alert_count']} "
            f"queue={_queue} sound={backend_output['sound_cue']} "
            f"bus_ready={backend_output['bus_ready']} emergency={backend_output['emergency_active']}"
        )

        if out.kind == "sticky_pending":
            print("(Compounded risk not evaluated: emergency active.)")
            log_emergency_event(
                "emergency_sticky_pending",
                tick=i,
                emergency_class=emergency_sticky.value,
            )
            log_compliance_event(
                "tick_eval",
                tick=i,
                risk_evaluated=False,
                gate_alert=False,
                consent_enhanced_mode=out.consent_enhanced_supervision,
                support_categories=out.sup_display,
                journey_phase=out.journey_phase_value,
                emergency_path=True,
                emergency_sticky_pending=True,
            )
            print(
                render_driver_alert(
                    alert_type=None,
                    scenario_matched=False,
                    should_alert=False,
                    emergency_sticky=emergency_sticky,
                    emergency_immediate=None,
                    support_categories=support_categories,
                )
            )
            continue

        if out.kind == "immediate":
            print("(Compounded risk not evaluated: emergency fast path.)")
            log_emergency_event(
                "emergency_immediate",
                tick=i,
                emergency_class=out.emergency_immediate.value,
            )
            log_compliance_event(
                "tick_eval",
                tick=i,
                risk_evaluated=False,
                gate_alert=False,
                consent_enhanced_mode=out.consent_enhanced_supervision,
                support_categories=out.sup_display,
                journey_phase=out.journey_phase_value,
                emergency_path=True,
            )
            print(
                render_driver_alert(
                    alert_type=None,
                    scenario_matched=False,
                    should_alert=False,
                    emergency_sticky=None,
                    emergency_immediate=out.emergency_immediate,
                    support_categories=support_categories,
                )
            )
            continue

        assert out.kind == "routine"
        if out.diversion_blocked:
            log_compliance_event(
                "diversion_blocked_vehicle_motion",
                tick=i,
                motion_level=round(out.vehicle_motion_level, 4),
                vehicle_stationary=out.can_vehicle_stationary,
            )
            print(
                "POLICY: Route diversion request ignored - vehicle not stationary "
                "(diversion_allowed=False); compliance event logged."
            )

        final_winner = out.final_winner
        scenario_matched = out.scenario_matched
        operational_alert = out.operational_alert
        should_alert = out.should_alert
        policy_bypass = out.policy_bypass
        risk_score = out.risk_score
        policy_candidates = list(out.policy_candidates)
        threshold_support = out.threshold_support

        if final_winner is not None:
            print(
                f"Selected alert (priority): {final_winner.value} | "
                f"scenario_matched={scenario_matched} | "
                f"policy_inputs={','.join(a.value for a in policy_candidates) or 'none'}"
            )
        elif operational_alert is AlertType.NONE:
            print(
                "Scenario classification: suppressed — no passenger foreground; "
                "inferencer state cleared."
            )
        else:
            print(
                "Scenario classification: none matched - "
                "threshold row uses INSTABILITY_RISK baseline for monitoring only."
            )
        print(f"Threshold row: support={threshold_support.value} alert={operational_alert.value}")
        print(f"Risk score (compounded): {risk_score:.4f}")

        if out.show_diversion_passenger_notify:
            log_compliance_event(
                "passenger_notify_simulated",
                tick=i,
                channel="in_app_message",
                template="route_diversion_active",
            )
            print(
                "SIMULATED NOTIFY (consented passengers): Route change in effect - "
                "please allow extra time; listen for driver announcements."
            )

        log_compliance_event(
            "tick_eval",
            tick=i,
            risk=round(risk_score, 4),
            gate_alert=should_alert,
            consent_enhanced_mode=out.consent_enhanced_supervision,
            support_categories=out.sup_display,
            journey_phase=out.journey_phase_value,
            scenario_matched=scenario_matched,
            alert_type=operational_alert.value,
            diversion_allowed=out.diversion_allowed,
            policy_bypass_risk_gating=policy_bypass,
        )

        print(
            render_driver_alert(
                alert_type=operational_alert,
                scenario_matched=scenario_matched,
                should_alert=should_alert,
                emergency_sticky=None,
                emergency_immediate=None,
                support_categories=support_categories,
            )
        )

        if should_alert and not alert_active:
            alert_active = True
            log_compliance_event(
                "driver_alert_raised",
                tick=i,
                risk=round(risk_score, 4),
                alert_type=operational_alert.value,
            )
        elif should_alert and alert_active:
            pass
        elif not should_alert and alert_active:
            print(render_alert_cleared())
            alert_active = False
            log_compliance_event(
                "driver_alert_cleared",
                tick=i,
                risk=round(risk_score, 4),
                alert_type=operational_alert.value,
            )
        else:
            pass


if __name__ == "__main__":
    if "--interactive" in sys.argv or "-i" in sys.argv:
        from interactive_cli import run_interactive_loop

        run_interactive_loop()
    else:
        _log_path = Path(__file__).resolve().parent / "travelmate_last_run.txt"
        if "--log" in sys.argv:
            with open(_log_path, "w", encoding="utf-8") as _lf:
                _saved = sys.stdout
                sys.stdout = _TeeStdout(_lf, _saved)
                try:
                    main()
                finally:
                    sys.stdout = _saved
            print(f"Full output also saved to: {_log_path}")
        else:
            main()
