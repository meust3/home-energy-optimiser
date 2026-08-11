# Home Energy Optimiser

Version 0.5.0 is an unreleased release candidate. It retains the UID/GID 10001,
one-process, one-collector, PostgreSQL-only App and adds one opt-in in-process
forecast coordinator. Forecast operations default to disabled; all new dashboard
routes are GET-only and no device command path exists. Explicit Alembic revision
`20260812_01` is required before App update.

Home Assistant App (formerly called an add-on) packaging for the existing
strictly read-only collector and Ingress dashboard. It reads Home Assistant Core
through the Supervisor proxy, stores observations in external PostgreSQL, and
presents existing stored data through administrator-only Home Assistant Ingress.

Version 0.4.0 retains the minimal root bootstrap introduced in v0.2.1 to copy
Supervisor's root-owned options file into protected ephemeral storage, then runs
Python as UID/GID 10001. The original `/data/options.json` is never modified.

Port 8099 remains internal to the App network. `/health` supports Supervisor
watchdog; dashboard and API routes accept only the actual Ingress gateway peer (or
loopback in tests). The dashboard uses local HTML, CSS, and vanilla JavaScript and
does not schedule forecasts or reserve estimation. Version 0.4.0 adds optional,
read-only vehicle status and SOC after an explicit additive PostgreSQL migration;
it is a release candidate and is not operational on the real Home Assistant OS NUC.

Vehicle battery power is vehicle-side raw telemetry, not charger AC demand. It is
never subtracted from household load. Fresh confirmed charging can exclude a
baseline row without changing measured house power or inventing EV power.

The App cannot call Home Assistant services or control an inverter, charger, EV,
or Modbus device. See the repository installation documentation before use.
