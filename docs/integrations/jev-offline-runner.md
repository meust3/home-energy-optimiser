# Jev experiment lifecycle: offline rehearsal

This runner exercises experiment safeguards using a real owned local child and
a synthetic SQLite ledger. It has **no live mode**, provider adapter, URL option,
production database connection, inference request or hardware path. It needs no
Panel SDK. Its result is lifecycle evidence, not Jev performance or paid-run
readiness.

## Running a rehearsal

From an installed development checkout, prepare a manifest with a fresh UUID:

```powershell
python -m tools.jev_rehearsal prepare --experiment-id <UUID> --output <manifest.json>
```

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

## What this does not establish

The published provider protocol at commit
`3d194368db297e33049b414c4cae345e632e5dbb` requires a separately verified provider,
current full-context billing evidence, exact paid-run approval, an exclusively
owned disposable PostgreSQL instance, real test-grant issuance/revocation and
independent provider-ledger reconciliation. None is replaced by this simulator.
No live backend is shipped here, and no paid approval file was created.

The filesystem checks cover ordinary process failure/interruption and atomic
same-registry claims, not arbitrary operator deletion, hostile local mutation
or a storage device's power-loss guarantees. The prior Jev adapter and default
disabled App configuration are unchanged. The earlier failed model quality gate
remains failed.

See [validation receipts](../Testing/jev_runner_reconciliation_20261031.md).
