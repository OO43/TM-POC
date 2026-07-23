# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — optional BLE zone-hint adapter (PoC).

Later: connect to consent-gated BLE proximity hints (zone + confidence only;
no MAC storage in policy path). Outputs ``BLEProximityContext`` or ``None`` when
disabled / unavailable.

No decision logic exists in this module.
"""

from __future__ import annotations

from ble_proximity import BLEProximityContext


def read_ble_proximity() -> BLEProximityContext | None:
    """
    Return optional BLE snapshot, or ``None`` if the subsystem is off.

    Fake PoC implementation: always disabled (no hints).
    """
    return None
