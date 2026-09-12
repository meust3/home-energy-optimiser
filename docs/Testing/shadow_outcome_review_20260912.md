# Shadow outcome review and deployment evidence — 2026-09-12

## Conclusion

Correction is required, not relabelling alone. The published v0.6.0 scorer cannot
establish performance against HOLD, hindsight regret or simulated reserve safety.
The v0.6.1 candidate on `codex/shadow-outcome-semantics` corrects observed accounting
and explicitly leaves unsupported comparisons unavailable. It is not deployed.

## Findings and resolution

| Finding in released outcome v1 | Development correction |
| --- | --- |
| Total energy multiplied by average price misprices varying load/prices | Sum paired slot energy times slot price; negative prices remain valid |
| Missing flow totals become zero in observed value | Missing/invalid evidence leaves affected whole-window totals NULL |
| Partial first slot omitted and remaining samples counted as full five minutes | Query overlapping first slot and integrate exact overlap duration |
| Coverage uses rounded slot count and separately counted price lists | Duration-weighted coverage; both prices/directions must coexist on each slot |
| Candidate nominal value added on top of observed operation | Withhold selected/HOLD/hindsight/regret metrics; observed operation is not a counterfactual baseline |
| Observed battery minimum stored as simulated reserve safety | Simulated minimum and breach remain NULL pending a trajectory model |

Scoring version changes explicitly from `battery-shadow-outcome-v1` to
`battery-shadow-outcome-v2`. Policy/assumption versions and schema remain unchanged.
Existing v1 evidence is preserved, and the same bounded coordinator may append v2
outcomes. The dashboard marks legacy estimates unvalidated and shows corrected
observed gross value. No policy, forecast hierarchy, reserve estimator, control,
retention setting or production state was changed.

## Home Assistant evidence

Read directly through the existing authenticated Chrome session on 2026-09-12,
approximately 14:40–14:45 Australia/Brisbane:

- App Info: current version **0.6.0**, state **Running**.
- Configuration: shadow decisioning **enabled**, non-HOLD recommendations
  **disabled**, retention **disabled**. Save button was disabled; no option edited.
- App auto-update **disabled**.
- Ingress Data Quality: current collection **Healthy**, recent 24-hour coverage
  **100%**, latest observed stored slot **14:40** at inspection.
- Logs: 14:30 boundary persisted **HOLD**, nine candidates,
  `no_command_issued=true`; matured outcome scoring stored one row. Collection
  continued at five-minute slots through 14:40. This is already a HOLD-only soak.
- Exact live schema revision was not independently read. The visible log did not
  include startup schema output, and direct status JSON navigation was blocked by
  the browser. The release expects `20260905_01`; expectation is not a live query.

Installed/running evidence supersedes the old pending-discovery claim. No historical
backup/restore certificate, migration audit, or deployed image digest was inspected.
Do not infer those gates passed from App version alone or repeat a migration based
on obsolete documentation. No Home Assistant service or hardware control was used.

## Published tag container validation

Remote refs verified on 2026-09-12:

- `origin/main` and peeled `v0.6.0`:
  `4bf59ef4de8dd9b56e604f5c7f3b22aae5d5865b`.
- Annotated tag object: `500e7d70b8dc6ff744d03e0d9109d09f21bca59e`.
- Built local image: `home-energy-optimiser:validation-v0.6.0`, linux/amd64.
- Image ID: `sha256:0b31ba93f98df526ea777e0ed08c21a44daab31c32744574a23edd1210c3ca1e`.
- Python base digest:
  `sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7`.
- SHA256 comparison: **67** source/packaging/migration files match the tag;
  **50** installed package files also match the tag.
- Image dependency consistency: **PASS**.
- Image-baked bootstrap probe (`--use-image-files`): **PASS**, covering protected
  options, UID/GID 10001, disabled shadow defaults, unchanged Supervisor options,
  secret-free output, trusted Ingress, denial of direct/spoofed access and SIGTERM.
- Working-source mounted bootstrap probe: **PASS**, separately checking the
  development source in the same runtime. This is not a released corrected image.

Reproduction commands (local synthetic tests, no production connections):

```powershell
docker build --platform linux/amd64 --build-arg APP_SOURCE_REF=v0.6.0 --build-arg BUILD_VERSION=0.6.0 --tag home-energy-optimiser:validation-v0.6.0 --file home_energy_optimiser/Dockerfile home_energy_optimiser
python tools/test_home_assistant_app_container.py --image home-energy-optimiser:validation-v0.6.0 --use-image-files
```

This validates a newly built image from exact tagged source. Dependencies have
minimum constraints, so it does not prove byte-for-byte identity with the image
already installed in Home Assistant. The v0.6.0 tag has not been moved or modified
and does not contain the correction.

## Development validation

SQLite: **356 passed, 9 skipped** (67.22 seconds). Disposable local PostgreSQL
17: **365 passed, 0 skipped** (69.79 seconds). Ruff, Black, compileall, JavaScript
syntax and `git diff --check` pass.
The PostgreSQL container is bound only to loopback, uses synthetic credentials,
and is removed after testing. No production database was opened or migrated.

## Local Docker repair

Docker initially failed because both `.docker/daemon.json` (124 bytes) and
`.docker/windows-daemon.json` (28 bytes) contained only NUL bytes. Each was backed
up to its sibling `.corrupt-20260912` file and replaced with valid empty JSON.
Docker Desktop subsequently started successfully. No factory reset, container
store deletion, or unrelated configuration change was performed.

## Next release gate

Review the correction as a separate release; never move `v0.6.0`. Its corrected
immutable artifact will need its own source/image validation. Keep current
non-HOLD selection disabled: this correction deliberately does not implement the
validated counterfactual model required for decision-quality approval. A later
model needs explicit HOLD dynamics, reconciled battery trajectories, common
load/PV evidence, terminal stored-energy value, and intervention uncertainty.

Any subsequent operational change remains subject to the existing manual gates.
This change introduces no migration, and the previous v0.6.0 migration must not be
repeated without first establishing the actual production revision.
