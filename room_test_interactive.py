# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Stdin control for ROOM_TEST manual density and fake CAN (same terminal as runtime_loop).

Prompts one field at a time; empty Enter keeps the current file value. Does not change core logic.
"""

from __future__ import annotations

import logging
import sys

from adapters.room_test_env import (
    merge_room_test_json_file,
    read_json_object,
    room_test_can_json_path,
    room_test_density_state_path,
)


class StdinClosed(Exception):
    """Stdin reached EOF (e.g. Ctrl+Z+Enter on Windows); exit interactive thread."""


def _read_line(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if line == "":
        raise StdinClosed
    return line.rstrip("\r\n")


def _bool_hint(b: bool) -> str:
    return "true" if b else "false"


def _prompt_optional_int(label: str, current: int, *, minimum: int) -> int | None:
    while True:
        try:
            s = _read_line(f"{label} [{current}]: ").strip()
        except StdinClosed:
            raise
        if s == "":
            return None
        try:
            v = int(s)
            if v < minimum:
                sys.stdout.write(f"  (use integer >= {minimum})\n")
                continue
            return v
        except ValueError:
            sys.stdout.write("  (use an integer)\n")


def _prompt_optional_float(label: str, current: float) -> float | None:
    while True:
        try:
            s = _read_line(f"{label} [{current}]: ").strip()
        except StdinClosed:
            raise
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            sys.stdout.write("  (use a number, e.g. 0.25)\n")


def _prompt_optional_bool(label: str, current: bool) -> bool | None:
    hint = _bool_hint(current)
    while True:
        try:
            s = _read_line(f"{label} [{hint}]: ").strip()
        except StdinClosed:
            raise
        if s == "":
            return None
        low = s.lower()
        if low in ("y", "yes", "1", "true", "t"):
            return True
        if low in ("n", "no", "0", "false", "f"):
            return False
        sys.stdout.write("  (y/n or true/false)\n")


def _one_prompt_round(log: logging.Logger) -> None:
    dpath = room_test_density_state_path()
    cpath = room_test_can_json_path()
    dcur = read_json_object(dpath) or {}
    ccur = read_json_object(cpath) or {}

    po = max(0, int(dcur.get("passengers_onboard", 0)))
    vc = max(1, int(dcur.get("vehicle_capacity", 50)))
    sp = float(ccur.get("speed", 0.0))
    br = float(ccur.get("braking_intensity", 0.0))
    tr = float(ccur.get("turn_intensity", 0.0))
    do = bool(ccur.get("doors_open", False))
    rd = bool(ccur.get("ramp_deployed", False))
    vs = bool(ccur.get("vehicle_stationary", True))

    sys.stdout.write("\n")
    sys.stdout.flush()

    new_po = _prompt_optional_int("density", po, minimum=0)
    new_vc = _prompt_optional_int("vehicle_capacity", vc, minimum=1)

    new_sp = _prompt_optional_float("speed", sp)
    new_br = _prompt_optional_float("braking_intensity", br)
    new_tr = _prompt_optional_float("turn_intensity", tr)

    new_do = _prompt_optional_bool("doors_open", do)
    new_rd = _prompt_optional_bool("ramp_deployed", rd)
    new_vs = _prompt_optional_bool("vehicle_stationary", vs)

    density_patch: dict = {}
    if new_po is not None:
        density_patch["passengers_onboard"] = new_po
    if new_vc is not None:
        density_patch["vehicle_capacity"] = new_vc
    if density_patch:
        merge_room_test_json_file(dpath, density_patch)
        log.info("ROOM_TEST_CONTROL density -> %s", density_patch)

    can_patch: dict = {}
    if new_sp is not None:
        can_patch["speed"] = new_sp
    if new_br is not None:
        can_patch["braking_intensity"] = new_br
    if new_tr is not None:
        can_patch["turn_intensity"] = new_tr
    if new_do is not None:
        can_patch["doors_open"] = new_do
    if new_rd is not None:
        can_patch["ramp_deployed"] = new_rd
    if new_vs is not None:
        can_patch["vehicle_stationary"] = new_vs
    if can_patch:
        merge_room_test_json_file(cpath, can_patch)
        log.info("ROOM_TEST_CONTROL CAN -> %s", can_patch)

    sys.stdout.write(
        "\n  — Round done. Next round starts below (Enter alone on a line keeps that field as-is).\n"
    )
    sys.stdout.flush()


def run_room_test_interactive_stdin(log: logging.Logger) -> None:
    """Blocking loop on stdin; intended to run in a daemon thread."""
    sys.stdout.write(
        "ROOM_TEST interactive: answer each prompt in order.\n"
        "  density = passengers_onboard. Empty Enter = keep the value shown in [ ].\n\n"
    )
    sys.stdout.flush()
    while True:
        try:
            _one_prompt_round(log)
        except StdinClosed:
            log.info("ROOM_TEST_CONTROL stdin closed; prompts stopped")
            break


def print_interactive_banner() -> None:
    sys.stdout.write(
        "ROOM_TEST_INTERACTIVE=1: wait for prompts (density → vehicle_capacity → speed → …).\n"
        "Ctrl+C stops the whole process.\n\n"
    )
    sys.stdout.flush()
