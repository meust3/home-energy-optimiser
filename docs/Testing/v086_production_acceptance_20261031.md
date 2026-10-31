# v0.8.6 production acceptance - 31 October 2026

Status: PASS. Installed and running; both natural cycles and the final read-only
inventory reconciliation passed. Acceptance completed at 04:31 UTC / 14:31 Brisbane.

## Baseline correction and release

Fresh discovery found v0.8.5 already running on schema `20261024_01`, corroborated
by the retained 25 October deployment receipt. The owner therefore authorized
the reconciled update as v0.8.6. Earlier v0.8.5 preparation documents are annotated
as historical; their proposed production migration was not performed again.

- [PR #22](https://github.com/meust3/home-energy-optimiser/pull/22) merged after
  exact-head CI and the current-data recovery rehearsal passed.
- Reviewed head: `5d490cff006cdd6838e2590267650abbc0836117`.
- Published merge/tag target: `33d36cb08e6fe2e2cd3092ca02eca55e62bc4201`.
  Its Git tree exactly matches the reviewed head.
- [v0.8.6 release](https://github.com/meust3/home-energy-optimiser/releases/tag/v0.8.6)
  is immutable; v0.8.5 was not moved.
- [CI](https://github.com/meust3/home-energy-optimiser/actions/runs/41165985144):
  1,428 Python tests passed, 35 skipped; 11 JavaScript tests passed; lint/format,
  amd64 build, image bootstrap and 93 installed Python source hashes passed.
- Local candidate verified all 97 Python/static files, dependency consistency,
  SDK absence and offline image-baked bootstrap behavior. Candidate image ID:
  `sha256:f44feeb85010565cbd03f0884105dca59b43b0be8b2ba2614772331014fa78b4`.
  This is the local validation image, not an independently measured installed image.

## Fresh backup and isolated current-data recovery

A consistent read-only exported snapshot was taken at
`2026-10-31T03:46:59.159777+00:00` while collection continued. The backup completed
at 03:50:41 UTC: 202,330,126 bytes, SHA-256
`75da96e717ed6a1318422f4e0035b937fff3ad1a9fad74ca90e205fd6e8b4149`.

The isolated PostgreSQL 17 restore matched all 22 snapshot table counts, including
the schema-version and derived-inventory tables. It contained 25,462 observations,
1,104,239 forecast points, 1,097,039 scores and 7,200 pending points. Complete
pending reconciliation found zero differences. Ordered historical row digests,
schema definitions and sequence values were captured from the restored copy and
remained unchanged through candidate and recovery App startup/readiness probes.
This is snapshot-count/restore verification and App-preservation evidence; it is
not a separate full-content digest comparison against the live production source.

The isolated fixture matched production's `energy_app` ownership while remaining
non-superuser. Both v0.8.6 and the retained v0.8.5 recovery image passed startup and
full database readiness on the same schema. Candidate scoring processed 144 eligible
points in 0.102 seconds; pending rows fell from 7,200 to 7,056 with exact inventory
reconciliation. The recovery App passed again after those analytical writes.
All network access was confined to loopback. No production schema or grant changed.
The owned restore container was removed; dumps and image recovery artifacts remain.

The first backup attempt stopped at its five-second unbounded-count limit. Its
failure receipt was retained and the successful attempt used the established
bounded keyset counter. Migration limits were not relaxed or exercised on production.

## Production permissions and cutover

Read-only preflight verified PostgreSQL 17.10, revision `20261024_01`, and
`energy_app` ownership of application tables and the queue. The role is not a
superuser, role creator or database creator. Queue DML and trigger-function access,
eight enabled triggers, seven invoker functions, valid due index and cascade FK
passed. Complete live inventory checks before and after both natural cycles found
zero mismatches and zero duplicate score IDs. No grants were necessary.

Home Assistant's supported update path installed v0.8.6 with the rollback-backup
option kept enabled. It created encrypted App backup `44f4f917`, named
`Home Energy Optimiser 0.8.5`, 69.79 MB, at 13:56 Brisbane. The backup was confirmed
in the UI; its encrypted payload was not restored onto production as a test.

Update requested: 03:56:29 UTC. Logs show clean shutdown at 03:57:11, startup
validation passed at 03:57:24, then the strictly read-only collector started.
The approximately 13-second interruption fell between collection slots. All 55
protected options were byte-for-byte identical before and after installation.
Startup, Ingress Overview, Data Quality and Forecast Operations rendered correctly.
Automatic updates stayed off; boot and watchdog remained on. Existing accepted
capture/context/vehicle settings were preserved. No AI/Jev/SEMS live execution,
hardware authority, operational non-HOLD selection or retention was enabled.

## Natural-cycle acceptance

| Scheduled UTC | Finished UTC | Full cycle | Forecast points | Scored | Scoring |
|---|---|---:|---:|---:|---:|
| 04:00 | 04:00:32.769650 | 12.768 s | 288 | 288 | 0.671 s |
| 04:30 | 04:30:36.149352 | 16.148 s | 288 | 288 | 0.767 s |

Each cycle persisted exactly one linked reserve and one completed HOLD decision,
with non-HOLD selection false and no command issued. Indexed selection completed
in one range per cycle with no failure/SQLSTATE. All seven five-minute observation
slots from 04:00 through 04:30 were present; 04:00 followed the pre-update 03:55 slot.
The final 04:31:45 UTC inventory snapshot found zero mismatches and duplicate score
IDs, with 7,200 pending rows. The cycle acceptance snapshot showed zero due rows.
No manual calculation or scheduling change was used to obtain acceptance. The
bounded observer exited successfully after the second cycle.

## Preservation and limits

Seven previously preserved uncommitted Jev/SEMS file hashes still match, and the
two existing untracked assessment reports remain uncommitted. Private evidence is
retained under `.local/v085-live-20261031/`, including protected options, backup,
rehearsal receipts, recovery images, startup logs and acceptance snapshots.

NAS drives report healthy; the existing volume-capacity warning remains, with
about 1.3 TB free. The NUC reported 196 GB free. No storage remediation was attempted.
Independent installed source/dependency/image-byte attestation remains unverified
through the supported UI route; local/CI hashes must not be represented as installed
runtime hashes. Limited live acceptance does not establish a long-term soak,
forecast accuracy, realized savings or hardware readiness.

Automatic approval review initially rejected merging while the rehearsal was still
running. The merge was retried only after the rehearsal passed and then succeeded.
