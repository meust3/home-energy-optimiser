# Local pending-score inventory fix (unreleased)

This patch addresses the confirmed mechanism in the October 20/23 scoring
failures: the selector swept all historical primary-key ranges before returning
an exact batch, exhausting its own 60-second selection budget. The underlying
reason individual production queries became slower remains unproven. Local
performance measurements do not establish NAS throughput or forecast accuracy,
and no arbitrage savings follow from this change.

## Invariants and bounded work

`forecast_score_pending` contains one row for every unscored
`baseline_household_load` point, including future intervals and late historical
inserts. Its primary key prevents duplicate inventory rows. The due index orders
`(period_end_utc, forecast_point_id)`; the selector fetches and locks at most 2,500
due IDs in that exact order with no historical scan, recent-only cutoff,
permanent cursor or `SKIP LOCKED` starvation. The established scoring delay,
actual lookup, EV eligibility, forecast values and scoring calculations are
unchanged. The existing coordinator runtime guard and server query timeouts
remain in force. The selection-specific timeout now has a distinct safe summary.

Database triggers synchronize point inserts and relevant updates, score
insert/delete/primary-key update, and run forecast-type changes. Forecasts,
scores and inventory share transactions. Interrupted scoring rolls back both
scores and dequeues. A stale concurrent PostgreSQL worker can fail serialization;
the next existing coordinator cycle retries the still-pending work. No worker,
scheduler or autonomous control is added. Retention's explicit score-then-point
deletion and point FK cascades preserve consistency. PostgreSQL TRUNCATE of
scores or the inventory is refused because it bypasses row triggers.

The inventory is derived state. Trigger disabling, manual inventory edits,
replication that bypasses triggers or incomplete restores are unsupported; they
require an explicitly approved audit/reconciliation before scoring resumes.
There is no automatic historical repair at startup. PostgreSQL functions use
invoker privileges, fixed schema-qualified relations and `pg_catalog` search path.
The helper's version-one trigger semantics are part of migration `20261024_01`;
future changes need a new explicit migration, preserving this revision's meaning.

## Explicit migration and rollback requirements

The new source expects Alembic head `20261024_01`, following `20261008_01`.
The normal schema gate refuses the old schema. No deployment or live migration
has been authorized or performed. Metadata DDL hooks are for the existing
explicit test schema creation path; application startup never creates/backfills
the inventory.

A later rollout needs separate approval and a maintenance window:

1. Freeze the reviewed source, take and verify a recoverable backup, and rehearse
   the migration on an isolated copy of the actual database. Measure its full
   inventory/backfill size and scoring duration; synthetic warm-cache timings
   are insufficient for production sizing.
2. Stop analytical writers, including the collector/coordinator and retention,
   before the explicit migration. Confirm migration ownership and the intended
   runtime role's required queue DML/function permissions without assuming the
   application has schema-owner privileges. This patch changes no grants.
3. Apply the explicit revision. PostgreSQL takes write-excluding locks on runs,
   points and scores, with 1-second lock and 5-second statement timeouts.
   Backfill visits at most 10,000 PKs per batch with a 120-second total backfill
   budget, retaining all unscored points. Timeout/error rolls back DDL, triggers,
   data and revision; investigate/rehearse rather than extending live deadlines
   blindly. SQLite explicitly begins its write transaction before DDL, including
   downgrade, to avoid legacy sqlite3 DDL autocommit. Offline SQL rendering is
   refused because it cannot perform or validate the data backfill.
4. Before starting the matching source, verify head, due index, FK and all six
   synchronization triggers (plus two PostgreSQL TRUNCATE guards and seven
   functions), enabled trigger state and invoker/search-path definitions. Compare
   the entire inventory to the authoritative unscored point/run/score join in
   both directions, including future intervals, while writers remain stopped.
   Verify historical forecast/score/observation counts and content are preserved.
5. Observe a supervised analytical scoring cycle and the next normal cycle:
   phase durations, selected/processed counts, pending backlog, duplicate scores,
   collector priority and recovery. Version `indexed-score-inventory-v2` retains
   the legacy `ranges` field; it now counts the single indexed selection query.
   The scoring transaction still does per-point actual lookups; this patch does
   not guarantee the entire operation will meet its runtime budget on the NAS.

Old source rejects a database ahead of its expected head. For rollback, stop
writers, explicitly downgrade only to `20261008_01`, verify preserved historical
data and the old revision, then restore the matching old source. Downgrade removes
only derived inventory and triggers, uses the same bounded write locks, and is
transactional. It restores the old selector's historical-scan limitation. Never
run old source against the new schema, bypass a schema gate, or edit the version
stamp to conceal incomplete migration. Keep backup restore as the recovery route
if independent checks fail.

## Local verification

`tests/test_pending_score_inventory.py` adds synthetic invariant, interruption,
restart, concurrency, query-count, migration rollback/lock-contention and
downgrade/re-upgrade coverage. `tests/test_bounded_forecast_scoring.py` retains the
independent full-history selection oracle and existing scoring regressions. The
PostgreSQL fixture accepts only the explicitly owned local test endpoint and
database; it must never be pointed at production.

The accompanying local evidence bundle records exact commands, passed/failed/
unrun checks, source identity and reproducible performance results. It is stored
outside the repository as `energy-pending-score-fix-20261024` beside the clean
continuation clone. No model/blend artifacts, original dirty checkouts, sealed
Gate B evidence, controls, credentials or live database rows were changed.
