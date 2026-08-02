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


HealthUse = Literal[
    "display", "load_profile", "grid_charge", "battery_export", "derived_flow"
]


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
    flow: HealthDomain
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
    """Solcast energy summary normalized to kWh with its source preserved."""

    estimate_kwh: float | None = None
    estimate10_kwh: float | None = None
    estimate90_kwh: float | None = None
    source_estimate: float | None = None
    source_estimate10: float | None = None
    source_estimate90: float | None = None
    source_unit: str | None = None
    conversion_status: Literal[
        "native_kwh", "converted_from_wh", "unit_missing", "unit_unsupported"
    ]


class LoadProfilePoint(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    slot_index: int = Field(ge=0, lt=288)
    estimated_power_kw: float = Field(ge=0)
    sample_count: int = Field(ge=0)
    source: Literal["history", "fallback"]
    explanation: str


GridSignConvention = Literal["positive_import", "positive_export", "unknown"]
BatterySignConvention = Literal["positive_charge", "positive_discharge", "unknown"]
SignConventionStatus = Literal["confirmed", "unconfirmed", "unavailable"]
ConfidenceLevel = Literal["high", "medium", "low", "unconfirmed"]
EVSource = Literal["charger", "home_assistant_helper", "inferred", "none"]
EventLabel = Literal[
    "normal_self_consumption",
    "solar_battery_charge",
    "grid_battery_charge",
    "solar_export",
    "battery_export",
    "ev_charge_solar",
    "ev_charge_grid",
    "ev_charge_mixed",
    "unknown",
]
ForecastType = Literal[
    "solar_power",
    "household_load",
    "baseline_household_load",
    "battery_soc",
    "grid_import",
    "grid_export",
    "buy_price",
    "sell_price",
]


class EnergyFlow(BaseModel):
    raw_pv_power_w: float | None = None
    raw_house_consumption_w: float | None = None
    raw_grid_power_w: float | None = None
    raw_battery_power_w: float | None = None
    grid_import_power_w: float | None = None
    grid_export_power_w: float | None = None
    battery_charge_power_w: float | None = None
    battery_discharge_power_w: float | None = None
    solar_to_house_power_w: float | None = None
    solar_to_battery_power_w: float | None = None
    solar_to_grid_power_w: float | None = None
    battery_to_house_power_w: float | None = None
    battery_to_grid_power_w: float | None = None
    grid_to_house_power_w: float | None = None
    grid_to_battery_power_w: float | None = None
    balance_residual_w: float | None = None
    sign_convention_status: SignConventionStatus
    sign_convention_confidence: ConfidenceLevel
    supporting_sample_count: int = Field(default=0, ge=0)


class ForecastPoint(BaseModel):
    period_start_utc: datetime
    period_end_utc: datetime
    expected_value: float
    lower_value: float | None = None
    upper_value: float | None = None
    unit: str
    actual_value: float | None = None
    error_value: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("period_start_utc", "period_end_utc")
    @classmethod
    def point_times_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast point datetimes must be timezone-aware")
        return value


class ForecastRun(BaseModel):
    id: int | None = None
    created_at_utc: datetime
    forecast_type: ForecastType
    source: str
    horizon_start_utc: datetime
    horizon_end_utc: datetime
    model_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    points: list[ForecastPoint] = Field(default_factory=list)

    @field_validator("created_at_utc", "horizon_start_utc", "horizon_end_utc")
    @classmethod
    def forecast_times_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast datetimes must be timezone-aware")
        return value


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
    grid_power_sign_convention: GridSignConvention = "unknown"
    battery_power_sign_convention: BatterySignConvention = "unknown"
    sign_convention_confidence: ConfidenceLevel = "unconfirmed"
    sign_convention_supporting_samples: int = Field(default=0, ge=0)
    balance_tolerance_w: float = Field(default=250.0, ge=0)
    ev_charging_active_entity_id: str | None = None
    ev_charging_power_entity_id: str | None = None
    ev_plugged_in_entity_id: str | None = None
    ev_energy_required_entity_id: str | None = None
    ev_ready_by_entity_id: str | None = None
    ev_inference_enabled: bool = False
    ev_plausible_power_min_w: float = Field(default=1800.0, ge=0)
    ev_plausible_power_max_w: float = Field(default=12000.0, gt=0)
    ev_minimum_session_minutes: int = Field(default=30, gt=0)
    forecast_retention_days: int = Field(default=365, gt=0)
    minimum_soc_percent: float = Field(default=20.0, ge=0, le=100)
    emergency_reserve_kwh: float = Field(default=6.0, ge=0)
    reserve_history_days: int = Field(default=28, gt=0)
    reserve_recent_days: int = Field(default=7, gt=0)
    reserve_max_horizon_hours: int = Field(default=24, gt=0)
    reserve_uncertainty_ratio: float = Field(default=0.20, ge=0)
    reserve_fallback_mode: Literal["banded", "flat"] = "banded"
    reserve_fallback_overnight_kw: float = Field(default=2.0, ge=0)
    reserve_fallback_morning_kw: float = Field(default=2.5, ge=0)
    reserve_fallback_daytime_kw: float = Field(default=2.0, ge=0)
    reserve_fallback_evening_kw: float = Field(default=3.0, ge=0)
    reserve_fallback_late_evening_kw: float = Field(default=2.5, ge=0)
    demand_tier2_minimum_samples: int = Field(default=3, gt=0)
    demand_tier3_minimum_samples: int = Field(default=3, gt=0)
    demand_tier4_minimum_samples: int = Field(default=6, gt=0)
    demand_tier4_lookback_days: int = Field(default=7, gt=0)
    demand_weekend_days: set[int] = Field(default_factory=lambda: {5, 6})
    cheap_import_price_per_kwh: float = 0.15
    solar_surplus_threshold_kwh: float = Field(default=1.0, ge=0)
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
    solcast_remaining_today_kwh: SolarForecastSummary | None = None
    solcast_tomorrow_kwh: SolarForecastSummary | None = None
    solcast_next_hour_kwh: SolarForecastSummary | None = None
    solcast_this_hour_kwh: SolarForecastSummary | None = None
    solcast_today_kwh: SolarForecastSummary | None = None
    solcast_power_now_w: float | None = None
    temperature_c: float | None = None
    weather_condition: str | None = None
    energy_flow: EnergyFlow
    ev_charging_active: bool | None = None
    ev_power_w: float | None = None
    ev_session_id: str | None = None
    ev_energy_required_kwh: float | None = None
    ev_ready_by_local: datetime | None = None
    ev_source: EVSource = "none"
    ev_detection_confidence: ConfidenceLevel = "unconfirmed"
    baseline_house_consumption_w: float | None = None
    baseline_training_eligible: bool = True
    baseline_exclusion_reason: str | None = None
    event_labels: list[EventLabel] = Field(default_factory=lambda: ["unknown"])
    event_label_confidence: ConfidenceLevel = "unconfirmed"
    event_label_evidence: dict[str, Any] = Field(default_factory=dict)
    data_health: DataHealth

    @field_validator("slot_utc", "observed_at_utc", "observed_at_local")
    @classmethod
    def observation_times_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation datetimes must be timezone-aware")
        return value
