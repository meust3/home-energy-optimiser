# Battery reserve estimation

v0.5.1 does not change reserve arithmetic, opportunity selection, battery
assumptions, or the Tier 2 mean. The dashboard overlays forecast calibration;
tradable energy remains advisory and is shown as not calibration-certified while
status is insufficient, degraded, or poor.

Version 0.5.0 does not change this estimator. When explicitly enabled, the scheduled
coordinator evaluates it at the forecast creation timestamp using history bounded to
that timestamp and stores the complete typed result described in
`reserve_persistence.md`. This is advisory only; unavailable tradable energy remains
missing and every audit row records that no command was issued.

## Evaluation-time semantics

Live estimates use the timestamp of the freshly collected GET-only observation as
their evaluation and forecast start time. History estimates without `--as-of` are
deterministic snapshots: the selected latest observation timestamp is both the
evaluation time and the reference used to discover forecast opportunities. With
`--as-of`, the requested instant is the evaluation time and the newest observation
at or before it supplies current state; observation age is measured at that replay
instant. Historical state is therefore never combined silently with wall-clock
opportunity forecasts.

Demand slots retain their actual start and end boundaries, including partial
five-minute slots. Reserve output validates slot ordering, timezone awareness,
total duration, and integrated energy. A failed horizon makes potentially tradable
energy unavailable and blocks manual-review readiness.

Scheduled reserve uses the actual creation/evaluation timestamp, not the later
aligned operational forecast start. For example, at `10:00:20` the reserve horizon
begins at `10:00:20`; its first partial demand slot runs to `10:05:00`, while the
linked operational run begins at `10:05:00` with 288 full points. Reconciliation
metadata partitions reserve demand into this pre-alignment energy, exact shared
full intervals, and any reserve-only end boundary. The linked forecast is not added
to reserve demand, so the gap is neither omitted nor double-counted. Both forecast
inputs remain bounded to evaluation time; no future observations enter either run.

## Active replenishment opportunities

Opportunities are classified as `before_opportunity`, `inside_opportunity`, or
`waiting_for_next_opportunity`. An active window no longer ends planning at a
zero-length horizon. Planning continues through the active window to the next
future opportunity, and the report separates expected replenishment from maximum
physical capacity.

For active solar, expected generation uses the stored remaining-today
`estimate10_kwh` bound. This is conservative but coarse because no interval Solcast
series is currently persisted. If that bound is absent, solar replenishment and
sufficiency are unknown; the estimator does not invent an intraday curve. Household
demand is subtracted before applying charge efficiency, then replenishment is
capped by battery headroom and configured charge power.

For cheap grid, maximum import and usable charging capacity are reported, but
expected grid replenishment is zero because no automatic charging behaviour or
command is assumed. Combined windows allocate solar first and grid only against
remaining headroom, so the two sources cannot be double-counted. If expected
replenishment cannot establish sufficient energy for the post-window reserve,
potentially tradable energy is unavailable and manual-review readiness is blocked.

Upcoming opportunities use the same capacity audit before they can terminate the
reserve horizon. Candidates are evaluated chronologically, but the first candidate
is accepted only when its expected usable replenishment covers the demand, EV
requirement, and conservative uncertainty following that window. Cheap-grid
capacity remains theoretical because expected automatic grid charging is zero.
Insufficient or unknown candidates are retained in the audit, their expected
replenishment is applied to sequential battery accounting, and planning continues
to the next candidate. This includes a currently active but insufficient window.
If none is sufficient, there is no effective replenishment boundary; demand is
forecast to the full configured planning horizon and potentially tradable energy is
unavailable.

Opportunity solar generation and opportunity-period household load are calculated
independently of demand before the opportunity. Their difference is solar surplus,
which is then limited by charge power, charge efficiency, usable capacity, and the
projected battery headroom at the start of the opportunity. Demand before the
window can therefore change the headroom cap, but it cannot become forecast solar
or solar surplus. Physical cheap-grid capacity is reported separately and expected
grid replenishment remains zero unless a future explicit plan supplies it.

