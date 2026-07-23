# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — TravelMate passenger app adapter (PoC).

Later: connect to authenticated app payloads (consent registry, stop requests).
Outputs ``ConsentContext``, passenger events, and explicit policy toggles only.

Passenger consent is explicit and user-declared. No medical diagnosis is
performed. No AI, NLP, or ML interpretation is used. The engine reacts only to
declared support needs mapped through the fixed table below.

No decision logic, scenario classification, or alerting exists in this module.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from adapters.room_test_env import (
    read_json_object,
    room_test_consent_json_path,
    room_test_enabled,
    room_test_passenger_json_path,
)
from consent_context import ConsentContext
from event_contexts import PassengerEventContext
from thresholds import SupportCategory

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Fixed UI option → policy support category (explicit mapping only).
# Unknown strings are rejected with a warning; never inferred.
# -----------------------------------------------------------------------------
CONSENT_UI_OPTION_TO_SUPPORT: dict[str, SupportCategory] = {
    "avoid_sudden_braking": SupportCategory.MEDICAL_SENSITIVITY,
    "motion_sensitive": SupportCategory.MEDICAL_SENSITIVITY,
    "extra_time_exiting": SupportCategory.MOBILITY_SUPPORT,
    "child_supervision": SupportCategory.CHILD_SUPPORT,
    "visual_assistance": SupportCategory.VISUAL_IMPAIRMENT,
    "pregnancy_support": SupportCategory.PREGNANCY_SUPPORT,
    "elderly_support": SupportCategory.ELDERLY_SUPPORT,
}

# Fake tick: which declared UI options the simulated app submits this cycle.
_FAKE_DECLARED_CONSENT_UI_OPTIONS: tuple[str, ...] = ("avoid_sudden_braking",)

# Opaque passenger free-text, if ever present from transport: not used in logic.
_FAKE_PASSENGER_NOTE_OPAQUE: str | None = None


def _normalize_ui_token(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def consent_context_from_declared_ui_options(options: Iterable[str]) -> ConsentContext:
    """
    Build ``ConsentContext`` from app-supplied consent option keys only.

    Rejects unknown options (logs warning). Does not guess or infer intent.
    """
    accepted: set[SupportCategory] = set()
    for raw in options:
        key = _normalize_ui_token(raw)
        if not key:
            continue
        cat = CONSENT_UI_OPTION_TO_SUPPORT.get(key)
        if cat is None:
            logger.warning(
                "Rejected unknown or unsupported consent UI option (no inference): %r",
                raw,
            )
            continue
        accepted.add(cat)
    return ConsentContext(active_support_categories=frozenset(accepted))


def _room_consent_payload() -> tuple[list[str], bool | None]:
    obj = read_json_object(room_test_consent_json_path())
    if obj is None:
        return (["visual_assistance"], False)
    opts = obj.get("declared_ui_options")
    options: list[str] = []
    if isinstance(opts, list):
        options = [str(x) for x in opts if str(x).strip()]
    elif isinstance(opts, str) and opts.strip():
        options = [opts.strip()]
    if not options:
        options = ["visual_assistance"]
    enh_raw = obj.get("consent_enhanced_supervision")
    enh: bool | None
    if isinstance(enh_raw, bool):
        enh = enh_raw
    elif enh_raw is None:
        enh = None
    else:
        enh = str(enh_raw).strip().lower() in ("1", "true", "yes", "on")
    return (options, enh)


def _room_passenger_payload() -> PassengerEventContext:
    obj = read_json_object(room_test_passenger_json_path())
    if obj is None:
        return PassengerEventContext(stop_request=False, source="app", consented=True)
    src = obj.get("source", "app")
    return PassengerEventContext(
        stop_request=bool(obj.get("stop_request", False)),
        source=str(src) if src is not None else "app",
        consented=bool(obj.get("consented", True)),
    )


def read_consent_context() -> ConsentContext:
    """Fake adapter or room-test JSON (declared UI options only)."""
    if room_test_enabled():
        options, _ = _room_consent_payload()
        return consent_context_from_declared_ui_options(options)
    return consent_context_from_declared_ui_options(_FAKE_DECLARED_CONSENT_UI_OPTIONS)


def read_passenger_events() -> PassengerEventContext:
    """Fake adapter or room-test JSON for passenger-initiated events."""
    if room_test_enabled():
        return _room_passenger_payload()
    return PassengerEventContext(
        stop_request=True,
        source="app",
        consented=True,
    )


def read_consent_enhanced_supervision() -> bool:
    """
    Explicit TravelMate app toggle for stricter threshold policy (declared only).

    Fake adapter: deterministic flag; room test: optional field in consent JSON.
    """
    if room_test_enabled():
        _, enh = _room_consent_payload()
        if enh is not None:
            return bool(enh)
    return False
