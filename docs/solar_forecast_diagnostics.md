# Solar forecast diagnostics

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
