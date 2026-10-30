import asyncio
import copy
import json
from uuid import uuid4

import pytest

pytest.importorskip("panel_energy_review_holdout")
import test_ai_review as pilot_tests  # noqa: E402
from panel_energy_review_holdout import CASES, DATASET_HASH, PATH, VERSION  # noqa: E402

from energy_optimizer.ai_integration import AIUnavailable  # noqa: E402
from energy_optimizer.ai_review import offline_report, run_replay  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return pilot_tests.settings.__wrapped__(tmp_path)


@pytest.fixture
def wire():
    return pilot_tests.wire.__wrapped__()


def holdout_wire(wire, case_id, operation):
    result = copy.deepcopy(pilot_tests.task_wire(wire, "supported_home", operation))
    result.update(task_version=VERSION, dataset_sha256=DATASET_HASH, case_id=case_id)
    wire[PATH] = result
    task = copy.deepcopy(wire["/v1/integration/capabilities"]["tasks"][0])
    task.update(task_version=VERSION, dataset_sha256=DATASET_HASH, path=PATH)
    wire["/v1/integration/capabilities"]["tasks"].append(task)
    return result


def test_holdout_sdk_only_sends_frozen_case_and_selects_matching_version(
    settings, wire
):
    operation = uuid4()
    holdout_wire(wire, "h01", operation)
    calls = []
    result = asyncio.run(
        pilot_tests.adapter(settings, wire, calls).review_synthetic_case(
            "h01", operation, suite="holdout"
        )
    )
    assert result["task_version"] == VERSION
    assert calls[-1].url.path == PATH
    assert json.loads(calls[-1].content) == {
        "case_id": "h01",
        "task_version": VERSION,
        "operation_id": str(operation),
    }
    assert len(calls) == 3


def test_no_automatic_upgrade_to_holdout_when_catalogue_lacks_it(settings, wire):
    operation = uuid4()
    pilot_tests.task_wire(wire, "supported_home", operation)
    calls = []
    with pytest.raises(AIUnavailable):
        asyncio.run(
            pilot_tests.adapter(settings, wire, calls).review_synthetic_case(
                "h01", operation, suite="holdout"
            )
        )
    assert all(request.method == "GET" for request in calls)


def test_offline_reference_and_label_provenance_are_explicit():
    report = offline_report("holdout")
    assert report["cases"] == 48 and report["baseline_correct"] == 44
    assert report["strata"]["numeric"]["baseline_correct"] == 40
    assert report["strata"]["narrative"]["baseline_correct"] == 4
    assert report["model_completed"] == 0
    assert {row["label_source"] for row in report["results"]} == {
        "scenario_specification",
        "author_specification_not_expert_reviewed",
    }


def test_confident_false_support_fails_gate_and_numeric_floor_is_preserved(
    settings, wire
):
    class Worker:
        async def review_synthetic_case(self, case_id, operation, *, suite):
            assert suite == "holdout"
            return copy.deepcopy(holdout_wire(wire, case_id, operation))

    report = asyncio.run(
        run_replay(settings, uuid4(), adapter=Worker(), suite="holdout")
    )
    assert report["model_completed"] == 48
    assert report["false_supported"] > 0 and not report["model_gate_passed"]
    reserve = next(row for row in report["results"] if row["case_id"] == "h17")
    assert reserve["model_review"] == "supported" and reserve["confidence"] == 1.0
    assert reserve["review_disposition"] == "needs_review"
    narrative = next(row for row in report["results"] if row["case_id"] == "h41")
    assert (
        narrative["baseline"] == "needs_review"
        and narrative["review_disposition"] == "supported"
    )
    assert not report["active_routing_enabled"] and not report["activation_gate_passed"]
    assert report["independent_expert_label_review"] == "pending"
    assert all(
        case["state"]["proposal_explanation"] not in json.dumps(report)
        for case in CASES.values()
    )


def test_exhausted_evaluation_deadline_prevents_new_inference(settings, monkeypatch):
    import energy_optimizer.ai_review as review

    times = iter([0.0, 121.0, 121.0, 121.0])
    monkeypatch.setattr(review, "perf_counter", lambda: next(times))

    class Worker:
        async def review_synthetic_case(self, *args, **kwargs):
            pytest.fail("Deadline exhausted before admission")

    report = asyncio.run(
        run_replay(settings, uuid4(), adapter=Worker(), suite="holdout")
    )
    assert report["model_completed"] == 0
    assert report["not_attempted"] == 47
    assert report["results"][0]["failure"] == "evaluation_deadline"
    assert not report["model_gate_passed"]
