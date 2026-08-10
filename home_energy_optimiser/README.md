# Home Energy Optimiser

Home Assistant App (formerly called an add-on) packaging for the existing
strictly read-only collector. It reads Home Assistant Core through the Supervisor
proxy and stores observations in an external PostgreSQL database.

The App cannot call Home Assistant services or control an inverter, charger, EV,
or Modbus device. See the repository installation documentation before use.
