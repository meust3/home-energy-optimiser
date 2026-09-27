"""Tests of the local seam only; these are not panel contract fixtures."""

import asyncio
import json
import traceback
from unittest.mock import AsyncMock

import pytest

from energy_optimizer.ai_integration import (
    AIFailure,
    AISettings,
    AIUnavailable,
    OptionalAI,
    local_status,
)
from energy_optimizer.collector import build_observation
from energy_optimizer.load_profile import estimate_load_profile


@pytest.mark.parametrize("value", ["bad-secret", "nan", "inf", "0", "-1", "61"])
def test_invalid_deadlines_do_not_echo_input(value):
    with pytest.raises(ValueError) as caught:
        AISettings.from_environment({"ENERGY_AI_TOTAL_TIMEOUT_SECONDS": value})
    assert str(caught.value) == "Invalid Energy AI configuration"
    assert "bad-secret" not in "".join(traceback.format_exception(caught.value))


def test_configuration_is_explicit_and_scoped():
    assert not AISettings.from_environment({"PANEL_ENABLED": "true"}).enabled
    assert AISettings.from_environment({"ENERGY_AI_ENABLED": "true"}).enabled
    with pytest.raises(ValueError):
        AISettings.from_environment({"ENERGY_AI_ENABLED": "maybe"})
    with pytest.raises(ValueError):
        AISettings(total_timeout_seconds=1)
    with pytest.raises(ValueError):
        AISettings(enabled="true")


def test_disabled_does_not_invoke_operation_and_enabled_has_no_fake_backend():
    operation = AsyncMock()
    with pytest.raises(AIUnavailable, match="disabled"):
        asyncio.run(OptionalAI(AISettings()).run_manual(operation))
    operation.assert_not_called()
    with pytest.raises(AIUnavailable, match="handoff_pending"):
        asyncio.run(OptionalAI(AISettings(enabled=True)).run_manual())


@pytest.mark.parametrize("reason", list(AIFailure))
def test_failure_is_explicit_redacted_and_never_retried(reason):
    upstream = AIUnavailable(reason)
    upstream.args = ("upstream-secret",)
    operation = AsyncMock(side_effect=upstream)
    with pytest.raises(AIUnavailable) as caught:
        asyncio.run(OptionalAI(AISettings(enabled=True)).run_manual(operation))
    assert caught.value.reason == reason
    assert caught.value.__context__ is None
    assert "upstream-secret" not in "".join(traceback.format_exception(caught.value))
    operation.assert_awaited_once()


def test_unexpected_error_is_redacted_and_not_retried():
    operation = AsyncMock(side_effect=RuntimeError("secret-request-body"))
    with pytest.raises(AIUnavailable) as caught:
        asyncio.run(OptionalAI(AISettings(enabled=True)).run_manual(operation))
    assert caught.value.reason == AIFailure.UNAVAILABLE
    assert caught.value.__context__ is None
    assert "secret-request-body" not in "".join(
        traceback.format_exception(caught.value)
    )
    operation.assert_awaited_once()


def test_deadline_cancels_operation_without_background_retry():
    cancelled = []

    async def pending(settings):
        assert settings.connect_timeout_seconds == 0.01
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    settings = AISettings(True, 0.01, 0.01, 0.02)
    with pytest.raises(AIUnavailable, match="timeout"):
        asyncio.run(OptionalAI(settings).run_manual(pending))
    assert cancelled == [True]


def test_caller_cancellation_propagates():
    async def check():
        started = asyncio.Event()

        async def pending(_settings):
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            OptionalAI(AISettings(enabled=True)).run_manual(pending)
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(check())


def test_success_preserves_typed_value_without_interpreting_as_telemetry():
    operation = AsyncMock(return_value=42)
    settings = AISettings(enabled=True)
    assert asyncio.run(OptionalAI(settings).run_manual(operation)) == 42
    operation.assert_awaited_once_with(settings)


def test_status_is_local_and_never_claims_live_verification():
    status = local_status({"ENERGY_AI_ENABLED": "true", "HA_TOKEN": "secret"})
    assert status["enabled"]
    assert status["connection"] == "unconfigured"
    assert status["latest_manual_live_test"] is None
    assert status["contract_version"] == "1.0.0"
    assert "secret" not in json.dumps(status)
    assert local_status({"ENERGY_AI_ENABLED": "secret"})["configuration"] == "invalid"


def test_optional_failure_leaves_ingestion_and_calculations_identical(
    healthy_states, config, now, monkeypatch
):
    before = build_observation(healthy_states, config, observed_at=now)
    profile = estimate_load_profile([])
    monkeypatch.setenv("ENERGY_AI_ENABLED", "invalid-secret")
    assert local_status()["configuration"] == "invalid"
    failure = AsyncMock(side_effect=ConnectionError("offline"))
    with pytest.raises(AIUnavailable):
        asyncio.run(OptionalAI(AISettings(enabled=True)).run_manual(failure))
    after = build_observation(healthy_states, config, observed_at=now)
    assert after == before
    assert estimate_load_profile([]) == profile
