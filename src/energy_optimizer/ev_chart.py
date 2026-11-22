"""Retrospective and forward EV evidence for read-only household demand charts."""

import logging
import math
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from energy_optimizer.arbitrage.capture import (
    VERSION,
    CaptureRepository,
    decode_capture_body,
)
from energy_optimizer.arbitrage.decision_types import digest
from energy_optimizer.db.models import (
    ArbitrageCapture,
    ArbitrageCommitWitness,
    Observation,
    ShadowDecisionRun,
)
from energy_optimizer.models import HomeAssistantState
from energy_optimizer.timestamps import aware_datetime

HISTORY = "ev_chart_history_v1"
LIVE = "ev_chart_sample_v1"
COUNTER = "ev_chart_counter_v1"
CHANNELS = {
    "charging_power": ("W", "kW"),
    "session_energy": ("kWh",),
    "session_duration": ("min",),
    "session_average_power": ("kW", "W"),
    "session_max_power": ("kW", "W"),
    "session_range_added": ("km",),
    "status": (),
    "plug": (),
}
WINDOW = timedelta(minutes=5)
LOGGER = logging.getLogger(__name__)


def _slot(value: Any) -> datetime:
    slot = aware_datetime(value).astimezone(UTC)
    if slot.minute % 5 or slot.second or slot.microsecond:
        raise ValueError("Expected an aligned five-minute slot")
    return slot


def _nonnegative(value: Any) -> float:
    number = float(value)
    if isinstance(value, bool) or not math.isfinite(number) or number < 0:
        raise ValueError("Expected a finite nonnegative value")
    return number


def prepare_history(row: dict) -> tuple[datetime, datetime, dict]:
    slot = _slot(row["slot"])
    reviewed = aware_datetime(row["review_as_of"]).astimezone(UTC)
    if reviewed < slot + WINDOW:
        raise ValueError("Review predates the interval")
    evidence = {"watts": None, "source": None, "context": []}
    if row.get("provider_session_start") is not None:
        start = aware_datetime(row["provider_session_start"])
        end = aware_datetime(row["provider_session_end"])
        if not (start < end <= reviewed and start < slot + WINDOW and slot < end):
            raise ValueError("Session does not overlap the slot")
        evidence.update(session_start=start.isoformat(), session_end=end.isoformat())
        evidence["context"].append("Reported session window")
    if row.get("state_estimate") == "BYD likely idle":
        evidence["context"].append("Vehicle likely idle")
    if row.get("charger_counter_delta_kwh") is not None:
        kwh = _nonnegative(row["charger_counter_delta_kwh"])
        evidence.update(
            watts=round(kwh * 12000, 3), source="Session counter interval mean"
        )
    elif row.get("power_only") is True:
        kwh = _nonnegative(row["estimated_session_counter_kwh_from_power"])
        evidence.update(
            watts=round(kwh * 12000, 3), source="Power-derived session counter estimate"
        )
    for key in (
        "charger_power_integral_kwh",
        "charger_counter_delta_kwh",
        "estimated_session_counter_kwh_from_power",
    ):
        if row.get(key) is not None:
            evidence[key] = _nonnegative(row[key])
    if evidence["source"] is None and not evidence["context"]:
        raise ValueError("Missing EV evidence")
    evidence["reviewed_at"] = reviewed.isoformat()
    return slot, reviewed, evidence


def import_history(repository, rows: Iterable[dict]) -> int:
    prepared = [prepare_history(row) for row in rows]
    if len({slot for slot, _, _ in prepared}) != len(prepared):
        raise ValueError("Duplicate EV history slot")
    pending = {
        _capture_key(slot, HISTORY): (slot, reviewed, body)
        for slot, reviewed, body in prepared
    }
    keys = list(pending)
    # Verify overlapping files before adding new slots. Preserve the first review date.
    with repository.transaction() as session:
        for offset in range(0, len(keys), 500):
            rows = session.execute(
                select(ArbitrageCapture.id, ArbitrageCapture.body).where(
                    ArbitrageCapture.id.in_(keys[offset : offset + 500])
                )
            )
            for key, storage in rows:
                slot, _, proposed = pending[key]
                saved = decode_capture_body(storage)
                if {**proposed, "reviewed_at": saved["reviewed_at"]} != saved:
                    raise ValueError(
                        f"Conflicting historical EV evidence at {slot.isoformat()}"
                    )
                pending[key] = (slot, aware_datetime(saved["reviewed_at"]), saved)
    store = CaptureRepository(repository)
    for slot, reviewed, evidence in pending.values():
        store.save(origin=slot.isoformat(), kind=HISTORY, at=reviewed, body=evidence)
    return len(prepared)


