"""Decision-only contract. No outcome, runtime, storage or application imports."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime


def primitive(value):
    if hasattr(value, "__dataclass_fields__"):
        return primitive(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitive(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_numeric": repr(value)}
    return value


def canonical(value) -> str:
    return json.dumps(
        primitive(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Evidence:
    source_id: str
    version: str
    source_sha256: str
    issued_at: datetime
    available_at: datetime
    availability_kind: str
    availability_basis: str
    fresh_until: datetime
    freshness_basis: str
    healthy: bool
    issues: tuple[str, ...]


@dataclass(frozen=True)
class Point:
    start: datetime
    end: datetime
    value: float | None


@dataclass(frozen=True)
class Forecast:
    target: str
    unit: str
    interpretation: str
    basis: str
    evidence: Evidence
    points: tuple[Point, ...]


@dataclass(frozen=True)
class BranchState:
    at: datetime
    energy_kwh: float | None
    kind: str
    basis: str
    evidence: Evidence


@dataclass(frozen=True)
class Assumptions:
    profile_id: str
    capacity_kwh: float
    physical_min_kwh: float
    charge_efficiency: float
    discharge_efficiency: float
    charge_limit_kw: float
    discharge_limit_kw: float
    import_limit_kw: float
    export_limit_kw: float
    topology: str
    flow_domain: str
    stored_energy_domain: str
    pv_abstraction: str
    curtailment_permitted: bool
    interval_interpretation: str
    omitted_effects: tuple[str, ...]
    uncertainty: tuple[str, ...]
    evidence: Evidence


@dataclass(frozen=True)
class Reserve:
    at: datetime
    floor_kwh: float
    basis: str
    evidence: Evidence


@dataclass(frozen=True)
class DecisionContext:
    context_id: str
    data_origin: str
    decision_at: datetime
    evaluated_at: datetime
    ready_at: datetime
    cutoff: datetime
    readiness_basis: str
    branch: BranchState
    reserve: Reserve
    assumptions: Assumptions
    action_start: datetime
    action_end: datetime
    demand: Forecast | None
    pv: Forecast | None
    import_price: Forecast | None
    export_price: Forecast | None
    uncontrolled_load: Forecast | None


@dataclass(frozen=True)
class SelectionReceipt:
    """All nested content is canonical text, never a mutable outcome dictionary."""

    policy_version: str
    policy_sha256: str
    source_sha256: str
    input_sha256: str
    assumptions_sha256: str
    selected: str
    cutoff: datetime
    horizon_end: datetime | None
    reasons: tuple[str, ...]
    estimates_json: str
    coverage_json: str

    @property
    def sha256(self):
        return digest(self)


def _exact(cls, raw):
    if not isinstance(raw, dict) or set(raw) != {f.name for f in fields(cls)}:
        raise ValueError("contract_fields:" + cls.__name__)
    return dict(raw)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp_string_required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone_required")
    return result.astimezone(UTC)


def evidence_from_dict(raw):
    v = _exact(Evidence, raw)
    for k in ("issued_at", "available_at", "fresh_until"):
        v[k] = timestamp(v[k])
    v["issues"] = tuple(v["issues"])
    return Evidence(**v)


def forecast_from_dict(raw):
    if raw is None:
        return None
    v = _exact(Forecast, raw)
    v["evidence"] = evidence_from_dict(v["evidence"])
    points = []
    for p in v["points"]:
        p = _exact(Point, p)
        points.append(Point(timestamp(p["start"]), timestamp(p["end"]), p["value"]))
    v["points"] = tuple(points)
    return Forecast(**v)


def decision_from_dict(raw) -> DecisionContext:
    """Strict keys: actuals, scores and outcomes cannot enter this interface."""
    v = _exact(DecisionContext, raw)
    for k in (
        "decision_at",
        "evaluated_at",
        "ready_at",
        "cutoff",
        "action_start",
        "action_end",
    ):
        v[k] = timestamp(v[k])
    for k, cls in (
        ("branch", BranchState),
        ("reserve", Reserve),
        ("assumptions", Assumptions),
    ):
        child = _exact(cls, v[k])
        child["evidence"] = evidence_from_dict(child["evidence"])
        if k != "assumptions":
            child["at"] = timestamp(child["at"])
        else:
            child["omitted_effects"] = tuple(child["omitted_effects"])
            child["uncertainty"] = tuple(child["uncertainty"])
        v[k] = cls(**child)
    for k in ("demand", "pv", "import_price", "export_price", "uncontrolled_load"):
        v[k] = forecast_from_dict(v[k])
    return DecisionContext(**v)
