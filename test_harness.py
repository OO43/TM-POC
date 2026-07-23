# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — test scenario builder (PoC only).

Builds dicts consumable by main.py as SIMULATED_TICKS entries.
"""

from __future__ import annotations

from dataclasses import asdict

from ble_proximity import BLEProximityContext, VehicleZone
from can_context import CANContext
from consent_context import ConsentContext
from density_context import DensityContext
from journey_phase import JourneyPhase
from observed_cues import ObservedCues, derive_behaviour_level_from_cues
from thresholds import SupportCategory


def build_test_scenario(
    *,
    observed_cues: ObservedCues,
    can_context: CANContext,
    density_context: DensityContext,
    consent_context: ConsentContext,
    journey_phase: JourneyPhase,
    ble: BLEProximityContext | None = None,
    emergency: dict | None = None,
    system_faults: dict[str, bool] | None = None,
    consent_enhanced_supervision: bool = False,
    driver_acknowledge_emergency: bool = False,
    driver_event: dict | None = None,
    passenger_event: dict | None = None,
) -> dict:
    """Single tick payload: adapter-like inputs only (no hardware)."""
    d = asdict(density_context)
    out = {
        "behaviour": derive_behaviour_level_from_cues(observed_cues),
        "density": density_context.passengers_onboard / float(density_context.vehicle_capacity),
        "density_context": d,
        "observed_cues": {k: float(v) for k, v in asdict(observed_cues).items()},
        "can": {
            "speed": can_context.speed,
            "braking_intensity": can_context.braking_intensity,
            "turn_intensity": can_context.turn_intensity,
            "doors_open": can_context.doors_open,
            "ramp_deployed": can_context.ramp_deployed,
            "vehicle_stationary": can_context.vehicle_stationary,
        },
        "consent_enhanced_supervision": consent_enhanced_supervision,
        "support_categories": [c.value for c in consent_context.active_support_categories],
        "journey_phase": journey_phase.value,
        "emergency": emergency or {},
        "system_faults": system_faults or {},
        "driver_acknowledge_emergency": driver_acknowledge_emergency,
    }
    if ble is not None:
        out["ble"] = {"enabled": ble.enabled, "zone": ble.zone.value, "confidence": ble.confidence}
    if driver_event is not None:
        out["driver_event"] = driver_event
    if passenger_event is not None:
        out["passenger_event"] = passenger_event
    return out


def behavioral_cane_observed_cues(
    raw_stick: float = 0.55, behavioral: float = 0.82
) -> ObservedCues:
    """Full behavioral cane dimensions + stick candidate for synthetic harness ticks."""
    return ObservedCues(
        navigation_aid_candidate=raw_stick,
        navigation_aid_in_use=raw_stick,
        nav_aid_floor_contact=behavioral,
        nav_aid_gait_coupling=behavioral,
        nav_aid_vertical_load=behavioral,
        nav_aid_unilateral_bias=behavioral,
    )


def example_test_matrix() -> list[dict]:
    """Scenarios for manual validation (wire into SIMULATED_TICKS in main)."""
    return [
        build_test_scenario(
            observed_cues=ObservedCues(unstable_posture=0.55, rapid_erratic_motion=0.2),
            can_context=CANContext(0.3, 0.2, 0.1, False, False),
            density_context=DensityContext(25, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(
                rapid_erratic_motion=0.65,
                large_mobility_device_present=0.2,
            ),
            can_context=CANContext(0.75, 0.5, 0.4, False, False),
            density_context=DensityContext(20, 50),
            consent_context=ConsentContext(frozenset({SupportCategory.CHILD_SUPPORT})),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(
                unstable_posture=0.4,
                leaning_without_support=0.45,
                prolonged_standing=0.5,
            ),
            can_context=CANContext(0.4, 0.75, 0.2, False, False),
            density_context=DensityContext(30, 50),
            consent_context=ConsentContext(frozenset({SupportCategory.PREGNANCY_SUPPORT})),
            journey_phase=JourneyPhase.APPROACHING_STOP,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(
                frequent_balance_correction=0.5,
                unstable_posture=0.45,
            ),
            can_context=CANContext(0.5, 0.3, 0.85, False, False),
            density_context=DensityContext(28, 50),
            consent_context=ConsentContext(frozenset({SupportCategory.MEDICAL_SENSITIVITY})),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(
                large_mobility_device_present=0.7,
                near_priority_space=0.25,
                near_stairs_or_upper_deck=0.6,
            ),
            can_context=CANContext(0.6, 0.4, 0.3, False, False),
            density_context=DensityContext(35, 50),
            consent_context=ConsentContext(frozenset({SupportCategory.WHEELCHAIR})),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(
                small_wheeled_carriage_present=0.65,
                unstable_posture=0.5,
                near_stairs_or_upper_deck=0.55,
            ),
            can_context=CANContext(0.55, 0.45, 0.35, False, False),
            density_context=DensityContext(40, 50),
            consent_context=ConsentContext(frozenset({SupportCategory.PUSHCHAIR})),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(
                near_door_area=0.65,
                prolonged_standing=0.55,
                distress_motion_pattern=0.35,
            ),
            can_context=CANContext(0.35, 0.2, 0.15, False, False),
            density_context=DensityContext(48, 50),
            consent_context=ConsentContext(frozenset({SupportCategory.ELDERLY_SUPPORT})),
            journey_phase=JourneyPhase.APPROACHING_STOP,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(
                distress_motion_pattern=0.4,
                aggressive_motion_pattern=0.35,
            ),
            can_context=CANContext(0.45, 0.3, 0.25, False, False),
            density_context=DensityContext(47, 50),
            consent_context=ConsentContext(
                frozenset({SupportCategory.MEDICAL_SENSITIVITY, SupportCategory.MOBILITY_SUPPORT})
            ),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.2, 0.1, 0.1, False, False),
            density_context=DensityContext(55, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.3, 0.2, 0.1, False, False),
            density_context=DensityContext(10, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
            emergency={"passenger_collapse_or_fall": True},
        ),
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.2, 0.1, 0.1, False, False),
            density_context=DensityContext(10, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
            driver_acknowledge_emergency=True,
        ),
        *[
            build_test_scenario(
                observed_cues=behavioral_cane_observed_cues(),
                can_context=CANContext(0.35, 0.25, 0.1, False, False),
                density_context=DensityContext(22, 50),
                consent_context=ConsentContext(frozenset({SupportCategory.VISUAL_IMPAIRMENT})),
                journey_phase=JourneyPhase.APPROACHING_STOP,
                ble=BLEProximityContext(True, VehicleZone.WHEELCHAIR_BAY, 0.75),
            )
            for _ in range(6)
        ],
        build_test_scenario(
            observed_cues=behavioral_cane_observed_cues(0.55),
            can_context=CANContext(0.35, 0.25, 0.1, False, False),
            density_context=DensityContext(22, 50),
            consent_context=ConsentContext(frozenset({SupportCategory.VISUAL_IMPAIRMENT})),
            journey_phase=JourneyPhase.APPROACHING_STOP,
            ble=BLEProximityContext(True, VehicleZone.WHEELCHAIR_BAY, 0.75),
        ),
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.2, 0.1, 0.1, False, False),
            density_context=DensityContext(10, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
            system_faults={"display_fault": True},
        ),
        # Policy: diversion requested while moving — must be blocked (tablet would hide/disable).
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.55, 0.15, 0.1, False, False, False),
            density_context=DensityContext(12, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
            driver_event={"diversion_active": True, "diversion_reason": "detour"},
        ),
        # Policy: diversion allowed when stationary — alert + simulated passenger notify.
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.0, 0.0, 0.0, False, False, True),
            density_context=DensityContext(8, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.APPROACHING_STOP,
            driver_event={"diversion_active": True},
        ),
        # Policy: strict over-capacity — alert even at compounded risk ~0 (low motion/behaviour).
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.0, 0.0, 0.0, False, False, True),
            density_context=DensityContext(52, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
        ),
        # Policy: consented passenger stop request — high priority, bypass risk gating.
        build_test_scenario(
            observed_cues=ObservedCues(),
            can_context=CANContext(0.25, 0.1, 0.05, False, False, False),
            density_context=DensityContext(15, 50),
            consent_context=ConsentContext(frozenset()),
            journey_phase=JourneyPhase.IN_MOTION,
            passenger_event={"stop_request": True, "source": "app", "consented": True},
        ),
    ]
