# v0.6.3 controlled deployment — 27 September 2026

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
initial acceptance. The first new scheduled forecast is due at 08:30; scheduled
cycle acceptance is deferred to the monitor rather than claimed from an old run.

Hourly read-only monitoring is active under automation
`home-energy-v0-6-3-48-hour-acceptance`. Window: 27 September 08:09 through
29 September 08:09 Australia/Brisbane. It checks collection, SOC evidence,
forecast/scoring failures and runtimes, index/revision, HOLD-only/no-command
records, PV issues and retention. It reports meaningful failures and a final
assessment, then disables itself. Local checks depend on the Codex host being
available; missing coverage must be reported. The 48-hour soak has not yet passed.
No hardware command was issued. Non-HOLD selection and retention remain disabled.

## Rollback

Stop the App before rollback. Since v0.6.2 rejects an unexpected schema head, downgrade
only the new index revision to `20260905_01` using the validated migration image,
then restore the v0.6.2 App backup and verify collection. A full database restore is
reserved for an integrity failure; the migration itself changes no application rows.
