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


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def _weekend_days() -> set[int]:
    raw = os.getenv("DEMAND_WEEKEND_DAYS", "5,6")
    try:
        days = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError as exc:
        raise ConfigurationError(
            "DEMAND_WEEKEND_DAYS must be comma-separated integers"
        ) from exc
    if not days or any(day < 0 or day > 6 for day in days):
        raise ConfigurationError("DEMAND_WEEKEND_DAYS values must be between 0 and 6")
    return days


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
        ev_vehicle_enabled=_env_bool("EV_VEHICLE_ENABLED"),
        ev_vehicle_charging_entity_id=_optional_env("EV_CHARGING_ENTITY"),
        ev_vehicle_plugged_entity_id=_optional_env("EV_PLUGGED_ENTITY"),
        ev_vehicle_online_entity_id=_optional_env("EV_ONLINE_ENTITY"),
        ev_vehicle_soc_entity_id=_optional_env("EV_SOC_ENTITY"),
        ev_vehicle_battery_power_entity_id=_optional_env("EV_BATTERY_POWER_ENTITY"),
        ev_vehicle_telemetry_updated_entity_id=_optional_env(
            "EV_TELEMETRY_UPDATED_ENTITY"
        ),
        ev_vehicle_location_entity_id=_optional_env("EV_LOCATION_ENTITY"),
        ev_home_state=os.getenv("EV_HOME_STATE", "home").strip() or "home",
        ev_telemetry_stale_seconds=_positive_env_int("EV_TELEMETRY_STALE_SECONDS", 900),
        forecast_retention_days=int(os.getenv("FORECAST_RETENTION_DAYS", "365")),
        minimum_soc_percent=float(os.getenv("MINIMUM_SOC_PERCENT", "20")),
        emergency_reserve_kwh=float(os.getenv("EMERGENCY_RESERVE_KWH", "6")),
        reserve_history_days=int(os.getenv("RESERVE_HISTORY_DAYS", "28")),
        reserve_recent_days=int(os.getenv("RESERVE_RECENT_DAYS", "7")),
        reserve_max_horizon_hours=int(os.getenv("RESERVE_MAX_HORIZON_HOURS", "24")),
        reserve_uncertainty_ratio=float(os.getenv("RESERVE_UNCERTAINTY_RATIO", "0.20")),
        battery_charge_efficiency=float(os.getenv("BATTERY_CHARGE_EFFICIENCY", "0.95")),
        reserve_max_charge_power_w=float(
            os.getenv("RESERVE_MAX_CHARGE_POWER_W", "9999")
        ),
        reserve_fallback_mode=os.getenv("RESERVE_FALLBACK_MODE", "banded"),
        reserve_fallback_overnight_kw=float(
            os.getenv("RESERVE_FALLBACK_OVERNIGHT_KW", "2.0")
        ),
        reserve_fallback_morning_kw=float(
            os.getenv("RESERVE_FALLBACK_MORNING_KW", "2.5")
        ),
        reserve_fallback_daytime_kw=float(
            os.getenv("RESERVE_FALLBACK_DAYTIME_KW", "2.0")
        ),
        reserve_fallback_evening_kw=float(
            os.getenv("RESERVE_FALLBACK_EVENING_KW", "3.0")
        ),
        reserve_fallback_late_evening_kw=float(
            os.getenv("RESERVE_FALLBACK_LATE_EVENING_KW", "2.5")
        ),
        demand_tier2_minimum_samples=int(
            os.getenv("DEMAND_TIER2_MINIMUM_SAMPLES", "3")
        ),
        demand_tier3_minimum_samples=int(
            os.getenv("DEMAND_TIER3_MINIMUM_SAMPLES", "3")
        ),
        demand_tier4_minimum_samples=int(
            os.getenv("DEMAND_TIER4_MINIMUM_SAMPLES", "6")
        ),
        demand_tier4_lookback_days=int(os.getenv("DEMAND_TIER4_LOOKBACK_DAYS", "7")),
        demand_weekend_days=_weekend_days(),
        demand_complete_period_fraction=float(
            os.getenv("DEMAND_COMPLETE_PERIOD_FRACTION", "0.90")
        ),
        demand_low_ceiling_complete_days=int(
            os.getenv("DEMAND_LOW_CEILING_COMPLETE_DAYS", "2")
        ),
        demand_medium_low_ceiling_complete_days=int(
            os.getenv("DEMAND_MEDIUM_LOW_CEILING_COMPLETE_DAYS", "7")
        ),
        demand_weak_tier_share_ceiling=float(
            os.getenv("DEMAND_WEAK_TIER_SHARE_CEILING", "0.50")
        ),
        cheap_import_price_per_kwh=float(
            os.getenv("CHEAP_IMPORT_PRICE_PER_KWH", "0.15")
        ),
        solar_surplus_threshold_kwh=float(
            os.getenv("SOLAR_SURPLUS_THRESHOLD_KWH", "1.0")
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


def load_database_url(env_file: Path | None = Path(".env")) -> str:
    """Load the canonical database URL, retaining the historical path fallback."""
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    path = Path(os.getenv("DATABASE_PATH", "data/energy_history.db"))
    return f"sqlite:///{path.as_posix()}"


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


def load_reserve_config(env_file: Path | None = Path(".env")) -> CollectorConfig:
    """Load local estimator settings without requiring Home Assistant secrets."""
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    return CollectorConfig(
        ha_url="http://read-only.local",
        ha_token="not-used",
        timezone=os.getenv("TIMEZONE", "Australia/Brisbane"),
        database_path=Path(os.getenv("DATABASE_PATH", "data/energy_history.db")),
        usable_battery_capacity_kwh=float(
            os.getenv("USABLE_BATTERY_CAPACITY_KWH", "40")
        ),
        minimum_soc_percent=float(os.getenv("MINIMUM_SOC_PERCENT", "20")),
        emergency_reserve_kwh=float(os.getenv("EMERGENCY_RESERVE_KWH", "6")),
        reserve_history_days=int(os.getenv("RESERVE_HISTORY_DAYS", "28")),
        reserve_recent_days=int(os.getenv("RESERVE_RECENT_DAYS", "7")),
        reserve_max_horizon_hours=int(os.getenv("RESERVE_MAX_HORIZON_HOURS", "24")),
        reserve_uncertainty_ratio=float(os.getenv("RESERVE_UNCERTAINTY_RATIO", "0.20")),
        battery_charge_efficiency=float(os.getenv("BATTERY_CHARGE_EFFICIENCY", "0.95")),
        reserve_max_charge_power_w=float(
            os.getenv("RESERVE_MAX_CHARGE_POWER_W", "9999")
        ),
        reserve_fallback_mode=os.getenv("RESERVE_FALLBACK_MODE", "banded"),
        reserve_fallback_overnight_kw=float(
            os.getenv("RESERVE_FALLBACK_OVERNIGHT_KW", "2.0")
        ),
        reserve_fallback_morning_kw=float(
            os.getenv("RESERVE_FALLBACK_MORNING_KW", "2.5")
        ),
        reserve_fallback_daytime_kw=float(
            os.getenv("RESERVE_FALLBACK_DAYTIME_KW", "2.0")
        ),
        reserve_fallback_evening_kw=float(
            os.getenv("RESERVE_FALLBACK_EVENING_KW", "3.0")
        ),
        reserve_fallback_late_evening_kw=float(
            os.getenv("RESERVE_FALLBACK_LATE_EVENING_KW", "2.5")
        ),
        demand_tier2_minimum_samples=int(
            os.getenv("DEMAND_TIER2_MINIMUM_SAMPLES", "3")
        ),
        demand_tier3_minimum_samples=int(
            os.getenv("DEMAND_TIER3_MINIMUM_SAMPLES", "3")
        ),
        demand_tier4_minimum_samples=int(
            os.getenv("DEMAND_TIER4_MINIMUM_SAMPLES", "6")
        ),
        demand_tier4_lookback_days=int(os.getenv("DEMAND_TIER4_LOOKBACK_DAYS", "7")),
        demand_weekend_days=_weekend_days(),
        demand_complete_period_fraction=float(
            os.getenv("DEMAND_COMPLETE_PERIOD_FRACTION", "0.90")
        ),
        demand_low_ceiling_complete_days=int(
            os.getenv("DEMAND_LOW_CEILING_COMPLETE_DAYS", "2")
        ),
        demand_medium_low_ceiling_complete_days=int(
            os.getenv("DEMAND_MEDIUM_LOW_CEILING_COMPLETE_DAYS", "7")
        ),
        demand_weak_tier_share_ceiling=float(
            os.getenv("DEMAND_WEAK_TIER_SHARE_CEILING", "0.50")
        ),
        cheap_import_price_per_kwh=float(
            os.getenv("CHEAP_IMPORT_PRICE_PER_KWH", "0.15")
        ),
        solar_surplus_threshold_kwh=float(
            os.getenv("SOLAR_SURPLUS_THRESHOLD_KWH", "1.0")
        ),
        conservative_fallback_household_load_kw=float(
            os.getenv("CONSERVATIVE_FALLBACK_HOUSEHOLD_LOAD_KW", "2.0")
        ),
        load_profile_minimum_samples=int(
            os.getenv("LOAD_PROFILE_MINIMUM_SAMPLES", "3")
        ),
    )


def load_reprocessing_config(env_file: Path | None = Path(".env")) -> CollectorConfig:
    """Load non-secret settings for local historical derivation."""
    config = load_reserve_config(env_file)
    config.grid_power_sign_convention = os.getenv("GRID_POWER_SIGN", "unknown")
    config.battery_power_sign_convention = os.getenv("BATTERY_POWER_SIGN", "unknown")
    config.sign_convention_confidence = os.getenv(
        "SIGN_CONVENTION_CONFIDENCE", "unconfirmed"
    )
    config.sign_convention_supporting_samples = int(
        os.getenv("SIGN_CONVENTION_SUPPORTING_SAMPLES", "0")
    )
    config.balance_tolerance_w = float(os.getenv("BALANCE_TOLERANCE_W", "250"))
    return config
