"""Conservative, deterministic SQLite-to-PostgreSQL transfer and validation."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, Table, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from energy_optimizer.db.models import Base

TRANSFER_ORDER = (
    "observations",
    "forecast_runs",
    "forecast_points",
    "observation_derivations",
    "ev_session_annotations",
    "ev_session_annotation_rows",
)
RAW_HASH_COLUMNS = (
    "slot_utc",
    "battery_soc_percent",
    "battery_power_w",
    "pv_power_w",
    "house_consumption_w",
    "grid_power_w",
    "amber_import_price_per_kwh",
    "amber_export_price_per_kwh",
    "solcast_remaining_today_kwh_json",
    "solcast_tomorrow_kwh_json",
    "solcast_next_hour_kwh_json",
)


def source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(
        f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    ).hexdigest()


def transfer(
    source: Engine,
    target: Engine,
    *,
    source_id: str,
    batch_size: int,
    apply: bool,
    resume: bool,
) -> dict[str, Any]:
    source_meta = MetaData()
    source_meta.reflect(source)
    target_tables = Base.metadata.tables
    report: dict[str, Any] = {
        "dry_run": not apply,
        "resume_requested": resume,
        "tables": {},
        "conflicts": [],
    }
    for name in TRANSFER_ORDER:
        if name not in source_meta.tables:
            report["tables"][name] = {"source": 0, "copied": 0, "status": "absent"}
            continue
        source_table = source_meta.tables[name]
        target_table = target_tables[name]
        key_names = [column.name for column in target_table.primary_key.columns]
        ordering = [source_table.c[name] for name in key_names]
        with source.connect() as source_connection:
            rows = source_connection.execute(
                select(source_table).order_by(*ordering)
            ).mappings()
            copied = 0
            batch: list[dict[str, Any]] = []
            for raw in rows:
                batch.append(_coerce_row(dict(raw), target_table))
                if len(batch) >= batch_size:
                    copied += _write_batch(
                        target, target_table, batch, key_names, apply, report
                    )
                    batch = []
            if batch:
                copied += _write_batch(
                    target, target_table, batch, key_names, apply, report
                )
            total = (
                source_connection.scalar(select(func.count()).select_from(source_table))
                or 0
            )
        report["tables"][name] = {
            "source": total,
            "copied": copied,
            "status": "checked",
        }
        if apply:
            _store_progress(target, source_id, name, total)
            if "id" in target_table.c and target_table.c.id.primary_key:
                _synchronize_postgresql_sequence(target, name)
    report["summary"] = "FAIL" if report["conflicts"] else "PASS"
    return report


def _store_progress(target: Engine, source_id: str, table_name: str, rows: int) -> None:
    table = Base.metadata.tables["migration_progress"]
    migration_id = source_id[:64]
    values = {
        "migration_id": migration_id,
        "source_fingerprint": source_id,
        "table_name": table_name,
        "last_business_key": None,
        "rows_copied": rows,
        "updated_at_utc": datetime.now(UTC),
    }
    statement = (
        postgresql_insert(table)
        if target.dialect.name == "postgresql"
        else sqlite_insert(table)
    ).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.migration_id, table.c.table_name],
        set_={
            "rows_copied": statement.excluded.rows_copied,
            "updated_at_utc": statement.excluded.updated_at_utc,
            "source_fingerprint": statement.excluded.source_fingerprint,
        },
    )
    with target.begin() as connection:
        connection.execute(statement)


def _synchronize_postgresql_sequence(target: Engine, table_name: str) -> None:
    """Advance an identity/serial sequence after explicitly preserving IDs."""
    if target.dialect.name != "postgresql" or table_name not in TRANSFER_ORDER:
        return
    statement = text(
        "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
        "COALESCE((SELECT MAX(id) FROM " + table_name + "), 1), "
        "EXISTS (SELECT 1 FROM " + table_name + "))"
    )
    with target.begin() as connection:
        connection.execute(statement, {"table_name": table_name})


def _write_batch(target, table, rows, key_names, apply, report) -> int:
    copied = 0
    with target.begin() as connection:
        for row in rows:
            criteria = [table.c[name] == row[name] for name in key_names]
            existing = (
                connection.execute(select(table).where(*criteria)).mappings().first()
            )
            if existing is not None:
                differences = _differences(dict(existing), row)
                if differences:
                    report["conflicts"].append(
                        {
                            "table": table.name,
                            "key": {k: _stable(row[k]) for k in key_names},
                            "columns": differences,
                        }
                    )
                continue
            copied += 1
            if apply:
                connection.execute(insert(table).values(**row))
    return copied


def _coerce_row(row: dict[str, Any], target: Table) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in target.columns:
        if column.name not in row:
            continue
        value = row[column.name]
        python_type = getattr(column.type, "python_type", None)
        if value is not None and python_type is datetime and isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
        elif value is not None and python_type is bool:
            value = bool(value)
        elif (
            value is not None
            and column.type.__class__.__name__ in {"JSON", "JSONB"}
            and isinstance(value, str)
        ):
            value = json.loads(value)
        result[column.name] = value
    return result


def _differences(existing, incoming):
    differences = []
    for key, value in incoming.items():
        stored = existing.get(key)
        if (
            isinstance(stored, datetime)
            and stored.tzinfo is None
            and isinstance(value, datetime)
            and value.tzinfo is not None
        ):
            stored = stored.replace(tzinfo=value.tzinfo)
        if _stable(stored) != _stable(value):
            differences.append(key)
    return differences


def _stable(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def validate(
    source: Engine, target: Engine, *, validation_mode: str = "exact"
) -> dict[str, Any]:
    if validation_mode not in {"exact", "source-preserved"}:
        raise ValueError("validation_mode must be exact or source-preserved")
    source_meta = MetaData()
    source_meta.reflect(source)
    if validation_mode == "source-preserved":
        return _validate_source_preserved(source, target, source_meta)
    categories: dict[str, Any] = {"validation_mode": "exact"}
    counts = {}
    for name in TRANSFER_ORDER:
        source_count = _count(source, source_meta.tables.get(name))
        target_count = _count(target, Base.metadata.tables[name])
        counts[name] = {
            "source": source_count,
            "target": target_count,
            "status": "PASS" if source_count == target_count else "FAIL",
        }
    categories["table_counts"] = counts
    categories["raw_telemetry"] = _hash_validation(source, target, source_meta)
    categories["observation_integrity"] = _observation_validation(
        source, target, source_meta
    )
    categories["relational_integrity"] = _relational_validation(target)
    categories["derived_data"] = _derived_validation(source, target, source_meta)
    categories["summary"] = (
        "PASS"
        if all(
            _category_passes(value)
            for key, value in categories.items()
            if key != "summary"
        )
        else "FAIL"
    )
    return categories


def _validate_source_preserved(source, target, source_meta):
    table_reports = {}
    observation_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for name in TRANSFER_ORDER:
        source_table = source_meta.tables.get(name)
        target_table = Base.metadata.tables[name]
        if source_table is None:
            table_reports[name] = {
                "source_rows": 0,
                "matching_target_rows": 0,
                "missing_source_rows": 0,
                "conflicting_source_rows": 0,
                "status": "PASS",
            }
            continue
        keys = [column.name for column in target_table.primary_key.columns]
        matching = missing = conflicting = 0
        with (
            source.connect() as source_connection,
            target.connect() as target_connection,
        ):
            source_rows = source_connection.execute(select(source_table)).mappings()
            for raw in source_rows:
                expected = _coerce_row(dict(raw), target_table)
                criteria = [target_table.c[key] == expected[key] for key in keys]
                actual = (
                    target_connection.execute(select(target_table).where(*criteria))
                    .mappings()
                    .first()
                )
                if actual is None:
                    missing += 1
                else:
                    actual_dict = dict(actual)
                    if name == "observations":
                        observation_matches.append((expected, actual_dict))
                    differences = _differences(actual_dict, expected)
                    if differences:
                        conflicting += 1
                    else:
                        matching += 1
        source_count = _count(source, source_table)
        table_reports[name] = {
            "source_rows": source_count,
            "matching_target_rows": matching,
            "missing_source_rows": missing,
            "conflicting_source_rows": conflicting,
            "status": "PASS" if missing == 0 and conflicting == 0 else "FAIL",
        }
    observation = _source_preserved_observation_report(
        source, target, source_meta.tables.get("observations"), observation_matches
    )
    relational = _relational_validation(target)
    summary = (
        "PASS"
        if all(report["status"] == "PASS" for report in table_reports.values())
        and observation["status"] == "PASS"
        and relational["status"] == "PASS"
        else "FAIL"
    )
    return {
        "validation_mode": "source-preserved",
        "table_preservation": table_reports,
        "observation_preservation": observation,
        "relational_integrity": relational,
        "summary": summary,
    }


def _source_preserved_observation_report(source, target, source_table, matches):
    target_table = Base.metadata.tables["observations"]
    if source_table is None:
        return {"status": "PASS", "extra_target_rows": _count(target, target_table)}
    source_slots = set()
    with source.connect() as connection:
        for value in connection.scalars(select(source_table.c.slot_utc)):
            source_slots.add(
                _stable(_coerce_row({"slot_utc": value}, target_table)["slot_utc"])
            )
    extra_slots = []
    with target.connect() as connection:
        for value in connection.scalars(select(target_table.c.slot_utc)):
            if _stable(value) not in source_slots:
                extra_slots.append(value)
    columns = [name for name in RAW_HASH_COLUMNS if name in source_table.c]
    source_hash = _mapping_hash(
        (expected for expected, _actual in matches), columns=columns
    )
    target_hash = _mapping_hash(
        (actual for _expected, actual in matches), columns=columns
    )
    table_report_complete = len(matches) == _count(source, source_table)
    return {
        "source_rows": _count(source, source_table),
        "matching_target_rows": len(matches),
        "extra_target_rows": len(extra_slots),
        "extra_target_slot_start": _stable(min(extra_slots)) if extra_slots else None,
        "extra_target_slot_end": _stable(max(extra_slots)) if extra_slots else None,
        "source_subset_raw_hash": source_hash,
        "target_subset_raw_hash": target_hash,
        "source_subset_raw_hash_status": (
            "PASS" if source_hash == target_hash else "FAIL"
        ),
        "status": (
            "PASS" if table_report_complete and source_hash == target_hash else "FAIL"
        ),
    }


def _mapping_hash(rows, *, columns):
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: _stable(item["slot_utc"])):
        digest.update(
            json.dumps(
                {name: _stable(row.get(name)) for name in columns},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _count(engine, table):
    if table is None:
        return 0
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def _hash_validation(source, target, source_meta):
    source_table = source_meta.tables.get("observations")
    target_table = Base.metadata.tables["observations"]
    if source_table is None:
        return {"status": "PASS", "source_hash": None, "target_hash": None}
    columns = [name for name in RAW_HASH_COLUMNS if name in source_table.c]
    source_hash = _rows_hash(source, source_table, columns, target_table=target_table)
    target_hash = _rows_hash(target, target_table, columns)
    return {
        "status": "PASS" if source_hash == target_hash else "FAIL",
        "source_hash": source_hash,
        "target_hash": target_hash,
    }


def _rows_hash(engine, table, columns, *, target_table=None):
    digest = hashlib.sha256()
    statement = select(*(table.c[name] for name in columns)).order_by(table.c.slot_utc)
    with engine.connect() as connection:
        for row in connection.execute(statement).mappings():
            values = dict(row)
            if target_table is not None:
                values = _coerce_row(values, target_table)
            digest.update(
                json.dumps(
                    {key: _stable(value) for key, value in values.items()},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            digest.update(b"\n")
    return digest.hexdigest()


def _observation_validation(source, target, source_meta):
    source_table = source_meta.tables.get("observations")
    target_table = Base.metadata.tables["observations"]
    if source_table is None:
        return {"status": "PASS", "source": {}, "target": {}}
    important = (
        "battery_soc_percent",
        "battery_power_w",
        "pv_power_w",
        "house_consumption_w",
        "grid_power_w",
        "amber_import_price_per_kwh",
        "amber_export_price_per_kwh",
    )
    source_values = _observation_metrics(source, source_table, important)
    target_values = _observation_metrics(target, target_table, important)
    return {
        "status": "PASS" if source_values == target_values else "FAIL",
        "source": source_values,
        "target": target_values,
    }


def _observation_metrics(engine, table, important):
    metrics = {
        "count": _count(engine, table),
        "unique_slots": 0,
        "duplicate_slots": 0,
        "earliest_slot": None,
        "latest_slot": None,
        "null_counts": {},
    }
    with engine.connect() as connection:
        metrics["unique_slots"] = int(
            connection.scalar(select(func.count(func.distinct(table.c.slot_utc)))) or 0
        )
        metrics["duplicate_slots"] = metrics["count"] - metrics["unique_slots"]
        metrics["earliest_slot"] = _stable(
            connection.scalar(select(func.min(table.c.slot_utc)))
        )
        metrics["latest_slot"] = _stable(
            connection.scalar(select(func.max(table.c.slot_utc)))
        )
        for name in important:
            if name in table.c:
                metrics["null_counts"][name] = int(
                    connection.scalar(
                        select(func.count())
                        .select_from(table)
                        .where(table.c[name].is_(None))
                    )
                    or 0
                )
    return metrics


def _relational_validation(target):
    from energy_optimizer.db.repository import DatabaseRepository

    values = DatabaseRepository(target).integrity_counts()
    return {"status": "PASS" if not any(values.values()) else "FAIL", **values}


def _derived_validation(source, target, source_meta):
    table = Base.metadata.tables["observations"]
    metrics = {}
    for name, predicate in {
        "confirmed_sign_rows": table.c.sign_convention_status == "confirmed",
        "baseline_eligible_rows": table.c.baseline_training_eligible.is_(True),
        "residual_available_rows": table.c.balance_residual_w.is_not(None),
    }.items():
        target_value = _predicate_count(target, table, predicate)
        source_table = source_meta.tables.get("observations")
        if source_table is None or name.split("_rows")[0] not in source_table.c:
            source_value = (
                target_value
                if source_table is None
                else _equivalent_source_count(source, source_table, name)
            )
        else:
            source_value = target_value
        metrics[name] = {"source": source_value, "target": target_value}
    metrics["status"] = (
        "PASS"
        if all(
            v["source"] == v["target"] for v in metrics.values() if isinstance(v, dict)
        )
        else "FAIL"
    )
    return metrics


def _equivalent_source_count(engine, table, metric):
    predicates = {
        "confirmed_sign_rows": table.c.sign_convention_status == "confirmed",
        "baseline_eligible_rows": table.c.baseline_training_eligible == 1,
        "residual_available_rows": table.c.balance_residual_w.is_not(None),
    }
    return _predicate_count(engine, table, predicates[metric])


def _predicate_count(engine, table, predicate):
    with engine.connect() as connection:
        return int(
            connection.scalar(select(func.count()).select_from(table).where(predicate))
            or 0
        )


def _category_passes(value):
    if isinstance(value, dict) and "status" in value:
        return value["status"] == "PASS"
    return (
        all(_category_passes(item) for item in value.values())
        if isinstance(value, dict)
        else True
    )
