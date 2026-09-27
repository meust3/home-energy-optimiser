"""Optional AI execution boundary, independent of any provider wire contract.

No network implementation or credentials are installed here. A future committed
SDK adapter must supply a cancellable async operation with validated output and
bounded transport timeouts. Never call this boundary from the collector.
"""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

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


class AIUnavailable(RuntimeError):
    """Only fixed categories cross the boundary; no upstream exception text."""

    def __init__(self, reason: AIFailure) -> None:
        self.reason = AIFailure(reason)
        super().__init__(self.reason.value)


@dataclass(frozen=True)
class AISettings:
    """Energy-only policy knobs; deliberately no guessed URL/key/route fields."""

    enabled: bool = False
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 10.0
    total_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
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
            return cls(
                enabled=enabled == "true",
                connect_timeout_seconds=float(
                    source.get("ENERGY_AI_CONNECT_TIMEOUT_SECONDS", "2")
                ),
                read_timeout_seconds=float(
                    source.get("ENERGY_AI_READ_TIMEOUT_SECONDS", "10")
                ),
                total_timeout_seconds=float(
                    source.get("ENERGY_AI_TOTAL_TIMEOUT_SECONDS", "15")
                ),
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
    return {
        "configuration": "valid" if settings is not None else "invalid",
        "enabled": settings.enabled if settings is not None else False,
        "connection": "handoff_pending",
        "contract_version": None,
        "transport_authentication": "unverified",
        "capability_permissions": "unverified",
        "worker_health": "unverified",
        "panel_policy": "unverified",
        "latest_manual_live_test": None,
        "automatic_processing": False,
        "paid_calls_enabled": False,
        "hardware_commands_enabled": False,
    }
