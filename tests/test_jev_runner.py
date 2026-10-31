"""Real offline child/ledger lifecycle and fault injection; no SDK or network."""

import asyncio
import hashlib
import importlib.util
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from energy_optimizer import jev_runner as runner


def artifacts(*, cap="0.13", change=None, approval_change=None):
    manifest = runner.manifest_template(str(uuid4()), cap)
    manifest.update(change or {})
    payload = json.dumps(manifest).encode()
    approval = {
        "approval": "APPROVE_OFFLINE_JEV_REHEARSAL",
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "max_cost_usd": cap,
    }
    approval.update(approval_change or {})
    return payload, json.dumps(approval).encode(), manifest["experiment_id"]


def execute(tmp_path, **kwargs):
    manifest, approval, identity = artifacts(**kwargs)
    report = asyncio.run(runner.rehearse(manifest, approval, tmp_path))
    return report, tmp_path / identity, manifest, approval


def test_real_child_complete_revoked_reconciled_and_no_restart(tmp_path):
    report, path, manifest, approval = execute(tmp_path)
    assert report["status"] == "completed"
    assert report["grant_revoked"] and report["child_stopped"]
    assert report["ledger_reconciled"]
    assert report["actual_cost_usd"] is None and report["live_calls"] == 0
    assert report["production_activation"] == "NOT AUTHORISED"
    assert report["reserved_usd"] == "0.129024"
    assert [r["case_id"] for r in report["results"]] == [
        f"h{i:02d}" for i in range(1, 49)
    ]
    assert all(r["reported_usage"] is None for r in report["results"])
    assert json.loads((path / "state.json").read_text()) == report
    with sqlite3.connect(path / "synthetic-ledger.sqlite3") as db:
        assert db.execute("SELECT revoked FROM grant_record").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM attempts").fetchone() == (48,)
    before = (path / "state.json").read_bytes()
    with pytest.raises(runner.RunnerRefused, match="restart"):
        asyncio.run(runner.rehearse(manifest, approval, tmp_path))
    assert (path / "state.json").read_bytes() == before


@pytest.mark.parametrize("cap", ["0", "-1", "1.01", "NaN", "Infinity"])
def test_bad_budget_refused_before_resources(tmp_path, cap):
    payload, approval, _ = artifacts(cap=cap)
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "0" * 64},
        {"fixture_sha256": "0" * 64},
        {"question_sha256": "0" * 64},
        {"mode": "live"},
        {"billing_evidence": "verified"},
        {"concurrency": True},
        {"fallback": 0},
        {"retries": 1},
        {"max_attempts": 49},
        {"base_url": "https://example.invalid"},
    ],
)
def test_manifest_mismatch_or_live_configuration_refused(tmp_path, change):
    payload, approval, _ = artifacts(change=change)
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "change",
    [
        {"manifest_sha256": "0" * 64},
        {"approval": "APPROVE_JEV_ENERGY_COMPARISON"},
        {"max_cost_usd": "1"},
    ],
)
def test_approval_is_exact_and_cannot_be_live_approval(tmp_path, change):
    payload, approval, _ = artifacts(approval_change=change)
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert not list(tmp_path.iterdir())


def test_reservations_prevent_fourth_dispatch(tmp_path):
    report, _, _, _ = execute(tmp_path, cap="0.01")
    assert len(report["results"]) == 3
    assert Decimal(report["reserved_usd"]) == 3 * runner.RESERVATION
    assert report["status"] == "partial"
    assert report["failure"] == "deadline_or_budget_exhausted"
    assert report["child_stopped"] and report["grant_revoked"]


def test_batch_deadline_stops_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "BATCH_SECONDS", 0)
    report, _, _, _ = execute(tmp_path)
    assert not report["results"]
    assert report["status"] == "partial"
    assert report["child_stopped"]


