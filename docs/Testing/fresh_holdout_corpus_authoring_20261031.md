# Fresh synthetic holdout authoring - 31 October 2026

Status: **candidate authored and prepared for independent label review**.
No human label adjudication, model/provider submission, confirmatory freeze,
execution approval or production activation is claimed.

This report records the authoring stage. The subsequent
[blind model review](fresh_holdout_blind_model_review_20261031.md) records later
reviewer exposure and results. Preservation statements below describe that stage,
before the separate authorization to publish these two reports only. Private
case content and labels remain excluded from publication.

This follows the 32-case [design](../integrations/ai-next-holdout-design-20261031.json)
and [review preparation](../integrations/ai-evaluation-preparation-20261031.md).
Those files record the earlier design stage and are preserved without edits.
The application baseline is merged main `5340020`; no application source,
provider task, runner contract or runtime configuration was modified.

## Private review handover

Current handover directory, relative to this checkout:
`.local/holdout-authoring-20261031/candidate-v3/`.
All case content, provisional labels and supporting files remain ignored/local.
Do not commit or publicly upload the corpus, question or review ZIP.

| Artifact | Purpose |
| --- | --- |
| `independent-review-packet.zip` | Share only with separately authorized reviewers through a private channel; no author answers. No sharing occurred in this task. |
| `reviewer/corpus.json` | 32 synthetic advisory inputs in shuffled order with neutral case IDs. |
| `reviewer/question-and-policy.json` | Proposed review question, explicit label semantics, units, precedence and tie rules. This is not a published provider task. |
| `reviewer/review-A-blank.json`, `reviewer/review-B-blank.json` | Two independent blank review forms bound to corpus/question hashes. |
| `reviewer/REVIEW.md`, `reviewer/manifest.json` | Reviewer instructions and per-file integrity hashes. |
| `author-only/provisional-labels-and-oracles.json` | Author's provisional labels, family membership and worked reasoning; withhold until reviews are sealed. |
| `author-only/deterministic-baseline.json` | Proposed reference outputs, not model execution or quality evidence. |
| `author-only/authoring-source.py`, `author-only/family-and-order.json` | Retained construction source and ordering/family provenance; not reviewer inputs. |
| `candidate-manifest.json` | Hashes, authoring status, disclosure of author-model exposure and explicit disabled execution gates. |

SHA-256 anchors for the current review candidate:

- Corpus: `a1dc3714dff7fd84e200d0e925b0b29c4c23cd7dfe234e1b4c0d3beab056f8fb`.
- Review ZIP: `f342daa1907780d34381372c0cdc83794c7cfe0d6c285a59684b4f8922586ef4`.
- Candidate manifest: `a211fd91d8806c717d94e4181b07d46945c6b324a92b2ee2d442cba778eec98b`.

## Corpus scope and checks

There are 24 numerical cases in 12 paired families and eight narratives in four
paired families: 16 designed, correlated family units, not 32 independent random
samples. Numerical families cover SOC freshness, import/export coverage boundaries,
present-zero versus missing evidence, reserve equality/shortfall, efficiency,
low-solar reserve, net margin, comparison uncertainty, justified blocking and
power/energy integration. Narrative pairs cover authority, economic claims,
measurement domains and forecast-source fidelity. New wording is used; none of
the eight old narrative sentences is copied verbatim.

The question explicitly defines inclusive freshness/reserve/margin checks, strict
advantage over comparison uncertainty, half-open continuous price windows and
required-evidence precedence. Missing values remain unknown. The task reviews a
precomputed advisory under a proposed policy; it does not optimize dispatch or
authorize hardware execution. Historical meter-integration evidence is labelled
as separate from forecast demand and proposed battery export. Optional vehicle
and charger telemetry domains are explicit.

Local standard-library validation passed:

- 24 numerical provisional labels cross-checked by a second implementation using
  Decimal cross-multiplication rather than the author's Fraction/division path.
  This is a local arithmetic check, not independent human/domain verification.
- All 32 case states are distinct; exactly two cases belong to each of 16
  families. All four narrative pairs have identical numerical context.
- Complete non-BLOCKED projections satisfy a basic supplied-energy plausibility
  bound. This is not a battery-trajectory simulation or proof of optimal dispatch.
- All 11 retained file hashes match. ZIP entries match the reviewer directory
  exactly; author-only files, expected-label keys, family/stratum hints, worked
  oracle answers and baseline outputs are absent from that packet.
- Both forms contain all 32 neutral IDs with blank labels/rationales. No reviewer
  identity, agreement, expert sign-off or execution result was fabricated.

Receipts are retained at
`.local/holdout-authoring-20261031/candidate-v3-validation.json`.
Earlier candidates v1/v2 and their source/receipts remain intact. Revisions
clarified projection/meter-trace context and version wording before handover;
none followed model evaluation results, and none was submitted to a provider.

## Independent review and remaining gates

Give the answer-free packet to two independent human/domain reviewers, each using
their own form. They should work without the author labels, old model outputs or
one another's answers; record an alias, independence/domain status, rationale and
ambiguity for every case. Abstention is allowed. Return each completed form as a
new file with a separate digest, preserving the originals. No reviewer outreach
or transmission was performed here.

After both submissions are sealed, independently adjudicate disagreements and
record policy/case changes as a new candidate version. Unresolved labels cannot
enter a confirmatory evaluation silently. Review the numerical workings as well
as narrative claims; author-proposed labels are not gold labels.

The content is exposed to its AI author. Exposure to a future evaluated provider
is **unverified**; this workflow made zero provider submissions, but that alone
cannot certify an untouched holdout. These private bytes are hash-identified for
review, not a final confirmatory freeze or an execution approval. Independent
custody, exposure review, adjudicated-label/question/oracle/baseline/source hashes,
final order, provider/task compatibility, billing checks and exact execution
approval remain required. The existing runner cannot submit this new corpus.
The old 48-case benchmark and its failed quality verdict remain unchanged.

## Preservation

All pre-existing work is preserved. The seven original Jev/SEMS files and three
earlier untracked review reports match their retained hashes. The old holdout
results, reference metadata and design bytes were not modified. No staging,
commit, push, deployment, live integration, production database, hardware,
retention or SDK/environment change occurred. Only private authoring/review
artifacts and this new uncommitted handover report were added.
