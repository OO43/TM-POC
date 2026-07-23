# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — observable cabin cues (domain model, PoC).

These fields simulate what a **perception adapter** could output (e.g. from vision or
crew input). They describe **situations and zones**, not named individuals.

Cues do **not** imply disability, pregnancy, age, medical condition, or diagnosis.
Vulnerable-accommodation needs are applied only via consent-declared SupportCategory
elsewhere — never inferred from cues alone.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservedCues:
    """Normalized confidences in [0, 1] unless noted; higher = stronger cue."""

    # After ``navigation_aid_behavioral_gate``: effective behavioral cane score only.
    navigation_aid_in_use: float = 0.0
    # Raw elongated-object / stick-like classifier (may fire on umbrella, broom, carried pole).
    navigation_aid_candidate: float = 0.0
    # Behavioral evidence (all required together + seconds of persistence in the gate):
    # thin-object floor contact; gait/step coupling; vertical load-bearing; one-sided use.
    nav_aid_floor_contact: float = 0.0
    nav_aid_gait_coupling: float = 0.0
    nav_aid_vertical_load: float = 0.0
    nav_aid_unilateral_bias: float = 0.0
    large_mobility_device_present: float = 0.0
    small_wheeled_carriage_present: float = 0.0
    prolonged_standing: float = 0.0
    unstable_posture: float = 0.0
    frequent_balance_correction: float = 0.0
    leaning_without_support: float = 0.0
    floor_level_posture: float = 0.0
    rapid_erratic_motion: float = 0.0
    repetitive_agitated_motion: float = 0.0
    distress_motion_pattern: float = 0.0
    aggressive_motion_pattern: float = 0.0
    near_door_area: float = 0.0
    near_priority_space: float = 0.0
    near_stairs_or_upper_deck: float = 0.0

    def clamped(self) -> ObservedCues:
        def _c(x: float) -> float:
            return max(0.0, min(1.0, x))

        return ObservedCues(
            navigation_aid_in_use=_c(self.navigation_aid_in_use),
            navigation_aid_candidate=_c(self.navigation_aid_candidate),
            nav_aid_floor_contact=_c(self.nav_aid_floor_contact),
            nav_aid_gait_coupling=_c(self.nav_aid_gait_coupling),
            nav_aid_vertical_load=_c(self.nav_aid_vertical_load),
            nav_aid_unilateral_bias=_c(self.nav_aid_unilateral_bias),
            large_mobility_device_present=_c(self.large_mobility_device_present),
            small_wheeled_carriage_present=_c(self.small_wheeled_carriage_present),
            prolonged_standing=_c(self.prolonged_standing),
            unstable_posture=_c(self.unstable_posture),
            frequent_balance_correction=_c(self.frequent_balance_correction),
            leaning_without_support=_c(self.leaning_without_support),
            floor_level_posture=_c(self.floor_level_posture),
            rapid_erratic_motion=_c(self.rapid_erratic_motion),
            repetitive_agitated_motion=_c(self.repetitive_agitated_motion),
            distress_motion_pattern=_c(self.distress_motion_pattern),
            aggressive_motion_pattern=_c(self.aggressive_motion_pattern),
            near_door_area=_c(self.near_door_area),
            near_priority_space=_c(self.near_priority_space),
            near_stairs_or_upper_deck=_c(self.near_stairs_or_upper_deck),
        )


def merge_zone_cues(*snapshots: ObservedCues) -> ObservedCues:
    """Fuse zone snapshots with element-wise max; no identity linkage."""
    if not snapshots:
        return ObservedCues()
    acc = snapshots[0].clamped()
    for s in snapshots[1:]:
        s = s.clamped()
        acc = ObservedCues(
            navigation_aid_in_use=max(acc.navigation_aid_in_use, s.navigation_aid_in_use),
            navigation_aid_candidate=max(acc.navigation_aid_candidate, s.navigation_aid_candidate),
            nav_aid_floor_contact=max(acc.nav_aid_floor_contact, s.nav_aid_floor_contact),
            nav_aid_gait_coupling=max(acc.nav_aid_gait_coupling, s.nav_aid_gait_coupling),
            nav_aid_vertical_load=max(acc.nav_aid_vertical_load, s.nav_aid_vertical_load),
            nav_aid_unilateral_bias=max(acc.nav_aid_unilateral_bias, s.nav_aid_unilateral_bias),
            large_mobility_device_present=max(
                acc.large_mobility_device_present, s.large_mobility_device_present
            ),
            small_wheeled_carriage_present=max(
                acc.small_wheeled_carriage_present, s.small_wheeled_carriage_present
            ),
            prolonged_standing=max(acc.prolonged_standing, s.prolonged_standing),
            unstable_posture=max(acc.unstable_posture, s.unstable_posture),
            frequent_balance_correction=max(
                acc.frequent_balance_correction, s.frequent_balance_correction
            ),
            leaning_without_support=max(acc.leaning_without_support, s.leaning_without_support),
            floor_level_posture=max(acc.floor_level_posture, s.floor_level_posture),
            rapid_erratic_motion=max(acc.rapid_erratic_motion, s.rapid_erratic_motion),
            repetitive_agitated_motion=max(
                acc.repetitive_agitated_motion, s.repetitive_agitated_motion
            ),
            distress_motion_pattern=max(acc.distress_motion_pattern, s.distress_motion_pattern),
            aggressive_motion_pattern=max(
                acc.aggressive_motion_pattern, s.aggressive_motion_pattern
            ),
            near_door_area=max(acc.near_door_area, s.near_door_area),
            near_priority_space=max(acc.near_priority_space, s.near_priority_space),
            near_stairs_or_upper_deck=max(
                acc.near_stairs_or_upper_deck, s.near_stairs_or_upper_deck
            ),
        )
    return acc


