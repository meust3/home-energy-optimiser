# Forecast-context final runtime validation — 5 October 2026

This receipt supersedes the original report's *pending runtime checks*, not its
historical implementation checkpoint. The original report, inventory and private
mapping retain their reviewed byte hashes. Everything below used synthetic inputs
and exclusively owned disposable environments. No production connection or live
HA configuration, migration, activation, inference, hardware call or deployment
occurred. The index is empty; nothing was staged, committed, pushed or tagged.

| Gate | Verdict | Executed evidence | Remaining prerequisite |
|---|---|---|---|
| App runtime | **PASS** | Python 3.12.11; 558 Python tests, zero failures/skips; 7 JavaScript tests; image source/assets identity; image-files bootstrap/Ingress/health/SIGTERM; actual App startup and optional failure/recovery matrix | Freeze an approved immutable release source/image and version after release-lineage inspection; rerun affected checks if source/runtime/dependencies change. Production installation remains separately approved. |
| HA cache draft | **PASS** | Actual HA Core 2026.9.3 schema, script, templates, entities and restore-state machinery; 13 synthetic cases; all 13 HA-output-to-Energy-parser cases; public/private structural equivalence | Approved backed-up merge, real configuration validation and explicit reload/restart; verify generated cache ID and normal scheduled receipts. Live setup/coverage remains unverified. |
| Migration/recovery | **PASS** | SQLite and PostgreSQL 17.10 migration value/hash preservation, physical round-trips, actual prior-App rejection on new head, compatible disabled recovery, prior startup after downgrade and synthetic backup restore | Verified production identity, fresh external backup plus isolated restore, prepared compatible replacement, and explicit cutover approval. Direct prior-code rollback on the new head is unsupported. |

## Candidate identity and narrow corrections

Worktree: `codex/forecast-context-collection`, based on v0.6.5,
`a93532b9ad5d604ee69a8215bb8ee9b5482e7af4`. The candidate remains uncommitted.
The working-source image did **not** download the pinned old release. It copied
the candidate source and installed that package using the canonical bootstrap,
App UID/GID 10001 and Python 3.12.11 base. Text transport normalization retained LF
for the bootstrap and the selected source/assets. Packaging adapters and manifests
are retained privately for reproduction.

The App-source manifest contains 96 files. Its SHA-256 is
`1fd463c099eb04fb027cce4aa9df2e2ee721e87d21a68c948058472079023957`.
All 96 baked working files and 55 installed package/assets files matched. The
actual prior image matched 92 working files and 52 installed files against the
v0.6.5 tree, accounting explicitly for Windows archive line endings and LF shell
bootstrap handling. Neither image contained private exports, options, `.env`,
credentials, Git metadata, documentation or tests.

Recorded local image identities, before cleanup:

| Image | SHA-256 |
|---|---|
| Working App | `1b332f40d70900244106464f5666d5f5961a074883a7d5611528dd9dfd4d5d15` |
| Prior App | `42bff8462623f179570f73e60ebd3f80f1e8bb4c00b52ff21310e42059f70c8e` |
| Test image | `63fe4751d25b38d21bed2d3e47f853485152e473813ef756f29c8c6e901491f2` |
| HA Core 2026.9.3 | `d8922685169707fd91e8b9729902d975f06157d005e422874d201e0261dda196` |

No Python implementation correction was needed. Two demonstrated cache-draft
defects were corrected identically in the public and private drafts:

1. HA's `availability: false` discarded cached attributes on failure. Removing
   that template lets the explicit `unavailable` state retain the successful
   timestamp and payload. Energy still rejects an unavailable/restored cache.
2. The draft admitted oversized/nested values as ready. Cache success now requires
   small scalar fields (strings at most 64 characters, no booleans/nested objects)
   and an ASCII-serialized payload at most 65,536 bytes. Failed validation retains
   the last successful payload. Existing Energy parser bounds remain unchanged.

Final public cache-draft SHA-256:
`abcd0843ceb483e8beca1d4b55ec687842c37fc588ae3e768725ff8c757478d3`.
The original private draft was preserved separately before correction.

The private arithmetic erratum records **16.7 percentage points**, correcting
the original 7.7-point prose. Original readings remain unchanged. This is not a
synchronous calibration comparison or evidence of sensor failure; no offsets or
averaging were applied. The private mapping still has five zones, twenty
quantities, and effective date `2099-01-01T00:00:00Z`. Default App options remain
`context_collection_enabled: false` and an empty mapping.

