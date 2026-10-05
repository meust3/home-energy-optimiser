# Forecast context collection — reviewed local candidate

Prepared 5 October 2026. This is an unstaged, uncommitted collection candidate. It has not been deployed or activated, and does not establish improved forecast accuracy.

## Scope and lineage

Dedicated managed worktree: branch `codex/forecast-context-collection`, based on reviewed tag `v0.6.5`, commit `a93532b9ad5d604ee69a8215bb8ee9b5482e7af4`. The paired simulator was not copied, merged or modified. Its initial status and SHA-256 manifest are retained privately for the final preservation check.

Discovery used the existing authenticated HA browser session, relevant cached state views, and device/integration registries. It did not use controls, services, force polling, raw-state exports, production SQL, subscriptions or new credentials. HA reported Core 2026.9.3. Production Energy schema/configuration was not re-audited; the source's previous migration head is 20260927_01.

## Source mapping

Real entity IDs, room assignments and individual observed readings are in Git-ignored `data/exports/context-collection/source_inventory.private.md`. The proposed private mapping is beside it. Public examples use fictional IDs.

| Initial set | Discovery evidence | Collection treatment |
|---|---|---|
| Four available indoor zones | ZHA registry identifies eWeLink SNZB-02P devices; separate temperature/humidity entities | Separate sensor measurements, no room averaging |
| Fifth indoor zone | Two unavailable ZHA readings; manufacturer/model unknown | Preserve missing values and reasons; do not claim a SONOFF model |
| One Sensibo skyv2 controller | Ambient temperature/humidity, off state, requested setpoint; same registered zone as one ZHA device | Keep duplicate sources individually, with duplicate_group |
| Climate mode/setpoint | Requested controller values | commanded_assumed, not compressor activity |
| HVAC activity | hvac_action absent in observed state and installed-version Sensibo implementation | Null; integration_reported if supplied later |
| HVAC electricity | No verified electrical meter on inspected Sensibo device | No inferred power, energy or runtime |
| BroadLink ambient sensors | Available; registry room conflicts with entity names | Excluded pending physical placement confirmation |
| Misleading appliance-labelled device | Registry identifies a temperature/humidity sensor; unavailable | Excluded; no claim of appliance power |
| Met.no current conditions | Available weather temperature, dew point, humidity, cloud coverage and condition | Distinct remote_modelled source |
| Physical outdoor air sensor | User confirms none installed | Explicit absent status; no car, battery or inverter substitution |
| Hourly weather cache | No suitable cache found by bounded relevant searches; weather state has no forecast array | Pending HA setup; proposed cache ID is not a discovered entity |

The initial mapping has five indoor zones and 20 quantities. Registry placement does not prove exact physical positioning. The co-located sources disagree on humidity; no calibration offset or preference was inferred. Reporting cadence and actual physical measurement time were not established through the inspected UI. Actual API last_reported presence remains a live acceptance check.

The private mapping is deliberately effective from 2099-01-01. Before approved activation, choose a real UTC effective-from instant and mapping version. This prevents a review draft from pretending historical collection occurred.

## Weather decision

