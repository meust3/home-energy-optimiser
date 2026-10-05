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


class DatabaseQueryCanceledError(DatabaseTransactionError):
    """PostgreSQL canceled a query (57014), including statement timeout."""


class DatabaseLockTimeoutError(DatabaseTransactionError):
    """PostgreSQL could not acquire a lock (55P03)."""


def create_database_engine(
    database_url: str,
    *,
    echo: bool = False,
    connect_timeout_seconds: int | None = None,
    statement_timeout_ms: int | None = None,
    sqlite_timeout_seconds: float = 30,
) -> Engine:
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
        kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": sqlite_timeout_seconds,
        }
    elif url.get_backend_name() == "postgresql" and (
        connect_timeout_seconds is not None or statement_timeout_ms is not None
    ):
        connect_args: dict[str, object] = {}
        if connect_timeout_seconds is not None:
            connect_args["connect_timeout"] = connect_timeout_seconds
        if statement_timeout_ms is not None:
            connect_args["options"] = (
                f"-c statement_timeout={statement_timeout_ms} "
                f"-c lock_timeout={statement_timeout_ms}"
            )
        kwargs["connect_args"] = connect_args
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
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "57014":
        return DatabaseQueryCanceledError(message)
    if sqlstate == "55P03":
        return DatabaseLockTimeoutError(message)
    if (
        exc.connection_invalidated
        or (isinstance(sqlstate, str) and sqlstate.startswith("08"))
        or (sqlstate is None and isinstance(exc, OperationalError))
    ):
        return DatabaseConnectionError(message)
    return DatabaseTransactionError(message)
