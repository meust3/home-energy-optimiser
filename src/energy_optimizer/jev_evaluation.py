"""Offline comparison of supplied synthetic results; no SDK or network required."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from importlib.resources import files
from typing import Any


def reference() -> dict[str, Any]:
    """Frozen label/reference metadata, never a provider request or task state."""
    return json.loads(
        files("energy_optimizer").joinpath("jev_reference.json").read_text("utf-8")
    )


def family(case_id: str) -> str:
    index = int(case_id[1:]) - 1
    return (
        f"numeric_family_{index // 4 + 1:02d}"
        if index < 40
        else f"narrative_pair_{(index - 40) // 2 + 1}"
    )


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    valid = [
        r
        for r in rows
        if r.get(field) in {"supported", "needs_review", "insufficient_evidence"}
    ]
    nonsupported = sum(r["expected"] != "supported" for r in rows)
    return {
        "cases": len(rows),
        "valid": len(valid),
        "invalid": (
            sum(r.get("status") == "invalid" for r in rows) if field == "jev" else 0
        ),
        "failed": (
            sum(r.get("status") in {"failed", "attempting"} for r in rows)
            if field == "jev"
            else 0
        ),
        "unattempted": (
            sum(r.get("status") == "unattempted" for r in rows) if field == "jev" else 0
        ),
        "unattempted_or_failed": len(rows) - len(valid),
        "unknown": (
            sum(r.get("status") == "unknown" for r in rows) if field == "jev" else 0
        ),
        "correct": sum(r[field] == r["expected"] for r in valid),
        "correctness_percent_all_cases": (
            100 * sum(r[field] == r["expected"] for r in valid) / len(rows)
            if rows
            else None
        ),
        "false_support": sum(
            r["expected"] != "supported" and r[field] == "supported" for r in valid
        ),
        "false_support_denominator": nonsupported,
        "false_review": sum(
            r["expected"] == "supported" and r[field] == "needs_review" for r in valid
        ),
        "confusion": dict(Counter(f"{r['expected']} -> {r[field]}" for r in valid)),
    }


def compare(mapika: dict[str, Any], jev: dict[str, Any]) -> dict[str, Any]:
    """Score supplied artifacts; this does not attest execution or ledger identity."""
    frozen = reference()
    cases = frozen["cases"]
    for report in (mapika, jev):
        for field in ("task_version", "dataset_sha256", "question_sha256"):
            if field in report and report[field] != frozen[field]:
                raise ValueError("Artifact contract mismatch")

    if [r["case_id"] for r in mapika["results"]] != list(cases):
        raise ValueError("Retained result order mismatch")
    results = {r["case_id"]: r for r in jev["results"]}
    if len(results) != len(jev["results"]) or not set(results).issubset(cases):
        raise ValueError("Duplicate or unknown challenger case")
    rows = []
    for old in mapika["results"]:
        case_id = old["case_id"]
        if old["expected"] != cases[case_id]["expected"]:
            raise ValueError("Retained label mismatch")
        if old["stratum"] != cases[case_id]["stratum"]:
            raise ValueError("Retained stratum mismatch")
        current = results.get(case_id, {})
        answer = current.get("raw_typed_answer", {})
        status = current.get("status", "unattempted")
        if status not in {
            "completed",
            "failed",
            "attempting",
            "invalid",
            "unattempted",
            "unknown",
        }:
            raise ValueError("Unknown challenger status")
        labels = {"supported", "needs_review", "insufficient_evidence"}
        if old["model_review"] is not None and old["model_review"] not in labels:
            raise ValueError("Invalid retained choice")
        if status == "completed" and answer.get("choice") not in labels:
            raise ValueError("Invalid completed choice")
        confidence = answer.get("confidence") if status == "completed" else None
        if confidence is not None:
            _finite_number(confidence, maximum=1)
        rows.append(
            {
                "case_id": case_id,
                "family": family(case_id),
                "stratum": old["stratum"],
                "expected": old["expected"],
                "reference": cases[case_id]["reference"],
                "mapika": old["model_review"],
                "jev": (
                    answer.get("choice")
                    if current.get("status") == "completed"
                    else None
                ),
                "confidence": confidence,
                "status": status,
            }
        )
    summary = {}
    for group in ("all", "numeric", "narrative"):
        subset = rows if group == "all" else [r for r in rows if r["stratum"] == group]
        summary[group] = {
            name: metrics(subset, name) for name in ("reference", "mapika", "jev")
        }
    eligible = summary["all"]["jev"]
    gate = (
        eligible["valid"] == 48
        and eligible["false_support"] == 0
        and eligible["correct"] >= 44
        and summary["numeric"]["jev"]["correct"] >= 40
        and summary["narrative"]["jev"]["correct"] >= 4
    )
    confidences = {"correct": [], "incorrect": []}
    for row in rows:
        if row["confidence"] is not None:
            confidences[
                "correct" if row["jev"] == row["expected"] else "incorrect"
            ].append(row["confidence"])
    latencies = [
        _finite_number(r["consumer_latency_ms"])
        for r in jev["results"]
        if r.get("consumer_latency_ms") is not None
    ]
    elapsed = jev.get("batch_elapsed_ms")
    if elapsed is not None:
        _finite_number(elapsed)
    return {
        "task_version": frozen["task_version"],
        "dataset_sha256": frozen["dataset_sha256"],
        "question_sha256": frozen["question_sha256"],
        "reference_source_commit": frozen["source_commit"],
        "evidence_scope": "offline supplied artifacts; execution and ledger unverified",
        "simulation_only": jev.get("mode") == "offline_rehearsal",
        "comparison": summary,
        "cases": rows,
        "per_family": {
            key: {
                name: metrics([r for r in rows if r["family"] == key], name)
                for name in ("reference", "mapika", "jev")
            }
            for key in dict.fromkeys(r["family"] for r in rows)
        },
        "improved_vs_mapika": [
            r["case_id"]
            for r in rows
            if r["jev"] == r["expected"] and r["mapika"] != r["expected"]
        ],
        "regressed_vs_mapika": [
            r["case_id"]
            for r in rows
            if r["jev"] is not None
            and r["jev"] != r["expected"]
            and r["mapika"] == r["expected"]
        ],
        "confidence_descriptive_only": {
            k: {"n": len(v), "mean": statistics.mean(v) if v else None}
            for k, v in confidences.items()
        },
        "completed_case_coverage": eligible["valid"] == 48,
        "frozen_numerical_quality_gate_passed": summary["numeric"]["jev"]["correct"]
        == 40
        and summary["numeric"]["jev"]["false_support"] == 0,
        "frozen_narrative_comparison_passed": summary["narrative"]["jev"]["correct"]
        >= 4
        and summary["narrative"]["jev"]["false_support"] == 0,
        "paired_narrative_consistency": {
            key: {
                name: {
                    "returned_labels": [r[name] for r in rows if r["family"] == key],
                    "expected_labels": [
                        r["expected"] for r in rows if r["family"] == key
                    ],
                    "both_correct": all(
                        r[name] == r["expected"] for r in rows if r["family"] == key
                    ),
                }
                for name in ("reference", "mapika", "jev")
            }
            for key in dict.fromkeys(
                r["family"] for r in rows if r["stratum"] == "narrative"
            )
        },
        "batch_elapsed_ms": elapsed,
        "latency_ms": {
            "count": len(latencies),
            "minimum": min(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "mean": statistics.mean(latencies) if latencies else None,
            "maximum": max(latencies) if latencies else None,
        },
        "reported_usage_by_case": {
            r["case_id"]: _usage(r.get("reported_usage")) for r in jev["results"]
        },
        "cost": (
            "Requires matched test-ledger reconciliation; "
            "missing usage is unknown, never zero"
        ),
        "frozen_quality_gate_passed": gate,
        "independent_narrative_label_review": "pending",
        "production_activation": "NOT AUTHORISED",
        "benchmark": "exposed correlated regression/challenger benchmark",
    }


def _finite_number(value: Any, *, maximum: float = math.inf) -> float:
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= maximum
    ):
        raise ValueError("Invalid numeric evidence")
    return value


def _usage(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid usage evidence")
    result = {}
    for field in ("input_tokens", "output_tokens"):
        if field in value:
            count = value[field]
            if type(count) is not int or count < 0:
                raise ValueError("Invalid usage evidence")
            result[field] = count
    return result
