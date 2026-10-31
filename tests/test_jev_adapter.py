"""Synthetic Jev contract tests; no provider, credentials or live discovery."""

import asyncio
import builtins
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from energy_optimizer.ai_integration import AIFailure, AISettings, AIUnavailable
from energy_optimizer.ai_panel import EnergyPanelAdapter


@pytest.fixture
def settings(tmp_path):
    return AISettings(
        enabled=True,
        environment="test",
        base_url="http://127.0.0.1:8787",
        key_file=tmp_path / "runtime-test.key",
    )


def invoke(adapter):
    return asyncio.run(
        adapter.review_jev_evaluation_case(
            "h01", uuid4(), experiment_id=uuid4(), manifest_sha256="a" * 64
        )
    )


@pytest.mark.parametrize(
    "environment,base_url,enabled,expected",
    [
        ("test", "http://127.0.0.1:8787", False, AIFailure.DISABLED),
        ("development", "http://127.0.0.1:8787", True, AIFailure.POLICY_DENIED),
        ("production", "http://127.0.0.1:8787", True, AIFailure.POLICY_DENIED),
        ("test", "https://example.invalid", True, AIFailure.POLICY_DENIED),
        ("test", "http://127.0.0.1:8787", True, AIFailure.UNAVAILABLE),
    ],
)
def test_guards_work_without_optional_sdk(
    settings, monkeypatch, environment, base_url, enabled, expected
):
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name.startswith("panel_"):
            raise ModuleNotFoundError("synthetic private upstream detail")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)

    async def forbidden_factory(_settings):
        raise AssertionError("No client may be created")

    candidate = EnergyPanelAdapter(
        replace(settings, environment=environment, base_url=base_url, enabled=enabled),
        client_factory=forbidden_factory,
    )
    with pytest.raises(AIUnavailable) as exc:
        invoke(candidate)
    assert exc.value.reason == expected
    assert "private" not in str(exc.value)


def test_wrong_sdk_fails_before_client_creation(settings, monkeypatch):
    sdk = pytest.importorskip("panel_client")
    monkeypatch.setattr(sdk, "__version__", "1.0.3")
    calls = []

    async def forbidden_factory(_settings):
        calls.append("created")
        raise AssertionError("Wrong SDK cannot create a client")

    with pytest.raises(AIUnavailable) as exc:
        invoke(EnergyPanelAdapter(settings, client_factory=forbidden_factory))
    assert exc.value.reason == AIFailure.POLICY_DENIED
    assert not calls


@pytest.fixture
def wire_adapter(settings):
    sdk = pytest.importorskip("panel_client")
    if sdk.__version__ != "1.0.4":
        pytest.skip("Jev wire tests require pinned SDK 1.0.4")
    httpx = pytest.importorskip("httpx")
    frozen = pytest.importorskip("panel_energy_review_holdout")
    calls = []

    def make(*, alteration=None, status=200, timeout=False):
        async def factory(_settings):
            def transport(request):
                calls.append(request)
                if timeout:
                    raise httpx.ReadTimeout("private detail", request=request)
                receipt = {
                    **json.loads(request.content),
                    "status": "completed",
                    "policy_version": "energy-review-jev-evaluation-v1",
                    "dataset_sha256": frozen.DATASET_HASH,
                    "question_sha256": frozen.QUESTION_HASH,
                    "provider": "typesafe",
                    "requested_model": "jev-1.13.0",
                    "provider_reported_model": "jev-1.13.0",
                    "execution": "cloud_evaluation",
                    "no_command_issued": True,
                    "cloud_fallback": False,
                    "event_id": str(uuid4()),
                    "request_id": str(uuid4()),
                    "raw_typed_answer": {
                        "type": "choice",
                        "choice": "supported",
                        "probabilities": {
                            "supported": 1.0,
                            "needs_review": 0.0,
                            "insufficient_evidence": 0.0,
                        },
                    },
                    "reported_usage": None,
                }
                if alteration:
                    receipt.update(alteration)
                return httpx.Response(status, json=receipt)

            client = sdk.AsyncPanelClient(settings.base_url, "synthetic-test-key")
            await client.close()
            client.http = httpx.AsyncClient(
                base_url=settings.base_url, transport=httpx.MockTransport(transport)
            )
            return client

        return EnergyPanelAdapter(settings, client_factory=factory)

    return make, calls


def test_jev_exact_request_without_discovery_or_invented_usage(wire_adapter):
    make, calls = wire_adapter
    report = invoke(make())
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].url.path == "/v1/evaluation/energy-review-jev"
    body = json.loads(calls[0].content)
    assert set(body) == {
        "task_version",
        "adapter_version",
        "case_id",
        "operation_id",
        "experiment_id",
        "manifest_sha256",
    }
    assert body["case_id"] == "h01"
    assert body["task_version"] == "1.1.0"
    assert body["adapter_version"] == "1.0.0"
    assert report["reported_usage"] is None
    assert "confidence" not in report["raw_typed_answer"]


@pytest.mark.parametrize(
    "alteration",
    [
        {"operation_id": str(uuid4())},
        {"experiment_id": str(uuid4())},
        {"manifest_sha256": "b" * 64},
        {"provider": "substituted"},
        {"no_command_issued": False},
        {"raw_typed_answer": {"choice": "supported"}},
    ],
)
def test_invalid_receipt_rejected_once(wire_adapter, alteration):
    make, calls = wire_adapter
    with pytest.raises(AIUnavailable) as exc:
        invoke(make(alteration=alteration))
    assert exc.value.reason == AIFailure.INVALID_RESPONSE
    assert len(calls) == 1


@pytest.mark.parametrize("options", [{"status": 503}, {"timeout": True}])
def test_transport_failure_has_no_retry_or_fallback(wire_adapter, options):
    make, calls = wire_adapter
    with pytest.raises(AIUnavailable) as exc:
        invoke(make(**options))
    assert exc.value.reason == AIFailure.UNAVAILABLE
    assert "private" not in str(exc.value)
    assert len(calls) == 1
