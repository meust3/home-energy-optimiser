"""Isolated wire tests against the pinned SDK, never the live shared services."""

import asyncio
import json
import threading
import traceback
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

httpx = pytest.importorskip("httpx")
sdk = pytest.importorskip("panel_client")

from energy_optimizer.ai_integration import (  # noqa: E402
    AIFailure,
    AISettings,
    AIUnavailable,
    local_status,
)
from energy_optimizer.ai_panel import (  # noqa: E402
    EnergyPanelAdapter,
    read_status,
    save_status,
)


@pytest.fixture
def settings(tmp_path):
    return AISettings(
        enabled=True,
        environment="development",
        base_url="http://127.0.0.1:8787",
        key_file=tmp_path / "runtime-development.key",
        status_file=tmp_path / "status.json",
    )


@pytest.fixture
def wire():
    principal = str(uuid4())
    return {
        "/v1/integration/health": {
            "contract_version": "1.0.0",
            "status": "ready",
            "project": "home-energy",
            "principal": principal,
            "database": "reachable",
            "grant": {
                "caller": "application_backend",
                "environment": "development",
                "scopes": ["health:read", "capabilities:read", "decisions:local"],
            },
        },
        "/v1/integration/capabilities": {
            "contract_version": "1.0.0",
            "project": "home-energy",
            "principal": principal,
            "environment": "development",
            "caller": "application_backend",
            "paused": False,
            "cloud_fallback": False,
            "tools": [],
            "capabilities": [
                {
                    "profile": "bounded-local",
                    "implemented": True,
                    "authorised": True,
                    "policy_enabled": True,
                    "credential_ready": True,
                    "execution": "local",
                    "health": {"ready": True},
                }
            ],
        },
        "/v1/systemone": {
            "status": "shadow",
            "trace_id": str(uuid4()),
            "event_id": str(uuid4()),
            "metadata_delivery": "accepted",
            "input_tokens": 12,
            "answers": {"stale": {"type": "noul", "noul": 0.8}},
        },
    }


def adapter(settings, wire, calls, *, failure=None):
    async def factory(_settings):
        def transport(request):
            calls.append(request)
            if failure is not None:
                if isinstance(failure, Exception):
                    raise failure
                return httpx.Response(failure, text="sensitive upstream body")
            return httpx.Response(200, json=wire[request.url.path])

        client = sdk.AsyncPanelClient(settings.base_url, "synthetic-test-key")
        await client.close()
        client.http = httpx.AsyncClient(
            base_url=settings.base_url, transport=httpx.MockTransport(transport)
        )
        return client

    return EnergyPanelAdapter(settings, client_factory=factory)


def test_actual_sdk_serializes_only_synthetic_local_input(settings, wire):
    calls = []
    operation_id = uuid4()
    report = asyncio.run(adapter(settings, wire, calls).diagnose_local(operation_id))
    assert report.local_diagnostic == "shadow"
    assert report.metadata_delivery == "accepted"
    assert [r.url.path for r in calls] == list(wire)
    body = json.loads(calls[-1].content)
    assert body["input_kind"] == "synthetic_diagnostic"
    assert body["decision_provider"] == "local"
    assert body["operation_id"] == str(operation_id)
    assert "app_id" not in body
    save_status(settings, report)
    assert read_status(settings)["historical_snapshot"]
    assert read_status(replace(settings, environment="production")) is None
    settings.status_file.write_text('{"credential":"secret"}')
    assert read_status(settings) is None


@pytest.mark.parametrize(
    "code,reason",
    [
        (401, AIFailure.AUTHENTICATION),
        (403, AIFailure.POLICY_DENIED),
        (429, AIFailure.POLICY_DENIED),
        (422, AIFailure.INVALID_RESPONSE),
        (503, AIFailure.UNAVAILABLE),
    ],
)
def test_http_failure_redaction_no_retry(settings, wire, code, reason):
    calls = []
    with pytest.raises(AIUnavailable) as caught:
        asyncio.run(adapter(settings, wire, calls, failure=code).discover())
    assert caught.value.reason == reason
    assert "sensitive upstream body" not in "".join(
        traceback.format_exception(caught.value)
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change", ["paused", "unhealthy", "denied", "wrong_app", "wrong_caller", "cloud"]
)
def test_policy_and_identity_checks_prevent_inference(settings, wire, change):
    catalogue = wire["/v1/integration/capabilities"]
    if change == "paused":
        catalogue["paused"] = True
    elif change == "unhealthy":
        catalogue["capabilities"][0]["health"]["ready"] = False
    elif change == "denied":
        catalogue["capabilities"][0]["authorised"] = False
    elif change == "wrong_app":
        catalogue["project"] = "home-finance"
    elif change == "wrong_caller":
        catalogue["caller"] = "codex_build"
    else:
        catalogue["cloud_fallback"] = True
    calls = []
    with pytest.raises(AIUnavailable):
        asyncio.run(adapter(settings, wire, calls).diagnose_local(uuid4()))
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize(
    "change",
    ["bad_probability", "bad_trace", "bad_metadata", "unavailable", "missing_answer"],
)
def test_untrusted_responses_are_not_results(settings, wire, change):
    result = wire["/v1/systemone"]
    if change == "bad_probability":
        result["answers"]["stale"]["noul"] = 2
    elif change == "bad_trace":
        result["trace_id"] = "invalid"
    elif change == "bad_metadata":
        result["metadata_delivery"] = "failed"
    elif change == "unavailable":
        result["status"] = "unavailable"
    else:
        result["answers"] = {}
    calls = []
    with pytest.raises(AIUnavailable):
        asyncio.run(adapter(settings, wire, calls).diagnose_local(uuid4()))
    assert len(calls) == 3


