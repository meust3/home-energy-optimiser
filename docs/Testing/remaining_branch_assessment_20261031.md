# Remaining branches and SEMS WIP assessment — 31 October 2026

Baseline: local `main` at `eaf9d6840ea4635ec6c820a7d4128303ee151291`,
20 commits ahead of cached `origin/main`. This is an offline review of local Git
objects and working files. No fetch or remote freshness claim is made.

## Reconciliation decision

No further implementation merge is recommended from the remaining branches or
old SEMS files. Preserve every branch/worktree and original uncommitted file.
One uncommitted historical acceptance-document update is a separate conditional
documentation candidate, not a reason to merge its old source worktree.

| Remaining work | Assessment | Recommended action |
| --- | --- | --- |
| `codex/data-quality-fixes`, `7eddcd2` | One commit absent by ancestry, but explicitly reconciled by `94c333d`. Shared actual-evidence, collection diagnostics, interval review, their focused tests and CLI match main; scoring integration deliberately retains main's newer inventory and transaction behavior. | Keep the branch as provenance. Do not merge or cherry-pick the older implementation again. |
| `feature/v0.5.0-preintegration`, `92e1b4a` | Old preservation commit, not missing forecast functionality. Accepted ancestor `533c911`, followed by release integration `eef729e`, includes its forecast engine, forecast tests, ORM models and forecast/reserve migration unchanged, alongside subsequent fixes. The overall commits are not patch-identical. | Preserve; no wholesale merge. |
| Other local branch tips | Already ancestors of main, including SEMS, AI review/consumer, Jev increments, forecast context, advisory inputs, capture, SOC freshness, arbitrage and historical releases. | No implementation merge remains. Do not delete branches or worktrees in this review. |
| Untracked old SEMS probe/tests | Superseded by main's reusable diagnostic and safer CLI. Both original hashes still match the previous preservation record. | Preserve as recovery material; do not restore unsupported normalization or its tests. |
| Original dirty Jev worktree | Same five preserved WIP files; the accepted offline comparison, SDK 1.0.4 adapter and mock-only runner increments now exist on main. | Do not overlay the stale files or restore the old submission CLI as a live runner. |
| Original AI/solar consumer worktree | Solar modules, replay CLI/tests and solar guide match main. Added solar model/parser definitions are AST-identical. AI pilot tests/guide match; older adapter/replay files would lose holdout/Jev support and restore fixed diagnostic/version and CLI defects. | Preserve; no code port required. Keep main's SDK 1.0.4 and diagnostic fixes. |
| Dirty `docs/Testing/v063_production_acceptance_20260927.md` in the original consumer worktree | Contains a unique historical follow-up: scheduled-cycle results, qualified 48-hour assessment, monitoring coverage gap and later scoring cancellation. These claims are absent from main's earlier document. | Conditional documentation-only candidate. Verify the exact dated local receipts, repair the malformed heading encoding, and retain the monitoring-gap/timeout qualifications. Do not treat historical claims as current production acceptance. |
| Private `.local/`, `data/`, `.agents/`, and `skills-lock.json` in the original consumer worktree | Local research/configuration/tooling inventory, not established merge candidates. Contents were not swept into this review or an archive. | Preserve and exclude from bulk staging. |

Inventory: **39 local branch refs**; only the first two above have commits outside
main's ancestry. **26 cached remote refs**, including the remote HEAD alias, show
the same two unmatched commits. All 14 registered worktrees were checked for
dirty/untracked filenames. Clean worktrees were not switched or modified.

The existing `remaining_wip_review_20261031.md` is an earlier snapshot at
`11d1bc7`. Its Jev recommendations are now historical, addressed by subsequent
increments; its SEMS cautions remain valid. It was preserved without edits.

## Standards

Independent standards review compared the original SEMS WIP directly with fixed
main, using `AGENTS.md` and the accepted SEMS discovery handover. References below
are to the old untracked `tools/probe_sems_hca_cloud.py`, not main.

1. **Reusable-code rule violated:** lines 331–780 put transport, authentication,
   discovery and normalization in the CLI. Main already puts reusable logic in
   `src/energy_optimizer/sems_probe.py`.
