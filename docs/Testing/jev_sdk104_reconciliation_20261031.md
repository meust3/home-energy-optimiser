# Jev adapter and SDK 1.0.4 reconciliation — 2026-10-31

Base main: `0b5f655`. Integration branch:
`codex/reconcile-jev-sdk104-20261031`.

## Scope and safety

The optional Python dependency now pins provider commit
`3d194368db297e33049b414c4cae345e632e5dbb` (SDK 1.0.4). The additive
`review_jev_evaluation_case` method accepts fixed case/operation/experiment IDs
and a manifest digest, only in the test environment against loopback. It uses
the SDK's published request and receipt validator without ordinary capabilities
discovery. SDK version checks occur inside the optional failure boundary and
before client creation. Missing SDKs return unavailable; disabled integrations
return disabled; other environments, off-host targets and wrong SDKs are denied.

Main's nullable diagnostic SDK field is preserved. Supported older diagnostic
versions remain readable. Pilot/holdout fixtures are unchanged and accept SDK
1.0.4; the offline comparison's metadata is checked against that pinned package.
The status surface reports expected SDK 1.0.4 without network activity.

The default App omits the SDK. The optional App requires a checksum-verified
1.0.4 wheel supplied through a BuildKit secret. No runtime credentials or
connection bundle are installed. AI remains disabled and unconfigured.

No runner, scheduler or live submission CLI was imported from the dirty Jev
worktree. Loopback alone does not establish ownership of a test service. The
published requirements for a verified manifest, separately approved experiment,
exclusive test process/database, ledger reconciliation, billing verification and
cleanup remain outstanding. No inference is authorized by these code changes.
The prior model quality gate remains failed. No production service, database,
hardware or integration was contacted or changed; nothing was pushed.

## Source provenance

Test/build source tree: `5d21cada027509bda48abe9c166b39d0b300e591`.
Runtime source archive SHA-256:
`fb6b948b3bb5d930390c3f869e9417c7f36ab92978993a73e7278e85eee04649`.
SDK wheel SHA-256:
`a68c4a4c210755f8e8f085af003ee601f231661623ff78467178b95672cdd966`.

The SDK wheel was built offline from the exact local provider Git archive, using
cached build dependencies. It is not committed. App builds consume the immutable
runtime archive and this wheel; normal public build dependencies are separate
from disabled live application integrations.

## Validation

- Full Python 3.12/PostgreSQL 17/SDK 1.0.4 suite: **1,435 passed, seven skipped
  in 287.64 seconds**. The skips are SQLite variants of PostgreSQL-specific
  MVCC/timeout/trigger/locking/migration tests; the PostgreSQL variants execute.
  The disposable database has network mode `none`, no published port and tmpfs
  storage; the test process shares only that container's network namespace.
- Focused SDK 1.0.4 tests: **124 passed**. Includes existing AI diagnostics,
  App initialization, pilot/holdout and offline comparison behavior.
- SDK removed in a disposable container: **58 passed, 11 skipped**. Only
  SDK-dependent wire/version/fidelity tests skip. Disabled, missing-SDK and
  out-of-scope adapter guards execute without the package.
- New wire tests use the actual SDK with `httpx.MockTransport`. They verify
  one exact evaluation request, no discovery, mismatched correlation/provider/
  safety receipts rejected, malformed typed answers rejected, missing usage and
  confidence preserved, and transport failure without retries or fallback.
- Ruff and Black pass over source, tests, tools and migrations (193 Python
  files). All 11 JavaScript tests pass.
- Both local App builds passed the image-baked bootstrap/Ingress probe: root-only
  options, UID/GID 10001, no secret output, health endpoint, rejection of direct
  requests and SIGTERM handling. Tags are
  `energy-jev-sdk104-app:20261031-default` and
  `energy-jev-sdk104-app:20261031-optional`; neither was published or deployed.
- All 92 installed Python/static/reference files in each image match the
  canonical Git blobs of the tested source tree. Network-disabled image checks
  verify SDK absent/default versus SDK 1.0.4/optional, disabled status, nullable
  diagnostic SDK evidence, all 48 offline reference cases and a disabled Jev
  call returning before SDK/client use.

Image IDs:

- Default: `sha256:11032895bed92bcb3feca35afbd1a403098c9a25d7e1d4817738b761a8307d61`.
- Optional: `sha256:fbb1ad4035611e6a8c5c7f8e9dc7edeae326aab1668deb9c43c480a16fa5cd28`.

All original uncommitted Jev/SEMS files and the earlier uncommitted review report
are preserved. Production acceptance and live Jev quality are not established.
