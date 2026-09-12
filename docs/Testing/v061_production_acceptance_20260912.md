# v0.6.1 production acceptance - 2026-09-12

The operator authorised the controlled update after release publication. This
record distinguishes local artifact validation from direct production checks.

## Release and backup gates

- Release tag: `v0.6.1`, commit `93721e8012b1f318a30d939ae8eec104f4453b1c`.
- Tagged linux/amd64 image, installed-source hashes and container probe passed
  before publication; see the GitHub release and prior outcome review record.
- Home Assistant offered installed 0.6.0 / latest 0.6.1 before installation.
- Production PostgreSQL major version **17**, live revision **20260905_01**,
  queried with transaction read-only enforced. No migration was run.
- Fresh custom-format dump used the same exported repeatable-read snapshot as
  its source table counts; the collector continued during the dump.
- Backup: `data/backups/v0.6.1-20260912T051357Z/home_energy_pre_v0.6.1.dump`.
- Bytes: **36,072,531**.
- SHA256: `d0b2d2a2af7ab4a937e79367b64ab11619f06ab6315c5c25a3f9424a3f0e02fa`.
- **RESTORE TEST PASSED** in disposable local PostgreSQL 17. All **17** table
  counts matched; **44** constraints verified; application readiness passed;
  duplicate slots, orphan checks and no-command violations were all zero.
- The first local restore attempt failed and was retried locally. Three restored
  status constraints had equivalent array/element text-cast formatting; their
  restricted expressions and allowed/invalid/NULL truth tables were checked.
  No production schema or data was changed to make the restore pass.
- The disposable restore container was removed; the dump, checksum and detailed
  `restore-test.json` remain in the ignored backup directory above.

## Installation

- The App was stopped before installation. Home Assistant showed **Stopped**;
  the database had **zero other client backends**, and no Windows collector
  process was found.
- Home Assistant's previous-version backup option remained enabled.
- v0.6.1 was installed and then explicitly started. Home Assistant showed
  **Current version: 0.6.1 / Running**.
- Preserved options: forecasting=true, reserve snapshots=true, shadow=true,
  non-HOLD=false, retention=false. No option was edited.
- First post-update observation: **15:25 Australia/Brisbane**. The previous
  observation was 15:15; the 15:20 maintenance slot remains missing, not fabricated.
- Ingress loaded successfully and reported collector, database, Home Assistant,
  reserve scheduler and the single coordinator healthy.

## Scheduled-cycle acceptance

**PASSED** at 15:32 Australia/Brisbane after the existing 15:30 coordinator
cycle. No extra calculation was triggered.

- Forecast **1494** contains **288** five-minute points, alignment `full_5m_v1`.
- Reserve **1489** and completed shadow decision **336** are linked to that
  forecast. Selection is **HOLD**, with `no_command_issued=true`.
- The scorer appended **24** `battery-shadow-outcome-v2` outcomes for matured
  historical decisions. This does not imply the new 15:30 decision has matured.
- All unsupported counterfactual/simulated comparison fields are NULL and
  counterfactual confidence is unavailable on those v2 rows.
- All **297** v1 outcomes and all **335** original decisions have unchanged
  full-row signatures. Table counts did not decrease (mutable rollups excluded).
- Duplicate observation slots and no-command violations are **zero**.
- Collection advanced to **15:30**. Ingress shows healthy collector, PostgreSQL
  and Home Assistant, the new reserve, the new HOLD recommendation, and the
  new forecast with `full_5m_v1` alignment.
- The live revision remains `20260905_01`; the acceptance database transactions
  were read-only.

Detailed audit snapshots are retained as `pre-update.json`, `post-update.json`
and `scheduled-cycle.json` alongside the backup. This is deployment acceptance,
not evidence of economic benefit or validated counterfactual decision quality.

## Safety and rollback

No hardware command, Home Assistant energy-control service, or migration was
issued. Existing decisions and v1 outcomes are retained. Non-HOLD remains disabled
because a validated counterfactual model has not been implemented. A rollback to
v0.6.0 would retain revision `20260905_01` and preserve v2 audit rows; it would not
require the pre-shadow downgrade. The release tag is unchanged.
