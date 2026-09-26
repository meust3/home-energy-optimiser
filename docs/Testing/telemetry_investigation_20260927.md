# Telemetry and overnight forecast investigation — 27 September 2026

## State and scope

Production remains App 0.6.2, schema `20260905_01`. Home Assistant is now
2026.9.3. The App UI confirmed shadow enabled, non-HOLD disabled and retention
disabled. No application deployment, migration, settings change or hardware
command was performed. Code changes are a candidate for review, not a completed
release gate. The September 19 SOC gate remains historical evidence.

## Confirmed second EV

The operator confirmed another EV during the investigated September 20 13:30–14:10
Brisbane sample window. BYD reports were fresh, plugged/online/home, SOC 91% and
zero raw vehicle battery power throughout. Thus the BYD correctly reported idle;
its state cannot describe a different car.

An audited production correction covered exactly nine slots, 13:30 through 14:10
inclusive; 13:25 and 14:15 were untouched. Session identifier:
`confirmed-other-ev-20260920-1330-1410-slots-brisbane`.

- Nine observations excluded from baseline training, without inferred AC power.
- 432 overlapping forecast scores made ineligible, with original score records
  preserved in correction metadata; four September 20 rollups rebuilt.
- Raw observation, boundary observation and immutable forecast signatures matched
  before/after. Original decisions and outcomes were not rewritten.
- Short-horizon September 20 MAE: 901.38 W → 761.80 W; actual-minus-forecast bias:
  459.38 W → 301.72 W; WAPE: 36.39% → 33.71%. Eligible slots: 229 → 220.
- Rollback and local commit/visibility rehearsals passed before the production
  transaction, with the coordinator advisory lock held. Post-commit visibility
  and all correction assertions passed independently.

Fresh PostgreSQL 17 dump/restore compared counts across all 17 tables.
Dump: 54,031,918 bytes; SHA256:
`9754dadbaab569bd0c87abfc2eb1f688f33efffa99935abcc8604212d15d4705`.
Private local artifacts are excluded from Git under
`data/soc_freshness_gate/20260927/`, including backup, restore receipt, repair
script, rehearsal and production receipts.

## PV threshold correction

The shared 15 kW plausibility threshold incorrectly assumes the same bound for
PV DC input and other power channels. GoodWe lists **20 kW maximum PV input** for
GW9.999K-EHA-G20, distinct from its 9.999 kW nominal AC output:
https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_ESA-3-10kW_Datasheet-EN.pdf

The five flagged September 25–26 PV samples were 15,196–15,884 W, alongside battery
charging around 12.3–13.6 kW. Their signed flow residuals were 0, -22, 9, -4 and
187 W. These support plausible PV measurements rather than spurious spikes;
they do not establish the installed panel nameplate capacity.

The candidate introduces a separate configurable `maximum_plausible_pv_power_w`
of 20,000 W. Other channels retain their existing 15,000 W limit. Raw readings
are unchanged. Historical health/scoring rows have not been rewritten by this
code change and require a separate audited reprocessing operation if desired.

## SOC freshness correction

The REST caching behavior remains present in Home Assistant 2026.9.3 source:
https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/core.py#L2285

An existing GET-readable entity provides a better source:
`sensor.outside_back_goodwe_inverter_timestamp`. The GoodWe library decodes
timestamp and battery SOC from the inverter runtime register response:
https://github.com/marcelblijleven/goodwe/blob/master/goodwe/et.py

At 07:30 Brisbane the runtime clock read 07:29:54 with HA update 07:29:57;
SOC was 38% with update 07:25:32 and cached report 07:25:37. Further captures at
07:35 and 07:39 confirmed the clock advanced. Offline replay of a captured payload
accepted its device age of 7.08 seconds and receipt age of 3.58 seconds.

