# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""Unit tests for explicit vulnerability, scenario gating, and alert priority (PoC)."""

from __future__ import annotations

import unittest

from journey_phase import JourneyPhase
from observed_cues import ObservedCues, derive_behaviour_level_for_risk
from policy_arbitration import pick_highest_priority_alert
from scenario_classification import select_operational_alert_unified
from thresholds import AlertType, SupportCategory
from navigation_aid_behavioral_gate import (
    apply_navigation_aid_behavioral_gate,
    reset_navigation_aid_behavioral_gate,
)
from vulnerability_inference import (
    VulnerabilityInferencer,
    VulnerabilitySource,
    explicit_vulnerability_category_strength,
    persistent_posture_vulnerability_strength,
    reset_vulnerability_inference,
)
from instability_escalation import (
    InstabilityEscalationSnapshot,
    reset_instability_escalation,
)


def setUpModule() -> None:
    reset_navigation_aid_behavioral_gate()
    reset_vulnerability_inference()
    reset_instability_escalation()


class TestExplicitVulnerabilityCategories(unittest.TestCase):
    def test_mild_posture_alone_not_explicit(self) -> None:
        o = ObservedCues(unstable_posture=0.2, leaning_without_support=0.15)
        self.assertLess(explicit_vulnerability_category_strength(o), 0.12)

    def test_navigation_aid_is_explicit(self) -> None:
        o = ObservedCues(navigation_aid_in_use=0.45)
        self.assertGreaterEqual(explicit_vulnerability_category_strength(o), 0.5)

    def test_wheelchair_device_is_explicit(self) -> None:
        o = ObservedCues(large_mobility_device_present=0.5)
        self.assertGreaterEqual(explicit_vulnerability_category_strength(o), 0.5)

    def test_posture_classification_disabled_when_mobility_aid_visible(self) -> None:
        o = ObservedCues(
            navigation_aid_in_use=0.40,
            unstable_posture=0.55,
            leaning_without_support=0.45,
        )
        self.assertEqual(persistent_posture_vulnerability_strength(o), 0.0)


class TestVulnerabilityPersistence(unittest.TestCase):
    def setUp(self) -> None:
        reset_vulnerability_inference()
        reset_instability_escalation()
        reset_navigation_aid_behavioral_gate()

    def test_confirms_only_after_sustained_explicit_signal(self) -> None:
        inf = VulnerabilityInferencer()
        o_strong = ObservedCues(navigation_aid_in_use=0.5)
        t = 0.0
        confirmed = False
        for _ in range(60):
            t += 0.06
            snap = inf.update(o_strong, now_mono=t)
            if snap.confirmed:
                confirmed = True
                break
        self.assertTrue(confirmed, "mobility aid should confirm after short persistence (~0.5s)")

    def test_mobility_aid_source_tag(self) -> None:
        inf = VulnerabilityInferencer()
        t = 0.0
        src = VulnerabilitySource.NONE
        for _ in range(20):
            t += 0.06
            s = inf.update(ObservedCues(navigation_aid_in_use=0.5), now_mono=t)
            if s.confirmed:
                src = s.source
                break
        self.assertEqual(src, VulnerabilitySource.MOBILITY_AID)

    def test_transient_spike_does_not_confirm(self) -> None:
        inf = VulnerabilityInferencer()
        t = 0.0
        for _ in range(3):
            t += 0.05
            inf.update(ObservedCues(navigation_aid_in_use=0.5), now_mono=t)
        for _ in range(40):
            t += 0.05
            inf.update(ObservedCues(), now_mono=t)
        self.assertFalse(inf.peek().confirmed)


