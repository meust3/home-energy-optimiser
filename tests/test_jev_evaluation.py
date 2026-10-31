"""Offline frozen comparison, including normal installations without a Panel SDK."""

import builtins
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from energy_optimizer.jev_evaluation import compare, reference

ROOT = Path(__file__).resolve().parents[1]
RETAINED = ROOT / "docs/integrations/ai-review-holdout-results-20261003.json"


@pytest.fixture
def retained():
    return json.loads(RETAINED.read_text(encoding="utf-8"))


def test_frozen_reference_mapika_metrics_without_sdk(retained, monkeypatch):
    original_import = builtins.__import__

    def no_sdk(name, *args, **kwargs):
        if name.startswith("panel_"):
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    summary = compare(retained, {"results": []})
    assert summary["comparison"]["numeric"]["reference"]["correct"] == 40
    assert summary["comparison"]["narrative"]["reference"]["correct"] == 4
    assert summary["comparison"]["all"]["mapika"]["correct"] == 16
    assert summary["comparison"]["all"]["mapika"]["false_support"] == 20
    assert summary["comparison"]["all"]["mapika"]["false_support_denominator"] == 36
    assert summary["comparison"]["all"]["jev"]["unattempted"] == 48
    assert summary["production_activation"] == "NOT AUTHORISED"
    assert not summary["frozen_quality_gate_passed"]
    assert not summary["completed_case_coverage"]
    assert len(summary["paired_narrative_consistency"]) == 4


def test_partial_results_remain_unknown_without_mutation(retained):
    challenger = {
        "results": [
            {
                "case_id": "h01",
                "status": "failed",
                "raw_typed_answer": {"choice": "supported", "confidence": 0.9},
            }
        ]
    }
    before = copy.deepcopy((retained, challenger))
    summary = compare(retained, challenger)
    counts = summary["comparison"]["all"]["jev"]
    assert counts["valid"] == 0 and counts["failed"] == 1
    assert counts["unattempted"] == 47 and counts["false_support"] == 0
    assert summary["confidence_descriptive_only"]["incorrect"]["n"] == 0
    assert summary["reported_usage_by_case"]["h01"] is None
    assert (retained, challenger) == before


def test_complete_synthetic_labels_never_authorize_activation(retained):
    challenger = {
        "results": [
            {
                "case_id": case_id,
                "status": "completed",
                "raw_typed_answer": {"choice": case["expected"]},
                "reported_usage": {"input_tokens": 2, "private_payload": "discard"},
            }
            for case_id, case in reference()["cases"].items()
        ]
    }
    report = compare(retained, challenger)
    assert report["frozen_quality_gate_passed"]
    assert report["completed_case_coverage"]
    assert report["production_activation"] == "NOT AUTHORISED"
    assert "unverified" in report["evidence_scope"]
    assert "discard" not in json.dumps(report)
    assert report["reported_usage_by_case"]["h01"] == {"input_tokens": 2}


@pytest.mark.parametrize(
    "challenger",
    [
        {"results": [{"case_id": "h01"}] * 2},
        {"results": [{"case_id": "unknown"}]},
        {"results": [], "dataset_sha256": "wrong"},
        {"results": [{"case_id": "h01", "status": "completed"}]},
        {"results": [{"case_id": "h01", "status": "success"}]},
        {"results": [], "batch_elapsed_ms": float("nan")},
    ],
)
def test_invalid_artifacts_rejected(retained, challenger):
    with pytest.raises(ValueError):
        compare(retained, challenger)


@pytest.mark.parametrize(
    "field,value", [("expected", "needs_review"), ("stratum", "narrative")]
)
def test_retained_label_and_stratum_cannot_change(retained, field, value):
    retained["results"][0][field] = value
    with pytest.raises(ValueError):
        compare(retained, {"results": []})


def test_optional_pinned_sdk_matches_frozen_reference():
    sdk = pytest.importorskip("panel_client")
    if sdk.__version__ != "1.0.4":
        pytest.skip("Fidelity check requires the project's pinned SDK 1.0.4")
    frozen = pytest.importorskip("panel_energy_review_holdout")
    snapshot = reference()
    assert snapshot["task_version"] == frozen.VERSION
    assert snapshot["dataset_sha256"] == frozen.DATASET_HASH
    assert snapshot["question_sha256"] == frozen.QUESTION_HASH
    assert snapshot["cases"] == {
        key: {
            "stratum": case["stratum"],
            "expected": case["expected"],
            "reference": frozen.baseline(key),
        }
        for key, case in frozen.CASES.items()
    }


def test_cli_reports_missing_challenger_and_preserves_existing_output(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "compare_jev_cli", ROOT / "tools/compare_jev.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    output = tmp_path / "report.json"
    args = ["--mapika", str(RETAINED), "--output", str(output)]
    assert cli.main(args) == 0
    before = output.read_bytes()
    assert json.loads(before)["comparison"]["all"]["jev"]["unattempted"] == 48
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    assert output.read_bytes() == before
