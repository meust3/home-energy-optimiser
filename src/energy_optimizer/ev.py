"""Conservative EV baseline handling and optional session inference."""

from collections.abc import Sequence
from typing import Any


def calculate_baseline_load(
    house_consumption_w: float | None,
    *,
    ev_charging_active: bool | None,
    ev_power_w: float | None,
    inferred_session: bool = False,
    inference_confidence: str = "unconfirmed",
) -> tuple[float | None, bool, str | None]:
    if house_consumption_w is None:
        return None, False, "house_consumption_missing"
    if ev_power_w is not None:
        return max(house_consumption_w - max(ev_power_w, 0.0), 0.0), True, None
    if ev_charging_active is False:
        return house_consumption_w, True, None
    if inferred_session:
        return (
            house_consumption_w,
            False,
            f"inferred_ev_session_{inference_confidence}_power_unknown",
        )
    if ev_charging_active is True:
        return house_consumption_w, False, "ev_active_power_unknown"
    return house_consumption_w, True, None


def infer_ev_sessions(
    rows: Sequence[dict[str, Any]],
    *,
    enabled: bool,
    plausible_min_w: float,
    plausible_max_w: float,
    minimum_samples: int,
) -> list[dict[str, Any]]:
    """Identify low-variability sustained candidates; never changes observations."""
    if not enabled or len(rows) < minimum_samples:
        return []
    sessions: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []
    for row in rows:
        power = row.get("house_consumption_w")
        if (
            isinstance(power, (int, float))
            and plausible_min_w <= power <= plausible_max_w
        ):
            run.append(row)
        else:
            if len(run) >= minimum_samples:
                sessions.append(_candidate(run))
            run = []
    if len(run) >= minimum_samples:
        sessions.append(_candidate(run))
    return [session for session in sessions if session["confidence"] != "low"]


def _candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["house_consumption_w"]) for row in rows]
    mean = sum(values) / len(values)
    spread = max(values) - min(values)
    variability = spread / max(mean, 1.0)
    confidence = (
        "high" if variability <= 0.05 else "medium" if variability <= 0.1 else "low"
    )
    return {
        "start_slot_utc": rows[0].get("slot_utc"),
        "end_slot_utc": rows[-1].get("slot_utc"),
        "sample_count": len(rows),
        "average_house_consumption_w": round(mean, 2),
        "variability_ratio": round(variability, 4),
        "confidence": confidence,
        "evidence": "sustained plausible-band load with low variability",
    }
