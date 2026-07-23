# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — stacked / queued alert display state (backend contract).

Maintains a deterministic ordered list of active alerts across ticks, driven only by
``evaluate_driver_tick`` outcomes and the tick dict (BLE zone, support categories).
Does not change detection, thresholds, priorities, or driver-facing wording.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypedDict

from driver_alert_text import render_driver_alert
from emergency import EmergencyEvent
from policy_arbitration import FULL_ALERT_PRIORITY
from thresholds import AlertType, SupportCategory
from tick_driver_eval import DriverTickOutcome


def _support_categories_from_tick(tick: dict) -> set[SupportCategory]:
    """Match tick_driver_eval / main harness (legacy ``support_category`` key)."""
    raw = tick.get("support_categories")
    if raw is not None:
        out = {SupportCategory(x) for x in raw}
        return out if out else {SupportCategory.UNDECLARED}
    if "support_category" in tick:
        return {SupportCategory(tick["support_category"])}
    return {SupportCategory.UNDECLARED}

# Lower index = higher operational priority (same order as policy_arbitration).
_ALERT_PRIORITY_INDEX: dict[AlertType, int] = {a: i for i, a in enumerate(FULL_ALERT_PRIORITY)}
# Emergencies sort before any operational alert in the stacked list.
_EMERGENCY_PRIORITY_INDEX = -1


class AlertItemDict(TypedDict):
    """One row for UI / API consumers."""

    alert_type: str
    priority: int
    message: str
    zone: str | None
    time_raised: str
    requires_ack: bool


class AlertDisplayContract(TypedDict):
    """Backend output contract for tablet / HMI (no UI logic here)."""

    primary_alert: AlertItemDict | None
    ordered_alerts: list[AlertItemDict]
    alerts_pending: bool
    camera_auto_display_allowed: bool


def _operational_priority(at: AlertType) -> int:
    return _ALERT_PRIORITY_INDEX.get(at, len(FULL_ALERT_PRIORITY))


def _zone_from_tick(tick: dict) -> str | None:
    ble = tick.get("ble")
    if not isinstance(ble, dict) or not ble.get("enabled"):
        return None
    z = ble.get("zone")
    return str(z) if z is not None else None


def _message_operational(at: AlertType, support_categories: set[SupportCategory]) -> str:
    return render_driver_alert(
        alert_type=at,
        scenario_matched=True,
        should_alert=True,
        emergency_sticky=None,
        emergency_immediate=None,
        support_categories=support_categories,
    )


def _message_emergency_sticky(
    ev: EmergencyEvent, support_categories: set[SupportCategory]
) -> str:
    return render_driver_alert(
        alert_type=None,
        scenario_matched=False,
        should_alert=False,
        emergency_sticky=ev,
        emergency_immediate=None,
        support_categories=support_categories,
    )


def _message_emergency_immediate(
    ev: EmergencyEvent, support_categories: set[SupportCategory]
) -> str:
    return render_driver_alert(
        alert_type=None,
        scenario_matched=False,
        should_alert=False,
        emergency_sticky=None,
        emergency_immediate=ev,
        support_categories=support_categories,
    )


@dataclass
class _ActiveRow:
    """Internal persisted row (stable key + sort keys)."""

    key: str
    alert_type: str
    priority: int
    message: str
    zone: str | None
    time_raised_iso: str
    first_seen_monotonic: float
    requires_ack: bool

    def to_item(self) -> AlertItemDict:
        return AlertItemDict(
            alert_type=self.alert_type,
            priority=self.priority,
            message=self.message,
            zone=self.zone,
            time_raised=self.time_raised_iso,
            requires_ack=self.requires_ack,
        )


class AlertDisplayStack:
    """
    Stateful stack: merges per-tick detections with persistence until conditions clear.
    Emergency-active ticks replace operational rows (non-distracting single focus path).
    """

    __slots__ = ("_rows",)

    def __init__(self) -> None:
        self._rows: dict[str, _ActiveRow] = {}

    def step(
        self,
        tick: dict,
        out: DriverTickOutcome,
        *,
        now: datetime | None = None,
    ) -> AlertDisplayContract:
        wall = now or datetime.now(timezone.utc)
        now_mono = time.monotonic()
        zone = _zone_from_tick(tick)
        support_categories = _support_categories_from_tick(tick)

        wanted: dict[str, tuple[str, int, str, bool]] = {}
        # key -> (alert_type field, priority index, message, requires_ack)

        if out.kind == "sticky_pending":
            ev = out.emergency_sticky_next
            if ev is not None:
                k = f"emergency:{ev.value}"
                wanted[k] = (
                    f"emergency_{ev.value}",
                    _EMERGENCY_PRIORITY_INDEX,
                    _message_emergency_sticky(ev, support_categories),
                    True,
                )
        elif out.kind == "immediate":
            ev = out.emergency_immediate
            if ev is not None:
                k = f"emergency:{ev.value}"
                wanted[k] = (
                    f"emergency_{ev.value}",
                    _EMERGENCY_PRIORITY_INDEX,
                    _message_emergency_immediate(ev, support_categories),
                    True,
                )
        else:
            for at in out.passing_operational_types:
                k = at.value
                wanted[k] = (
                    at.value,
                    _operational_priority(at),
                    _message_operational(at, support_categories),
                    False,
                )

        next_rows: dict[str, _ActiveRow] = {}
        for key, (alert_type, priority, message, requires_ack) in wanted.items():
            prev = self._rows.get(key)
            if prev is None:
                next_rows[key] = _ActiveRow(
                    key=key,
                    alert_type=alert_type,
                    priority=priority,
                    message=message,
                    zone=zone,
                    time_raised_iso=wall.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    first_seen_monotonic=now_mono,
                    requires_ack=requires_ack,
                )
            else:
                next_rows[key] = _ActiveRow(
                    key=key,
                    alert_type=alert_type,
                    priority=priority,
                    message=message,
                    zone=zone,
                    time_raised_iso=prev.time_raised_iso,
                    first_seen_monotonic=prev.first_seen_monotonic,
                    requires_ack=requires_ack,
                )

        self._rows = next_rows

        ordered = sorted(
            self._rows.values(),
            key=lambda r: (r.priority, r.first_seen_monotonic),
        )
        items: list[AlertItemDict] = [r.to_item() for r in ordered]
        primary: AlertItemDict | None = items[0] if items else None
        pending = len(items) > 0

        return AlertDisplayContract(
            primary_alert=primary,
            ordered_alerts=items,
            alerts_pending=pending,
            camera_auto_display_allowed=not pending,
        )


def alert_display_contract_to_jsonable(contract: AlertDisplayContract) -> dict[str, Any]:
    """Plain dict/list structure for JSON logging (TypedDict is dict at runtime)."""
    return dict(contract)
