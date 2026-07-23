# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — explicit human / app event hooks (PoC).

No network or mobile code. These structures mirror future tablet / TravelMate app
payloads injected by adapters into the decision engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriverEventContext:
    """Driver tablet: route diversion (operator-initiated)."""

    diversion_active: bool = False
    diversion_reason: str | None = None


@dataclass(frozen=True)
class PassengerEventContext:
    """TravelMate app: consented passenger stop request (not an emergency classifier)."""

    stop_request: bool = False
    source: str = "app"
    consented: bool = False