The CLI distinguishes the first candidate from the effective reserve boundary and
lists every evaluated window with maximum capacity, expected replenishment, and
sufficiency. Partial forecast slots retain their actual duration; a short horizon
crossing a five-minute bucket boundary can therefore contain two partial slots,
whose durations still sum exactly to the horizon.

Reserve history uses the shared forecast repository (`forecast_runs` and
`forecast_points`) on the configured SQLite or PostgreSQL backend. It remains
analytical and never triggers a device action.

Live mode still obtains current state with allowlisted Home Assistant GET requests.
Historical demand, prior scoring, and the newly stored forecast run all use the one
backend selected by `DATABASE_URL`.

The reserve estimator answers one advisory question: how much battery energy should
be retained for household use before the next plausible replenishment opportunity,
and how much appears potentially tradable? It never controls equipment and never
returns execution readiness.

## Current-state source

The CLI makes its current-state source explicit. `--source live` is the default and
performs one GET-only Home Assistant collection without saving it. Only
`--save-observation` persists that snapshot. `--source history` reads the configured
database without modifying observations, prints the stored observation timestamp
and age, and warns after ten minutes. A timezone-aware `--as-of` selects the last
observation at or before that instant and excludes later load samples, enabling
deterministic replay.

Every result includes the source, observation timestamp and age, SOC used, usable
capacity assumption, and calculated battery energy. This prevents a stored SOC from
being presented as live state.

## Inputs

The estimator uses either a fresh GET-only observation or an explicitly selected
stored observation, plus healthy baseline-load history. It uses battery
SOC/estimated energy, usable capacity, minimum SOC,
emergency reserve, local time, GoodWe mode/derived-flow context, normalized Solcast
energy, Amber import forecasts, optional weather health, and optional direct EV
required-energy context. EV power is removed from baseline history only where the
collector had direct EV telemetry; inferred EV power is never silently subtracted.
Version 0.4.0 vehicle-cloud SOC is contextual only and does not become required EV
energy or change the reserve algorithm. Fresh confirmed charging without charger AC
power is excluded from baseline training instead of being subtracted.

## Method

Household demand is the integrated hierarchical baseline until the next opportunity.
The hierarchy is explicitly less reliable as it moves away from an exact weekday
and five-minute match. A zero configured-fallback share does not mean the result is
fully personalised when broad historical tiers dominate.

History qualification is explicit. A row must have healthy telemetry, be marked
eligible for baseline training, contain a baseline value, and match both the target
local weekday and five-minute slot. Each target needs the configured minimum sample
count. Migrated legacy rows without a trustworthy baseline are counted as
`legacy_or_unclassified`; the estimator never reconstructs them from raw load.

Fallback defaults are configured assumptions:

- overnight, 00:00–06:00: 2.0 kW;
- morning, 06:00–09:00: 2.5 kW;
- daytime, 09:00–17:00: 2.0 kW;
- evening, 17:00–22:00: 3.0 kW;
- late evening, 22:00–00:00: 2.5 kW.

All values are configurable and none is learned from the current dataset. The
banded defaults never reduce the former 2.0 kW assumption. Flat mode remains
available. Reports decompose fallback energy by band and distinguish forecast slots
with too few matching samples from slots with no matching history.

Forecast iteration advances in UTC and converts every interval back to local time
for band and weekday/slot matching. This avoids inventing or losing elapsed energy
across daylight-saving transitions, including deployments outside Brisbane.

## Hierarchical demand tiers

Each five-minute output slot uses the first tier meeting its sample minimum:

1. Exact local weekday and five-minute slot.
2. Configured weekday/weekend category and matching 30-minute local bucket.
3. All days and matching 30-minute local bucket.
4. Recent eligible samples in the same broad time band, using the median.
5. Configured fallback-band assumption.

