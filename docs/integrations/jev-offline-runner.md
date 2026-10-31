# Jev experiment lifecycle: offline rehearsal

This runner exercises experiment safeguards using a real owned local child and
a synthetic SQLite ledger. It has **no live mode**, URL option, production
database connection, inference request or hardware path. The default
`offline_pipe` transport needs no Panel SDK. The optional
`offline_shared_adapter` transport exercises the real shared adapter and pinned
SDK through a mandatory mock transport. Its result is lifecycle and adapter
contract evidence, not Jev performance or paid-run readiness.

## Running a rehearsal

From an installed development checkout, prepare a manifest with a fresh UUID:

```powershell
python -m tools.jev_rehearsal prepare --experiment-id <UUID> --output <manifest.json>
```

To include the shared adapter and SDK validators, use the pinned SDK 1.0.4 and:

```powershell
python -m tools.jev_rehearsal prepare --transport offline_shared_adapter --experiment-id <UUID> --output <manifest.json>
```

The selected transport and SDK source digest are included in the manifest and
its approval hash. There is no run-time override or automatic fallback. Missing,
wrong-version or modified SDK files refuse this mode before a registry claim or
child is created. Prepare a fresh manifest after source changes; existing
experiment claims remain protected against restart.

Preparation refuses an existing output file and does not create an approval.
An offline approval JSON has this shape:

```json
{
  "approval": "APPROVE_OFFLINE_JEV_REHEARSAL",
  "manifest_sha256": "<SHA-256 of the exact manifest file bytes>",
  "max_cost_usd": "0.13"
}
```

Then run the bounded rehearsal:

```powershell
python -m tools.jev_rehearsal run --manifest <manifest.json> --approval <offline-approval.json> --registry <persistent-rehearsal-directory>
```

This approval is distinct from, and cannot substitute for, the published live
approval. Live approval markers and live configuration fields are rejected by
the offline runner. The manifest binds the bundled code/reference bytes, exact
fixture/question identities, historical provider publication, experiment UUID,
48-attempt maximum, sequential execution, 120-second deadline, zero retries and
no fallback. Runtime credentials are neither requested nor read.

## Shared-adapter path

The path is runner → `EnergyPanelAdapter.review_jev_evaluation_case` → pinned
`AsyncPanelClient.review_energy_jev_case` → `httpx.MockTransport` → owned child
pipes. SDK request serialization and receipt validation execute normally. The
offline SDK subclass overrides only construction so it never creates a socket
transport; proxy inheritance and redirects are disabled. It accepts exactly one
fixed mock evaluation route, with no discovery, health or provider route.

Seven SDK module files are checked against the canonical source digest from
published commit `3d194368db297e33049b414c4cae345e632e5dbb`:
`d7e595e586ba589e4b026faaf9e7efbadc097932c5c887a56040263144adb3fa`.
This is code identity, not live provider identity or permission.

An internal adapter instance is enabled solely for this mock call path. It uses
an injected mock-only factory and no key file is read. Application configuration,
environment flags and the normal live client factory remain untouched.

The mock wire response supplies the published validator's required
`cloud_evaluation` enum and fixed model/policy fields. These are synthetic wire
constants, not a claim that cloud execution happened. Saved receipts are projected
back to `offline_simulation`; reports retain `live_calls=0`, unknown actual cost
and `production_activation=NOT AUTHORISED`. Unexpected child modes are rejected
before this conversion. Unknown outcomes still stop the run and retain their
reservation.

Exit zero means the synthetic lifecycle completed with cleanup and ledger
reconciliation. Exit two means refusal, partial execution or incomplete cleanup.
Keyboard interruption returns 130 after bounded cleanup. These outcomes never
authorize production activation.

## Durable evidence and ownership

The registry gets one exclusively created subdirectory per experiment UUID.
Creation is atomic. An existing directory is refused even if it has no checkpoint,
so concurrent callers, interruption and partial runs cannot silently restart.
Keep the same registry intact; this local protection cannot prevent an operator
from deleting it or deliberately selecting a different registry. No registry
entries are automatically pruned or overwritten by a new run.

Each experiment retains:

- `state.json`: bounded metadata and per-case progress, atomically replaced after
  file flush/fsync. A `.partial` file can remain after a failed write.
- `synthetic-ledger.sqlite3`: run-owned attempt records and an ephemeral synthetic
  grant digest/revocation marker. No production schema or URL is involved.
- `worker.py`: the copied, source-bound offline worker. The child has no socket
  interface and receives only case/correlation IDs through private pipes.

The worker deliberately returns `needs_review` for every case. It does not run
a model, consult expected labels or estimate model confidence. Every receipt is
labelled `offline_simulation`; reported usage and actual cost remain unknown.
The ephemeral nonce travels only through pipes, not argv, environment or files.
The child inherits only minimal operating-system environment fields, excluding
HA, database, provider and SDK credentials.

## Safeguards exercised

A synthetic full-context reservation of USD 0.002688 is committed before each
submission, following the historical published policy. The ledger and checkpoint
initially mark that attempt `unknown`. No reservation is released, even after a
completed synthetic receipt. Admission stops before exceeding the manifest cap;
the 48-case bound is USD 0.129024. These are simulated historical-policy amounts,
not current provider billing verification or actual expenditure.

