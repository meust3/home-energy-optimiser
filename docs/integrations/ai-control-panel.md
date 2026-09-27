# Shared AI infrastructure

Status on 2026-09-27: **real Windows development-runtime and isolated matching
App-image diagnostics verified; not deployed to the Home Assistant App**. Project Codex MCP registration is ready,
but the fresh-session verification was blocked by the existing tool approval policy.

## Pinned contract and client

Panel origin: `https://github.com/meust3/AI_Control_Planel.git`.
Contract **1.0.0** was published in commit
`436b04c50514487f9558d67c93facd0998e2f8a6`. The compatible optional-mTLS SDK
**ai-control-panel-client 1.0.1** is pinned to
`17453cb65f8ff7714b203aba8d2a7b964cb3f09c` on `codex/shared-infrastructure`.
The client was installed from that exact remote commit, not a mutable sibling import.
The normative contract and Energy handoff are committed at that revision:

- `contracts/app-integration-v1.json`
- `docs/integrations/client-contract.md`
- `docs/integrations/home-energy-handoff.md`

The manifest still names SDK 1.0.0; the committed contract's compatibility addendum
and SDK package metadata establish optional TLS support in 1.0.1 without changing
contract 1.0.0. During this task the provider published the completed network handoff at
`d323744ec6738f9280a562da89b3268a93576410`, including
`contracts/transport-mtls-v1.json`. It names SDK commit `f936b81`; a Git comparison
confirmed the SDK files are identical at our pinned `17453cb` (a test-only fix).

Install from this repository with `python -m pip install -e '.[ai,dev]'`. The extra
is optional: normal collector installation/startup does not import or require the SDK.
The image/version/source reference and production options have not been changed.

## Runtime and scope

Energy is a Python 3.12 Home Assistant App with a GET-only Ingress dashboard,
collector and existing lightweight calculation coordinator. Current v0.6.3 acceptance
notes record an amd64 HA OS NUC and a separate Synology PostgreSQL 17 database;
these deployment facts were not independently revalidated in this task. Older
README/AGENTS deployment notes describe 0.6.2; never migrate from those stale notes.
No production database or Home Assistant API was contacted by this integration.

| Context | Route | Result |
| --- | --- | --- |
| Energy Python 3.12 development runtime on PC | `http://127.0.0.1:8787` | Discovery and one real synthetic local diagnostic passed |
| Fresh project Codex process | Same PC loopback; separate build key | MCP configured; calls blocked by existing approval policy |
| Isolated production App image on PC Docker bridge | `https://192.168.50.148:8789` with mTLS | Real synthetic diagnostic passed |
| Production HA OS NUC App | Same provider-approved mTLS endpoint | Not connected/deployed/tested from NUC |

PC loopback is not NUC loopback. The panel DB is not an API endpoint and direct
worker access is not permitted. The committed mTLS route and client certificates
were verified from the isolated matching App image, not the running NUC. Do not
turn off TLS verification, open firewalls, restart shared services or deploy
production changes to bypass that remaining acceptance gate.
PC/panel/worker availability affects optional diagnostics only.

Protected provider-issued Energy files are in the panel's
`.local/consumer-handoffs/home-energy/` directory. Read only the needed slot:
`runtime-development.key`, `runtime-test.key`, `runtime-production.key`, or
`build-development.key`. Provisioning and rotation remain panel-owned. No key
was copied, generated, displayed or committed by this task. Server identity is
validated as `home-energy / application_backend / configured environment` before
inference. Wrong project, caller or environment fails closed. Production/test
slots support readiness only; development slots permit explicit local diagnostics.

## Adapter and configuration

`ai_panel.py` is the thin pinned-SDK adapter; `ai_integration.py` owns independent
settings, the optional call boundary and non-network status. Only the published
fixed synthetic diagnostic can invoke a model. Discovery validates identity,
contract version, local execution, scope, policy and worker readiness. SDK validation
checks decision bodies/answers; Energy additionally checks accepted metadata,
UUID trace/event IDs and its typed evidence report. Duplicate responses are receipts,
never replayed answers. Unknown fields are tolerated in discovery, not exposed as
secrets or treated as telemetry. No model output enters energy arithmetic.

No automatic retries, cloud fallback or background worker exists. A single SDK client
handles discovery and diagnostic within one cancellable total deadline. Connect/read
phases are bounded; the adapter adds a 64 KiB response-stream cap and rejects compressed
responses to bound decompression. Cancellation may occur after server acceptance:
retain the operation UUID and never silently replace it or retry uncertain inference.
Generation is represented by an explicit policy-denied method: onboarding keys have
no generation scope, and this task authorises no paid requests. Only published health,
capabilities and explicit local diagnostic tool operations are accepted. Native Codex
shell/test tools are not exported into the app.

Environment settings are separate from core collector configuration:

