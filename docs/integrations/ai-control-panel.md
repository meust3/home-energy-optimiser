# Shared AI infrastructure

Status on 2026-09-27: **fresh project Codex inference verified; development-runtime
inference and production readiness verified in isolated containers; not deployed
to the Home Assistant NUC**. The NUC still runs 0.6.3. Candidate 0.6.4 packages the
optional integration. See [latest acceptance evidence](ai-control-panel-candidate-evidence-20260927.md)
for exact commits, identities, image, deployment dependencies and test results.

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
Candidate packaging is version 0.6.4; its immutable source is recorded in the
Dockerfile. No database migration or Supervisor option change is required.
The provider Git repository requires authentication in a clean builder: a normal
Supervisor source build deliberately omits the optional SDK. The verified private
image uses `INCLUDE_AI_SDK=true` and the checksum-verified SDK wheel as a BuildKit
secret mount. Do not publish that wheel, embed Git credentials or claim a normal
source update alone completes AI onboarding.

## Runtime and scope

Energy is a Python 3.12 Home Assistant App with a GET-only Ingress dashboard,
collector and existing lightweight calculation coordinator. Current v0.6.3 acceptance
notes record an amd64 HA OS NUC and a separate Synology PostgreSQL 17 database;
the running 0.6.3 App was independently checked in authenticated HA administration. Older
README/AGENTS deployment notes describe 0.6.2; never migrate from those stale notes.
No production database was contacted by this integration. Read-only HA administration
confirmed the running version and existing terminal access; no hardware API was called.

| Context | Route | Result |
| --- | --- | --- |
| Energy Python 3.12 development runtime on PC | `http://127.0.0.1:8787` | Discovery and one real synthetic local diagnostic passed |
| Fresh project Codex process | Same PC loopback; separate build key | Health, capabilities and one local decision passed; panel event verified |
| Isolated production App image on PC Docker bridge | `https://192.168.50.148:8789` with mTLS | Real synthetic diagnostic passed |
| Baked candidate 0.6.4 image, production slot | Same verified mTLS endpoint | Health/capabilities passed; inference correctly unavailable by policy |
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
The App uses its own protected bundle, described below.

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

CLI 0.159.0-alpha.7 accepted the scoped syntax. The initial unapproved probe was
blocked by `approval policy is never`. Following the user's explicit renewed
authorization of this local diagnostic, a fresh run with `-Probe -ApproveDiagnostic
-OperationId <UUID>` completed. This explicit switch approves only the three
allowlisted panel tools for that fixed diagnostic process, using documented
per-tool `approval_mode` overrides; it rejects non-probe use. Ordinary interactive
launches retain their existing approvals. It does not edit shared policy or weaken
the read-only sandbox. Global configuration was hashed before and after and unchanged.
See [official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).
The launcher itself is project access, not a model-routing proxy.

## Verification, deployment and rollback

See [live-development evidence](ai-control-panel-live-evidence-20260927.md).
Original preparation results remain in [the earlier evidence record](ai-control-panel-evidence-20260927.md).
No production App deployment, image update or migration was performed. Concurrent
acceptance-document/skill work remains untouched. Deployment is authorized, but
the existing NUC Terminal App has neither Docker access nor access to Energy's
private data directory, and host SSH refused the connection. Remaining acceptance
requires an existing authorized image/secret deployment channel, protected runtime
files and NUC-origin verification of the encrypted route. A production key
cannot perform the requested inference under contract v1; any NUC diagnostic must
use the explicitly authorised isolated development slot, never widen production scope.

## Candidate App bundle and deployment

The administrator installs only these provider-issued Energy files in the App's
private `/data/ai-control-panel/`: `runtime-production.key`, `ca.crt`, `client.crt`,
`client.key`, plus this non-secret `connection.json`:

```json
{"enabled": true, "base_url": "https://192.168.50.148:8789"}
```

Use a protected existing deployment channel. Keep the directory owned by root with
group 10001 and mode 0750, and files root:10001 mode 0440, readable but not writable
by the App. Do not copy any build/development key or CA signing key. The same scoped
certificate is reused; no credential is provisioned by this consumer. The loader
accepts only enabled/base_url, insists on HTTPS and fixed production/TLS filenames,
rejects symlinks, bounds config reads, and performs no network activity. Malformed
configuration appears as invalid in local status and cannot stop core startup.

Build privately with the wheel whose SHA-256 is pinned in the Dockerfile:

```powershell
docker build --platform linux/amd64 --build-arg INCLUDE_AI_SDK=true --secret id=panel_sdk_wheel,src=.local/ai-control-panel/wheels/ai_control_panel_client-1.0.1-py3-none-any.whl -t home-energy-ai:0.6.4-candidate home_energy_optimiser
```

No wheel or credential is added to Git or the build context. The wheel is a scoped
build input; only its installed package is in the image. Default builds leave the
SDK out, keeping existing source-build functionality independent of private Git access.
Deploy only the tested private image through the authorized App update procedure,
with previous-version backup and existing settings retained; no schema migration.
Do not update/restart the panel, SSH service, NAS or any other application.

Run explicitly **inside the deployed App container**, as UID/GID 10001:

```text
python -m tools.ai_diagnostic --app-runtime --discover
```

This uses the same bundle loader as the App process. The report is cached in
`/run/home-energy-optimiser/ai-status.json` and becomes visible on the authenticated
Ingress `/api/v1/ai/status` route. Startup, watchdog and dashboard requests never
run discovery or inference. Production permission=false/policy_enabled=false
alongside transport_authenticated=true/failure=null means readiness succeeded
while inference is restricted. Do not swap in a build key to change that result.

Rollback disables `ENERGY_AI_ENABLED`, stops using the optional Codex launcher,
and removes only local diagnostic config/cache. Ask the panel owner to revoke the
Energy slots if needed. Do not alter hardware, controllers, historical readings,
production database topology, the worker or other applications. No paid calls or
business processing are activated by this integration.
