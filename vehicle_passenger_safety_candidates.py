# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Structured safety *candidates* from PassengerEntity aggregates + vehicle context.

This layer encodes Phase‑3 contextual rules explicitly. Outputs are informational
vehicles-level recommendations with priority hints for aggregation into driver alerts.

Fusion into ``tick[\"emergency\"``] / ``evaluate_driver_tick`` stays explicit and
incremental — candidates are serialized on the tick for downstream consumers tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from passenger_entity import (
    PassengerEntity,
    PassengerIntent,
    PassengerMobilityType,
    PassengerPostureState,
    PassengerVulnerabilityStatus,
)


class SafetyCandidateSeverity(str, Enum):
    ROUTINE_ADJUSTMENT = "routine_adjustment"
    HIGH_ATTENTION = "high_attention"
    EMERGENCY = "emergency"


@dataclass(frozen=True)
class VehicleOperationContext:
    speed: float
    vehicle_stationary: bool
    doors_open: bool
    ramp_deployed: bool


@dataclass(frozen=True)
class PassengerSafetyCandidate:
    """Vehicle-level prioritized candidate derived from passenger + vehicle pairing."""

    kind: str
    severity: SafetyCandidateSeverity
    priority_rank: int
    rationale: str
    passenger_slots: tuple[str, ...]
    zones: tuple[int, ...]


def vehicle_context_from_can_map(can_map: dict[str, Any]) -> VehicleOperationContext:
    return VehicleOperationContext(
        speed=float(can_map.get("speed", 0.0)),
        vehicle_stationary=bool(can_map.get("vehicle_stationary", False)),
        doors_open=bool(can_map.get("doors_open", False)),
        ramp_deployed=bool(can_map.get("ramp_deployed", False)),
    )


def _moving_vehicle(vc: VehicleOperationContext) -> bool:
    return (not vc.vehicle_stationary) and vc.speed > 0.05


def derive_safety_candidates(
    entities_by_id: dict[str, PassengerEntity],
    vc: VehicleOperationContext,
) -> tuple[PassengerSafetyCandidate, ...]:
    """
    Multi-passenger ready: each entity evaluated independently; results sorted by priority_rank (asc).
    """
    out: list[PassengerSafetyCandidate] = []
    for pid, pe in entities_by_id.items():
        z = int(pe.current_zone)

        if (
            pe.posture_state is PassengerPostureState.FLOOR_LEVEL
            and pe.vulnerability_status == PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED
        ):
            out.append(
                PassengerSafetyCandidate(
                    kind="medical_or_collapse_like_posture",
                    severity=SafetyCandidateSeverity.EMERGENCY,
                    priority_rank=1,
                    rationale="floor_level_posture proxy with assist context — route to emergency arbitration",
                    passenger_slots=(pid,),
                    zones=(z,),
                )
            )

        if (
            pe.intent is PassengerIntent.EXITING
            and pe.vulnerability_status == PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED
        ):
            if _moving_vehicle(vc):
                out.append(
                    PassengerSafetyCandidate(
                        kind="vulnerable_exiting_while_vehicle_moving",
                        severity=SafetyCandidateSeverity.HIGH_ATTENTION,
                        priority_rank=5,
                        rationale="vulnerable passenger exiting zone while vehicle not settled",
                        passenger_slots=(pid,),
                        zones=(z,),
                    )
                )

        if pe.intent is PassengerIntent.EXITING and pe.mobility_type is PassengerMobilityType.WHEELCHAIR:
            if vc.doors_open and not vc.ramp_deployed:
                out.append(
                    PassengerSafetyCandidate(
                        kind="wheelchair_exit_ramp_required",
                        severity=SafetyCandidateSeverity.HIGH_ATTENTION,
                        priority_rank=4,
                        rationale="Wheelchair exit · deploy ramp (candidate only).",
                        passenger_slots=(pid,),
                        zones=(z,),
                    )
                )

        if pe.vulnerability_status is PassengerVulnerabilityStatus.ASSIST_CONTEXT_ELEVATED:
            if pe.posture_state in (
                PassengerPostureState.STANDING,
                PassengerPostureState.UNKNOWN,
            ) and _moving_vehicle(vc) and z in (2, 3):
                out.append(
                    PassengerSafetyCandidate(
                        kind="unstable_or_assist_mid_or_upper_zone_while_moving",
                        severity=SafetyCandidateSeverity.ROUTINE_ADJUSTMENT,
                        priority_rank=8,
                        rationale="assist-elevated passenger in mid/upper zone while vehicle moving — smooth driving",
                        passenger_slots=(pid,),
                        zones=(z,),
                    )
                )

    out.sort(key=lambda c: (c.priority_rank, c.kind))
    return tuple(out)


def safety_candidates_to_jsonable(cands: tuple[PassengerSafetyCandidate, ...]) -> list[dict[str, Any]]:
    return [
        {
            "kind": c.kind,
            "severity": c.severity.value,
            "priority_rank": c.priority_rank,
            "rationale": c.rationale,
            "passenger_slots": list(c.passenger_slots),
            "zones": list(c.zones),
        }
        for c in cands
    ]
