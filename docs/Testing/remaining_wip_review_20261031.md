# Remaining Jev and SEMS work review — 2026-10-31

## Decision

Do not merge either remaining worktree wholesale.

| Work | Reconciliation assessment |
| --- | --- |
| Old untracked SEMS probe and tests | Superseded by main. Preserve the originals; no additional implementation needs merging. Do not restore their normalization, transport or CLI behavior. |
| Jev offline comparison and fake-adapter tests | Useful next increment, after making the optional-SDK test behavior explicit. Keep the frozen labels, raw answers, partial-run accounting and failed production-activation gate. |
| Jev SDK 1.0.4 adapter additions | Conditional: port the additive changes onto main, preserve nullable SDK evidence, repair missing-SDK handling and coordinate the exact SDK dependency/build pin. |
| Jev submission CLI and runner | Consumer component only. Not a complete experiment runner and not ready for live execution. Lifecycle, source/manifest verification and ledger reconciliation remain outstanding. |

No source code was changed, staged, committed or merged in this review. Local
main remains `11d1bc7`. This report is the only new repository file. No credentials
were loaded, no cloud/provider requests were sent, no production database was
connected, and no integrations were enabled.

## Sources and comparison method

- Baseline: local main `11d1bc7`, following SEMS/AI reconciliation.
- Jev: `codex/jev-energy-comparison` at `1a4634f`, plus its two modified files
  (`ai_panel.py`, `ai_review.py`) and three untracked evaluator/test/CLI files.
  The tracked patch was inspected with `git diff HEAD --` in that worktree;
  whole-file differences against main were also reviewed for lost fixes.
- SEMS: the two untracked `tools/probe_sems_hca_cloud.py` and
  `tests/test_probe_sems_hca_cloud.py` files in the preintegration worktree at
  `92e1b4a`. They were compared with main's reusable module, CLI and tests.
- Standards: `AGENTS.md`, including optional AI and read-only data rules.
- Specs: `docs/Testing/sems_hca_readonly_20261011.md`,
  `docs/integrations/ai-review-holdout-20261003.md` and
  `docs/integrations/ai-control-panel.md`.
- Exact Jev protocol: local provider Git commit
  `3d194368db297e33049b414c4cae345e632e5dbb`,
  `docs/integrations/energy-review-jev-evaluation.md` and
  `packages/client-python/panel_energy_challenger.py`. This is a historical
  published contract, not verification of a currently running provider.

Independent standards and specification reviews were performed under the
code-review skill. Findings below intentionally retain overlap between axes.
Line references refer to the original candidate files, not main.

## Standards

1. **P2 — preserve unknown SDK evidence.** Jev `ai_panel.py:104` defaults
   `sdk_version` to `1.0.1`; main uses `None`. The failure-report constructor does
   not supply a detected SDK version, so wholesale copying fabricates a version
   for disabled/unavailable checks. This violates the shared-integration rule to
   handle unknown, offline and disabled routes honestly. It is a main-relative
   regression, not a newly introduced WIP-versus-HEAD change.
2. **P2 — do not fabricate zero power.** Old SEMS CLI lines 592–594 replace
   reported power with zero for any integer `workStu != 6`. An undocumented code
   such as 99 therefore becomes available zero power. This violates the rule
   never to invent or silently replace unavailable data. Main preserves raw
   evidence and leaves operational power unknown.
3. **P2 — keep reusable logic under src.** Old SEMS CLI lines 331–778 contain
   transport, authentication, parsing and normalization. The coding standard
   requires CLI tools to call reusable code under `src/`. Main already provides
   that separation.
4. **P2 — do not restore redirect-enabled transport.** Old SEMS CLI lines
   364–372 leave Requests redirects enabled. A 307 can forward the POST body and
   custom token header beyond the inspected endpoint allowlist. Main disables
   redirects and rejects non-2xx responses. This is a concrete safety regression.

No additional actionable code-smell findings were identified beyond the CLI
concentration covered by the explicit standard.

## Spec

1. **Jev is not the required owned runner.** The provider protocol requires the
   runner to verify immutable source/manifest, reconcile test-ledger IDs, revoke
   the temporary key and stop its child. Candidate `tools/jev_evaluation.py:21–35`
   reads/hashes a manifest and submits through an existing endpoint. It does not
   implement that lifecycle or independent billing/source verification. Preserve
   it as a consumer component, not a live-run readiness claim. The protocol
   explicitly says publication does not permit inference.
2. **Preserve main's unknown SDK status.** Candidate `ai_panel.py:104` would undo
   main's nullable default and violate honest unavailable-state handling. Add
   `1.0.4` to the supported literals while retaining `| None = None`.
