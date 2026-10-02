# v0.6.4 production acceptance - 3 October 2026

The Home Assistant OS amd64 App was updated from v0.6.3 to v0.6.4
on 3 October 2026 (Australia/Brisbane). This is initial deployment acceptance,
not extended soak evidence or validation of automatic battery export.

## Frozen release and isolated validation

- Release tag v0.6.4: `10d79a809ae26ba32c739a3c233f68ca4a817f61`.
- Main merge: `949a063c2a79dcd4324303976da0bfbad56e7ea7`; both trees
  are `16802ea953dab754ec037ce2cfeb71b785a5ab36`.
- [PR #8](https://github.com/meust3/home-energy-optimiser/pull/8) excludes
  the separate optional AI integration PR #7.
- [CI validation](https://github.com/meust3/home-energy-optimiser/actions/runs/37068339843):
  430 tests passed against isolated PostgreSQL 17; Ruff, Black and whitespace
  checks passed. The amd64 image passed the image-baked App bootstrap checks.
- After Docker recovery, a local exact-tag amd64 build matched all 49 installed
  Python source hashes from CI and passed the bootstrap checks again: protected
  options, UID/GID 10001, trusted Ingress simulation, denial of spoofed requests,
  watchdog/health and SIGTERM. Original options remained unchanged and output
  contained no secrets.
- Local Docker inspect image identity:
  `sha256:58cb51e6d1431bdfb764258800eecf6090bc485d915e6bdd9ca2a525da7db205`.
  This is the observed local image identity, not a NUC image checksum. The 49-file
  comparison verifies CI/local builds; no independent NUC source-hash comparison
  was performed.

## Backup and restore gate

A fresh read-only repeatable-read snapshot was exported while collection continued.
The dump, table counts, constraints and indexes came from that same snapshot.
No production migration or data repair was performed. Revision remained
`20260927_01`.

- Snapshot started 07:51:36 Brisbane; isolated restore completed 07:53:33.
- Backup size: 61,777,839 bytes.
- SHA256: `2dfe9345f116b97bc87184b8037dd1f61b9818053eecc82a43f3b1ccae915afb`.
- Isolated PostgreSQL 17.10 restore completed with `pg_restore --exit-on-error`.
- All 17 table counts, 44 constraints, 45 indexes and the Alembic revision matched.
  Only the same three previously validated status-array cast deparsing equivalents
  were accepted; no other definition differences were allowed.
- The disposable local restore container and its volumes were removed. The dump
  and JSON receipts remain in ignored local storage:
  `data/exports/v064-deployment-20261003/`.

## Controlled App update and runtime checks

The authenticated Home Assistant update dialog showed installed v0.6.3 and latest
v0.6.4. Its previous-version backup option was enabled when Update was submitted.
The App info page then showed v0.6.4 Running, auto-update off, watchdog and start
on boot enabled. No Home Assistant service or device command was called.

The previous process stopped cleanly at 07:55:07. The replacement started at
07:55:10; startup validation passed at 07:55:11 and the read-only collector and
Ingress dashboard started successfully. PostgreSQL schema validation required no
migration. Existing options and the HOLD-only/retention-disabled configuration
were preserved.

The first new observation at 08:00 persisted 48 half-hour intervals for today and
48 for tomorrow, including P10/P50/P90 power and UTC period bounds. Interval issues
were empty. Telemetry and overall health were 100, with fresh GoodWe runtime frame
evidence. The already-written 07:55 observation was retained without rewriting.
There were no missing five-minute slots from 07:30 through 08:00 and no invalid
database indexes. Authenticated Ingress showed collector, PostgreSQL and Home
Assistant healthy, with the forced-HOLD/no-command explanation.

The 08:00 scheduled cycle completed successfully in 19.74 seconds. Bounded
read-only verification at 08:01:15 linked forecast run 2486 (288 persisted points)
to reserve run 2476 and its shadow decision. The reserve recorded
`command_issued=false`; selection was HOLD, `non_hold_selection_enabled=false`
and `no_command_issued=true`. There were zero retention maintenance runs since
the pre-update check. Schema revision and index validity remained unchanged.

## Limits

Timed solar capture and the explicit offline diagnostic are deployed. Production
still selects HOLD; non-HOLD selection and retention remain disabled, and no
executor, command endpoint or scheduled export planner was introduced. The
reserve estimator is unchanged. This receipt does not establish economic savings,
manual control readiness, automatic export readiness or resolution of unrelated
historical scoring failures. Historical observations were not backfilled.
