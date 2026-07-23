# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — driver tablet adapter (PoC).

Later: connect to operator tablet events (e.g. route diversion acknowledgment
payloads). Outputs ``DriverEventContext`` only.

No decision logic or motion gating exists in this module; the engine enforces
diversion policy when consuming the tick dict.
"""

from __future__ import annotations

from event_contexts import DriverEventContext


def read_driver_events() -> DriverEventContext:
    """Fake PoC implementation: no diversion active."""
    return DriverEventContext(diversion_active=False, diversion_reason=None)
