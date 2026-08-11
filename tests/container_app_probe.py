"""In-container assertions for the Home Assistant App bootstrap test."""

import json
import os
import signal
import stat
import sys
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

OPTIONS_PATH_ENV = "HOME_ENERGY_APP_OPTIONS_PATH"
SOURCE_OPTIONS = Path("/data/options.json")


def write_options() -> None:
    """Write an stdin fixture as root without passing its contents on argv."""
    payload = sys.stdin.buffer.read()
    descriptor = os.open(
        SOURCE_OPTIONS,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    os.chown(SOURCE_OPTIONS, 0, 0)
    os.chmod(SOURCE_OPTIONS, 0o600)


def parse_options() -> None:
    """Assert copied-file metadata, parse it, and print only safe evidence."""
    from energy_optimizer.home_assistant_app import load_app_options

    runtime_path = Path(os.environ[OPTIONS_PATH_ENV])
    runtime_metadata = runtime_path.stat()
    runtime_mode = stat.S_IMODE(runtime_metadata.st_mode)
    assert runtime_metadata.st_uid == 10001
    assert runtime_metadata.st_gid == 10001
    assert runtime_mode == 0o600

    options = load_app_options()
    assert options.db_host == "db.example.invalid"
    assert options.ev_vehicle_enabled
    assert options.ev_charging_entity == "binary_sensor.test_vehicle_charging"
    assert options.ev_telemetry_stale_seconds == 900
    assert os.environ.get("SUPERVISOR_TOKEN")
    assert not runtime_path.exists()
    print(
        json.dumps(
            {
                "configuration": "parsed",
                "ephemeral_removed": True,
                "gid": os.getgid(),
                "runtime_copy_gid": runtime_metadata.st_gid,
                "runtime_copy_mode": f"{runtime_mode:04o}",
                "runtime_copy_uid": runtime_metadata.st_uid,
                "status": "ok",
                "token_present": True,
                "uid": os.getuid(),
            },
            sort_keys=True,
        ),
        flush=True,
    )


def wait_for_sigterm() -> None:
    """Remain alive until SIGTERM proves it reaches this Python process."""

    def stop(_signum: int, _frame: object) -> None:
        print("SIGTERM_REACHED_PYTHON", flush=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    print("PYTHON_READY", flush=True)
    while True:
        time.sleep(1)


def dashboard_smoke() -> None:
    """Exercise current local dashboard code without Home Assistant or PostgreSQL."""
    from energy_optimizer.dashboard_api import LiveResponse, StatusResponse
    from energy_optimizer.dashboard_web import IngressAccessPolicy, make_handler
    from energy_optimizer.home_assistant import HomeAssistantClient
    from energy_optimizer.home_assistant_app import AppHealth, load_app_options

    load_app_options()

    class Service:
        def live(self):
            return LiveResponse(
                available=True,
                ev_vehicle_configured=True,
                ev_vehicle_available=True,
                ev_vehicle_soc_percent=64,
                ev_charging_active=False,
                ev_plugged_in=True,
                ev_at_home=True,
                ev_telemetry_fresh=True,
                ev_vehicle_status="plugged_idle",
                ev_vehicle_battery_power_w_raw=-18.5,
            )

        def status(self):
            return StatusResponse(
                app_version="0.4.0",
                overall_status="healthy",
                collector_status="healthy",
                database_status="healthy",
                home_assistant_status="healthy",
                latest_successful_collection_utc=None,
                latest_observation_slot_utc=None,
                observation_age_seconds=None,
                database_schema_revision="test",
                expected_schema_revision="test",
            )

    def start(policy):
        handler = make_handler(
            health=AppHealth(900), service=Service(), access_policy=policy
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def request(server, path, headers=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    prefix = "/api/hassio_ingress/container-test/"
    server, thread = start(IngressAccessPolicy())
    try:
        status, shell = request(server, prefix, {"X-Ingress-Path": prefix})
        assert status == 200 and f'<base href="{prefix}">'.encode() in shell
        assert b'id="overview-ev"' in shell
        status, css = request(
            server,
            prefix + "static/app.css?v=0.4.0",
            {"X-Ingress-Path": prefix},
        )
        assert status == 200 and b"prefers-color-scheme" in css
        status, api = request(
            server,
            prefix + "api/v1/live",
            {"X-Ingress-Path": prefix},
        )
        payload = json.loads(api)
        assert status == 200 and payload["ev_vehicle_status"] == "plugged_idle"
        assert "vin" not in api.decode().lower()
        assert "latitude" not in api.decode().lower()
        assert "longitude" not in api.decode().lower()
        assert not hasattr(HomeAssistantClient, "post")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)

    denied, denied_thread = start(IngressAccessPolicy(allow_loopback=False))
    try:
        status, _ = request(
            denied,
            "/",
            {
                "X-Forwarded-For": "172.30.32.2",
                "X-Ingress-Path": prefix,
            },
        )
        assert status == 403
        health_status, _ = request(denied, "/health")
        assert health_status == 200
    finally:
        denied.shutdown()
        denied.server_close()
        denied_thread.join(5)
    print(
        json.dumps(
            {
                "api_secret_free": True,
                "dashboard": "started",
                "direct_request": "denied",
                "health": "available",
                "nested_static": "loaded",
                "simulated_ingress": "loaded",
                "uid": os.getuid(),
                "gid": os.getgid(),
            },
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> int:
    actions = {
        "dashboard-smoke": dashboard_smoke,
        "parse-options": parse_options,
        "wait-for-sigterm": wait_for_sigterm,
        "write-options": write_options,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit("Expected one probe action")
    actions[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