def charger_entities(prefix: str) -> tuple[str, ...]:
    return tuple(f"{prefix}_{field}" for field in CHANNELS) if prefix else ()


def charger_sample(
    states: dict[str, HomeAssistantState],
    prefix: str,
    slot: datetime,
    receipt: datetime,
) -> dict:
    slot = _slot(slot)
    channels = {}
    for field, units in CHANNELS.items():
        state = states.get(f"{prefix}_{field}")
        if state is None:
            continue
        unit = state.attributes.get("unit_of_measurement")
        if units:
            if unit not in units:
                continue
            try:
                value = _nonnegative(state.state)
            except (ValueError, TypeError, OverflowError):
                continue
        else:
            value = state.state.lower()
            if value not in {
                "charging",
                "connected",
                "disconnected",
                "available",
                "idle",
                "finished",
                "offline",
                "standby",
                "unplugged",
                "plugged",
            }:
                continue
        updated = aware_datetime(state.last_updated).astimezone(UTC)
        channel = {
            "value": value,
            "unit": unit if units else None,
            "updated": updated.isoformat(),
        }
        if state.last_reported is not None:
            channel["reported"] = aware_datetime(state.last_reported).isoformat()
        channels[field] = channel
    body = {
        "channels": channels,
        "station_key": digest(prefix),
        "watts": None,
        "source": None,
        "context": [],
    }
    status = channels.get("status")
    if status and timedelta(0) <= receipt - aware_datetime(status["updated"]) <= WINDOW:
        body["context"].append(f"Station status: {status['value']}")
    # Preserve provider wall times as reported. These describe completed sessions.
    status_state = states.get(f"{prefix}_status")
    if status_state:
        completed = {}
        for key in ("last_session_start", "last_session_end"):
            try:
                completed[key] = datetime.fromisoformat(
                    status_state.attributes.get(key)
                ).isoformat()
            except (ValueError, TypeError):
                continue
        if len(completed) == 2:
            body["last_session_reported_times"] = completed
    power = channels.get("charging_power")
    if power:
        # HA cache update times do not establish physical AC metering.
        updated = aware_datetime(power["updated"])
        if (
            slot <= receipt < slot + WINDOW
            and timedelta(0) <= receipt - updated <= WINDOW
        ):
            body.update(
                watts=power["value"] * (1000 if power["unit"] == "kW" else 1),
                source="Station reported power sample",
            )
    return body


def _capture_key(slot: datetime, kind: str) -> str:
    return digest(
        {"origin": slot.astimezone(UTC).isoformat(), "kind": kind, "version": VERSION}
    )


def interval_counter(previous: dict, current: dict, start: datetime) -> dict | None:
    """Compare near-boundary updates from the same advancing charging session."""
    if previous.get("station_key") != current.get("station_key"):
        return None
    samples = []
    for body, boundary in ((previous, start), (current, start + WINDOW)):
        channels = body["channels"]
        energy = channels.get("session_energy")
        duration = channels.get("session_duration")
        if (
            not energy
            or not duration
            or channels.get("status", {}).get("value") != "charging"
        ):
            return None
        for field in (energy, duration):
            if abs((aware_datetime(field["updated"]) - boundary).total_seconds()) > 60:
                return None
        samples.append(
            (energy["value"], duration["value"], aware_datetime(energy["updated"]))
        )
    left, right = samples
    delta = right[0] - left[0]
    elapsed = (right[2] - left[2]).total_seconds()
    if not (0 < delta <= 1 and 4 <= right[1] - left[1] <= 6 and 270 <= elapsed <= 330):
        return None
    return {
        "watts": round(delta * 3600000 / elapsed, 2),
        "source": "Session counter mean between reports",
        "context": [],
        "energy_kwh": delta,
        "from": left[2].isoformat(),
        "to": right[2].isoformat(),
    }


