"""Shared validation rules for persisted raw energy telemetry."""

MATERIAL_NEGATIVE_HOUSEHOLD_DEMAND_W = -1.0
INVALID_NEGATIVE_HOUSEHOLD_DEMAND = "invalid_negative_household_demand"
INVALID_ACTUAL_NEGATIVE_HOUSEHOLD_DEMAND = "invalid_actual_negative_household_demand"


def materially_negative_household_demand(value: float | None) -> bool:
    """Treat tiny sign/rounding noise as zero-compatible, not invalid telemetry."""
    return value is not None and float(value) < MATERIAL_NEGATIVE_HOUSEHOLD_DEMAND_W


def nonnegative_household_demand(value: float) -> float:
    """Normalize only already-validated sub-watt noise for analytical use."""
    if materially_negative_household_demand(value):
        raise ValueError(INVALID_NEGATIVE_HOUSEHOLD_DEMAND)
    return max(float(value), 0.0)
