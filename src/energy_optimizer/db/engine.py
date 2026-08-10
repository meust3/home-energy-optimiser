"""SQLAlchemy engine construction and persistence error classification."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import DBAPIError, OperationalError

from energy_optimizer.db.redaction import redact_database_urls, safe_url


class DatabaseError(RuntimeError):
    """Credential-safe base persistence failure."""


class DatabaseConnectionError(DatabaseError):
    """Database connectivity failed before a transaction completed."""


class DatabaseTransactionError(DatabaseError):
    """A database transaction failed."""


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    url = safe_url(database_url)
    is_read_only_sqlite_uri = (
        url.get_backend_name() == "sqlite"
        and str(url.query.get("uri", "")).lower() == "true"
    )
    if (
        url.get_backend_name() == "sqlite"
        and url.database not in (None, ":memory:")
        and not is_read_only_sqlite_uri
    ):
        Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {"pool_pre_ping": True, "echo": echo}
    if url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def translate_database_error(exc: DBAPIError) -> DatabaseError:
    message = redact_database_urls(exc)
    if isinstance(exc, OperationalError) or exc.connection_invalidated:
        return DatabaseConnectionError(message)
    return DatabaseTransactionError(message)
