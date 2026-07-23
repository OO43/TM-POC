# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — cabin perception adapter (PoC).

Room test + ``ROOM_TEST_LIVE_CAMERA`` + ``ROOM_TEST_CAMERA_INDEX`` (Phase-1B): live Cam Link
feed via OpenCV; JSON camera file is not used.

Room test + ``TRAVELMATE_GOPRO_CAMERA_INDEX`` (legacy, non-empty): live feed via OpenCV
(``cv2.CAP_DSHOW`` on Windows), deterministic layered cue extraction, full
:class:`observed_cues.ObservedCues` on every tick (phase‑2 fields present at 0.0).

Room test + ``ROOM_TEST_DUAL_CAMERA`` + zone indices: two OpenCV devices — Zone 1 front +
Zone 2 mid cabin; per-tick cues are elementwise max-fused for legacy ``observed_cues``;
``passenger_tick_bridge`` consumes paired :class:`camera_observation_contract.CameraObservation`
rows. Zone 3 stays inactive.

Room test without live / dual / GOPRO index: JSON file at ``room_test_env.room_test_camera_json_path``.

Non–room-test: legacy fixed fake cues for non-hardware demos.

Requires ``opencv-python`` when using the GoPro path (``import cv2``).

Environment (OpenCV path, only when ``room_test_enabled()``):

- ``ROOM_TEST_LIVE_CAMERA`` — set to 1/true/yes to enable live capture (Phase-1B).
- ``ROOM_TEST_CAMERA_INDEX`` — **required** with live camera (non-negative integer);
  **no fallback** device.
- ``ROOM_TEST_SHOW_PREVIEW`` — if 1/true/yes, show an OpenCV preview window **in the same
  process** as ``runtime_loop`` (do **not** run ``room_test_camlink_verify.py`` on the same index).
- ``TRAVELMATE_GOPRO_CAMERA_INDEX`` — legacy alternate; ignored when ``ROOM_TEST_LIVE_CAMERA``
  is enabled.
- ``ROOM_TEST_PERCEPTION_START_DELAY_SECONDS`` — ROOM_TEST + live OpenCV only: countdown after
  process start / resume-from-pause; frames are grabbed and preview may run but cues stay 0,
  dwell state unchanged until ``PERCEPTION ARMED`` log.
- ``ROOM_TEST_CAMERA_RESOLUTION`` — optional ``WIDTHxHEIGHT`` (e.g. ``1280x720``). When unset,
  live ROOM_TEST capture requests ``1280x720`` via ``CAP_PROP_FRAME_WIDTH/HEIGHT``.
- ``TRAVELMATE_DOOR_BAND_FRAC`` — optional; fraction of frame width treated as the door
  side band (default ``0.30``).
- ``TRAVELMATE_FG_MIN_AREA_FRAC`` — optional; minimum contour area vs frame area
  (default ``0.0015``).
- ``TRAVELMATE_STANDING_SPEED_THRESH`` — optional; normalized centroid speed below which
  the passenger is considered “still” (default ``0.018``).
- ``TRAVELMATE_STANDING_FULL_SECS`` — optional; seconds at low speed to reach
  ``prolonged_standing`` ≈ 1 (default ``12.0``).

Per-tick logs use logger ``travelmate.runtime.camera`` (propagates to the runtime handler).

Optional **human-only cue view** (does not change cues sent to the backend):

- ``TRAVELMATE_SHOW_CAMERA_CUES=1`` (or ``true``/``yes``): each tick, a formatted block is
  written through logger ``travelmate.camera.cues`` to **stderr only** (``propagate=False``),
  so it stays separate from the runtime logger on **stdout**.
- ``TRAVELMATE_CAMERA_CUES_FILE`` — optional path; the same block is appended each tick
  (UTF-8) so a second terminal can ``tail -f`` / ``Get-Content -Wait`` that file.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import time
from collections import deque
from dataclasses import asdict, fields
from typing import Deque

from adapters.room_test_env import (
    parse_room_test_camera_index_required,
    parse_room_test_zone1_camera_index_for_dual,
    parse_room_test_zone2_camera_index_for_dual,
    read_json_object,
    room_test_camera_json_path,
    room_test_camera_resolution_wh,
    room_test_dual_camera_enabled,
    room_test_enabled,
    room_test_live_camera_enabled,
)
from cabin_topology import CabinZoneId
from observed_cues import ObservedCues

_CAMERA_ZONE_KEYS: tuple[str, ...] = ("door", "mid", "rear")

# Last dual-camera snapshot for ``adapter_manager`` / bridge (consumed once per tick).
_dual_observation_snapshots: list[tuple[str, CabinZoneId, float, ObservedCues, str]] | None = None

_LOG = logging.getLogger("travelmate.runtime.camera")
_LOG_CUES = logging.getLogger("travelmate.camera.cues")

ROOM_TEST_PREVIEW_WINDOW_TITLE = "TravelMate ROOM_TEST live preview"