def derive_behaviour_level_from_cues(o: ObservedCues) -> float:
    """Single aggregate [0,1] behaviour cue for compounded risk (not a person score)."""
    c = o.clamped()
    motion_like = max(
        c.unstable_posture,
        c.rapid_erratic_motion,
        c.repetitive_agitated_motion,
        c.distress_motion_pattern,
        c.aggressive_motion_pattern,
        c.frequent_balance_correction,
        c.leaning_without_support,
        c.floor_level_posture,
    )
    # Large devices / carriages contribute to activity load in the space (not identity).
    device_load = max(
        0.55 * c.large_mobility_device_present,
        0.45 * c.small_wheeled_carriage_present,
    )
    return max(motion_like, device_load)


def derive_behaviour_level_for_risk(
    o: ObservedCues,
    *,
    vulnerability_confirmed: bool,
    instability_escalation_active: bool,
    vulnerability_source: str = "none",
) -> float:
    """
    For compounded risk gates: unstable / balance / lean are evaluated vs a **vulnerability
    baseline**, not generic passengers. ``vulnerability_source`` selects baseline width
    (mobility-aid users: leaning and correction are normal until escalation).

    ``vulnerability_source`` uses ``VulnerabilitySource`` string values (``none``,
    ``mobility_aid``, ``mobility_device``, ``persistent_posture``).

    Non-vulnerable passengers: routine standing / lean / balance must not inflate behaviour
    for risk scoring unless cues rise into a clearly unstable band.
    Distress / erratic / floor / device cues are unchanged.
    """
    c = o.clamped()
    if not vulnerability_confirmed:
        kinematic = max(
            c.rapid_erratic_motion,
            c.repetitive_agitated_motion,
            c.distress_motion_pattern,
            c.aggressive_motion_pattern,
        )
        routine_posture = max(
            c.unstable_posture,
            c.frequent_balance_correction,
            c.leaning_without_support,
            c.prolonged_standing,
        )
        posture_component = max(0.0, routine_posture - 0.42)
        device_load = max(
            0.55 * c.large_mobility_device_present,
            0.45 * c.small_wheeled_carriage_present,
        )
        return max(kinematic, c.floor_level_posture, device_load, posture_component)

    if instability_escalation_active:
        return derive_behaviour_level_from_cues(o)

    if vulnerability_source == "mobility_aid":
        # Cane / crutch / walker: leaning and balance correction are baseline; instability
        # scoring uses excess beyond typical aid use (handled via escalation + scenario).
        adj_u = max(0.0, c.unstable_posture - 0.32)
        adj_f = max(0.0, c.frequent_balance_correction - 0.38)
        adj_l = max(0.0, c.leaning_without_support - 0.32)
    else:
        adj_u = max(0.0, c.unstable_posture - 0.18)
        adj_f = max(0.0, c.frequent_balance_correction - 0.22)
        adj_l = max(0.0, c.leaning_without_support - 0.18)
    motion_like = max(
        adj_u,
        adj_f,
        adj_l,
        c.rapid_erratic_motion,
        c.repetitive_agitated_motion,
        c.distress_motion_pattern,
        c.aggressive_motion_pattern,
        c.floor_level_posture,
    )
    device_load = max(
        0.55 * c.large_mobility_device_present,
        0.45 * c.small_wheeled_carriage_present,
    )
    return max(motion_like, device_load)
