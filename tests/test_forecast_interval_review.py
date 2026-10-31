from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from energy_optimizer.forecast_interval_review import review_forecast_intervals

ZONE = ZoneInfo("Australia/Brisbane")
START = datetime(2026, 8, 1, 12, tzinfo=ZONE)
CUTOFF = datetime(2026, 8, 29, tzinfo=ZONE)


def samples():
    result = []
    for day in range(35):
        for slot in range(10):
            target = START + timedelta(days=day, minutes=5 * slot)
            result.append(
                {
                    "period_start_utc": target,
                    "period_end_utc": target + timedelta(minutes=5),
                    "created_at_utc": target - timedelta(hours=1),
                    "scored_at_utc": target + timedelta(minutes=20),
                    "expected_value": 1000,
                    "actual_value": 1000 + slot - 5,
                    "actual_available": True,
                    "health_eligible": True,
                    "source": "scheduled_forecast_operations",
                    "forecast_type": "baseline_household_load",
                    "model_version": "household-demand-hierarchy-v1-cohort-v1",
                    "run_metadata_json": {
                        "alignment_version": "full_5m_v1",
                        "training_policy": "verified_preferred",
                    },
                }
            )
    return result


def test_overlap_deduplication_and_heldout_coverage_never_enable_bounds():
    rows = samples()
    report = review_forecast_intervals(
        rows + rows, training_end=CUTOFF, minimum_group_samples=50
    )
    group = report["groups"][0]
    assert report["independent_target_horizon_slots"] == len(rows)
    assert group["training_dates"] == 28 and group["holdout_dates"] == 7
    assert group["holdout_coverage_percent"] == 80
    assert group["status"] == "coverage_candidate_pass"
    assert report["operational_bounds_enabled"] is False
    assert report["database_write_performed"] is False


def test_holdout_actuals_cannot_change_the_fitted_interval():
    rows = samples()
    original = review_forecast_intervals(
        rows, training_end=CUTOFF, minimum_group_samples=50
    )["groups"][0]
    for row in rows:
        if row["period_start_utc"] >= CUTOFF:
            row["actual_value"] = 10000
    changed = review_forecast_intervals(
        rows, training_end=CUTOFF, minimum_group_samples=50
    )["groups"][0]
    assert changed["residual_p10_w"] == original["residual_p10_w"]
    assert changed["residual_p90_w"] == original["residual_p90_w"]
    assert changed["status"] == "coverage_candidate_failed"


def test_late_training_labels_and_ineligible_points_do_not_enter_fit():
    rows = samples()
    for row in rows[:10]:
        row["scored_at_utc"] = CUTOFF + timedelta(days=1)
    report = review_forecast_intervals(rows, training_end=CUTOFF)
    assert report["rejected_rows"] == 10
    assert report["groups"][0]["training_dates"] == 27
    assert report["groups"][0]["status"] == "insufficient_independent_evidence"
    assert report["groups"][0]["residual_p10_w"] is None


def test_wrong_identity_is_excluded_and_cutoff_must_split_local_dates():
    rows = samples()
    for row in rows:
        row["run_metadata_json"]["training_policy"] = "legacy_all_eligible"
    assert review_forecast_intervals(rows, training_end=CUTOFF)["groups"] == []
    with pytest.raises(ValueError, match="midnight"):
        review_forecast_intervals([], training_end=CUTOFF + timedelta(hours=1))
