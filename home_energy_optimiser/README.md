# Home Energy Optimiser

Home Assistant App (formerly called an add-on) packaging for the existing
strictly read-only collector and Ingress dashboard. It reads Home Assistant Core
through the Supervisor proxy, stores observations in external PostgreSQL, and
presents existing stored data through administrator-only Home Assistant Ingress.

Version 0.3.0 retains the minimal root bootstrap introduced in v0.2.1 to copy
Supervisor's root-owned options file into protected ephemeral storage, then runs
Python as UID/GID 10001. The original `/data/options.json` is never modified.

Port 8099 remains internal to the App network. `/health` supports Supervisor
watchdog; dashboard and API routes accept only the actual Ingress gateway peer (or
loopback in tests). The dashboard uses local HTML, CSS, and vanilla JavaScript and
does not schedule forecasts or reserve estimation. Version 0.3.0 is a release
candidate until installed and verified on the real Home Assistant OS NUC.

The App cannot call Home Assistant services or control an inverter, charger, EV,
or Modbus device. See the repository installation documentation before use.
