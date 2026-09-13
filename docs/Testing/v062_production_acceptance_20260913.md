# v0.6.2 production acceptance - 2026-09-13

## Release and backup

- User explicitly authorised deployment of the forecast comparison fixes.
- Tag `v0.6.2`: `ce364a84f4f87af4c3617a4391d1012931fc3e2a`.
- PR #5 merged; main merge commit `73d90f7` has the same tree as the tag.
- 377 regression tests passed with disposable PostgreSQL 17 enabled; three Node
  behavior tests and local browser visual run-switch checks passed. Version-bump
  packaging/dashboard checks: 79 passed, six optional PostgreSQL cases skipped.
- Candidate and exact-tag amd64 container bootstrap probes passed using baked
  image files. All 68 source/packaging/migration hashes and 50 installed package
  file hashes matched the tag.
- Exact-tag image ID:
  `sha256:ee0a8e805773c16af1dbe784025da88779fa00c1a1668fba715eafbf1c297cfb`.
- Home Assistant discovery: installed 0.6.1 / latest 0.6.2, before installation.
- Fresh consistent custom-format PostgreSQL 17 backup, with source counts from
  the same exported repeatable-read snapshot; production transactions read-only.
- Backup directory: `data/backups/v0.6.2-20260913T013437Z` (ignored by git).
- Dump: `home_energy_pre_v0.6.2.dump`, 37,179,300 bytes.
- SHA256: `6b68fc56f9f74433dd9b73b33db32608676dbbbd0bfd4c5c51e0363a8f059e6c`.
- RESTORE TEST PASSED: 17 table counts matched; all 44 constraints verified,
  including three exactly recognised equivalent text-array casts; application
  readiness, orphan, duplicate-slot and no-command integrity checks passed.
- Disposable restore container removed. Detailed restore and tag-hash reports
  remain alongside the dump.
- Live schema `20260905_01` confirmed; no migration required or performed.

## Controlled installation

- Home Assistant showed Stopped before installation; read-only database audit
  found zero other client backends. No Windows collector process was found.
- Last pre-update observation: 11:35 Australia/Brisbane.
- Previous-version Home Assistant backup option remained enabled.
- Pre-update settings: forecast operations=true, reserve=true, shadow=true,
  non-HOLD=false, retention=false. No option was edited.

## Post-update acceptance

- Home Assistant shows installed/latest v0.6.2; the App was explicitly started.
- Forecast operations, reserve, shadow, non-HOLD and retention settings were
  rechecked after update and remain unchanged; Save stayed disabled.
- Ingress reports collector, PostgreSQL and Home Assistant healthy. Forecast
  Operations reports one healthy in-process coordinator, healthy reserve status,
  the last successful 11:30 forecast (288 points), and next run at 12:00.
- Production visual checks passed: the 06:00 run shows the full expected curve
  across 13 September 06:05 to 14 September 06:05; selecting 06:30 changes both
  metadata and chart axis to 06:35-06:35. No extra calculation was triggered.
- The 06:00 view at acceptance has 35 comparable observations, 25 excluded
  observations and 228 points without actuals. Its remaining large errors remain
  visible. The earlier 0.55 kW MAE referred only to the original 06:05-07:45
  screenshot interval, not the subsequently expanded comparison window.
- First post-update observation: **11:45 Australia/Brisbane**. The 11:40
  maintenance slot remains missing; no data was fabricated.
- Final read-only audit at 11:45:26: revision `20260905_01`, zero duplicate slots,
  zero no-command violations, unchanged signatures for all 375 original decisions
  and all 297 v1 outcomes; no table-count loss (mutable rollups excluded). There
  are 337 v2 outcomes, with unsupported counterfactual fields still unavailable.
- **Deployment acceptance passed.** The next existing forecast cycle is due at
  12:00; the 11:30 scheduled-cycle evidence above predates the restart. This
  dashboard patch does not change scheduling; no extra cycle was triggered.


## Rollback and safety

Rollback application is v0.6.1, retaining schema `20260905_01`. No database
restoration or downgrade is needed for a routine patch rollback. Forecast model,
collector, coordinator, scoring policy and hardware boundaries are unchanged.
Stored forecast values and genuine comparable forecast errors remain preserved.
