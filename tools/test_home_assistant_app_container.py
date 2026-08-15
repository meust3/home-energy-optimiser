"""Exercise the App bootstrap in Docker without contacting external services."""

import argparse
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER_RUN_SH = "/opt/home-energy-optimiser/home_energy_optimiser/run.sh"
CONTAINER_APP_MODULE = (
    "/usr/local/lib/python3.12/site-packages/energy_optimizer/" "home_assistant_app.py"
)
CONTAINER_PROBE = "/tmp/home-energy-app-probe.py"
HOST_PROBE = ROOT / "tests" / "container_app_probe.py"
TEST_TOKEN = "container-test-supervisor-token"
TEST_PASSWORD = "container-test-password"


def docker(*arguments: str, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run Docker with output captured so callers control secret-safe reporting."""
    return subprocess.run(
        ["docker", *arguments],
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def container_command(
    image: str, volume: str, *command: str, use_image_files: bool
) -> list[str]:
    """Build a Docker invocation using working or image-baked patch files."""
    app_module = ROOT / "src" / "energy_optimizer" / "home_assistant_app.py"
    arguments = [
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--volume",
        f"{volume}:/data",
        "--mount",
        f"type=bind,source={HOST_PROBE},target={CONTAINER_PROBE},readonly",
    ]
    if not use_image_files:
        arguments.extend(
            [
                "--mount",
                f"type=bind,source={ROOT / 'src'},target=/tmp/current-src,readonly",
                "--env",
                "PYTHONPATH=/tmp/current-src",
                "--mount",
                f"type=bind,source={ROOT / 'home_energy_optimiser' / 'run.sh'},"
                f"target={CONTAINER_RUN_SH},readonly",
                "--mount",
                f"type=bind,source={app_module},"
                f"target={CONTAINER_APP_MODULE},readonly",
            ]
        )
    arguments.extend(
        [
            "--env",
            "SUPERVISOR_TOKEN",
            "--entrypoint",
            "/bin/bash",
            image,
            CONTAINER_RUN_SH,
            *command,
        ]
    )
    return arguments


def write_root_only_options(volume: str) -> None:
    """Create the Supervisor fixture as root:root 0600 inside a Docker volume."""
    payload = json.dumps(
        {
            "db_host": "db.example.invalid",
            "db_port": 55432,
            "db_name": "home_energy",
            "db_user": "energy_app",
            "db_password": TEST_PASSWORD,
            "timezone": "Australia/Brisbane",
            "health_max_observation_age_seconds": 900,
            "grid_power_sign": "positive_export",
            "battery_power_sign": "positive_discharge",
            "sign_convention_confidence": "high",
            "sign_convention_supporting_samples": 175,
            "balance_tolerance_w": 250,
            "ev_vehicle_enabled": True,
            "ev_charging_entity": "binary_sensor.test_vehicle_charging",
            "ev_plugged_entity": "binary_sensor.test_vehicle_plugged",
            "ev_online_entity": "binary_sensor.test_vehicle_online",
            "ev_soc_entity": "sensor.test_vehicle_soc",
            "ev_battery_power_entity": "sensor.test_vehicle_battery_power",
            "ev_telemetry_updated_entity": "sensor.test_vehicle_updated",
            "ev_location_entity": "device_tracker.test_vehicle_location",
            "ev_home_state": "home",
            "ev_telemetry_stale_seconds": 900,
            "forecast_operations_enabled": False,
            "forecast_interval_minutes": 30,
            "forecast_horizon_hours": 24,
            "forecast_alignment_minutes": 30,
            "forecast_scoring_delay_minutes": 10,
            "forecast_max_runtime_seconds": 120,
            "reserve_snapshot_enabled": True,
        }
    )
    docker(
        "run",
        "--rm",
        "--volume",
        f"{volume}:/data",
        "--interactive",
        "--mount",
        f"type=bind,source={HOST_PROBE},target={CONTAINER_PROBE},readonly",
        "python:3.12.11-slim-bookworm",
        "python",
        CONTAINER_PROBE,
        "write-options",
        input=payload,
    )


def options_metadata(volume: str) -> str:
    """Return source owner/group and mode from inside a Linux container."""
    return docker(
        "run",
        "--rm",
        "--volume",
        f"{volume}:/data",
        "python:3.12.11-slim-bookworm",
        "stat",
        "-c",
        "%u:%g %a",
        "/data/options.json",
    ).stdout.strip()


def test_options_and_identity(
    image: str,
    volume: str,
    environment: dict[str, str],
    *,
    use_image_files: bool,
) -> None:
    """Confirm parsing, cleanup, credential preservation, and runtime identity."""
    result = docker(
        *container_command(
            image,
            volume,
            "python",
            CONTAINER_PROBE,
            "parse-options",
            use_image_files=use_image_files,
        ),
        env=environment,
    )
    captured_output = result.stdout + result.stderr
    if TEST_PASSWORD in captured_output or TEST_TOKEN in captured_output:
        raise RuntimeError("Container probe printed a secret")
    payload = json.loads(result.stdout.strip())
    expected = {
        "configuration": "parsed",
        "ephemeral_removed": True,
        "gid": 10001,
        "runtime_copy_gid": 10001,
        "runtime_copy_mode": "0600",
        "runtime_copy_uid": 10001,
        "forecast_environment": "propagated",
        "sign_environment": "propagated",
        "status": "ok",
        "token_present": True,
        "uid": 10001,
    }
    if payload != expected:
        raise RuntimeError(f"Unexpected sanitized probe result: {payload!r}")
    print("PASS bootstrap copied options as app:app mode=0600")
    print("PASS configuration parsing succeeded")
    print("PASS all five sign options propagated to the application environment")
    print(
        "PASS all forecast, training, retention, and calibration options "
        "propagated to the application environment"
    )
    print("PASS application process uid=10001 gid=10001")
    print("PASS ephemeral options copy removed")
    print("PASS no secret printed")


def test_sigterm(
    image: str,
    volume: str,
    environment: dict[str, str],
    *,
    use_image_files: bool,
) -> None:
    """Confirm exec-based privilege drop delivers SIGTERM directly to Python."""
    name = f"home-energy-signal-{uuid.uuid4().hex[:12]}"
    command = container_command(
        image,
        volume,
        "python",
        CONTAINER_PROBE,
        "wait-for-sigterm",
        use_image_files=use_image_files,
    )
    command.remove("--rm")
    command[1:1] = ["--name", name, "--detach"]
    try:
        docker(*command, env=environment)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if "PYTHON_READY" in docker("logs", name).stdout:
                break
            time.sleep(0.2)
        else:
            state = docker(
                "inspect", "--format", "{{.State.Status}}", name
            ).stdout.strip()
            logs = docker("logs", name)
            diagnostic = (logs.stdout + logs.stderr).strip()
            raise RuntimeError(
                "Container probe did not become ready; "
                f"state={state!r}, output={diagnostic!r}"
            )
        docker("stop", "--time", "5", name)
        log_result = docker("logs", name)
        logs = log_result.stdout + log_result.stderr
        if TEST_PASSWORD in logs or TEST_TOKEN in logs:
            raise RuntimeError("Signal probe printed a secret")
        if "SIGTERM_REACHED_PYTHON" not in logs:
            raise RuntimeError("SIGTERM did not reach the unprivileged Python process")
        print("PASS SIGTERM reached Python")
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name],
            check=False,
            capture_output=True,
            text=True,
        )


def test_dashboard(
    image: str,
    volume: str,
    environment: dict[str, str],
    *,
    use_image_files: bool,
) -> None:
    """Exercise Ingress shell, static, API, direct denial, and watchdog locally."""
    result = docker(
        *container_command(
            image,
            volume,
            "python",
            CONTAINER_PROBE,
            "dashboard-smoke",
            use_image_files=use_image_files,
        ),
        env=environment,
    )
    captured_output = result.stdout + result.stderr
    if TEST_PASSWORD in captured_output or TEST_TOKEN in captured_output:
        raise RuntimeError("Dashboard smoke test printed a secret")
    payload = json.loads(result.stdout.strip())
    expected = {
        "api_secret_free": True,
        "dashboard": "started",
        "direct_request": "denied",
        "health": "available",
        "nested_static": "loaded",
        "simulated_ingress": "loaded",
        "uid": 10001,
        "gid": 10001,
    }
    if payload != expected:
        raise RuntimeError(f"Unexpected dashboard smoke result: {payload!r}")
    print("PASS dashboard server started as uid=10001 gid=10001")
    print("PASS /health remained available to watchdog")
    print("PASS simulated trusted Ingress loaded shell and nested static asset")
    print("PASS direct request denied even with spoofed forwarding headers")
    print("PASS dashboard API response contained no secret")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Locally built App image")
    parser.add_argument(
        "--use-image-files",
        action="store_true",
        help="Test the image-baked bootstrap and loader instead of working files",
    )
    args = parser.parse_args()
    volume = f"home-energy-options-{uuid.uuid4().hex}"
    environment = os.environ.copy()
    environment["SUPERVISOR_TOKEN"] = TEST_TOKEN
    docker("volume", "create", volume)
    try:
        write_root_only_options(volume)
        before = options_metadata(volume)
        if before != "0:0 600":
            raise RuntimeError(f"Unexpected source options metadata: {before!r}")
        print("PASS original options before bootstrap owner=root:root mode=0600")
        test_options_and_identity(
            args.image,
            volume,
            environment,
            use_image_files=args.use_image_files,
        )
        after = options_metadata(volume)
        if after != before:
            raise RuntimeError(
                "Supervisor options metadata changed: "
                f"before={before!r} after={after!r}"
            )
        print("PASS original options unchanged owner=root:root mode=0600")
        write_root_only_options(volume)
        test_dashboard(
            args.image,
            volume,
            environment,
            use_image_files=args.use_image_files,
        )
        write_root_only_options(volume)
        test_sigterm(
            args.image,
            volume,
            environment,
            use_image_files=args.use_image_files,
        )
    finally:
        docker("volume", "rm", "--force", volume)
    print(
        "Container bootstrap checks passed: root-only options, UID/GID 10001, SIGTERM"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
