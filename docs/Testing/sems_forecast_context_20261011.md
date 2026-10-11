# SEMS charging context for the existing app

## Validation update: 11 October 2026

This update supersedes the timezone-unconfirmed finding below. The SEMS+
Station Information page explicitly displays Australia/Brisbane (UTC+10:00).
A separate, bounded HA recorder GET for BYD charging state covers the latest
four SEMS sessions on 9-11 October. All eight boundaries align after Brisbane
conversion: HA start reports lag by 108.7-208.9 seconds and end reports by
108.1-250.1 seconds. This corroborates the session timezone; vehicle-cloud
reporting latency is not used to adjust the charger timestamps.

All 20 captured session intervals and displayed energies were reread unchanged.
Every displayed duration equals elapsed start/end time rounded up to a minute.
The total remains 220.54 displayed kWh. These are qualified session-window
timestamps, not proof of uninterrupted charging or independently metered AC
energy. The 12 September-11 October filter showed 20 records; completeness and
pagination have not been established. Missing records do not mean no charging.

The qualified private ledger preserves the original raw values, explicit
Australia/Brisbane timezone, UTC conversions, evidence references and the later
qualification time. It leaves ev_power_w null and training eligibility disabled.
The reusable qualification function rejects missing evidence references,
backdated qualification, sessions ending after acquisition, ambiguous/nonexistent
DST timestamps and overlapping single-charger sessions. No retrospective
qualification is made available before its context_known_at_utc timestamp.
Any eventual as-of consumer must enforce that timestamp; this helper does not
alter runtime queries or make the ledger a forecasting input.

### Preview against actual app history

Used the programme's existing stopped v0.8.1 backup, SHA-256
f3be9207faaa550ea224c1ca8de814e518cbdb24ec7559284829c4e16292ace2,
snapshot 2026-10-10T23:54:59Z. Verified its hash and extracted only observations
using the already available PostgreSQL 17 image's pg_restore, with network
disabled, a read-only filesystem and read-only backup mount. No database server
was started, no production connection was opened, and no source backup changed.
The temporary full-table SQL extraction was removed after a minimal private
review CSV was produced.

Within the review horizon, 6,163 existing observation rows were inspected:

- 478 distinct five-minute slots overlap the 20 session windows.
- 479 session/slot links include one slot shared by two adjacent sessions.
- 39 links intersect session boundaries; 459 links have the actual observation
  timestamp inside the session. Interval overlap must not be confused with
  proof that an instantaneous boundary sample was charging.
- 405 overlapping slots already carry known_ev_session_without_ac_power exclusion.
- 73 are currently effective forecast-training rows without direct EV power.
  These are candidates for a conservative session-window exclusion policy,
  not automatically approved exclusions or proven forecast improvement.
- No matched row has direct EV power or an existing session annotation ID.
- The snapshot ends at 09:50 Brisbane on 11 October, so only 29 slots of that
  morning's completed session are present. A final import must recheck fresh data.

No backfill or training mutation was applied. The proposed next change is an
idempotent source-evidence import and reviewed reversible annotation, preserving
source provenance rather than labelling SEMS records as confirmed manual input.
Boundary policy, fresh row counts and forecast evaluation remain integration work.

### HA beta read-only audit

Inspected tagged 11.13.0-beta.1 source. The normal charger read method makes four
GETs (telemetry, telecounting, mode metadata, last charge) and a conditional detail
POST. It does not call a charging command. The installation nevertheless forwards
sensor, switch, select and number platforms and registers charger controls; no
read-only configuration option was found in its config flow. Reading sensors is
read-only consumption, but installing this beta is not a sensors-only installation.
Prefer a separately scoped Visitor account for any later isolated evaluation;
actual Visitor-account endpoint behavior still needs testing.

An offline injected-transport audit exercised the two extracted read/parser methods:

1. Normal reads called only the four GET endpoints and detail POST.
2. Factor values and units survived parsing.
3. Factor timestamp fields did not survive parsing: source freshness is lost.
4. A telemetry permission failure marked that source unavailable while retaining
   the independent last-session result.
5. A mode-metadata permission failure skipped dependent detail retrieval.

The audit mechanically parenthesized Python 3.14 exception syntax for the local
Python audit host; it is not a full unmodified-beta HA runtime test. The private
script, tagged source hash and receipt are retained for reproducibility. There
were zero live cloud diagnostic requests in this validation turn.

Other important limits: station-flow pEvChar is assigned only with one charger,
converted from kW to W and made absolute, which loses the original sign. The app
must preserve upstream/raw-domain qualification before baseline subtraction.
Sensor availability reflects failed fetches, not necessarily source data age.
Last-session counters replace previous sessions and cannot retrieve the historical
record list. Upstream itself reports incomplete full-session validation.

Production HA was not upgraded. The safest eventual route is a validated
sensor-only adapter consuming the existing HA collection pass, with explicit
source timestamps, enum parsing, units and charger/BYD precedence. No independent
poller or copied control code is needed.

### Validation receipts and changed files

Private receipts in .local/sems-hca: portal-timezone-validation.json,
portal-session-revalidation.json, ha-charging-history-crosscheck.json,
session-validation-report.json, session-ledger-qualified-v1.json,
app-backfill-preview.json, app-backfill-slot-context.json and
beta-offline-read-audit.json. Personal data is not committed.

This validation changes only sems_history.py, prepare_sems_history.py,
test_sems_history.py and this report. Focused suite: 90 passed, including eight
new qualification cases. Ruff and Black pass. Runtime forecast algorithms,
collector, schema, controls and production data remain unchanged.

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
