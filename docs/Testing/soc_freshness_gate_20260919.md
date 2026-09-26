# SOC freshness release gate — 19 September 2026

## Decision

**Gate not passed. No application or production changes made.** Preserve the
existing SOC block and HOLD-only selection. Do not classify the 32 historical
blocks as false positives or substitute REST `last_reported` without further
transport evidence. No new release tag, container, migration or deployment is
warranted by this investigation.

## Verified evidence

- Repository started clean at `6a879c8`, following the confirmed EV-session repair.
- Home Assistant `/api/config` reported version `2026.9.0`.
- Read-only GETs at 10:57:56, 10:58:35 and 11:00:45 Brisbane found SOC at 44%,
  `last_updated=2026-09-19T00:55:32.683517+00:00` and
  `last_reported=2026-09-19T00:55:58.463984+00:00` throughout.
- PV, battery power and household power advanced between the latter two reads.
  This demonstrates that the REST SOC report timestamp did not advance alongside
  those readings; it does not independently prove the SOC sensor was refreshed.
- The application model currently discards `last_reported`. SOC freshness uses
  `last_updated`, with a 60-minute unchanged grace, then produces
  `source_update_stale`; shadow decisioning blocks on that classification.

Home Assistant documents `last_reported` as tracking unchanged state reports:
https://developers.home-assistant.io/blog/2024/03/20/state_reported_timestamp/

However, the installed-version source caches `State._as_dict` (including the
serialized report time), while the unchanged-state path updates `last_reported`
and its numeric cache without invalidating the serialized dictionary. This is a
source-supported explanation for the observed REST behavior, not a direct trace
of the running server's internal state:
https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/core.py#L1835
https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/core.py#L2285

## Historical replay and checks

A bounded, read-only PostgreSQL query exported the 32 decisions containing
`battery_soc_stale` since 13 September 11:45 Brisbane, joined to their original
observation slots. Replay ran locally against the current `_current_state_blockers`
function with a 10-minute observation freshness policy.

- 32/32 retained `battery_soc_stale`.
- 0/32 had persisted `last_reported` evidence supporting reclassification.
- This was a replay of the current-state blocker, not a full economic decision
  replay or a counterfactual proof that the battery telemetry was fresh.
- No observations, decisions, outcomes or scores were changed.
- Targeted collector-health and shadow-decision tests: **66 passed, 1 skipped**.
  The PostgreSQL-dependent test was not exercised in this targeted run; this is
  not full regression or container acceptance.

Local evidence remains in ignored `data/soc_freshness_gate/`:
`live-report-evidence.json`, `live-report-evidence-2.json`,
`blocked-observations.json` and `replay-results.json`.

## Required next evidence

1. Establish a trustworthy SOC report signal through the permitted GET transport:
   verify an upstream fix for REST timestamp caching, or separately design and
   review a narrowly scoped integration-provided freshness signal. A sibling
   power reading alone must not silently certify SOC freshness.
2. Demonstrate unchanged SOC with advancing report evidence, stopped reporting,
   unavailable/malformed SOC, and invalid/future timestamps. Persist the evidence
   used for the classification so subsequent decisions can be audited.
3. Implement the narrow policy correction only after that evidence exists. Keep
   historical blocks unchanged where evidence is absent, and test fail-closed
   behavior alongside genuine unchanged fresh SOC.
4. Then run full regression, exact-tag container validation and App discovery;
   perform fresh backup/restore validation and schema comparison before the
   controlled HOLD-only update. A schema comparison is not migration authority.
5. Start a new 48-hour observation period after acceptance. This investigation
   does not start or complete that soak, and does not enable non-HOLD selection.
