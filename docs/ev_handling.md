# EV handling

Independent EV telemetry is not currently integrated in the deployed data source.
Until it is available, EV charging can contaminate measured household load and
reduce forecast and reserve-estimate confidence. The rules below describe the
implemented handling when direct telemetry or explicit local annotations exist.

Manual session annotation, reversal, prior-state snapshots, and audit records use
the configured repository backend selected by `DATABASE_URL`. Annotation and
reversal are single transactions on both SQLite and PostgreSQL; raw telemetry and
direct EV power are preserved.

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

Historical sessions can be marked locally with `tools/annotate_ev_session.py`.
Timezone-aware start/end values select an inclusive UTC-normalized slot range;
preview is the default and `--apply` is required to write. A supplied session ID is
used verbatim, otherwise a UUID-based ID is generated. Rows without exact EV power
are excluded with `known_ev_session_without_ev_power`; no EV power is inferred.
Existing direct power is preserved and used as `max(house - EV power, 0)` when
telemetry quality permits. `--remove-session ID` previews or reverses a session
from its audited prior-state snapshots. These operations affect only the configured
database and never contact Home Assistant or hardware.
