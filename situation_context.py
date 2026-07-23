# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
TravelMate AI — situation-based (zone) interpretation for the PoC.

Multi-passenger cabin state is not modeled as a list of individuals. Instead:

- **behaviour** is the most relevant fused / worst-zone observable cue in [0, 1] for the
  situation (e.g. aggregate non-biometric activity or instability proxy across zones).

- **density** is an occupancy / load cue in [0, 1]. It compounds into risk and participates
  in factor-elevation gating; it is not a person identifier. Prefer treating it as
  sensitivity to crowding in the compounded score rather than as a label of who is on board.

- **Alert kind** is chosen at most once per tick via `select_operational_alert_type` and
  `ALERT_PRIORITY` in `alert_routing.py` when multiple scenario cues could apply.

CAN-derived **motion** (see `derive_motion_level`) modulates vehicle dynamics only; it does
not select alert types by itself.
"""
