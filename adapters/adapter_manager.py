# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — adapter orchestration (PoC).

Aggregates one tick worth of inputs from all adapters into the same ``dict``
shape used by ``interactive_cli`` and the batch harness. No decision logic:
only assembly and serialization of domain objects.

Fields without dedicated hardware adapters yet (journey phase, emergency flags,
system faults) use explicit fixed placeholders here until split out.
"""

from __future__ import annotations

from dataclasses import asdict, fields as dc_fields

from journey_phase import JourneyPhase
from thresholds import SupportCategory, get_room_test_timing

from demo_flags import travelmate_demo_enabled

from adapters.ble_adapter import read_ble_proximity
from adapters.camera_adapter import pop_dual_observation_snapshots, read_cabin_perception
from adapters.can_adapter import read_can_context
from adapters.room_test_env import (
    phase1_validation_enabled,
    room_test_can_json_path,
    room_test_density_state_path,
    room_test_enabled,
)
from adapters.density_adapter import read_density_context
from adapters.driver_tablet_adapter import read_driver_events
from adapters.passenger_app_adapter import (
    read_consent_context,
    read_consent_enhanced_supervision,
    read_passenger_events,
)
from observed_cues import ObservedCues
from passenger_tick_bridge import attach_cabin_architecture_to_tick
from room_test_context_override import can_bus_connected_effective
from room_test_sim_limits import normalized_speed_to_kmh


def _camera_zone_primary(zones: dict[str, float]) -> str | None:
    z = {k: float(zones.get(k, 0.0)) for k in ("door", "mid", "rear")}
    m = max(z.values()) if z else 0.0
    if m < 1e-9:
        return None
    for k in ("door", "mid", "rear"):
        if z[k] + 1e-12 >= m:
            return k
    return None


def collect_tick_inputs() -> dict:
    """
    Call all fake adapters and return one tick dict for ``evaluate_driver_tick``.

    Structure matches ``interactive_cli`` manual tick assembly.
    """
    can_ctx = read_can_context()
    cues, camera_zones, camera_perception_status = read_cabin_perception()
    dual_rows = pop_dual_observation_snapshots()
    density_ctx = read_density_context()
    consent_ctx = read_consent_context()
    passenger_event = read_passenger_events()
    driver_event = read_driver_events()
    ble_ctx = read_ble_proximity()

    can_map = {
        "speed": can_ctx.speed,
        "braking_intensity": can_ctx.braking_intensity,
        "turn_intensity": can_ctx.turn_intensity,
        "doors_open": can_ctx.doors_open,
        "ramp_deployed": can_ctx.ramp_deployed,
        "vehicle_stationary": can_ctx.vehicle_stationary,
        "speed_kmh": round(float(normalized_speed_to_kmh(can_ctx.speed)), 1),
    }

    active = consent_ctx.active_support_categories
    if active:
        support_list = [c.value for c in sorted(active, key=lambda x: x.value)]
    else:
        support_list = [SupportCategory.UNDECLARED.value]

    cz = {k: float(camera_zones.get(k, 0.0)) for k in ("door", "mid", "rear")}
    tick: dict = {
        "observed_cues": {k: float(v) for k, v in asdict(cues).items()},
        "camera_perception_status": camera_perception_status,
        "camera_zones": cz,
        "camera_zone_primary": _camera_zone_primary(cz),
        "can": can_map,
        "density_context": {
            "passengers_onboard": density_ctx.passengers_onboard,
            "vehicle_capacity": density_ctx.vehicle_capacity,
        },
        "density": density_ctx.passengers_onboard / float(density_ctx.vehicle_capacity),
        "behaviour": 0.0,
        "consent_enhanced_supervision": read_consent_enhanced_supervision(),
        "support_categories": support_list,
        "journey_phase": JourneyPhase.IN_MOTION.value,
        "passenger_event": {
            "stop_request": passenger_event.stop_request,
            "source": passenger_event.source,
            "consented": passenger_event.consented,
        },
        "driver_event": {"diversion_active": driver_event.diversion_active},
        "emergency": {
            "passenger_collapse_or_fall": False,
            "medical_collapse_slow_descent": False,
            "fire_or_smoke": False,
            "altercation": False,
            "severe_distress": False,
        },
        "driver_acknowledge_emergency": False,
        "driver_ack_passenger_remaining_onboard": False,
    }

    if ble_ctx is not None:
        tick["ble"] = {
            "enabled": ble_ctx.enabled,
            "zone": ble_ctx.zone.value,
            "confidence": ble_ctx.confidence,
        }

    if room_test_enabled():
        tick["room_test"] = True
        tick["room_test_can_bus_connected"] = can_bus_connected_effective()
        rt = get_room_test_timing()
        tick["room_test_timing"] = {
            "boarding_dwell_secs": rt.boarding_dwell_secs,
            "exit_dwell_secs": rt.exit_dwell_secs,
            "standing_dwell_secs": rt.standing_dwell_secs,
        }
        d_path = room_test_density_state_path()
        c_path = room_test_can_json_path()
        tick["room_test_input_sources"] = {
            "density": {
                "control": "manual",
                "source_label": "room_density_state_json",
                "path": str(d_path),
                "file_present": d_path.is_file(),
                "authoritative_per_tick": True,
                "backend_auto_mutates": False,
                "demo_timeline_may_modify": False,
            },
            "can": {
                "control": "manual",
                "source_label": "room_can_state_json",
                "path": str(c_path),
                "file_present": c_path.is_file(),
                "authoritative_per_tick": True,
                "backend_auto_mutates": False,
                "demo_timeline_may_modify": False,
            },
            "values_not_auto_generated": True,
        }

    if travelmate_demo_enabled() and not room_test_enabled():
        import time as _time

        from demo_simulator import merge_demo_timeline_inputs

        merge_demo_timeline_inputs(tick, _time.monotonic())

    if room_test_enabled() and phase1_validation_enabled():
        from room_test_phase1_validation import apply_phase1_observed_cue_mask

        apply_phase1_observed_cue_mask(tick)

    oc_raw = tick["observed_cues"]
    cues_for_arch = ObservedCues(
        **{f.name: float(oc_raw.get(f.name, 0.0)) for f in dc_fields(ObservedCues)}
    )
    attach_cabin_architecture_to_tick(
        tick,
        cues=cues_for_arch,
        camera_perception_status=str(tick.get("camera_perception_status") or ""),
        dual_observation_rows=dual_rows,
    )

    return tick