The opt-in `goodwe_soc_timestamp_enabled` policy requires both the device clock
and HA receipt to be within the configured SOC freshness window (10 minutes by
default), with at most 60 seconds future skew. A timezone-naive inverter clock
uses the configured installation timezone; ambiguous/nonexistent local times
fail closed. Missing, malformed, stale or future clock evidence blocks SOC
readiness even if SOC recently changed. Unavailable/malformed/out-of-range SOC
cannot be rescued by a fresh clock. No sibling power is used as proof of SOC.

Each enabled observation persists the policy, entity, timestamps, ages, threshold
and reason in telemetry health JSON, without a schema change. Tests cover fresh
unchanged SOC and clock failures. The option defaults off pending controlled
deployment. Historical SOC blocks remain unchanged because clock evidence was
not persisted with them.

## Overnight database failures: confirmed scoring statement timeouts

Four failures since September 19: September 24 03:00/04:00, September 26 03:00,
and September 27 05:30 Brisbane. Each saved 288 forecast points, had no linked
reserve, and failed after 32.9–35.0 seconds. The coordinator's statement/lock
timeout is 30 seconds. Collection continued and later cycles recovered. The
PostgreSQL server had not restarted since September 13.

The current error translation incorrectly treats all SQLAlchemy OperationalError
instances as lost connectivity. PostgreSQL query cancellation (SQLSTATE 57014)
and lock-unavailable (55P03) are included in that class. The candidate separates
these transaction errors and records the coordinator stage, without exposing SQL,
parameters or exception messages in the operational audit. A real local PostgreSQL
statement timeout verified the corrected classification.

The signed-in Synology Container Manager log subsequently confirmed all four
statement timeouts: September 24 03:00:52.864 and 04:00:52.825, September 26
03:00:54.036, September 27 05:30:52.914 AEST. Matching scoring SELECT statements were found for all four windows; the latest
full statement matches `score_completed_forecast_points`' historical anti-join
and its 2,500-row limit.
Its parallel workers are terminated as a consequence of query cancellation; this
is not evidence of a database restart or a separate administrator intervention.

The candidate now materializes a narrow pending-ID batch before loading full
point/run payloads. It preserves all historical backlog, cutoff, forecast-type
and score eligibility rules, and orders equal-time points by ID. A covering index
`idx_forecast_points_scoring(id, period_end_utc, forecast_run_id)` allows the
historical point scan to avoid fetching every point payload. The index starts
with ID to support a merge anti-join against the score primary key.

On the restored database, identical 144-row results were verified. The measured
baseline was 330.291 ms with 25,291 shared blocks read; the candidate was 92.177 ms
with 3,113 shared blocks read and no temporary blocks. These local measurements
include different cache states and do not predict NAS latency or prove that
production will never time out. They demonstrate the intended index-only plan
and reduced data reads. The actual repository method then scored the same 144
pending points locally, with zero on a repeated pass (0.416 seconds combined).
No timeout increase or uncertain-transaction retry was
introduced. Keep the 30-second statement bound and verify overnight after release.

**New index-only migration `20260927_01` is required for this candidate.** Local
upgrade, downgrade and re-upgrade preserved counts in all 17 restored tables.
The baseline migration clones metadata and excludes later forecast-point indexes
so a fresh install cannot create the new index twice. A normal transactional
index build can block point writes: stop the App/coordinator during the manual
migration gate. Production still remains at `20260905_01`; no migration was run
there. This supersedes the earlier no-schema-change candidate description.

## Validation and remaining gates

- Final full suite with a fresh isolated PostgreSQL 17 database: 400 passed.
- Ruff, Black and diff whitespace checks passed.
- Index-only migration rehearsed locally; application options retain SOC opt-in.

Before release: complete review and exact-tag container validation/App discovery;
fresh backup/restore and stopped-App manual index migration; controlled HOLD-only
deployment with explicit SOC option; then 48-hour observation including overnight
scoring. Validate the new index and confirm the collector resumes. No soak or release
acceptance is claimed by this document.
