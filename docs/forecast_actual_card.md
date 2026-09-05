# Forecast vs Actual card

The Overview card uses one bounded GET-only data contract:

```text
GET /api/v1/forecast-comparison-card?mode=live
GET /api/v1/forecast-comparison-card?mode=latest_complete
```

Both modes require the current forecast type/model/alignment/training-policy
identity and return at most one immutable run and 288 points. Live deterministically
selects the latest current-identity run, renders its full forecast, leaves future
actuals null, marks Now, and calculates metrics only from elapsed eligible matched
intervals. Latest complete chooses the most recent fully elapsed 288-point run
meeting the configured actual-coverage threshold; it does not select by performance.

The API exposes UTC timestamps, identity, optional stored lower/upper bounds,
actual eligibility and missing reason, compared-period metrics, coverage, and
intentional empty states. Signed error and bias are **actual minus forecast**.
Forecast/actual energy uses identical compared intervals, so live energy is labelled
“Compared elapsed period.” Missing and unhealthy actuals are gaps, never zeroes.

The local SVG view displays kW, Brisbane time, forecast/actual distinction, optional
uncertainty band, missing gaps, an accessible legend, keyboard point navigation,
tooltips, and the existing accessible table fallback. The mode is stored only in
browser `localStorage`. No CDN, external asset, Node pipeline, run-now action, or
write endpoint is used. A future native Home Assistant card can reuse the API; no
HACS/Lovelace custom card is included in v0.6.0.