def capture_charger(
    states: dict,
    prefix: str,
    slot: datetime,
    receipt: datetime,
    repository_factory: Callable,
) -> None:
    repository = None
    try:
        body = charger_sample(states, prefix, slot, receipt)
        repository = repository_factory()
        store = CaptureRepository(repository)
        slot = _slot(slot)
        store.save(origin=slot.isoformat(), kind=LIVE, at=receipt, body=body)
        start = slot - WINDOW
        with repository.transaction() as session:
            stored = session.scalar(
                select(ArbitrageCapture.body)
                .join(
                    ArbitrageCommitWitness,
                    ArbitrageCommitWitness.capture_id == ArbitrageCapture.id,
                )
                .where(ArbitrageCapture.id == _capture_key(start, LIVE))
            )
        if stored is not None:
            interval = interval_counter(decode_capture_body(stored), body, start)
            if interval is not None:
                store.save(
                    origin=start.isoformat(), kind=COUNTER, at=receipt, body=interval
                )
    except Exception as exc:
        LOGGER.warning(
            "Optional EV chart capture failed (%s); core observation saved",
            type(exc).__name__,
        )
    finally:
        if repository is not None:
            try:
                repository.close()
            except Exception as exc:
                LOGGER.warning(
                    "Optional EV chart cleanup failed (%s)", type(exc).__name__
                )


def attach_chart_evidence(session: Session, run: Any, points: list[dict]) -> list[dict]:
    if run["forecast_type"] not in {"household_load", "baseline_household_load"}:
        return []
    slots = {
        p["period_start_utc"]: p
        for p in points
        if p["period_end_utc"] - p["period_start_utc"] == WINDOW
        and p["period_start_utc"].minute % 5 == 0
        and p["period_start_utc"].second == 0
        and p["period_start_utc"].microsecond == 0
    }
    # Chunk indexed lookups to respect SQLite host-parameter limits.
    ordered = sorted(slots)
    for offset in range(0, len(ordered), 300):
        batch = ordered[offset : offset + 300]
        for slot, site, ev, active, source, fresh in session.execute(
            select(
                Observation.slot_utc,
                Observation.house_consumption_w,
                Observation.ev_power_w,
                Observation.ev_charging_active,
                Observation.ev_source,
                Observation.ev_telemetry_fresh,
            ).where(
                Observation.slot_utc.in_(batch),
                Observation.telemetry_is_healthy.is_(True),
            )
        ):
            slots[slot]["site_actual_w"] = site
            if active is not None and source == "byd_vehicle_cloud" and fresh:
                slots[slot]["ev_context"] = (
                    "Vehicle reports charging" if active else "Vehicle reports idle"
                )
            elif source == "manual_annotation":
                slots[slot]["ev_context"] = "Reviewed session annotation"
            if ev is not None and ev >= 0:
                slots[slot].update(ev_adjustment_w=ev, ev_source="Direct charger AC")
        keys = {
            _capture_key(slot, kind): slot
            for slot in batch
            for kind in (LIVE, HISTORY, COUNTER)
        }
        rows = session.execute(
            select(ArbitrageCapture.id, ArbitrageCapture.kind, ArbitrageCapture.body)
            .join(
                ArbitrageCommitWitness,
                ArbitrageCommitWitness.capture_id == ArbitrageCapture.id,
            )
            .where(ArbitrageCapture.id.in_(keys))
        )
        # Prefer direct AC, then interval evidence, then the instantaneous sample.
        priority = {HISTORY: 0, COUNTER: 1, LIVE: 2}
        for key, _kind, storage in sorted(rows, key=lambda row: priority[row.kind]):
            point = slots[keys[key]]
            body = decode_capture_body(storage)
            if body.get("context"):
                point["ev_context"] = ", ".join(
                    filter(None, [point.get("ev_context"), *body["context"]])
                )
            if point.get("ev_adjustment_w") is None and body.get("watts") is not None:
                point.update(ev_adjustment_w=body["watts"], ev_source=body["source"])
    decision = ShadowDecisionRun
    actions = (
        select(
            decision.created_at_utc,
            decision.selected_action,
            decision.status,
            decision.selected_start_utc,
            decision.selected_end_utc,
            decision.no_command_issued,
        )
        .where(decision.forecast_run_id == run["id"])
        .order_by(decision.created_at_utc, decision.id)
        .limit(288)
    )
    return [dict(action) for action in session.execute(actions).mappings()]
