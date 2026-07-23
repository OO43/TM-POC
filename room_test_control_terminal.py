# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
ROOM_TEST prompts in a **second terminal** (recommended).

Writes ``room_density_state.json`` and ``room_can_state.json``; ``runtime_loop.py`` in
another window reads them each tick. No log spam from the runtime here, so prompts
stay visible.

Run from project root (use the same ROOM_TEST_ROOT as runtime if you set it):

  python room_test_control_terminal.py

Do **not** set ROOM_TEST_INTERACTIVE=1 on ``runtime_loop`` when using this script.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root on path when launched as a script.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from room_test_interactive import StdinClosed, _one_prompt_round


def main() -> None:
    log = logging.getLogger("travelmate.room_test_control_terminal")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    sys.stdout.write(
        "ROOM_TEST — control terminal (this window only)\n"
        "  • Run runtime_loop in another terminal with ROOM_TEST=1 only (not ROOM_TEST_INTERACTIVE).\n"
        "  • Use the same ROOM_TEST_ROOT here if you set it there.\n"
        "  • Empty Enter keeps the value in [ ]. Ctrl+Z then Enter (Windows) or Ctrl+D (Unix) to exit.\n\n"
    )
    sys.stdout.flush()

    while True:
        try:
            _one_prompt_round(log)
        except StdinClosed:
            sys.stdout.write("\nExiting control terminal.\n")
            sys.stdout.flush()
            break


if __name__ == "__main__":
    main()
