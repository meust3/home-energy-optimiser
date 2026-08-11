"""Home Assistant App configuration, readiness checks, and secret-safe health."""

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr, ValidationError
from sqlalchemy.engine import URL

from energy_optimizer import entity_ids
from energy_optimizer.config import ConfigurationError
from energy_optimizer.db.migrations import current_revision, expected_revision
from energy_optimizer.db.redaction import redact_database_urls
from energy_optimizer.home_assistant import HomeAssistantClient, redact_secret
from energy_optimizer.persistence import ApplicationRepository, open_repository

SUPERVISOR_CORE_API_URL = "http://supervisor/core/api"
APP_VERSION = "0.4.0"
HEALTH_PORT = 8099
OPTIONS_PATH_ENV = "HOME_ENERGY_APP_OPTIONS_PATH"
SUPERVISOR_OPTIONS_PATH = Path("/data/options.json")
EPHEMERAL_OPTIONS_PATH = Path("/run/home-energy-optimiser/options.json")


class HomeAssistantAppOptions(BaseModel):
    """Validated values read from Supervisor-managed ``/data/options.json``."""

    db_host: str = Field(min_length=1)
    db_port: int = Field(default=55432, ge=1, le=65535)
    db_name: str = Field(default="home_energy", min_length=1)
    db_user: str = Field(default="energy_app", min_length=1)
    db_password: SecretStr
    timezone: str = "Australia/Brisbane"
    health_max_observation_age_seconds: int = Field(default=900, ge=300)
    ev_vehicle_enabled: bool = False
    ev_charging_entity: str = ""
    ev_plugged_entity: str = ""
    ev_online_entity: str = ""
    ev_soc_entity: str = ""
    ev_battery_power_entity: str = ""
    ev_telemetry_updated_entity: str = ""
    ev_location_entity: str = ""
    ev_home_state: str = Field(default="home", min_length=1)
    ev_telemetry_stale_seconds: int = Field(default=900, gt=0)


def load_app_options(
    path: Path | None = None,
) -> HomeAssistantAppOptions:
    """Read App options, report safe failure classes, and remove runtime copies."""
    options_path = path or Path(
        os.getenv(OPTIONS_PATH_ENV, str(SUPERVISOR_OPTIONS_PATH))
    )
    try:
        raw_options = options_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigurationError(
            "Unable to read Home Assistant App options file: file not found"
        ) from None
    except PermissionError:
        raise ConfigurationError(
            "Unable to read Home Assistant App options file: permission denied"
        ) from None
    except OSError:
        raise ConfigurationError(
            "Unable to read Home Assistant App options file: operating system error"
        ) from None

    try:
        payload = json.loads(raw_options)
    except json.JSONDecodeError:
        raise ConfigurationError(
            "Home Assistant App options contain malformed JSON"
        ) from None

    try:
        options = HomeAssistantAppOptions.model_validate(payload)
    except ValidationError:
        raise ConfigurationError(
            "Home Assistant App options failed schema validation"
        ) from None

    if not options.db_password.get_secret_value():
        raise ConfigurationError(
            "Home Assistant App options require a non-empty database password"
        )

    if options_path == EPHEMERAL_OPTIONS_PATH:
        try:
            options_path.unlink()
        except OSError:
            raise ConfigurationError(
                "Home Assistant App options loaded but the ephemeral copy could "
                "not be removed"
            ) from None
    return options


def postgresql_url(options: HomeAssistantAppOptions) -> str:
    """Build the sole App database URL with SQLAlchemy URL encoding."""
    return URL.create(
        "postgresql+psycopg",
        username=options.db_user,
        password=options.db_password.get_secret_value(),
        host=options.db_host,
        port=options.db_port,
        database=options.db_name,
    ).render_as_string(hide_password=False)


def app_environment(
    options: HomeAssistantAppOptions, *, supervisor_token: str | None = None
) -> dict[str, str]:
    """Create the App process environment without any SQLite fallback."""
    token = (supervisor_token or os.getenv("SUPERVISOR_TOKEN", "")).strip()
    if not token:
        raise ConfigurationError(
            "SUPERVISOR_TOKEN is unavailable; homeassistant_api must be enabled"
        )
    environment = {
        "HA_URL": SUPERVISOR_CORE_API_URL,
        "HA_TOKEN": token,
        "DATABASE_URL": postgresql_url(options),
        "TIMEZONE": options.timezone,
        "EV_VEHICLE_ENABLED": str(options.ev_vehicle_enabled).lower(),
        "EV_CHARGING_ENTITY": options.ev_charging_entity.strip(),
        "EV_PLUGGED_ENTITY": options.ev_plugged_entity.strip(),
        "EV_ONLINE_ENTITY": options.ev_online_entity.strip(),
        "EV_SOC_ENTITY": options.ev_soc_entity.strip(),
        "EV_BATTERY_POWER_ENTITY": options.ev_battery_power_entity.strip(),
        "EV_TELEMETRY_UPDATED_ENTITY": options.ev_telemetry_updated_entity.strip(),
        "EV_LOCATION_ENTITY": options.ev_location_entity.strip(),
        "EV_HOME_STATE": options.ev_home_state.strip(),
        "EV_TELEMETRY_STALE_SECONDS": str(options.ev_telemetry_stale_seconds),
    }
    return environment


