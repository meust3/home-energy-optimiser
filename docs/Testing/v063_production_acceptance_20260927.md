# v0.6.3 controlled deployment - 27 September 2026

Historical evidence only. The follow-up below was reconciled on 31 October 2026
from dated local receipts, without accessing production or changing integrations.
It describes September 2026, not current runtime state. See the
[claim verification record](v063_acceptance_evidence_review_20261031.md).

## Release and pre-deployment evidence

- User explicitly authorized exact-tag validation, fresh backup/restore, controlled
  index migration, deployment and 48-hour monitoring.
- Release tag `v0.6.3`: `6fd1c1d12ab10ad967aa4a3d86d6b21775f5190e`; PR #6 merged as
  `70ee0ab42260ec5377d8db3c043669b5982a3aaf`. A subsequent documentation-only commit
  in the merged branch clarifies the current migration gate in the App overview.
  Runtime sources and Dockerfile remain those of the immutable tag.
- Exact-tag amd64 image: `sha256:5e311f85579945db216f4681204de705b9b7d6797de55a789d28a295d889d686`.
- All 69 source/packaging/migration file hashes and all 50
  installed package hashes matched the tag. Image-baked bootstrap, protected options,
  UID/GID 10001, Ingress, watchdog health, secret-free output and SIGTERM checks passed.
  Explicit SOC/PV option propagation and expected migration head also passed.
- Candidate suite: 400 passed on a fresh isolated PostgreSQL 17 database; release
  packaging tests: 57 passed. Ruff, Black and whitespace checks passed before release.
- Home Assistant discovery showed installed 0.6.2 and offered 0.6.3, with the new
  changelog and migration warning, before any production migration or installation.

## Backup, restore and migration

The App was confirmed stopped; an independent read-only PostgreSQL audit found zero
other client connections and revision `20260905_01`.

- Fresh custom-format PostgreSQL backup: 54,069,361 bytes.
- SHA-256: `9515d81e41b1815bd073a6a0418ef62500b7f7f4d587e15267d289d0fbd69d87`.
- Local evidence and dump: ignored `data/soc_freshness_gate/v063-deployment/`.
- Isolated PostgreSQL 17.10 restore matched all 17 table counts, 44 constraints and
  44 indexes. Three status CHECK constraints deparsed with equivalent array casts;
  comparison explicitly verified only these cast/parenthesis differences.
- Exact release image rehearsed migration `20260905_01 -> 20260927_01` on the restore.
- Exact release image applied the same migration to production in 25.072 seconds;
  all 17 table counts unchanged. `idx_forecast_points_scoring` is valid, covering
  `(id, period_end_utc, forecast_run_id)`. No telemetry or forecast rows were rewritten.
- Home Assistant update was started with its previous-version backup option enabled.

## Acceptance

Home Assistant confirmed v0.6.3 running. Startup at 08:08:54 Brisbane passed
PostgreSQL revision, readiness and GET-only entity access checks. Ingress loaded.
Configuration was saved with `goodwe_soc_timestamp_enabled=true`, PV limit 20000 W,
shadow enabled, non-HOLD disabled and retention disabled.

The first new observation at 08:10 was healthy with SOC 33%. Its persisted
`goodwe_runtime_timestamp_v1` evidence reported `runtime_frame_fresh`, device age
6.001028 seconds and receipt age 2.372911 seconds. The maintenance window omitted
the 08:05 slot; it is not backfilled or hidden. There were no post-start gaps at
initial acceptance.

The check around 09:10 Brisbane on 27 September recorded two successful scheduled
cycles, at 08:30 and 09:00, with 288 forecast points and non-null forecast/reserve
run IDs. Durations were 36.36 and 12.66 seconds respectively. It recorded 13
observations with fresh GoodWe runtime-clock evidence, zero collection gaps,
no recorded operation failures or PV plausibility flags, and no retention runs.
The two shadow decisions were HOLD with `no_command_issued=true` and non-HOLD
selection false. Revision `20260927_01` and scoring-index validity were confirmed.

The check around 21:19 recorded 158 observations and 26 successful cycles with
HOLD-only/no-command decisions. Of those observations, 156 had fresh runtime-clock
evidence. The separate `soc-exceptions-20260927T1119.json` receipt records the two
exceptions at 20:25 and 20:35: all five core GoodWe entities and the inverter clock
were unavailable, SOC was null, telemetry health was false, and the recorded
reason was `soc_unavailable_or_invalid`. Collection had no missing slots. These
are unavailable-input rejections, not a stale-clock test at a scheduled decision
boundary; neither exception was at a half-hour decision slot.

The planned monitoring window for `home-energy-v0-6-3-48-hour-acceptance` was
27 September 08:08:58.856579 through 29 September 08:08:58.856579 Brisbane
(approximately 08:09 to 08:09). Monitoring coverage and its limits are assessed
below. No current automation state is asserted from these historical receipts.

## Rollback

Stop the App before rollback. Since v0.6.2 rejects an unexpected schema head, downgrade
only the new index revision to `20260905_01` using the validated migration image,
then restore the v0.6.2 App backup and verify collection. A full database restore is
reserved for an integrity failure; the migration itself changes no application rows.

## Qualified historical assessment - 30 September 2026

The retained `final-window-audit.json` records 576 observations in the fixed
48-hour window, from 27 September 08:10 through 29 September 08:05 Brisbane,
and 96 successful operations with runtimes from 11.83 to 55.39 seconds. Its
`actual_points` summary is `[96, 288, 288]`, consistent with 288 points per run.
The audit records 96 completed HOLD decisions with `no_command_issued=true` and
non-HOLD selection false, 574 fresh SOC records, two unavailable/invalid SOC
records, no failures and no retention runs. The later monitor's broader interval
reports zero collection gaps and PV plausibility flags, with the revision and
scoring index still valid. These are retained aggregate results, not a new
database audit; the final audit query definitions were not available for this
review, so an independent per-run points/reserve verification is not claimed.

**Continuous monitoring coverage did not pass.** Recomputing the intervals between
all 46 entries in `monitor-history.jsonl` gives a largest gap of 40.3844 hours:
29 September 02:41:23 to 30 September 19:04:27 Brisbane. The final 5 hours
27 minutes 36 seconds of the planned window had no intervening recorded check
and were assessed retrospectively. The receipts do not establish why checks
stopped. This must not be described as uninterrupted 48-hour monitoring.

**The historical evidence did not close the scoring-timeout issue.** Outside the
fixed window, the 29 September 19:30 cycle failed with
`DatabaseQueryCanceledError during forecast operation; phase=score_forecast_points`.
Its recorded total duration was 47.24 seconds. Later cycles succeeded, including
30 September 19:00. These receipts establish recurrence after the index migration,
not its cause or current resolution; they do not establish NAS contention or
quantify the index's performance benefit.

No live stale-clock decision-boundary rejection is demonstrated by the reviewed
receipts. The unavailable-input examples must not substitute for that evidence.
The proposed statement that the automation was disabled afterward was not
verified from the reviewed local receipts and is not adopted here.

Overall acceptance remains qualified: retained in-window operating results were
positive, monitoring coverage was incomplete, and a later cancellation prevented
closing the timeout issue at that date. This historical reconciliation authorizes
no migration, backfill, restart, deployment, hardware command or live integration.
