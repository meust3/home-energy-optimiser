# v0.6.5 shadow evidence release candidate

Status: preparation only; not published, deployed or runtime-attested.
Application version 0.6.5 and calculation identity `battery-shadow-evidence-v2`
are separate. Policy, assumption and outcome scoring versions are unchanged.

## Source lineage and scope

The original validated F1-F3 candidate was based on v0.6.4 commit
`10d79a809ae26ba32c739a3c233f68ca4a817f61`. This candidate integrates that correction
onto main `601e0ebddacf57270f1fd910b511076391487b8a`. Their net difference is the
v0.6.4 acceptance receipt and release-gate documentation; runtime source is equal.
Receipt `a169678c161c469a230216877b779197e2606b82` is historical acceptance evidence,
not fresh verification of the installed production build.

F1 combines compatible linked reserve household intervals before operational
alignment with operational intervals owning the aligned span. IDs, model, target,
alignment, training policy and evaluation/history context must agree. Partial
interval-average energy is clipped by duration; gaps, overlaps and incompatible
inputs stay unavailable with reasons. Reserve total/EV demand is not added and
later operational gaps are not filled. Consumed segment provenance is bounded.

F2 records signed battery-after minus reserve separately from clamped available
energy. Missing inputs stay null. Shortfall does not make no-command HOLD
infeasible. Absent calculation markers retain legacy stored semantics; unknown
markers are not asserted to have evidence-v2 semantics. Historical hashes and
boundary-plus-policy deduplication remain unchanged.

F3 applies the existing one-second tolerance independently at internal adjacent
price boundaries. Endpoints are strict, including subsecond gaps. Zero/negative
finite prices and represented-duration weighting remain valid. Arrays are not
mutated; sorted-first overlap behavior remains, including conflicting exact-tie
source-order dependence as a known limitation.

Corrected inputs can change future diagnostics and feasibility; unchanged economic
formulas do not imply identical outputs. No recalculation or historical repair is
included. Comparative selected/HOLD, hindsight, regret, simulated minimum reserve
and reserve safety remain unavailable under `battery-shadow-outcome-v2`.
Forecast-versus-Actual eligibility, matched periods, thresholds and delays remain
unchanged. No authority, routing, inference, physical-limit or policy activation.
Source migration head remains `20260927_01`; this patch introduces no migration.

## Validation and artifact gate

The original candidate validation remains independently preserved. A separate
private release manifest records metadata/docs changes and any proven existing Git
line-ending canonicalisation. Full isolated default and owned PostgreSQL suites,
Node suites, style/compilation/dependency checks must pass on the final release
source. Unchanged dashboard assets retain the prior desktop/narrow fixture QA.
The exact committed source must build with its full SHA, version 0.6.5 and
Linux/AMD64, match application source/assets, package canonical LF bootstrap and
pass the image-baked probe without replacement source mounts. Actual results,
commit, image/base/dependency identities and manifests belong in the private
preparation receipt; this document does not claim those pending gates have passed.

## Later publication and update (separate authorisation)

1. Obtain fresh confirmation automatic App updates are disabled before publishing
   anything discoverable. Recheck unused v0.6.5 tag and remote lineage. Tag only
   the approved exact commit; follow main/PR branch protection without force.
   Validate tag-resolved source and any different merge/discoverable artifact.
   Stop for confirmation Home Assistant discovers the intended version.
2. Separately verify installed build, compatible schema, effective HOLD-only,
   calibration/routing/retention gates and recoverable backup. Stop on discrepancy.
   Update only the App with one collector and restore any explicitly managed
   watchdog state. No Alembic upgrade/downgrade/stamp or routine database restore.
3. Inspect a bounded chronological sample of new evidence-v2 decisions and linked
   inputs. Recompute exact consumed segment overlaps, signed/clamped margins and
   actual price boundaries; accept precise unavailable reasons. Verify no command,
   unchanged selection gates and fixed-ID/cutoff historical hashes. Account for
   normal append-only writes, not whole-database totals during collection.
4. Confirm outcome-v2 comparative fields remain unavailable, Forecast vs Actual
   rules remain intact, and collector/forecast/reserve progress is healthy. Report
   absent representative conditions as pending; no backfill or injected fixtures.
5. Roll back application artifacts only, preserving new v2 rows and hashes. First
   verify previous-app additive-JSON tolerance; document legacy display limits.
   Do not erase/relabel rows or restore an old database to conceal the rollback.

This correction improves evidence truthfulness; it establishes neither forecast
accuracy, paired policy value, a validated battery trajectory nor monetary savings.
