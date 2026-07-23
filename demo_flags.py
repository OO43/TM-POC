# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""Tiny env gate so ``demo_simulator`` is not imported when demo is off."""

from __future__ import annotations

import os


def travelmate_demo_enabled() -> bool:
    """True when ``TRAVELMATE_DEMO`` or ``DEMO_MODE`` is set to 1/true/yes."""
    for key in ("TRAVELMATE_DEMO", "DEMO_MODE"):
        v = os.environ.get(key, "").strip().lower()
        if v in ("1", "true", "yes"):
            return True
    return False
