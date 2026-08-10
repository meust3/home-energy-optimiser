"""Complete portable SQLAlchemy schema for history, forecasts, and audits."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from energy_optimizer.timestamps import AwareDateTime

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("idx_observations_health_time", "is_healthy", "slot_utc"),
        Index(
            "idx_observations_telemetry_health_time", "telemetry_is_healthy", "slot_utc"
        ),
        Index(
            "idx_observations_baseline_training",
            "baseline_training_eligible",
            "slot_utc",
        ),
    )

    slot_utc: Mapped[datetime] = mapped_column(AwareDateTime(), primary_key=True)
    collected_at_utc: Mapped[datetime] = mapped_column(
        "observed_at_utc", AwareDateTime()
    )
    observed_at_local: Mapped[datetime] = mapped_column(AwareDateTime(utc=False))
    battery_soc_percent: Mapped[float | None] = mapped_column(Float)
    battery_energy_estimate_kwh: Mapped[float | None] = mapped_column(Float)
    battery_power_w: Mapped[float | None] = mapped_column(Float)
    battery_mode: Mapped[str | None] = mapped_column(Text)
    pv_power_w: Mapped[float | None] = mapped_column(Float)
    house_consumption_w: Mapped[float | None] = mapped_column(Float)
    grid_power_w: Mapped[float | None] = mapped_column(Float)
    work_mode: Mapped[str | None] = mapped_column(Text)
    amber_import_price_per_kwh: Mapped[float | None] = mapped_column(Float)
    amber_export_price_per_kwh: Mapped[float | None] = mapped_column(Float)
    amber_price_spike: Mapped[bool | None] = mapped_column(Boolean)
    amber_import_forecast_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    amber_export_forecast_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    solcast_remaining_today_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_tomorrow_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_next_hour_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_this_hour_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_today_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_remaining_today_kwh_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_tomorrow_kwh_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_next_hour_kwh_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_this_hour_kwh_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_today_kwh_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    solcast_power_now_w: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    weather_condition: Mapped[str | None] = mapped_column(Text)
    is_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    health_score: Mapped[int] = mapped_column(Integer, nullable=False)
    health_issues_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    telemetry_is_healthy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    telemetry_health_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    price_is_healthy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    price_health_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    solar_is_healthy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    solar_health_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weather_is_healthy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    weather_health_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    flow_is_healthy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    flow_health_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    health_domains_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    grid_import_power_w: Mapped[float | None] = mapped_column(Float)
    grid_export_power_w: Mapped[float | None] = mapped_column(Float)
    battery_charge_power_w: Mapped[float | None] = mapped_column(Float)
    battery_discharge_power_w: Mapped[float | None] = mapped_column(Float)
    solar_to_house_power_w: Mapped[float | None] = mapped_column(Float)
    solar_to_battery_power_w: Mapped[float | None] = mapped_column(Float)
    solar_to_grid_power_w: Mapped[float | None] = mapped_column(Float)
    battery_to_house_power_w: Mapped[float | None] = mapped_column(Float)
    battery_to_grid_power_w: Mapped[float | None] = mapped_column(Float)
    grid_to_house_power_w: Mapped[float | None] = mapped_column(Float)
    grid_to_battery_power_w: Mapped[float | None] = mapped_column(Float)
    balance_residual_w: Mapped[float | None] = mapped_column(Float)
    sign_convention_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="unconfirmed"
    )
    sign_convention_confidence: Mapped[str] = mapped_column(
        Text, nullable=False, default="unconfirmed"
    )
    sign_supporting_sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    ev_charging_active: Mapped[bool | None] = mapped_column(Boolean)
    ev_power_w: Mapped[float | None] = mapped_column(Float)
    ev_session_id: Mapped[str | None] = mapped_column(Text)
    ev_energy_required_kwh: Mapped[float | None] = mapped_column(Float)
    ev_ready_by_local: Mapped[datetime | None] = mapped_column(AwareDateTime(utc=False))
    ev_source: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    ev_detection_confidence: Mapped[str] = mapped_column(
        Text, nullable=False, default="unconfirmed"
    )
    baseline_house_consumption_w: Mapped[float | None] = mapped_column(Float)
    baseline_training_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    baseline_exclusion_reason: Mapped[str | None] = mapped_column(Text)
    event_labels_json: Mapped[Any] = mapped_column(
        JSON_TYPE, nullable=False, default=lambda: ["unknown"]
    )
    event_label_confidence: Mapped[str] = mapped_column(
        Text, nullable=False, default="unconfirmed"
    )
    event_label_evidence_json: Mapped[Any] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    derivation_model_version: Mapped[str | None] = mapped_column(Text)
    reprocessed_at_utc: Mapped[datetime | None] = mapped_column(AwareDateTime())
    derivation_metadata_json: Mapped[Any | None] = mapped_column(JSON_TYPE)
    originally_legacy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    forecast_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    horizon_start_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    horizon_end_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    __table_args__ = (
        Index("idx_forecast_runs_type_created", "forecast_type", "created_at_utc"),
    )


class ForecastPoint(Base):
    __tablename__ = "forecast_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id"), nullable=False
    )
    period_start_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    period_end_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, nullable=False)
    lower_value: Mapped[float | None] = mapped_column(Float)
    upper_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    actual_value: Mapped[float | None] = mapped_column(Float)
    error_value: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    __table_args__ = (
        Index("idx_forecast_points_run_period", "forecast_run_id", "period_start_utc"),
    )


class ObservationDerivation(Base):
    __tablename__ = "observation_derivations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_utc: Mapped[datetime] = mapped_column(
        ForeignKey("observations.slot_utc"), nullable=False
    )
    derived_at_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    conventions_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    previous_derived_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    result_derived_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    originally_legacy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "slot_utc",
            "model_version",
            "input_fingerprint",
            name="uq_derivation_business_key",
        ),
        Index("idx_derivations_slot", "slot_utc", "derived_at_utc"),
    )


class EVSessionAnnotation(Base):
    __tablename__ = "ev_session_annotations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    annotation_timestamp_utc: Mapped[datetime] = mapped_column(
        AwareDateTime(), nullable=False
    )
    range_start_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    range_end_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    affected_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    previous_eligibility_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    new_eligibility_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)
    annotation_source: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        Index("idx_ev_annotations_session", "session_id", "annotation_timestamp_utc"),
    )


class EVSessionAnnotationRow(Base):
    __tablename__ = "ev_session_annotation_rows"
    annotation_id: Mapped[int] = mapped_column(
        ForeignKey("ev_session_annotations.id"), primary_key=True
    )
    slot_utc: Mapped[datetime] = mapped_column(
        ForeignKey("observations.slot_utc"), primary_key=True
    )
    previous_state_json: Mapped[Any] = mapped_column(JSON_TYPE, nullable=False)


class MigrationProgress(Base):
    __tablename__ = "migration_progress"
    migration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_business_key: Mapped[str | None] = mapped_column(Text)
    rows_copied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at_utc: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
