# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Room-based validation test profile (PoC).

When enabled via environment, perception uses the configured camera path; CAN and
density are read from JSON files (fake vehicle/load). Consent and passenger app
payloads are read from JSON (real app integration can write the same files).

Does not alter ``evaluate_driver_tick`` or alert arbitration — adapter inputs only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def room_test_enabled() -> bool:
    """True when ``ROOM_TEST`` or ``TRAVELMATE_ROOM_TEST`` is set to 1/true/yes."""
    return _truthy_env("ROOM_TEST") or _truthy_env("TRAVELMATE_ROOM_TEST")


def room_test_interactive_enabled() -> bool:
    """Stdin density/CAN commands in ``runtime_loop`` (requires ROOM_TEST)."""
    return room_test_enabled() and _truthy_env("ROOM_TEST_INTERACTIVE")


def phase1_validation_enabled() -> bool:
    """Extra cue/decision/trace terminal output (ROOM_TEST only; observational)."""
    return room_test_enabled() and _truthy_env("ROOM_TEST_PHASE1_VALIDATE")


def room_test_live_camera_enabled() -> bool:
    """Phase-1B: live OpenCV capture (requires ``ROOM_TEST`` + ``ROOM_TEST_LIVE_CAMERA``)."""
    return room_test_enabled() and _truthy_env("ROOM_TEST_LIVE_CAMERA")


def room_test_dual_camera_enabled() -> bool:
    """Two live OpenCV devices: Zone 1 (front) + Zone 2 (mid); Zone 3 stays inactive."""
    return room_test_enabled() and _truthy_env("ROOM_TEST_DUAL_CAMERA")


def passenger_zone_continuity_gap_seconds() -> float:
    """Max seconds after last Zone-2 sighting to treat a new Zone-1 sighting as same passenger."""
    raw = os.environ.get("ROOM_TEST_PASSENGER_CONTINUITY_SEC", "").strip()
    if not raw:
        return 4.5
    try:
        return max(0.5, min(120.0, float(raw)))
    except ValueError:
        return 4.5


def parse_room_test_zone1_camera_index_for_dual() -> int:
    raw = os.environ.get("ROOM_TEST_CAMERA_INDEX_ZONE1", "").strip()
    if raw:
        return _non_negative_camera_index(raw, "ROOM_TEST_CAMERA_INDEX_ZONE1")
    legacy = os.environ.get("ROOM_TEST_CAMERA_INDEX", "").strip()
    if legacy:
        return _non_negative_camera_index(legacy, "ROOM_TEST_CAMERA_INDEX")
    raise RuntimeError(
        "ROOM_TEST_DUAL_CAMERA requires ROOM_TEST_CAMERA_INDEX_ZONE1 "
        "(or legacy ROOM_TEST_CAMERA_INDEX) — OpenCV device index for Zone 1."
    )


def parse_room_test_zone2_camera_index_for_dual() -> int:
    raw = os.environ.get("ROOM_TEST_CAMERA_INDEX_ZONE2", "").strip()
    if not raw:
        raise RuntimeError(
            "ROOM_TEST_DUAL_CAMERA requires ROOM_TEST_CAMERA_INDEX_ZONE2 "
            "(OpenCV device index for Zone 2 / mid cabin)."
        )
    return _non_negative_camera_index(raw, "ROOM_TEST_CAMERA_INDEX_ZONE2")


def _non_negative_camera_index(raw: str, label: str) -> int:
    try:
        idx = int(raw, 10)
    except ValueError as e:
        raise RuntimeError(f"{label} must be a non-negative integer (got {raw!r}).") from e
    if idx < 0:
        raise RuntimeError(f"{label} must be non-negative (got {idx}).")
    return idx


def room_test_camera_resolution_wh() -> tuple[int, int]:
    """
    Requested capture width × height for ROOM_TEST live OpenCV (``cv2.VideoCapture.set``).

    Env ``ROOM_TEST_CAMERA_RESOLUTION`` as ``WIDTHxHEIGHT`` (e.g. ``1280x720``). When unset
    or invalid, defaults to ``1280x720``. Non–ROOM_TEST callers get the same default tuple.
    """
    default_w, default_h = 1280, 720
    if not room_test_enabled():
        return (default_w, default_h)
    raw = os.environ.get("ROOM_TEST_CAMERA_RESOLUTION", "").strip()
    if not raw:
        return (default_w, default_h)
    token = raw.lower().replace("*", "x")
    if "x" not in token:
        return (default_w, default_h)
    left, _, right = token.partition("x")
    try:
        w = int(left.strip(), 10)
        h = int(right.strip(), 10)
    except ValueError:
        return (default_w, default_h)
    if w < 160 or h < 120 or w > 8192 or h > 8192:
        return (default_w, default_h)
    return (w, h)


def parse_room_test_camera_index_required() -> int:
    """
    Non-negative integer from ``ROOM_TEST_CAMERA_INDEX`` (required when live camera is enabled).

    Raises ``RuntimeError`` when unset or invalid — no fallback to another device.
    """
    raw = os.environ.get("ROOM_TEST_CAMERA_INDEX", "").strip()
    if not raw:
        raise RuntimeError(
            "ROOM_TEST_LIVE_CAMERA is enabled but ROOM_TEST_CAMERA_INDEX is not set. "
            "Set it to the OpenCV device index for your Cam Link (integer). "
            "No default index and no fallback."
        )
    try:
        idx = int(raw, 10)
    except ValueError as e:
        raise RuntimeError(
            f"ROOM_TEST_CAMERA_INDEX must be a non-negative integer (got {raw!r})."
        ) from e
    if idx < 0:
        raise RuntimeError(
            f"ROOM_TEST_CAMERA_INDEX must be non-negative (got {idx})."
        )
    return idx


def room_test_root() -> Path:
    raw = os.environ.get("ROOM_TEST_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "room_test").resolve()


def _incoming(name: str, default_rel: str) -> Path:
    env_key = f"ROOM_TEST_{name.upper()}_JSON"
    raw = os.environ.get(env_key, "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p.resolve() if p.is_absolute() else (room_test_root() / p).resolve()
    return (room_test_root() / default_rel).resolve()


def room_test_camera_json_path() -> Path:
    return _incoming("CAMERA", "incoming/camera_cues.json")


def room_test_can_json_path() -> Path:
    """Authoritative fake CAN state (room test). Override with ``ROOM_TEST_CAN_JSON``."""
    return _incoming("CAN", "room_can_state.json")


def room_test_density_state_path() -> Path:
    """Authoritative density state (room test). Override with ``ROOM_TEST_DENSITY_JSON``."""
    return _incoming("DENSITY", "room_density_state.json")


def room_test_density_json_path() -> Path:
    """Alias for :func:`room_test_density_state_path` (same env key)."""
    return room_test_density_state_path()


def room_test_consent_json_path() -> Path:
    return _incoming("CONSENT", "incoming/consent_context.json")


def room_test_passenger_json_path() -> Path:
    return _incoming("PASSENGER", "incoming/passenger_event.json")


def read_json_object(path: Path) -> dict | None:
    """Return parsed object if file exists and is a JSON object; else None."""
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def merge_room_test_json_file(path: Path, patch: dict) -> None:
    """Merge ``patch`` into existing JSON object at ``path`` (atomic replace)."""
    base = read_json_object(path) or {}
    for k, v in patch.items():
        base[k] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(base, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
