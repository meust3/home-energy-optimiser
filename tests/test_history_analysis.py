import json
from datetime import UTC, datetime, timedelta

from energy_optimizer.history_analysis import (
    calculate_gap_report,
    summarize_health_issues,
)


def test_gap_detection_and_coverage():
    start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    slots = [
        start,
        start + timedelta(minutes=5),
        start + timedelta(minutes=15),
        start + timedelta(minutes=20),
    ]
    report = calculate_gap_report(slots)
    assert report["expected_slots"] == 5
    assert report["collected_slots"] == 4
    assert report["missing_slots"] == 1
    assert report["coverage_percent"] == 80.0
    assert report["longest_gap_slots"] == 1
    assert report["longest_gap_minutes"] == 5
    assert report["first_missing_period"]["start"].endswith("00:10:00+00:00")
    assert report["last_missing_period"] == report["first_missing_period"]
    assert report["longest_missing_period"] == report["first_missing_period"]


def test_gap_report_includes_empty_edges_for_explicit_range():
    start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    report = calculate_gap_report(
        [start + timedelta(minutes=5)],
        start=start,
        end=start + timedelta(minutes=10),
    )
    assert report["expected_slots"] == 3
    assert report["collected_slots"] == 1
    assert report["missing_slots"] == 2
    assert report["coverage_percent"] == 33.33
    assert report["first_missing_period"]["start"].endswith("00:00:00+00:00")
    assert report["last_missing_period"]["start"].endswith("00:10:00+00:00")


def test_health_issue_summary_by_domain():
    payload = {
        "telemetry": {
            "issues": [
                {
                    "code": "stale_state",
                    "entity_id": "sensor.power",
                    "severity": "warning",
                }
            ]
        },
        "price": {
            "issues": [
                {
                    "code": "missing_amber_forecast",
                    "entity_id": "sensor.forecast",
                    "severity": "error",
                }
            ]
        },
        "solar": {"issues": []},
        "weather": {"issues": []},
        "overall": {"issues": []},
    }
    records = [
        {
            "health_domains_json": json.dumps(payload),
            "telemetry_health_score": 95,
            "price_health_score": 80,
            "solar_health_score": 100,
            "weather_health_score": 100,
            "overall_health_score": 95,
        },
        {
            "health_domains_json": json.dumps(payload),
            "telemetry_health_score": 85,
            "price_health_score": 60,
            "solar_health_score": 100,
            "weather_health_score": 100,
            "overall_health_score": 85,
        },
    ]
    summary = summarize_health_issues(records)
    assert summary["telemetry"]["warning_count"] == 2
    assert summary["telemetry"]["average_score"] == 90
    assert summary["price"]["error_count"] == 2
    assert summary["price"]["most_common_issues"][0]["count"] == 2
