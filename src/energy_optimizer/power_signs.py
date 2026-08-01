"""Non-mutating hypotheses for GoodWe grid and battery power signs."""

import math
from collections import defaultdict
from typing import Any


def analyze_power_signs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank all sign combinations using PV + grid + battery ~= house residuals."""
    complete = [
        row
        for row in rows
        if all(
            isinstance(row.get(field), (int, float))
            for field in (
                "pv_power_w",
                "house_consumption_w",
                "grid_power_w",
                "battery_power_w",
            )
        )
    ]
    hypotheses: list[dict[str, Any]] = []
    for grid_sign in (1, -1):
        for battery_sign in (1, -1):
            residuals = [
                row["pv_power_w"]
                + grid_sign * row["grid_power_w"]
                + battery_sign * row["battery_power_w"]
                - row["house_consumption_w"]
                for row in complete
            ]
            count = len(residuals)
            mae = sum(abs(value) for value in residuals) / count if count else None
            rmse = (
                math.sqrt(sum(value * value for value in residuals) / count)
                if count
                else None
            )
            bias = sum(residuals) / count if count else None
            hypotheses.append(
                {
                    "grid_multiplier": grid_sign,
                    "battery_multiplier": battery_sign,
                    "grid_positive_likely_means": (
                        "import" if grid_sign == 1 else "export"
                    ),
                    "battery_positive_likely_means": (
                        "discharge" if battery_sign == 1 else "charge"
                    ),
                    "sample_count": count,
                    "mean_absolute_residual_w": (
                        round(mae, 2) if mae is not None else None
                    ),
                    "root_mean_square_residual_w": (
                        round(rmse, 2) if rmse is not None else None
                    ),
                    "mean_signed_residual_w": (
                        round(bias, 2) if bias is not None else None
                    ),
                }
            )
    ranked = sorted(
        hypotheses,
        key=lambda item: (
            item["root_mean_square_residual_w"] is None,
            item["root_mean_square_residual_w"] or 0,
        ),
    )
    confidence = "insufficient_data"
    improvement_percent = None
    if complete and len(ranked) > 1:
        best = ranked[0]["root_mean_square_residual_w"]
        second = ranked[1]["root_mean_square_residual_w"]
        if second and best is not None:
            improvement_percent = round((second - best) / second * 100, 2)
            mean_house = sum(abs(row["house_consumption_w"]) for row in complete) / len(
                complete
            )
            normalized = best / max(mean_house, 1)
            if (
                len(complete) >= 100
                and improvement_percent >= 25
                and normalized <= 0.15
            ):
                confidence = "high"
            elif (
                len(complete) >= 30 and improvement_percent >= 10 and normalized <= 0.35
            ):
                confidence = "medium"
            else:
                confidence = "low"
    modes: dict[str, list[float]] = defaultdict(list)
    for row in complete:
        mode = row.get("battery_mode")
        if mode not in (None, ""):
            modes[str(mode)].append(float(row["battery_power_w"]))
    mode_summary = [
        {
            "battery_mode": mode,
            "sample_count": len(values),
            "average_battery_power_w": round(sum(values) / len(values), 2),
            "positive_samples": sum(value > 0 for value in values),
            "negative_samples": sum(value < 0 for value in values),
            "zero_samples": sum(value == 0 for value in values),
        }
        for mode, values in sorted(modes.items())
    ]
    return {
        "sample_count": len(complete),
        "excluded_incomplete_samples": len(rows) - len(complete),
        "hypotheses": ranked,
        "leading_hypothesis": ranked[0] if complete else None,
        "confidence": confidence,
        "best_vs_second_improvement_percent": improvement_percent,
        "battery_mode_evidence": mode_summary,
        "disclaimer": (
            "Statistical hypothesis only; no sign convention was selected or stored."
        ),
    }
