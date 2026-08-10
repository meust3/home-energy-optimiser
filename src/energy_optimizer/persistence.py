"""One canonical configured persistence backend per application process."""

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from energy_optimizer.config import load_database_url
from energy_optimizer.db.engine import create_database_engine
from energy_optimizer.db.redaction import display_database_url
from energy_optimizer.db.repository import DatabaseRepository, DuplicateResult

LOGGER = logging.getLogger(__name__)


class ApplicationRepository(DatabaseRepository):
    """Configured repository with credential-safe source metadata."""

    @property
    def target_display(self) -> str:
        return display_database_url(self.engine.url)

    @property
    def database_name(self) -> str | None:
        return self.engine.url.database

    def close(self) -> None:
        self.engine.dispose()


def open_repository(database_url: str | None = None) -> ApplicationRepository:
    """Open exactly the configured backend; failures never fall back to SQLite."""
    url = database_url or load_database_url()
    repository = ApplicationRepository(create_database_engine(url))
    LOGGER.debug(
        "Configured database backend=%s target=%s database=%s",
        repository.backend,
        repository.target_display,
        repository.database_name,
    )
    return repository


def emit_database_info(repository: ApplicationRepository) -> None:
    latest = repository.latest_observation()
    latest_slot = latest["slot_utc"] if latest else None
    if hasattr(latest_slot, "isoformat"):
        latest_slot = latest_slot.isoformat()
    print(
        f"database backend={repository.backend} target={repository.target_display} "
        f"database={repository.database_name} latest_observation={latest_slot}",
        file=sys.stderr,
    )


@contextmanager
def configured_repository(
    database_url: str | None = None,
) -> Iterator[ApplicationRepository]:
    repository = open_repository(database_url)
    try:
        yield repository
    finally:
        repository.close()


class ObservationStore:
    """Backward-compatible collector facade over the canonical repository."""

    def __init__(self, database_url: str | None = None) -> None:
        self._repository = open_repository(database_url)

    @property
    def backend(self) -> str:
        return self._repository.backend

    def save(self, observation) -> DuplicateResult:
        return self._repository.save_observation(observation)

    def close(self) -> None:
        self._repository.close()
