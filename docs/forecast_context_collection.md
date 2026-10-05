# Optional forecast context - migration and recovery runbook

v0.7.0 is a local release candidate based on released v0.6.5
`a93532b9ad5d604ee69a8215bb8ee9b5482e7af4`. Publication, HA cache setup, production
migration/App installation and mapping activation require separate approvals.
The release collects context only; forecasts do not consume it yet. It does not
claim improved accuracy, physical outdoor sensing, metered HVAC power or savings.

## Frozen defaults and local evidence

`context_collection_enabled: false`; `context_mapping_json: ""`. The private
mapping remains inactive, with its retained 2099 effective date. Other model,
calibration, reserve, shadow, non-HOLD, AI and retention settings are unchanged.
Do not copy real entity IDs or private mappings into public examples.

The corrected fictional [hourly cache example](examples/met_no_hourly_cache.yaml)
has SHA-256 `abcd0843ceb483e8beca1d4b55ec687842c37fc588ae3e768725ff8c757478d3`.
It matches the validated private draft structurally after substituting only the
source variable. Its unavailable/restored state retains the last successful
attributes honestly; it does not make them newly usable. Scalar fields are bounded
to 64 characters, nested/boolean values rejected, and the ASCII-serialized array
bounded to 65,536 bytes. Energy's separate normalized bound remains 256 KiB.

The immutable [final runtime report](Testing/forecast_context_final_runtime_validation_20261005.md)
records Python 3.12.11, 558 Python tests, seven JavaScript tests, 13 synthetic HA
Core 2026.9.3 cases and their 13 matching parser-bridge cases. Those are paired
checks, not 26 independent live HA tests. It records source identity, migration,
legacy hashes and isolated recovery. Its raw receipts and the private mapping
remain outside Git. The original implementation report is preserved; its earlier
suggestion that an old-App reinstall can retain the new schema is superseded by
the tested matrix below.

## Schema and tested recovery matrix

The only transition is `20260927_01 -> 20261005_01`, adding
`context_observations` and `weather_context_snapshots` via
`migrations/versions/20261005_01_forecast_context.py`. The exact new revision is
required even when collection is disabled. App startup does not migrate.

| Code/schema | Supported result and recovery interpretation |
|---|---|
| v0.6.5 / 20260927_01 | Prior operating baseline, requiring a later live identity preflight. |
| v0.6.5 / 20261005_01 | Startup rejects the revision before HA validation, with both old-shaped and disabled new-shaped options. Reinstalling this old App while retaining the new schema is not recovery. |
| Tested compatible candidate / 20261005_01 / context disabled | Core collection starts and existing context/weather rows remain. Preferred non-destructive recovery for the supported context-specific containment scenario. |
| Compatible candidate / enabled synthetic mapping | Optional inserts succeeded; a revoked INSERT grant produced an optional failure without undoing the durable core observation, and restoring the grant recovered in the same process. |
| Physical downgrade to 20260927_01, then v0.6.5 | Prior code starts, but both context/weather tables and all their history are deleted. This is destructive and is not automatically authorised. |
| Re-upgrade after physical downgrade | Legacy values survive; dropped context/weather history is not recreated. |
| Restore an old-head backup, then v0.6.5 | Tested with synthetic pg_dump/pg_restore only. All post-backup writes are lost, including core/analytical history; separate explicit approval is required. |

The compatible recovery artifact is the same source-verified v0.7.0 App image
prepared for this release, identified by exact local commit/image ID in the private
release manifest. No alternative recovery implementation is introduced. Its
entrypoint is `home_energy_optimiser/run.sh`, then unprivileged
`python tools/run_home_assistant_app.py`. For the supported scenario, retain the
compatible code and new schema and disable context; the empty mapping is already
the release default. Existing context history remains stored.

Disabling context contains optional context failures; it is not proof of recovery
from broken packaging, incompatible startup code, unavailable PostgreSQL, HA or
other infrastructure failures. Preserve existing unrelated settings. Do not
`alembic stamp`, weaken revision checks or automatically drop tables. No physical
downgrade/restore command is authorised by this runbook alone.

## Later publication gate

1. Obtain publication approval for the exact local commit and v0.7.0. Recheck
   remote lineage and version availability. Obtain current confirmation automatic
   App updates are disabled before making the update discoverable.
2. Use the protected release process without force. Build and probe the exact
   remotely addressable commit, then the immutable tag, before acceptance. Local
   archive/working-source builds are not remote/tag-resolved validation. Never move
   a published tag. Validate any different merge/discoverable source explicitly.
3. Keep a built, source-verified schema-compatible disabled recovery image
   available before the separately approved migration. Record its exact identity,
   dependencies, bootstrap and supported recovery checks.

The current workflow runs on pull requests to `main` or manual dispatch. It uses
owned CI PostgreSQL, installs test dependencies, runs source/tests, builds the
exact head App and probes image files; it does not deploy, call hardware, activate
collection or invoke models. A simple branch/tag push does not trigger this
workflow. Updating the discoverable App repository can offer v0.7.0 to HA; that
does not authorise installation or schema changes.

## Later HA cache setup gate

Approve the exact private configuration merge, backup, real HA validation and
specific reload/restart first. Reuse the existing Met.no integration. HA's approved
`weather.get_forecasts` cache action is separate from Energy's GET-only client.
Verify the naturally generated entity ID and ordinary minute-17 receipts without
startup warm-up, forced polling or provider changes. Restore/failure cases are
locally tested; real provider coverage and receipt timing are still unverified.
No missing indoor/HVAC value or physical outdoor sensor is invented.

## Later production switch gate

1. Approve the specific production preflight, fresh external PostgreSQL backup,
   isolated restore, writer pause, migration and App replacement window. HA App
   backups do not replace external PostgreSQL backups. Compare backup/restore at
   a common cutoff or while writers are deliberately quiescent.
2. Verify actual installed source/schema/options and exactly one collector. Have
   the compatible replacement and recovery artifact ready before stopping it.
   Preserve HOLD-only, non-HOLD-disabled, AI and retention settings. Lifecycle
   changes to watchdog/autostart require explicit approval.
3. Stop the necessary writers, then use pinned approved release source to migrate
   explicitly to `20261005_01`, not an arbitrary newer checkout's head. Verify
   legacy preservation and narrowly required schema USAGE/SELECT/INSERT privileges.
   Hashed new primary keys require no new sequence privilege. Stop on discrepancy.
4. Start the approved compatible App with collection disabled and no active
   mapping. Verify a new normal core observation, forecast/coordinator operation,
   Ingress/health, no-command boundaries and one collector. Restore only approved
   lifecycle controls. Do not start v0.6.5 on the migrated schema.

## Later mapping activation and bounded acceptance

Approve the exact private mapping separately. Keep the reviewed five-zone,
20-quantity scope; confirm the generated cache ID, new version/hash and a real UTC
effective-from instant at or after activation. Preserve the inactive draft, do not
backdate records, and change only the explicitly approved context settings.

Indoor/current-weather collection and hourly cache acceptance are separate. Missing
cache remains pending without invalidating core observations. A cache that existed
earlier does not establish earlier Energy knowledge. Preserve source/cache receipt
versus provider issuance distinctions, missing versus zero, domain/unit labels,
deduplication, snapshot history and immutable core/decision records. Use bounded
chronological read-only acceptance after separate authority; no forced updates,
history repair, inference or comparative economic scoring. Storage/latency fixture
measurements are not production growth or timing guarantees. Retention stays off.
