"""Version-one derived scoring inventory DDL and explicit migration backfill.

No connection, migration or reconciliation is run at import or application startup.
Database triggers keep raw SQL/ORM inserts and score changes in the same transaction.
"""

import re
from time import monotonic

from sqlalchemy import Connection, insert, select, text

from energy_optimizer.db.models import ForecastPoint, ForecastScorePending

BACKFILL_RANGE_WIDTH = 10_000
BACKFILL_BUDGET_SECONDS = 120

TRIGGERS = {
    "points_insert": ("forecast_points", "AFTER INSERT"),
    "points_update": (
        "forecast_points",
        "AFTER UPDATE OF id, forecast_run_id, period_end_utc",
    ),
    "scores_insert": ("forecast_point_scores", "AFTER INSERT"),
    "scores_delete": ("forecast_point_scores", "AFTER DELETE"),
    "scores_update": ("forecast_point_scores", "AFTER UPDATE OF forecast_point_id"),
    "runs_update": ("forecast_runs", "AFTER UPDATE OF forecast_type"),
}


def _enqueue(expression: str) -> str:
    # Callers supply only the fixed OLD/NEW references below, never user input.
    return f"""INSERT INTO forecast_score_pending(forecast_point_id,period_end_utc)
      SELECT p.id,p.period_end_utc FROM forecast_points p
      JOIN forecast_runs r ON r.id=p.forecast_run_id
      WHERE {expression} AND r.forecast_type='baseline_household_load'
      AND NOT EXISTS(SELECT 1 FROM forecast_point_scores s
                     WHERE s.forecast_point_id=p.id)
      ON CONFLICT(forecast_point_id) DO NOTHING;"""


def install_inventory_triggers(connection: Connection) -> None:
    dialect = connection.dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError("pending inventory requires SQLite or PostgreSQL")
    schema = None
    if dialect == "postgresql":
        schema = connection.scalar(text("SELECT current_schema()"))
        if not schema:
            raise ValueError("pending inventory needs an explicit current schema")
    quote = connection.dialect.identifier_preparer.quote_identifier

    def relation(name: str) -> str:
        return f"{quote(schema)}.{quote(name)}" if schema else name

    def qualify(body: str) -> str:
        # One pass: a schema name may itself contain one of these table names.
        return re.sub(
            r"\b(forecast_score_pending|forecast_point_scores|forecast_points|forecast_runs)\b",
            lambda match: relation(match.group()),
            body,
        )

    statements = {
        "points_insert": _enqueue("p.id=NEW.id"),
        "points_update": (
            "DELETE FROM forecast_score_pending "
            "WHERE forecast_point_id IN (OLD.id,NEW.id);" + _enqueue("p.id=NEW.id")
        ),
        "scores_insert": (
            "DELETE FROM forecast_score_pending "
            "WHERE forecast_point_id=NEW.forecast_point_id;"
        ),
        "scores_delete": _enqueue("p.id=OLD.forecast_point_id"),
        "scores_update": (
            "DELETE FROM forecast_score_pending "
            "WHERE forecast_point_id=NEW.forecast_point_id;"
            + _enqueue("p.id=OLD.forecast_point_id")
        ),
        "runs_update": (
            "DELETE FROM forecast_score_pending WHERE forecast_point_id IN "
            "(SELECT id FROM forecast_points WHERE forecast_run_id=NEW.id);"
            + _enqueue("p.forecast_run_id=NEW.id")
        ),
    }
    for key, (table, timing) in TRIGGERS.items():
        name = f"score_pending_{key}_v1"
        if dialect == "sqlite":
            connection.exec_driver_sql(
                f"CREATE TRIGGER {name} {timing} ON {table} "
                f"BEGIN {statements[key]} END"
            )
        else:
            # Invoker rights; no privilege elevation or credential-bearing SQL.
            connection.exec_driver_sql(
                f"CREATE FUNCTION {relation(name)}() RETURNS trigger LANGUAGE plpgsql "
                f"SECURITY INVOKER SET search_path=pg_catalog AS $$ "
                f"BEGIN {qualify(statements[key])} RETURN NULL; END $$"
            )
            connection.exec_driver_sql(
                f"CREATE TRIGGER {name} {timing} ON {relation(table)} FOR EACH ROW "
                f"EXECUTE FUNCTION {relation(name)}()"
            )
    if dialect == "postgresql":
        connection.exec_driver_sql(
            f"CREATE FUNCTION {relation('score_pending_reject_truncate_v1')}() "
            "RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER "
            "SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION "
            "'TRUNCATE would invalidate pending scoring inventory; "
            "use transactional DELETE'; END $$"
        )
        for table in ("forecast_point_scores", "forecast_score_pending"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER score_pending_reject_truncate_v1 BEFORE TRUNCATE "
                f"ON {relation(table)} FOR EACH STATEMENT EXECUTE FUNCTION "
                f"{relation('score_pending_reject_truncate_v1')}()"
            )


