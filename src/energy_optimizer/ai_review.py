"""Manual synthetic evaluation only. Never imported by the collector or dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from energy_optimizer.ai_integration import AISettings, AIUnavailable

TASK_CONTRACT_COMMIT = "4c821193f4c406ddedcc077fd29459e3c435c98d"


class ReviewCapability(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    task: Literal["battery-decision-review"]
    task_version: Literal["1.0.0"]
    path: Literal["/v1/integration/tasks/battery-review"]
    mode: Literal["synthetic_shadow"]
    dataset_sha256: str
    authorised: bool
    policy_enabled: bool
    route: Literal["bounded-local"]
    execution: Literal["local"]
    paid_budget_usd: Literal[0]
    accepts_household_data: Literal[False]
    automatic_escalation: Literal[False]


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str
    operation_id: str | None = None
    expected: str
    baseline: str
    baseline_correct: bool
    status: Literal["not_run", "shadow", "duplicate", "unavailable", "failed"]
    failure: str | None = None
    model_review: str | None = None
    review_disposition: str | None = None
    model_correct: bool | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    elapsed_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    worker_latency_ms: int | None = Field(default=None, ge=0, le=120000)
    input_tokens: int | None = Field(default=None, ge=0, le=100000)
    trace_id: str | None = None
    event_id: str | None = None
    route: str | None = None
    provider: str | None = None
    model: str | None = None
    model_revision: str | None = None


def dataset() -> tuple[dict, str]:
    """Load only the pinned provider package, not a mutable sibling repository."""
    import panel_client
    from panel_energy_review import CASES, DATASET_HASH

    if panel_client.__version__ != "1.0.2":
        raise ValueError("Synthetic review requires pinned SDK 1.0.2")
    return CASES, DATASET_HASH


def offline_report() -> dict:
    from panel_energy_review import baseline

    cases, digest = dataset()
    return make_report(
        [
            CaseResult(
                case_id=case_id,
                expected=case["expected"],
                baseline=baseline(case_id),
                baseline_correct=baseline(case_id) == case["expected"],
                status="not_run",
            )
            for case_id, case in cases.items()
        ],
        digest,
        None,
    )


def make_report(rows: list[CaseResult], digest: str, operation_id: UUID | None) -> dict:
    completed = [row for row in rows if row.status == "shadow"]
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "task": "battery-decision-review",
        "task_version": "1.0.0",
        "task_contract_commit": TASK_CONTRACT_COMMIT,
        "dataset_sha256": digest,
        "operation_id": str(operation_id) if operation_id else None,
        "mode": "synthetic_development_replay",
        "cases": len(rows),
        "baseline_correct": sum(row.baseline_correct for row in rows),
        "model_completed": len(completed),
        "model_correct": sum(row.model_correct is True for row in completed),
        "model_accuracy_completed": (
            sum(row.model_correct is True for row in completed) / len(completed)
            if completed
            else None
        ),
        "model_failures": sum(
            row.status in {"unavailable", "failed", "duplicate"} for row in rows
        ),
        "reported_input_tokens": (
            sum(row.input_tokens or 0 for row in completed) if completed else None
        ),
        "total_elapsed_ms": (
            sum(row.elapsed_ms or 0 for row in rows) if operation_id else None
        ),
        "paid_budget_usd": 0,
        "local_electricity_cost": "unknown",
        "calibration": "unverified",
        "economic_decision_quality": "not evaluated",
        "savings": "not established",
        "active_routing_enabled": False,
        "production_data_sent": False,
        "no_command_issued": True,
        "results": [row.model_dump() for row in rows],
    }


async def run_replay(settings: AISettings, operation_id: UUID, *, adapter=None) -> dict:
    from panel_energy_review import baseline, checked_result

    from energy_optimizer.ai_panel import EnergyPanelAdapter

    cases, digest = dataset()
    adapter = adapter or EnergyPanelAdapter(settings)
    rows = []
    for case_id, case in cases.items():
        # A caller retains the root ID; uncertain cases never receive new IDs on rerun.
        case_operation = uuid5(operation_id, f"battery-review-v1:{digest}:{case_id}")
        fields = dict(
            case_id=case_id,
            operation_id=str(case_operation),
            expected=case["expected"],
            baseline=baseline(case_id),
            baseline_correct=baseline(case_id) == case["expected"],
        )
        started = perf_counter()
        try:
            value = await adapter.review_synthetic_case(case_id, case_operation)
            if value.get("case_id") != case_id:
                raise ValueError("Wrong case receipt")
            checked_result(value, str(case_operation))
            status = value["status"]
            answer = (
                value.get("answers", {}).get("review", {}) if status == "shadow" else {}
            )
            result = CaseResult(
                **fields,
                status=status,
                model_review=answer.get("choice"),
                review_disposition=(
                    (
                        baseline(case_id)
                        if baseline(case_id) != "supported"
                        else answer.get("choice")
                    )
                    if status == "shadow"
                    else None
                ),
                model_correct=(
                    (answer["choice"] == case["expected"]) if answer else None
                ),
                probabilities=answer.get("probabilities"),
                confidence=answer.get("confidence"),
                worker_latency_ms=value.get("latency_ms"),
                input_tokens=value.get("input_tokens"),
                trace_id=str(UUID(value["trace_id"])),
                event_id=str(UUID(value["event_id"])) if "event_id" in value else None,
                route=value["route"],
                provider=value["provider"],
                model=value["model"],
                model_revision=value["model_revision"],
            )
        except AIUnavailable as exc:
            result = CaseResult(**fields, status="failed", failure=exc.reason.value)
        except (ValueError, KeyError, TypeError):
            result = CaseResult(**fields, status="failed", failure="invalid_response")
        result.elapsed_ms = round((perf_counter() - started) * 1000, 3)
        rows.append(result)
        # Stop after a failed request; do not repeat a discovery/transport failure.
        if result.status == "failed":
            break
    report = make_report(rows, digest, operation_id)
    report["dataset_cases"] = len(cases)
    report["not_attempted"] = len(cases) - len(rows)
    return report
