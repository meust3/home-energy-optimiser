"""Backend-neutral persistence primitives."""

from energy_optimizer.db.engine import DatabaseError, create_database_engine
from energy_optimizer.db.redaction import display_database_url, redact_database_urls
from energy_optimizer.db.repository import DatabaseRepository, DuplicateResult

__all__ = [
    "DatabaseError",
    "DatabaseRepository",
    "DuplicateResult",
    "create_database_engine",
    "display_database_url",
    "redact_database_urls",
]