```text
ENERGY_AI_ENABLED=false
ENERGY_AI_ENVIRONMENT=production
ENERGY_AI_BASE_URL=
ENERGY_AI_KEY_FILE=
ENERGY_AI_CONNECT_TIMEOUT_SECONDS=2
ENERGY_AI_READ_TIMEOUT_SECONDS=8
ENERGY_AI_TOTAL_TIMEOUT_SECONDS=10
ENERGY_AI_CA_FILE=
ENERGY_AI_CERT_FILE=
ENERGY_AI_CERT_KEY_FILE=
ENERGY_AI_STATUS_FILE=
```

Base URL and key-file path must be paired. HTTP is accepted only for localhost or
127.0.0.1; off-host requires verified HTTPS. Optional mTLS needs both certificate
and private-key file references. Runtime slot filenames must match the configured
environment. Timeout values must be finite/positive, at most 60 seconds, with
connect/read not exceeding total; the SDK also imposes its own ten-second request
limit. Bad/missing AI configuration cannot block ingestion or core startup.

This workstation's ignored `.env.ai-control-panel` enables only development
manual diagnostics and references the protected runtime key. It contains no key
material. The CLI reads it only when explicitly named; the App does not auto-load it.
An eventual runtime must receive its own environment and protected file mounts.

```powershell
.\.venv\Scripts\python.exe -m tools.ai_diagnostic --config .env.ai-control-panel
.\.venv\Scripts\python.exe -m tools.ai_diagnostic --config .env.ai-control-panel --discover
# Explicit synthetic inference requires a stable caller-supplied UUID:
.\.venv\Scripts\python.exe -m tools.ai_diagnostic --config .env.ai-control-panel --decide --operation-id <UUID>
```

Default local inspection has exit 2 because it does not prove live readiness.
Explicit discovery/diagnostics exit 0 on success, 2 on failure/duplicate receipt.
No CLI mode accepts household observations or arbitrary model prompts.

`GET /api/v1/ai/status` exposes non-secret local status and timestamped historical
manual evidence. It makes no network/model calls. Records are validated and bound
to the current configuration; untrusted/oversized/mismatched records are ignored.
The latest successful manual result is kept separately from later discovery checks.
Historical evidence does not prove current key validity or current worker readiness.
The protected status uses existing HA `panel_admin: true` and socket-peer Ingress
policy (including existing local loopback allowance). It is not independent password
authentication. POST/execution parameters are rejected; no new host port or writable
settings endpoint exists. Core watchdog status remains independent of AI.

## Project Codex access

`tools/launch_ai_codex.ps1` installs optional MCP access for the launched project
session using only the documented `mcp_servers.panel_consumer` overrides. It preserves
global configuration, authentication, model/provider/base URL and unrelated MCP
entries. The pinned SDK runs under this project's `.venv`; only `panel_health`,
`panel_capabilities` and `panel_decide` are allowed. Startup is optional, with ten-second
startup and twenty-second tool limits. No persistent global/project tool policy is
changed. Local decisions are optional, never a mandatory step in ordinary coding.

```powershell
./tools/launch_ai_codex.ps1 -BuildKeyFile <protected-home-energy/build-development.key> -Inspect
./tools/launch_ai_codex.ps1 -BuildKeyFile <protected-home-energy/build-development.key>
# Noninteractive evidence probe, only when existing tool approvals permit it:
./tools/launch_ai_codex.ps1 -BuildKeyFile <protected-home-energy/build-development.key> -Probe -OperationId <UUID>
```

CLI 0.159.0-alpha.7 accepted the scoped syntax. Its fresh probe session was blocked:
`MCP tool call requires approval, but approval policy is never`. Neither a build
inference nor a build trace is claimed. Complete the call through the normal
interactive tool-approval workflow; do not auto-approve tools or weaken the sandbox
to turn the probe green. See [official MCP documentation](https://developers.openai.com/codex/mcp/).
The launcher itself is project access, not a model-routing proxy.

## Verification, deployment and rollback

See [live-development evidence](ai-control-panel-live-evidence-20260927.md).
Original preparation results remain in [the earlier evidence record](ai-control-panel-evidence-20260927.md).
No production App deployment, image update or migration was performed. Concurrent
acceptance-document/skill work remains untouched. Remaining acceptance requires
normal approval of fresh project MCP calls, NUC-origin verification of the approved
encrypted route, protected runtime mounts and a separately reviewed deployment. A production key
cannot perform the requested inference under contract v1; any NUC diagnostic must
use the explicitly authorised isolated development slot, never widen production scope.

Rollback disables `ENERGY_AI_ENABLED`, stops using the optional Codex launcher,
and removes only local diagnostic config/cache. Ask the panel owner to revoke the
Energy slots if needed. Do not alter hardware, controllers, historical readings,
production database topology, the worker or other applications. No paid calls or
business processing are activated by this integration.