## Executed runtime receipts

Private receipts and reproducible synthetic harnesses are under
`data/exports/context-runtime-validation/`; they are Git-ignored. Names below
identify actual logs, not inherited test claims.

| Receipt | Actual result |
|---|---|
| `python312-tests-final.txt` | **558 passed in 88.04 seconds; zero skipped**. PostgreSQL-gated tests used the owned PostgreSQL 17.10 instance. |
| `javascript-tests.txt`, `javascript-syntax.txt` | **7 passed, zero failures/skips**; JavaScript syntax check passed. Node 18.20.4. |
| `ruff.txt`, `black.txt`, `python-syntax.txt` | Ruff passed; Black: 119 files unchanged; image Python compilation passed. Final Git whitespace check passed. |
| `app-runtime-dependency-check.txt`, `dependency-check.txt` | Runtime and validation dependency checks passed. Exact freezes retained separately. |
| `image-identity.txt`, `prior-image-identity.txt` | Baked and installed source/assets matched their manifests. |
| `image-bootstrap.txt` | Existing `--use-image-files` harness passed old/explicit options, root-owned source options, privilege drop, secret exclusion, Ingress assets/API, watchdog health, direct-access rejection and SIGTERM. |
| `app-matrix.json`, `one-get-validation.txt` | 14 actual startup cases: 12 successful starts and 2 expected prior-App schema rejections. Enabled fixture proved one cached state GET per cycle plus the separate startup state GET. |
| `context-timing.json` | 13 measured calls; core commits survived refused connection, 500 ms table locks and injected cleanup exceptions. A subsequent normal call succeeded. |
| `ha-runtime-final.txt`, `ha-runtime-output.json`, `cache-bridge-final.txt` | Matching HA runtime and Energy bridge each passed 13 cases. |
| `context_migration-migration.json`, `context_legacy-migration.json` | Migration preserved all 16 legacy table hashes. Nonempty fixtures included observations, forecast runs/points and reserve runs. Both new tables accepted synthetic records. |
| `postgres-downgrade-recovery.json`, `postgres-upgrade-recovery.json`, `backup-restore.json` | Physical round-trip preserved legacy values/hashes and explicitly lost new history. Actual prior App started after physical downgrade and after restoring an old-head synthetic backup. |
| `final-preservation.json`, `cleanup-receipt.json` | Preservation passed; zero owned runtime resources remain. |

The full Python command was `python -m pytest -q`, inside the owned test image
with `TEST_POSTGRES_URL` and `F1_F3_OWNED_TEST_DATABASE` pointing exclusively to
the disposable database. The image-files command was
`python tools/test_home_assistant_app_container.py --image codex-context-runtime:working --use-image-files`.
Other commands were `ruff check .`, `black --check .`, `python -m pip check`,
`node --check src/energy_optimizer/dashboard_static/app.js`,
`node --test tests/*.test.cjs`, and image `python -m compileall -q src tools migrations`.
Owned-runtime scripts `ha_validation.py`, `cache_bridge.py`, `owned_fixture.py`,
`app_matrix.py`, `context_timing.py`, `backup_validation.py` and the image manifest
checkers preserve the fixture configuration and executable assertions.

Validation dependencies were installed only in the owned images. Key recorded
versions: pytest 9.1.1, Ruff 0.16.10, Black 26.10.0, PyYAML 6.0.3; App Pydantic
2.13.5, SQLAlchemy 2.1.3, Alembic 1.20.0, psycopg 3.3.6 and requests 2.34.2.
The declarations are not a locked release environment. These receipts attest
these resolved versions, not every future dependency resolution.

Earlier attempts are not passes: the initial test snapshot omitted documentation
and `.gitignore` (556 passed, two missing-fixture failures); a bare `pytest` launcher
missed the root import path; early disposable drivers used the default DB port,
an incorrect diagnostic key and future receipt times. The first prior-image
bootstrap retained CRLF from Windows archive conversion and exited 127. Corrected
fixtures and LF handling were rerun; none required an application-code change.

