# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Pipe scripted answers into interactive_cli.run_interactive_loop for demos.

Run: python run_interactive_demo.py
"""

from __future__ import annotations

import io
import sys

import interactive_cli

empty = ""


def _yn(b: bool) -> str:
    return "y" if b else "n"


def _emergency_ble_faults(
    *,
    fall: bool = False,
    fire: bool = False,
    altercation: bool = False,
    distress: bool = False,
    ack: bool = False,
    ble: bool = False,
    display_fault: bool = False,
    audio_fault: bool = False,
) -> list[str]:
    """Exactly 8 lines: 5 emergency y/n, BLE, display_fault, audio_fault."""
    return [
        _yn(fall),
        _yn(fire),
        _yn(altercation),
        _yn(distress),
        _yn(ack),
        _yn(ble),
        _yn(display_fault),
        _yn(audio_fault),
    ]


def _tick(
    *,
    cues15: list[str],
    consent: str,
    consent_enhanced: bool,
    speed: str,
    braking: str,
    turn: str,
    doors_open: bool,
    ramp_deployed: bool,
    vehicle_stationary: bool,
    onboard: str,
    capacity: str,
    journey: str,
    stop_req: bool,
    stop_consented: bool,
    diversion: bool,
    emergency_ble_faults: list[str],
) -> list[str]:
    assert len(cues15) == 15
    assert len(emergency_ble_faults) == 8
    return [
        *cues15,
        consent,
        _yn(consent_enhanced),
        speed,
        braking,
        turn,
        _yn(doors_open),
        _yn(ramp_deployed),
        _yn(vehicle_stationary),
        onboard,
        capacity,
        journey,
        _yn(stop_req),
        _yn(stop_consented),
        _yn(diversion),
        *emergency_ble_faults,
    ]


def _lines() -> list[str]:
    z = ["0"] * 15

    tick_stop = _tick(
        cues15=[empty] * 15,
        consent=empty,
        consent_enhanced=False,
        speed="0.25",
        braking="0.1",
        turn="0.05",
        doors_open=False,
        ramp_deployed=False,
        vehicle_stationary=False,
        onboard="15",
        capacity="50",
        journey=empty,
        stop_req=True,
        stop_consented=True,
        diversion=False,
        emergency_ble_faults=_emergency_ble_faults(),
    )

    tick_capacity = _tick(
        cues15=[empty] * 15,
        consent=empty,
        consent_enhanced=False,
        speed="0",
        braking="0",
        turn="0",
        doors_open=False,
        ramp_deployed=False,
        vehicle_stationary=True,
        onboard="52",
        capacity="50",
        journey=empty,
        stop_req=False,
        stop_consented=False,
        diversion=False,
        emergency_ble_faults=_emergency_ble_faults(),
    )

    tick_diversion = _tick(
        cues15=[empty] * 15,
        consent=empty,
        consent_enhanced=False,
        speed="0",
        braking="0",
        turn="0",
        doors_open=False,
        ramp_deployed=False,
        vehicle_stationary=True,
        onboard="8",
        capacity="50",
        journey="approaching_stop",
        stop_req=False,
        stop_consented=False,
        diversion=True,
        emergency_ble_faults=_emergency_ble_faults(),
    )

    tick_medical = _tick(
        cues15=[
            "0",
            "0",
            "0",
            "0.5",
            "0.5",
            "0",
            "0",
            "0",
            "0.5",
            "0",
            "0",
            "0",
            "0",
            "0",
            "0",
        ],
        consent="medical_sensitivity",
        consent_enhanced=True,
        speed="0.55",
        braking="0.45",
        turn="0.35",
        doors_open=False,
        ramp_deployed=False,
        vehicle_stationary=False,
        onboard="28",
        capacity="50",
        journey="in_motion",
        stop_req=False,
        stop_consented=False,
        diversion=False,
        emergency_ble_faults=_emergency_ble_faults(),
    )

    tick_fire = _tick(
        cues15=[empty] * 15,
        consent=empty,
        consent_enhanced=False,
        speed="0.2",
        braking="0.1",
        turn="0.1",
        doors_open=False,
        ramp_deployed=False,
        vehicle_stationary=False,
        onboard="10",
        capacity="50",
        journey=empty,
        stop_req=False,
        stop_consented=False,
        diversion=False,
        emergency_ble_faults=_emergency_ble_faults(fire=True),
    )

    tick_ack = _tick(
        cues15=[empty] * 15,
        consent=empty,
        consent_enhanced=False,
        speed=empty,
        braking=empty,
        turn=empty,
        doors_open=False,
        ramp_deployed=False,
        vehicle_stationary=False,
        onboard=empty,
        capacity=empty,
        journey=empty,
        stop_req=False,
        stop_consented=False,
        diversion=False,
        emergency_ble_faults=_emergency_ble_faults(ack=True),
    )

    return [
        empty,  # menu: start tick 1
        *tick_stop,
        empty,
        *tick_capacity,
        empty,
        *tick_diversion,
        empty,
        *tick_medical,
        empty,
        *tick_fire,
        empty,
        *tick_ack,
        "q",  # next line is menu prompt -> quit (do not add blank before q)
    ]


def main() -> None:
    data = "\n".join(_lines()) + "\n"
    sys.stdin = io.StringIO(data)
    interactive_cli.run_interactive_loop()


if __name__ == "__main__":
    main()