3. **Missing optional SDK bypasses the failure boundary.** Candidate
   `ai_panel.py:359` imports `panel_client` before `_execute`. SDK-free calls
   raise `ModuleNotFoundError`, including calls that should be policy-denied.
   Move import/version checks inside the established optional boundary and add
   SDK-absent coverage. The new test module also lacks optional-dependency
   handling and breaks the normal SDK-free test baseline.
4. **Old SEMS normalization contradicts the accepted evidence model.** Lines
   592–593 force power to zero and line 702 infers charging from status. The
   SEMS handover says normalized power remains unvalidated and values are never
   forced to zero. Main already preserves the raw value and unknown semantics.
5. **Old SEMS loses request safeguards.** Lines 363–371 omit disabled redirects;
   lines 783–787 execute from environment credentials without `--allow-live`.
   The accepted handover requires both safeguards. Main already implements them.

The SDK 1.0.4 receipt validator checks correlation, typed answers and completed
status. No separate duplicate-answer defect is claimed. Loopback-only transport
does not itself prove ownership of a test process; the full runner requirements
remain relevant even after the adapter fixes.

## Offline validation

All runs used disposable Docker containers with `--network none`, read-only
source mounts, synthetic fixtures and no runtime configuration bundles. The Jev
candidate snapshot consists of main's committed files with the five exact WIP
files overlaid in a temporary directory; originals were never edited. SDK 1.0.4
was read from the pinned provider Git archive, not fetched or run against a live
service. Import identity was verified as `1.0.4 /sdk/panel_client.py`.

| Check | Result |
| --- | --- |
| Candidate Jev tests plus main AI integration tests, installed SDK 1.0.3 | 29 passed, one failed: `test_disabled_manual_check_does_not_fabricate_sdk_evidence` |
| Candidate Jev tests with SDK removed inside disposable container | Seven failed: missing `panel_client` or `panel_energy_review_holdout` |
| Candidate Jev plus existing adapter/pilot/holdout tests, pinned SDK 1.0.4 | 62 passed |
| Old SEMS test suite against its original tool | 24 passed; this includes assertions for behavior rejected by the newer spec |
| Main's current SEMS probe tests | 62 passed |
| Ruff/Black on the three new Jev files | Passed |

The SDK 1.0.4 focused pass does not establish a green combined candidate: the
known main-relative diagnostic regression remains. No full application suite or
App rebuild was needed for this review-only assessment. The prior main receipts
remain separate; no claim is made that this WIP has passed them.

## Recommended reconciliation sequence

1. Keep the current SEMS implementation and preserve the two older untracked
   files as recovery material. There is no reason to replace main or merge old
   tests that require fabricated normalized values.
2. Prepare a small offline Jev comparison increment with deterministic fixtures,
   explicit optional-dependency test handling and no invocation of the submission
   CLI. Retain partial results, unknown usage/cost and no activation claims.
3. Port the Jev adapter method onto current main, retain the diagnostic fix, move
   SDK imports into graceful failure handling and test disabled/missing/wrong
   SDK cases. Main currently pins SDK 1.0.3; accepting 1.0.4 in a method is not a
   dependency upgrade. Coordinate the Python pin, SDK identity/status metadata,
   optional App wheel/version contract and both default/optional builds.
4. Treat the experiment runner as separate future work. Complete immutable
   manifest/source checks, owned-process lifecycle, ledger reconciliation and
   interruption cleanup offline before any separately authorized inference.

Standards: four findings, most consequential is the old SEMS redirect regression.
Spec: five findings, the main readiness gap is the incomplete owned Jev runner.

## Original WIP byte identities

SHA-256 was recorded before testing and checked again after review.

| Original file | SHA-256 |
| --- | --- |
| Jev `src/energy_optimizer/ai_panel.py` | `ac49d6938f17b1834b4f5057e25df08a4faad96aa1881182550261320ec648e0` |
| Jev `src/energy_optimizer/ai_review.py` | `5908e35fea53d0a03bd1b74aae099f5ac6751ba2db45d37970144d951431ef22` |
| Jev `src/energy_optimizer/jev_evaluation.py` | `138b98815187d2946d5d7da3a6910aa9e16a811aff9461865d06deb007a4c551` |
| Jev `tests/test_jev_evaluation.py` | `1b7a1de465435232602eacc9089c8d0224426b92aabba9402adeaf6b790efb04` |
| Jev `tools/jev_evaluation.py` | `84ce050469396aca93c243a283f53b020948956836c7b1e5dff05c04723043a4` |
| Old SEMS `tools/probe_sems_hca_cloud.py` | `947b0e5ef14187c698483d2a15cb02f39959fc18792e62a3969cce3c9acbe735` |
| Old SEMS `tests/test_probe_sems_hca_cloud.py` | `552c126e66338da3e94e8cc159ddc76e47893784070c92720241792ba7931749` |
