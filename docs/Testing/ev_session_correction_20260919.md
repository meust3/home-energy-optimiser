# Confirmed other-EV session correction - 2026-09-19

The operator confirmed another EV charged on 2026-09-18 from 11:35 to 13:10
Australia/Brisbane and explicitly authorised the annotation and accuracy repair.
The window is half-open: 19 five-minute slots, 11:35 through 13:05 inclusive.

## Backup and rehearsal

- Fresh PostgreSQL 17 snapshot backup and restore verification passed for all
  17 tables, 44 constraints and application integrity checks.
- Ignored evidence directory:
  `data/backups/ev-session-20260918-20260919T003952Z`.
- Dump: `home_energy_pre_ev_annotation.dump`, 44,170,804 bytes.
- SHA256: `e200e3b9c45ac2ec7c3ab7263eebd2c2f8327f052cc1cee00bec68c1c2ac76bb`.
- The repair was rehearsed on the restored local PostgreSQL database. Explicit
  transaction rollback restored observations, scores and rollups exactly and
  removed the uncommitted annotation. A second pass committed locally and was
  verified from a separate connection.
- The exact operational script and complete before/after receipts are retained
  beside the backup. Script SHA256:
  `dab8a4cf127496d01a22015b68d6ef91016d610656433210a325960dc616513e`.

## Production repair

Committed at approximately 10:42:38 Brisbane time on 2026-09-19, in one transaction
holding the existing forecast coordinator advisory lock. Collection continued.
This was authorised operational maintenance, not development against production.

- Session: `confirmed-other-ev-20260918-1135-1310-brisbane`.
- Existing annotation workflow stored prior derived states for all 19 observations.
- All 19 now have confirmed manual EV-session provenance and baseline eligibility
  false. No charger AC power was available; `ev_power_w` remains NULL and no power
  was inferred or subtracted.
- Corrected 912 existing score rows across overlapping baseline forecasts. Their
  observed actual values remain intact; health eligibility is false and error
  metrics are NULL. Each row retains its entire previous score inside
  `metadata_json.manual_ev_correction.previous_score`, linked to the session.
- Rebuilt all four September 18 horizon rollups from the corrected score detail.
- Raw-observation and immutable-forecast signatures matched before/after. Boundary
  observations at 11:30 and 13:10 were unchanged.
- Independent read-only postcheck confirmed the annotation, all 19 exclusions,
  all 912 score corrections and their prior-score audit records. No duplicate
  observation slots or no-command violations were found. Revision remains
  `20260905_01`; application remains v0.6.2. No migration, model adjustment,
  hardware command or release deployment occurred.

## Corrected evidence

For September 18, the independently weighted 0-3 hour horizon now has:

- 255 eligible target slots; `complete_day=false` because coverage is below 95%.
- MAE: 708.635 W (previously 1,157.478 W).
- Actual minus forecast bias: +221.469 W (previously +704.094 W).
- WAPE: 38.043% (previously 50.145%).

The other horizons have approximately 708 W MAE and the same 255 eligible slots.
These are filtered household-baseline comparisons, not total household/EV demand
forecasts. Remaining real errors are retained. Previously issued forecasts,
reserve snapshots, decisions and outcome evidence were not retrospectively
rewritten; future scheduled forecasts can use the corrected training eligibility.

## Recovery

Retain the complete backup and repair receipts. Reversing this repair requires
both the audited observation-state reversal and restoration of the affected score
states, followed by rebuilding the date's rollups in a coordinated transaction.
Running the annotation removal command alone would leave scores inconsistent.
The repair refuses to apply again when the session annotation already exists.