@pytest.mark.parametrize("fault", ["timeout", "malformed", "correlation", "exception"])
def test_uncertain_first_attempt_retains_reservation_and_stops(
    tmp_path, monkeypatch, fault
):
    original = runner._exchange
    calls = []

    async def broken(process, nonce, request):
        calls.append(request)
        if fault == "timeout":
            raise TimeoutError()
        if fault == "exception":
            raise RuntimeError("private upstream secret")
        value = await original(process, nonce, request)
        if fault == "malformed":
            value["raw_typed_answer"]["probabilities"]["supported"] = float("nan")
        else:
            value["operation_id"] = str(uuid4())
        return value

    monkeypatch.setattr(runner, "_exchange", broken)
    report, path, manifest, approval = execute(tmp_path)
    assert len(calls) == 1
    assert report["results"][0]["status"] == "unknown"
    assert Decimal(report["reserved_usd"]) == runner.RESERVATION
    assert report["ledger_reconciled"] and report["child_stopped"]
    assert "private" not in (path / "state.json").read_text()
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(manifest, approval, tmp_path))


def test_cancellation_preserves_unknown_and_cleans_up(tmp_path, monkeypatch):
    async def scenario():
        entered = asyncio.Event()

        async def hanging(*args):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(runner, "_exchange", hanging)
        payload, approval, identity = artifacts()
        task = asyncio.create_task(runner.rehearse(payload, approval, tmp_path))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        report = json.loads((tmp_path / identity / "state.json").read_text())
        assert report["status"] == "interrupted"
        assert report["grant_revoked"] and report["child_stopped"]
        assert report["results"][0]["status"] == "unknown"
        assert report["ledger_reconciled"]

    asyncio.run(scenario())


def test_ledger_failure_does_not_skip_child_cleanup(tmp_path, monkeypatch):
    def broken(*args):
        raise ValueError("private ledger content")

    monkeypatch.setattr(runner, "_reconcile", broken)
    report, _, _, _ = execute(tmp_path, cap="0.001")
    assert report["status"] == "cleanup_incomplete"
    assert report["child_stopped"] and report["grant_revoked"]
    assert report["cleanup_failure"] == "ledger_cleanup_failed"


def test_existing_claim_without_checkpoint_cannot_restart(tmp_path):
    payload, approval, identity = artifacts()
    (tmp_path / identity).mkdir()
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))


def test_repeated_cancellation_during_startup_cleans_owned_child(tmp_path, monkeypatch):
    original = runner._start_child
    processes = []

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_start(*args):
            process = await original(*args)
            processes.append(process)
            entered.set()
            await release.wait()
            return process

        monkeypatch.setattr(runner, "_start_child", slow_start)
        payload, approval, identity = artifacts()
        task = asyncio.create_task(runner.rehearse(payload, approval, tmp_path))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None
        report = json.loads((tmp_path / identity / "state.json").read_text())
        assert not report["results"]
        assert report["child_stopped"] and report["grant_revoked"]

    asyncio.run(scenario())


def test_concurrent_same_experiment_has_single_owner(tmp_path, monkeypatch):
    async def scenario():
        entered = asyncio.Event()

        async def hanging(*args):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(runner, "_exchange", hanging)
        payload, approval, identity = artifacts()
        first = asyncio.create_task(runner.rehearse(payload, approval, tmp_path))
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(runner.RunnerRefused):
            await runner.rehearse(payload, approval, tmp_path)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        report = json.loads((tmp_path / identity / "state.json").read_text())
        assert len(report["results"]) == 1

    asyncio.run(scenario())


def test_startup_failure_revokes_grant_without_submission(tmp_path, monkeypatch):
    async def failed(*args):
        raise OSError("private startup detail")

    monkeypatch.setattr(runner, "_start_child", failed)
    report, path, _, _ = execute(tmp_path)
    assert report["status"] == "partial"
    assert report["child_stopped"] and report["grant_revoked"]
    assert not report["results"]
    assert "private" not in (path / "state.json").read_text()


