# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — occupancy / load (PoC).

Simulates an adapter that estimates onboard count vs rated capacity (e.g. from
door counters or AI crowd estimate). No identity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DensityContext:
    passengers_onboard: int
    vehicle_capacity: int

    def __post_init__(self) -> None:
        if self.vehicle_capacity <= 0:
            raise ValueError("vehicle_capacity must be positive")
        if self.passengers_onboard < 0:
            raise ValueError("passengers_onboard cannot be negative")


def derive_density_level(ctx: DensityContext) -> float:
    """Normalized load in [0, 1]; 1.0 means at or above nominal capacity."""
    ratio = ctx.passengers_onboard / float(ctx.vehicle_capacity)
    return max(0.0, min(1.0, ratio))