2. **Unknown values replaced with assumptions:** lines 592–594 and 709–721 force
   power to zero for unvalidated non-6 status codes and present assumed units.
   Main preserves raw evidence and leaves operational power/status unknown.
3. **Future timestamps treated as fresh:** lines 604–605 clamp their age to zero;
   lines 695–698 then classify them as not stale. Main preserves future timing.
4. **Redirect protection lost:** lines 364–371 omit `allow_redirects=False`,
   allowing the transport to leave its inspected endpoint. Main disables redirects.
5. **Manual live opt-in lost:** lines 783–787 run from credentials without
   `--allow-live`. Main requires explicit opt-in before creating the probe.

Judgment call: `_normalize` at lines 565–763 combines extraction, interpretation
and presentation. This adds no reason to restore the old code or create another
abstraction; main's evidence summarizer already separates these concerns.

No validated capability missing from main was identified. The original raw
charge-mode fields are omitted from main, but no accepted requirement establishes
them as a useful addition; control metadata must not be reintroduced by default.

## Spec

Independent specification review identified five candidate regressions:

1. **P1 — explicit opt-in absent.** Discovery handover lines 69–71 requires a
   CLI with explicit `--allow-live`; candidate lines 783–787 omit it.
2. **P1 — redirect escape.** Handover lines 66–68 requires exact endpoint/method
   allowlisting and disabled redirects; candidate lines 364–371 omit the latter.
3. **P1 — unverified operational values.** Handover lines 76–80 says values are
   never forced to zero and normalized power remains unvalidated. Candidate
   lines 592–594, 617–623 and 701–714 infer power/status/connection. Old tests
   174–216 assert these unsupported semantics; their passing result is not acceptance.
4. **P2 — invalid freshness inference.** Handover lines 78–79 requires unknown
   freshness for naive/numeric timestamps and excludes future timestamps from
   freshness. Candidate lines 246–249 and 604–605 violate this distinction.
5. **P2 — CLI concentration.** `AGENTS.md` requires reusable logic under `src/`;
   candidate lines 331–780 retain it in `tools/`.

Main already has the safer successor. These are findings against restoring the
candidate, not new findings that main has enabled unsafe execution.

## Backfill and runtime boundary

The SEMS branch `76e617c` and its analytical backfill tooling are already included
in main. That does not approve the historical 54-row eligibility change. The
current handover still requires independent review, fresh conflict checks,
recovery backup and separately authorized maintenance. It also explicitly says
mutable-history queries do not reconstruct pre-backfill eligibility automatically.

Recorded session windows do not prove continuous charging, measured charger AC
power or contemporaneous knowledge. Do not distribute session energy into samples,
replace BYD/raw power, apply exclusions, or change frozen historical populations
as part of branch reconciliation. Source authentication and telemetry semantics
remain a separate evidence task requiring explicit authority for any live work.

## Offline validation and preservation

- Current SEMS probe/history/backfill suite: **92 passed, 11 skipped**. The skips
  require a separately owned PostgreSQL instance; none was connected in this review.
- Original two-file SEMS snapshot: **24 passed**. Passing tests include the
  unsupported normalization assumptions described above.
- Both used disposable containers with `--network none`, read-only source mounts,
  no runtime bundles and synthetic fixtures. No probe CLI or live endpoint ran.
- All seven preserved original Jev/SEMS files matched their prior SHA-256 records.
  Old SEMS probe: `947b0e5ef14187c698483d2a15cb02f39959fc18792e62a3969cce3c9acbe735`.
  Old SEMS tests: `552c126e66338da3e94e8cc159ddc76e47893784070c92720241792ba7931749`.
- No source changes, staging, commits, merges, branch deletion, push, production
  access or integration activation occurred. This new report is the only repository
  addition. Historical/private acceptance receipts were not revalidated.

Standards: five actionable candidate findings plus one focus-related judgment
call; the redirect regression is a principal safety concern. Spec: five findings;
missing explicit opt-in, redirects and fabricated telemetry are P1 blockers.
