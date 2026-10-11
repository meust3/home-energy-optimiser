# SEMS reversible session-context backfill handover

Status: prepared for main-session review; no production annotation or deployment.

## Fresh snapshot and result

The owner requested a fresh app-history snapshot. A bounded PostgreSQL transaction
used REPEATABLE READ, READ ONLY, default_transaction_read_only=on, a ten-second
statement limit and one-second lock limit. It selected twelve explicit observation
fields and existing annotation-slot identities, then rolled back. No application
stop, configuration change, database write, schema change or cloud poll occurred.

Snapshot: 11 October 2026 15:40:50 Brisbane, latest slot 15:40 Brisbane, 6,111 rows
in the UTC 20 September-12 October query range. This range differs from the older
backup preview but includes all 20 qualified session windows. The SHA-256 of the
private snapshot file is
e2691a6506fec6f188b1052ddb4ef526a2c22be1caec69ca1243dccfb7c74b4c.
The plan also stores a canonical-JSON snapshot hash; it is intentionally a
different digest from the formatted file hash.

Plan identity:
48515fbe0f74674f07b3bd636b3e3993ce2f906681375dc3baefec78de629945.

| Disposition | Distinct observations |
| --- | ---: |
| Proposed session-window exclusions | 54 |
| Existing exclusions preserved | 444 |
| Boundary context only | 19 |
| Total session-overlapping rows | 517 |

There is no claim of forecast accuracy improvement. These are conservative
household-baseline exclusions for recorded session windows, which may include
pauses. No session total is converted into instantaneous EV power.

## Boundary and precedence decisions

Use observed_at_utc, not the rounded slot timestamp, against [start,end): a sample
at the session start is included and one at its end is excluded. A partial slot
alone is insufficient. The 19 rows outside the actual observation-time window
retain their eligibility. Adjacent sessions sharing a slot cannot duplicate an
observation or subtract energy twice. Observations outside their own five-minute
slot are withheld for review.

Precedence: previous annotation history/current session ID; any direct EV power
(including zero); existing exclusion; unhealthy or missing baseline; then the
proposed session-window exclusion. Earlier annotation history is protected even
if its current session ID has since been cleared. BYD charging state/source and
raw vehicle power remain unchanged. No-match never means verified not charging.

## Implementation and reversal

- src/energy_optimizer/sems_backfill.py builds a deterministic hashed review plan
  from an explicit snapshot and qualified ledger. It does not open a database.
- tools/prepare_sems_backfill.py writes the plan to a new file only. It has no
  database apply flag, default configured connection, or network access.
- src/energy_optimizer/db/sems_context.py accepts an explicitly supplied shared
  DatabaseRepository and reviewed plan. It reuses EVSessionAnnotation and
  EVSessionAnnotationRow, so no migration or parallel persistence store is added.
- tests/test_sems_backfill.py tests SQLite and an explicitly supplied, exclusively
  owned PostgreSQL database. No production URL fallback is provided.

Only baseline_training_eligible and baseline_exclusion_reason can change. The
reason is sems_recorded_session_window_ac_power_unknown. All raw readings,
baseline power, EV charging state, EV source, session ID and vehicle fields remain
unchanged. Source context and per-row session links live in the audit note under
annotation_source=sems_session_context, not manual_annotation.

Apply and reverse each execute in one transaction. Twelve guarded fields must
match the reviewed state, and conflicting annotation history aborts the entire
operation. Updates additionally use compare-and-set predicates. PostgreSQL uses
a non-waiting maintenance advisory lock and NOWAIT observation row locks; this
operation has no collector/scheduler lock or polling thread. A retry of an applied
plan is a no-op after checking its state. Reversal verifies after-state and later
annotations before restoring the two prior values, and writes its own audit.
Reapplication after reversal requires a new snapshot/plan.

The plan retains context_known_at_utc and evidence references. Applying exclusions
changes subsequent baseline training selection; it does not rerun forecasts or
rewrite frozen selector outputs. Historical as-of studies must continue to use
their original immutable input snapshots. Existing mutable-history queries do
not automatically reconstruct pre-backfill eligibility from the audit: any future
replay consumer using this database must explicitly respect audit/knowledge time.

## Validation and review

Synthetic SQLite/PostgreSQL coverage includes exact start/end boundaries,
preservation precedence, idempotency, all-or-nothing stale-row refusal, later-audit
rollback refusal, tampered plan rejection and apply/reverse equality. The full
suite and final rehearsal receipts are recorded in the private handover.

Final full suite: 931 passed, 30 skipped in 89.56 seconds. The new backfill cases
ran on both SQLite and exclusively owned PostgreSQL 17; the 30 skips belong to
other tests requiring their separate PostgreSQL fixture configuration. Focused
suite: 112 passed. Ruff, Black and staged diff checks passed. Five changed files
are this report and the four implementation/test/CLI files listed above.

The actual 6,111-row snapshot was rehearsed using an explicitly incomplete
guard-column projection into owned test databases. Omitted application columns
were null, never fabricated; this was not a full production database restore or
forecast evaluation. The rehearsal verifies exactly 54 rows change, raw guarded
fields stay equal, repeated apply is idempotent and reversal restores the original
canonical guard hash. Retain snapshot, ledger, plan and receipts together.
Both SQLite and PostgreSQL rehearsals passed with guard SHA-256
02cca49087282fb1524eefc43653fd542755d89a67ef017d1d6f3768327dcb38
before apply and after rollback. Owned PostgreSQL containers were stopped and
removed after testing; no production dataset was modified.

This is local self-review plus automated validation. Independent review by the
main Home Energy session remains required before a production backfill. Nothing
here authorizes deployment or applying the plan to production.

## Main-session integration sequence

1. Retain accepted v0.8.1 a13c27e and current programme work. Review the isolated
   codex/sems-hca-readonly change set in the main owner's designated worktree.
2. Earlier commits are 67014ff (restricted diagnostic), fe72b60 (session staging),
   and 4741229 (timezone qualification); the private handover records this tip.
3. Review the boundary policy and the 54-row plan. Inspect private context-only
   dispositions and evidence hashes. No app options or HA beta upgrade is needed.
4. Before a separately authorized production application, obtain a recovery
   backup and recheck the plan against current rows/schema/annotation history.
   Conflicts require a new plan and review, not automatic overwrite or retries.
5. Invoke apply_context_plan with an explicit repository and aware current time
   only in that authorized maintenance step. Retain its audit and the exact plan.
   For reversal, use the same plan with reverse=True; stop if later edits conflict.
6. Validate only normal subsequent forecast cycles and baseline sample counts.
   Do not claim accuracy gains without a separately controlled evaluation.

Private artifacts live under this feature worktree's ignored .local/sems-hca:
fresh-app-history-snapshot.json, reviewed-backfill-plan.json,
session-ledger-qualified-v1.json, backfill-test-results.txt and
backfill-rehearsal-*.json. These include household data and must not be pushed.
