"""Runner -> shared adapter -> pinned SDK -> mock transport -> real offline child."""

import asyncio
import builtins
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from energy_optimizer import jev_runner as runner
from energy_optimizer.ai_panel import EnergyPanelAdapter
from energy_optimizer.jev_offline_adapter import SDK_SOURCE_SHA256, checked_sdk_digest


def artifacts(*, cap="0.13", change=None):
    manifest = runner.manifest_template(str(uuid4()), cap)
    manifest.update(
        transport="offline_shared_adapter", sdk_source_sha256=SDK_SOURCE_SHA256
    )
    manifest.update(change or {})
    payload = json.dumps(manifest).encode()
    approval = json.dumps(
        {
            "approval": "APPROVE_OFFLINE_JEV_REHEARSAL",
            "manifest_sha256": hashlib.sha256(payload).hexdigest(),
            "max_cost_usd": cap,
        }
    ).encode()
    return payload, approval, manifest["experiment_id"]


@pytest.fixture
def sdk():
    client = pytest.importorskip("panel_client")
    if client.__version__ != "1.0.4":
        pytest.skip("Shared adapter rehearsal requires pinned SDK 1.0.4")
    return client


def test_missing_sdk_refuses_before_claim_or_child(tmp_path, monkeypatch):
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name.startswith("panel_"):
            raise ModuleNotFoundError("private package detail")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    payload, approval, _ = artifacts()
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert not list(tmp_path.iterdir())


def test_exact_published_sdk_and_manifest_transport_bound(sdk):
    assert checked_sdk_digest() == SDK_SOURCE_SHA256
    manifest = runner.manifest_template(
        str(uuid4()), transport="offline_shared_adapter"
    )
    assert manifest["sdk_source_sha256"] == SDK_SOURCE_SHA256
    assert manifest["transport"] == "offline_shared_adapter"


@pytest.mark.parametrize(
    "change", [{"sdk_source_sha256": "0" * 64}, {"transport": "live"}]
)
def test_bad_binding_refused_before_resources(sdk, tmp_path, change):
    payload, approval, _ = artifacts(change=change)
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert not list(tmp_path.iterdir())


def test_wrong_sdk_refused_before_resources(sdk, tmp_path, monkeypatch):
    payload, approval, _ = artifacts()
    monkeypatch.setattr(sdk, "__version__", "1.0.3")
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert not list(tmp_path.iterdir())


def test_transport_cannot_change_after_approval(sdk, tmp_path):
    payload, approval, _ = artifacts()
    changed = json.loads(payload)
    changed.update(transport="offline_pipe", sdk_source_sha256=None)
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(json.dumps(changed).encode(), approval, tmp_path))
    assert not list(tmp_path.iterdir())


def test_modified_sdk_source_refused_without_writing_package(
    sdk, tmp_path, monkeypatch
):
    payload, approval, _ = artifacts()
    read = Path.read_bytes

    def altered(path):
        data = read(path)
        return (
            data + b"# changed" if path.name == "panel_energy_challenger.py" else data
        )

    monkeypatch.setattr(Path, "read_bytes", altered)
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert not list(tmp_path.iterdir())


def test_complete_actual_adapter_sdk_path_never_creates_socket_transport(
    sdk, tmp_path, monkeypatch
):
    import httpx

    adapter_calls, sdk_calls, bodies = [], [], []
    adapter_method = EnergyPanelAdapter.review_jev_evaluation_case
    sdk_method = sdk.AsyncPanelClient.review_energy_jev_case
    pipe = runner._exchange

    async def counted_adapter(self, *args, **kwargs):
        adapter_calls.append(args[0])
        return await adapter_method(self, *args, **kwargs)

    async def counted_sdk(self, *args, **kwargs):
        sdk_calls.append(args[0])
        return await sdk_method(self, *args, **kwargs)

    async def counted_pipe(process, nonce, request):
        bodies.append(request.copy())
        return await pipe(process, nonce, request)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("A network transport must never be constructed")

    monkeypatch.setattr(
        EnergyPanelAdapter, "review_jev_evaluation_case", counted_adapter
    )
    monkeypatch.setattr(sdk.AsyncPanelClient, "review_energy_jev_case", counted_sdk)
    monkeypatch.setattr(runner, "_exchange", counted_pipe)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden_network)
    monkeypatch.setenv("HTTPS_PROXY", "http://not-a-real-proxy.invalid:1")
    payload, approval, _ = artifacts()
    report = asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert report["status"] == "completed"
    assert len(adapter_calls) == len(sdk_calls) == len(bodies) == 48
    assert adapter_calls == sdk_calls == [f"h{i:02d}" for i in range(1, 49)]
    assert all(
        set(body)
        == {
            "task_version",
            "adapter_version",
            "case_id",
            "operation_id",
            "experiment_id",
            "manifest_sha256",
        }
        for body in bodies
    )
    assert report["transport"] == "offline_shared_adapter"
    assert (
        report["ledger_reconciled"]
        and report["child_stopped"]
        and report["grant_revoked"]
    )
    assert report["live_calls"] == 0 and report["actual_cost_usd"] is None
    assert all(row["execution"] == "offline_simulation" for row in report["results"])
    assert "cloud_evaluation" not in json.dumps(report)
    with pytest.raises(runner.RunnerRefused):
        asyncio.run(runner.rehearse(payload, approval, tmp_path))


@pytest.mark.parametrize(
    "fault", ["correlation", "probabilities", "timeout", "wrong_mode"]
)
def test_shared_path_failure_stops_without_retry(sdk, tmp_path, monkeypatch, fault):
    original = runner._exchange
    calls = []

    async def broken(process, nonce, request):
        calls.append(request)
        if fault == "timeout":
            raise TimeoutError()
        value = await original(process, nonce, request)
        if fault == "correlation":
            value["experiment_id"] = str(uuid4())
        elif fault == "probabilities":
            value["raw_typed_answer"]["probabilities"]["needs_review"] = 0.5
        else:
            value["execution"] = "cloud_evaluation"
        return value

    monkeypatch.setattr(runner, "_exchange", broken)
    payload, approval, _ = artifacts()
    report = asyncio.run(runner.rehearse(payload, approval, tmp_path))
    assert len(calls) == 1
    assert report["status"] == "partial"
    assert report["reserved_usd"] == "0.002688"
    assert report["results"][0]["status"] == "unknown"
    assert (
        report["ledger_reconciled"]
        and report["child_stopped"]
        and report["grant_revoked"]
    )


def test_cancellation_through_shared_adapter_keeps_unknown_and_cleans(
    sdk, tmp_path, monkeypatch
):
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
        assert report["results"][0]["status"] == "unknown"
        assert report["child_stopped"] and report["grant_revoked"]

    asyncio.run(scenario())
