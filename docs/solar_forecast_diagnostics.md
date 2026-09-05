# Solar forecast diagnostics

v0.6.0 reads the persisted normalized `estimate10_kwh`, `estimate_kwh`, and
`estimate90_kwh` keys first. Legacy `estimate10`, `estimate`, and `estimate90`
remain readable; explicit Wh provenance is converted once to kWh. Values are not
changed or automatically derated, and classifications remain cautious context.


The GET-only solar diagnostic compares the earliest persisted start-of-day
Solcast P10/P50/P90 summary with realised PV integrated from five-minute raw power.
A day requires 95% telemetry coverage before comparison.

Battery SOC/headroom, charge/discharge duration, export duration, observed work
modes, and possible inverter-ceiling duration are reported as context. Labels are
deliberately cautious:
`likely_unconstrained`, `possible_battery_saturation`,
`possible_export_constraint`, `possible_inverter_clipping`,
`multiple_constraints_possible`, or `insufficient_context`.

These labels do not prove curtailment. The project does not persist enough context
to make every constraint claim, so unavailable evidence remains unavailable.
Private Solcast attributes, identifiers, coordinates, and credentials are not
returned. No automatic Solcast derating is calculated or applied, and no forecast,
reserve, or device-control arithmetic changes.
