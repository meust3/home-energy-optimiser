"""Pure analysis helpers for collection coverage and persisted health issues."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

DOMAIN_NAMES = ("telemetry", "price", "solar", "weather", "flow", "overall")
SLOT_INTERVAL = timedelta(minutes=5)


def _slot(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("gap analysis requires timezone-aware datetimes")
    utc = value.astimezone(UTC)
    return utc.replace(minute=(utc.minute // 5) * 5, second=0, microsecond=0)


def _missing_period(start: datetime, end: datetime, slots: int) -> dict[str, Any]:
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "slots": slots,
        "minutes": slots * 5,
    }


def calculate_gap_report(
    slots: list[datetime],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Calculate inclusive five-minute coverage for an explicit or observed range."""
    normalized = sorted({_slot(value) for value in slots})
    range_start = _slot(start) if start else (normalized[0] if normalized else None)
    range_end = _slot(end) if end else (normalized[-1] if normalized else None)
    if range_start is None or range_end is None or range_end < range_start:
        return {
            "range_start": None,
            "range_end": None,
            "expected_slots": 0,
            "collected_slots": 0,
            "missing_slots": 0,
            "coverage_percent": 0.0,
            "longest_gap_slots": 0,
            "longest_gap_minutes": 0,
            "longest_gap_start": None,
            "longest_gap_end": None,
            "first_missing_period": None,
            "last_missing_period": None,
            "longest_missing_period": None,
        }
    expected = int((range_end - range_start) / SLOT_INTERVAL) + 1
    present = {value for value in normalized if range_start <= value <= range_end}
    missing_periods: list[dict[str, Any]] = []
    current_count = 0
    current_start = None
    cursor = range_start
    while cursor <= range_end:
        if cursor not in present:
            if current_count == 0:
                current_start = cursor
            current_count += 1
        elif current_count and current_start is not None:
            missing_periods.append(
                _missing_period(current_start, cursor - SLOT_INTERVAL, current_count)
            )
            current_count = 0
            current_start = None
        cursor += SLOT_INTERVAL
    if current_count and current_start is not None:
        missing_periods.append(_missing_period(current_start, range_end, current_count))
    longest = (
        max(missing_periods, key=lambda period: period["slots"])
        if missing_periods
        else None
    )
    collected = len(present)
    return {
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "expected_slots": expected,
        "collected_slots": collected,
        "missing_slots": expected - collected,
        "coverage_percent": round(collected / expected * 100, 2),
        "longest_gap_slots": longest["slots"] if longest else 0,
        "longest_gap_minutes": longest["minutes"] if longest else 0,
        "longest_gap_start": longest["start"] if longest else None,
        "longest_gap_end": longest["end"] if longest else None,
        "first_missing_period": missing_periods[0] if missing_periods else None,
        "last_missing_period": missing_periods[-1] if missing_periods else None,
        "longest_missing_period": longest,
    }


def summarize_health_issues(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate persisted typed domain issues and scores."""
    result: dict[str, Any] = {}
    for domain in DOMAIN_NAMES:
        counter: Counter[tuple[str, str | None, str]] = Counter()
        warning_count = 0
        error_count = 0
        scores: list[float] = []
        for record in records:
            score = record.get(f"{domain}_health_score")
            if isinstance(score, (int, float)):
                scores.append(float(score))
            raw = record.get("health_domains_json")
            if not isinstance(raw, str):
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            domain_payload = payload.get(domain) if isinstance(payload, dict) else None
            if not isinstance(domain_payload, dict):
                continue
            issues = domain_payload.get("issues", [])
            if not isinstance(issues, list):
                continue
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                severity = str(issue.get("severity", "error"))
                code = str(issue.get("code", "unknown"))
                entity_id = issue.get("entity_id")
                counter[(code, entity_id, severity)] += 1
                if severity == "warning":
                    warning_count += 1
                else:
                    error_count += 1
        result[domain] = {
            "warning_count": warning_count,
            "error_count": error_count,
            "average_score": round(sum(scores) / len(scores), 2) if scores else None,
            "most_common_issues": [
                {
                    "code": code,
                    "entity_id": entity_id,
                    "severity": severity,
                    "count": count,
                }
                for (code, entity_id, severity), count in counter.most_common(10)
            ],
        }
    return result
