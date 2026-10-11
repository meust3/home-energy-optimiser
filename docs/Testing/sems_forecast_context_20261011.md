# SEMS charging context for the existing app

## Result

Historical SEMS sessions can enrich the app's existing observations after source
time and interval semantics are qualified. They cannot reconstruct five-minute
charger AC power. No production dataset, model or training flag was changed.

The app's DatabaseRepository.healthy_load_samples already selects healthy rows
with baseline_training_eligible=true and a non-null baseline_house_consumption_w.
The existing audited, reversible EV annotation path excludes known session rows
without direct power, while retaining measured household consumption. This is
the natural integration point for qualified historical charging context. A session
total must not be spread uniformly over samples or added to household consumption.
Session boundaries also may contain pauses; 'within session' is not proof of
continuous charging. Excluding entire sessions would be a conservative training
policy needing a before/after sample-count and forecast evaluation.

## Current HA source validation

Fresh GET /api/states at 2026-10-11T05:02:02Z returned 699 entities. GoodWe SEMS API
reports installed 11.11.0 and latest offered 11.12.0. Matching sensor names and
attribute keys show SEMS household/inverter totals but no identifiable HCA
telemetry. Disabled entities/entity registry were not inspected, so absence is
limited to the current state inventory. The unrelated phone charger-type sensor
is not EV evidence.

Upstream 11.13.0-beta.1 explicitly adds HCA support: status, plug state, station-flow
charging power, live factors, counters and last-session sensors. Its release notes
say a complete charging session has not been tested and fixtures are hand-built.
It also includes command entities. No integration update or command was executed.
Being authenticated to SEMS in HA does not itself expose every SEMS data source.

Tagged beta source inspection confirms:

- Live power sensor uses watts and station-flow charging_power, distinct from
  last-session average/max power in kW.
- Plug sensor emits connected/disconnected; status is an enum.
- Last-session values are replaced by the next session, intentionally without
  an accumulating energy state class. They do not backfill historical sessions.
- Status attributes carry last_session_start/end; these are not a live charger
  telemetry timestamp. Successful HA refresh alone cannot prove source freshness.

The app's legacy EV mapping is insufficient to enable these unvalidated sensors:
collector.py reads direct power as a bare number without source-unit conversion
or charger-specific freshness qualification. parse_bool does not understand the
beta status/plug enums. When vehicle telemetry is enabled, charging activity comes
from that vehicle path; charger/vehicle precedence needs an explicit adapter.
Do not simply point EV_CHARGING_POWER_ENTITY_ID at a guessed entity.

## Prepared evidence and next implementation

sems_history.py and prepare_sems_history.py prepare a private single-charger
session ledger from the already captured portal evidence. They preserve raw
energy/time strings, reject invalid/conflicting records, deduplicate exact
records and leave power/UTC time unqualified. An optional CSV preview returns
separate point-in-session context with an explicitly confirmed source UTC offset;
it never writes observations or authorizes training changes. No-match means unknown.
This is staging support for an eventual app backfill, not a separate forecast model.
The 20 real records were staged locally; no observation join was run because source
timezone remains unconfirmed. Personal evidence stays ignored, not in fixtures.

Recommended app work, in order:

1. Establish portal timezone and interval meaning from source evidence; retain
   source identity, acquisition time and incomplete history coverage explicitly.
2. Add an idempotent session-evidence table through shared persistence, with raw
   source values and revision/conflict handling. Preview its join against an owned
   copy of app history. Do not stamp imported records as manual confirmations.
3. Review affected rows, existing annotations/direct power and boundary slots;
   use reversible audits for approved training exclusions. Preserve raw house
   power, keep unknown EV power null, and compare training coverage/model accuracy.
   Retrospective session acquisition must not leak into historical as-of replay.
4. Validate a released HA HCA source, or separately review a beta evaluation, with
   naturally occurring charge and plugged-idle evidence. Confirm single-charger
   station-flow scope, units, timestamp and stale/unavailable behavior.
5. Add a disabled-by-default read-only adapter to the existing collection pass,
   separating charger AC, vehicle DC and session summaries. Persist source-specific
   freshness; retain BYD context without adding its battery power to charger AC.
   Show qualified EV context in the existing dashboard, without another poller.

Existing cloud diagnostic authorization is unchanged: four of seven requests were
used earlier, all failing at authentication. No additional cloud diagnostic was
made for this follow-up. Production application changes and beta installation
remain unperformed; the original no-deployment boundary still applies.

## Validation

Focused suite: 82 passed (session preparation, restricted probe, EV annotation
and baseline handling), including 9 new session-evidence cases. Ruff passed and
Black formatted the three new Python files. Tests used synthetic evidence with
network/database credentials removed. No production database was connected.

References:

- [HCA beta release](https://github.com/TimSoethout/goodwe-sems-home-assistant/releases/tag/11.13.0-beta.1)
- [Tagged HCA entities](https://github.com/TimSoethout/goodwe-sems-home-assistant/blob/11.13.0-beta.1/custom_components/sems/ev_charger.py)

Changed files for this follow-up: src/energy_optimizer/sems_history.py,
tools/prepare_sems_history.py, tests/test_sems_history.py and this report. Forecast
algorithms, collector, repository, schema, controls and dashboard are unchanged.
