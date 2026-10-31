# Blind human holdout review and adjudication

Status: handover prepared; reviewers not appointed or contacted. No human review,
adjudication, confirmatory freeze or execution approval has occurred.

This procedure separates reviewer inputs from coordinator-only evidence. It
contains no case inputs or answers. Private material remains under the ignored
`.local/holdout-authoring-20261031/` directory; do not force-add it to Git.

## Roles and release of the handover

The owner appoints two independent human reviewers and a separate human
adjudicator. Reviewers must be independent of corpus construction and each other,
disclose conflicts and prior exposure, and be able to check exact numerical
reasoning and energy-domain assumptions. Collectively cover battery/reserve
accounting, tariff windows, uncertainty, telemetry provenance and advisory safety.
Record gaps in expertise; do not silently treat general review as domain sign-off.
The adjudicator must not be the corpus author or either first-pass reviewer.

The coordinator verifies the private bundle manifests, assigns slots A and B,
and records aliases, appointment, competence, conflicts and exposure declarations.
Real identities and contact details belong in a separately controlled owner
record, not Git. An alias does not itself prove identity or independence.

The prepared directory is
`.local/holdout-authoring-20261031/human-handover-20261031-v1/`.
Send only the assigned `reviewer-A.zip` or `reviewer-B.zip` through an
owner-approved private channel after authorization to contact/share is obtained.
Each contains the unchanged original answer-free packet and human instructions,
plus blank declaration, policy-validity and submission-seal forms. The original
packet contains both blank forms; the reviewer uses only the assigned one.
No outreach or transmission is authorized by this preparation procedure alone.

Never send the repository, author-only directory, source generator, baseline,
family mapping, completed model reviews, model agreement summary, coordinator
records or this procedure as the reviewer handover. Prior aggregate agreement
can anchor judgment even without per-case labels. Ask reviewers not to browse
project reports. Disclose that the synthetic candidate has had prior AI exposure,
without disclosing prior findings. Do not describe it as untouched.

## Independent review and sealing

1. Verify the assigned bundle SHA-256 against the separately supplied digest,
   then its manifest and the nested packet manifest. A mismatch stops review.
2. Complete the declaration before reviewing. Disclose prior labels, reports,
   author discussions, model outputs or case exposure. The coordinator records
   any compromise and appoints a replacement where blind review is required;
   retain the compromised review as explicitly unblinded evidence.
3. Work alone, offline, using a calculator or locally written arithmetic if
   needed. Do not upload cases to AI, search engines or cloud tools. Do not use
   the author's implementation. Record tools and any external references used.
4. Copy the assigned blank form to a new file. Assess every case under the
   literal proposed policy, giving a case-specific rationale and workings.
   Abstention is permitted: null label, ambiguous=true, with a reason. Use the
   policy's label vocabulary. Never edit original inputs or blank forms.
5. Separately complete the policy-validity review. A label consistent with a
   supplied rule does not validate that rule's physical or operational adequacy.
   Record missing assumptions, unsafe scope, ambiguity and expertise limits.
6. Address clarification requests through the coordinator. Log questions and
   answer-neutral replies, sharing the same reply with both reviewers. A policy
   or case meaning change requires a new version and fresh blinded review; do
   not silently clarify away a disagreement after viewing answers.
7. Return the completed review, declaration and policy-validity form as new
   files, plus a seal recording their SHA-256 digests, input identities, alias,
   slot and UTC completion time. Send the digest through a separately confirmed
   channel. Preserve the original bytes; later corrections are new submissions.

The coordinator records receipt times and verifies hashes without comparing
answers. Hashes detect changes; they do not prove authorship or trusted custody.
Both submissions must be sealed before either is opened for substantive review.
Then check complete unique case coverage, allowed labels, nonempty rationales,
explicit ambiguity flags, correct input hashes and genuine human declarations.
Return incomplete forms for a new sealed version without exposing other answers.
Never fill missing human judgments automatically.

## Adjudication after both seals

Give the adjudicator the unchanged inputs first, without author or model answers.
They record an independent policy assessment before opening the human submissions.
Then assess every case, including agreements, numerical workings and policy
validity. Do not use majority voting or author/model agreement as correctness.

For each case retain both original human labels/rationales and the adjudicator's
decision, reason, policy references and arithmetic. Record one disposition:
accepted, unresolved, or revision_required. A final label is allowed only for an
accepted case with a reasoned decision and no unresolved material policy issue.
All cases remain confirmatory_eligible=false during this process.

Only after the provisional human adjudication is sealed may the coordinator
reveal author/oracle/model material for discrepancy auditing. Log every resulting
change and its reason. Preserve the pre-unblinding judgment; never tune a label
to match a model output. Author or oracle errors require explicit correction,
not silent replacement. A separate adjudicator resolves disputes; unresolved
items stay unresolved when expertise or evidence is inadequate.

Changed inputs, semantics or policy produce a new candidate version, with old
bytes retained and a change log. Obtain fresh blind review of affected cases and
all cases affected by global policy changes. Reviewers already exposed to answers
cannot be represented as blind to those answers on a revised candidate.

Keep all original cases in the disposition ledger. Report unresolved cases,
abstentions, policy defects and any proposed exclusions with reasons. Do not
improve the headline result by quietly dropping difficult cases. Any evaluation
subset and its exclusion rules need explicit approval before evaluation.

## Completion and later gates

Completion requires two sealed human reviews, competence/conflict/exposure
records, independent adjudication of every case, policy-validity findings, a
versioned discrepancy log and owner acceptance of outstanding limitations.
Record case counts and the 16 correlated family units; do not interpret 32 cases
as 32 independent random samples. Human consensus is not real-world safety proof.

Final corpus/labels/policy/oracle/baseline/source/order hashes, independent custody,
future evaluated-provider exposure checks, scoring and pass/fail criteria remain
separate gates. A new blinded confirmatory set may be needed if exposure cannot
be excluded. Provider task compatibility, billing limits and exact execution
authorization must also be established separately. No review sign-off enables
live execution, hardware controls or production deployment.

## Local preparation verification

The private `validation-receipt.json` records bundle allowlists, nested packet
identity, blank-form checks, Git exclusion and preservation hashes. Preparation
changes no existing files, application code, configuration, SDK environment or
production state. No tests invoke an application provider or live integration.
This document is prepared locally and is not committed or published by this task.
