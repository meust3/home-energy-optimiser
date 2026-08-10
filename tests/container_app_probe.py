"""In-container assertions for the Home Assistant App bootstrap test."""

import json
import os
import signal
import stat
import sys
import time
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


def main() -> int:
    actions = {
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
