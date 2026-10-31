"""Offline historical training populations; no mutable repository fallback."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool

from energy_optimizer.demand_forecast import forecast_household_demand
from energy_optimizer.timestamps import aware_datetime, json_safe

MAX_POPULATION_BYTES = 16 * 1024 * 1024


class _Observation(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    slot_utc: AwareDatetime
    observed_at_utc: AwareDatetime
    observed_at_local: AwareDatetime
    telemetry_is_healthy: StrictBool
    baseline_training_eligible: StrictBool
    baseline_house_consumption_w: float | None


class _Population(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["immutable-training-population-v1"]
    captured_at_utc: AwareDatetime
    source_id: str = Field(min_length=1, max_length=200)
    observations: list[_Observation] = Field(max_length=50000)


def freeze_training_population(
    rows: list[dict[str, Any]], *, captured_at: datetime, source_id: str
) -> bytes:
    """Seal explicitly supplied original rows, without reading any database.

    Caller must retain the digest in the original study manifest. A checksum
    establishes byte identity, not truth of capture time or source provenance.
    """
    payload = {
        "format": "immutable-training-population-v1",
        "captured_at_utc": aware_datetime(captured_at).astimezone(UTC).isoformat(),
        "source_id": source_id,
        "observations": rows,
    }
    # Reject naive capture/sample instants before legacy JSON helpers can infer UTC.
    _Population.model_validate(payload)
    data = json.dumps(json_safe(payload), sort_keys=True, allow_nan=False).encode()
    load_frozen_training_population(
        data, expected_sha256=hashlib.sha256(data).hexdigest(), decision_at=captured_at
    )
    return data


def load_frozen_training_population(
    data: bytes, *, expected_sha256: str, decision_at: datetime
) -> list[dict[str, Any]]:
    """Refuse late/changed populations; return detached original sample rows."""
    boundary = aware_datetime(decision_at).astimezone(UTC)
    if len(data) > MAX_POPULATION_BYTES:
        raise ValueError("Training population exceeds offline size limit")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Training population checksum mismatch")
    population = _Population.model_validate_json(data)
    if population.captured_at_utc > boundary:
        raise ValueError("Training population was captured after the decision")
    seen: set[datetime] = set()
    for row in population.observations:
        if row.slot_utc in seen:
            raise ValueError("Duplicate observation slot in training population")
        seen.add(row.slot_utc)
        if max(row.slot_utc, row.observed_at_utc) > population.captured_at_utc:
            raise ValueError("Observation follows population capture")
        if row.observed_at_local != row.observed_at_utc:
            raise ValueError("Observation timestamps disagree")
    # Parse afresh on every load: callers cannot mutate the retained bytes.
    return json.loads(data)["observations"]


def replay_demand_population(
    data: bytes,
    *,
    expected_sha256: str,
    decision_at: datetime,
    start_local: datetime,
    end_local: datetime,
    minimum_samples: int,
    fallback_kw: float,
) -> dict[str, Any]:
    """Run the existing estimator on verified original rows, never current data."""
    boundary = aware_datetime(decision_at).astimezone(UTC)
    if aware_datetime(start_local) < boundary:
        raise ValueError("Forecast start precedes the decision")
    if minimum_samples < 1 or fallback_kw < 0:
        raise ValueError("Invalid forecast assumptions")
    rows = load_frozen_training_population(
        data, expected_sha256=expected_sha256, decision_at=boundary
    )
    forecast = forecast_household_demand(
        rows,
        start_local=start_local,
        end_local=end_local,
        minimum_samples=minimum_samples,
        fallback_kw=fallback_kw,
    )
    return {
        "knowledge_time_policy": "immutable_original_population",
        "population_sha256": expected_sha256,
        "decision_at_utc": boundary.isoformat(),
        "provenance_verified": False,
        "no_command_issued": True,
        "forecast": forecast.model_dump(mode="json"),
    }
