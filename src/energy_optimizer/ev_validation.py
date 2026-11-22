"""App-owned EV validation. Recorder reads and derived evidence only."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from energy_optimizer.arbitrage.capture import CaptureRepository, decode_capture_body
from energy_optimizer.arbitrage.decision_types import digest
from energy_optimizer.db.models import ArbitrageCapture, ArbitrageCommitWitness
from energy_optimizer.entity_ids import GOODWE_HOUSE_CONSUMPTION
from energy_optimizer.ev_chart import LIVE
from energy_optimizer.ev_validation_metrics import (
    comparison_report,
    improves,
    summarize,
)
from energy_optimizer.timestamps import aware_datetime, utc_datetime

REPORT_KIND = "ev_validator_ten_v1"
STATE_DIR = Path("/data/ev-validation")


def discovered(repository, since: datetime, until: datetime) -> list:
    with repository.transaction() as session:
        return session.execute(
            select(
                ArbitrageCapture.origin,
                ArbitrageCapture.captured_at_utc,
                ArbitrageCapture.body,
            )
            .join(
                ArbitrageCommitWitness,
                ArbitrageCommitWitness.capture_id == ArbitrageCapture.id,
            )
            .where(
                ArbitrageCapture.kind == LIVE,
                ArbitrageCommitWitness.confirmed_at_utc >= since,
                ArbitrageCommitWitness.confirmed_at_utc <= until,
            )
        ).all()


def read_channels(
    groups: list, ids: dict, start: float, end: float, request_start: float
) -> list:
    names = {v: k for k, v in ids.items()}
    rows = []
    for group in groups:
        for row in group:
            key = names.get(row.get("entity_id"))
            if key is None:
                continue
            t = aware_datetime(row["last_updated"]).timestamp()
            # Recorder inserts a synthetic starting state at the request boundary.
            if abs(t - request_start) < 0.01 or (
                key in {"station", "energy"} and not start <= t < end
            ):
                continue
            unit = row.get("attributes", {}).get("unit_of_measurement")
            try:
                value = float(row["state"])
                if key != "energy" and unit == "kW":
                    value *= 1000
                elif unit != ("kWh" if key == "energy" else "W"):
                    value = None
                if value is not None and (not math.isfinite(value) or value < 0):
                    value = None
            except (ValueError, TypeError):
                value = None
            rows.append((key, t, value))
    return rows


class EVValidator:
    """Resume witnessed discovery and one bounded recorder page per scheduler turn."""

    def __init__(
        self,
        *,
        directory: Path,
        frozen: datetime,
        prefix: str,
        reference: str,
        timezone: str,
        repository_factory: Callable,
        read_history: Callable,
    ):
        self.frozen = aware_datetime(frozen).astimezone(UTC)
        self.timezone = ZoneInfo(timezone)
        self.ids = {
            "site": GOODWE_HOUSE_CONSUMPTION,
            "station": prefix + "_charging_power",
            "energy": prefix + "_session_energy",
            "load": reference,
        }
        if len(set(self.ids.values())) != 4:
            raise ValueError("Validation requires four distinct sensors")
        self.station = digest(prefix)
        self.identity = digest([1, self.frozen.isoformat(), self.ids, timezone])
        self.directory = directory / self.identity
        self.read_history = read_history
        self.repository_factory = repository_factory

    def status(self) -> dict:
        try:
            return json.loads(
                (self.directory / "status.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return {
                "status": "waiting for first collection",
                "completed": 0,
                "required": 10,
            }

    def _events(self, db, captures: list) -> None:
        def wall_time(value: str) -> float:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=self.timezone)
            return parsed.timestamp()

        for origin, receipt, stored in captures:
            body = decode_capture_body(stored)
            if body["station_key"] != self.station:
                raise ValueError("Charger identity changed in validation population")
            receipt_ts = utc_datetime(receipt).timestamp()
            status = body.get("channels", {}).get("status") or {}
            active = None
            if status.get("value") == "charging":
                updated = wall_time(status["updated"])
                if 0 <= receipt_ts - updated <= 300:
                    active = updated
            times = body.get("last_session_reported_times") or {}
            start = end = None
            if times.get("last_session_start") and times.get("last_session_end"):
                start, end = (
                    wall_time(times[k])
                    for k in ("last_session_start", "last_session_end")
                )
                if not start < end <= receipt_ts:
                    start = end = None
            db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?)",
                (int(aware_datetime(origin).timestamp()), active, start, end),
            )

    def _page(self, db, start: float, end: float) -> None:
        row = db.execute(
            "SELECT through FROM pages WHERE start=? AND end=?", (start, end)
        ).fetchone()
        cursor = row[0] if row else start - 600
        # Overlap page boundaries so an actual change exactly on the boundary survives.
        left = cursor - 1 if row else cursor
        right = min(end + 600, cursor + 7200)
        groups = self.read_history(
            self.ids.values(),
            datetime.fromtimestamp(left, UTC),
            datetime.fromtimestamp(right, UTC),
        )
        rows = read_channels(groups, self.ids, start, end, left)
        db.executemany(
            "INSERT OR REPLACE INTO readings VALUES(?,?,?,?,?)",
            [(start, end, *r) for r in rows],
        )
        db.execute("INSERT OR REPLACE INTO pages VALUES(?,?,?)", (start, end, right))
        if right < end + 600:
            return
        streams = {key: [] for key in self.ids}
        for key, at, value in db.execute(
            "SELECT channel,at,value FROM readings WHERE start=? AND end=? ORDER BY at",
            (start, end),
        ):
            streams[key].append((at, value))
        result = summarize(start, end, streams)
        db.execute(
            "INSERT INTO scores VALUES(?,?,?)",
            (start, end, json.dumps(result, allow_nan=False)),
        )

    def step(self, now: datetime) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.directory / "discovery.sqlite")) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY, at REAL);
                CREATE TABLE IF NOT EXISTS events (
                    slot INTEGER PRIMARY KEY, active REAL, start REAL, end REAL);
                CREATE INDEX IF NOT EXISTS windows ON events(start,end);
                CREATE TABLE IF NOT EXISTS scores (
                    start REAL,end REAL,summary TEXT,PRIMARY KEY(start,end));
                CREATE TABLE IF NOT EXISTS pages (
                    start REAL,end REAL,through REAL,PRIMARY KEY(start,end));
                CREATE TABLE IF NOT EXISTS readings (
                    start REAL,end REAL,channel TEXT,at REAL,value REAL,
                    PRIMARY KEY(start,end,channel,at));
                CREATE TABLE IF NOT EXISTS publication (digest TEXT PRIMARY KEY);
            """)
            cursor = db.execute("SELECT at FROM cursor WHERE id=1").fetchone()
            since = (
                max(self.frozen, datetime.fromtimestamp(cursor[0] - 300, UTC))
                if cursor
                else self.frozen
            )
            if now < since:
                return
            until = min(since + timedelta(hours=12), now)
            with closing(self.repository_factory()) as repository:
                captures = discovered(repository, since, until)
                with db:
                    self._events(db, captures)
                    db.execute(
                        "INSERT OR REPLACE INTO cursor VALUES(1,?)",
                        (until.timestamp(),),
                    )
                windows = db.execute(
                    "SELECT start,max(end) FROM events WHERE start IS NOT NULL "
                    "GROUP BY start ORDER BY start"
                ).fetchall()
                selected = [(a, b) for a, b in windows if a >= self.frozen.timestamp()]
                conflict = any(
                    b > c for (_, b), (c, _) in zip(windows, windows[1:], strict=False)
                )
                if not conflict:
                    for a, b in selected:
                        if (
                            b + 600 <= now.timestamp()
                            and not db.execute(
                                "SELECT 1 FROM scores WHERE start=? AND end=?", (a, b)
                            ).fetchone()
                        ):
                            with db:
                                self._page(db, a, b)
                            break
                summaries = dict(
                    ((a, b), json.loads(s))
                    for a, b, s in db.execute("SELECT start,end,summary FROM scores")
                )
                first = selected[:10]
                rows = [summaries[w] for w in first if w in summaries]
                fence = first[-1][1] if len(first) == 10 else until.timestamp()
                lo = math.ceil(self.frozen.timestamp() / 300) * 300
                hi = math.floor(fence / 300) * 300
                present = db.execute(
                    "SELECT count(*) FROM events WHERE slot>=? AND slot<?", (lo, hi)
                ).fetchone()[0]
                gaps = max(0, (hi - lo) // 300 - present)
                unmatched = sum(
                    not any(a - 300 <= t <= b + 300 for a, b in windows)
                    for (t,) in db.execute(
                        "SELECT DISTINCT active FROM events "
                        "WHERE active>=? AND active<=?",
                        (self.frozen.timestamp(), fence),
                    )
                )
                coverage = (
                    sum(r["aligned_seconds"] for r in rows)
                    / sum(r["seconds"] for r in rows)
                    if rows
                    else None
                )
                votes = sum(improves([r]) for r in rows)
                status = dict(
                    as_of=now.isoformat(),
                    discovery_through=until.isoformat(),
                    frozen_at=self.frozen.isoformat(),
                    required=10,
                    completed=len(rows),
                    all_completed=sum(w in summaries for w in selected),
                    discovered=len(selected),
                    unmatched_charging_updates=unmatched,
                    missing_collection_slots=gaps,
                    coverage=coverage,
                    sessions_improving_both_metrics=votes,
                    sessions=rows,
                    status="awaiting sessions",
                )
                if conflict:
                    status["status"] = "overlapping sessions require reconciliation"
                elif until < now:
                    status["status"] = "catching up"
                elif len(rows) == 10:
                    passed = (
                        coverage >= 0.9
                        and votes > 5
                        and not gaps
                        and not unmatched
                        and all(improves(rows[:i] + rows[i + 1 :]) for i in range(10))
                    )
                    status["status"] = (
                        "ready for manual review"
                        if passed
                        else "inspect evidence before promotion"
                    )
                    report = comparison_report(status)
                    key = digest([self.identity, report])
                    if not db.execute(
                        "SELECT 1 FROM publication WHERE digest=?", (key,)
                    ).fetchone():
                        CaptureRepository(repository).save(
                            origin=key, kind=REPORT_KIND, at=now, body=report
                        )
                        with db:
                            db.execute("INSERT INTO publication VALUES(?)", (key,))
                    status["comparison"] = report
                partial = self.directory / "status.tmp"
                partial.write_text(
                    json.dumps(status, allow_nan=False), encoding="utf-8"
                )
                os.replace(partial, self.directory / "status.json")


def build_app_validator(options, config, database_url: str) -> EVValidator:
    from energy_optimizer.context_collection import open_bounded_context_repository
    from energy_optimizer.home_assistant import HomeAssistantClient

    def read_history(ids, start: datetime, end: datetime) -> list:
        with HomeAssistantClient(
            config.ha_url, config.ha_token, timeout_seconds=10
        ) as client:
            return client.recorder_history(ids, start, end)

    return EVValidator(
        directory=STATE_DIR,
        frozen=aware_datetime(options.ev_validation_start),
        prefix=options.ev_chart_charger_prefix,
        reference=options.ev_validation_reference,
        timezone=options.timezone,
        repository_factory=lambda: open_bounded_context_repository(database_url),
        read_history=read_history,
    )
