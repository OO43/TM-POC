# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Cam Link 4K room-test verification loop (OpenCV).

This script intentionally opens exactly one configured capture device and never
falls back to a different camera. It is a simple test harness for verifying the
live feed path before adding room-door logic.

Usage examples (PowerShell):
  python room_test_camlink_verify.py --device-index 1
  python room_test_camlink_verify.py --device-index 1 --width 1920 --height 1080 --fps 30
"""

from __future__ import annotations

import argparse
import time

import cv2


WINDOW_NAME = "TravelMate ROOM_TEST - Cam Link 4K Verify"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verify Cam Link 4K realtime feed via OpenCV.")
    p.add_argument(
        "--device-index",
        type=int,
        required=True,
        help="Windows video device index for Cam Link 4K (required; no fallback camera).",
    )
    p.add_argument("--width", type=int, default=1280, help="Requested frame width.")
    p.add_argument("--height", type=int, default=720, help="Requested frame height.")
    p.add_argument("--fps", type=int, default=30, help="Requested frame rate.")
    return p


def _open_capture(device_index: int, width: int, height: int, fps: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(
            f"Failed to open capture device index={device_index}. "
            "No fallback is attempted."
        )

    # Request deterministic capture properties. The camera/driver may negotiate.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    cap.set(cv2.CAP_PROP_FPS, float(fps))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
    return cap


def run_loop(device_index: int, width: int, height: int, fps: int) -> None:
    cap = _open_capture(device_index, width, height, fps)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    print(
        f"[room-test] source=device-index:{device_index} "
        f"requested={width}x{height}@{fps}fps | press 'q' or ESC to exit"
    )

    frames = 0
    start = time.time()
    last_log = start
    failures = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                if failures >= 20:
                    raise RuntimeError("Capture read failed repeatedly; stopping verification loop.")
                continue
            failures = 0
            frames += 1

            now = time.time()
            if now - last_log >= 2.0:
                elapsed = max(1e-6, now - start)
                live_fps = frames / elapsed
                print(f"[room-test] frames={frames} avg_fps={live_fps:.1f}")
                last_log = now

            cv2.imshow(WINDOW_NAME, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    args = _build_parser().parse_args()
    run_loop(
        device_index=args.device_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )


if __name__ == "__main__":
    main()
