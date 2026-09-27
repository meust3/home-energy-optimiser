"""Optional AI boundary and local status; never called from the collector."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlsplit

T = TypeVar("T")


class AIFailure(StrEnum):
    """Application-local failure categories, not panel response codes."""

    DISABLED = "disabled"
    HANDOFF_PENDING = "handoff_pending"
    AUTHENTICATION = "authentication_failed"
    POLICY_DENIED = "policy_denied"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    TIMEOUT = "timeout"
    DUPLICATE = "duplicate_receipt"


class AIUnavailable(RuntimeError):
    """Only fixed categories cross the boundary; no upstream exception text."""

    def __init__(self, reason: AIFailure) -> None:
        self.reason = AIFailure(reason)
        super().__init__(self.reason.value)


@dataclass(frozen=True)
class AISettings:
    """Energy runtime configuration, separate from project Codex credentials."""

    enabled: bool = False
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 8.0
    total_timeout_seconds: float = 10.0
    base_url: str | None = field(default=None, repr=False)
    key_file: Path | None = field(default=None, repr=False)
    environment: str = "production"
    ca_file: Path | None = field(default=None, repr=False)
    cert_file: Path | None = field(default=None, repr=False)
    cert_key_file: Path | None = field(default=None, repr=False)
    status_file: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("Invalid Energy AI configuration")
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Invalid Energy AI configuration")
        if bool(self.base_url) != bool(self.key_file):
            raise ValueError("Invalid Energy AI configuration")
        if self.base_url:
            try:
                url = urlsplit(self.base_url)
                allowed = url.scheme == "https" or (
                    url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"}
                )
                if (
                    not allowed
                    or not url.hostname
                    or url.username
                    or url.password
                    or url.query
                    or url.fragment
                    or url.path not in {"", "/"}
                ):
                    raise ValueError()
                _ = url.port
            except ValueError:
                raise ValueError("Invalid Energy AI configuration") from None
        if bool(self.cert_file) != bool(self.cert_key_file):
            raise ValueError("Invalid Energy AI configuration")
        for value in (
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
            self.total_timeout_seconds,
        ):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 < value <= 60
            ):
                raise ValueError("Invalid Energy AI configuration")
        if max(self.connect_timeout_seconds, self.read_timeout_seconds) > (
            self.total_timeout_seconds
        ):
            raise ValueError("Invalid Energy AI configuration")

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> AISettings:
        source = os.environ if env is None else env
        enabled = source.get("ENERGY_AI_ENABLED", "false").strip().lower()
        if enabled not in {"true", "false"}:
            raise ValueError("Invalid Energy AI configuration")
        try:

            def path(name: str) -> Path | None:
                value = source.get(name, "").strip()
                return Path(value) if value else None

            return cls(
                enabled=enabled == "true",
                connect_timeout_seconds=float(
                    source.get("ENERGY_AI_CONNECT_TIMEOUT_SECONDS", "2")
                ),
                read_timeout_seconds=float(
                    source.get("ENERGY_AI_READ_TIMEOUT_SECONDS", "8")
                ),
                total_timeout_seconds=float(
                    source.get("ENERGY_AI_TOTAL_TIMEOUT_SECONDS", "10")
                ),
                base_url=source.get("ENERGY_AI_BASE_URL", "").strip() or None,
                key_file=path("ENERGY_AI_KEY_FILE"),
                environment=source.get("ENERGY_AI_ENVIRONMENT", "production"),
                ca_file=path("ENERGY_AI_CA_FILE"),
                cert_file=path("ENERGY_AI_CERT_FILE"),
                cert_key_file=path("ENERGY_AI_CERT_KEY_FILE"),
                status_file=path("ENERGY_AI_STATUS_FILE"),
            )
        except (ValueError, TypeError):
            raise ValueError("Invalid Energy AI configuration") from None


class OptionalAI:
    """Manual-only execution seam, with no retry, fallback or background worker.

    The injected operation takes settings so a future SDK adapter can enforce
    connect/read deadlines as well as this total deadline. It must yield to the
    event loop and propagate cancellation; wrapping blocking I/O in a thread does
    not meet that requirement. Cancellation cannot undo an accepted remote call.
    """

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings

    async def run_manual(
        self,
        operation: Callable[[AISettings], Awaitable[T]] | None = None,
    ) -> T:
        if not self.settings.enabled:
            raise AIUnavailable(AIFailure.DISABLED)
        if operation is None:
            raise AIUnavailable(AIFailure.HANDOFF_PENDING)
        reason = AIFailure.UNAVAILABLE
        try:
            async with asyncio.timeout(self.settings.total_timeout_seconds):
                return await operation(self.settings)
        except AIUnavailable as exc:
            reason = exc.reason
        except TimeoutError:
            reason = AIFailure.TIMEOUT
        except Exception:
            # This optional boundary deliberately converts unexpected SDK failures
            # into a visible failure category. Never log upstream bodies/secrets.
            reason = AIFailure.UNAVAILABLE
        # Raise outside the handler so even exception context holds no SDK secret.
        raise AIUnavailable(reason)


def local_status(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """Pure local status. Opening this surface never discovers or runs inference."""
    try:
        settings = AISettings.from_environment(env)
    except ValueError:
        settings = None
    try:
        sdk_version = version("ai-control-panel-client")
    except PackageNotFoundError:
        sdk_version = None
    result = {
        "configuration": "valid" if settings is not None else "invalid",
        "enabled": settings.enabled if settings is not None else False,
        "connection": (
            "configured" if settings and settings.base_url else "unconfigured"
        ),
        "contract_version": "1.0.0",
        "sdk_version": sdk_version,
        "sdk_expected_version": "1.0.1",
        "transport_authentication": "unverified",
        "capability_permissions": "unverified",
        "worker_health": "unverified",
        "panel_policy": "unverified",
        "latest_manual_live_test": None,
        "automatic_processing": False,
        "paid_calls_enabled": False,
        "hardware_commands_enabled": False,
    }
    if settings and settings.status_file:
        from energy_optimizer.ai_panel import read_status

        result["last_explicit_check"] = read_status(settings)
        snapshot = (
            read_status(settings, diagnostic=True) or result["last_explicit_check"]
        )
        if snapshot and snapshot["local_diagnostic"] == "shadow":
            result["latest_manual_live_test"] = {
                k: snapshot[k]
                for k in ("checked_at", "trace_id", "event_id", "environment", "caller")
            }
    return result
