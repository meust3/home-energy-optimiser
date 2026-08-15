# Forecast calibration

Headline calibration uses one exact identity: `forecast_type`, `model_version`,
`alignment_version`, and `training_policy`. For the intended v0.5.1 production
configuration this is baseline household load,
`household-demand-hierarchy-v1-cohort-v1`, `full_5m_v1`, and
`verified_preferred`. A change to any identity component forms a new cohort and
starts with its own evidence.

Legacy and ad-hoc runs remain immutable. Pre-v0.5.1/legacy metrics remain visible
as a separate baseline, but legacy alignment, another model version, or another
training policy cannot contribute to Current model status. If the current cohort
lacks enough history, its result is `insufficient_data`; calibration never falls
back to legacy scores. Positive bias means the forecast was above the actual load.
Metrics include bias, absolute bias, MAE, RMSE, coverage, local-hour and
0-3/3-6/6-12/12-24 hour buckets, plus energy error for complete 288-point runs.

A meaningful status requires at least two independent current-cohort runs, one
complete 24-hour run, and 80% eligible coverage. These are project engineering
heuristics: good is absolute bias <=200 W and MAE <=600 W; acceptable is <=300 W
and <=750 W; degraded is <=600 W and <=900 W; otherwise status is poor.
Calibration is advisory quality and never affects the watchdog or executes a
command.

The measured pre-v0.5.1 reference is +767 W forecast-high bias, 956 W MAE, and a
46.9 kWh recent forecast versus 27.8 kWh actual. These values are a displayed
benchmark, not algorithm inputs. Genuine improvement must be measured after new
aligned forecasts accumulate; v0.5.1 must not be described as production
calibrated before that evidence exists.
