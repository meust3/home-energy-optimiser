"""Thin Energy adapter for pinned panel contract 1.0.0 / SDK 1.0.1.

Only explicit synthetic diagnostics are executable. This module is never imported
by collection/calculation code. SDK imports are lazy so the AI extra is optional.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, Self, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from energy_optimizer.ai_integration import (
    AIFailure,
    AISettings,
    AIUnavailable,
    OptionalAI,
)

CONTRACT_COMMIT = "436b04c50514487f9558d67c93facd0998e2f8a6"
SDK_COMMIT = "17453cb65f8ff7714b203aba8d2a7b964cb3f09c"
T = TypeVar("T")


class PanelSession(Protocol):
    """Only the installed SDK methods used by this consumer."""

    async def health(self) -> dict[str, Any]: ...
    async def capabilities(self) -> dict[str, Any]: ...
    async def decide(
        self,
        state: Any,
        questions: dict[str, Any],
        *,
        operation_id: str,
        feature: str,
        input_kind: str,
        runtime_instance: str,
    ) -> dict[str, Any]: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *args: Any) -> None: ...


class WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class Grant(WireModel):
    caller: Literal["application_backend"]
    environment: Literal["development", "test", "production"]
    scopes: list[str]


class Health(WireModel):
    contract_version: Literal["1.0.0"]
    status: Literal["ready"]
    project: Literal["home-energy"]
    principal: str
    grant: Grant
    database: Literal["reachable"]


class Capability(WireModel):
    profile: str
    implemented: bool
    authorised: bool
    policy_enabled: bool
    credential_ready: bool
    health: dict[str, Any] | None = None
    execution: str


class Catalogue(WireModel):
    contract_version: Literal["1.0.0"]
    project: Literal["home-energy"]
    principal: str
    environment: Literal["development", "test", "production"]
    caller: Literal["application_backend"]
    paused: bool
    capabilities: list[Capability]
    tools: list[dict[str, Any]]
    cloud_fallback: Literal[False]


class DiagnosticReport(BaseModel):
    """Allowlisted local evidence; never persists input, raw bodies or credentials."""

    model_config = ConfigDict(extra="forbid")
    checked_at: datetime
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_version: Literal["1.0.0"] = "1.0.0"
    sdk_version: Literal["1.0.1"] = "1.0.1"
    project: Literal["home-energy"] = "home-energy"
    caller: Literal["application_backend"] = "application_backend"
    environment: Literal["development", "test", "production"]
    principal: UUID | None = None
    transport_authenticated: bool = False
    permission: bool | None = None
    policy_enabled: bool | None = None
    worker_ready: bool | None = None
    paused: bool | None = None
    failure: AIFailure | None = None
    local_diagnostic: Literal["not_run", "shadow", "duplicate_receipt"] = "not_run"
    operation_id: UUID | None = None
    trace_id: UUID | None = None
    event_id: UUID | None = None
    metadata_delivery: Literal["accepted"] | None = None
    stale_probability: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    generation_enabled: Literal[False] = False
    business_processing: Literal[False] = False
    hardware_commands: Literal[False] = False


def configuration_hash(settings: AISettings) -> str:
    # Key *path*, not material. A historical snapshot never proves current auth.
    value = json.dumps(
        [
            settings.base_url,
            str(settings.key_file),
            settings.environment,
            str(settings.ca_file),
            str(settings.cert_file),
            str(settings.cert_key_file),
        ]
    )
    return hashlib.sha256(value.encode()).hexdigest()


def save_status(settings: AISettings, report: DiagnosticReport) -> None:
    if settings.status_file is None:
        return
    settings.status_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = settings.status_file.with_suffix(".tmp")
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(settings.status_file)
    if report.local_diagnostic == "shadow":
        diagnostic = settings.status_file.with_suffix(".diagnostic.json")
        temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(diagnostic)


def read_status(
    settings: AISettings, *, diagnostic: bool = False
) -> dict[str, Any] | None:
    try:
        if settings.status_file is None:
            return None
        path = (
            settings.status_file.with_suffix(".diagnostic.json")
            if diagnostic
            else settings.status_file
        )
        with path.open("rb") as handle:
            raw = handle.read(16385)
        if len(raw) > 16384:
            return None
        report = DiagnosticReport.model_validate_json(raw)
        if (
            report.configuration_hash != configuration_hash(settings)
            or report.checked_at.tzinfo is None
        ):
            return None
        result = report.model_dump(mode="json", exclude={"configuration_hash"})
        result["historical_snapshot"] = True
        return result
    except (OSError, ValueError):
        return None


async def sdk_client(settings: AISettings) -> PanelSession:
    """Instantiate only the pinned SDK, with a bounded streaming transport."""
    import httpx
    import panel_client

    if panel_client.__version__ != "1.0.1":
        raise AIUnavailable(AIFailure.UNAVAILABLE)
    if not settings.key_file or not settings.base_url:
        raise AIUnavailable(AIFailure.HANDOFF_PENDING)
    try:
        # Reject build/test/production slot mix-ups before opening the connection.
        if settings.key_file.name != f"runtime-{settings.environment}.key":
            raise AIUnavailable(AIFailure.AUTHENTICATION)
        with settings.key_file.open("r", encoding="utf-8") as handle:
            key = handle.read(4097).strip()
        if not key or len(key) > 4096 or any(c.isspace() for c in key):
            raise AIUnavailable(AIFailure.AUTHENTICATION)
        kwargs = dict(
            ca_file=settings.ca_file,
            cert_file=settings.cert_file,
            cert_key_file=settings.cert_key_file,
        )
        options = panel_client.configuration(settings.base_url, key, **kwargs)
    except (OSError, ValueError):
        raise AIUnavailable(AIFailure.AUTHENTICATION) from None

    class LimitedStream(httpx.AsyncByteStream):
        def __init__(self, stream: httpx.AsyncByteStream) -> None:
            self.stream = stream

        async def __aiter__(self) -> AsyncIterator[bytes]:
            size = 0
            async for chunk in self.stream:
                size += len(chunk)
                if size > 65536:
                    raise AIUnavailable(AIFailure.INVALID_RESPONSE)
                yield chunk

        async def aclose(self) -> None:
            await self.stream.aclose()

    class LimitedTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.AsyncHTTPTransport(verify=options["verify"], retries=0)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            response = await self.inner.handle_async_request(request)
            # No compressed body: prevents decompression expansion past the wire cap.
            if response.headers.get("content-encoding", "identity") != "identity":
                await response.aclose()
                raise AIUnavailable(AIFailure.INVALID_RESPONSE)
            response.stream = LimitedStream(response.stream)
            return response

        async def aclose(self) -> None:
            await self.inner.aclose()

    client = panel_client.AsyncPanelClient(settings.base_url, key, **kwargs)
    await client.close()
    options["timeout"] = httpx.Timeout(
        settings.read_timeout_seconds, connect=settings.connect_timeout_seconds
    )
    options["headers"]["Accept-Encoding"] = "identity"
    client.http = httpx.AsyncClient(**options, transport=LimitedTransport())
    return client


class EnergyPanelAdapter:
    def __init__(
        self,
        settings: AISettings,
        *,
        client_factory: Callable[[AISettings], Awaitable[PanelSession]] = sdk_client,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.boundary = OptionalAI(settings)

    async def _execute(self, action: Callable[[PanelSession], Awaitable[T]]) -> T:
        async def operation(_settings: AISettings) -> T:
            from panel_client import AuthenticationError, PanelError, PolicyError

            failure = AIFailure.UNAVAILABLE
            try:
                async with await self.client_factory(self.settings) as client:
                    return await action(client)
            except AuthenticationError:
                failure = AIFailure.AUTHENTICATION
            except PolicyError:
                failure = AIFailure.POLICY_DENIED
            except PanelError as exc:
                failure = (
                    AIFailure.INVALID_RESPONSE
                    if exc.status == 422 or exc.code.startswith("invalid_")
                    else AIFailure.UNAVAILABLE
                )
            except (ValidationError, ValueError, KeyError, TypeError):
                failure = AIFailure.INVALID_RESPONSE
            raise AIUnavailable(failure)

        return await self.boundary.run_manual(operation)

    async def _discover_with_client(self, client: PanelSession) -> DiagnosticReport:
        health = Health.model_validate(await client.health())
        catalogue = Catalogue.model_validate(await client.capabilities())
        if (
            health.principal != catalogue.principal
            or health.grant.environment != self.settings.environment
            or catalogue.environment != self.settings.environment
        ):
            raise AIUnavailable(AIFailure.AUTHENTICATION)
        local = [c for c in catalogue.capabilities if c.profile == "bounded-local"]
        if len(local) != 1 or local[0].execution != "local":
            raise AIUnavailable(AIFailure.INVALID_RESPONSE)
        local = local[0]
        ready = (local.health or {}).get("ready")
        if type(ready) is not bool:
            raise AIUnavailable(AIFailure.INVALID_RESPONSE)
        return DiagnosticReport(
            checked_at=datetime.now(UTC),
            configuration_hash=configuration_hash(self.settings),
            environment=self.settings.environment,
            principal=UUID(health.principal),
            transport_authenticated=True,
            permission=local.authorised
            and local.implemented
            and local.credential_ready
            and "decisions:local" in health.grant.scopes,
            policy_enabled=local.policy_enabled,
            worker_ready=ready,
            paused=catalogue.paused,
        )

    async def discover(self) -> DiagnosticReport:
        return await self._execute(self._discover_with_client)

    async def diagnose_local(self, operation_id: UUID) -> DiagnosticReport:
        """Only the published fixed synthetic probe; never accepts household input."""

        async def action(client: PanelSession) -> DiagnosticReport:
            report = await self._discover_with_client(client)
            if (
                self.settings.environment != "development"
                or not report.permission
                or not report.policy_enabled
                or report.paused
            ):
                raise AIUnavailable(AIFailure.POLICY_DENIED)
            if not report.worker_ready:
                raise AIUnavailable(AIFailure.UNAVAILABLE)
            value = await client.decide(
                "Synthetic reading is three days old",
                {"stale": {"type": "noul", "instructions": "Is the reading stale?"}},
                operation_id=str(operation_id),
                feature="diagnostic",
                input_kind="synthetic_diagnostic",
                runtime_instance="energy-manual-diagnostic",
            )
            if value.get("metadata_delivery") != "accepted":
                raise AIUnavailable(AIFailure.INVALID_RESPONSE)
            trace_id = UUID(value["trace_id"])
            if value.get("status") == "duplicate":
                return report.model_copy(
                    update={
                        "local_diagnostic": "duplicate_receipt",
                        "trace_id": trace_id,
                        "operation_id": operation_id,
                        "failure": AIFailure.DUPLICATE,
                    }
                )
            if value.get("status") != "shadow":
                raise AIUnavailable(AIFailure.UNAVAILABLE)
            # SDK validates the complete answer shape; this DTO validates metadata too.
            return DiagnosticReport.model_validate(
                {
                    **report.model_dump(),
                    "checked_at": datetime.now(UTC),
                    "operation_id": operation_id,
                    "trace_id": trace_id,
                    "event_id": UUID(value["event_id"]),
                    "metadata_delivery": "accepted",
                    "local_diagnostic": "shadow",
                    "stale_probability": value["answers"]["stale"]["noul"],
                }
            )

        return await self._execute(action)

    async def generate(self, model: str, input_text: str) -> None:
        """Contract supports generation, but no onboarding grant authorises it."""
        raise AIUnavailable(AIFailure.POLICY_DENIED)

    async def invoke_tool(
        self, tool_id: str, *, operation_id: UUID | None = None
    ) -> DiagnosticReport:
        """Only documented infrastructure operations; no shell or native app tools."""
        if tool_id in {"integration-health", "integration-capabilities"}:
            return await self.discover()
        if tool_id == "explicit-local-decision" and operation_id is not None:
            return await self.diagnose_local(operation_id)
        raise AIUnavailable(AIFailure.POLICY_DENIED)


async def manual_check(
    settings: AISettings, operation_id: UUID | None = None
) -> DiagnosticReport:
    adapter = EnergyPanelAdapter(settings)
    try:
        report = (
            await adapter.discover()
            if operation_id is None
            else await adapter.diagnose_local(operation_id)
        )
    except AIUnavailable as exc:
        report = DiagnosticReport(
            checked_at=datetime.now(UTC),
            configuration_hash=configuration_hash(settings),
            environment=settings.environment,
            failure=exc.reason,
            operation_id=operation_id,
        )
    save_status(settings, report)
    return report
