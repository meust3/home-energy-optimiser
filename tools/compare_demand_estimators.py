"""Offline historical as-of comparison; does not alter the production estimator."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from energy_optimizer.estimator_comparison import EstimatorCase, compare_estimators
from energy_optimizer.ev_annotation import parse_aware_timestamp
from energy_optimizer.persistence import configured_repository
from energy_optimizer.training_provenance import classify_training_cohort


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--as-of", type=parse_aware_timestamp)
    parser.add_argument("--max-targets", type=int, default=2500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.days <= 7 or not 1 <= args.max_targets <= 10000:
        parser.error("days must exceed 7 and max-targets must be 1-10000")
    as_of = (args.as_of or datetime.now(UTC)).astimezone(UTC)
    start = as_of - timedelta(days=args.days)
    columns = (
        "slot_utc",
        "observed_at_local",
        "baseline_house_consumption_w",
        "baseline_training_eligible",
        "telemetry_is_healthy",
        "ev_source",
        "ev_charging_active",
        "ev_detection_confidence",
        "ev_telemetry_fresh",
        "baseline_exclusion_reason",
    )
    with configured_repository() as repository:
        rows = repository.observation_rows(start=start, end=as_of, columns=columns)
    cases = _tier2_cases(rows, args.max_targets)
    report = compare_estimators(cases).model_dump(mode="json")
    report.update(
        evaluation="historical_as_of_tier2_day_type_30m",
        target_count=len(cases),
        as_of_utc=as_of.isoformat(),
        future_data_used=False,
        production_tier2="arithmetic_mean_unchanged",
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps(report, indent=2))
        print("Evaluation only: no estimator was selected or changed.")
    return 0


def _tier2_cases(rows: list[dict], limit: int) -> list[EstimatorCase]:
    timezone = ZoneInfo("Australia/Brisbane")
    ordered = sorted(rows, key=lambda row: row["slot_utc"])
    cases = []
    for index, target in enumerate(ordered):
        if len(cases) >= limit or not _eligible(target):
            continue
        local = target["slot_utc"].astimezone(timezone)
        bucket = local.hour * 2 + local.minute // 30
        weekend = local.weekday() >= 5
        candidates = []
        for prior in ordered[:index]:
            if not _eligible(prior):
                continue
            prior_local = prior["slot_utc"].astimezone(timezone)
            if prior_local.date() == local.date():
                continue
            if (prior_local.weekday() >= 5) != weekend:
                continue
            if prior_local.hour * 2 + prior_local.minute // 30 != bucket:
                continue
            cohort = classify_training_cohort(prior)
            candidates.append((float(prior["baseline_house_consumption_w"]), cohort))
        verified = [
            value for value, cohort in candidates if cohort == "verified_non_ev"
        ]
        values = verified if len(verified) >= 3 else [value for value, _ in candidates]
        if len(values) < 3:
            continue
        cases.append(
            EstimatorCase(
                training_values_w=values,
                actual_w=float(target["baseline_house_consumption_w"]),
                horizon_hours=0,
                local_hour=local.hour,
                day_type="weekend" if weekend else "weekday",
            )
        )
    return cases


def _eligible(row: dict) -> bool:
    return bool(
        row.get("telemetry_is_healthy")
        and row.get("baseline_training_eligible")
        and row.get("baseline_house_consumption_w") is not None
    )


if __name__ == "__main__":
    raise SystemExit(main())
