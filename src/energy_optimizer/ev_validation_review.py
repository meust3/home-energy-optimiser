"""Local side-by-side review of the frozen EV validation cohort."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Collection
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from energy_optimizer.ev_validation_metrics import comparison, improves, summarize
from energy_optimizer.timestamps import aware_datetime

VERSION = "ev-validator-segmented-v2"
IDLE = {"available", "idle", "finished", "disconnected", "unplugged"}
PAGE_SIZE = 144


def prepare(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS review_slots_v2(
            slot INTEGER PRIMARY KEY, state TEXT, state_at REAL,
            watts REAL, power_at REAL,
            checkpoint TEXT, detected_start REAL, detected_end REAL);
        CREATE INDEX IF NOT EXISTS review_detections_v2 ON review_slots_v2(slot)
            WHERE detected_start IS NOT NULL;
        CREATE TABLE IF NOT EXISTS review_progress_v2(
            id INTEGER PRIMARY KEY, witnessed REAL, scanned INTEGER);
        CREATE TABLE IF NOT EXISTS review_scores_v2(
            start REAL, end REAL, summary TEXT, PRIMARY KEY(start,end));
    """)


def store_capture(
    db: sqlite3.Connection, slot: int, receipt: float, body: dict
) -> None:
    channels = body.get("channels", {})
    status = channels.get("status") or {}
    power = channels.get("charging_power") or {}

    def updated(channel: dict) -> float | None:
        stamp = channel.get("updated")
        if stamp:
            value = aware_datetime(stamp).timestamp()
            if 0 <= receipt - value <= 600:
                return value
        return None

    watts = power.get("value")
    if not isinstance(watts, (int, float)) or not math.isfinite(watts) or watts < 0:
        watts = None
    elif power.get("unit") == "kW":
        watts *= 1000
    elif power.get("unit") != "W":
        watts = None
    inserted = db.execute(
        "INSERT OR IGNORE INTO review_slots_v2(slot,state,state_at,watts,power_at) "
        "VALUES(?,?,?,?,?)",
        (slot, status.get("value"), updated(status), watts, updated(power)),
    )
    if inserted.rowcount:
        # A witness may arrive after a later slot. Rebuild from the last valid prefix.
        db.execute(
            "UPDATE review_progress_v2 SET scanned=min(scanned,?) WHERE id=1",
            (slot - 1,),
        )


@dataclass
class Pending:
    start: float | None = None
    positive: bool = False
    idle_at: float | None = None
    zero_at: float | None = None

    def observe(
        self,
        slot: int,
        state: str | None,
        state_at: float | None,
        watts: float | None,
        power_at: float | None,
        freeze: float,
    ) -> tuple[Pending, tuple[float, float] | None]:
        if state == "charging":
            if self.idle_at is not None:
                self = Pending()
            if self.start is None and state_at is not None and state_at >= freeze:
                self.start = state_at
        elif state not in IDLE:
            return Pending(), None
        elif self.start is not None and self.idle_at is None:
            if state_at is None or state_at <= self.start:
                return Pending(), None
            self.idle_at = state_at
        if self.start is None:
            return self, None
        if watts is not None and power_at is not None and power_at >= self.start:
            if watts > 0 and (self.idle_at is None or power_at < self.idle_at):
                self.positive = True
            if watts > 0 and self.zero_at is not None and power_at >= self.zero_at:
                self.zero_at = None
            elif watts == 0:
                self.zero_at = power_at
        if self.idle_at is not None:
            if (
                self.positive
                and self.zero_at is not None
                and -120 <= self.zero_at - self.idle_at <= 300
            ):
                return Pending(), (self.start, self.idle_at)
            if slot > self.idle_at + 600:
                return Pending(), None
        return self, None


def scan(db: sqlite3.Connection, freeze: float, fence: float) -> int:
    last = db.execute("SELECT scanned FROM review_progress_v2 WHERE id=1").fetchone()[0]
    previous = db.execute(
        "SELECT slot,checkpoint FROM review_slots_v2 WHERE slot<=? "
        "ORDER BY slot DESC LIMIT 1",
        (last,),
    ).fetchone()
    pending = Pending(**json.loads(previous[1])) if previous else Pending()
    prior_slot = previous[0] if previous else None
    slots = db.execute(
        "SELECT slot,state,state_at,watts,power_at FROM review_slots_v2 "
        "WHERE slot>? AND slot<=? ORDER BY slot LIMIT ?",
        (last, fence, PAGE_SIZE),
    ).fetchall()
    for slot, state, at, watts, power_at in slots:
        if prior_slot is None or slot - prior_slot != 300:
            pending = Pending()
        pending, detected = pending.observe(slot, state, at, watts, power_at, freeze)
        db.execute(
            "UPDATE review_slots_v2 SET checkpoint=?,detected_start=?,detected_end=? "
            "WHERE slot=?",
            (json.dumps(asdict(pending)), *(detected or (None, None)), slot),
        )
        prior_slot = last = slot
    db.execute("UPDATE review_progress_v2 SET scanned=? WHERE id=1", (last,))
    return last


