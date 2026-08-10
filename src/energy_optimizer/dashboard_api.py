"""Typed, bounded, read-only query services for the Ingress dashboard."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from energy_optimizer.db.migrations import current_revision, expected_revision
from energy_optimizer.history_analysis import (
    calculate_gap_report,
    summarize_health_issues,
)
from energy_optimizer.persistence import ApplicationRepository, open_repository

MAX_RANGE = timedelta(days=31)
MAX_RETURNED_POINTS = 2500
MAX_OBSERVATION_ROWS = 9000
RANGE_DURATIONS = {
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "48h": timedelta(hours=48),
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "30d": timedelta(days=30),
}
RESOLUTION_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
OBSERVATION_COLUMNS = (
    "slot_utc",
    "observed_at_local",
    "house_consumption_w",
    "baseline_house_consumption_w",
    "pv_power_w",
    "battery_soc_percent",
    "battery_charge_power_w",
    "battery_discharge_power_w",
    "grid_import_power_w",
    "grid_export_power_w",
    "amber_import_price_per_kwh",
    "amber_export_price_per_kwh",
    "telemetry_is_healthy",
    "telemetry_health_score",
    "price_is_healthy",
    "price_health_score",
    "solar_is_healthy",
    "solar_health_score",
    "weather_is_healthy",
    "weather_health_score",
    "flow_is_healthy",
    "flow_health_score",
    "is_healthy",
    "health_score",
    "health_domains_json",
    "baseline_training_eligible",
    "baseline_exclusion_reason",
    "ev_power_w",
    "ev_source",
    "sign_convention_confidence",
    "balance_residual_w",
)


class ApiModel(BaseModel):
    """Base contract that rejects non-JSON floating-point values."""

    model_config = ConfigDict(allow_inf_nan=False)


class StatusResponse(ApiModel):
    app_version: str
    overall_status: str
    collector_status: str
    database_status: str
    home_assistant_status: str
    dashboard_status: Literal["healthy"] = "healthy"
    latest_successful_collection_utc: datetime | None
    latest_observation_slot_utc: datetime | None
    observation_age_seconds: float | None
    database_schema_revision: str | None
    expected_schema_revision: str
    read_only_mode: Literal[True] = True
    command_execution_enabled: Literal[False] = False


class HealthDomain(ApiModel):
    healthy: bool
    score_percent: float | None


class LiveResponse(ApiModel):
    available: bool
    slot_utc: datetime | None = None
    collected_at_utc: datetime | None = None
    battery_soc_percent: float | None = None
    battery_energy_estimate_kwh: float | None = None
    pv_power_w: float | None = None
    house_consumption_w: float | None = None
    baseline_house_consumption_w: float | None = None
    grid_power_w: float | None = None
    grid_import_power_w: float | None = None
    grid_export_power_w: float | None = None
    battery_power_w: float | None = None
    battery_charge_power_w: float | None = None
    battery_discharge_power_w: float | None = None
    amber_buy_price_aud_per_kwh: float | None = None
    amber_sell_price_aud_per_kwh: float | None = None
    battery_mode: str | None = None
    work_mode: str | None = None
    energy_balance_residual_w: float | None = None
    sign_convention_confidence: str | None = None
    event_labels: list[str] = Field(default_factory=list)
    telemetry_health: HealthDomain | None = None
    price_health: HealthDomain | None = None
    solar_health: HealthDomain | None = None
    flow_health: HealthDomain | None = None
    overall_health: HealthDomain | None = None
    ev_power_w: float | None = None
    independent_ev_telemetry_available: bool = False
    ev_contamination_warning: bool = True


class TimeseriesPoint(ApiModel):
    timestamp_utc: datetime
    has_observation: bool
    healthy: bool | None
    house_consumption_w: float | None
    baseline_house_consumption_w: float | None
    pv_power_w: float | None
    battery_soc_percent: float | None
    battery_charge_power_w: float | None
    battery_discharge_power_w: float | None
    grid_import_power_w: float | None
    grid_export_power_w: float | None
    amber_buy_price_aud_per_kwh: float | None
    amber_sell_price_aud_per_kwh: float | None


class TimeseriesResponse(ApiModel):
    requested_start_utc: datetime
    requested_end_utc: datetime
    requested_resolution: str
    actual_resolution: str
    point_count: int
    expected_five_minute_slots: int
    collected_slots: int
    missing_slot_count: int
    coverage_percent: float
    points: list[TimeseriesPoint]


class ForecastRunSummary(ApiModel):
    forecast_run_id: int
    created_at_utc: datetime
    forecast_type: str
    source: str
    horizon_start_utc: datetime
    horizon_end_utc: datetime
    model_version: str
    forecast_point_count: int
    actual_point_count: int
    comparison_ready: bool


class ForecastRunsResponse(ApiModel):
    runs: list[ForecastRunSummary]
    empty: bool


class ForecastComparisonPoint(ApiModel):
    period_start_utc: datetime
    period_end_utc: datetime
    expected_value: float
    lower_value: float | None
    upper_value: float | None
    actual_value: float | None
    error_value: float | None
    missing_actual: bool


class ForecastComparisonResponse(ApiModel):
    available: bool
    message: str | None = None
    forecast_run_id: int | None = None
    forecast_type: str | None = None
    source: str | None = None
    model_version: str | None = None
    created_at_utc: datetime | None = None
    horizon_start_utc: datetime | None = None
    horizon_end_utc: datetime | None = None
    unit: str | None = None
    sample_count: int = 0
    missing_actual_count: int = 0
    mae: float | None = None
    bias: float | None = None
    points: list[ForecastComparisonPoint] = Field(default_factory=list)


class ReserveResponse(ApiModel):
    available: bool
    message: str | None = None
    forecast_run_id: int | None = None
    calculation_timestamp_utc: datetime | None = None
    state_source: str | None = None
    battery_soc_percent: float | None = None
    battery_energy_estimate_kwh: float | None = None
    expected_household_demand_kwh: float | None = None
    expected_ev_demand_kwh: float | None = None
    gross_reserve_requirement_kwh: float | None = None
    capacity_capped_reserve_kwh: float | None = None
    potentially_tradable_energy_kwh: float | None = None
    confidence: dict[str, Any] | None = None
    readiness: bool | None = None
    horizon_start_utc: datetime | None = None
    horizon_end_utc: datetime | None = None
    forecast_tier_counts: dict[str, int] = Field(default_factory=dict)
    persisted_fields: list[str] = Field(default_factory=list)
    command_issued: Literal[False] = False


class DataQualityResponse(ApiModel):
    range_start_utc: datetime
    range_end_utc: datetime
    total_observations: int
    expected_five_minute_slots: int
    collected_slots: int
    missing_slots: int
    coverage_percent: float
    longest_gap_minutes: int
    longest_gap_start_utc: datetime | None
    longest_gap_end_utc: datetime | None
    first_gap: dict[str, Any] | None
    last_gap: dict[str, Any] | None
    domain_health: dict[str, dict[str, Any]]
    complete_calendar_days: int
    complete_overnight_periods: int
    eligible_baseline_rows: int
    ineligible_baseline_rows_by_reason: dict[str, int]
    forecast_tier_usage: dict[str, int]
    forecast_tier_share: dict[str, float]
    independent_ev_telemetry_available: bool
    ev_contamination_warning: bool
    sign_convention_confidence: dict[str, int]
    average_absolute_balance_residual_w: float | None


class DashboardQueryError(ValueError):
    """Stable client-safe query validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DashboardService:
    """Open short-lived repositories and expose only bounded presentation queries."""

    def __init__(
        self, database_url: str, health: Any, repository_factory=open_repository
    ):
        self.database_url = database_url
        self.health = health
        self.repository_factory = repository_factory

    @contextmanager
    def _repository(self):
        repository: ApplicationRepository = self.repository_factory(self.database_url)
        try:
            yield repository
        finally:
            repository.close()

    def status(self) -> StatusResponse:
        _, health = self.health.response()
        revision = None
        latest = None
        database_status = str(health["database"])
        try:
            with self._repository() as repository:
                repository.ping()
                revision = current_revision(repository.engine)
                latest = repository.latest_observation_read_only()
        except Exception:
            database_status = "unhealthy"
        healthy = (
            health["collector"] == "healthy"
            and database_status == "healthy"
            and health["home_assistant"] == "healthy"
        )
        latest_slot = health["last_slot_utc"]
        latest_collection = health["last_successful_collection_utc"]
        observation_age = health["observation_age_seconds"]
        if latest is not None:
            latest_slot = latest_slot or _utc(latest["slot_utc"])
            latest_collection = latest_collection or _utc(latest["observed_at_utc"])
            if observation_age is None:
                observation_age = max(
                    (datetime.now(UTC) - _utc(latest["slot_utc"])).total_seconds(), 0
                )
        return StatusResponse(
            app_version=str(health["version"]),
            overall_status="healthy" if healthy else "unhealthy",
            collector_status=str(health["collector"]),
            database_status=database_status,
            home_assistant_status=str(health["home_assistant"]),
            latest_successful_collection_utc=latest_collection,
            latest_observation_slot_utc=latest_slot,
            observation_age_seconds=observation_age,
            database_schema_revision=revision,
            expected_schema_revision=expected_revision(),
        )

    def live(self) -> LiveResponse:
        with self._repository() as repository:
            row = repository.latest_observation_read_only()
        if row is None:
            return LiveResponse(available=False)
        direct_ev = (
            row.get("ev_source") == "charger" and row.get("ev_power_w") is not None
        )
        return LiveResponse(
            available=True,
            slot_utc=_utc(row.get("slot_utc")),
            collected_at_utc=_utc(row.get("observed_at_utc")),
            battery_soc_percent=_number(row.get("battery_soc_percent")),
            battery_energy_estimate_kwh=_number(row.get("battery_energy_estimate_kwh")),
            pv_power_w=_number(row.get("pv_power_w")),
            house_consumption_w=_number(row.get("house_consumption_w")),
            baseline_house_consumption_w=_number(
                row.get("baseline_house_consumption_w")
            ),
            grid_power_w=_number(row.get("grid_power_w")),
            grid_import_power_w=_number(row.get("grid_import_power_w")),
            grid_export_power_w=_number(row.get("grid_export_power_w")),
            battery_power_w=_number(row.get("battery_power_w")),
            battery_charge_power_w=_number(row.get("battery_charge_power_w")),
            battery_discharge_power_w=_number(row.get("battery_discharge_power_w")),
            amber_buy_price_aud_per_kwh=_number(row.get("amber_import_price_per_kwh")),
            amber_sell_price_aud_per_kwh=_number(row.get("amber_export_price_per_kwh")),
            battery_mode=row.get("battery_mode"),
            work_mode=row.get("work_mode"),
            energy_balance_residual_w=_number(row.get("balance_residual_w")),
            sign_convention_confidence=row.get("sign_convention_confidence"),
            event_labels=[str(value) for value in (row.get("event_labels_json") or [])],
            telemetry_health=_domain(row, "telemetry"),
            price_health=_domain(row, "price"),
            solar_health=_domain(row, "solar"),
            flow_health=_domain(row, "flow"),
            overall_health=HealthDomain(
                healthy=bool(row.get("is_healthy")),
                score_percent=_number(row.get("health_score")),
            ),
            ev_power_w=_number(row.get("ev_power_w")) if direct_ev else None,
            independent_ev_telemetry_available=direct_ev,
            ev_contamination_warning=not direct_ev,
        )

    def timeseries(
        self,
        *,
        range_name: str = "24h",
        start: datetime | None = None,
        end: datetime | None = None,
        resolution: str = "auto",
        now: datetime | None = None,
    ) -> TimeseriesResponse:
        start_utc, end_utc = resolve_window(
            range_name=range_name, start=start, end=end, now=now
        )
        actual_resolution = resolve_resolution(start_utc, end_utc, resolution)
        with self._repository() as repository:
            rows = repository.dashboard_observation_rows_read_only(
                start=start_utc,
                end=end_utc,
                columns=OBSERVATION_COLUMNS,
                limit=MAX_OBSERVATION_ROWS,
            )
        gap = calculate_gap_report(
            [_utc(row["slot_utc"]) for row in rows], start=start_utc, end=end_utc
        )
        points = aggregate_timeseries(
            rows, start=start_utc, end=end_utc, resolution=actual_resolution
        )
        return TimeseriesResponse(
            requested_start_utc=start_utc,
            requested_end_utc=end_utc,
            requested_resolution=resolution,
            actual_resolution=actual_resolution,
            point_count=len(points),
            expected_five_minute_slots=gap["expected_slots"],
            collected_slots=gap["collected_slots"],
            missing_slot_count=gap["missing_slots"],
            coverage_percent=gap["coverage_percent"],
            points=points,
        )

    def forecast_runs(
        self,
        *,
        forecast_type: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        limit: int = 25,
    ) -> ForecastRunsResponse:
        with self._repository() as repository:
            rows = repository.forecast_run_summaries_read_only(
                forecast_type=forecast_type,
                after=after,
                before=before,
                limit=limit,
            )
        runs = [
            ForecastRunSummary(
                forecast_run_id=row["id"],
                created_at_utc=_utc(row["created_at_utc"]),
                forecast_type=row["forecast_type"],
                source=row["source"],
                horizon_start_utc=_utc(row["horizon_start_utc"]),
                horizon_end_utc=_utc(row["horizon_end_utc"]),
                model_version=row["model_version"],
                forecast_point_count=row["point_count"],
                actual_point_count=row["actual_point_count"],
                comparison_ready=row["point_count"] > 0,
            )
            for row in rows
        ]
        return ForecastRunsResponse(runs=runs, empty=not runs)

    def forecast_comparison(
        self,
        *,
        forecast_run_id: int | None = None,
        forecast_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = MAX_RETURNED_POINTS,
    ) -> ForecastComparisonResponse:
        with self._repository() as repository:
            run = repository.forecast_comparison_read_only(
                forecast_run_id=forecast_run_id,
                forecast_type=forecast_type,
                start=start,
                end=end,
                limit=limit,
            )
        if run is None or not run["points"]:
            return ForecastComparisonResponse(
                available=False,
                message="No persisted forecast series is available for this period.",
                forecast_run_id=forecast_run_id,
                forecast_type=forecast_type,
            )
        points = []
        errors = []
        for row in run["points"]:
            error = _number(row.get("error_value"))
            if error is not None:
                errors.append(error)
            actual = _number(row.get("actual_value"))
            points.append(
                ForecastComparisonPoint(
                    period_start_utc=_utc(row["period_start_utc"]),
                    period_end_utc=_utc(row["period_end_utc"]),
                    expected_value=float(row["expected_value"]),
                    lower_value=_number(row.get("lower_value")),
                    upper_value=_number(row.get("upper_value")),
                    actual_value=actual,
                    error_value=error,
                    missing_actual=actual is None,
                )
            )
        return ForecastComparisonResponse(
            available=True,
            forecast_run_id=run["id"],
            forecast_type=run["forecast_type"],
            source=run["source"],
            model_version=run["model_version"],
            created_at_utc=_utc(run["created_at_utc"]),
            horizon_start_utc=_utc(run["horizon_start_utc"]),
            horizon_end_utc=_utc(run["horizon_end_utc"]),
            unit=run["points"][0]["unit"],
            sample_count=len(errors),
            missing_actual_count=len(points) - len(errors),
            mae=sum(abs(value) for value in errors) / len(errors) if errors else None,
            bias=sum(errors) / len(errors) if errors else None,
            points=points,
        )

    def reserve_latest(self) -> ReserveResponse:
        with self._repository() as repository:
            run = repository.latest_reserve_run_read_only()
        if run is None:
            return ReserveResponse(
                available=False,
                message="No persisted advisory reserve estimate is available.",
            )
        metadata = run.get("metadata_json") or {}
        supported = [
            name
            for name in (
                "current_state_source",
                "gross_reserve_requirement_kwh",
                "capacity_capped_reserve_kwh",
                "household_demand_confidence",
                "overall_reserve_confidence",
            )
            if name in metadata
        ]
        return ReserveResponse(
            available=True,
            forecast_run_id=run["id"],
            calculation_timestamp_utc=_utc(run["created_at_utc"]),
            state_source=metadata.get("current_state_source"),
            expected_household_demand_kwh=_number(
                run.get("expected_household_demand_kwh")
            ),
            gross_reserve_requirement_kwh=_number(
                metadata.get("gross_reserve_requirement_kwh")
            ),
            capacity_capped_reserve_kwh=_number(
                metadata.get("capacity_capped_reserve_kwh")
            ),
            confidence=metadata.get("overall_reserve_confidence"),
            horizon_start_utc=_utc(run["horizon_start_utc"]),
            horizon_end_utc=_utc(run["horizon_end_utc"]),
            forecast_tier_counts=run["tier_counts"],
            persisted_fields=supported,
        )

    def data_quality(
        self,
        *,
        range_name: str = "30d",
        start: datetime | None = None,
        end: datetime | None = None,
        now: datetime | None = None,
    ) -> DataQualityResponse:
        start_utc, end_utc = resolve_window(
            range_name=range_name, start=start, end=end, now=now
        )
        with self._repository() as repository:
            rows = repository.dashboard_observation_rows_read_only(
                start=start_utc,
                end=end_utc,
                columns=OBSERVATION_COLUMNS,
                limit=MAX_OBSERVATION_ROWS,
            )
            reserve = repository.latest_reserve_run_read_only()
        slots = [_utc(row["slot_utc"]) for row in rows]
        gap = calculate_gap_report(slots, start=start_utc, end=end_utc)
        health_rows = []
        for row in rows:
            item = dict(row)
            item["overall_health_score"] = item.get("health_score")
            health_rows.append(item)
        issue_summary = summarize_health_issues(health_rows)
        domain_health = {}
        for domain in ("telemetry", "price", "solar", "weather", "flow", "overall"):
            flag = "is_healthy" if domain == "overall" else f"{domain}_is_healthy"
            domain_health[domain] = {
                "healthy_count": sum(bool(row.get(flag)) for row in rows),
                "unhealthy_count": sum(not bool(row.get(flag)) for row in rows),
                **issue_summary[domain],
            }
        eligible_rows = [row for row in rows if row["baseline_training_eligible"]]
        ineligible = Counter(
            str(row.get("baseline_exclusion_reason") or "unspecified")
            for row in rows
            if not row["baseline_training_eligible"]
        )
        complete_days, complete_overnights = _complete_periods(eligible_rows)
        tier_counts = (reserve or {}).get("tier_counts", {})
        tier_total = sum(tier_counts.values())
        tier_share = (
            {
                "exact": round(tier_counts.get("tier1_exact", 0) / tier_total, 4),
                "grouped": round(
                    (
                        tier_counts.get("tier2_day_type_30m", 0)
                        + tier_counts.get("tier3_all_days_30m", 0)
                    )
                    / tier_total,
                    4,
                ),
                "recent": round(
                    tier_counts.get("tier4_recent_band", 0) / tier_total, 4
                ),
                "fallback": round(tier_counts.get("tier5_fallback", 0) / tier_total, 4),
            }
            if tier_total
            else {}
        )
        direct_ev = any(
            row.get("ev_source") == "charger" and row.get("ev_power_w") is not None
            for row in rows
        )
        confidence = Counter(str(row["sign_convention_confidence"]) for row in rows)
        residuals = [
            abs(value)
            for row in rows
            if (value := _number(row.get("balance_residual_w"))) is not None
        ]
        return DataQualityResponse(
            range_start_utc=start_utc,
            range_end_utc=end_utc,
            total_observations=len(rows),
            expected_five_minute_slots=gap["expected_slots"],
            collected_slots=gap["collected_slots"],
            missing_slots=gap["missing_slots"],
            coverage_percent=gap["coverage_percent"],
            longest_gap_minutes=gap["longest_gap_minutes"],
            longest_gap_start_utc=_optional_utc(gap["longest_gap_start"]),
            longest_gap_end_utc=_optional_utc(gap["longest_gap_end"]),
            first_gap=gap["first_missing_period"],
            last_gap=gap["last_missing_period"],
            domain_health=domain_health,
            complete_calendar_days=complete_days,
            complete_overnight_periods=complete_overnights,
            eligible_baseline_rows=len(eligible_rows),
            ineligible_baseline_rows_by_reason=dict(ineligible),
            forecast_tier_usage=tier_counts,
            forecast_tier_share=tier_share,
            independent_ev_telemetry_available=direct_ev,
            ev_contamination_warning=not direct_ev,
            sign_convention_confidence=dict(confidence),
            average_absolute_balance_residual_w=(
                sum(residuals) / len(residuals) if residuals else None
            ),
        )


