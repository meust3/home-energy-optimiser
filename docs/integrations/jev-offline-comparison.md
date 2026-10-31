# Offline Jev comparison

The subsequent [SDK 1.0.4 reconciliation](../Testing/jev_sdk104_reconciliation_20261031.md)
updates the optional dependency and adapter. This offline tool still needs no
SDK; its frozen task 1.1.0 metadata remains unchanged. The scope and validation
below record the preceding offline-only increment at `0b5f655`.

This reconciles only the offline comparison portion of the uncommitted Jev
evaluator. It reads saved synthetic results and never submits inference,
loads runtime credentials, discovers providers or changes energy decisions.
The original evaluator, submission CLI and SEMS recovery files remain untouched
in their original worktrees.

## Use

From the repository root, after installing the normal application:

```powershell
python -m tools.compare_jev --mapika docs/integrations/ai-review-holdout-results-20261003.json
```

With no challenger file, all 48 Jev cases are reported as unattempted. To compare
an existing saved artifact and create a new report:

```powershell
python -m tools.compare_jev --mapika docs/integrations/ai-review-holdout-results-20261003.json --jev <saved-results.json> --output <new-comparison.json>
```

The command has no live mode. Existing output files are refused, including when
the output names an input. Exit zero means an offline report was produced;
it does not mean the challenger passed the quality gate. Exit two means the
input or output was invalid/unavailable. Original inputs are not modified.

## Evidence and interpretation

`energy_optimizer/jev_reference.json` contains only frozen case identifiers,
strata, expected labels and deterministic reference labels, plus task/dataset/
question identity. It is extracted from the published holdout at provider commit
`2aa746e42b6acea0515b099c5ba2ec986e925fc1`, task 1.1.0, SDK 1.0.3. It contains
no prompts, household observations, credentials or provider responses. An optional
fidelity test checks every case and identity against the pinned SDK.

Normal comparison and tests require no Panel SDK. The existing optional SDK
pin, App build contract, AI adapter, disabled integration settings and nullable
SDK diagnostic remain unchanged. SDK 1.0.4 support and the live submission method
are not part of this increment.

Reports retain per-stratum/per-family counts, raw supplied choices, false-support
counts, partial/failed/unattempted cases and descriptive confidence/latency.
Failed answers are not scored, and their confidence is excluded from descriptive
correct/incorrect groups. Missing usage remains unknown; usage output is limited
to supplied input/output token counts. Labels, strata, known contract metadata,
duplicate/unknown cases, completed choices and numeric evidence are validated.

Artifact validity does not prove provider identity, execution, billing, ledger
correlation or independent model quality. Reports explicitly identify execution
and ledger evidence as unverified. `completed_case_coverage` means 48 valid
completed labels were supplied, not that this tool witnessed execution. The
48 cases remain exposed and correlated; independent narrative label review is
pending. Even perfect synthetic labels retain `production_activation` as
`NOT AUTHORISED`. No costs or savings are inferred.

## Reconciliation validation — 2026-10-31

Starting main: `11d1bc7`. All checks ran in disposable, network-disabled
containers using synthetic fixtures and read-only source snapshots.

- Pinned SDK 1.0.3: **109 passed** across offline comparison and existing AI
  App/integration/adapter/pilot/holdout/CLI tests, including snapshot fidelity.
- SDK uninstalled in the disposable container: **53 passed, one skipped**.
  Only the optional SDK fidelity check skips; all offline comparison tests run.
- Main's disabled-diagnostic regression passes in both environments. Neither
  `ai_panel.py` nor `ai_integration.py` was modified.
- Ruff and Black pass across source, tests, tools and migrations (192 files).
- A wheel was built and installed without network access, using a previously
  cached setuptools wheel. Outside the source checkout, with no Panel SDK,
  the CLI loaded all 48 packaged reference cases and produced an unattempted
  comparison; nullable diagnostic evidence was also checked.

The first packaging attempt lacked setuptools in the test image. Using the
existing cached wheel resolved that environment issue; no download or runtime
configuration was required. This validates packaging of the reference resource,
not a new deployed App image. No production acceptance, migration or live model
quality is claimed. No production service was contacted and nothing was pushed.