# Phase‑1 instability: centroid variance window (seconds) and sustained-lean time scale.
_INSTABILITY_ROLLING_SECS = 1.65
_LEAN_SUSTAIN_FULL_SECS = 6.5
# Lean signal: hysteresis so segmentation centroid jitter near center is not treated as sustained
# lean (which previously latched ``leaning_without_support`` at 1.0). Alert thresholds unchanged.
_LEAN_GATE_ACCUM = 0.028
_LEAN_GATE_DECAY = 0.012
_LEAN_DECAY_UPRIGHT_PER_SEC = 0.38
_LEAN_DECAY_MIDZONE_PER_SEC = 0.16
# Balance correction: accumulate only on reversal / above-noise micro-jerk; faster decay when quiet.
_BAL_CORR_DECAY_SECS_ACTIVE = 5.5
_BAL_CORR_DECAY_SECS_IDLE = 1.35
_BAL_CORR_MICRO_EPS = 1.2e-4

_CUES_STDERR_INSTALLED = False
_CUES_FILE_HANDLER_PATH: str | None = None

# ROOM_TEST perception start-delay (live OpenCV only): mono deadline while outputs are clamped zero.
_live_perception_hold_until_mono: float | None = None


def room_test_schedule_live_camera_perception_start_delay(*, log: logging.Logger) -> None:
    """
    Begin (or restart) the live-camera perception hold window (ROOM_TEST only).

    Frames are still read so preview can update; observed cues forced to zero until expiry,
    then state is cleared and perception runs normally again.
    """
    global _live_perception_hold_until_mono
    if not room_test_enabled():
        return
    if not (
        room_test_live_camera_enabled()
        or room_test_dual_camera_enabled()
        or _parse_gopro_index_strict() is not None
    ):
        return
    delay = perception_start_delay_seconds_room_test()
    if delay <= 0:
        _live_perception_hold_until_mono = None
        return
    secs_show = max(1, int(math.ceil(float(delay))))
    _live_perception_hold_until_mono = time.monotonic() + float(delay)
    msg = (
        f"PERCEPTION STARTING IN {secs_show} SECONDS – prepare scenario"
    )
    log.info("%s", msg)
    print(msg, flush=True)


def perception_start_delay_seconds_room_test() -> float:
    """Configured delay (seconds), or 0 if unset/disabled/non–ROOM_TEST."""
    if not room_test_enabled():
        return 0.0
    raw = os.environ.get("ROOM_TEST_PERCEPTION_START_DELAY_SECONDS", "").strip()
    if not raw:
        return 0.0
    try:
        v = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, v)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _camera_cues_view_enabled() -> bool:
    if _truthy_env("TRAVELMATE_SHOW_CAMERA_CUES"):
        return True
    return bool(os.environ.get("TRAVELMATE_CAMERA_CUES_FILE", "").strip())


