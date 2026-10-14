"""Bounded pending-score selection and payload-free operation diagnostics."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from energy_optimizer.db.models import ForecastPoint, ForecastPointScore, ForecastRun

RANGE_WIDTH = 10_000
SELECTION_BUDGET_SECONDS = 60


@dataclass
class ScoringDiagnostics:
    """Only fixed phase names, counts, timings and validated SQLSTATE leave here."""

    phase: str = "not_started"
    ranges: int = 0
    selected: int = 0
    processed: int = 0
    sqlstate: str | None = None
    failed: bool = False
    phase_seconds: dict[str, float] = field(default_factory=dict)
    _started: float = field(default_factory=monotonic, repr=False)
    _phase_started: float = field(default_factory=monotonic, repr=False)
    _finished: float | None = field(default=None, repr=False)

    def enter(self, phase: str) -> None:
        if phase not in {
            "snapshot",
            "pending_selection",
            "payload_fetch",
            "actual_lookup",
            "score_persistence",
            "commit",
            "complete",
        }:
            raise ValueError("Unknown scoring phase")
        now = monotonic()
        if self.phase == "not_started":
            self._started = now
        if self.phase != "not_started":
            self.phase_seconds[self.phase] = (
                self.phase_seconds.get(self.phase, 0) + now - self._phase_started
            )
        self.phase = phase
        self._phase_started = now
        if phase == "complete":
            self._finished = now

    def snapshot(self) -> dict:
        timings = dict(self.phase_seconds)
        end = self._finished if self._finished is not None else monotonic()
        timings[self.phase] = timings.get(self.phase, 0) + end - self._phase_started
        return {
            "version": "bounded-score-selection-v1",
            "phase": self.phase,
            "ranges": self.ranges,
            "selected": self.selected,
            "processed": self.processed,
            "failed": self.failed,
            "sqlstate": self.sqlstate,
            "elapsed_seconds": round(end - self._started, 6),
            "phase_seconds": {k: round(v, 6) for k, v in timings.items()},
        }


@contextmanager
def scoring_trace(diagnostics: ScoringDiagnostics) -> Iterator[None]:
    try:
        yield
    except Exception as exc:
        # Repository transactions translate DBAPI errors. Their suppressed context
        # retains the original SQLSTATE; never stringify either exception.
        raw = exc if isinstance(exc, DBAPIError) else exc.__context__
        state = getattr(getattr(raw, "orig", None), "sqlstate", None)
        if (
            isinstance(state, str)
            and len(state) == 5
            and state.isascii()
            and state.isalnum()
        ):
            diagnostics.sqlstate = state
        diagnostics.failed = True
        diagnostics._finished = monotonic()
        raise
    else:
        diagnostics.enter("complete")


def pending_range_statement(lower: int, upper: int, cutoff: datetime, limit: int):
    scores = (
        select(ForecastPointScore.forecast_point_id)
        .where(
            ForecastPointScore.forecast_point_id >= lower,
            ForecastPointScore.forecast_point_id < upper,
        )
        .cte("bounded_scores")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    return (
        select(ForecastPoint.id, ForecastPoint.period_end_utc)
        .join(ForecastRun, ForecastRun.id == ForecastPoint.forecast_run_id)
        .outerjoin(scores, scores.c.forecast_point_id == ForecastPoint.id)
        .where(
            ForecastPoint.id >= lower,
            ForecastPoint.id < upper,
            ForecastPoint.period_end_utc <= cutoff,
            scores.c.forecast_point_id.is_(None),
            ForecastRun.forecast_type == "baseline_household_load",
        )
        .order_by(ForecastPoint.period_end_utc, ForecastPoint.id)
        .limit(limit)
    )


def select_pending_ids(
    session: Session,
    *,
    cutoff: datetime,
    limit: int,
    runtime_guard: Callable[[], None] | None,
    diagnostics: ScoringDiagnostics,
) -> list[int]:
    """Exact global earliest batch, using a stable snapshot and bounded PK ranges.

    No persistent cursor: future and late-inserted points are reconsidered next
    cycle. A PK seek skips empty ID gaps without treating MAX(id) as a count.
    No partial batch is returned when selection exceeds its runtime budget.
    """
    if not 1 <= limit <= 2500:
        raise ValueError("score limit must be 1-2500")
    started = monotonic()

    def checkpoint() -> None:
        if runtime_guard is not None:
            runtime_guard()
        if monotonic() - started >= SELECTION_BUDGET_SECONDS:
            raise TimeoutError("Forecast scoring selection budget exceeded")

    checkpoint()
    lower = session.scalar(select(ForecastPoint.id).order_by(ForecastPoint.id).limit(1))
    candidates = []
    while lower is not None:
        checkpoint()
        upper = lower + RANGE_WIDTH
        rows = session.execute(
            pending_range_statement(lower, upper, cutoff, limit)
        ).all()
        diagnostics.ranges += 1
        # At most 2 * limit skinny rows; truncation preserves exact global order.
        candidates = sorted(candidates + rows, key=lambda row: (row[1], row[0]))[:limit]
        checkpoint()
        lower = session.scalar(
            select(ForecastPoint.id)
            .where(ForecastPoint.id >= upper)
            .order_by(ForecastPoint.id)
            .limit(1)
        )
    checkpoint()
    diagnostics.selected = len(candidates)
    return [row[0] for row in candidates]
