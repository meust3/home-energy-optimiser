"""Failure-isolated optional work, run only after a durable core observation."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from energy_optimizer.context_repository import ContextRepository
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.forecast_context import ContextMapping, collect_context
from energy_optimizer.models import HomeAssistantState
from energy_optimizer.persistence import ApplicationRepository

LOGGER = logging.getLogger(__name__)


def open_bounded_context_repository(database_url: str) -> ApplicationRepository:
    """Same configured backend; no schema creation, retry or fallback."""
    return ApplicationRepository(
        create_database_engine(
            database_url,
            connect_timeout_seconds=1,
            statement_timeout_ms=500,
            sqlite_timeout_seconds=0.5,
        )
    )


def collect_and_store_context(
    states: dict[str, HomeAssistantState],
    mapping: ContextMapping,
    *,
    slot: datetime,
    receipt: datetime,
    repository_factory: Callable[[], Any],
) -> dict[str, Any]:
    repository = None
    try:
        batch = collect_context(states, mapping, slot=slot, receipt=receipt)
        if batch.diagnostic["status"] == "mapping_not_effective":
            return {"status": "mapping_not_effective"}
        repository = repository_factory()
        result = ContextRepository(repository).save(batch)
        return {"status": batch.diagnostic["status"], **result}
    except Exception as exc:
        # Optional boundary deliberately contains parser/programming/DB failures.
        # Report the class; payloads, IDs, connection strings and exception text
        # can contain private data and are never sent to logs or public health.
        LOGGER.warning(
            "Optional context collection failed (%s); core already saved",
            type(exc).__name__,
        )
        return {"status": "optional_failure", "failure_class": type(exc).__name__}
    finally:
        if repository is not None:
            try:
                repository.close()
            except Exception as exc:
                LOGGER.warning(
                    "Optional context cleanup failed (%s); core already saved",
                    type(exc).__name__,
                )
