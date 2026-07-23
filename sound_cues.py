# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — backend sound cue tokens (PoC).

UI/audio layers map these to assets; the backend only emits cues on state transitions.
"""

from __future__ import annotations

from enum import Enum


class SoundCue(str, Enum):
    """Single cue per tick at most; NONE on steady state."""

    NONE = "NONE"
    INFO = "INFO"
    NOT_READY = "NOT_READY"
    SAFETY = "SAFETY"
    EMERGENCY = "EMERGENCY"
    STARTUP = "STARTUP"
    READY = "READY"


# Higher value wins when multiple transitions occur the same tick.
_SOUND_PRIORITY_RANK: dict[SoundCue, int] = {
    SoundCue.NONE: 0,
    SoundCue.STARTUP: 20,
    SoundCue.INFO: 40,
    SoundCue.NOT_READY: 55,
    SoundCue.READY: 60,
    SoundCue.SAFETY: 80,
    SoundCue.EMERGENCY: 100,
}


def sound_cue_priority(cue: SoundCue) -> int:
    return _SOUND_PRIORITY_RANK[cue]
