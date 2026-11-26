"""Issue-time household comparison, isolated from the operational forecast."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from statistics import median

from sqlalchemy import select, text

from energy_optimizer.arbitrage.capture import (
    VERSION as CAPTURE_VERSION,
)
from energy_optimizer.arbitrage.capture import (
    CaptureRepository,
    decode_capture_body,
)
from energy_optimizer.arbitrage.decision_types import digest
from energy_optimizer.db.models import ArbitrageCapture, ArbitrageCommitWitness
from energy_optimizer.forecast_calibration import CURRENT_FORECAST_MODEL_VERSION

MODEL = "household-combined-eased-v1"
KIND = "household_shadow"
STEP = timedelta(minutes=5)


@dataclass(frozen=True)
class Sample:
    slot: datetime
    error: float
    household: float | None = None


def select_offset(issue, fresh, delayed):
    for source, readings, max_age in (
        ("fresh", fresh, 15),
        ("delayed", delayed, 45),
    ):
        if not readings:
            continue
        latest = max(readings)
        age = (issue - latest - STEP).total_seconds()
        window = [s for t, s in readings.items() if latest - t < 12 * STEP]
        if not 0 <= age <= max_age * 60 or len(window) < 9:
            continue
        offset = max(-1000.0, min(1000.0, median(s.error for s in window)))
        original = offset
        if source == "fresh" and offset > 0:
            end = issue.replace(minute=issue.minute // 5 * 5, second=0, microsecond=0)
            six = [readings.get(end - n * STEP) for n in range(6, 0, -1)]
            if all(s is not None for s in six):
                before = median(s.household for s in six[:3])
                after = median(s.household for s in six[3:])
                if before - after >= 500:
                    offset = min(offset, max(0.0, median(s.error for s in six[3:])))
        return dict(
            source=source,
            offset_w=offset,
            age_seconds=age,
            input_count=len(window),
            eased=offset < original,
        )
    return dict(
        source="issued", offset_w=0.0, age_seconds=None, input_count=0, eased=False
    )


_POINTS = text("""
    SELECT p.period_start_utc AS slot, r.created_at_utc, p.expected_value,
           s.actual_value, s.health_eligible, s.actual_available,
           scoring.finished_at_utc AS score_finished, pub.finished_at_utc AS published
    FROM forecast_runs r JOIN forecast_points p ON p.forecast_run_id=r.id
    LEFT JOIN forecast_point_scores s ON s.forecast_point_id=p.id
        AND s.scored_at_utc<=:issue
    LEFT JOIN forecast_operation_attempts scoring
        ON scoring.started_at_utc=s.scored_at_utc
        AND scoring.status='success' AND scoring.finished_at_utc<=:issue
    LEFT JOIN forecast_operation_attempts pub ON pub.forecast_run_id=r.id
        AND pub.status='success' AND pub.finished_at_utc<=p.period_start_utc
    WHERE r.created_at_utc BETWEEN :earliest AND :issue
        AND r.source='scheduled_forecast_operations'
        AND r.forecast_type='baseline_household_load'
        AND r.model_version=:model
        AND r.metadata_json->>'training_policy'='verified_preferred'
        AND r.metadata_json->>'alignment_version'='full_5m_v1'
        AND p.period_start_utc>=r.created_at_utc
        AND p.period_start_utc<r.created_at_utc+interval '3 hours'
        AND p.period_start_utc>=:lo AND p.period_end_utc<=:issue
    ORDER BY r.created_at_utc
""")

_OBS = text("""
    SELECT o.slot_utc, o.house_consumption_w,
           o.baseline_house_consumption_w, o.ev_power_w
    FROM observations o WHERE o.slot_utc BETWEEN :lo AND :issue
      AND o.observed_at_utc<=:issue AND o.telemetry_is_healthy
      AND o.baseline_training_eligible
      AND o.baseline_exclusion_reason IS NULL AND o.reprocessed_at_utc IS NULL
      AND o.house_consumption_w>=0 AND o.baseline_house_consumption_w IS NOT NULL
      AND (o.ev_power_w IS NOT NULL OR
           (o.ev_telemetry_fresh AND o.ev_charging_active IS FALSE))
      AND NOT EXISTS(SELECT 1 FROM ev_session_annotation_rows e
                     WHERE e.slot_utc=o.slot_utc)
      AND NOT EXISTS(SELECT 1 FROM observation_derivations d
                     WHERE d.slot_utc=o.slot_utc)
