# © 2026 TravelMate AI.
# Confidential and Proprietary.
# All rights reserved.

"""
Local HTTP mirror of ``BackendSession.step`` stacked alerts for Phase‑3 validation.

Serves ``GET /alerts``, ``GET /tablet_bundle`` (context for /ui), ``GET /ui``, and ``POST /acknowledge_emergency``.
When ``ROOM_TEST`` is enabled: ``GET /test/vehicle_context``, ``POST /test/set_vehicle_context``,
``POST /test/request_route_diversion`` (simulation overrides only; 404 when ROOM_TEST is off).
The POST route only queues a one-shot signal; ``runtime_loop`` applies the same
``evaluate_driver_tick`` / sticky clearing rules as other ack channels.

Requires Flask (see requirements_alert_display.txt).

Set ``TRAVELMATE_ALERT_DISPLAY_HTTP=1`` before starting ``runtime_loop.py``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import Any, Mapping

_TABLET_UI_PATH = Path(__file__).resolve().parent / "tablet_display_ui.html"

from adapters.room_test_env import room_test_enabled
from alert_display_view import alert_rows_from_backend_output
from room_test_context_override import (
    apply_vehicle_context_patch,
    room_test_control_bundle_for_tablet,
    snapshot_override,
)
from room_test_sim_limits import (
    MAX_BRAKING_INTENSITY,
    MAX_REALISTIC_SPEED_KMH,
    MAX_TURN_INTENSITY,
)
from tablet_attention_mode import (
    attention_mode_payload_from_tick,
    tertiary_panel_payload_from_tick,
    vehicle_panel_payload_from_tick,
)


def _candidate_ipv4s_for_hints() -> list[str]:
    """
    Best-effort local IPv4s for operator hints (tablet must use one of these, not gateway-only).
    Excludes loopback.
    """
    out: set[str] = set()
    try:
        hn = socket.gethostname()
        for res in socket.getaddrinfo(hn, None, socket.AF_INET, socket.SOCK_STREAM):
            addr = res[4][0]
            if addr and not addr.startswith("127."):
                out.add(addr)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Does not send traffic — picks outbound interface IPv4 when route exists.
            s.connect(("198.51.100.1", 1))
            lb = s.getsockname()[0]
            if lb and not lb.startswith("127."):
                out.add(lb)
        finally:
            s.close()
    except OSError:
        pass
    return sorted(out)


class AlertDisplayPublishHub:
    """Thread-safe snapshot + one-shot emergency-ack queue for the HTTP UI."""

    __slots__ = (
        "_ack_lock",
        "_ack_pending",
        "_bundle_extras",
        "_lock",
        "_rows",
        "_tick_seq",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] = []
        self._tick_seq = 0
        self._bundle_extras: dict[str, Any] = {}
        self._ack_lock = threading.Lock()
        self._ack_pending = False

    def publish(
        self,
        backend_output: Mapping[str, Any],
        tick_seq: int,
        tick: Mapping[str, Any] | None = None,
    ) -> None:
        rows = alert_rows_from_backend_output(backend_output)
        extras: dict[str, Any] = {}
        if tick is not None:
            extras["attention"] = attention_mode_payload_from_tick(tick)
            extras["vehicle"] = vehicle_panel_payload_from_tick(tick)
            extras["tertiary"] = tertiary_panel_payload_from_tick(tick)
            if room_test_enabled():
                extras["room_test_control"] = room_test_control_bundle_for_tablet(tick)
        with self._lock:
            self._rows = rows
            self._tick_seq = tick_seq
            self._bundle_extras = extras

    def snapshot_alerts(self) -> tuple[int, list[dict[str, Any]]]:
        with self._lock:
            return self._tick_seq, list(self._rows)

    def snapshot_tablet_bundle(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tick_seq": self._tick_seq,
                "alerts": list(self._rows),
                **self._bundle_extras,
            }

    def request_emergency_acknowledgment_via_http(self) -> None:
        """UI / tablet: arm a one-shot consumed by ``runtime_loop`` (no eval logic here)."""
        with self._ack_lock:
            self._ack_pending = True

    def consume_emergency_acknowledgment_requested(self) -> bool:
        """Runtime: at most one ``True`` per queued request; clears the flag."""
        with self._ack_lock:
            if not self._ack_pending:
                return False
            self._ack_pending = False
            return True


def _truthy_alert_display_http() -> bool:
    raw = os.environ.get("TRAVELMATE_ALERT_DISPLAY_HTTP", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def maybe_start_alert_display_server(
    log: logging.Logger | None,
) -> AlertDisplayPublishHub | None:
    """
    If enabled via env, start Flask on ``0.0.0.0:<port>`` (default 8765) and return publish hub.

    Uses a daemon thread; callers must invoke ``hub.publish(output, tick_seq, tick)`` after ``backend.step``.
    """
    if not _truthy_alert_display_http():
        return None
    try:
        from flask import Flask, Response, request
    except ImportError:
        if log:
            log.warning(
                "TRAVELMATE_ALERT_DISPLAY_HTTP enabled but Flask is not installed "
                "(pip install -r requirements_alert_display.txt); alert display HTTP disabled."
            )
        return None

    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    port_raw = os.environ.get("TRAVELMATE_ALERT_DISPLAY_PORT", "").strip()
    port = int(port_raw) if port_raw else 8765

    hub = AlertDisplayPublishHub()

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.get("/alerts")
    def route_alerts() -> Response:
        tick_seq, rows = hub.snapshot_alerts()
        payload = json.dumps(rows, separators=(",", ":"))
        resp = Response(
            payload,
            status=200,
            mimetype="application/json",
        )
        resp.headers["X-Tick-Seq"] = str(tick_seq)
        return resp

    @app.get("/tablet_bundle")
    def route_tablet_bundle() -> Response:
        bundle = hub.snapshot_tablet_bundle()
        tick_seq = bundle.get("tick_seq", 0)
        payload = json.dumps(bundle, separators=(",", ":"))
        resp = Response(payload, status=200, mimetype="application/json")
        resp.headers["X-Tick-Seq"] = str(tick_seq)
        return resp

    @app.post("/acknowledge_emergency")
    def route_acknowledge_emergency() -> Response:
        # No body parsing — runtime owns clearing when a pending emergency exists.
        hub.request_emergency_acknowledgment_via_http()
        payload = json.dumps({"ok": True}, separators=(",", ":"))
        return Response(
            payload,
            status=200,
            mimetype="application/json",
        )

    @app.get("/ui")
    def route_ui() -> Response:
        try:
            html = _TABLET_UI_PATH.read_text(encoding="utf-8")
        except OSError:
            html = (
                "<!DOCTYPE html><html><body><p>Missing tablet_display_ui.html beside "
                "alert_display_http_server.py</p></body></html>"
            )
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    def _room_test_http_404() -> Response | None:
        if room_test_enabled():
            return None
        payload = json.dumps({"ok": False, "error": "ROOM_TEST_disabled"}, separators=(",", ":"))
        return Response(payload, status=404, mimetype="application/json")

    @app.get("/test/vehicle_context")
    def route_test_vehicle_context() -> Response:
        blocked = _room_test_http_404()
        if blocked is not None:
            return blocked
        payload = json.dumps(
            {
                "ok": True,
                "limits": {
                    "speed_kmh_max": MAX_REALISTIC_SPEED_KMH,
                    "braking_intensity_max": MAX_BRAKING_INTENSITY,
                    "turn_intensity_max": MAX_TURN_INTENSITY,
                },
                "override": snapshot_override(),
            },
            separators=(",", ":"),
        )
        return Response(payload, status=200, mimetype="application/json")

    @app.post("/test/set_vehicle_context")
    def route_test_set_vehicle_context() -> Response:
        blocked = _room_test_http_404()
        if blocked is not None:
            return blocked
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        snap = apply_vehicle_context_patch(body)
        payload = json.dumps({"ok": True, "override": snap}, separators=(",", ":"))
        return Response(payload, status=200, mimetype="application/json")

    @app.post("/test/request_route_diversion")
    def route_test_request_route_diversion() -> Response:
        blocked = _room_test_http_404()
        if blocked is not None:
            return blocked
        logging.getLogger("travelmate.room_test_http").info("Diversion requested from UI")
        payload = json.dumps({"ok": True, "message": "Diversion requested from UI"}, separators=(",", ":"))
        return Response(payload, status=200, mimetype="application/json")

    def run_flask() -> None:
        try:
            app.run(
                host="0.0.0.0",
                port=port,
                threaded=True,
                use_reloader=False,
                debug=False,
            )
        except OSError as exc:
            if log:
                log.error(
                    "TRAVELMATE_ALERT_DISPLAY_HTTP: failed to bind 0.0.0.0:%s (%s). "
                    "Pick another TRAVELMATE_ALERT_DISPLAY_PORT or free the socket.",
                    port,
                    exc,
                )

    threading.Thread(
        target=run_flask,
        name="travelmate.alert_display_http",
        daemon=True,
    ).start()

    if log:
        log.info(
            "TRAVELMATE_ALERT_DISPLAY_HTTP: listening on 0.0.0.0:%s · try on this PC "
            "http://127.0.0.1:%s/ui · GET /tablet_bundle · GET /alerts · POST /acknowledge_emergency"
            + (
                " · ROOM_TEST: GET /test/vehicle_context · POST /test/set_vehicle_context · "
                "POST /test/request_route_diversion"
                if room_test_enabled()
                else ""
            ),
            port,
            port,
        )
        ips = _candidate_ipv4s_for_hints()
        if ips:
            for ip in ips:
                log.info(
                    "TRAVELMATE_ALERT_DISPLAY_HTTP: tablet / phone URL http://%s:%s/ui",
                    ip,
                    port,
                )
        else:
            log.info(
                "TRAVELMATE_ALERT_DISPLAY_HTTP: could not enumerate LAN IPs — run ipconfig "
                "and open http://<your-PC-Wi-Fi-IPv4>:%s/ui on the tablet (same hotspot/Wi‑Fi).",
                port,
            )
        log.info(
            "TRAVELMATE_ALERT_DISPLAY_HTTP: if localhost works but the tablet timed out or "
            "refused connection, allow inbound TCP %s (Admin PowerShell): "
            "New-NetFirewallRule -DisplayName 'TravelMate Alert UI %s' "
            "-Direction Inbound -LocalPort %s -Protocol TCP -Action Allow",
            port,
            port,
            port,
        )

    return hub