The actual App matrix covered old-shaped options, disabled/empty mapping, enabled
synthetic context, future mapping, missing cache with valid indoor/current weather,
malformed optional readings/cache, and database failure after a durable core write.
Revoking new-table INSERT yielded an optional failure with core health still
healthy; restoring the grant allowed context persistence in the **same process**.
All fixture HA requests were GETs; no private entity IDs or fixture secrets appeared
in public health/errors. Fixtures accelerated collection to one second while the
unchanged production default remains 300 seconds and five-minute slot alignment.

Normal optional persistence measured 20.30–29.99 ms; refused connections
3.44–3.64 ms; selected table-lock failures 511.35–515.42 ms; cleanup-error calls
20.16–20.53 ms; the post-failure normal call 22.26 ms. Cleanup exceptions were
injected *after real disposal*. The connection test exercised refusal, not a
black-holed network/DNS delay. These are measured fixtures and per-operation
timeouts, **not an absolute wall-clock or production cadence guarantee**. No retry,
second collector, worker or scheduling architecture was introduced.

The synthetic twenty-quantity batch serialized to 16,352 bytes, excluding its
separate weather snapshot. The test database's eight context rows occupied
98,304 bytes including indexes/TOAST; two snapshots occupied 49,152 bytes.
This small allocated footprint is not a production growth measurement. The
original storage estimate remains an estimate; retention remains disabled.

## HA cache validation boundary

The official HA Core **2026.9.3** image ran its actual configuration schema,
trigger coordinator, action script, entity templates and persistent restore-state
machinery. Its interpreter was Python **3.14.6**, distinct from the App's 3.12.11.
Only the base helpers and template/sensor machinery were initialized, with a
mocked `weather.get_forecasts` service and fictional state. No real weather
integration/provider client, HTTP server, live configuration or network was used.
Hourly triggers were invoked deterministically through the registered coordinator
callback rather than waiting an hour; real schema/trigger registration and HA
stop/restart restoration were exercised.

The 13 cases were fresh startup, successful response, empty response, service
exception, unavailable source, success before restart, restored startup, success
after restart, entry/horizon bounds, oversized scalar, nested value, serialized
byte overflow and boolean numeric input. Startup performed no weather action.
Empty/error/unavailable cases retained the last successful timestamp/array while
remaining unavailable. Actual restart restored those attributes and stayed
unavailable until an hourly success.

The bounded fixture received 110 entries and retained 93 from the first 96 input
rows after past/outside-48-hour exclusions; received count and truncation stayed
typed. Native target strings and Celsius/mm source units survived. Booleans,
nulls, integers, arrays and dictionaries were actual types. Unsupported optional
forecast fields and current-only dew point stayed absent; private/unrelated
metadata was excluded. Issue/model/version remained null. Temperature stayed a
native target point; precipitation/probability periods remained unspecified.

All 13 **HA-generated** entity responses were consumed by the unchanged Energy
parser. Only the four valid successes/bounded responses produced snapshots;
failed/restored caches could not make retained old data newly usable. Maximum
normalized snapshot size was 74,239 bytes, below the separate 256 KiB normalized
limit. HA's 64 KiB bound applies to its forecast-array serialization, not the
expanded normalized snapshot. Public/private draft structures matched after
substituting only the source entity variable. Live entity generation, provider
coverage and normal receipt timing remain separately unverified.

## Executed recovery matrix

The DDL adds only `context_observations` and `weather_context_snapshots`, from
`20260927_01` to `20261005_01`. Context slots reference core observations; the
context-recording and weather source/as-of indexes were inspected. Runtime needs
schema USAGE and SELECT/INSERT on the new tables; their hashed primary keys require
no new sequence privilege. The tested runtime role had DML grants and no database
CREATE permission. Migration remains a separately privileged/manual operation.

| Code / schema / options | Executed result | Recovery implication |
|---|---|---|
| Candidate / new head / disabled | Starts, core collection healthy | **Preferred tested recovery:** retain compatible code, disable only context. Both new histories remained present. |
| Candidate / new head / enabled synthetic mapping | Starts and writes optional records | Compatible local candidate; no production activation authorized. |
| Actual v0.6.5 / new head / old-shaped options | Exits 1 before HA startup validation | Direct code rollback retaining the new head **does not work**. |
| Actual v0.6.5 / new head / new-shaped disabled options | Same revision rejection | Ignored optional fields do not solve schema incompatibility. |
| Actual v0.6.5 / physically downgraded old head | Starts, core collection healthy | Tested destructive recovery: **all context/weather history is dropped**. Legacy values/hashes survived the downgrade. |
| Candidate / physically re-upgraded head / disabled | Starts | Legacy history survives; dropped context/weather history is not recreated. |
| Actual v0.6.5 / restored old-head synthetic backup | Starts | Tested pg_dump/pg_restore route. At the pre-start cutoff, restored observation values/hash exactly matched the backup; one deliberately later synthetic observation was absent. Normal startup can subsequently add legitimate rows. |

