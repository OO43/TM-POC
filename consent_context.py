# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — consent context (PoC).

``active_support_categories`` is the **only** declared source for pregnancy-related,
medical-sensitivity, neurodiversity, child-support, elderly-support, mobility, and
visual-navigation accommodation flags in policy. Consent **never** creates a detection
event; it only selects threshold rows and eligibility for certain **operational**
alert kinds when combined with observable cues.
"""

from __future__ import annotations

from dataclasses import dataclass

from thresholds import SupportCategory


@dataclass(frozen=True)
class ConsentContext:
    active_support_categories: frozenset[SupportCategory]
