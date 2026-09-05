"""Deterministic, idempotent forecast calibration rollups."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from energy_optimizer.db.models import ForecastAccuracyRollup
from energy_optimizer.forecast_alignment import alignment_version
from energy_optimizer.forecast_calibration import HORIZON_NAMES, _horizon_bucket
from energy_optimizer.timestamps import aware_datetime


def refresh_forecast_accuracy_rollups(
    repository: Any,
    *,
    local_dates: list[date],
    timezone_name: str,
    complete_day_coverage_percent: float = 95,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Replace rollups for explicit local dates; never append partial batches."""
    zone = ZoneInfo(timezone_name)
    calculated = (now or datetime.now(UTC)).astimezone(UTC)
    rebuilt = 0
    for local_date in sorted(set(local_dates)):
        start = datetime.combine(local_date, time.min, zone).astimezone(UTC)
        end = (
            datetime.combine(local_date, time.min, zone) + timedelta(days=1)
        ).astimezone(UTC)
        rows, truncated = repository.forecast_rollup_detail_rows_read_only(
            after=start, before=end
        )
        if truncated:
            raise RuntimeError(f"rollup detail truncated for {local_date.isoformat()}")
        groups = build_rollup_groups(
            rows,
            timezone_name=timezone_name,
            complete_day_coverage_percent=complete_day_coverage_percent,
            calculated_at=calculated,
        )
        with repository.transaction() as session:
            session.execute(
                delete(ForecastAccuracyRollup).where(
                    ForecastAccuracyRollup.rollup_date == local_date
                )
            )
            table = ForecastAccuracyRollup.__table__
            for key, values in groups.items():
                statement = (
                    postgresql_insert(table)
                    if repository.backend == "postgresql"
                    else sqlite_insert(table)
                ).values(
                    rollup_date=key[0],
                    forecast_type=key[1],
                    model_version=key[2],
                    alignment_version=key[3],
                    training_policy=key[4],
                    horizon_bucket=key[5],
                    day_type=key[6],
                    **values,
                )
                session.execute(statement)
        rebuilt += len(groups)
    return {
        "dates_rebuilt": len(set(local_dates)),
        "rollups_rebuilt": rebuilt,
        "calculated_at_utc": calculated.isoformat(),
    }


def forecast_rollup_backfill_status(
    repository: Any,
    *,
    forecast_type: str,
    model_version: str,
    alignment_version_name: str,
    training_policy: str,
    window_start: date,
    window_end: date,
    timezone_name: str,
    last_failure: str | None = None,
) -> dict[str, Any]:
    """Plan exact-identity work so legacy-only dates cannot starve backfill."""
    zone = ZoneInfo(timezone_name)
    start_utc = datetime.combine(window_start, time.min, zone).astimezone(UTC)
    end_utc = datetime.combine(window_end, time.min, zone).astimezone(UTC)
    targets, detail_truncated = repository.forecast_rollup_candidate_targets_read_only(
        forecast_type=forecast_type,
        model_version=model_version,
        alignment_version=alignment_version_name,
        training_policy=training_policy,
        after=start_utc,
        before=end_utc,
    )
    eligible = sorted(
        {aware_datetime(value).astimezone(zone).date() for value in targets}
    )
    rows, rollups_truncated = repository.forecast_rollup_rows_read_only(
        after_date=window_start,
        before_date=window_end,
    )
    represented: dict[date, set[str]] = defaultdict(set)
    successes = []
    for row in rows:
        if (
            row.get("forecast_type") == forecast_type
            and row.get("model_version") == model_version
            and row.get("alignment_version") == alignment_version_name
            and row.get("training_policy") == training_policy
            and row.get("calculated_at_utc") is not None
        ):
            represented[row["rollup_date"]].add(str(row.get("horizon_bucket")))
            successes.append(aware_datetime(row["calculated_at_utc"]).astimezone(UTC))
    completed = sorted(
        day for day in eligible if represented.get(day) == set(HORIZON_NAMES)
    )
    remaining = [day for day in eligible if day not in set(completed)]
    truncated = detail_truncated or rollups_truncated
    status = (
        "blocked_truncated"
        if truncated
        else "complete" if not remaining else "in_progress"
    )
    return {
        "rollup_backfill_status": status,
        "eligible_dates": len(eligible),
        "completed_dates": len(completed),
        "remaining_dates": len(remaining),
        "remaining_local_dates": remaining,
        "last_success_utc": max(successes).isoformat() if successes else None,
        "last_failure": last_failure,
        "current_identity_complete": bool(eligible) and not remaining and not truncated,
        "detail_query_truncated": detail_truncated,
        "rollup_query_truncated": rollups_truncated,
        "identity": {
            "forecast_type": forecast_type,
            "model_version": model_version,
            "alignment_version": alignment_version_name,
            "training_policy": training_policy,
        },
    }


