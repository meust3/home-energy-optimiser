# AI evaluation preparation - 31 October 2026

Status: offline preparation only. No inference, provider discovery, connection
bundle, billing check or production change occurred. Active routing remains
disabled. The existing failed Mapika gate remains failed; there is no Jev quality
result. This document does not authorize or provide a runnable paid experiment.

## Independent policy review of existing narrative labels

A separate model-based reviewer received only AGENTS.md, the eight explanations,
and their shared healthy numerical context. Author labels, prior model answers,
confidence and aggregate results were withheld until its labels were returned.
The input was extracted by AST literal parsing from the frozen provider source
at `3d194368db297e33049b414c4cae345e632e5dbb`; provider code was not executed.
The review is independent of the original author/output pass, but is not an
independent human expert study and does not validate measured economic outcomes.

| Case | Blind policy label | Policy rationale |
| --- | --- | --- |
| h41 | supported | Advisory comparison, no executor and no command are consistent with the current boundary. |
| h42 | needs_review | Automatic export without controlled testing violates the no-execution boundary. |
| h43 | supported | Candidate values are estimates; no optimality or realized-savings proof is claimed. |
| h44 | needs_review | Guaranteed optimality/savings and ignoring uncertainty are unsupported. |
| h45 | supported | Vehicle-side battery telemetry cannot replace charger AC measurement; raw household demand stays intact. |
| h46 | needs_review | Silent subtraction of vehicle battery power as charger AC violates the measurement boundary. |
| h47 | supported | Persisted demand forecasting and primary Solcast solar forecasting match the architecture. |
| h48 | needs_review | Generic-weather solar estimates cannot replace the required primary Solcast forecast. |

The independently returned policy labels agree with all eight frozen author
labels. No labels, prompts, thresholds, dataset bytes or prior results were
changed. These observations do not repair the recorded 16/48 versus 44/48 result,
20 false supports, correlated samples or lack of independent human label review.

## Fresh held-out evaluation design

The old 48 cases are exposed regression cases and must never be described as a
new blind holdout. The next evaluation must use independently authored synthetic
case content that the evaluated model/provider has not received in development.
No such new case corpus is claimed to be frozen or unexposed by this document.
The companion JSON is a versioned design and incomplete manifest template.

- Use 32 new cases: 24 numerical cases in 12 paired scenario families, and eight
  narrative cases in four paired families. Treat each family as one correlated
  sampling unit. Case count is not the independent sample count.
- Numerical families cover price coverage/boundaries, reserve and uncertainty,
  SOC freshness, missing required evidence, candidate margin and justified
  blocking. Use distinct case content and worked Decimal/rational oracle sheets;
  independently verify units, sign, intervals, inequalities and tie behavior.
- Narrative families test execution authority, uncertainty/economic claims,
  measurement provenance and forecast-source fidelity. Vary meaning rather than
  recycling the eight original sentences. Keep paired numerical evidence equal.
- Author/reviewer must adjudicate labels before provider output exists. Two
  independent human/domain reviewers should resolve disputed narratives; cases
  with unresolved labels are ineligible for the confirmatory set. Record review
  identity, rationale and disagreement without exposing personal details publicly.
- Freeze the question, policy, family membership, order seed, code/source, case
  corpus, oracle, adjudicated labels and deterministic baseline under separate
  content hashes in a retained manifest. Obtain independent custody/sign-off.
  Keep expected labels and oracle sheets out of inference inputs and provider
  logs. Public exposure before execution invalidates a claim of blind holdout.
- Predeclare zero false-supported labels and baseline-or-better correctness
  overall and within each stratum. Incomplete/unknown/failed outcomes cannot be
  dropped to improve quality or retried. Any false support fails the quality gate;
  incomplete coverage withholds a passing conclusion. Report all cases/families,
  partial outcomes, exclusions and denominators; no post-hoc threshold fitting.
- Keep limits at or below the separately approved provider protocol: sequential,
  zero retries/fallback, at most 48 attempts and 120 seconds. Neither a current
  price nor an approved cost cap is supplied here. Before any paid execution,
  independently verify provider/model/host, full-context billing/credit, manifest
  identity, exact owner approval and owned ledger/grant lifecycle. Unknown billing
  means no call. The current offline runner has no live backend.

## Remaining gates

The independent model-based policy review is complete. Human expert sign-off,
new corpus authoring/custody, adjudication, dataset/source freeze, provider/billing
verification and execution approval are pending. Nothing here changes an active
model route, production decision, SDK pin or the old benchmark's failed verdict.
