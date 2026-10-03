# Home Energy Optimiser

Version 0.6.5 is a release candidate, not yet published or deployed. It corrects
shadow evidence with compatible partial-window household-demand assembly, signed
HOLD reserve margin separately from clamped available energy, and per-boundary
price tolerance. New calculations use `battery-shadow-evidence-v2`; legacy and
unknown markers retain explicit display semantics. Existing records are untouched.
No schema migration is required from v0.6.4 (`20260927_01`). Policy, assumptions,
physical limits and no-command authority remain unchanged; outcome-v2 comparative
economic fields remain unavailable. See the v0.6.5 release preparation notes.

Version 0.6.4 retains the existing schema `20260927_01`; no migration is
required from a running v0.6.3 installation. It preserves Solcast half-hourly
P10/P50/P90 forecasts in observation JSON and adds an explicit offline morning
export diagnostic. Production recommendations remain HOLD-only, retention stays
disabled, and no hardware control or scheduled export planner is introduced.
Take a fresh backup and validate its isolated restore before a controlled update.
Older migration instructions below apply only to their named releases.

Version 0.6.3 requires the index-only revision `20260927_01`. Stop the App, take
a fresh backup and validate its isolated restore, then manually migrate before
starting this version. It bounds forecast scoring scans, separates the 20 kW PV
plausibility limit, and adds opt-in GoodWe runtime timestamp evidence for SOC.
Keep shadow decisioning HOLD-only and retention disabled. The App never migrates
at startup and never issues hardware commands. Older migration notes below apply
only to their named releases.

Version 0.6.1 corrects observed outcome accounting and appends scoring v2. HOLD
comparisons, hindsight, regret and simulated reserve safety remain unavailable
until a counterfactual model is validated. Existing v1 rows remain audit-only.
This update retains schema `20260905_01`; do not migrate an existing v0.6.0 database.
Keep non-HOLD selection and retention disabled. No hardware command is issued.

Version 0.6.0 retains UID/GID 10001, GET-only Home Assistant access, one process,
one collector, and the existing forecast coordinator. Its battery shadow engine,
Decisions view, and Forecast vs Actual card are advisory only. Shadow decisioning
and non-HOLD selection default off; unknown power limits block dependent
candidates. Revision `20260905_01` must be migrated manually and the App never
executes an action or migrates at startup.

Version 0.5.2 retains the UID/GID 10001, read-only Home Assistant access, one
process and one collector. It requires schema revision `20260814_01` and adds
independent calibration rollups, negative-demand validation, and GET-only solar
diagnostics. Retention remains disabled by default.

Version 0.5.1 retained the UID/GID 10001,
one-process, one-collector, PostgreSQL-only App and adds one opt-in in-process
forecast coordinator. Forecast operations default to disabled; all new dashboard
routes are GET-only and no device command path exists. Explicit Alembic revision
`20260813_01` is required before App update and is already expected in production;
no migration is needed for this deployment. The revision adds only forecast
accuracy rollups and retention-maintenance audit tables.

Home Assistant App (formerly called an add-on) packaging for the existing
strictly read-only collector and Ingress dashboard. It reads Home Assistant Core
through the Supervisor proxy, stores observations in external PostgreSQL, and
presents existing stored data through administrator-only Home Assistant Ingress.

Version 0.5.0 retains the minimal root bootstrap introduced in v0.2.1 to copy
Supervisor's root-owned options file into protected ephemeral storage, then runs
Python as UID/GID 10001. The original `/data/options.json` is never modified.

Port 8099 remains internal to the App network. `/health` supports Supervisor
watchdog; dashboard and API routes accept only the actual Ingress gateway peer (or
loopback in tests). The dashboard uses local HTML, CSS, and vanilla JavaScript and
does not schedule forecasts or reserve estimation. Version 0.4.0 added optional,
read-only vehicle status and SOC after an explicit additive PostgreSQL migration
and is operational on the Home Assistant OS NUC.

Version 0.4.1 adds validated, installation-specific power-sign options, explicit
unconfigured-sign diagnostics, and protected historical derived-field repair. It
does not change the database schema, raw telemetry, normalization equations, or
read-only boundary. Production installation and acceptance remain gated.

Vehicle battery power is vehicle-side raw telemetry, not charger AC demand. It is
never subtracted from household load. Fresh confirmed charging can exclude a
baseline row without changing measured house power or inventing EV power.

The App cannot call Home Assistant services or control an inverter, charger, EV,
or Modbus device. See the repository installation documentation before use.
