# Home Energy Optimiser

The App collects energy observations every five minutes and displays them in a
read-only Home Assistant dashboard. It stores history in PostgreSQL and issues
no hardware commands.

## Completed v0.8.9 dashboard update

Production updated from v0.8.8 to v0.8.9 on 21 November 2026. The App passed
startup checks on the existing PostgreSQL revision `20261101_01`.
**No database migration was required for this update.** Forecast Operations
loaded scored results and the weather archive fit a narrow screen.

All 61 saved App options matched their pre-update values, including enabled
ten-minute weather collection and the confirmed 1,000-call daily provider cap.
The first scheduled capture after restart completed in four requests and
archived all 192 quarter-hour targets in its 48-hour window.

## Recovery and earlier migrations

For a rollback to v0.8.8, preserve the current database, including forecast
versions and the weather call ledger. The runbook covers pending receipts and
taking a fresh recovery backup before rollback.
[Rollback without losing newly collected history](https://github.com/meust3/home-energy-optimiser/blob/v0.8.9/docs/Testing/v089_update_preparation.md#rollback-without-losing-newly-collected-history)

The migration from `20261024_01` to `20261101_01` applied to the v0.8.6 → v0.8.7
upgrade. See the [v0.8.7 preparation record](https://github.com/meust3/home-energy-optimiser/blob/v0.8.9/docs/Testing/v087_update_preparation.md)
and [archived notes for earlier releases](https://github.com/meust3/home-energy-optimiser/blob/v0.8.9/home_energy_optimiser/README.md#historical-release-transitions).
