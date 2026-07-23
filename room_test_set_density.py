# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""Merge JSON into ROOM_TEST density state (CLI). Does not run the engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from adapters.room_test_env import merge_room_test_json_file, room_test_density_state_path


def main() -> None:
    if len(sys.argv) < 2:
        print(
            'Usage: python room_test_set_density.py \'{"passengers_onboard":5,"vehicle_capacity":50}\'',
            file=sys.stderr,
        )
        sys.exit(2)
    raw = sys.argv[1]
    patch = json.loads(raw)
    if not isinstance(patch, dict):
        print("JSON must be an object", file=sys.stderr)
        sys.exit(2)
    path = room_test_density_state_path()
    merge_room_test_json_file(path, patch)
    print(path)


if __name__ == "__main__":
    main()
