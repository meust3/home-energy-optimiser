# Morning solar export diagnostic

This explicit offline diagnostic evaluates selling stored battery energy during
morning Amber feed-in price windows, followed by solar recharge. It is separate
from `battery-shadow-policy-v1`, the coordinator and the dashboard. Nothing
schedules it, deploys it, changes non-HOLD selection or controls hardware.

## Data and collector candidate

The candidate collector preserves the allowlisted `detailedForecast` half-hourly
Solcast interval series inside existing `solcast_*_kwh_json` summary fields.
Each interval retains UTC start/end and P10/P50/P90 **average power in kW**.
The daily summary remains energy in kWh; multiplying interval power by duration
gives interval energy. No migration is needed, and old rows remain immutable.

The source format is documented by
[the Home Assistant Solcast integration](https://github.com/BJReplay/ha-solcast-solar#sensors).
Only its combined `detailedForecast` is accepted, never hourly or per-site arrays.
Payloads are bounded to 96 intervals per summary. Missing P10, malformed timestamps,
negative power, reversed uncertainty bands, gaps and overlaps remain visible.
Optional interval problems do not reduce core telemetry health. Added interval JSON
increases observation storage; retention remains disabled. This collector change
has not been deployed to the NUC.

## Model and recommendation

Inputs are an immutable decision, its observation, its linked operational load
forecast and reserve audit, and the configuration/calibration snapshots available
at that decision. Future forecasts and observations are rejected. Scored actuals
are ignored, preventing hindsight from becoming a forecast. The stored reserve's
initial partial load slot may bridge creation to the first full operational slot;
otherwise that gap blocks analysis.

The diagnostic consumes interval P10 solar and the greater of upper load or
expected load multiplied by 1.2. The load buffer is a configurable modelling
assumption, not a calibrated confidence interval. Known required EV demand without
timing blocks replay; unknown future charging remains a disclosed limitation.
Weather descriptions do not replace Solcast.

Default replay considers exports before 12:00 and recharge to 100% by 17:30 in
Australia/Brisbane. These times and the target are explicit model assumptions;
reusable functions accept alternatives. The CLI currently uses these defaults.

Both baseline and candidate use identical conservative solar/load and prices.
The assumed baseline supplies household deficit from battery above the linked
reserve, then grid, and charges from surplus solar before exporting remaining
solar within the export limit. It never assumes grid charging. In planned export
slots, battery charging is suspended, solar export consumes export capacity first,
and battery export uses remaining export/discharge capacity after household use.
No simultaneous battery charging/discharging is modelled.

The linked recommended reserve is never reduced. The configured minimum SOC also
applies. Greedy candidate additions must respect total discharge and grid export
power, cause no additional grid imports in any forecast slot, and reach the target
after the last export window before the deadline. Replenishment is modelled, not
guaranteed; a pointwise P10 curve is not a joint probability guarantee.

Expected incremental **model value** compares import cost and export revenue with
the assumed baseline, subtracts additional battery wear (default AUD 0.08 per
battery-side discharged kWh), and penalises lower terminal stored energy using
the highest nonnegative horizon import price and discharge efficiency. The default
minimum incremental margin is AUD 0.10 per battery-export kWh, with a minimum total
value of AUD 0.25. Fixed charges, future tariff changes and response uncertainty
are excluded. This estimate is not observed savings, validated HOLD accounting
or mathematical optimality. The bounded greedy search can miss better schedules.

Power limits default to unknown. Replay uses stored limits, with no assumed 9,999 W
export entitlement. An explicitly supplied scenario configuration is always
labelled hypothetical, keeps the action at HOLD, and cannot open calibration gates.
Replay additionally requires the exact current forecast identity and the existing
independent calibration gate before showing an advisory EXPORT_BATTERY action.
All results have `execution_ready=false`, `no_command_issued=true` and
`database_write_performed=false`.

Output includes export windows/kWh, minimum projected SOC, retained reserve,
target recharge time, comparison value, baseline/candidate battery trajectories,
assumptions, source IDs/input hash and rejection reasons. The trajectory exposes
solar charging, battery-to-house energy and reserve margin for reconciliation.

## Offline replay

Run against an explicitly exported, local snapshot bundle, never a configured
production database. The CLI has no database or Home Assistant client and does not
load `.env`:

```powershell
.\.venv\Scripts\python.exe tools/replay_solar_export.py `
  data/exports/solar_export_20261002/snapshots.json `
  --output-json data/exports/solar_export_20261002/report.json
```

The bundle is an object with `snapshots`, each containing `decision`, `observation`,
`forecast` (including immutable `points`) and `reserve`. The replay adapter documents
the required database fields. Keep household snapshots and output under ignored
`data/exports/`; do not commit them. The report accepts 1–200 snapshots, rejects
excessive timeline boundaries, and treats missing/overlapping forecast coverage
as a blocker. It does not infer solar curves from daily totals or historical PV.

## Read-only audit on 2 October 2026

A separate operational audit exported 13 existing 05:30 Brisbane decision
snapshots between 19 September and 2 October. It used PostgreSQL-enforced read-only
connections, five-second query timeouts and allowlisted fields. The missing
27 September morning sample had no matching linked decision in this query; its
absence was not explained or backfilled. Development replay and tests used only
local files/databases.

| Blocker | Snapshots |
| --- | ---: |
| No stored timed solar forecast | 13 |
| Export/discharge power limits unknown | 13 |
| No energy above linked reserve | 13 |
| Independent calibration evidence insufficient | 3 |

All 13 reserves retained 40 kWh; morning battery energy ranged from 4.8 to 26.0 kWh.
All reports kept HOLD, with unknown export quantity, recharge time and model value.
This is a readiness audit, not a successful economic backtest. A separate GET-only
check confirmed the current Solcast today sensor supplies 48 valid half-hour
intervals with all three uncertainty values. That current series was not inserted
into historical snapshots.

The next evidence requirements are deployment of interval retention through the
normal release gate, accumulation of forecast snapshots and comparison with actual
generation, independent load calibration, documented export/discharge limits,
and an assessment of the reserve estimator's full-capacity retention using timed
solar. This change does not alter that estimator or bypass its reserve.
Hardware validation and an explicitly approved executor remain separate future work.
