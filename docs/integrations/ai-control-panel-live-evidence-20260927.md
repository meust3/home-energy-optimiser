# Energy AI consumer verification — 27 September 2026

This work follows preparation commit `7aaa687`. It connects the actual Energy
Python adapter in development and verifies it in an isolated copy of the production
App image. **It does not deploy the adapter to the NUC, and it does not claim a
successful fresh Codex tool call.** Existing business/hardware paths remain unchanged.

## Contract and installed client

- Contract 1.0.0: `436b04c50514487f9558d67c93facd0998e2f8a6`.
- SDK 1.0.1 pinned to `17453cb65f8ff7714b203aba8d2a7b964cb3f09c`.
  Installed distribution `direct_url.json` confirmed this exact remote Git revision.
- Wheel used in the container: `ai_control_panel_client-1.0.1-py3-none-any.whl`,
  SHA256 `a10d6a3170bb0c564e478d338bcac293dbdb0adc1748acc838d1cfabb8db65bb`.
  This is a consumer-built wheel, not the provider's separately built wheel/hash.
- Completed provider/network handoff: `d323744ec6738f9280a562da89b3268a93576410`
  on `codex/shared-infrastructure`; `main` was still `814643a` at inspection.
- Transport manifest names SDK `f936b81`; Git diff confirmed no SDK source change
  between that commit and pinned `17453cb` (the latter fixes a test literal).
- Runtime principal: `545f309b-885a-489a-bb25-539d276f5e94`, server-derived
  `home-energy / application_backend / development`. Build credentials are separate.
  Only the runtime-development slot and Energy TLS files were read/mounted.

## Real consumer calls and independent panel read-back

| Context | Operation UUID | Trace | Event |
| --- | --- | --- | --- |
| Energy Windows Python 3.12.14 runtime, loopback | `7b46729e-4727-4a1b-b156-015c3c7c8cde` | `a3ece0f5-a568-4bed-8c85-e574743372a4` | `13700231-866a-5015-83f4-ef35ffe22b46` |
| Isolated App image, Python 3.12.11, mTLS | `c19053a2-b4d7-4f16-8c89-e63eae1d9221` | `9fa5abe9-3e5c-49bd-84be-8be019634dde` | `390dbe1d-a3b1-596e-afe6-90bbeed2902a` |

Both calls used the published fixed synthetic stale-reading question, returned
`shadow` with `metadata_delivery=accepted`, and produced real local Decider output.
Neither used a mock worker, cloud provider or household telemetry. The returned
probability was 0.2172; this is an untrusted synthetic model result, not a claim of
classification accuracy or calibrated confidence, and is not used by Energy logic.

Authenticated Chrome panel Activity inspection, fixture view filtered to Home Energy,
independently showed each exact event and trace. Records identified `home-energy`,
`diagnostic`, `Local Decider`, `Mapika/decider-4b`, `shadow`, `fixture=true`, 33 local
input tokens, and unknown output/cached/reasoning tokens. Runtime latency metadata
was 128 ms and 144 ms respectively. Correlation remained `unlinked`; no session or
Codex tool-call identity is invented. The UI's detail projection omits principal/caller;
those were checked via the authenticated credential-bound discovery response.

System UI separately showed panel build `f936b81b4263d657b5498e2223fdbb8ff767c6b0`,
image `sha256:37160367476be0ccd41cc5f4cc635532ceb3bbd9596e1ec6c772d7b4534661fc`,
database `ai_control_panel`, verified TLS, schema `008_consumer_grants.sql`, healthy
database and ready shared worker. The committed provider record establishes NAS
placement. No direct panel database credentials/query were used by this consumer.
Fixture view was returned to normal after inspection; no panel policy was changed.

## Matching App runtime, tested in isolation

The already-present image matching the production acceptance record was inspected:
`sha256:5e311f85579945db216f4681204de705b9b7d6797de55a789d28a295d889d686`.
It contains Python 3.12.11 and Pydantic 2.13.5. This task did not rebuild or replace it.

The disposable diagnostic container used UID/GID 10001, read-only root filesystem,
all capabilities dropped, no-new-privileges, default Docker bridge and temporary
`/tmp`. The entrypoint was overridden to run only the CLI, never the collector.
Energy source/tools and pinned pure-Python dependency wheels were mounted read-only;
dependencies installed only into temporary `/tmp/site`. Only this project's
`runtime-development.key`, `ca.crt`, `client.crt`, `client.key` were mounted read-only.
No production/test/build key, CA signing key, HA token, database URL, device or Docker
socket was mounted. The container exited and was removed after the test.

The actual adapter called the committed `https://192.168.50.148:8789` mTLS route,
with certificate/hostname verification enabled and bearer scope independently checked.
This proves compatibility and connectivity from the PC's isolated Docker peer, not
from the running NUC. No shared services were restarted/reconfigured.

