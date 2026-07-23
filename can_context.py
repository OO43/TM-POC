# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — vehicle-side context from CAN (PoC abstraction).

These fields stand in for decoded OBD-II / J1939 / manufacturer CAN frames (e.g. wheel
speed, brake pressure, steering angle, door latch, ramp ECU status). Values are
simulated in the PoC; no bus drivers or parsing here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CANContext:
    """
    Snapshot of vehicle state relevant to motion and accessibility hardware.

    In a full system, each field would be populated from periodic CAN messages
    (normalized or raw counts → engineering units in an adapter layer).
    """

    speed: float  # e.g. m/s or km/h normalized to a PoC scale [0, 1] for simulation
    braking_intensity: float  # e.g. deceleration demand or brake pressure → [0, 1]
    turn_intensity: float  # e.g. yaw rate or steering angle magnitude → [0, 1]
    doors_open: bool  # any passenger door open (logical OR of door switches)
    ramp_deployed: bool  # wheelchair lift / ramp in deployed position
    vehicle_stationary: bool = False  # e.g. wheel speed / park brake / standstill flag from CAN


def derive_motion_level(ctx: CANContext) -> float:
    """
    Single vehicle-motion stress signal in [0, 1] for the existing risk pipeline.

    Real CAN mapping (later): wheel-speed derivatives -> speed; brake pressure or
    requested deceleration -> braking_intensity; yaw rate or steer angle -> turn_intensity.
    Doors/ramp override: boarding / alighting / lift ops → no inertial passenger-motion risk.
    """
    if ctx.doors_open or ctx.ramp_deployed:
        return 0.0
    combined = (
        0.50 * ctx.speed
        + 0.35 * ctx.braking_intensity
        + 0.15 * ctx.turn_intensity
    )
    if combined < 0.0:
        return 0.0
    if combined > 1.0:
        return 1.0
    return combined
