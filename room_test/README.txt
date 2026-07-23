Room-based validation (PoC backend)

Enable: ROOM_TEST=1 or TRAVELMATE_ROOM_TEST=1.

Fast validation cadence (1 tick per second): set before runtime_loop.py:
  $env:ROOM_TEST_TICK_SECONDS = "1"
  (alias: ROOM_TEST_TICK_SEC)
  If unset, TRAVELMATE_TICK_INTERVAL_SEC still applies (default 120s).

Recommended: **second terminal for prompts** (stays readable; runtime logs stay in the other window):
  Terminal A: ROOM_TEST=1 only — python runtime_loop.py
  Terminal B: same ROOM_TEST_ROOT if you use it — python room_test_control_terminal.py

Optional: ROOM_TEST_INTERACTIVE=1 on runtime_loop (prompts in the same window as logs; often scrolls away).

Prompt order: density, vehicle_capacity, speed, braking_intensity, turn_intensity,
doors_open, ramp_deployed, vehicle_stationary. Empty Enter keeps the value in [ ].

If TRAVELMATE_DEMO is on with stdin interactive, use TRAVELMATE_DEMO_EMERGENCY_ACK_FILE for ack.

Authoritative manual inputs (per tick, no auto ramp / timeline writes):
  • Density: room_density_state.json in this folder (or ROOM_TEST_DENSITY_JSON).
  • Fake CAN: room_can_state.json (or ROOM_TEST_CAN_JSON).

Example density file:
  { "passengers_onboard": 5, "vehicle_capacity": 50 }

CAN fields (all optional in a patch; merge CLI replaces keys you pass):
  speed, braking_intensity, turn_intensity, doors_open, ramp_deployed, vehicle_stationary

CLI (from project root; PowerShell — single-quote the JSON):
  python room_test_set_density.py '{"passengers_onboard":12,"vehicle_capacity":50}'
  python room_test_set_can.py '{"speed":0.3,"vehicle_stationary":false}'

Optional ROOM_TEST_ROOT. Camera/consent/passenger JSON paths unchanged (see adapters/room_test_env.py).

TRAVELMATE_DEMO + ROOM_TEST: demo timeline does not run; consent episodes only
change support_categories and demo_* UI fields, not CAN or density.

Per-tick log: ROOM_TEST_JSON includes room_test_input_sources and observer_validation.

Phase-1B — live camera (OpenCV), CAN/density still JSON files:
  $env:ROOM_TEST = "1"
  $env:ROOM_TEST_LIVE_CAMERA = "1"
  $env:ROOM_TEST_CAMERA_INDEX = "1"    # Cam Link OpenCV index; required, no default
  $env:ROOM_TEST_PHASE1_VALIDATE = "1"
  Optional: same tuning as TRAVELMATE_* (door band, standing dwell) on env — see adapters/camera_adapter.py
  If open fails while another window holds the device: stop room_test_camlink_verify.py first.
  Preview + backend together: use ``ROOM_TEST_SHOW_PREVIEW=1`` on ``runtime_loop`` only — do not
  run ``room_test_camlink_verify.py`` on the same camera index (Windows: one capture handle).
  If DSHOW open fails: $env:ROOM_TEST_TRY_CAP_MSMF = "1" (retries with CAP_MSMF on Windows).
  Disable live: unset ROOM_TEST_LIVE_CAMERA (falls back to camera JSON when no GOPRO index).


Phase-1 E2E trace (logging + terminal lines; does not change backend rules):
  $env:ROOM_TEST = "1"
  $env:ROOM_TEST_PHASE1_VALIDATE = "1"
  python runtime_loop.py
  Sets non–Phase-1 observed cues to 0.0 each tick (near_door_area, prolonged_standing,
  unstable_posture, floor_level_posture unchanged from adapter/JSON).
  Terminal: PHASE1_CUES (full cue dict JSON), PHASE1_MIRROR (scenario mirror + policy flags),
  PHASE1_TRACE in log JSON, PHASE1_ALERT on primary/emergency fingerprint changes.

Cam Link 4K (separate from runtime loop; no camera fallback; single --device-index only):

  Test #1 — live + FPS (buffer=1; watch for delay/ghosting when you move / leave frame):
    python room_test_camlink_verify.py --device-index 1 --width 1920 --height 1080 --fps 30

  Test #2 — frame orientation (use the same verify window; decide door region for later):
    (same command as #1; adjust physical camera if door not visible.)

  Test #3 — motion vs stillness (mean absdiff; left=live, right=heat):
    python room_test_camlink_motion.py --device-index 1 --width 1920 --height 1080 --fps 30

  Test #4 — higher FPS request (headroom; driver may cap):
    python room_test_camlink_verify.py --device-index 1 --width 1920 --height 1080 --fps 60

  Note: every flag needs a value, e.g. --fps 30 or --fps 60 (not “--fps” alone).