def remove_inventory_triggers(connection: Connection) -> None:
    quote = connection.dialect.identifier_preparer.quote_identifier
    schema = (
        connection.scalar(text("SELECT current_schema()"))
        if connection.dialect.name == "postgresql"
        else None
    )

    def relation(name: str) -> str:
        return f"{quote(schema)}.{quote(name)}" if schema else name

    if connection.dialect.name == "postgresql":
        for table in ("forecast_point_scores", "forecast_score_pending"):
            connection.exec_driver_sql(
                "DROP TRIGGER IF EXISTS score_pending_reject_truncate_v1 "
                f"ON {relation(table)}"
            )
        connection.exec_driver_sql(
            f"DROP FUNCTION IF EXISTS {relation('score_pending_reject_truncate_v1')}()"
        )
    for key, (table, _timing) in TRIGGERS.items():
        name = f"score_pending_{key}_v1"
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql(
                f"DROP TRIGGER IF EXISTS {name} ON {relation(table)}"
            )
            connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS {relation(name)}()")
        else:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")


def backfill_pending_inventory(connection: Connection) -> int:
    """One explicit maintenance sweep; caller holds a stable write-excluding lock.

    Each batch contains at most 10,000 skinny IDs/timestamps, including future work.
    Never use a permanent MAX(id) cursor or a recent-only eligibility boundary.
    Failure rolls back the migration instead of publishing a partial inventory.
    """
    from energy_optimizer.db.models import ForecastPointScore, ForecastRun

    started = monotonic()
    lower = connection.scalar(
        select(ForecastPoint.id).order_by(ForecastPoint.id).limit(1)
    )
    count = 0
    while lower is not None:
        if monotonic() - started >= BACKFILL_BUDGET_SECONDS:
            raise TimeoutError("pending inventory backfill budget exceeded")
        upper = lower + BACKFILL_RANGE_WIDTH
        rows = connection.execute(
            select(ForecastPoint.id, ForecastPoint.period_end_utc)
            .join(ForecastRun, ForecastRun.id == ForecastPoint.forecast_run_id)
            .outerjoin(
                ForecastPointScore,
                ForecastPointScore.forecast_point_id == ForecastPoint.id,
            )
            .where(
                ForecastPoint.id >= lower,
                ForecastPoint.id < upper,
                ForecastRun.forecast_type == "baseline_household_load",
                ForecastPointScore.forecast_point_id.is_(None),
            )
        ).all()
        if rows:
            connection.execute(
                insert(ForecastScorePending),
                [{"forecast_point_id": r[0], "period_end_utc": r[1]} for r in rows],
            )
            count += len(rows)
        lower = connection.scalar(
            select(ForecastPoint.id)
            .where(ForecastPoint.id >= upper)
            .order_by(ForecastPoint.id)
            .limit(1)
        )
    if monotonic() - started >= BACKFILL_BUDGET_SECONDS:
        raise TimeoutError("pending inventory backfill budget exceeded")
    return count
