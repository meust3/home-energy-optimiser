# EV handling

All EV entities are optional and read-only. Direct charging-active and power sensors
are preferred. Required-energy and ready-by helpers provide future planning context
but are never created or changed by this project.

Baseline load is `max(house - EV power, 0)` only when direct EV power exists. When
EV is inactive, baseline equals measured house load. If charging is active with
unknown power, or inference detects a candidate session, measured load is retained
unchanged and the sample is excluded from baseline training.

Inference is disabled by default. It requires sustained load in configured charger
bands with low variability and sufficient duration. It produces confidence and
evidence only, never a control action or override of direct data.

Suggested future helpers, documented but not automatically created:

- `input_boolean.energy_optimizer_ev_expected`
- `input_number.energy_optimizer_ev_required_kwh`
- `input_datetime.energy_optimizer_ev_ready_by`