class TestScenarioGating(unittest.TestCase):
    def test_non_vulnerable_no_instability_from_routine_posture(self) -> None:
        o = ObservedCues(
            prolonged_standing=0.5,
            unstable_posture=0.28,
            leaning_without_support=0.22,
        )
        sel = select_operational_alert_unified(
            o,
            JourneyPhase.IN_MOTION,
            {SupportCategory.UNDECLARED},
            density_level=0.5,
            motion_level=0.5,
            vulnerability_confirmed=False,
            instability_escalation=InstabilityEscalationSnapshot(False),
        )
        self.assertNotEqual(sel, AlertType.INSTABILITY_RISK)

    def test_non_vulnerable_no_standing_motion_risk(self) -> None:
        o = ObservedCues(prolonged_standing=0.5)
        sel = select_operational_alert_unified(
            o,
            JourneyPhase.IN_MOTION,
            {SupportCategory.UNDECLARED},
            density_level=0.4,
            motion_level=0.5,
            vulnerability_confirmed=False,
            instability_escalation=InstabilityEscalationSnapshot(False),
        )
        self.assertNotEqual(sel, AlertType.STANDING_MOTION_RISK)

    def test_vulnerable_motion_wobble_can_select_instability(self) -> None:
        o = ObservedCues(
            unstable_posture=0.42,
            distress_motion_pattern=0.22,
        )
        sel = select_operational_alert_unified(
            o,
            JourneyPhase.IN_MOTION,
            {SupportCategory.MOBILITY_SUPPORT},
            density_level=0.45,
            motion_level=0.45,
            vulnerability_confirmed=True,
            instability_escalation=InstabilityEscalationSnapshot(False),
        )
        self.assertEqual(sel, AlertType.INSTABILITY_RISK)


class TestBehaviourLevelNonVulnerable(unittest.TestCase):
    def test_mild_posture_suppressed_for_risk(self) -> None:
        o = ObservedCues(unstable_posture=0.35, leaning_without_support=0.3)
        b = derive_behaviour_level_for_risk(
            o,
            vulnerability_confirmed=False,
            instability_escalation_active=False,
        )
        self.assertLess(b, 0.15)


class TestMobilityAidBaselineRisk(unittest.TestCase):
    def test_mobility_aid_widens_baseline_vs_posture_only(self) -> None:
        o = ObservedCues(
            unstable_posture=0.26,
            leaning_without_support=0.36,
            frequent_balance_correction=0.31,
        )
        b_aid = derive_behaviour_level_for_risk(
            o,
            vulnerability_confirmed=True,
            instability_escalation_active=False,
            vulnerability_source="mobility_aid",
        )
        b_post = derive_behaviour_level_for_risk(
            o,
            vulnerability_confirmed=True,
            instability_escalation_active=False,
            vulnerability_source="persistent_posture",
        )
        self.assertLess(b_aid, b_post)


class TestMobilityAidInstabilityGating(unittest.TestCase):
    def test_mobility_aid_no_instability_from_mild_posture_alone(self) -> None:
        o = ObservedCues(
            unstable_posture=0.34,
            frequent_balance_correction=0.30,
            leaning_without_support=0.28,
        )
        sel = select_operational_alert_unified(
            o,
            JourneyPhase.IN_MOTION,
            {SupportCategory.UNDECLARED},
            density_level=0.45,
            motion_level=0.5,
            vulnerability_confirmed=True,
            vulnerability_source=VulnerabilitySource.MOBILITY_AID,
            instability_escalation=InstabilityEscalationSnapshot(False),
        )
        self.assertNotEqual(sel, AlertType.INSTABILITY_RISK)


class TestBehavioralNavigationAidGate(unittest.TestCase):
    def setUp(self) -> None:
        reset_navigation_aid_behavioral_gate()

    def test_carried_stick_alone_suppressed(self) -> None:
        o = apply_navigation_aid_behavioral_gate(
            ObservedCues(navigation_aid_candidate=0.95, navigation_aid_in_use=0.95)
        )
        assert o is not None
        self.assertLess(o.navigation_aid_in_use, 0.05)

    def test_behavioral_cane_passes_after_persistence(self) -> None:
        reset_navigation_aid_behavioral_gate()
        o: ObservedCues | None = ObservedCues()
        for _ in range(8):
            o = apply_navigation_aid_behavioral_gate(
                ObservedCues(
                    navigation_aid_candidate=0.6,
                    navigation_aid_in_use=0.6,
                    nav_aid_floor_contact=0.82,
                    nav_aid_gait_coupling=0.82,
                    nav_aid_vertical_load=0.82,
                    nav_aid_unilateral_bias=0.82,
                )
            )
        assert o is not None
        self.assertGreaterEqual(o.navigation_aid_in_use, 0.18)


class TestPriorityOrder(unittest.TestCase):
    def test_instability_outranks_standing_motion(self) -> None:
        w = pick_highest_priority_alert(
            [AlertType.STANDING_MOTION_RISK, AlertType.INSTABILITY_RISK]
        )
        self.assertEqual(w, AlertType.INSTABILITY_RISK)


if __name__ == "__main__":
    unittest.main()