def _ensure_camera_cues_log_handlers() -> None:
    """Attach stderr and/or file handlers once; logger never propagates to root/runtime."""
    global _CUES_STDERR_INSTALLED, _CUES_FILE_HANDLER_PATH
    _LOG_CUES.setLevel(logging.INFO)
    _LOG_CUES.propagate = False
    if _truthy_env("TRAVELMATE_SHOW_CAMERA_CUES") and not _CUES_STDERR_INSTALLED:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(message)s"))
        _LOG_CUES.addHandler(sh)
        _CUES_STDERR_INSTALLED = True
    fp = os.environ.get("TRAVELMATE_CAMERA_CUES_FILE", "").strip()
    if fp and fp != _CUES_FILE_HANDLER_PATH:
        for h in list(_LOG_CUES.handlers):
            if isinstance(h, logging.FileHandler):
                _LOG_CUES.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
        fh = logging.FileHandler(fp, mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(message)s"))
        _LOG_CUES.addHandler(fh)
        _CUES_FILE_HANDLER_PATH = fp


def _format_camera_cues_block(
    *,
    camera_index_display: str,
    frame_status: str,
    cues: ObservedCues,
) -> str:
    d = asdict(cues.clamped())
    names = [f.name for f in fields(ObservedCues)]
    w = max(len(n) for n in names) if names else 20
    lines = [
        "---------- CAMERA_CUES ----------",
        f"camera_index:  {camera_index_display}",
        f"frame_status:  {frame_status}",
        "cues:",
    ]
    for name in sorted(names):
        lines.append(f"  {name:{w}s}  {float(d[name]):.4f}")
    lines.append("---------------------------------")
    return "\n".join(lines)


def _emit_camera_cues_view(
    *,
    camera_index_display: str,
    frame_status: str,
    cues: ObservedCues,
) -> None:
    if not _camera_cues_view_enabled():
        return
    _ensure_camera_cues_log_handlers()
    _LOG_CUES.info("%s", _format_camera_cues_block(
        camera_index_display=camera_index_display,
        frame_status=frame_status,
        cues=cues,
    ))


def _zero_zones() -> dict[str, float]:
    return {k: 0.0 for k in _CAMERA_ZONE_KEYS}


def _fuse_camera_zones_max(z1: dict[str, float], z2: dict[str, float]) -> dict[str, float]:
    return {k: max(float(z1.get(k, 0.0)), float(z2.get(k, 0.0))) for k in _CAMERA_ZONE_KEYS}


def _fuse_observed_cues_max(a: ObservedCues, b: ObservedCues) -> ObservedCues:
    da = asdict(a.clamped())
    db = asdict(b.clamped())
    kw = {f.name: max(float(da[f.name]), float(db[f.name])) for f in fields(ObservedCues)}
    return ObservedCues(**kw).clamped()


def _dual_camera_logical_id(zone_id: CabinZoneId) -> str:
    if zone_id == CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT:
        raw = os.environ.get("ROOM_TEST_DUAL_CAMERA_ID_ZONE1", "").strip()
        return raw if raw else "1"
    if zone_id == CabinZoneId.ZONE_2_MID_CABIN:
        raw = os.environ.get("ROOM_TEST_DUAL_CAMERA_ID_ZONE2", "").strip()
        return raw if raw else "2"
    return "?unknown_zone?"


def pop_dual_observation_snapshots() -> (
    list[tuple[str, CabinZoneId, float, ObservedCues, str]] | None
):
    """
    Observation rows from the latest ``read_cabin_perception`` when ``ROOM_TEST_DUAL_CAMERA``
    was active. Call exactly once after each read from ``adapter_manager`` (consumes storage).
    """
    global _dual_observation_snapshots
    snap = _dual_observation_snapshots
    _dual_observation_snapshots = None
    return snap


def _clamp01(x: object) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _cues_from_mapping(raw: dict | None) -> ObservedCues:
    if not raw:
        return ObservedCues()
    kw: dict[str, float] = {}
    for f in fields(ObservedCues):
        if f.name in raw:
            kw[f.name] = _clamp01(raw[f.name])
        else:
            kw[f.name] = 0.0
    return ObservedCues(**kw)


def _zones_from_mapping(raw: dict | None) -> dict[str, float]:
    z = _zero_zones()
    if not raw:
        return z
    for k in _CAMERA_ZONE_KEYS:
        if k in raw:
            z[k] = _clamp01(raw[k])
    return z


def _read_room_file() -> tuple[ObservedCues, dict[str, float], str]:
    """
    Return ``(cues, zones, frame_status)`` where ``frame_status`` is ``json_ok`` or
    ``json_missing`` for the optional cue-view channel.
    """
    path = room_test_camera_json_path()
    obj = read_json_object(path)
    status = "json_missing" if obj is None else "json_ok"
    if obj is None:
        return ObservedCues(), _zero_zones(), status
    oc_raw = obj.get("observed_cues")
    oc_map = oc_raw if isinstance(oc_raw, dict) else {}
    z_raw = obj.get("camera_zones")
    z_map = z_raw if isinstance(z_raw, dict) else {}
    return _cues_from_mapping(oc_map).clamped(), _zones_from_mapping(z_map), status


def _parse_gopro_index_strict() -> int | None:
    """
    Return camera index when ``TRAVELMATE_GOPRO_CAMERA_INDEX`` is set, else None.

    Invalid values raise ``ValueError`` with an explicit message (no silent fallback).
    """
    raw = os.environ.get("TRAVELMATE_GOPRO_CAMERA_INDEX", "").strip()
    if not raw:
        return None
    try:
        idx = int(raw, 10)
    except ValueError as e:
        raise ValueError(
            "TRAVELMATE_GOPRO_CAMERA_INDEX must be a non-negative integer "
            f"(got {raw!r}). No fallback camera index is used."
        ) from e
    if idx < 0:
        raise ValueError(
            "TRAVELMATE_GOPRO_CAMERA_INDEX must be non-negative "
            f"(got {idx}). No fallback camera index is used."
        )
    return idx


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _room_test_vehicle_motion_sensitivity_boost() -> float:
    """
    ROOM_TEST only: modest >1 multiplier when CAN reports motion (perception shaping only).

    Uses the same ``read_can_context()`` path as the tick (room JSON / defaults).
    """
    if not room_test_enabled():
        return 1.0
    try:
        from adapters.can_adapter import read_can_context

        c = read_can_context()
    except Exception:
        return 1.0
    motion = max(float(c.speed), float(c.braking_intensity), float(c.turn_intensity))
    if getattr(c, "vehicle_stationary", True):
        motion *= 0.72
    return 1.0 + 0.55 * _clamp01(motion)


def _smooth(prev: float, target: float, alpha: float) -> float:
    a = _clamp01(alpha)
    return (1.0 - a) * prev + a * _clamp01(target)


def _zones_from_mask_vertical_thirds(mask: object, frame_w: int, frame_h: int) -> dict[str, float]:
    """Door = left third, mid = center, rear = right (deterministic geometry)."""
    import numpy as np

    z = _zero_zones()
    if frame_w <= 0 or frame_h <= 0:
        return z
    m = np.asarray(mask)
    if m.size == 0 or m.shape[0] != frame_h or m.shape[1] != frame_w:
        return z
    third = frame_w // 3
    if third < 1:
        return z
    w0, w1 = 0, third
    w1b, w2 = third, 2 * third
    w2b, w3 = 2 * third, frame_w
    door_m = float(m[:, w0:w1].sum())
    mid_m = float(m[:, w1b:w2].sum())
    rear_m = float(m[:, w2b:w3].sum())
    tot = door_m + mid_m + rear_m
    if tot < 1e-6:
        return z
    z["door"] = _clamp01(door_m / tot)
    z["mid"] = _clamp01(mid_m / tot)
    z["rear"] = _clamp01(rear_m / tot)
    return z


def _observed_cues_all_present(*, phase1: dict[str, float]) -> ObservedCues:
    """Build a full ``ObservedCues`` instance: phase‑1 from ``phase1``, everything else 0.0."""
    kw: dict[str, float] = {f.name: 0.0 for f in fields(ObservedCues)}
    for k, v in phase1.items():
        if k in kw:
            kw[k] = _clamp01(v)
    return ObservedCues(**kw).clamped()


class _GoProOpenCVPerception:
    """
    Stateful, deterministic pipeline: background model → foreground geometry →
    temporal motion statistics → phase‑1 cue confidences.
    """

    def __init__(self, camera_index: int, *, preview_title_suffix: str = "") -> None:
        self._camera_index = camera_index
        self._preview_window_title = f"{ROOM_TEST_PREVIEW_WINDOW_TITLE}{preview_title_suffix}"
        self._cap = None
        self._bg = None
        self._last_mono: float | None = None
        self._prev_cx: float | None = None
        self._prev_cy: float | None = None
        self._ema_horiz_speed = 0.0
        self._ema_near_door = 0.0
        self._standing_credit_secs = 0.0
        self._trail: Deque[tuple[float, float, float]] = deque(maxlen=90)  # t, cx_norm, cy_norm
        self._ema_unstable = 0.0
        self._ema_floor = 0.0
        self._fps_frames = 0
        self._fps_t0 = 0.0
        self._last_fps_logged = 0.0
        self._room_test_preview_named = False
        self._last_preview_frame: object | None = None
        self._preview_warned = False
        self._posture_var_deque: Deque[tuple[float, float, float]] = deque(maxlen=160)
        self._lean_sustain = 0.0
        self._bal_corr_acc = 0.0
        self._prev_vx_norm: float | None = None

    def reset_live_perception_state_after_arm(self) -> None:
        """Drop MOG/EMA/trail dwell state so evaluation resumes from a clean baseline."""
        import cv2

        self._ensure_capture()
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=100,
            varThreshold=40,
            detectShadows=False,
        )
        self._last_mono = None
        self._prev_cx = None
        self._prev_cy = None
        self._ema_horiz_speed = 0.0
        self._ema_near_door = 0.0
        self._standing_credit_secs = 0.0
        self._trail.clear()
        self._ema_unstable = 0.0
        self._ema_floor = 0.0
        self._fps_frames = 0
        self._fps_t0 = 0.0
        self._last_fps_logged = 0.0
        self._posture_var_deque.clear()
        self._lean_sustain = 0.0
        self._bal_corr_acc = 0.0
        self._prev_vx_norm = None

    def read_cabin_perception_hold_zeros_with_preview_only(
        self,
    ) -> tuple[ObservedCues, dict[str, float], str]:
        """
        Grab one frame for preview only; observed cues/zones forced to zero; no temporal/dwell accumulation.
        """
        self._ensure_capture()
        if self._cap is None:
            raise RuntimeError("internal error: OpenCV capture missing after _ensure_capture()")

        ok, frame = self._cap.read()
        shape: tuple[int, int] | None = None
        if ok and frame is not None:
            shape = (int(frame.shape[0]), int(frame.shape[1]))
            self._maybe_room_test_preview(frame)
        else:
            self._refresh_room_test_preview_last_good_if_any()

        zs = ObservedCues().clamped()
        zzones = _zero_zones()
        self._log_tick(
            frame_status="perception_hold",
            frame_shape=shape,
            cues=zs,
            zones=zzones,
        )
        self._pulse_room_test_preview_highgui()
        return zs, zzones, "perception_hold"

    def _ensure_capture(self) -> None:
        if self._cap is not None and self._cap.isOpened():
            return
        try:
            import cv2
        except ImportError as e:
            raise RuntimeError(
                "OpenCV is required for the GoPro camera adapter. Install opencv-python "
                "in this environment."
            ) from e

        idx = self._camera_index
        backend_used = "default"
        if sys.platform == "win32":
            self._cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            backend_used = "CAP_DSHOW"
            if not self._cap.isOpened():
                if self._cap is not None:
                    self._cap.release()
                if _truthy_env("ROOM_TEST_TRY_CAP_MSMF"):
                    self._cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
                    backend_used = "CAP_MSMF"
        else:
            self._cap = cv2.VideoCapture(idx)
        if not self._cap.isOpened():
            hint = (
                f"Live camera could not be opened: index={idx}, backend={backend_used}. "
                "Checklist: (1) Stop any other app using this device (e.g. room_test_camlink_verify.py, "
                "OBS, Windows Camera). (2) Confirm ROOM_TEST_CAMERA_INDEX matches the working index. "
                "(3) On Windows, try ROOM_TEST_TRY_CAP_MSMF=1 if DSHOW fails. "
                "(4) USB / Cam Link drivers. "
                "No fallback to a different device index."
            )
            raise RuntimeError(hint)

        if room_test_enabled():
            req_w, req_h = room_test_camera_resolution_wh()
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(req_w))
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(req_h))
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
            got_w = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            got_h = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            _LOG.info(
                "ROOM_TEST camera cap.set CAP_PROP_FRAME_WIDTH=%.0f CAP_PROP_FRAME_HEIGHT=%.0f "
                "(requested %dx%d) negotiated wxh=%.0fx%.0f",
                float(req_w),
                float(req_h),
                req_w,
                req_h,
                got_w,
                got_h,
            )

        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=100,
            varThreshold=40,
            detectShadows=False,
        )

    def _refresh_room_test_preview_last_good_if_any(self) -> None:
        """Keep preview responsive if the latest grab fails (common with DSHow webcams)."""
        lf = self._last_preview_frame
        if lf is None:
            return
        self._maybe_room_test_preview(lf)

    def _maybe_room_test_preview(self, frame: object) -> None:
        """
        Optional live window in the **same** process as ``runtime_loop`` (ROOM_TEST only).

        You cannot run ``room_test_camlink_verify.py`` at the same time on the same device:
        Windows allows only one capture handle per index. Use this flag instead of a second
        Python camera process.
        """
        if not _truthy_env("ROOM_TEST_SHOW_PREVIEW"):
            return
        try:
            import numpy as np
            import cv2

            if frame is None:
                return
            arr = np.asarray(frame)
            if arr.size == 0:
                return

            if not self._room_test_preview_named:
                cv2.namedWindow(self._preview_window_title, cv2.WINDOW_NORMAL)
                self._room_test_preview_named = True

            cv2.imshow(self._preview_window_title, frame)
            cv2.waitKey(1)
            try:
                self._last_preview_frame = frame.copy()
            except Exception:
                self._last_preview_frame = np.array(arr, copy=True)
        except Exception as e:
            self._room_test_preview_named = False
            if not self._preview_warned:
                _LOG.warning(
                    "ROOM_TEST live preview failed (will retry next frame): %s",
                    e,
                )
                self._preview_warned = True

    def _pulse_room_test_preview_highgui(self) -> None:
        """Extra waitKey keeps the preview window responding after heavy perception work."""
        if not _truthy_env("ROOM_TEST_SHOW_PREVIEW") or not self._room_test_preview_named:
            return
        try:
            import cv2

            cv2.waitKey(1)
        except Exception:
            pass

    def read_cabin_perception(self) -> tuple[ObservedCues, dict[str, float], str]:
        import cv2
        import numpy as np

        self._ensure_capture()
        if self._cap is None or self._bg is None:
            raise RuntimeError("internal error: OpenCV capture not initialized after _ensure_capture()")

        now = time.monotonic()
        dt = 0.05 if self._last_mono is None else max(1e-3, now - self._last_mono)
        self._last_mono = now

        ok, frame = self._cap.read()
        if ok and frame is not None:
            self._maybe_room_test_preview(frame)
        else:
            self._refresh_room_test_preview_last_good_if_any()

        if not ok or frame is None:
            self._decay_phase1_on_bad_frame(dt)
            stand_full_d = max(3.0, _env_float("TRAVELMATE_STANDING_FULL_SECS", 12.0))
            cues = _observed_cues_all_present(
                phase1={
                    "near_door_area": self._ema_near_door,
                    "prolonged_standing": _clamp01(self._standing_credit_secs / stand_full_d),
                    "unstable_posture": float(self._ema_unstable),
                    "floor_level_posture": self._ema_floor,
                    "frequent_balance_correction": _clamp01(self._bal_corr_acc),
                    "leaning_without_support": _clamp01(
                        self._lean_sustain / max(1e-6, _LEAN_SUSTAIN_FULL_SECS)
                    ),
                }
            )
            self._log_tick(
                frame_status="grab_failed",
                frame_shape=None,
                cues=cues,
                zones=_zero_zones(),
            )
            self._pulse_room_test_preview_highgui()
            return cues, _zero_zones(), "grab_failed"

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fg = self._bg.apply(gray)
        _, bin_mask = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        bin_mask = cv2.morphologyEx(bin_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        bin_mask = cv2.dilate(bin_mask, kernel, iterations=1)

        min_area_frac = _env_float("TRAVELMATE_FG_MIN_AREA_FRAC", 0.0015)
        min_area = max(400.0, min_area_frac * float(w * h))
        contours, _ = cv2.findContours(bin_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_area = 0.0
        for c in contours:
            a = float(cv2.contourArea(c))
            if a >= min_area and a > best_area:
                best_area = a
                best = c

        zones = _zones_from_mask_vertical_thirds(bin_mask, w, h)

        if best is None:
            while self._posture_var_deque and self._posture_var_deque[0][0] < now - (_INSTABILITY_ROLLING_SECS + 0.5):
                self._posture_var_deque.popleft()
            self._standing_credit_secs = max(0.0, self._standing_credit_secs - 0.4 * dt)
            self._ema_near_door = _smooth(self._ema_near_door, 0.0, 0.35)
            self._ema_unstable = _smooth(self._ema_unstable, 0.0, 0.4)
            self._ema_floor = _smooth(self._ema_floor, 0.0, 0.35)
            self._lean_sustain = max(0.0, self._lean_sustain - _LEAN_DECAY_UPRIGHT_PER_SEC * dt)
            self._bal_corr_acc *= math.exp(-dt / _BAL_CORR_DECAY_SECS_IDLE)
            self._prev_vx_norm = None
            stand_full = max(3.0, _env_float("TRAVELMATE_STANDING_FULL_SECS", 12.0))
            phase1 = {
                "near_door_area": float(self._ema_near_door),
                "prolonged_standing": _clamp01(self._standing_credit_secs / stand_full),
                "unstable_posture": float(self._ema_unstable),
                "floor_level_posture": float(self._ema_floor),
                "frequent_balance_correction": _clamp01(self._bal_corr_acc),
                "leaning_without_support": _clamp01(
                    self._lean_sustain / max(1e-6, _LEAN_SUSTAIN_FULL_SECS)
                ),
            }
            cues = _observed_cues_all_present(phase1=phase1)
            self._log_tick(
                frame_status="no_foreground",
                frame_shape=(h, w),
                cues=cues,
                zones=zones,
            )
            self._pulse_room_test_preview_highgui()
            return cues, zones, "no_foreground"

        moments = cv2.moments(best)
        if moments["m00"] < 1e-6:
            m00 = 1e-6
        else:
            m00 = moments["m00"]
        cx = float(moments["m10"] / m00)
        cy = float(moments["m01"] / m00)
        x, y, bw, bh = cv2.boundingRect(best)

        cx_n = cx / float(w)
        cy_n = cy / float(h)

        door_frac = _env_float("TRAVELMATE_DOOR_BAND_FRAC", 0.30)
        door_frac = max(0.08, min(0.45, door_frac))
        door_band = bin_mask[:, 0 : max(1, int(door_frac * w))]
        mass_door = float(door_band.sum())
        mass_total = float(bin_mask.sum()) + 1e-6
        door_mass_ratio = mass_door / mass_total
        centroid_door_boost = 1.0 if cx < door_frac * w else 0.0
        raw_near_door = max(door_mass_ratio, 0.55 * centroid_door_boost * min(1.0, mass_total / (255.0 * w * h * 0.02)))
        self._ema_near_door = _smooth(self._ema_near_door, raw_near_door, 0.28)
        near_door_area = self._ema_near_door

        boost = _room_test_vehicle_motion_sensitivity_boost()

        speed_norm = 0.0
        vx_norm = 0.0
        if self._prev_cx is not None and self._prev_cy is not None:
            disp = float(np.hypot(cx - self._prev_cx, cy - self._prev_cy))
            speed_norm = disp / float(w) / dt
            vx_norm = (cx - self._prev_cx) / float(w) / max(1e-3, dt)

        correction_observed = False
        if self._prev_vx_norm is not None:
            if self._prev_vx_norm * vx_norm < 0.0 and abs(self._prev_vx_norm) > 1.4e-4 and abs(vx_norm) > 1.4e-4:
                self._bal_corr_acc += 0.52 * boost
                correction_observed = True
            micro = abs(vx_norm - self._prev_vx_norm)
            if micro > _BAL_CORR_MICRO_EPS:
                self._bal_corr_acc += micro * 6.2 * dt * boost
                correction_observed = True
        bal_tau = (
            _BAL_CORR_DECAY_SECS_ACTIVE if correction_observed else _BAL_CORR_DECAY_SECS_IDLE
        )
        self._bal_corr_acc *= math.exp(-dt / bal_tau)
        self._bal_corr_acc = max(0.0, min(1.85, self._bal_corr_acc))
        self._prev_vx_norm = vx_norm

        self._prev_cx, self._prev_cy = cx, cy
        self._ema_horiz_speed = _smooth(self._ema_horiz_speed, speed_norm, 0.22)

        stand_thresh = _env_float("TRAVELMATE_STANDING_SPEED_THRESH", 0.018)
        stand_full = _env_float("TRAVELMATE_STANDING_FULL_SECS", 12.0)
        stand_full = max(3.0, stand_full)
        if self._ema_horiz_speed < stand_thresh:
            self._standing_credit_secs = min(stand_full * 1.25, self._standing_credit_secs + dt)
        else:
            self._standing_credit_secs = max(0.0, self._standing_credit_secs - 1.2 * dt)
        prolonged_standing = _clamp01(self._standing_credit_secs / stand_full)

        self._trail.append((now, cx_n, cy_n))
        while self._trail and (now - self._trail[0][0]) > 2.2:
            self._trail.popleft()
        cy_vals = np.array([t[2] for t in self._trail], dtype=np.float64)
        if cy_vals.size >= 5:
            dcy = np.diff(cy_vals)
            vert_jitter = float(np.std(dcy)) if dcy.size else 0.0
            walk_like = 1.0 if self._ema_horiz_speed > stand_thresh * 2.8 else 0.0
            raw_unstable = vert_jitter * 18.0 * (1.0 - 0.65 * walk_like)
        else:
            raw_unstable = 0.0

        self._posture_var_deque.append((now, cx_n, cy_n))
        while self._posture_var_deque and self._posture_var_deque[0][0] < now - _INSTABILITY_ROLLING_SECS:
            self._posture_var_deque.popleft()
        var_score = 0.0
        if len(self._posture_var_deque) >= 6:
            arr = np.array([(p[1], p[2]) for p in self._posture_var_deque], dtype=np.float64)
            pos_spread = float(np.std(arr[:, 0]) ** 2 + np.std(arr[:, 1]) ** 2) ** 0.5
            var_score = _clamp01((pos_spread - 0.006) * 26.0 * (0.82 + 0.18 * boost))

        raw_inst_combined = max(var_score, raw_unstable * (0.48 + 0.22 * (boost - 1.0)))
        self._ema_unstable = _smooth(self._ema_unstable, raw_inst_combined, 0.3)
        unstable_posture = _clamp01(self._ema_unstable)

        raw_lean = abs(cx_n - 0.5) * 2.08
        lean_gate = max(0.0, raw_lean - 0.10)
        if lean_gate >= _LEAN_GATE_ACCUM:
            self._lean_sustain = min(
                14.0,
                self._lean_sustain + dt * lean_gate * 0.44 * (0.88 + 0.12 * boost),
            )
        elif lean_gate <= _LEAN_GATE_DECAY:
            self._lean_sustain = max(0.0, self._lean_sustain - _LEAN_DECAY_UPRIGHT_PER_SEC * dt)
        else:
            self._lean_sustain = max(0.0, self._lean_sustain - _LEAN_DECAY_MIDZONE_PER_SEC * dt)
        leaning_without_support = _clamp01(self._lean_sustain / _LEAN_SUSTAIN_FULL_SECS)

        frequent_balance_correction = _clamp01(self._bal_corr_acc)

        bottom_frac = (y + bh) / float(h)
        rel_h = bh / float(h)
        floor_geom = max(0.0, bottom_frac - 0.72) / 0.28
        height_factor = max(0.0, 1.0 - min(1.0, rel_h / 0.42))
        raw_floor = _clamp01(floor_geom * (0.55 + 0.45 * height_factor))
        self._ema_floor = _smooth(self._ema_floor, raw_floor, 0.3)
        floor_level_posture = _clamp01(self._ema_floor)

        phase1 = {
            "near_door_area": float(near_door_area),
            "prolonged_standing": float(prolonged_standing),
            "unstable_posture": float(unstable_posture),
            "floor_level_posture": float(floor_level_posture),
            "frequent_balance_correction": float(frequent_balance_correction),
            "leaning_without_support": float(leaning_without_support),
        }
        cues = _observed_cues_all_present(phase1=phase1)
        self._log_tick(
            frame_status="ok",
            frame_shape=(h, w),
            cues=cues,
            zones=zones,
        )
        self._pulse_room_test_preview_highgui()
        return cues, zones, "ok"

    def _decay_phase1_on_bad_frame(self, dt: float) -> None:
        """Transient grab failure: soften motion state; do not treat as instant zero subject."""
        self._ema_near_door = _smooth(self._ema_near_door, 0.0, 0.45)
        self._ema_unstable = _smooth(self._ema_unstable, 0.0, 0.5)
        self._ema_floor = _smooth(self._ema_floor, 0.0, 0.5)
        self._standing_credit_secs = max(0.0, self._standing_credit_secs - 0.8 * dt)
        self._lean_sustain = max(0.0, self._lean_sustain - 0.55 * dt)
        self._bal_corr_acc *= math.exp(-dt / 2.2)
        self._prev_vx_norm = None

    def _log_tick(
        self,
        *,
        frame_status: str,
        frame_shape: tuple[int, int] | None,
        cues: ObservedCues,
        zones: dict[str, float],
    ) -> None:
        d = asdict(cues)
        cue_str = ", ".join(f"{k}={d[k]:.4f}" for k in sorted(d.keys()))
        shape = "None" if frame_shape is None else f"{frame_shape[0]}x{frame_shape[1]}"
        now = time.monotonic()
        fps_note = ""
        if frame_status == "ok" and frame_shape is not None:
            if self._fps_frames == 0:
                self._fps_t0 = now
            self._fps_frames += 1
            elapsed = max(1e-3, now - self._fps_t0)
            if self._fps_frames >= 30 or elapsed >= 2.0:
                fps_est = float(self._fps_frames) / elapsed
                fps_note = f" fps_estimate={fps_est:.1f}"
                self._fps_frames = 0
                self._fps_t0 = now
                self._last_fps_logged = fps_est
        inst_suffix = ""
        if room_test_enabled():
            inst_e = _clamp01(
                0.34 * float(d["unstable_posture"])
                + 0.33 * float(d["frequent_balance_correction"])
                + 0.33 * float(d["leaning_without_support"])
            )
            inst_suffix = f" instability_energy={inst_e:.4f}"
        _LOG.info(
            "camera_tick index=%s frame_status=%s frame_shape=%s zones=%s%s | %s%s",
            self._camera_index,
            frame_status,
            shape,
            {k: round(float(zones.get(k, 0.0)), 4) for k in _CAMERA_ZONE_KEYS},
            fps_note,
            cue_str,
            inst_suffix,
        )
        _emit_camera_cues_view(
            camera_index_display=str(self._camera_index),
            frame_status=frame_status,
            cues=cues,
        )


_gopro_engines: dict[int, _GoProOpenCVPerception] = {}


def _get_gopro_engine(index: int, *, preview_title_suffix: str = "") -> _GoProOpenCVPerception:
    global _gopro_engines
    if index not in _gopro_engines:
        _gopro_engines[index] = _GoProOpenCVPerception(index, preview_title_suffix=preview_title_suffix)
    return _gopro_engines[index]


def _consume_room_test_live_hold_for_engines(
    engines: tuple[_GoProOpenCVPerception, ...],
) -> tuple[ObservedCues, dict[str, float], str] | None:
    """
    ROOM_TEST perception start delay across one or more OpenCV engines: during hold,
    previews update but fused cues/zones stay zero.
    """
    global _live_perception_hold_until_mono
    if _live_perception_hold_until_mono is None:
        return None
    now = time.monotonic()
    if now < _live_perception_hold_until_mono:
        zz_acc = _zero_zones()
        cues_acc = ObservedCues().clamped()
        for eng in engines:
            hz, zn, _st = eng.read_cabin_perception_hold_zeros_with_preview_only()
            zz_acc = _fuse_camera_zones_max(zz_acc, zn)
            cues_acc = _fuse_observed_cues_max(cues_acc, hz)
        return cues_acc, zz_acc, "perception_hold"
    for eng in engines:
        eng.reset_live_perception_state_after_arm()
    _live_perception_hold_until_mono = None
    armed_msg = "PERCEPTION ARMED – evaluation started"
    _LOG.info("%s", armed_msg)
    print(armed_msg, flush=True)
    return None


def _consume_room_test_live_hold_if_any(
    eng: _GoProOpenCVPerception,
) -> tuple[ObservedCues, dict[str, float], str] | None:
    return _consume_room_test_live_hold_for_engines((eng,))


def read_cabin_perception() -> tuple[ObservedCues, dict[str, float], str]:
    """
    Latest cabin cues plus optional camera zone weights (door / mid / rear).

    * Non–room-test: fixed fake cues and zero zone weights (legacy PoC).
    * Room test + ``ROOM_TEST_DUAL_CAMERA`` (+ zone indices): two OpenCV devices; fused cues;
      snapshots for paired :class:`camera_observation_contract.CameraObservation` rows (see
      :func:`pop_dual_observation_snapshots`).
    * Room test + ``ROOM_TEST_LIVE_CAMERA`` + ``ROOM_TEST_CAMERA_INDEX``: live OpenCV
      capture (same pipeline as GOPRO helper); fails loudly if unset or device cannot open;
      **never** reads ``camera_cues.json``.
    * Room test + ``TRAVELMATE_GOPRO_CAMERA_INDEX`` (legacy): live OpenCV if set.
    * Room test otherwise: JSON file only (missing file → safe zeros).
    """
    global _dual_observation_snapshots
    _dual_observation_snapshots = None

    if room_test_enabled():
        if room_test_dual_camera_enabled():
            idx1 = parse_room_test_zone1_camera_index_for_dual()
            idx2 = parse_room_test_zone2_camera_index_for_dual()
            if idx1 == idx2:
                raise RuntimeError(
                    "ROOM_TEST_DUAL_CAMERA requires distinct OpenCV indices for "
                    "ROOM_TEST_CAMERA_INDEX_ZONE1 (/ legacy ROOM_TEST_CAMERA_INDEX) and ROOM_TEST_CAMERA_INDEX_ZONE2 "
                    f"(both were {idx1})."
                )
            eng1 = _get_gopro_engine(idx1, preview_title_suffix=" · Zone 1 front")
            eng2 = _get_gopro_engine(idx2, preview_title_suffix=" · Zone 2 mid")
            held = _consume_room_test_live_hold_for_engines((eng1, eng2))
            if held is not None:
                return held
            c1, z1, s1 = eng1.read_cabin_perception()
            c2, z2, s2 = eng2.read_cabin_perception()
            fused_cues = _fuse_observed_cues_max(c1, c2)
            fused_z = _fuse_camera_zones_max(z1, z2)
            mono_snap = time.monotonic()
            _dual_observation_snapshots = [
                (
                    _dual_camera_logical_id(CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT),
                    CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
                    mono_snap,
                    c1,
                    s1,
                ),
                (
                    _dual_camera_logical_id(CabinZoneId.ZONE_2_MID_CABIN),
                    CabinZoneId.ZONE_2_MID_CABIN,
                    mono_snap,
                    c2,
                    s2,
                ),
            ]
            return fused_cues, fused_z, f"dual:z1={s1};z2={s2}"
        if room_test_live_camera_enabled():
            idx_live = parse_room_test_camera_index_required()
            eng = _get_gopro_engine(idx_live)
            held = _consume_room_test_live_hold_if_any(eng)
            if held is not None:
                return held
            return eng.read_cabin_perception()
        idx = _parse_gopro_index_strict()
        if idx is not None:
            eng = _get_gopro_engine(idx)
            held = _consume_room_test_live_hold_if_any(eng)
            if held is not None:
                return held
            return eng.read_cabin_perception()
        cues, zones, json_status = _read_room_file()
        _emit_camera_cues_view(
            camera_index_display="json",
            frame_status=json_status,
            cues=cues,
        )
        return cues, zones, json_status

    cues = ObservedCues(
        unstable_posture=0.7,
        prolonged_standing=0.35,
        rapid_erratic_motion=0.1,
    )
    _emit_camera_cues_view(
        camera_index_display="demo",
        frame_status="synthetic",
        cues=cues,
    )
    return cues, _zero_zones(), "synthetic"


def read_observed_cues() -> ObservedCues:
    """Return the latest observed cabin cue snapshot for one tick."""
    return read_cabin_perception()[0]


__all__ = [
    "perception_start_delay_seconds_room_test",
    "pop_dual_observation_snapshots",
    "read_cabin_perception",
    "read_observed_cues",
    "room_test_schedule_live_camera_perception_start_delay",
]
