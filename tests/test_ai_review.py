import asyncio
import copy
import json
from dataclasses import replace
from uuid import uuid4, uuid5

import pytest

pytest.importorskip("panel_energy_review")
import test_ai_panel as panel_tests  # noqa: E402
from panel_energy_review import (  # noqa: E402
    CASES,
    DATASET_HASH,
    PATH,
    POLICY,
    TASK,
    VERSION,
)

from energy_optimizer.ai_integration import AIUnavailable  # noqa: E402
from energy_optimizer.ai_review import offline_report, run_replay  # noqa: E402

adapter = panel_tests.adapter


@pytest.fixture
def settings(tmp_path):
    return panel_tests.settings.__wrapped__(tmp_path)


@pytest.fixture
def wire():
    return panel_tests.wire.__wrapped__()


def task_wire(wire, case_id, operation):
    value = {
        "status": "shadow",
        "task": TASK,
        "task_version": VERSION,
        "dataset_sha256": DATASET_HASH,
        "policy_version": POLICY,
        "case_id": case_id,
        "operation_id": str(operation),
        "route": "bounded-local",
        "execution": "local",
        "provider": "local",
        "model": "Mapika/decider-4b",
        "model_revision": "eb5fbdfc9448473ec25e399882912863afbdb70e",
        "cloud_fallback": False,
        "no_command_issued": True,
        "metadata_delivery": "accepted",
        "trace_id": str(uuid4()),
        "event_id": str(uuid4()),
        "input_tokens": 20,
        "latency_ms": 2,
        "answers": {
            "review": {
                "type": "choice",
                "choice": "supported",
                "confidence": 1.0,
                "probabilities": {
                    "supported": 1.0,
                    "needs_review": 0.0,
                    "insufficient_evidence": 0.0,
                },
            }
        },
    }
    wire[PATH] = value
    wire["/v1/integration/capabilities"]["tasks"] = [
        {
            "task": TASK,
            "task_version": VERSION,
            "path": PATH,
            "mode": "synthetic_shadow",
            "dataset_sha256": DATASET_HASH,
            "authorised": True,
            "policy_enabled": True,
            "route": "bounded-local",
            "execution": "local",
            "paid_budget_usd": 0,
            "accepts_household_data": False,
            "automatic_escalation": False,
        }
    ]
    return value


def test_actual_sdk_sends_case_only_and_panel_selects_route(settings, wire):
    operation = uuid4()
    task_wire(wire, "supported_home", operation)
    calls = []
    result = asyncio.run(
        adapter(settings, wire, calls).review_synthetic_case(
            "supported_home", operation
        )
    )
    assert result["status"] == "shadow"
    assert json.loads(calls[-1].content) == {
        "task_version": VERSION,
        "case_id": "supported_home",
        "operation_id": str(operation),
    }
    assert [r.method for r in calls] == ["GET", "GET", "POST"]
    assert calls[-1].url.path == PATH


@pytest.mark.parametrize(
    "change", ["missing", "denied", "cloud", "hash", "paused", "unhealthy"]
)
def test_discovery_blocks_before_post(settings, wire, change):
    operation = uuid4()
    task_wire(wire, "supported_home", operation)
    catalogue = wire["/v1/integration/capabilities"]
    task = catalogue["tasks"][0]
    if change == "missing":
        catalogue["tasks"] = []
    elif change == "denied":
        task["authorised"] = False
    elif change == "cloud":
        task["execution"] = "cloud"
    elif change == "hash":
        task["dataset_sha256"] = "wrong"
    elif change == "paused":
        catalogue["paused"] = True
    else:
        catalogue["capabilities"][0]["health"]["ready"] = False
    calls = []
    with pytest.raises(AIUnavailable):
        asyncio.run(
            adapter(settings, wire, calls).review_synthetic_case(
                "supported_home", operation
            )
        )
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("environment", ["test", "production"])
def test_no_production_or_test_network(settings, wire, environment):
    calls = []
    with pytest.raises(AIUnavailable):
        asyncio.run(
            adapter(
                replace(settings, environment=environment), wire, calls
            ).review_synthetic_case("supported_home", uuid4())
        )
    assert not calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "unknown"),
        ("operation_id", str(uuid4())),
        ("case_id", "stale_soc"),
        ("metadata_delivery", "pending"),
        ("cloud_fallback", True),
        ("task_version", "2.0.0"),
    ],
)
def test_bad_receipts_are_redacted_and_not_retried(settings, wire, field, value):
    operation = uuid4()
    task_wire(wire, "supported_home", operation)[field] = value
    calls = []
    with pytest.raises(AIUnavailable):
        asyncio.run(
            adapter(settings, wire, calls).review_synthetic_case(
                "supported_home", operation
            )
        )
    assert sum(r.method == "POST" for r in calls) == 1


def test_offline_labels_and_no_model_accuracy_claim():
    report = offline_report()
    assert report["cases"] == report["baseline_correct"] == 8
    assert report["model_completed"] == 0
    assert report["model_accuracy_completed"] is None
    assert report["reported_input_tokens"] is None


def test_replay_retains_uuid_and_counts_wrong_model_answer(settings, wire):
    root = uuid4()
    ids = []

    class Replay:
        async def review_synthetic_case(self, case_id, operation):
            ids.append(operation)
            return copy.deepcopy(task_wire(wire, case_id, operation))

    report = asyncio.run(run_replay(settings, root, adapter=Replay()))
    assert ids == [
        uuid5(root, f"battery-review-v1:{DATASET_HASH}:{case}") for case in CASES
    ]
    assert report["model_completed"] == 8
    assert report["model_correct"] == 2
    reserve = next(
        row for row in report["results"] if row["case_id"] == "reserve_violation"
    )
    assert reserve["model_review"] == "supported"
    assert reserve["review_disposition"] == "needs_review"
    assert reserve["confidence"] == 1.0
    assert report["reported_input_tokens"] == 160
    assert report["no_command_issued"] and not report["active_routing_enabled"]
    assert all(
        case["state"]["evidence"] not in json.dumps(report) for case in CASES.values()
    )
    previous = list(ids)
    ids.clear()
    asyncio.run(run_replay(settings, root, adapter=Replay()))
    assert ids == previous


def test_failed_discovery_stops_batch_with_unknown_quality(settings, wire):
    report = asyncio.run(
        run_replay(settings, uuid4(), adapter=adapter(settings, wire, []))
    )
    assert report["model_completed"] == 0
    assert report["model_failures"] == 1 and report["not_attempted"] == 7
    assert report["results"][0]["failure"] == "handoff_pending"
