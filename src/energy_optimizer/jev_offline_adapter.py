"""Shared-adapter rehearsal using only a mock HTTP transport over owned pipes."""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from energy_optimizer.ai_integration import AISettings
from energy_optimizer.ai_panel import EnergyPanelAdapter
from energy_optimizer.jev_evaluation import reference

SDK_SOURCE_SHA256 = "d7e595e586ba589e4b026faaf9e7efbadc097932c5c887a56040263144adb3fa"
SDK_MODULES = (
    "advisory_contracts",
    "panel_client",
    "panel_energy_challenger",
    "panel_energy_review",
    "panel_energy_review_holdout",
    "panel_mcp",
    "panel_protocol",
)
MOCK_ORIGIN = "http://127.0.0.1:1"
EVALUATION_PATH = "/v1/evaluation/energy-review-jev"


def checked_sdk_digest() -> str:
    """Check the exact published SDK bytes before admitting an offline run."""
    try:
        import panel_client

        if panel_client.__version__ != "1.0.4":
            raise ValueError()
        digest = hashlib.sha256()
        for module in SDK_MODULES:
            spec = importlib.util.find_spec(module)
            if spec is None or not spec.origin:
                raise ValueError()
            data = Path(spec.origin).read_bytes().replace(b"\r\n", b"\n")
            digest.update((module + ".py").encode() + b"\0" + data + b"\0")
        if digest.hexdigest() != SDK_SOURCE_SHA256:
            raise ValueError()
        return digest.hexdigest()
    except (ImportError, OSError, ValueError, AttributeError):
        raise ValueError(
            "Offline shared adapter requires the pinned SDK 1.0.4"
        ) from None


async def exchange_via_shared_adapter(
    exchange: Callable[[dict], Awaitable[dict]], request: dict
) -> dict:
    """Exercise actual adapter/SDK methods, never construct a network transport."""
    import httpx
    import panel_client

    frozen = reference()

    async def mock_transport(http_request: httpx.Request) -> httpx.Response:
        import json

        if (
            http_request.method != "POST"
            or str(http_request.url) != MOCK_ORIGIN + EVALUATION_PATH
        ):
            raise ValueError("Only the offline evaluation route is permitted")
        body = json.loads(http_request.content)
        expected_keys = set(request) | {"task_version", "adapter_version"}
        if set(body) != expected_keys:
            raise ValueError("Unexpected evaluation request fields")
        value = await exchange(body)
        response_keys = expected_keys | {
            "status",
            "execution",
            "event_id",
            "request_id",
            "raw_typed_answer",
            "reported_usage",
        }
        if set(value) != response_keys or value["execution"] != "offline_simulation":
            raise ValueError("Only the owned simulator's receipts are permitted")
        # These are mock wire constants required by the published validator,
        # not evidence of a provider call. Persisted results stay offline_simulation.
        wire_receipt = {
            **value,
            "policy_version": "energy-review-jev-evaluation-v1",
            "dataset_sha256": frozen["dataset_sha256"],
            "question_sha256": frozen["question_sha256"],
            "provider": "typesafe",
            "requested_model": "jev-1.13.0",
            "provider_reported_model": "jev-1.13.0",
            "execution": "cloud_evaluation",
            "no_command_issued": True,
            "cloud_fallback": False,
        }
        return httpx.Response(200, json=wire_receipt)

    class OfflineClient(panel_client.AsyncPanelClient):
        def __init__(self) -> None:
            # Do not call the SDK constructor: it creates a network transport.
            # Inherit its pinned request serialization, validators and lifecycle.
            self.http = httpx.AsyncClient(
                base_url=MOCK_ORIGIN,
                transport=httpx.MockTransport(mock_transport),
                trust_env=False,
                follow_redirects=False,
            )

    async def factory(_settings):
        return OfflineClient()

    settings = AISettings(
        enabled=True,
        environment="test",
        base_url=MOCK_ORIGIN,
        # Configuration identity only; the forced mock factory never reads a key.
        key_file=Path("runtime-test.key"),
    )
    adapter = EnergyPanelAdapter(settings, client_factory=factory)
    receipt = await adapter.review_jev_evaluation_case(
        request["case_id"],
        UUID(request["operation_id"]),
        experiment_id=UUID(request["experiment_id"]),
        manifest_sha256=request["manifest_sha256"],
    )
    return {
        **{key: receipt[key] for key in request},
        **{
            key: receipt[key]
            for key in (
                "status",
                "event_id",
                "request_id",
                "raw_typed_answer",
                "reported_usage",
            )
        },
        "execution": "offline_simulation",
    }
