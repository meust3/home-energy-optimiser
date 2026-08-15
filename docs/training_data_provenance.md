# Training-data provenance

Each candidate training sample is classified independently as
`verified_non_ev`, `verified_ev_excluded`, `direct_ev_separated`,
`manual_historical_ev`, `pre_ev_telemetry_unknown`, `suspected_historical_ev`, or
`unknown`. The verified boundary is the first row with a configured independent EV
source, fresh telemetry, known charging state, and direct confidence. Intermittent
rows are still classified individually.

`verified_preferred` first attempts each unchanged hierarchy tier using verified
clean samples. If the tier minimum is not met, eligible pre-telemetry history may
be used and its share and contamination warning are recorded. Confirmed charging
and approved manual exclusions are never training samples. General configuration
retains `legacy_all_eligible` for compatibility; new App options default to
`verified_preferred`. Tier 1 minimums and the Tier 2 arithmetic mean are unchanged.