Tiers 2–4 are broader contextual estimates, not exact household patterns.
Diagnostics report samples, slots, energy, and variability by tier plus fallback
share. Confidence weights stronger tiers more highly and penalizes variability and
fallback-heavy horizons. Exact weekday/five-minute history normally needs at least
three weeks to acquire three eligible samples for each slot.

Training rows must predate forecast creation. Earlier observations from the same
local partial day are also excluded from every tier. This prevents Tier 3 or Tier 4
from presenting a few hours from the day being forecast as broad historical
coverage. Diagnostics count same-day and future exclusions separately.

Reprocessed rows without direct EV telemetry preserve measured household load and
record that limitation. Known EV activity without power remains excluded, and
inferred EV power is never subtracted.

The opportunity detector considers qualifying remaining-today or tomorrow Solcast
energy and Amber intervals at or below the configured cheap-import threshold. Stored
Solcast summaries lack interval timing, so solar windows use documented 07:00 and
17:30 local heuristics. If neither source identifies a window inside the configured
horizon, the estimator holds demand for the whole horizon as an overnight reserve.

The calculation is:

```text
current energy = usable capacity * SOC / 100
technical reserve = usable capacity * minimum SOC / 100
safety floor = max(technical reserve, emergency reserve)
gross reserve = safety floor + household demand + known EV demand + uncertainty
capacity-capped reserve = min(capacity, gross reserve)
unmet reserve = max(gross reserve - capacity, 0)
potentially tradable = max(current energy - recommended reserve, 0)
```

Technical and emergency reserves overlap; they are not double-counted. Known EV
required energy is conservatively included. Missing EV information contributes zero
explicit EV demand and is disclosed rather than inferred.

## Confidence

Four components are reported separately: current data availability,
household-demand forecast, replenishment-opportunity forecast, and overall reserve.
Entity presence can improve availability but cannot override weak demand history;
the overall score is capped by household-demand confidence.

Demand confidence accounts for eligible history duration, complete days and
overnights, tier shares, bucket sample counts, variability, sample age, independent
EV telemetry, and prior scored forecast error when available. Initial configurable
ceilings are conservative: fewer than two complete days is Low, fewer than seven is
at most Medium-Low, no exact-slot coverage cannot be High, and more than half Tier
3–5 cannot exceed Medium. Missing independent EV telemetry is disclosed as possible
contamination rather than treated as proof of clean household demand. Vehicle
charging state can reduce known-session contamination, but the absence of direct
charger AC power still prevents complete EV energy separation.

Each CLI estimate stores its immutable five-minute demand projection in the
configured forecast tables. After its horizon, `--score-run ID` attaches eligible
measured baseline load and reports actual energy, forecast error, percentage error
where valid, bias, and errors by tier. These analytical writes never contact Home
Assistant or hardware.

The v0.3.0 dashboard does not invoke this CLI or estimator. It reads only existing
`reserve_estimator` forecast runs. Current persistence includes projected baseline
demand plus state source, gross and capacity-capped requirements, demand confidence,
and overall confidence. It does not persist the complete `ReserveEstimate`, so SOC,
tradable energy, opportunity analysis, readiness, EV demand, and the full explanation
remain unavailable in the dashboard. Version 0.3.0 adds no migration to fill that
gap.

Low and medium confidence increase the configured demand uncertainty ratio. This is
an explainable safety margin, not a statistical guarantee.

## Limitations

- Solcast totals do not identify exact solar-surplus timing.
- The first demand model uses means and a bounded recent adjustment, not weather
  regression or machine learning.
- Battery efficiency, forecast interval prices, EV charging losses, and household
  demand correlation are not yet modelled in detail.
- Potentially tradable energy is not a recommendation to discharge or export.
- Estimates are computed from the latest stored observation; collection freshness
  remains visible through health and confidence.

## Future roadmap

A future optimiser may consume this reserve as one constraint alongside price,
solar uncertainty, degradation cost, efficiency, and manually validated inverter
limits. Any executor must remain a separate component and requires explicit safety
approval and controlled testing.
