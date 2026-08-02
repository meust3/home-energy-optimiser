"""Configuration loading without exposing Home Assistant credentials."""

import os
from pathlib import Path

from dotenv import load_dotenv

from energy_optimizer.models import CollectorConfig


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or invalid."""


def _optional_env(name: str) -> str | None:
    return os.getenv(name, "").strip() or None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


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
        weather_temperature_entity_id=_optional_env("WEATHER_TEMPERATURE_ENTITY_ID"),
        weather_condition_entity_id=_optional_env("WEATHER_CONDITION_ENTITY_ID"),
        grid_power_sign_convention=os.getenv("GRID_POWER_SIGN", "unknown"),
        battery_power_sign_convention=os.getenv("BATTERY_POWER_SIGN", "unknown"),
        sign_convention_confidence=os.getenv(
            "SIGN_CONVENTION_CONFIDENCE", "unconfirmed"
        ),
        sign_convention_supporting_samples=int(
            os.getenv("SIGN_CONVENTION_SUPPORTING_SAMPLES", "0")
        ),
        balance_tolerance_w=float(os.getenv("BALANCE_TOLERANCE_W", "250")),
        ev_charging_active_entity_id=_optional_env("EV_CHARGING_ACTIVE_ENTITY_ID"),
        ev_charging_power_entity_id=_optional_env("EV_CHARGING_POWER_ENTITY_ID"),
        ev_plugged_in_entity_id=_optional_env("EV_PLUGGED_IN_ENTITY_ID"),
        ev_energy_required_entity_id=_optional_env("EV_ENERGY_REQUIRED_ENTITY_ID"),
        ev_ready_by_entity_id=_optional_env("EV_READY_BY_ENTITY_ID"),
        ev_inference_enabled=_env_bool("EV_INFERENCE_ENABLED"),
        ev_plausible_power_min_w=float(os.getenv("EV_PLAUSIBLE_POWER_MIN_W", "1800")),
        ev_plausible_power_max_w=float(os.getenv("EV_PLAUSIBLE_POWER_MAX_W", "12000")),
        ev_minimum_session_minutes=int(os.getenv("EV_MINIMUM_SESSION_MINUTES", "30")),
        forecast_retention_days=int(os.getenv("FORECAST_RETENTION_DAYS", "365")),
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


def load_sign_settings(env_file: Path | None = Path(".env")) -> dict[str, str | float]:
    """Load non-secret flow settings for local inspection tools."""
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    return {
        "grid_power_sign": os.getenv("GRID_POWER_SIGN", "unknown"),
        "battery_power_sign": os.getenv("BATTERY_POWER_SIGN", "unknown"),
        "confidence": os.getenv("SIGN_CONVENTION_CONFIDENCE", "unconfirmed"),
        "supporting_samples": int(os.getenv("SIGN_CONVENTION_SUPPORTING_SAMPLES", "0")),
        "balance_tolerance_w": float(os.getenv("BALANCE_TOLERANCE_W", "250")),
    }