def test_duplicate_is_receipt_not_answer(settings, wire):
    wire["/v1/systemone"]["status"] = "duplicate"
    wire["/v1/systemone"].pop("answers")
    calls = []
    report = asyncio.run(adapter(settings, wire, calls).diagnose_local(uuid4()))
    assert report.failure == AIFailure.DUPLICATE
    assert report.stale_probability is None
    assert len(calls) == 3


def test_missing_and_wrong_slot_keys_are_redacted(settings):
    for config in (
        settings,
        replace(
            settings, key_file=settings.key_file.with_name("build-development.key")
        ),
    ):
        with pytest.raises(AIUnavailable) as caught:
            asyncio.run(EnergyPanelAdapter(config).discover())
        assert caught.value.reason == AIFailure.AUTHENTICATION
        assert str(config.key_file) not in str(caught.value)


def test_generation_and_unknown_tools_cannot_make_network_calls(settings, wire):
    calls = []
    client = adapter(settings, wire, calls)
    with pytest.raises(AIUnavailable, match="policy_denied"):
        asyncio.run(client.generate("premium-reasoning", "synthetic"))
    with pytest.raises(AIUnavailable, match="policy_denied"):
        asyncio.run(client.invoke_tool("shell"))
    assert not calls


@pytest.mark.parametrize(
    "url",
    [
        "http://192.0.2.1:8787",
        "http://host.docker.internal:8787",
        "https://user:secret@example.test",
        "https://example.test/?key=secret",
    ],
)
def test_configuration_rejects_unapproved_transport(settings, url):
    with pytest.raises(ValueError, match="Invalid Energy AI configuration"):
        replace(settings, base_url=url)


def test_offline_and_timeout_do_not_fallback(settings, wire):
    calls = []
    with pytest.raises(AIUnavailable, match="unavailable"):
        asyncio.run(
            adapter(
                settings, wire, calls, failure=httpx.ConnectError("secret")
            ).discover()
        )
    assert len(calls) == 1


def test_status_does_not_contact_panel(settings, monkeypatch):
    monkeypatch.setenv("ENERGY_AI_ENABLED", "true")
    monkeypatch.setenv("ENERGY_AI_BASE_URL", settings.base_url)
    monkeypatch.setenv("ENERGY_AI_KEY_FILE", str(settings.key_file))
    monkeypatch.setenv("ENERGY_AI_STATUS_FILE", str(settings.status_file))
    assert local_status()["connection"] == "configured"
    assert local_status()["last_explicit_check"] is None


def test_async_sdk_deadline_and_cancellation(settings):
    async def exercise(cancel):
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def factory(config):
            async def transport(request):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            client = sdk.AsyncPanelClient(config.base_url, "synthetic-test-key")
            await client.close()
            client.http = httpx.AsyncClient(
                base_url=config.base_url, transport=httpx.MockTransport(transport)
            )
            return client

        config = replace(
            settings,
            connect_timeout_seconds=0.01,
            read_timeout_seconds=0.01,
            total_timeout_seconds=0.02,
        )
        task = asyncio.create_task(
            EnergyPanelAdapter(config, client_factory=factory).discover()
        )
        await started.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(AIUnavailable, match="timeout"):
                await task
        assert stopped.is_set()

    asyncio.run(exercise(False))
    asyncio.run(exercise(True))


@pytest.mark.parametrize("mode", ["oversize", "compressed", "valid"])
def test_real_sdk_transport_is_bounded_and_preserves_key_privacy(settings, wire, mode):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            assert self.headers["Authorization"] == "Bearer synthetic-test-key"
            assert self.headers["Accept-Encoding"] == "identity"
            payload = (
                b"x" * 65537
                if mode == "oversize"
                else json.dumps(wire[self.path]).encode()
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            if mode == "compressed":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    settings.key_file.write_text("synthetic-test-key")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = replace(settings, base_url=f"http://127.0.0.1:{server.server_port}")
        if mode == "valid":
            report = asyncio.run(EnergyPanelAdapter(config).discover())
            assert report.transport_authenticated
            assert requests == [
                "/v1/integration/health",
                "/v1/integration/capabilities",
            ]
        else:
            with pytest.raises(AIUnavailable, match="invalid_response"):
                asyncio.run(EnergyPanelAdapter(config).discover())
            assert len(requests) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_sdk_outage_leaves_core_observations_and_profiles_unchanged(
    settings, wire, healthy_states, config, now
):
    from energy_optimizer.collector import build_observation
    from energy_optimizer.load_profile import estimate_load_profile

    observation = build_observation(healthy_states, config, observed_at=now)
    profile = estimate_load_profile([])
    with pytest.raises(AIUnavailable):
        asyncio.run(adapter(settings, wire, [], failure=503).discover())
    assert build_observation(healthy_states, config, observed_at=now) == observation
    assert estimate_load_profile([]) == profile


def test_last_success_is_retained_across_explicit_discovery(settings, wire):
    report = asyncio.run(adapter(settings, wire, []).diagnose_local(uuid4()))
    save_status(settings, report)
    discovery = asyncio.run(adapter(settings, wire, []).discover())
    save_status(settings, discovery)
    assert read_status(settings)["local_diagnostic"] == "not_run"
    assert read_status(settings, diagnostic=True)["trace_id"] == str(report.trace_id)
