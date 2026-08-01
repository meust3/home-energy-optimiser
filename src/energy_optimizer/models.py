"""Typed domain models for collection, health, persistence, and forecasting."""

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class HomeAssistantState(BaseModel):
    entity_id: str
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    last_changed: datetime
    last_updated: datetime

    @field_validator("last_changed", "last_updated")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value


class HealthIssue(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"] = "error"
    entity_id: str | None = None
    deduction: int = Field(ge=0, le=100)


HealthUse = Literal["display", "load_profile", "grid_charge", "battery_export"]


class HealthDomain(BaseModel):
    is_healthy: bool
    score: int = Field(ge=0, le=100)
    issues: list[HealthIssue] = Field(default_factory=list)
    required_for: list[HealthUse] = Field(default_factory=list)


class DataHealth(BaseModel):
    telemetry: HealthDomain
    price: HealthDomain
    solar: HealthDomain
    weather: HealthDomain
    overall: HealthDomain

    @computed_field
    @property
    def is_healthy(self) -> bool:
        """Backward-compatible display summary derived from overall health."""
        return self.overall.is_healthy

    @computed_field
    @property
    def health_score(self) -> int:
        """Backward-compatible display score derived from overall health."""
        return self.overall.score

    @computed_field
    @property
    def issues(self) -> list[HealthIssue]:
        """Backward-compatible display issues derived from overall health."""
        return self.overall.issues


class AmberPriceInterval(BaseModel):
    duration: int | float | str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    per_kwh: float | None = None
    spot_per_kwh: float | None = None
    renewables: float | None = None
    descriptor: str | None = None
    spike_status: str | bool | None = None


class SolarForecastSummary(BaseModel):
    estimate: float | None = None
    estimate10: float | None = None
    estimate90: float | None = None


class LoadProfilePoint(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    slot_index: int = Field(ge=0, lt=288)
    estimated_power_kw: float = Field(ge=0)
    sample_count: int = Field(ge=0)
    source: Literal["history", "fallback"]
    explanation: str


class CollectorConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ha_url: str
    ha_token: str = Field(repr=False, exclude=True)
    timezone: str = "Australia/Brisbane"
    database_path: Path = Path("data/energy_history.db")
    collection_interval_seconds: int = Field(default=300, gt=0)
    usable_battery_capacity_kwh: float = Field(default=40.0, gt=0)
    maximum_plausible_inverter_power_w: float = Field(default=15000.0, gt=0)
    live_power_freshness_minutes: int = Field(default=5, gt=0)
    battery_soc_freshness_minutes: int = Field(default=10, gt=0)
    amber_current_price_freshness_minutes: int = Field(default=10, gt=0)
    amber_forecast_freshness_minutes: int = Field(default=60, gt=0)
    solcast_forecast_freshness_minutes: int = Field(default=360, gt=0)
    weather_freshness_minutes: int = Field(default=60, gt=0)
    weather_temperature_entity_id: str | None = None
    weather_condition_entity_id: str | None = None
    conservative_fallback_household_load_kw: float = Field(default=2.0, ge=0)
    load_profile_minimum_samples: int = Field(default=3, gt=0)
    request_timeout_seconds: float = Field(default=10.0, gt=0)


class EnergyObservation(BaseModel):
    slot_utc: datetime
    observed_at_utc: datetime
    observed_at_local: datetime
    battery_soc_percent: float | None = None
    battery_energy_estimate_kwh: float | None = None
    battery_power_w: float | None = None
    battery_mode: str | None = None
    pv_power_w: float | None = None
    house_consumption_w: float | None = None
    grid_power_w: float | None = None
    work_mode: str | None = None
    amber_import_price_per_kwh: float | None = None
    amber_export_price_per_kwh: float | None = None
    amber_price_spike: bool | None = None
    amber_import_forecast: list[AmberPriceInterval] = Field(default_factory=list)
    amber_export_forecast: list[AmberPriceInterval] = Field(default_factory=list)
    solcast_remaining_today: SolarForecastSummary | None = None
    solcast_tomorrow: SolarForecastSummary | None = None
    solcast_next_hour: SolarForecastSummary | None = None
    solcast_this_hour: SolarForecastSummary | None = None
    solcast_today: SolarForecastSummary | None = None
    solcast_power_now_w: float | None = None
    temperature_c: float | None = None
    weather_condition: str | None = None
    data_health: DataHealth

    @field_validator("slot_utc", "observed_at_utc", "observed_at_local")
    @classmethod
    def observation_times_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation datetimes must be timezone-aware")
        return value
