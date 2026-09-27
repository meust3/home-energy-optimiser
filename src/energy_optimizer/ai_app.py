"""Optional production App configuration. Reading it performs no network I/O."""

import json
from pathlib import Path

from energy_optimizer.ai_integration import AISettings

APP_AI_DIRECTORY = Path("/data/ai-control-panel")
APP_AI_STATUS = Path("/run/home-energy-optimiser/ai-status.json")


def app_ai_environment(
    directory: Path = APP_AI_DIRECTORY,
    status_file: Path = APP_AI_STATUS,
) -> dict[str, str]:
    """Load the separately installed Energy bundle without affecting core startup.

    The App always uses its production slot. Neither credentials nor arbitrary
    environment overrides belong in Supervisor options or browser configuration.
    Invalid optional configuration is visible in status, never a startup error.
    """
    disabled = {"ENERGY_AI_ENABLED": "false"}
    invalid = {"ENERGY_AI_ENABLED": "invalid"}
    try:
        config = directory / "connection.json"
        if not config.exists():
            return disabled
        if directory.is_symlink() or config.is_symlink():
            return invalid
        with config.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return invalid
        values = json.loads(raw)
        if not isinstance(values, dict) or set(values) != {"enabled", "base_url"}:
            return invalid
        if type(values["enabled"]) is not bool:
            return invalid
        if not values["enabled"]:
            return disabled
        if not isinstance(values["base_url"], str) or not values["base_url"].startswith(
            "https://"
        ):
            return invalid
        files = {
            "ENERGY_AI_KEY_FILE": "runtime-production.key",
            "ENERGY_AI_CA_FILE": "ca.crt",
            "ENERGY_AI_CERT_FILE": "client.crt",
            "ENERGY_AI_CERT_KEY_FILE": "client.key",
        }
        for name in files.values():
            path = directory / name
            if path.is_symlink() or not path.is_file():
                return invalid
        env = {
            "ENERGY_AI_ENABLED": "true",
            "ENERGY_AI_ENVIRONMENT": "production",
            "ENERGY_AI_BASE_URL": values["base_url"],
            "ENERGY_AI_STATUS_FILE": str(status_file),
            **{key: str(directory / name) for key, name in files.items()},
        }
        AISettings.from_environment(env)
        return env
    except (OSError, ValueError, TypeError, RecursionError):
        # No exception text: paths or malformed config may contain credentials.
        return invalid