Reproduce discovery without inference after preparing the wheels:

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir .local/ai-control-panel/wheels 'ai-control-panel-client @ git+https://github.com/meust3/AI_Control_Planel.git@17453cb65f8ff7714b203aba8d2a7b964cb3f09c#subdirectory=packages/client-python'
.\.venv\Scripts\python.exe -m pip download --only-binary=:all: --no-deps --dest .local/ai-control-panel/wheels httpx==0.28.1 httpcore==1.0.9 anyio==4.15.1 h11==0.16.0
./tools/verify_ai_runtime.ps1 -Image sha256:5e311f85579945db216f4681204de705b9b7d6797de55a789d28a295d889d686 -HandoffDirectory ../AI_Control_Planel/.local/consumer-handoffs/home-energy -BaseUrl https://192.168.50.148:8789
```

An explicit `-OperationId <UUID>` enables the fixed diagnostic. The recorded UUID
above is already consumed; reusing it is only a duplicate receipt, not a new result.
The reusable script's default discovery mode was exercised successfully. Its first
trial exposed a missing-Guid default, rejected by CLI argument validation before any
request; both launchers now initialise that parameter to `Guid.Empty` explicitly.

The local CLI was exercised with:

```powershell
.\.venv\Scripts\python.exe -m tools.ai_diagnostic --config .env.ai-control-panel --discover
.\.venv\Scripts\python.exe -m tools.ai_diagnostic --config .env.ai-control-panel --decide --operation-id 7b46729e-4727-4a1b-b156-015c3c7c8cde
```

The ignored `.env.ai-control-panel` contains only scoped configuration/file references.
The timestamped local evidence lives under ignored `.local/ai-control-panel/`.
An isolated actual dashboard handler served its cached real trace at
`GET /api/v1/ai/status`: HTTP 200, `Cache-Control: no-store`, historical snapshot marked.
No database service was available to that handler and none was used. This was allowed
local loopback access; authenticated live HA Ingress was not claimed. Separate tests
verify peer denial, POST rejection and no inference on status requests.

## Fresh project Codex result: blocked honestly

Codex CLI `0.159.0-alpha.7` accepted `tools/launch_ai_codex.ps1 -Inspect`, showing
the project `.venv` interpreter, separate protected Energy build-development key-file
reference and only `panel_health`, `panel_capabilities`, `panel_decide`. Startup remains
optional; no global or persistent model/auth/approval setting was changed.

Fresh session `01a0e152-08bf-7fe2-ae66-4aa7a9cc4a73` was launched from this repo with
operation UUID `8c1c45a0-e5b7-41e5-869f-de2b70254fef` and fixed synthetic input.
Its health and capabilities tool calls were blocked by:

> MCP tool call requires approval, but approval policy is never

The model stopped without calling Decider or retrying. **No build trace/event exists
from this test.** Provider-owned fixture traces are not substituted for consumer proof.
Normal interactive tool approval is still required. No bypass, auto-approval setting,
alternate direct build request, authentication change or cloud fallback was attempted.

Global `config.toml` SHA256 before/after was unchanged:
`29574a09de97f7ba9e22a115e9542ae39abd39717ea4dfcc26366f35334ccf42`.
Probe events/result remain in the ignored evidence directory. The launcher is reusable
project-scoped access; it does not create a routing proxy or expose native shell tools.

## Tests and remaining acceptance

- SDK/adapter/config/status suites: **78 passed, 6 skipped** (PostgreSQL cases).
- Collector, HA client/App, load profiles, flows, reserve, coordinator and shadow
  regression suites: **224 passed, 1 skipped**.
- Dashboard JavaScript: **3 passed**. Ruff, Black and whitespace checks passed.
- Failure cases include missing/revoked/wrong-scope credentials, wrong project/caller,
  pause/worker failure, invalid answer/schema/metadata, duplicate receipt, bounded
  timeout/cancellation, oversized/compressed responses, redaction and denied generation.
  Real loopback HTTP tests exercise the SDK transport; injected outage tests compare
  unchanged deterministic observations/calculations. Shared live failures were not induced.

Re-run the focused suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ai_panel.py tests/test_ai_integration.py tests/test_dashboard.py -q --tb=short -p no:cacheprovider --basetemp=.venv/ai-connected-test-final
```

Unfinished acceptance: fresh project Codex tool approval/call/attribution and
production NUC runtime mounting/connectivity/deployment. Generation/premium/tool
routes beyond the infrastructure allowlist remain denied, not emulated. Paid calls,
automatic AI processing and hardware commands remain disabled. No accounting/token
savings or successful household automation is claimed. Concurrent Energy acceptance
and skill work was excluded; no other repository was modified.
