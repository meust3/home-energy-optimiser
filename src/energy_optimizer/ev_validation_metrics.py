"""Five-minute comparisons of EV-adjusted site demand against independent home load."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from datetime import UTC, datetime

Series = list[tuple[float, float | None]]
Streams = dict[str, Series]
SLOT = 300


def interval(series: Series, start: int) -> float | None:
    """Time-weighted watts only when the full slot has fresh valid samples."""
    index = bisect_right(series, start, key=lambda p: p[0]) - 1
    elapsed = watt_seconds = 0.0
    left = start
    while left < start + SLOT:
        right = min(
            start + SLOT,
            series[index + 1][0] if index + 1 < len(series) else start + SLOT,
        )
        if index >= 0:
            at, value = series[index]
            if value is not None:
                seconds = max(0, min(right, at + 600) - left)
                watt_seconds += seconds * value
                elapsed += seconds
        left = right
        index += 1
    return watt_seconds / SLOT if elapsed >= SLOT - 0.00001 else None


def slot_samples(series: Series, start: int) -> Series:
    left = bisect_left(series, start, key=lambda p: p[0])
    right = bisect_left(series, start + SLOT, key=lambda p: p[0])
    return series[left:right]


def point_pair(streams: Streams, start: int) -> tuple | None:
    station = slot_samples(streams["station"], start)
    return min(
        (
            (abs(a - b), a, b, x, y)
            for a, x in slot_samples(streams["site"], start)
            for b, y in station
            if x is not None and y is not None and abs(a - b) <= 60
        ),
        default=None,
    )


def counter_at(series: Series, at: int) -> float | None:
    index = bisect_left(series, at, key=lambda p: p[0])
    for i in (index - 1, index):
        if 0 <= i < len(series) - 1:
            (u, x), (v, y) = series[i : i + 2]
            if (
                u <= at <= v
                and 0 < v - u <= 150
                and x is not None
                and y is not None
                and y >= x
            ):
                return x + (y - x) * (at - u) / (v - u)
    return None


def summarize(start: float, end: float, streams: Streams) -> dict:
    def timestamp(t: float) -> str:
        return datetime.fromtimestamp(t, UTC).isoformat()

    energy = streams["energy"]
    reset = any(
        x is not None and y is not None and y < x
        for (_, x), (_, y) in zip(energy, energy[1:], strict=False)
    )
    result = dict(
        start=timestamp(start),
        end=timestamp(end),
        seconds=end - start,
        aligned_seconds=0,
        counter_reset=reset,
        pairs=0,
        revised_pairs=0,
        paired_point_slots=0,
        counter_only_slots=0,
        station_energy_slots=0,
        counter_energy_slots=0,
        provider_final_kwh=None,
    )
    totals = {"station": 0.0, "counter": 0.0}
    for label in ("station", "counter", "revised", "reference_counter"):
        result[label + "_absolute_sum"] = result[label + "_signed_sum"] = 0.0

    def record(label: str, error: float) -> None:
        result[label + "_absolute_sum"] += abs(error)
        result[label + "_signed_sum"] += error

    for t in range(math.ceil(start / SLOT) * SLOT, math.floor(end / SLOT) * SLOT, SLOT):
        site, station, load = (
            interval(streams[k], t) for k in ("site", "station", "load")
        )
        left, right = (counter_at(energy, u) for u in (t, t + SLOT))
        counter = (
            (right - left) * 12000
            if not reset
            and left is not None
            and right is not None
            and 0 <= right - left <= 1
            else None
        )
        for label, value in (("station", station), ("counter", counter)):
            if value is not None:
                totals[label] += value / 12000
                result[label + "_energy_slots"] += 1
        aligned = site is not None and station is not None and station <= site
        estimate = site - station if aligned else None
        if aligned:
            result["aligned_seconds"] += SLOT
        elif site is None or station is None:
            pair = point_pair(streams, t)
            if pair is not None:
                if pair[3] >= pair[4]:
                    estimate = pair[3] - pair[4]
                    result["paired_point_slots"] += 1
            elif site is not None and counter is not None and counter <= site:
                estimate = site - counter
                result["counter_only_slots"] += 1
        if (
            site is None
            or load is None
            or counter is None
            or counter > site
            or estimate is None
        ):
            continue
        baseline_error = site - counter - load
        revised_error = estimate - load
        record("reference_counter", baseline_error)
        record("revised", revised_error)
        result["revised_pairs"] += 1
        if aligned:
            record("counter", baseline_error)
            record("station", revised_error)
            result["pairs"] += 1
    result["other_seconds"] = end - start - result["aligned_seconds"]
    result["coverage"] = result["aligned_seconds"] / (end - start)
    result["station_energy_kwh_over_covered_slots"] = (
        totals["station"] if result["station_energy_slots"] else None
    )
    result["counter_increase_kwh_over_covered_slots"] = (
        totals["counter"] if result["counter_energy_slots"] else None
    )
    return result


def improves(rows: Sequence[dict]) -> bool:
    return (
        sum(r["pairs"] for r in rows) > 0
        and sum(r["station_absolute_sum"] for r in rows)
        < sum(r["counter_absolute_sum"] for r in rows)
        and abs(sum(r["station_signed_sum"] for r in rows))
        < abs(sum(r["counter_signed_sum"] for r in rows))
    )


def comparison(rows: Sequence[dict], count_key: str, labels: list[str]) -> dict:
    n = sum(r[count_key] for r in rows)
    return {
        "matched_intervals": n,
        **{
            label: {
                "mean_absolute_disagreement_w": (
                    sum(r[label + "_absolute_sum"] for r in rows) / n if n else None
                ),
                "bias_w": (
                    sum(r[label + "_signed_sum"] for r in rows) / n if n else None
                ),
            }
            for label in labels
        },
    }


def comparison_report(status: dict) -> dict:
    rows = status["sessions"]
    return {
        "cohort_start": status["frozen_at"],
        "first_completion": rows[0]["end"],
        "tenth_completion": rows[-1]["end"],
        "sessions": len(rows),
        "aligned_fraction": status["coverage"],
        "baseline": "session counter",
        "reference": (
            "separately reported household load; "
            "positive bias means the estimate is higher"
        ),
        "aligned": comparison(rows, "pairs", ["station", "counter"]),
        "including_fallbacks": comparison(
            rows, "revised_pairs", ["revised", "reference_counter"]
        ),
        "sessions_improving_both_metrics": status["sessions_improving_both_metrics"],
        "sessions_with_matched_reference": sum(r["pairs"] > 0 for r in rows),
        "improvement_survives_each_session_omission": all(
            improves(rows[:i] + rows[i + 1 :]) for i in range(len(rows))
        ),
        "missing_collection_slots": status["missing_collection_slots"],
        "unmatched_charging_updates": status["unmatched_charging_updates"],
        "decision": status["status"],
        "per_session": rows,
    }
