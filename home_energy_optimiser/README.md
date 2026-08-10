# Home Energy Optimiser

Home Assistant App (formerly called an add-on) packaging for the existing
strictly read-only collector. It reads Home Assistant Core through the Supervisor
proxy and stores observations in an external PostgreSQL database.

Version 0.2.1 uses a minimal root bootstrap to copy Supervisor's root-owned options
file into protected ephemeral storage, then runs Python as UID/GID 10001. The
original `/data/options.json` is never modified.

The App cannot call Home Assistant services or control an inverter, charger, EV,
or Modbus device. See the repository installation documentation before use.