def build_rollup_groups(
    detail_rows: list[dict[str, Any]],
    *,
    timezone_name: str = "Australia/Brisbane",
    complete_day_coverage_percent: float = 95,
    calculated_at: datetime | None = None,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    zone = ZoneInfo(timezone_name)
    raw: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    slots: dict[tuple[Any, ...], dict[datetime, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    date_slots: dict[tuple[Any, ...], dict[datetime, list[dict[str, Any]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for row in detail_rows:
        metadata = row.get("run_metadata_json") or row.get("run_metadata") or {}
        target = aware_datetime(row["period_start_utc"]).astimezone(UTC)
        horizon = _horizon_bucket(
            (target - aware_datetime(row["created_at_utc"])).total_seconds() / 3600
        )
        if horizon not in HORIZON_NAMES:
            continue
        local_date = target.astimezone(zone).date()
        key = (
            local_date,
            row["forecast_type"],
            row["model_version"],
            alignment_version(metadata),
            str(metadata.get("training_policy", "legacy_all_eligible")),
            horizon,
            "weekend" if local_date.weekday() >= 5 else "weekday",
        )
        raw[key].append(row)
        slots[key][target].append(row)
        date_key = (*key[:5], key[6])
        date_slots[date_key][target].append(row)
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    calculated = (calculated_at or datetime.now(UTC)).astimezone(UTC)
    required = ceil(288 * complete_day_coverage_percent / 100)
    for key, rows in raw.items():
        eligible_rows = [r for r in rows if _eligible(r)]
        date_key = (*key[:5], key[6])
        all_date_slots = date_slots[date_key]
        eligible_date_slots = sum(
            any(_eligible(row) for row in predictions)
            for predictions in all_date_slots.values()
        )
        slot_values = []
        for target, predictions in sorted(slots[key].items()):
            usable = [r for r in predictions if _eligible(r)]
            if usable:
                forecast = sum(float(r["expected_value"]) for r in usable) / len(usable)
                actual = sum(float(r["actual_value"]) for r in usable) / len(usable)
                slot_values.append((target, forecast, actual))
        signed_energy = sum(
            (actual - forecast) / 12_000 for _, forecast, actual in slot_values
        )
        result[key] = {
            "eligible_points": len(eligible_rows),
            "missing_points": len(rows) - len(eligible_rows),
            "total_points": len(rows),
            "sum_signed_error": sum(
                float(r.get("signed_error") or 0) for r in eligible_rows
            ),
            "sum_absolute_error": sum(
                float(
                    r.get("absolute_error")
                    or abs(float(r["actual_value"]) - float(r["expected_value"]))
                )
                for r in eligible_rows
            ),
            "sum_squared_error": sum(
                float(
                    r.get("squared_error")
                    or (float(r["actual_value"]) - float(r["expected_value"])) ** 2
                )
                for r in eligible_rows
            ),
            "forecast_energy_kwh": sum(
                float(r["expected_value"]) / 12_000 for r in eligible_rows
            ),
            "actual_energy_kwh": sum(
                float(r["actual_value"]) / 12_000 for r in eligible_rows
            ),
            "unique_target_slots": len(slots[key]),
            "eligible_target_slots": len(slot_values),
            "date_unique_target_slots": len(all_date_slots),
            "date_eligible_target_slots": eligible_date_slots,
            "expected_target_slots": 288,
            "target_slot_coverage_percent": len(slot_values) / 288 * 100,
            "slot_sum_actual_w": sum(v[2] for v in slot_values),
            "slot_sum_forecast_w": sum(v[1] for v in slot_values),
            "slot_sum_signed_error_w": sum(v[2] - v[1] for v in slot_values),
            "slot_sum_absolute_error_w": sum(abs(v[2] - v[1]) for v in slot_values),
            "slot_sum_squared_error_w2": sum((v[2] - v[1]) ** 2 for v in slot_values),
            "cumulative_signed_energy_error_kwh": signed_energy,
            "cumulative_underforecast_kwh": max(signed_energy, 0),
            "complete_day": len(slot_values) >= required,
            "minimum_target_utc": slot_values[0][0] if slot_values else None,
            "maximum_target_utc": slot_values[-1][0] if slot_values else None,
            "calculated_at_utc": calculated,
        }
    return result


def _eligible(row: dict[str, Any]) -> bool:
    return (
        bool(row.get("actual_available") and row.get("health_eligible"))
        and row.get("actual_value") is not None
    )
