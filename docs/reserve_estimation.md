# Battery reserve estimation

The reserve estimator answers one advisory question: how much battery energy should
be retained for household use before the next plausible replenishment opportunity,
and how much appears potentially tradable? It never controls equipment and never
returns execution readiness.

## Inputs

The estimator reads the latest local SQLite observation and healthy baseline-load
history. It uses battery SOC/estimated energy, usable capacity, minimum SOC,
emergency reserve, local time, GoodWe mode/derived-flow context, normalized Solcast
energy, Amber import forecasts, optional weather health, and optional direct EV
required-energy context. EV power is removed from baseline history only where the
collector had direct EV telemetry; inferred EV power is never silently subtracted.

## Method

Household demand is the integrated weekday/five-minute baseline until the next
opportunity. Slots without the configured sample minimum use the conservative load
fallback. A bounded recent-history ratio adjusts historical slots without machine
learning.

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
recommended reserve = min(capacity,
    safety floor + household demand + known EV demand + uncertainty)
potentially tradable = max(current energy - recommended reserve, 0)
```

Technical and emergency reserves overlap; they are not double-counted. Known EV
required energy is conservatively included. Missing EV information contributes zero
explicit EV demand and is disclosed rather than inferred.

## Confidence

The 0–100 score weights telemetry health (30), usable history (25), solar health
(15), price health (15), weather availability (5), confirmed sign conventions (5),
and opportunity confidence (5). High confidence additionally requires a high-history
forecast: at least 21 distinct days and at least 80% historical coverage across the
forecast window. Missing price, solar, or weather reduces confidence but does not
prevent a conservative estimate. Unhealthy telemetry or missing battery energy
prevents manual-review readiness.

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