The original report's claim that application rollback can retain additive tables
is therefore corrected by this receipt. No stamping, weakened schema check,
modified old binary or automatic drop was used. A future forward-recovery build
is not attested here. Physical downgrade and backup restoration each require
separate explicit production approval; restoration loses **all writes after its
cutoff**, including legitimate analytical/observation history, not only context.

## Preservation and cleanup

All 15 paired-simulator file byte hashes and Git status still match the retained
pre-task evidence. Fourteen protected forecasting/training/calibration/reserve/
shadow/EV modules match both their initial bytes and release-base text. The
original concurrent checkout remains at `af3d0077bb5c03201ecb050ce953bc3dc6c99d76`;
no writes were performed there. Review-document hashes and the inert private
mapping are unchanged. The original report was not overwritten.

Cleanup completed at `2026-10-05T03:57:50.879408+00:00`: three remaining owned
containers, their anonymous PostgreSQL volume, the internal fixture network and
all four task images were removed and absence verified. Disposable host SQLite,
HA configuration/restore directories and synthetic backup were removed after
recording hashes. Successful App containers and the bootstrap harness's resources
had already been removed. Shared services, base images and builder cache were
untouched. Synthetic source snapshots, harnesses and receipts remain as evidence.

## Later approvals — do not execute this runbook yet

1. **HA cache setup:** back up relevant configuration; merge only this template
   block into the existing configuration. Use the existing Met.no integration.
   Obtain approval for real HA validation and the precise supported reload/restart.
   Verify generated cache ID, source units, restoration/failure behavior and normal
   minute-17 receipts. Do not force updates, replace all templates or install a
   provider. Update the private cache ID only if actual generation differs.
2. **Release/publication:** inspect current release lineage and automatic-update
   state before discovery/update; confirm automatic updates off. Approve the
   immutable source, correct version, privacy review and publication separately.
   Replace the old pinned source reference with the approved artifact. Prepare
   and verify the compatible image **before production migration**; record digest
   and exact dependency versions. Source/runtime changes invalidate affected
   receipt reuse. No next version number is assumed here.
3. **Production migration/update:** verify current installed source and external
   PostgreSQL revision/identity; take a fresh backup and isolated restore. Compare
   at a common backup cutoff or approved quiescent snapshot, not moving live counts.
   Approve the precise migration and App replacement. Stop only necessary writers,
   migrate once, then immediately install/start the prepared compatible App with
   context disabled. Grant the narrowly required new-table privileges. Verify
   readiness/core health. Keep the compatible disabled build as the first recovery
   choice; old v0.6.5 cannot start on the new head. Any physical downgrade or backup
   restoration needs its own approval and explicit history-loss acceptance.
4. **Collection activation:** approve the private mapping version, real UTC
   effective-from time and verified cache ID. Enable only optional context
   collection; keep forecast, shadow selection, retention and all other flags
   unchanged. Do not backdate. Indoor/current-weather collection may be approved
   independently while hourly setup remains pending; that is not complete hourly
   forecast-snapshot acceptance.
5. **Bounded read-only acceptance:** observe several normal five-minute slots,
   source labels/nulls/units/timestamps/freshness limits, immutable retry references,
   unchanged core cadence/health and forecast identities/output logic. Observe
   ordinary scheduled receipts and content deduplication; distinguish repeated
   content or rolling horizon changes from an actual provider-issued version.
   Never force provider changes to manufacture two versions. Measure real rows,
   bytes and optional latency later; unavailable sensors and missing outdoor air
   measurement remain honest limitations, not substitutes or activation blockers.

Stopping point: the reviewed local candidate and corrected inactive drafts.
These three PASS verdicts are local release-gate results, not live setup,
production migration, deployment or forecast-quality acceptance.
