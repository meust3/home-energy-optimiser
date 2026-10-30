# SEMS+ HCA G2 read-only discovery handover

Status: **runtime integration withheld pending reliable source evidence**.
Inspection date: 11 October 2026, Australia/Brisbane.

## Source and isolation

The feature branch `codex/sems-hca-readonly` starts at accepted `origin/main`,
`a13c27eff944a42406fd611a78cf0512f8c3110c`, also the `v0.8.1` tag.
The established `codex/` naming convention is retained. The existing programme
branch `codex/arbitrage-programme-v1` is at
`62dead9729542dd41fc8dc0ce83a7566f8efbf03` and is an ancestor of that base.
The `codex/advisory-input-compatibility-v081` branch matches the base.

Only the dedicated feature worktree is edited. The prior untracked
`tools/probe_sems_hca_cloud.py` and its tests in the preintegration checkout are
read as recovery material and preserved. Their SHA-256 hashes are recorded in
the private handover. Production version is reported by the main programme's
dated acceptance receipts; no production runtime or database inspection is
performed by this workstream.

## Findings and limitations

One authorized Home Assistant `GET /api/states` returned 699 entities. Existing
SEMS entities provide household/inverter energy totals. No identifiable HCA
charger power, connection, charging state, session-energy or charger timestamp
entities were present in that snapshot. This does not establish whether disabled
entities or a different installed integration version could expose them.

BYD exposed plugged and charging binary states and raw vehicle battery power.
The snapshot displayed plugged-idle values. Those are vehicle-cloud context,
not charger AC measurements; a dedicated source timestamp is still necessary
before treating them as fresh.

The owner-designated logged-in Australian SEMS+ portal displayed:

- A charger idle status and a separate connection label.
- A station EV power display with a station update time.
- A charger operation-monitoring power chart.
- Twenty existing natural charging-session records with displayed energy,
  start/end times and duration.

Private values are retained only in ignored local evidence. Portal timestamps
do not explicitly identify their timezone. A station update time is not proof
of charger-specific freshness, and a historical power chart or last-session
power is not a live AC sample. The connection label is not assigned a boolean
without corroborating semantics.

The owner approved at most seven diagnostic API requests. Four authentication
requests were attempted in total: three at the recovered global origin and one
at the owner-designated Australian origin. All stopped before discovery or
charger requests; the final diagnostics report no success code, token or gateway.
The cause is unresolved. No login retry loop, browser-session extraction, local
charger connection or control was used. Two additional anonymous HTTP reads
retrieved public portal client/configuration source; normal portal navigation
requests are separate from the diagnostic API budget.

**Confirmed:** telemetry is visible in the owner's portal, including historical
session energy and timestamps. **Unconfirmed:** a reliable application-readable
live AC power source, charging/connection code meanings, AC measurement domain,
per-source freshness, update cadence and retrieval authentication.

## Feature change set

- `src/energy_optimizer/sems_probe.py`: reusable, manually invoked diagnostic
  with dependency-injected transport, exact endpoint/method allowlisting,
  global/Australian authentication origins, disabled redirects, HTTPS and cloud
  host checks, a maximum seven-request budget, one session refresh and no polling.
- `tools/probe_sems_hca_cloud.py`: small CLI requiring explicit `--allow-live`;
  optional protected `--env-file` and `--region au`. The flag records an operator
  opt-in; it does not grant owner approval for future requests.
- `tests/test_sems_probe.py`: synthetic endpoint, authentication, privacy,
  budget, redirect, timestamp, missing-value and runtime-isolation coverage.
- This handover document.

The diagnostic preserves allowlisted scalar raw values. Units, status codes,
AC domain and normalized operational power remain unvalidated; values are never
forced to zero. Timing evidence stays with its source endpoint. Naive or numeric
timestamps have unknown freshness; future timestamps cannot be fresh. Missing
values remain null, and diagnostic evidence is ineligible for baseline subtraction.

There is no collector import, scheduled cloud adapter, application configuration,
schema migration, dashboard change or runtime integration. BYD accounting,
forecasts, reserves, frozen selector, arbitrage capture and controls remain
unchanged. No release, production migration, deployment or other-worktree merge
is authorized by this discovery change.

## Validation and review

See the ignored `.local/sems-hca/SEMS_HCA_HANDOVER.md` for final test counts,
commit identity, private evidence hashes, review findings and merge simulation.
The local test campaign removes inherited network/database credentials and runs
against synthetic inputs and disposable local test databases. PostgreSQL cases
requiring a separately owned test instance are explicitly skipped, not claimed
as passed. Existing dashboard tests and repository formatting/lint checks are run.

Review checks cover request paths and fixed bodies, redirect handling, raw-value
preservation, endpoint-specific timestamps, error redaction, missing fields,
selection ambiguity and absence of runtime imports. This is a local self-review;
independent maintainer approval remains part of the merge handover.

## Recommended merge sequence

1. Fetch and inspect the latest accepted main and the programme owner's actual
   current source branch. Preserve their dirty and untracked work.
2. Keep the accepted v0.8.1 advisory-input changes before this feature. Do not
   merge the older programme tip over accepted main or regress production refs.
3. Review this isolated diagnostic change. Merge it only in an owner-controlled
   integration worktree; it does not enable collection or require a migration.
4. Resolve source authentication separately. Any additional live diagnostic must
   respect the existing approval's remaining budget or obtain renewed authority.
5. During naturally occurring charging and plugged idle, validate simultaneous
   source power, explicit units, measurement point, charging/connection states,
   source timestamps and session counters against independent AC evidence.
   Keep raw session/history data separate from live samples and do not start or
   stop charging to manufacture evidence.
6. Prefer fresh existing Home Assistant sensor entities. Once reliable telemetry
   is confirmed, implement a disabled-by-default adapter using the existing bulk
   collection schedule and the smallest additive persistence/dashboard changes.
   BYD raw battery power must never populate AC power or be added to charger power.

The current upstream SEMS integration documents HCA sensors and identifies station
flow as a candidate live-power source for a station with one charger. That is
public implementation context, not verification of the installed integration or
this home's measurement domain. Its control and control-metadata paths must not
be adopted into this project.

References: [GoodWe HCA G2](https://en.goodwe.com/hca-g2),
[SEMS integration source](https://github.com/TimSoethout/goodwe-sems-home-assistant/blob/master/custom_components/sems/sems_api.py),
[SEMS integration documentation](https://github.com/TimSoethout/goodwe-sems-home-assistant#goodwe-ev-charger-hca-wallbox).
