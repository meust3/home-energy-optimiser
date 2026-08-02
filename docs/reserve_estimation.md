# Battery reserve estimation

The reserve estimator answers one advisory question: how much battery energy should
be retained for household use before the next plausible replenishment opportunity,
and how much appears potentially tradable? It never controls equipment and never
returns execution readiness.

## Current-state source

The CLI makes its current-state source explicit. `--source live` is the default and
performs one GET-only Home Assistant collection without saving it. Only
`--save-observation` persists that snapshot. `--source history` reads SQLite in
read-only mode, prints the stored observation timestamp and age, and warns after ten
minutes. A timezone-aware `--as-of` selects the last observation at or before that
instant and excludes later load samples, enabling deterministic replay.

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
contamination rather than treated as proof of clean household demand.

Each CLI estimate stores its immutable five-minute demand projection in the local
forecast tables. After its horizon, `--score-run ID` attaches eligible measured
baseline load and reports actual energy, forecast error, percentage error where
valid, bias, and errors by tier. These local writes never contact Home Assistant or
hardware.

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
