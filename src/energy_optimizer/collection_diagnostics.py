"""Bounded incident summaries over existing observation evidence."""

from datetime import datetime, timedelta
from typing import Any

from energy_optimizer.timestamps import native_json


def collection_incidents(
    rows: list[dict[str, Any]], start: datetime, end: datetime
) -> dict[str, Any]:
    """Separate absent slots from unhealthy stored telemetry; keep only 20 details."""
    by_slot = {row["slot_utc"]: row for row in rows}
    gaps: list[dict[str, Any]] = []
    outages: list[dict[str, Any]] = []
    gap = None
    outage = None
    cursor = start
    interval = timedelta(minutes=5)
    while cursor <= end:
        row = by_slot.get(cursor)
        if row is None:
            if gap is None:
                gap = {"start_utc": cursor, "end_utc": cursor, "slots": 0}
                gaps.append(gap)
            gap["end_utc"] = cursor
            gap["slots"] += 1
            outage = None
        else:
            gap = None
            if not row.get("telemetry_is_healthy"):
                if outage is None:
                    outage = {
                        "start_utc": cursor,
                        "end_utc": cursor,
                        "slots": 0,
                        "entities": set(),
                        "reasons": set(),
                        "recovered_at_utc": None,
                    }
                    outages.append(outage)
                outage["end_utc"] = cursor
                outage["slots"] += 1
                payload = native_json(row.get("health_domains_json")) or {}
                for issue in payload.get("telemetry", {}).get("issues", []):
                    if issue.get("entity_id"):
                        outage["entities"].add(issue["entity_id"])
                    outage["reasons"].add(issue.get("code", "unknown"))
            elif outage is not None:
                outage["recovered_at_utc"] = cursor
                outage = None
        cursor += interval
    for item in outages:
        item["entities"] = sorted(item["entities"])
        item["reasons"] = sorted(item["reasons"])
    return {
        "collection_gap_periods": gaps[-20:],
        "collection_gap_period_count": len(gaps),
        "telemetry_incidents": outages[-20:],
        "telemetry_incident_count": len(outages),
        "incident_details_truncated": len(gaps) > 20 or len(outages) > 20,
        "missing_value_counts": {
            field: sum(row.get(field) is None for row in rows)
            for field in (
                "house_consumption_w",
                "battery_soc_percent",
                "pv_power_w",
                "ev_power_w",
                "temperature_c",
            )
        },
    }