""")

_CAPS = text("""
    WITH sources AS MATERIALIZED (
        SELECT c.origin,c.captured_at_utc,
           COALESCE((c.body->>'canonical_body_json')::jsonb,c.body::jsonb)
               #>'{sources,house_power}' AS h
        FROM arbitrage_input_captures c JOIN arbitrage_commit_witnesses w
          ON w.capture_id=c.id
        WHERE c.kind='source' AND c.captured_at_utc BETWEEN :lo AND :issue
              AND w.confirmed_at_utc<=:issue)
    SELECT origin,captured_at_utc,h->>'state',
           h#>>'{attributes,unit_of_measurement}',h->>'reported_at'
    FROM sources
""")


def read_inputs(repository, issue, model):
    lo = issue - timedelta(minutes=110)
    params = dict(issue=issue, lo=lo, earliest=lo - timedelta(hours=3), model=model)
    published, delayed, fresh = {}, {}, {}
    with repository.transaction() as session:
        for row in session.execute(_POINTS, params).mappings():
            slot, base = row["slot"], row["expected_value"]
            if not isfinite(base):
                continue
            if row["published"] is not None:
                published[slot] = base
            actual = row["actual_value"]
            if (
                row["score_finished"]
                and row["health_eligible"]
                and row["actual_available"]
                and actual is not None
                and isfinite(actual)
            ):
                delayed[slot] = Sample(slot, actual - base)
        observations = {r[0]: r for r in session.execute(_OBS, params)}
        for origin, captured, state, unit, reported in session.execute(_CAPS, params):
            if unit not in ("W", "kW") or not reported:
                continue
            try:
                slot = datetime.fromisoformat(origin)
                seen = datetime.fromisoformat(reported)
                value = float(state) * (1000 if unit == "kW" else 1)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                slot not in published
                or slot not in observations
                or seen.tzinfo is None
                or not 0 <= (captured - seen).total_seconds() <= 300
            ):
                continue
            _, site, household, ev = observations[slot]
            if (
                all(isfinite(w) for w in (value, site, household, ev or 0))
                and abs(site - value) <= 0.01
                and abs(household - (site - (ev or 0))) < 0.01
            ):
                fresh[slot] = Sample(slot, household - published[slot], household)
    return fresh, delayed


def record(repository, run, run_id, clock):
    issue = run.created_at_utc
    first = run.horizon_start_utc
    if (
        run.model_version != CURRENT_FORECAST_MODEL_VERSION
        or run.metadata.get("training_policy") != "verified_preferred"
        or run.metadata.get("alignment_version") != "full_5m_v1"
        or not run.points
        or clock() >= first
    ):
        return
    fresh, delayed = read_inputs(repository, issue, run.model_version)
    summary = select_offset(issue, fresh, delayed)
    values = []
    for p in run.points:
        lead = (p.period_start_utc - issue).total_seconds()
        value = max(
            0.0, p.expected_value + summary["offset_w"] * max(0.0, 1 - lead / 10800)
        )
        values.append([p.period_start_utc.isoformat(), p.expected_value, value])
    at = clock()
    if at >= first:
        return
    body = dict(
        model=MODEL,
        run_id=run_id,
        issue=issue.isoformat(),
        first=first.isoformat(),
        decision=summary,
        points=values,
    )
    CaptureRepository(repository).save(
        origin=f"{MODEL}/{run_id}", kind=KIND, at=at, body=body, clock=clock
    )


def read_pair(repository, run_id):
    key = digest(dict(origin=f"{MODEL}/{run_id}", kind=KIND, version=CAPTURE_VERSION))
    with repository.transaction() as session:
        row = session.execute(
            select(ArbitrageCapture.body, ArbitrageCommitWitness.confirmed_at_utc)
            .join(
                ArbitrageCommitWitness,
                ArbitrageCommitWitness.capture_id == ArbitrageCapture.id,
            )
            .where(ArbitrageCapture.id == key)
        ).first()
    if row is None:
        return None
    body = decode_capture_body(row[0])
    if (
        body["model"] != MODEL
        or body["run_id"] != run_id
        or row[1] >= datetime.fromisoformat(body["first"])
    ):
        return None
    return body
