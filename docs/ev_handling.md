# EV handling

Read-only vehicle-cloud telemetry is operational from v0.4.0 while direct charger
AC power remains
unavailable. Until AC power is integrated and validated, EV energy separation is
incomplete even though fresh confirmed charging rows can be excluded safely.

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

Vehicle charging and plugged states are distinct. Fresh confirmed charging with no
direct AC power preserves measured house load, leaves `ev_power_w` NULL, and uses
`known_ev_session_without_ac_power`; fresh plugged-idle data does not exclude a row
solely because the cable is connected. Stale or offline `off` is unknown rather
than confident not-charging. Raw vehicle battery power is stored separately and is
never subtracted or used as a non-zero charging heuristic.

See [read-only vehicle telemetry](byd_vehicle_integration.md) for configuration,
privacy, migration, first-session validation, and rollback.
