# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Cam Link 4K — minimal frame-differencing motion test (no ML, no model downloads).

Uses the same single-device rule as room_test_camlink_verify.py: one --device-index,
no automatic fallback to other cameras. Intended to verify that movement produces a
larger change signal and stillness does not, before any zone or alert integration.

Run (example):
  python room_test_camlink_motion.py --device-index 1 --width 1920 --height 1080 --fps 30
"""

from __future__ import annotations

import argparse
import time

import cv2

WINDOW_NAME = "TravelMate ROOM_TEST - Cam Link Motion (absdiff)"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cam Link motion probe: grayscale absdiff; shows live BGR + heatmap."
    )
    p.add_argument(
        "--device-index",
        type=int,
        required=True,
        help="Windows video device index for Cam Link 4K (required; no fallback).",
    )
    p.add_argument("--width", type=int, default=1280, help="Requested frame width.")
    p.add_argument("--height", type=int, default=720, help="Requested frame height.")
    p.add_argument("--fps", type=int, default=30, help="Requested frame rate (e.g. 30 or 60).")
    p.add_argument(
        "--blur",
        type=int,
        default=5,
        help="Odd Gaussian blur kernel size (noise rejection).",
    )
    p.add_argument(
        "--print-every-sec",
        type=float,
        default=1.0,
        help="How often to print mean motion and FPS to the console.",
    )
    return p


def _open_capture(device_index: int, width: int, height: int, fps: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(
            f"Failed to open capture device index={device_index}. No fallback is attempted."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    cap.set(cv2.CAP_PROP_FPS, float(fps))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
    return cap


def _odd_kernel(n: int) -> int:
    n = max(1, n)
    if n % 2 == 0:
        n += 1
    return n


def run_motion_loop(
    device_index: int,
    width: int,
    height: int,
    fps: int,
    blur: int,
    print_every_sec: float,
) -> None:
    cap = _open_capture(device_index, width, height, fps)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    k = _odd_kernel(blur)
    prev_gray = None
    frame_count = 0
    t0 = time.time()
    last_print = t0
    failures = 0

    print(
        f"[room-test/motion] device-index={device_index} requested={width}x{height}@{fps}fps | "
        f"mean=avg absdiff 0-255 in ROI | q or Esc exit"
    )

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                if failures >= 20:
                    raise RuntimeError("Capture read failed repeatedly; stopping.")
                continue
            failures = 0
            frame_count += 1

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (k, k), 0)
            if prev_gray is None:
                prev_gray = gray.copy()
                continue

            diff = cv2.absdiff(gray, prev_gray)
            prev_gray = gray.copy()

            motion_mean = float(cv2.mean(diff)[0])
            # Heatmap of change (normalized per frame for display only).
            heat = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
            heat_bgr = cv2.applyColorMap(heat, cv2.COLORMAP_JET)
            h, w0 = frame.shape[:2]
            if heat_bgr.shape[:2] != (h, w0):
                heat_bgr = cv2.resize(heat_bgr, (w0, h))
            combo = cv2.hconcat([frame, heat_bgr])
            y0 = 28
            cv2.putText(
                combo,
                f"mean absdiff: {motion_mean:.1f}   (higher = more change vs previous frame)",
                (10, y0),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
            now = time.time()
            if now - last_print >= print_every_sec:
                elapsed = max(1e-6, now - t0)
                live_fps = frame_count / elapsed
                print(
                    f"[room-test/motion] frames={frame_count} avg_fps={live_fps:.1f} mean_absdiff={motion_mean:.2f}"
                )
                last_print = now

            cv2.imshow(WINDOW_NAME, combo)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    args = _build_parser().parse_args()
    run_motion_loop(
        device_index=args.device_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
        blur=args.blur,
        print_every_sec=args.print_every_sec,
    )


if __name__ == "__main__":
    main()
