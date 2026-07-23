# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Maps camera observations (+ Zone 1 semantics) onto anonymous PassengerEntity slots.

Identity-free: synthesizes coarse mobility / posture / intent from cues and timing.
Alerts must consume PassengerEntity aggregates, not raw frames (see safety candidate layer).

Current limitation: exactly one foreground-focused slot fed by Zone 1 observations.
Reserve keys exist for multi-passenger expansion without changing callers.
"""

from __future__ import annotations

from cabin_topology import CabinZoneId
from observed_cues import ObservedCues
from passenger_entity import (
    PassengerEntity,
    PassengerIntent,
    PassengerMobilityType,
    PassengerPostureState,
    PassengerVulnerabilityStatus,
)

PRIMARY_ZONE1_FOCUS_SLOT_ID = "p_slot_zone1_primary_focus"
PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID = "p_tracked_primary_cross_zone"
MULTI_PASSENGER_RESERVE_IDS: tuple[str, ...] = (
    "p_reserve_slot_b",
    "p_reserve_slot_c",
)


_MOBILITY_RANK: dict[PassengerMobilityType, int] = {
    PassengerMobilityType.NONE: 0,
    PassengerMobilityType.CANE: 1,
    PassengerMobilityType.WALKER: 2,
    PassengerMobilityType.WHEELCHAIR: 3,
}

_VULN_RANK: dict[PassengerVulnerabilityStatus, int] = {
    PassengerVulnerabilityStatus.UNKNOWN: 0,
    PassengerVulnerabilityStatus.NOT_VULNERABLE: 1,
    PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED: 2,
}


def _mobility_from_cues(c: ObservedCues) -> PassengerMobilityType:
    if c.large_mobility_device_present >= 0.34:
        return PassengerMobilityType.WHEELCHAIR
    if c.small_wheeled_carriage_present >= 0.34:
        return PassengerMobilityType.WALKER
    if c.navigation_aid_in_use >= 0.12:
        return PassengerMobilityType.CANE
    return PassengerMobilityType.NONE


def _posture_from_cues(c: ObservedCues) -> PassengerPostureState:
    if c.floor_level_posture >= 0.42:
        return PassengerPostureState.FLOOR_LEVEL
    if c.prolonged_standing >= 0.35 or c.unstable_posture >= 0.22:
        return PassengerPostureState.STANDING
    if (
        c.rapid_erratic_motion < 0.08
        and c.floor_level_posture < 0.12
        and c.prolonged_standing > 0.12
    ):
        return PassengerPostureState.SEATED
    return PassengerPostureState.UNKNOWN


def _vulnerability_placeholder(c: ObservedCues, mobility: PassengerMobilityType) -> PassengerVulnerabilityStatus:
    mob_vuln = mobility in (
        PassengerMobilityType.WHEELCHAIR,
        PassengerMobilityType.WALKER,
        PassengerMobilityType.CANE,
    )
    postural = (
        c.floor_level_posture >= 0.22
        or c.unstable_posture >= 0.24
        or c.frequent_balance_correction >= 0.55
    )
    if mob_vuln or postural:
        return PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED
    return PassengerVulnerabilityStatus.NOT_VULNERABLE


def _merge_mobility(a: PassengerMobilityType, b: PassengerMobilityType) -> PassengerMobilityType:
    return a if _MOBILITY_RANK[a] >= _MOBILITY_RANK[b] else b


def _merge_vulnerability(
    a: PassengerVulnerabilityStatus, b: PassengerVulnerabilityStatus
) -> PassengerVulnerabilityStatus:
    return a if _VULN_RANK[a] >= _VULN_RANK[b] else b


def passenger_entity_from_zone1_observation(
    *,
    cues: ObservedCues,
    at_mono: float,
    passenger_id: str | None = None,
) -> PassengerEntity:
    """
    Zone 1 (front entry/exit camera) projection.

    Exit intent precedence: dominant near-door cues trigger ``EXITING`` for door/ramp
    awareness without inferring identity (motion + doorway engagement).
    """
    c = cues.clamped()
    mobility = _mobility_from_cues(c)
    posture = _posture_from_cues(c)
    vuln = _vulnerability_placeholder(c, mobility)

    intent = PassengerIntent.IDLE
    if c.near_door_area >= 0.42:
        egress_motion = (
            c.rapid_erratic_motion >= 0.08
            or c.repetitive_agitated_motion >= 0.08
            or posture is PassengerPostureState.STANDING
            or vuln is PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED
        )
        if egress_motion or c.unstable_posture >= 0.12:
            intent = PassengerIntent.EXITING
    if intent is PassengerIntent.IDLE:
        if c.rapid_erratic_motion >= 0.22 or c.repetitive_agitated_motion >= 0.22:
            intent = PassengerIntent.MOVING

    rationale = ("zone_1_near_door_exit_bias" if intent is PassengerIntent.EXITING else "zone_1_projection",)

    slot = passenger_id if passenger_id else PRIMARY_ZONE1_FOCUS_SLOT_ID
    return PassengerEntity(
        passenger_id=slot,
        current_zone=CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
        vulnerability_status=vuln,
        mobility_type=mobility,
        posture_state=posture,
        intent=intent,
        last_seen_timestamp=at_mono,
        provenance_notes=rationale,
    )


def passenger_entity_from_zone2_observation(
    *,
    cues: ObservedCues,
    at_mono: float,
    passenger_id: str | None = None,
) -> PassengerEntity:
    """
    Mid-cabin logical zone — no exit-door intent from near_door thirds (those are intra-frame cues only).

    Instability-style posture cues still inform vulnerability for validation scenarios without Zone 1.
    """
    c = cues.clamped()
    mobility = _mobility_from_cues(c)
    posture = _posture_from_cues(c)
    vuln = _vulnerability_placeholder(c, mobility)

    intent = PassengerIntent.IDLE
    if c.rapid_erratic_motion >= 0.22 or c.repetitive_agitated_motion >= 0.22:
        intent = PassengerIntent.MOVING

    rationale = ("zone_2_mid_projection_no_exit_intent_from_door_fractions",)
    slot = passenger_id if passenger_id else PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID
    return PassengerEntity(
        passenger_id=slot,
        current_zone=CabinZoneId.ZONE_2_MID_CABIN,
        vulnerability_status=vuln,
        mobility_type=mobility,
        posture_state=posture,
        intent=intent,
        last_seen_timestamp=at_mono,
        provenance_notes=rationale,
    )


def merge_passenger_entities_zone2_to_zone1_transition(
    *,
    previous_zone2: PassengerEntity,
    zone1_projection: PassengerEntity,
    risk_mark: str = "continuity:z2_to_z1",
) -> PassengerEntity:
    """Same anonymous slot crosses mid → front cameras; escalation fields preserved conservatively."""
    z1 = zone1_projection
    return PassengerEntity(
        passenger_id=previous_zone2.passenger_id,
        current_zone=CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
        vulnerability_status=_merge_vulnerability(previous_zone2.vulnerability_status, z1.vulnerability_status),
        mobility_type=_merge_mobility(previous_zone2.mobility_type, z1.mobility_type),
        posture_state=z1.posture_state,
        intent=z1.intent,
        last_seen_timestamp=z1.last_seen_timestamp,
        provenance_notes=previous_zone2.provenance_notes + z1.provenance_notes + (risk_mark,),
        risk_history=previous_zone2.risk_history + (risk_mark,),
    )


def merge_passenger_entities_dual_visible_zone1_priority(
    *,
    zone1_entity: PassengerEntity,
    zone2_entity: PassengerEntity,
    at_mono: float,
) -> PassengerEntity:
    """Both sensors see a subject; exit semantics follow Zone 1; assistance context is maxed."""
    z1 = zone1_entity
    z2 = zone2_entity
    mark = "dual_visible:zone1_priority"
    return PassengerEntity(
        passenger_id=PRIMARY_TRACKED_CROSS_ZONE_SLOT_ID,
        current_zone=CabinZoneId.ZONE_1_FRONT_ENTRY_EXIT,
        vulnerability_status=_merge_vulnerability(z1.vulnerability_status, z2.vulnerability_status),
        mobility_type=_merge_mobility(z1.mobility_type, z2.mobility_type),
        posture_state=z1.posture_state,
        intent=z1.intent,
        last_seen_timestamp=at_mono,
        provenance_notes=z1.provenance_notes + z2.provenance_notes + (mark,),
        risk_history=z1.risk_history + z2.risk_history + (mark,),
    )


def passenger_entity_to_jsonable(pe: PassengerEntity) -> dict:
    return {
        "passenger_id": pe.passenger_id,
        "current_zone": int(pe.current_zone),
        "vulnerability_status": pe.vulnerability_status.value,
        "mobility_type": pe.mobility_type.value,
        "posture_state": pe.posture_state.value,
        "intent": pe.intent.value,
        "last_seen_timestamp": pe.last_seen_timestamp,
        "provenance_notes": list(pe.provenance_notes),
        "risk_history": list(pe.risk_history),
    }