The runner bounds each exchange by eight seconds and remaining batch time,
validates correlation IDs, unique event/request IDs and finite typed answers,
and stops at the first malformed, failed or uncertain outcome. It never retries,
resumes, falls back or invents a successful result for an uncertain attempt.

Cleanup revokes the synthetic grant, compares ordered ledger records with saved
results and terminates/waits for its owned child. A child handle is retained as
soon as spawn succeeds, including startup acknowledgement failure. Startup and
final cleanup are shielded against repeated cancellation. Termination escalates
to killing only that owned child after a bounded wait. Cleanup errors remain
visible and prevent a completed status; exception text is not persisted.

Partial states can be supplied to `tools.compare_jev`. Unknown attempts remain
unknown and unscored; rehearsal reports propagate `simulation_only=true`.
`production_activation` always remains `NOT AUTHORISED`.

## Isolated Panel/PostgreSQL lifecycle

`python -m tools.jev_panel_rehearsal --image <local-test-image> --registry
<new-or-existing-evidence-directory> --experiment-id <new-UUID>` runs the separate
`offline_panel_postgres` transport. Add `--fail-provider` to rehearse a fixed
provider timeout. Neither option can select a live service or provider response.
An experiment directory is claimed before Docker operations; reuse is refused.

The launcher creates a PostgreSQL 17 container with `--network none`, tmpfs data
and no published ports. The runtime shares only that container's network namespace,
has a read-only root filesystem, no capabilities, no Docker socket, and mounts
only this Python package read-only plus its newly claimed evidence directory.
It checks ownership labels and network settings before starting or deleting each
resource. Container names are recorded before creation, allowing cleanup after
an interrupted create. A failed identity check prevents deletion and records
`cleanup_incomplete`; it never cleans up unrelated containers.

Inside the namespace, a loopback-only interface check and exact Panel/SDK source
fingerprints run before database access. The generated role can address only
the fixed loopback test database; inherited database/HA/live approval configuration
is refused. Nonempty databases are refused, never reset. Trust authentication is
restricted to this disposable, unpublished namespace. No real credentials enter it.

The actual pinned Panel evaluation app applies its migrations, holds its exclusive
database lock, enforces ordered claims and calls its real admission/settlement
ledger. A narrow test wrapper replaces its **live approval reader** with the
runner's exact offline manifest approval and replaces **provider_call** with fixed
typed responses. The generated approval says `APPROVE_OFFLINE_JEV_REHEARSAL`;
no live approval or verified-billing assertion is created. An encrypted fixture
credential and temporary test-only grant exist only in this disposable database.

The runner owns the Panel subprocess and uses the actual shared adapter and SDK
over loopback HTTP. Cleanup checks the PostgreSQL event/request identities, typed
answers, reservations, unknown costs, schema versions and absence of extra requests.
It verifies duplicate rejection, revokes the temporary grant, verifies HTTP 403,
closes its connection and stops the owned process. The host then removes only its
labelled containers. Sanitized PostgreSQL ledger evidence survives in `lifecycle.json`
and the runner checkpoint; the database and fixture secrets are destroyed.

Successful mock answers retain unknown usage and cost. Consequently Panel request
settlement remains `incomplete` even when evaluation answers are `completed`.
This is expected; synthetic reservations are retained. A timeout stops after one
unknown runner attempt, with no retry or fallback. The outer lifecycle can report
`completed` for a successfully verified timeout scenario; inspect `runner.status`
to distinguish that `partial` experiment from a completed 48-case batch.

To build a test image, export `apps/api`, `services/system_one` and
`packages/client-python` from Panel commit
`3d194368db297e33049b414c4cae345e632e5dbb` into a new build context. Add a locally
built Energy wheel under `wheels/`, and build using
`tools/jev-panel-rehearsal.Dockerfile`. Do not copy a provider working directory,
runtime bundle, `.env`, secrets or production data. Dependency installation occurs
only at build time; every rehearsal runs without external networking.

## What this does not establish

The published provider protocol at commit
`3d194368db297e33049b414c4cae345e632e5dbb` requires a separately verified provider,
current full-context billing evidence, exact paid-run approval, an exclusively
owned disposable PostgreSQL instance, real test-grant issuance/revocation and
independent provider-ledger reconciliation. The isolated mode rehearses local
database ownership, grants and ledger mechanics using fixtures; it does not
establish live provider compatibility, billing, spend or model quality.
No live backend is shipped here, and no paid approval file was created.

The filesystem checks cover ordinary process failure/interruption and atomic
same-registry claims, not arbitrary operator deletion, hostile local mutation
or a storage device's power-loss guarantees. The prior Jev adapter and default
disabled App configuration are unchanged. The earlier failed model quality gate
remains failed.

See [validation receipts](../Testing/jev_runner_reconciliation_20261031.md).
For the shared-adapter increment, see
[wiring validation](../Testing/jev_runner_adapter_wiring_20261031.md).
