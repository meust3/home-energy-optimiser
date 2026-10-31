# Fresh holdout blind model label review - 31 October 2026

Status: **two procedurally blind model reviews completed; human/domain
adjudication remains pending**. No confirmatory eligibility or execution approval
is established. This follows the [private corpus handover](fresh_holdout_corpus_authoring_20261031.md).

This report records the completed local review stage. Preservation statements
below describe that stage, before the separate authorization to publish these
two reports only. Private case inputs, per-case answers and comparisons remain
excluded from publication.

## Scope and blinding

The owner authorized independent label review while preserving existing work and
disabled integrations. Two fresh-context Codex reviewers received separate copies
of the candidate-v3 corpus, proposed question/policy, instructions and their own
blank form. They received no author labels, baseline outputs, oracle workings,
family/stratum hints, prior model results, conversation history or other review.
Each was instructed to read only its own input directory, verify input hashes,
evaluate all cases independently, and save new exclusive submission/seal files.

The original packet's generic prohibition on sending cases to models was
superseded only for this explicitly authorized model-based label review. No
Energy/Panel/Jev inference route, provider SDK, live experiment, production
database or hardware interface was used. This is not a human expert review.

Blinding was procedural and scope-instructed within a shared filesystem, not an
OS-enforced access boundary. Fresh contexts do not establish independent model
errors or model-family diversity. Both reviewers disclosed these limitations.

## Sealed inputs and submissions

Corpus SHA-256:
`a1dc3714dff7fd84e200d0e925b0b29c4c23cd7dfe234e1b4c0d3beab056f8fb`.

Question/policy SHA-256:
`fcda5bf50089b7e10b11e58ddb88cfd536ab138eb9f1f38b9038c2a9fce63cb8`.

| Review | Submission SHA-256 | Coverage | Ambiguities / abstentions |
| --- | --- | --- | --- |
| A | `84e96342dbce7f1e6b9692746a2e4ce5c41df939ace7307dca0314f2e0dcfb0f` | 32/32 | 0 / 0 |
| B | `a9c910fdd63b65b91fe246c5f56a34913bcc7b39827bc1d81e41e447b88f87ad` | 32/32 | 0 / 0 |

Both submissions were sealed before opening their contents for comparison with
the author proposals. Read-back checks verified unique complete case IDs, valid
labels, case-specific rationales, ambiguity flags and matching input identities.
Reviewers used exact .NET Decimal arithmetic and cross-multiplied inequalities;
they assessed the literal proposed policy rather than inventing a new dispatch
optimization problem. No application calculation or provider task was invoked.

## Results and limits

- The reviewers agreed definitively on all 32 labels; zero unresolved label
  differences or case-level ambiguities were reported.
- Their consensus matches all 32 author proposals. Author labels, inputs,
  policies, baseline and oracle files were not modified. No labels were tuned to
  the review responses; no third-review tie-break was needed.
- This is model policy/arithmetic agreement on a small designed corpus, not
  accuracy against independent human gold labels. It establishes no real-world
  safety, physical-model completeness, calibration, economic benefit or Jev
  performance. The old benchmark's failed quality gate remains unchanged.
- There are 16 designed paired/correlated families, not 32 independent random
  observations. Shared model-family errors remain possible even with full agreement.
- The corpus is now exposed to the author and two Codex reviewer contexts. It
  cannot be called untouched for those review models. Exposure to any future
  evaluated provider remains unverified; no application-provider submission was made.

Human/domain review of label and policy validity, external custody/exposure
verification, final adjudicated-label/source/question/oracle/baseline freeze,
provider compatibility/billing and exact execution approval remain separate gates.
Every case remains `confirmatory_eligible=false`. The current runner has no
compatible published task for this corpus and live execution stays disabled.

## Private artifacts and preservation

All detailed case answers stay local under:
`.local/holdout-authoring-20261031/blind-review-20261031-v1/`.

- `reviewer-A/completed-review.json` and `reviewer-B/completed-review.json`:
  independent submissions; adjacent `review-receipt.json` files seal them.
- `sealed-review-comparison.json`: case-level comparison with author proposals;
  this is **unblinded material** and must not be supplied to future blind reviewers.
- `review-summary.json`: aggregate results, submission identities and limits.
- `review-authorization.json`: scope of the narrow model-review authorization.
- `preservation-before.json`: SHA-256 identities of 57 prior files.

For any future human blind review, use the unchanged original answer-free ZIP
and forms. Withhold these completed submissions, comparisons, author-only files
and this agreement summary until that review is sealed, to avoid anchoring.

All 57 pre-existing file hashes and both answer-free input copies were checked
unchanged. The original candidate-v1/v2/v3 artifacts and four previous untracked
reports remain intact. No files were staged, committed, pushed or deployed;
only new private review artifacts and this new uncommitted report were added.
Production, live integration settings, retention and existing SDK environments
were unchanged. No human reviewers were contacted.
