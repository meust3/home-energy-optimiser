# Remaining work after v0.8.6 - 31 October 2026

Review baseline: refreshed `origin/main` at
`2fe5e3a360411cac6e752f8e94b756f94666825a`, after acceptance-report PR #23.
The deployed release remains the earlier v0.8.6 tag; the documentation merge is
not another deployment. This review made no production or provider requests.

## Decision

No further wholesale implementation merge is recommended. The remaining dirty
Jev/SEMS files are preserved original candidates, superseded by the reconciled
implementations. The next substantive increment should protect historical replay
from later SEMS eligibility annotations, using synthetic offline fixtures. Follow
with independent evaluation-label review and a fresh held-out evaluation design
before considering any separately authorized Jev execution.

## Ref and worktree inventory

Fetched remote refs without pruning, branch switching or changing working files.
Inspected 43 local refs, 31 remote refs including the HEAD alias, and all 10
registered worktrees. Only these two unique branch tips have commits outside
current main's ancestry:

| Ref / candidate | Finding | Action |
| --- | --- | --- |
| `codex/data-quality-fixes`, `7eddcd2` | Reconciled by `94c333d`; actual-evidence/diagnostic/interval modules and their focused files match main. Newer scoring and transaction fixes must remain. | Preserve as provenance; do not merge again. |
| `feature/v0.5.0-preintegration`, `92e1b4a` | Old preservation commit. Forecast functionality was integrated through `533c911` / `eef729e` and subsequently evolved; the original whole commit is not patch-identical. | Preserve; no wholesale merge. |
| All other local and fetched branch tips | Ancestors of main, including SEMS, optional AI, Jev SDK/runner/wiring/Panel lifecycle, capture, advisory inputs, arbitrage and releases. | No missing branch implementation to integrate. |
| Draft [PR #10](https://github.com/meust3/home-energy-optimiser/pull/10) | Synthetic review tip is included in main. | Recommend closing as superseded, with reconciliation references; preserve branch/worktree. |
| Draft [PR #11](https://github.com/meust3/home-energy-optimiser/pull/11) | Data-quality work was reconciled through a newer implementation. | Recommend closing as superseded rather than merging its stale patch. |

The two draft PRs are the complete currently open PR inventory. Neither was
closed or edited during this review. The previous report's conditional v0.6.3
acceptance-document candidate was subsequently reconciled by `afd73ee`; it is no
longer pending. Its original dirty copy remains preserved.

## Standards

Independent source review found no residual safe implementation port in the seven
original Jev/SEMS files. These are restoration regressions, not newly enabled
defects in main:

1. Original Jev `src/energy_optimizer/ai_panel.py:104` fabricates SDK 1.0.1 for
   unknown checks; main retains nullable diagnostic evidence.
2. Its `ai_panel.py:359` imports the optional SDK before policy/failure handling;
   original `jev_evaluation.py:73` also makes offline comparison SDK-dependent.
   Main has graceful optional handling and an SDK-free comparison.
3. Original `jev_evaluation.py:100,119-123` includes failed-answer confidence in
   incorrect-answer statistics. Main excludes confidence unless completed.
4. Old SEMS `tools/probe_sems_hca_cloud.py:592-594,617-623,701-721` substitutes
   zero power or infers operational semantics from unvalidated status/units.
5. Its `:604-605,695-698` treats future timestamps as fresh by clamping age.
6. Its `:331-780` concentrates reusable transport/authentication/parsing in a CLI,
   contrary to the repository's reusable-code-under-src rule.
7. Its `:364-371,783-787` loses disabled redirects and explicit live opt-in.

Main's successors retain the safer boundaries. No additional actionable smell
finding was identified beyond the explicit CLI concentration rule. Standards:
seven restoration-regression findings; request safeguards are the principal
safety concern. None justifies porting the old code.

## Spec

Independent specification review confirms the older incomplete-owned-runner
finding is superseded for offline rehearsal:

- **Jev lifecycle is reconciled offline.** `jev_runner.py:130-167` binds manifest,
  source and SDK identities; `jev_panel_rehearsal.py:56-80` checks pinned Panel
  source. The lifecycle receipt records disposable PostgreSQL reconciliation,
  duplicate rejection, grant revocation/403, process/container cleanup and unknown
  timeout handling (`jev_panel_lifecycle_20261031.md:30-43`).
- **Paid-run evidence remains intentionally absent.** The runner guide
  (`jev-offline-runner.md:192-199`) requires a separately verified provider,
  current full-context billing evidence, exact approval and independent ledger
  reconciliation: "No live backend is shipped here." The pinned provider
  protocol likewise says "Unknown billing means no approval and no call."
  These are future execution gates, not missing mock-runner functionality.
- **SEMS semantics remain unvalidated.** The discovery report
  (`sems_hca_readonly_20261011.md:58-61,76-80`) leaves authentication, AC measurement
  domain, state meanings, cadence and freshness unconfirmed. The context report
  (`sems_forecast_context_20261011.md:72-96,152-157`) records source-timestamp/sign
  loss and missing explicit charger/BYD precedence. Timezone qualification was
  subsequently resolved; it is not an outstanding finding.
- **Historical eligibility is not reconstructed automatically.** The backfill
  report (`sems_reversible_backfill_20261011.md:77-82`) explicitly requires
  immutable populations or audit/knowledge-time-aware replay. Its production
  sequence still requires independent review, fresh conflict checks, a recovery
  backup and separately authorized maintenance (`:108-125`). Reversibility alone
  does not establish factual eligibility or authorize the historical 54-row plan.

Spec: four status/gate conclusions above, no newly identified offline-runner
implementation defect. Historical eligibility and SEMS measurement semantics
remain the main evidence gaps in that area. The old AI quality failure and
independent-label gap also remain; neither has been retested in this review.

## Recommended sequence

1. **Resolve stale PR status without deleting work.** Close #10/#11 as superseded
   when authorized, linking the reconciliation commits and PR #21. This is an
   administrative follow-up, not a code merge or production change.
2. **Protect SEMS historical replay offline.** Define a separate knowledge-time
   contract or require immutable original populations. Current
   `db/repository.py:259-290` filters current `baseline_training_eligible`; its
   `as_of` wrapper limits observation time, not when annotation facts became
   known. Use synthetic SQLite and exclusively owned PostgreSQL fixtures to
   demonstrate that an annotation learned after decision time cannot change
   that decision's historical inputs. Include apply/reverse and later-annotation
   cases; refuse replay where historical eligibility cannot be reconstructed.
   Keep operational collection/training behavior unchanged in this increment.
3. **Prepare stronger AI evidence offline.** Independently review the eight
   narrative labels, preserve the exposed 48-case benchmark as regression evidence,
   and design a new held-out set with labels/gates frozen before any model run.
   The recorded Mapika result remains 16/48 versus baseline 44/48 with 20 false
   supports; the quality gate failed. It is not a Jev result. Do not tune labels
   to those outputs or treat mocked `needs_review` replies as model performance.
4. **Keep SEMS backfill and live Jev as separate gated decisions.** Historical
   session windows do not prove continuous charging, charger AC power or facts
   known at earlier decisions. The historical 54-row proposal remains unapproved;
   this review did not query its current production rows. Jev needs independently
   verified provider/billing evidence and exact bounded execution authorization;
   no live backend or paid approval is supplied by the offline rehearsals.

The first substantive development recommendation is item 2. There is no missing
offline Jev runner to rebuild. No production deployment is required by this review.

## Preservation and validation limits

All seven Jev/SEMS originals still match the retained SHA-256 records. Both
pre-existing untracked review reports retain their prior hashes. The original
consumer worktree still contains its AI/solar/acceptance edits and private local
directories; no files there were staged, overwritten or archived. Other registered
worktrees were clean by tracked/untracked filename inventory. Private ignored
directories were not recursively inspected or published.

No tests, submission CLI, SEMS probe, rehearsal, inference or live observation
were executed for this source/inventory review. Existing test receipts remain
historical evidence, including v0.8.6 acceptance and its CI. This new uncommitted
report is the only working-file addition. No branch deletion, merge, push,
production access, migration, integration activation or hardware action occurred.
