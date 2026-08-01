"""Configuration loading without exposing Home Assistant credentials."""

import os
from pathlib import Path

from dotenv import load_dotenv

from energy_optimizer.models import CollectorConfig


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or invalid."""


def load_config(env_file: Path | None = Path(".env")) -> CollectorConfig:
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    ha_url = os.getenv("HA_URL", "").strip()
    ha_token = os.getenv("HA_TOKEN", "").strip()
    missing = [
        name
        for name, value in (("HA_URL", ha_url), ("HA_TOKEN", ha_token))
        if not value
    ]
    if missing:
        raise ConfigurationError(
            f"Missing required configuration: {', '.join(missing)}"
        )
    return CollectorConfig(
        ha_url=ha_url.rstrip("/"),
        ha_token=ha_token,
        timezone=os.getenv("TIMEZONE", "Australia/Brisbane"),
        database_path=Path(os.getenv("DATABASE_PATH", "data/energy_history.db")),
        collection_interval_seconds=int(
            os.getenv("COLLECTION_INTERVAL_SECONDS", "300")
        ),
        usable_battery_capacity_kwh=float(
            os.getenv("USABLE_BATTERY_CAPACITY_KWH", "40")
        ),
        maximum_plausible_inverter_power_w=float(
            os.getenv("MAXIMUM_PLAUSIBLE_INVERTER_POWER_W", "15000")
        ),
        live_power_freshness_minutes=int(
            os.getenv("LIVE_POWER_FRESHNESS_MINUTES", "5")
        ),
        battery_soc_freshness_minutes=int(
            os.getenv("BATTERY_SOC_FRESHNESS_MINUTES", "10")
        ),
        amber_current_price_freshness_minutes=int(
            os.getenv("AMBER_CURRENT_PRICE_FRESHNESS_MINUTES", "10")
        ),
        amber_forecast_freshness_minutes=int(
            os.getenv("AMBER_FORECAST_FRESHNESS_MINUTES", "60")
        ),
        solcast_forecast_freshness_minutes=int(
            os.getenv("SOLCAST_FORECAST_FRESHNESS_MINUTES", "360")
        ),
        weather_freshness_minutes=int(os.getenv("WEATHER_FRESHNESS_MINUTES", "60")),
        weather_temperature_entity_id=(
            os.getenv("WEATHER_TEMPERATURE_ENTITY_ID", "").strip() or None
        ),
        weather_condition_entity_id=(
            os.getenv("WEATHER_CONDITION_ENTITY_ID", "").strip() or None
        ),
        conservative_fallback_household_load_kw=float(
            os.getenv("CONSERVATIVE_FALLBACK_HOUSEHOLD_LOAD_KW", "2.0")
        ),
        load_profile_minimum_samples=int(
            os.getenv("LOAD_PROFILE_MINIMUM_SAMPLES", "3")
        ),
        request_timeout_seconds=float(os.getenv("HA_REQUEST_TIMEOUT_SECONDS", "10")),
    )


def load_database_path(env_file: Path | None = Path(".env")) -> Path:
    """Load local history configuration without Home Assistant credentials."""
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    return Path(os.getenv("DATABASE_PATH", "data/energy_history.db"))


def load_timezone_name(env_file: Path | None = Path(".env")) -> str:
    """Load the configured local timezone without requiring HA credentials."""
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    return os.getenv("TIMEZONE", "Australia/Brisbane")
