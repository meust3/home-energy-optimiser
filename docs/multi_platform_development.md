# Multi-platform development

Production uses `home_energy`/`energy_app`; development uses `home_energy_dev`/`energy_dev`; analytics uses `home_energy`/`energy_readonly`; tests use temporary SQLite databases. Migration writes to `home_energy` require explicit production confirmation.

Each machine keeps its own `.env`; GitHub contains source and migrations only. Run `python tools/check_database.py --json` before work to confirm the redacted target and revision. Never paste complete connection URLs into tickets or logs.

Do not mix backends within one shell/process. Changing `DATABASE_URL` changes the
collector, reserve estimator, inspection, forecasts, annotations, reprocessing, and
exports together.

The Home Assistant App is the production wrapper only. It obtains Home Assistant
authentication from `SUPERVISOR_TOKEN` and refuses SQLite. Windows workflows remain
unchanged and continue to use `HA_URL`, `HA_TOKEN`, and `DATABASE_URL` from the
local environment or `.env`. Development must target `home_energy_dev` as
`energy_dev`; production analysis should use `energy_readonly` unless collection is
being deliberately rolled back to Windows.