def test_failure_after_spawn_keeps_child_handle_for_final_cleanup(
    tmp_path, monkeypatch
):
    original = runner._start_child
    processes = []

    async def fail_after_spawn(*args):
        process = await original(*args)
        processes.append(process)
        raise OSError("Startup acknowledgement lost")

    monkeypatch.setattr(runner, "_start_child", fail_after_spawn)
    report, _, _, _ = execute(tmp_path)
    assert processes[0].returncode is not None
    assert report["child_stopped"] and report["grant_revoked"]
    assert report["status"] == "partial" and not report["results"]


def test_duplicate_event_cannot_complete_second_attempt(tmp_path, monkeypatch):
    original = runner._exchange
    event_id = str(uuid4())

    async def duplicate(*args):
        value = await original(*args)
        value["event_id"] = event_id
        return value

    monkeypatch.setattr(runner, "_exchange", duplicate)
    report, _, _, _ = execute(tmp_path)
    assert [r["status"] for r in report["results"]] == ["completed", "unknown"]
    assert report["status"] == "partial"
    assert report["ledger_reconciled"]


def test_cleanup_failure_cannot_claim_completion(tmp_path, monkeypatch):
    original = runner._stop_child

    async def uncertain_ack(process):
        await original(process)
        raise OSError("private cleanup detail")

    monkeypatch.setattr(runner, "_stop_child", uncertain_ack)
    report, _, _, _ = execute(tmp_path)
    assert report["status"] == "cleanup_incomplete"
    assert report["grant_revoked"]
    assert not report["child_stopped"]


def test_real_per_case_deadline_stops_hanging_exchange(tmp_path, monkeypatch):
    original = runner._start_child

    async def start(*args):
        process = await original(*args)
        monkeypatch.setattr(runner, "CASE_SECONDS", 0.05)
        return process

    async def hanging(*args):
        await asyncio.sleep(60)

    monkeypatch.setattr(runner, "_start_child", start)
    monkeypatch.setattr(runner, "_exchange", hanging)
    report, _, _, _ = execute(tmp_path)
    assert len(report["results"]) == 1
    assert report["results"][0]["status"] == "unknown"
    assert report["status"] == "partial" and report["child_stopped"]


def test_runtime_secrets_not_inherited_or_persisted(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    captured = []
    secret = "synthetic-unique-secret-must-stay-private"
    monkeypatch.setenv("HA_TOKEN", secret)
    monkeypatch.setenv("DATABASE_URL", secret)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda *_: secret)

    async def spawn(*args, **kwargs):
        captured.append(kwargs["env"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    report, path, _, _ = execute(tmp_path, cap="0.003")
    assert report["status"] == "partial"
    assert len(captured) == 1
    assert "HA_TOKEN" not in captured[0] and "DATABASE_URL" not in captured[0]
    assert all(
        secret.encode() not in p.read_bytes() for p in path.iterdir() if p.is_file()
    )


def test_cli_prepare_does_not_approve_or_overwrite_and_run_is_offline(tmp_path, capsys):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "rehearsal_cli", root / "tools/jev_rehearsal.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    path = tmp_path / "manifest.json"
    args = ["prepare", "--experiment-id", str(uuid4()), "--output", str(path)]
    assert cli.main(args) == 0
    before = path.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifest.json"]
    with pytest.raises(SystemExit):
        cli.main(args)
    assert path.read_bytes() == before
    approval = tmp_path / "offline-approval.json"
    approval.write_text(
        json.dumps(
            {
                "approval": "APPROVE_OFFLINE_JEV_REHEARSAL",
                "manifest_sha256": hashlib.sha256(before).hexdigest(),
                "max_cost_usd": "0.13",
            }
        )
    )
    assert (
        cli.main(
            [
                "run",
                "--manifest",
                str(path),
                "--approval",
                str(approval),
                "--registry",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["live_calls"] == 0 and report["status"] == "completed"
