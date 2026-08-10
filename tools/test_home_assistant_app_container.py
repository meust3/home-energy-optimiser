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
TEST_TOKEN = "container-test-supervisor-token"


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
    ]
    if not use_image_files:
        arguments.extend(
            [
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
            "db_password": "container-test-password",
            "timezone": "Australia/Brisbane",
            "health_max_observation_age_seconds": 900,
        }
    )
    docker(
        "run",
        "--rm",
        "--volume",
        f"{volume}:/data",
        "--interactive",
        "python:3.12.11-slim-bookworm",
        "sh",
        "-c",
        "umask 077; cat > /data/options.json; chown 0:0 /data/options.json; "
        "chmod 0600 /data/options.json",
        input=payload,
    )


def test_options_and_identity(
    image: str,
    volume: str,
    environment: dict[str, str],
    *,
    use_image_files: bool,
) -> None:
    """Confirm parsing, cleanup, credential preservation, and runtime identity."""
    probe = """
import json
import os
from pathlib import Path
from energy_optimizer.home_assistant_app import load_app_options

options_path = Path(os.environ["HOME_ENERGY_APP_OPTIONS_PATH"])
options = load_app_options()
assert options.db_host == "db.example.invalid"
assert os.environ.get("SUPERVISOR_TOKEN")
assert not options_path.exists()
print(json.dumps({"status": "ok", "uid": os.getuid(), "gid": os.getgid()}))
"""
    result = docker(
        *container_command(
            image,
            volume,
            "python",
            "-c",
            probe,
            use_image_files=use_image_files,
        ),
        env=environment,
    )
    payload = json.loads(result.stdout.strip())
    if payload != {"status": "ok", "uid": 10001, "gid": 10001}:
        raise RuntimeError(f"Unexpected unprivileged process identity: {payload!r}")

    metadata = docker(
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
    if metadata != "0:0 600":
        raise RuntimeError(f"Supervisor options metadata changed: {metadata!r}")


def test_sigterm(
    image: str,
    volume: str,
    environment: dict[str, str],
    *,
    use_image_files: bool,
) -> None:
    """Confirm exec-based privilege drop delivers SIGTERM directly to Python."""
    name = f"home-energy-signal-{uuid.uuid4().hex[:12]}"
    probe = """
import signal
import sys
import time

def stop(_signum, _frame):
    print("SIGTERM_RECEIVED", flush=True)
    sys.exit(0)

signal.signal(signal.SIGTERM, stop)
print("READY", flush=True)
while True:
    time.sleep(1)
"""
    command = container_command(
        image,
        volume,
        "python",
        "-c",
        probe,
        use_image_files=use_image_files,
    )
    command.remove("--rm")
    command[1:1] = ["--name", name, "--detach"]
    try:
        docker(*command, env=environment)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if "READY" in docker("logs", name).stdout:
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
        logs = docker("logs", name).stdout
        if "SIGTERM_RECEIVED" not in logs:
            raise RuntimeError("SIGTERM did not reach the unprivileged Python process")
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name],
            check=False,
            capture_output=True,
            text=True,
        )


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
        test_options_and_identity(
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
