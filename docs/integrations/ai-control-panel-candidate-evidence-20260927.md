# Home Energy consumer acceptance — 27 September 2026

## Scope and immutable references

This is Home Energy. Only its matching handoff and common contract/status were read.
The provider worktree remained read-only on `codex/shared-infrastructure`, verified
at `d323744ec6738f9280a562da89b3268a93576410`; no assumption that it is on main.
Contract 1.0.0: `436b04c50514487f9558d67c93facd0998e2f8a6`.
SDK 1.0.1 pinned at `17453cb65f8ff7714b203aba8d2a7b964cb3f09c`; SDK source matches
the handoff's `f936b81b4263d657b5498e2223fdbb8ff767c6b0`.

Candidate App 0.6.4 code: `8e2c165976130a0f99b441bf242c5c7ce10f163e`.
Private local image built with the subsequent checked-in Dockerfile:
`sha256:808ace751a9663727d337ab0d63e61a6b3d879c5d2a2b79c3a443b44727c18b0`.
OCI revision label independently returned that code commit. No mutable source
mount, test package overlay or injected SDK was used for the candidate check below.
The image is **not deployed to the NUC** and no 0.6.4 release tag was published.

## Fresh project Codex execution — passed

CLI 0.159.0-alpha.7; fresh session `01a0e1fe-4134-7ee2-97a9-5369317712dd`.
Following the user's explicit authorization of the approved local diagnostic,
the launcher used `-Probe -ApproveDiagnostic`, retaining `--sandbox read-only`.
Only health/capabilities/decide received process-scoped per-tool approval overrides.
No global approval/auth/model/provider settings changed. Ordinary launches retain
their existing approvals. The initial denied attempt is retained in earlier evidence;
it did not consume the operation UUID, which was reused for this single execution.

The raw child-session JSONL independently records exactly one completed call each
to `panel_health`, `panel_capabilities`, and `panel_decide`, with no tool errors.
Health and capabilities returned:

- project `home-energy`, caller `codex_build`, environment `development`;
- principal `93266c65-351e-4aea-b8f8-24ea039f2a3c`;
- scopes health:read, capabilities:read, decisions:local; local policy/worker ready.

Decision at `2026-09-27T08:32:30.453065Z`:

| Evidence | Exact value |
| --- | --- |
| Operation | `8c1c45a0-e5b7-41e5-869f-de2b70254fef` |
| Trace | `2f4821ab-8e1a-4e13-8e78-39be6b997956` |
| Event | `b8aea2bc-3dfb-53ba-ab50-d434d68da57a` |
| Status / delivery | shadow / accepted |
| Runtime | local Mapika/decider-4b; 80 ms; 33 observed input tokens |

Authenticated panel UI → Activity → Fixture data → Home Energy independently showed
the exact event and trace, diagnostic kind, local provider and shadow status. This
UI projection does not expose caller/principal; those are established by the fresh
credential-authenticated health/capability responses, not invented UI fields.
Correlation quality is unlinked; no exact native Codex tool-call correlation is claimed.
Returned stale.noul=0.2172 is connectivity evidence, not a calibrated accuracy claim.
Synthetic input used a real local model. No cloud fallback or paid provider call.

Global config SHA-256 before/after this run:
`0dc57f477e3257a96b65b5ef8eab34a0cdd46d878fd9297cf80f3702c9b14e67`.
An older evidence record has a different earlier baseline; concurrent sessions may
change it between tasks. This task neither rewrote nor restored global settings.

## Production identity, isolated baked App image — passed readiness

At `2026-09-27T08:41:58.540745Z`, the candidate's baked Python code and SDK executed:
`python -m tools.ai_diagnostic --app-runtime --discover`.
It ran as UID/GID 10001 on Docker Desktop bridge, read-only root, all capabilities
dropped, no-new-privileges, with only the Energy production key and TLS files mounted
read-only. The status directory was a small private tmpfs. No HA token, database
credentials, build key, development key, CA signing key or Docker socket was mounted.
The process used verified server TLS plus the Energy client certificate at
`https://192.168.50.148:8789`.

Authenticated result:

- project `home-energy`, caller `application_backend`, environment `production`;
- principal `1d97349d-90c6-488e-932c-f6dc87cc4aaf`;
- transport_authenticated=true, worker_ready=true, paused=false, failure=null;
- permission=false, policy_enabled=false; local_diagnostic=not_run;
- generation, business processing and hardware commands all false.

This is successful connectivity with an inference policy restriction, not a connection
failure. No decision was attempted under the production slot. The contract's discovery
response supplies no decision operation/trace/event IDs; those fields remain null.
Earlier real **development-runtime** calls and their exact IDs remain in
[live-development evidence](ai-control-panel-live-evidence-20260927.md), including
runtime trace `9fa5abe9-3e5c-49bd-84be-8be019634dde` from the isolated v0.6.3 image.
Those results must not be described as NUC-origin execution.

## Packaging and tests

The first clean image build established that the SDK Git source requires GitHub
authentication. No Git credential was copied into Docker. Instead the private AI
image receives the verified SDK wheel through a build-time-only BuildKit secret
mount, with SHA-256 verification before installation:
`a10d6a3170bb0c564e478d338bcac293dbdb0adc1748acc838d1cfabb8db65bb`.
The wheel is not committed/published. Normal source builds default to SDK omitted;
`INCLUDE_AI_SDK=true` is required for the tested AI image. Do not confuse the two.

- Full local suite: **456 passed, 15 skipped**, 70.53 seconds. Skipped integration
  checks are not passed production tests.
- Focused adapter/configuration/App/dashboard run: 150 passed, 6 skipped.
- Updated packaging/version/config tests: 72 passed.
- Both private SDK-included and default SDK-omitted images built successfully.
  Offline local status in the default image reported disabled/unconfigured with
  sdk_version=null, making the missing optional dependency explicit.
- Image-baked container verification passed: root-owned original options preserved,
  protected ephemeral copy removed after parsing, UID/GID 10001, defaults HOLD-only,
  watchdog available, simulated trusted Ingress accepted, spoofed headers denied,
  no secrets in API responses, SIGTERM delivered to Python.
- Ruff, Black and Git whitespace checks passed for changed code.

Tests use public contract fixtures or local dummy options, never production household
data. No collector, hardware command, migration or paid model operation was launched
by these isolated checks. Ignored logs and raw diagnostic evidence are under
`.local/ai-control-panel/`.

## Authorized deployment — blocked by access, not completed

Authenticated HA UI confirmed `20ed6eda_home_energy_optimiser` **running 0.6.3**,
automatic updates off. Existing Terminal & SSH reports HA OS 18.3 / Core 2026.9.3.
Read-only inspection of that terminal showed no Docker executable and no
`/addon_configs` directory; Energy's existing App IP was 172.30.33.3. Host SSH to
homeassistant.local refused the connection. No shared permissions, service settings,
firewall, credential, protection mode or host exposure was changed to bypass this.

The user authorized deployment, but an existing authorized channel is still needed
to install the tested private image and the Energy production bundle in its private
`/data` directory, and execute the readiness command inside that deployed container.
A focused question requesting only that connection name/path was sent; no secret
was requested. No other application or provider repository was edited.

No new deployed commit is claimed. Current live NUC image commit was not independently
read; version 0.6.3 was verified in administration. Production Ingress AI status,
NUC-to-panel mTLS reachability and readiness remain unverified. Cloud generation,
business use, hardware actions, token savings and counterfactual quality remain
disabled or unverified. Concurrent acceptance-document and skill changes were
preserved. No database migration is needed for this candidate.