def resolve_window(
    *,
    range_name: str,
    start: datetime | None,
    end: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Validate a named or custom UTC query range."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if (start is None) != (end is None):
        raise DashboardQueryError(
            "invalid_time_range", "Custom start and end must be supplied together."
        )
    if start is None:
        duration = RANGE_DURATIONS.get(range_name)
        if duration is None:
            raise DashboardQueryError(
                "invalid_range", "Range must be 6h, 24h, 48h, 7d, 14d, or 30d."
            )
        return current - duration, current
    _require_aware(start)
    _require_aware(end)
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if start_utc >= end_utc:
        raise DashboardQueryError(
            "invalid_time_range", "Start must be earlier than end."
        )
    if end_utc - start_utc > MAX_RANGE:
        raise DashboardQueryError(
            "range_too_large", "Dashboard queries are limited to 31 days."
        )
    return start_utc, end_utc


def resolve_resolution(start: datetime, end: datetime, requested: str) -> str:
    """Choose or validate a resolution that cannot exceed the response cap."""
    if requested == "auto":
        for name in ("5m", "15m", "30m", "1h"):
            if (
                _bucket_count(start, end, RESOLUTION_MINUTES[name])
                <= MAX_RETURNED_POINTS
            ):
                return name
        raise DashboardQueryError("too_many_points", "Range exceeds the point limit.")
    if requested not in RESOLUTION_MINUTES:
        raise DashboardQueryError(
            "invalid_resolution", "Resolution must be auto, 5m, 15m, 30m, or 1h."
        )
    if _bucket_count(start, end, RESOLUTION_MINUTES[requested]) > MAX_RETURNED_POINTS:
        raise DashboardQueryError(
            "too_many_points",
            "Requested resolution would exceed the 2500-point response limit.",
        )
    return requested


def aggregate_timeseries(
    rows: list[dict[str, Any]], *, start: datetime, end: datetime, resolution: str
) -> list[TimeseriesPoint]:
    """Aggregate power/prices by mean, SOC by last value, and preserve empty gaps."""
    minutes = RESOLUTION_MINUTES[resolution]
    interval = timedelta(minutes=minutes)
    buckets: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        slot = _utc(row["slot_utc"])
        index = int((slot - start).total_seconds() // interval.total_seconds())
        if index >= 0:
            buckets[start + interval * index].append(row)
    result = []
    cursor = start
    while cursor <= end:
        values = buckets.get(cursor, [])
        result.append(
            TimeseriesPoint(
                timestamp_utc=cursor,
                has_observation=bool(values),
                healthy=(
                    all(bool(row["is_healthy"]) for row in values) if values else None
                ),
                house_consumption_w=_average(values, "house_consumption_w"),
                baseline_house_consumption_w=_average(
                    values, "baseline_house_consumption_w"
                ),
                pv_power_w=_average(values, "pv_power_w"),
                battery_soc_percent=_last(values, "battery_soc_percent"),
                battery_charge_power_w=_average(values, "battery_charge_power_w"),
                battery_discharge_power_w=_average(values, "battery_discharge_power_w"),
                grid_import_power_w=_average(values, "grid_import_power_w"),
                grid_export_power_w=_average(values, "grid_export_power_w"),
                amber_buy_price_aud_per_kwh=_average(
                    values, "amber_import_price_per_kwh"
                ),
                amber_sell_price_aud_per_kwh=_average(
                    values, "amber_export_price_per_kwh"
                ),
            )
        )
        cursor += interval
    return result


def _domain(row: dict[str, Any], name: str) -> HealthDomain:
    return HealthDomain(
        healthy=bool(row.get(f"{name}_is_healthy")),
        score_percent=_number(row.get(f"{name}_health_score")),
    )


def _average(rows: list[dict[str, Any]], name: str) -> float | None:
    values = [_number(row.get(name)) for row in rows]
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _last(rows: list[dict[str, Any]], name: str) -> float | None:
    for row in reversed(rows):
        value = _number(row.get(name))
        if value is not None:
            return value
    return None


def _bucket_count(start: datetime, end: datetime, minutes: int) -> int:
    return int((end - start).total_seconds() // (minutes * 60)) + 1


def _complete_periods(rows: list[dict[str, Any]]) -> tuple[int, int]:
    slots_by_day: dict[Any, set[int]] = defaultdict(set)
    for row in rows:
        local = row["observed_at_local"]
        if isinstance(local, str):
            local = datetime.fromisoformat(local.replace("Z", "+00:00"))
        slots_by_day[local.date()].add(local.hour * 12 + local.minute // 5)
    complete_days = sum(len(slots) >= 288 * 0.9 for slots in slots_by_day.values())
    overnights = sum(
        len({slot for slot in slots if slot < 72}) >= 72 * 0.9
        for slots in slots_by_day.values()
    )
    return complete_days, overnights


def _number(value: Any) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _utc(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_aware(value)
    return value.astimezone(UTC)


def _optional_utc(value: Any) -> datetime | None:
    return _utc(value) if value is not None else None


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DashboardQueryError(
            "timezone_required", "Dashboard timestamps must include a timezone."
        )