def redact_runtime_error(value: Any, *secrets: str | None) -> str:
    """Redact database URLs and runtime-only credentials from an error."""
    message = redact_database_urls(value)
    for secret in secrets:
        message = redact_secret(message, secret or "")
    return message


def validate_startup(
    *,
    database_url: str,
    ha_url: str,
    ha_token: str,
    request_timeout_seconds: float = 10.0,
    repository_factory=open_repository,
    client_factory=HomeAssistantClient,
) -> None:
    """Fail closed unless PostgreSQL, schema, and read-only HA access are ready."""
    if not database_url.startswith("postgresql+psycopg://"):
        raise ConfigurationError(
            "Home Assistant App requires PostgreSQL; SQLite fallback is disabled"
        )
    repository: ApplicationRepository = repository_factory(database_url)
    try:
        repository.ping()
        found = current_revision(repository.engine)
        wanted = expected_revision()
        if found != wanted:
            raise ConfigurationError(
                f"Database schema revision {wanted} expected; found {found or 'none'}. "
                "Run database migration before restarting the App."
            )
        required_tables = {
            "observations",
            "forecast_runs",
            "forecast_points",
            "observation_derivations",
            "ev_session_annotations",
            "ev_session_annotation_rows",
        }
        if not required_tables.issubset(repository.table_counts().__dict__):
            raise ConfigurationError("Database application-readiness check failed")
    finally:
        repository.close()
    with client_factory(
        ha_url, ha_token, timeout_seconds=request_timeout_seconds
    ) as client:
        client.check_api()
        states = client.get_states(entity_ids.REQUIRED_ENTITY_IDS)
    missing = sorted(set(entity_ids.REQUIRED_ENTITY_IDS) - set(states))
    if missing:
        raise ConfigurationError(
            "Required Home Assistant entities are unavailable: " + ", ".join(missing)
        )


@dataclass
class AppHealth:
    """Thread-safe, non-secret collector heartbeat exposed to Supervisor."""

    max_observation_age_seconds: int
    version: str = APP_VERSION
    database: str = "healthy"
    home_assistant: str = "healthy"
    collector: str = "healthy"
    dashboard: str = "healthy"
    last_successful_collection_utc: datetime | None = None
    last_slot_utc: datetime | None = None
    _started_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    _database_failures: int = 0
    _home_assistant_failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self, observation: Any) -> None:
        with self._lock:
            self.database = "healthy"
            self.home_assistant = "healthy"
            self.collector = "healthy"
            self._database_failures = 0
            self._home_assistant_failures = 0
            self.last_successful_collection_utc = datetime.now(UTC)
            self.last_slot_utc = observation.slot_utc.astimezone(UTC)

    def record_failure(self, component: str) -> None:
        with self._lock:
            if component == "database":
                self._database_failures += 1
                if self._database_failures >= 3:
                    self.database = "unhealthy"
            elif component == "home_assistant":
                self._home_assistant_failures += 1
                if self._home_assistant_failures >= 3:
                    self.home_assistant = "unhealthy"

    def response(self, *, now: datetime | None = None) -> tuple[int, dict[str, Any]]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        with self._lock:
            reference = self.last_successful_collection_utc or self._started_at_utc
            age = (current - reference).total_seconds()
            stale = age > self.max_observation_age_seconds
            collector = "unhealthy" if stale else self.collector
            healthy = (
                self.database == "healthy"
                and self.home_assistant == "healthy"
                and collector == "healthy"
            )
            payload = {
                "status": "healthy" if healthy else "unhealthy",
                "database": self.database,
                "home_assistant": self.home_assistant,
                "collector": collector,
                "dashboard": self.dashboard,
                "last_successful_collection_utc": _iso(
                    self.last_successful_collection_utc
                ),
                "last_slot_utc": _iso(self.last_slot_utc),
                "observation_age_seconds": (
                    round(age, 1)
                    if self.last_successful_collection_utc is not None
                    else None
                ),
                "version": self.version,
            }
        return (200 if healthy else 503), payload


def start_dashboard_server(
    health: AppHealth, *, database_url: str, port: int
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the one internal watchdog and Home Assistant Ingress server."""
    from energy_optimizer.dashboard_web import create_dashboard_server

    server = create_dashboard_server(
        health=health, database_url=database_url, port=port
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None
