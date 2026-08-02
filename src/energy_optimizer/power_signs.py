"""Non-mutating hypotheses for GoodWe grid and battery power signs."""

import math
from collections import defaultdict
from statistics import median
from typing import Any


def _residual_example(row: dict[str, Any], residual: float) -> dict[str, Any]:
    return {
        "slot_utc": row.get("slot_utc"),
        "pv_power_w": row["pv_power_w"],
        "house_consumption_w": row["house_consumption_w"],
        "grid_power_w": row["grid_power_w"],
        "battery_power_w": row["battery_power_w"],
        "battery_mode": row.get("battery_mode"),
        "residual_w": round(residual, 2),
        "absolute_residual_w": round(abs(residual), 2),
    }


def _fit_confidence(sample_count: int, normalized_rmse: float | None) -> str:
    if sample_count < 10 or normalized_rmse is None:
        return "insufficient_data"
    if sample_count >= 100 and normalized_rmse <= 0.15:
        return "high"
    if sample_count >= 30 and normalized_rmse <= 0.35:
        return "medium"
    return "low"


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
            evaluated = [
                (
                    row,
                    row["pv_power_w"]
                    + grid_sign * row["grid_power_w"]
                    + battery_sign * row["battery_power_w"]
                    - row["house_consumption_w"],
                )
                for row in complete
            ]
            residuals = [residual for _row, residual in evaluated]
            count = len(residuals)
            mae = sum(abs(value) for value in residuals) / count if count else None
            rmse = (
                math.sqrt(sum(value * value for value in residuals) / count)
                if count
                else None
            )
            bias = sum(residuals) / count if count else None
            median_signed = median(residuals) if residuals else None
            median_absolute = (
                median(abs(value) for value in residuals) if residuals else None
            )
            mean_house = (
                sum(abs(row["house_consumption_w"]) for row in complete) / count
                if count
                else None
            )
            normalized_rmse = rmse / max(mean_house, 1) if rmse is not None else None
            by_fit = sorted(evaluated, key=lambda item: abs(item[1]))
            convention = (
                f"grid_positive={'import' if grid_sign == 1 else 'export'}, "
                f"battery_positive={'discharge' if battery_sign == 1 else 'charge'}"
            )
            hypotheses.append(
                {
                    "convention": convention,
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
                    "median_residual_w": (
                        round(median_signed, 2) if median_signed is not None else None
                    ),
                    "median_absolute_residual_w": (
                        round(median_absolute, 2)
                        if median_absolute is not None
                        else None
                    ),
                    "confidence": _fit_confidence(count, normalized_rmse),
                    "supporting_examples": [
                        _residual_example(row, residual) for row, residual in by_fit[:3]
                    ],
                    "contradicting_examples": [
                        _residual_example(row, residual)
                        for row, residual in reversed(by_fit[-3:])
                    ],
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
    suggestion = None
    if confidence == "high" and complete:
        leading = ranked[0]
        suggestion = {
            "GRID_POWER_SIGN": (
                "positive_import"
                if leading["grid_positive_likely_means"] == "import"
                else "positive_export"
            ),
            "BATTERY_POWER_SIGN": (
                "positive_charge"
                if leading["battery_positive_likely_means"] == "charge"
                else "positive_discharge"
            ),
            "SIGN_CONVENTION_CONFIDENCE": "high",
            "SIGN_CONVENTION_SUPPORTING_SAMPLES": len(complete),
        }
    return {
        "sample_count": len(complete),
        "excluded_incomplete_samples": len(rows) - len(complete),
        "hypotheses": ranked,
        "leading_hypothesis": ranked[0] if complete else None,
        "confidence": confidence,
        "best_vs_second_improvement_percent": improvement_percent,
        "battery_mode_evidence": mode_summary,
        "suggested_configuration": suggestion,
        "disclaimer": (
            "Statistical hypothesis only; no sign convention was selected or stored."
        ),
    }
