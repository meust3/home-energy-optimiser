# Offline runner/shared-adapter wiring — 2026-10-31

Base main: `f63aac6`. Branch: `codex/jev-runner-adapter-20261031`.
Tested source tree: `91ca3ac3a767372e435c18e1ab390656623a5fc7`.
Test image: `energy-jev-wiring-tests:20261031`.

## Change

The runner can explicitly select `offline_shared_adapter` in its manifest.
That selection uses the real shared adapter, SDK 1.0.4 request construction and
receipt validators, a mandatory mock HTTP transport, then the existing owned
offline child over pipes. No network transport, URL option, runtime credentials,
discovery, retry, fallback or live mode is added. Default `offline_pipe` remains
SDK-free.

Approval binds transport selection and SDK source identity. Preflight checks all
seven published SDK Python module files against canonical SHA-256
`d7e595e586ba589e4b026faaf9e7efbadc097932c5c887a56040263144adb3fa`, computed directly
from provider Git commit `3d194368db297e33049b414c4cae345e632e5dbb`. Wrong/missing/
modified packages are refused before resources are created. Source binding also
includes the bridge and shared-adapter implementation files.

SDK-required cloud/model wire metadata is explicitly synthetic. It exists only
inside the mock exchange, not as persisted execution evidence. Saved receipts
remain `offline_simulation`, with unknown usage/cost and no production activation.
Existing durable reservations, no-restart rules, cancellation handling, ledger
checks and child cleanup still apply.

The existing AI adapter/diagnostic source, SDK pin and App runtime configuration
were not modified. No runtime bundle was installed or environment enabled. All
original uncommitted Jev/SEMS files and the earlier uncommitted review report
remain preserved. Nothing was pushed, deployed or sent to a live integration.

## Validation

- Full Python 3.12/PostgreSQL 17/SDK 1.0.4 suite: **1,486 passed, seven skipped
  in 274.47 seconds**. The skips are SQLite variants of PostgreSQL-only MVCC,
  timeout, trigger, locking and migration checks; their PostgreSQL variants run.
  The disposable PostgreSQL container has network mode `none`, no published
  ports and tmpfs storage; tests share only its network namespace.
- Focused runner/shared-adapter/SDK/diagnostic checks: **88 passed**.
- SDK-free checks: **97 passed, 23 skipped**. SDK-dependent checks skip; default
  runner checks and explicit missing-SDK refusal execute.
- Full-route rehearsal spies on both actual adapter and SDK methods and observes
  48 calls each, with exact SDK request fields reaching the owned child. A trap
  rejects construction of `httpx.AsyncHTTPTransport`; the happy path still passes.
- Wrong SDK versions/source digests, post-approval transport changes, malformed
  typed answers, wrong receipt correlation/modes, timeout and cancellation are
  tested. Failures retain unknown attempts/reservations and stop without retry.
- Ruff and Black pass over source, tests, tools and migrations (199 Python files).
  All 11 JavaScript tests pass.
- An installed wheel, outside the source tree and with networking disabled,
  completed 48 cases through the actual shared adapter/SDK/mock-pipe CLI path.
  Process lookup confirmed the owned child had exited. Removing the SDK then
  refused that mode before creating a registry; the SDK-free pipe CLI still
  completed 48 cases. No network or credential configuration was supplied.

All test execution uses synthetic data in disposable containers with external
networking disabled. There are no provider credentials or live requests. Mocked
success does not establish current provider compatibility, billing, model quality
or production acceptance.

## Standards

Independent standards review found zero hard violations and zero actionable
smell findings. The SDK subclass is a deliberate constructor seam that prevents
network transport creation while preserving pinned SDK behavior.

## Spec

Independent specification review found no functional or safety defects. It
identified stale guide wording about SDK/adapter absence; the guide now qualifies
the default SDK-free mode and documents the optional mock-only shared-adapter
path. No outstanding confirmed specification findings remain.

Standards: zero outstanding findings. Spec: zero outstanding findings after the
documentation correction. Live execution remains disabled and unestablished.

Usage: [offline runner guide](../integrations/jev-offline-runner.md).
