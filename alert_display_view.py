# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
HTTP/test mapping from ``BackendSession.step`` output to read-only alert rows.

Pure projection only — does not evaluate ticks or alter ``AlertDisplayStack``.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from thresholds import AlertType


CoarseAlertType = Literal["emergency", "instability", "advisory"]

# Softer operational kinds → advisory (blue); everything else operational → instability/risk (orange).
_ADVISORY_ALERT_VALUES: frozenset[str] = frozenset(
    {
        AlertType.VULNERABILITY_ASSISTANCE_ADVISORY.value,
        AlertType.VULNERABLE_EXIT_CROWD_ASSISTANCE_ADVISORY.value,
        AlertType.EXIT_PREPARATION.value,
        AlertType.JOURNEY_END_CHECK.value,
        AlertType.CROWDING_ADVISORY.value,
        AlertType.ROUTE_DIVERSION_ACTIVE.value,
        AlertType.PASSENGER_REMAINING_ONBOARD_ADVISORY.value,
    }
)


def coarse_alert_type(item_alert_type: str, requires_ack: bool) -> CoarseAlertType:
    """Bucket for distraction-testing UI styling (not a safety classifier)."""
    if requires_ack or item_alert_type.startswith("emergency_"):
        return "emergency"
    if item_alert_type in _ADVISORY_ALERT_VALUES:
        return "advisory"
    return "instability"


def alert_rows_from_backend_output(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    One JSON-serializable dict per stacked row in ``ordered_alerts`` (runtime source of truth).

    Fields: id, priority, alert_type, message, active, sticky, timestamp
    """
    ordered = output.get("ordered_alerts") or []
    rows: list[dict[str, Any]] = []
    for row in ordered:
        raw = str(row["alert_type"])
        requires_ack = bool(row["requires_ack"])
        coarse = coarse_alert_type(raw, requires_ack)
        rows.append(
            {
                "id": raw,
                "priority": int(row["priority"]),
                "alert_type": coarse,
                "message": str(row["message"]),
                "active": True,
                "sticky": requires_ack,
                "timestamp": str(row["time_raised"]),
            }
        )
    rows.sort(key=lambda r: (r["priority"], r["timestamp"]))
    return rows
