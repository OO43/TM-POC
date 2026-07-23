# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
ROOM_TEST / tablet simulation limits — single source of truth for UI ranges.

CANContext.speed in the PoC pipeline is normalized to [0, 1] for ``derive_motion_level``.
Display and sliders use km/h; conversion uses ``MAX_REALISTIC_SPEED_KMH``.
"""

from __future__ import annotations

# Urban / coach-style upper bound for simulation (not a legal claim).
MAX_REALISTIC_SPEED_KMH: float = 90.0
MAX_BRAKING_INTENSITY: float = 1.0
MAX_TURN_INTENSITY: float = 1.0


def speed_kmh_to_normalized(speed_kmh: float) -> float:
    if speed_kmh <= 0.0:
        return 0.0
    return min(1.0, float(speed_kmh) / MAX_REALISTIC_SPEED_KMH)


def normalized_speed_to_kmh(normalized_speed: float) -> float:
    return max(
        0.0,
        min(MAX_REALISTIC_SPEED_KMH, float(normalized_speed) * MAX_REALISTIC_SPEED_KMH),
    )


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