**Reuse the installed Met.no integration.** Its current fields and registered hourly capability satisfy the small collection objective. It needs no API key and normally polls every 55–65 minutes; this cadence is documented, not locally measured. Retain attribution. [HA Met.no documentation](https://www.home-assistant.io/integrations/met/)

| Dimension | Met.no — recommended | Open-Meteo — comparison only |
|---|---|---|
| Installed locally | Yes, core met integration | Not listed in installed integrations |
| Current relevant fields | Temperature, humidity, dew point, cloud coverage observed | Documentation describes temperature/humidity/cloud fields; not verified here |
| Hourly temperature | Registered capability; installed source implements it | Documented hourly support |
| Optional hourly fields | Installed source maps condition, precipitation, humidity/cloud where provided; dew point not in its forecast mapping | Do not assume all upstream variables are exposed in HA |
| Horizon | Installed coordinator requests a native range through 49 entries; actual live coverage unverified | Live horizon unverified |
| Units | Current °C / mm observed; draft preserves weather entity unit metadata | Live units unverified |
| Refresh | Documented 55–65 minutes | Documented 30 minutes |
| Issue/model metadata | No such fields exposed in inspected HA Met response transformation | Not locally verified |
| Account/terms | No API key; provider attribution/fair-use terms apply | No account/key; documented free non-commercial/open-source use |

Open-Meteo would add setup without resolving a verified deficiency in the existing source. No integration was installed and no provider accuracy comparison was performed. [HA Open-Meteo documentation](https://www.home-assistant.io/integrations/open_meteo/)

Installed-version behavior was checked against official [Met weather.py](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/met/weather.py), [coordinator.py](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/met/coordinator.py), [forecast field mapping](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/met/const.py), and [Sensibo climate.py](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/sensibo/climate.py). Hourly response values were not requested live.

## Implementation contract

- New configuration: `context_collection_enabled=false` and empty `context_mapping_json`. CLI environment equivalents: `CONTEXT_COLLECTION_ENABLED`, `CONTEXT_MAPPING_JSON`. Old-shaped App options remain valid.
- Maximum 16 KiB mapping, 32 quantities and six indoor zones. Explicit source/attribute/evidence/units; version and content hash accompany each batch.
- Collector reads the existing cached-state snapshot once. Optional malformed entities are isolated, while required core validation remains unchanged.
- Core energy observation commits first. Context parsing and persistence use a separate bounded transaction on the same configured database URL; no fallback or automatic migration.
- PostgreSQL context connections request connect_timeout=1 and statement/lock timeout=500 ms; libpq has its own effective connection-timeout behavior. SQLite context busy timeout is 500 ms. These are operation limits, not a universal hard wall-clock guarantee over DNS/network failures. No context retry loop or second thread is introduced.
- Parser/open/save/cleanup failures produce a non-secret diagnostic containing the exception class. They cannot undo a committed core observation. Forecast coordination remains the existing thread.
- Current records preserve source identity, quantity, raw scalar, canonical value/unit, conversion, availability/reason, mapping/parser identity, collector slot and actual Energy receipt.
- HA changed/updated/reported times are preserved separately from optional explicit measurement time. Unchanged values do not fail merely because last_changed is old. Missing measurement proof remains unknown freshness. Receipt does not freshen physical measurements. [HA state object semantics](https://www.home-assistant.io/docs/configuration/state_object/)
- Known numeric conversions are explicit; zero is valid. Nonfinite/malformed/implausible values become null with reasons, never clamped or silently replaced.
- Two additive tables: `context_observations` linked to the existing observation slot; `weather_context_snapshots` storing immutable received versions. Migration `20261005_01` follows `20260927_01`.
- One context batch per slot/mapping is immutable on retry. Weather arrays are stored separately and referenced by ID, not repeated in every batch.
- Repeated content with the same known issue/version does not create independent forecasts. New issue/version metadata is retained even if values agree. Consecutive A→B→A revisions are retained, including a revision with an unchanged cache timestamp.
- Each snapshot preserves provider/integration/cache identity, source units and allowed raw values, native target timestamps, nullable issue/model/version, cache success, first Energy receipt, semantic/payload hashes, and parser version.
- Native temperature is a target-time point; rainfall/probability interval bounds stay unspecified where HA supplies no period definition. Optional absent fields remain absent. There is no hourly-to-five-minute resampling.
- Bound: next 48 hours, at most 96 entries; raw allowed-field JSON <=64 KiB and normalized snapshot <=256 KiB. Oversized/malformed cache payloads are rejected with diagnostics; outside-window points are explicitly counted. HA-side truncation and original entry counts are retained.
- Cache availability, restoration, attempt time, HA times, age, coverage, truncation and unknown upstream freshness remain explicit. Retrieval is not issuance. Cache outage never deletes already archived versions.
- Future-only as-of helpers require both Energy receipt and recorded-at <= origin. Provider issue/cache times cannot backdate Energy knowledge. Recorded-at is the application recording timestamp, not an independently measured database commit timestamp. No current forecast consumes these helpers.
- Existing /health gains an optional diagnostic: disabled/pending/operating/failure, mapped count/evidence types, valid/invalid/missing counts, known/unknown freshness, last useful receipt, last snapshot/coverage and estimated storage. Optional failures do not reduce the collector's core health status.

No demand model, training eligibility, EV accounting, calibration, reserve, forecast identity/output, shadow selection, outcome scoring, retention or simulator implementation was changed. The legacy generic weather fields were not repurposed.

## Prepared HA cache — not applied

Public fictional draft: `docs/examples/met_no_hourly_cache.yaml`. Private source-specific draft: `data/exports/context-collection/met_no_hourly_cache.private.yaml`.

After separate approval, HA may perform `weather.get_forecasts` hourly at minute 17 for the selected weather entity. This is HA's weather-retrieval action, outside Energy's GET-only client. It reads the installed Met integration's cached coordinator data; the draft does not call update_entity or request provider force refresh. [Documented template/forecast pattern](https://www.home-assistant.io/integrations/template/)

The draft retains only required native fields, next-48-hour targets, units/source identity, entry counts and explicit truncation. Provider issue/model/version remain null. Failed/empty/unavailable retrieval keeps the previous success timestamp and payload but marks the cache unavailable. Startup marks it restored/unavailable and waits for the next scheduled successful retrieval; it does not force a startup poll.

The YAML parses locally. HA template schema and Jinja runtime validation remain pending: neither Home Assistant nor Jinja is installed in the local test interpreter, and no configuration was submitted to live HA. Entity ID generation, startup restoration, action-error handling, exposed hourly fields and live coverage require the separately approved setup acceptance. An old payload retained in HA is not treated as a new usable Energy snapshot while the cache entity is unavailable.

Indoor/current-weather collection can proceed after an approved schema/release/activation even if hourly cache setup remains pending. Missing optional cache data does not make baseline rows ineligible.

## Local validation and review

Final run: **558 passed, zero failed, zero skipped in 73.46 seconds**, using Python 3.13.14 and owned PostgreSQL 17. The private reviewed-tests.txt log contains the actual result. This includes 62 new context tests and the 496 existing tests. Ruff passed; Black reported 119 files unchanged; git diff --check passed.

Earlier development runs exposed fixture mistakes (required HA timestamps, SQL type-object comparisons, Alembic disabling test loggers, and a shared fixture import). These were corrected and rerun. The final result is not a claim that those earlier runs passed, nor is it Python 3.12 image-baked or production acceptance.

Witnesses cover source/role separation, duplicate groups, conversions/zero/nonfinite/missing values, unchanged readings, measurement age, unavailable/restored cache, revisions/dedup/reversions, issue metadata, native semantics/size/horizon/privacy, causal receipt/recording filters, retry immutability, core-priority/error isolation, actual forecast output equality before/after context persistence, old App options, JSON/schema round trips and legacy-row preservation. SQLite and owned disposable PostgreSQL 17 are exercised. No test uses production household readings or an HA network connection.

Static checks: Ruff, Black, git diff --check. Both cache YAML drafts and both JSON mappings parse locally. Public files contain fictional IDs; private files are Git-ignored. The staging area is empty.

Preservation review: all 15 paired-simulator file SHA-256 hashes and its Git status match the pre-task manifest. Fourteen protected calculation/forecast/EV/shadow modules match the release-base Git blobs exactly. Existing forecast/shadow migration tests changed only their expected latest schema head. The original concurrent-work checkout remains on af3d007 and was not edited.

Owned PostgreSQL reported 17.10. The labelled test container, its anonymous data volume, and the temporary test credential file were removed after validation. Test logs, preservation evidence and the private deployment drafts remain in the ignored export directory.

Storage illustration: 20-source private-map-shaped synthetic records serialize to approximately 17.5 kB each, about 5.03 MB/day at 288 slots (about 1.84 GB/year before indexes/WAL/compression). This is a JSON estimate, not measured PostgreSQL disk usage. Separate snapshots at the maximum 256 KiB and 24 distinct versions/day add up to 6 MiB/day; real versions are likely smaller and repeated reads deduplicate. Retention remains unchanged and disabled.

## Precise steps still requiring approval

1. Resolve the BroadLink physical placement only if including it later; leave it excluded otherwise. Investigate the unavailable fifth-zone sensor under a separate operational task; this candidate records the missing readings honestly.
2. Approve the HA cache setup separately. Verify the private weather entity, merge the template block into the existing HA configuration without replacing other templates, run HA configuration/template validation, then separately authorize the appropriate reload/restart. Confirm the generated cache entity ID and update the private mapping if it differs. Do not enable another weather provider.
3. Observe normal scheduled cache updates using read-only views: units/allowed fields, target times/counts, shortened coverage/truncation, unavailable/empty behavior and startup restoration. Confirm cache receipt never becomes a fabricated provider issue time. The draft's runtime remains unverified until this passes.
4. Approve a release freeze/version update and commit/push workflow separately. Current candidate is uncommitted; the existing Dockerfile downloads its pinned remote APP_SOURCE_REF and would not include these local edits. Do not build/deploy the unchanged v0.6.5 reference as if it contained this extension.
5. Preflight production identity/current revision and take a fresh verified PostgreSQL backup with an isolated restore. Review the additive DDL, then obtain explicit production migration approval for 20261005_01. Existing startup readiness intentionally requires the new head; it will not migrate automatically, even when collection is disabled.
6. Build the approved immutable amd64 source/image, run the repository's release checks and image-baked App bootstrap/source-identity checks, and preserve the previous image/options/backup for rollback. Deployment/restart still need explicit approval. An application rollback can retain the additive tables; do not run the destructive downgrade merely to revert code.
7. Initially deploy with context disabled. Approve private options separately, choose the real mapping effective-from UTC/version, provide its JSON through context_mapping_json, then enable context_collection_enabled. Keep existing HOLD-only/non-HOLD-disabled, retention and other operational options unchanged.
8. After activation, perform bounded read-only acceptance over several normal collection slots and at least two naturally received weather versions. Confirm source roles/nulls/units/ages, one collector and normal cadence, immutable version references, no array duplication, and causal origin filters. Confirm core timestamps/health and existing forecast inputs/outputs/identity remain unaffected. Validate provider-failure isolation when naturally observed, or in an owned fixture; do not induce a production outage.
9. Measure actual rows/bytes and optional operation latency. Record the live hourly coverage and timestamp limitations. Do not claim improved accuracy, a complete horizon, or source physical freshness without evidence.

Stopping point: reviewed local candidate and drafts only. No staging, commit, push, tag, HA setup, production migration/write, deployment, hardware command, paid service or inference was performed.