def score_one(
    db: sqlite3.Connection, first: list, channels: Collection[str]
) -> list[dict]:
    scored = []
    computed = False
    for start, end in first:
        row = db.execute(
            "SELECT summary FROM review_scores_v2 WHERE start=? AND end=?", (start, end)
        ).fetchone()
        if row:
            scored.append(json.loads(row[0]))
        elif (
            not computed
            and db.execute(
                "SELECT 1 FROM scores WHERE start=? AND end=?", (start, end)
            ).fetchone()
        ):
            streams = {k: [] for k in channels}
            for k, t, value in db.execute(
                "SELECT channel,at,value FROM readings "
                "WHERE start=? AND end=? ORDER BY at",
                (start, end),
            ):
                streams[k].append((t, value))
            summary = summarize(start, end, streams, recover_resets=True)
            db.execute(
                "INSERT INTO review_scores_v2 VALUES(?,?,?)",
                (start, end, json.dumps(summary, allow_nan=False)),
            )
            scored.append(summary)
            computed = True
    return scored


def review_status(
    db: sqlite3.Connection,
    first: list,
    windows: list,
    channels: Collection[str],
    original: dict,
    freeze: float,
    fence: float,
) -> dict:
    scanned = scan(db, freeze, fence)
    backlog = db.execute(
        "SELECT 1 FROM review_slots_v2 WHERE slot>? AND slot<=? LIMIT 1",
        (scanned, fence),
    ).fetchone()
    witnessed = db.execute(
        "SELECT witnessed FROM review_progress_v2 WHERE id=1"
    ).fetchone()[0]
    rows = score_one(db, first, channels)
    unmatched = []
    for a, b in db.execute(
        "SELECT detected_start,detected_end FROM review_slots_v2 WHERE slot<=? "
        "AND detected_start IS NOT NULL AND detected_start<? ORDER BY slot",
        (min(scanned, fence), first[-1][1] if len(first) == 10 else fence),
    ):
        matches = sum(abs(x - a) <= 120 and abs(y - b) <= 120 for x, y in windows)
        if matches != 1:
            unmatched.append(
                dict(
                    start=datetime.fromtimestamp(a, UTC).isoformat(),
                    end=datetime.fromtimestamp(b, UTC).isoformat(),
                    status="ambiguous" if matches else "provisional",
                    final_kwh=None,
                )
            )
    decision = "collecting"
    if backlog or witnessed < aware_datetime(original["discovery_through"]).timestamp():
        decision = "catching up"
    elif len(rows) == 10:
        supported = (
            original["missing_collection_slots"] == 0
            and original["unmatched_charging_updates"] == 0
            and original["status"]
            not in {"overlapping sessions require reconciliation", "catching up"}
            and not unmatched
            and original["coverage"] is not None
            and original["coverage"] >= 0.9
            and sum(improves([r]) for r in rows) > 5
            and all(improves(rows[:i] + rows[i + 1 :]) for i in range(10))
        )
        decision = (
            "ready for manual review"
            if supported
            else "inspect evidence before promotion"
        )
    duration = sum(r["seconds"] for r in rows)
    return dict(
        version=VERSION,
        status=decision,
        completed=len(rows),
        required=10,
        discovered_through=datetime.fromtimestamp(witnessed, UTC).isoformat(),
        sessions=rows,
        provisional_sessions=unmatched,
        direct_coverage=(
            sum(r["aligned_seconds"] for r in rows) / duration if duration else None
        ),
        sessions_improving_both_metrics=sum(improves([r]) for r in rows),
        improvement_survives_each_session_omission=(
            all(improves(rows[:i] + rows[i + 1 :]) for i in range(10))
            if len(rows) == 10
            else None
        ),
        aligned=comparison(rows, "pairs", ["station", "counter"]),
        including_fallbacks=comparison(
            rows, "revised_pairs", ["revised", "reference_counter"]
        ),
    )
