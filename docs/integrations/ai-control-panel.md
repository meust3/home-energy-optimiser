# Shared AI infrastructure: consumer preparation

Status on 2026-09-27: **local preparation only; no live connection or deployment**.
The owner's concurrent-work instruction permits independently testable preparation
while the panel session publishes its contract. No panel protocol is fabricated.

## Contract gate

Verified panel remote: `https://github.com/meust3/AI_Control_Planel.git`.
Inspected committed HEAD: `10446b1c5d8b531358bfca766c9bfd042d39c984`.
These paths were absent from that commit:

- `docs/integrations/client-contract.md`
- `contracts/app-integration-v1.json`
- `docs/integrations/home-energy-handoff.md`

The committed `docs/integration-examples.md` and `docs/integration-status.md`
describe synthetic pilots and existing panel infrastructure. They are not a
versioned Energy runtime/build handoff. No endpoint, schema, capability name,
credential or SDK version has been inferred from those pilots.
**Contract/client version used: none.** No live provider readiness was checked.

Needed from the panel owner: committed versioned client artifact/schema and Energy
handoff specifying approved encrypted NUC-to-PC route and certificate verification,
separate runtime/build identity references and protected credential locations,
local-only capability/policy permissions, safe attribution inspection, and the
verified MCP interpreter/entrypoint/tool allowlist. Do not provision duplicate keys.

## Architecture and execution contexts

Energy remote: `https://github.com/meust3/home-energy-optimiser.git`; inspected
base `79737ee2dd162fd3a5f02c0e77b817fc6e3a7497` on `main`, Python package 0.6.3.
The working checkout already contained concurrent changes to the v0.6.3 production
acceptance document, `.agents/`, and `skills-lock.json`; these are outside this work.

`home_energy_optimiser/Dockerfile` builds Python 3.12.11 on amd64 from an immutable
source ref. `home_assistant_app.py` serves the standard-library dashboard and
health endpoint; collection and the existing lightweight calculation coordinator
remain separate from optional AI. `config.py` loads local environment configuration;
HA App protected options supply production configuration. Pydantic validates core
models; pytest uses injected collaborators and SQLite/temp fixtures, with explicitly
opt-in PostgreSQL tests. JavaScript chart tests use Node's built-in test runner.

The current acceptance document records App 0.6.3 on the Home Assistant OS NUC
and PostgreSQL 17 on Synology, revision `20260927_01`. That document is concurrent
work, not independently revalidated live evidence in this task. Older README and
AGENTS deployment statements still describe 0.6.2; do not migrate using them.
No database, collector, shared service, HA configuration or hardware was contacted
or changed for this integration.

| Context | Panel route | Verification |
| --- | --- | --- |
| Windows development checkout | Awaiting Energy handoff | Local tests only |
| HA OS NUC App container | Awaiting approved encrypted route | Not tested |
| Project Codex subprocess | Awaiting scoped MCP handoff | Not registered/tested |

PC loopback is not the NUC's loopback. Panel database access and direct worker
access are forbidden alternatives. PC availability will affect optional AI only.
Existing telemetry, deterministic arithmetic and safety behavior must remain
independent of the PC, panel, worker and cloud.

## Implemented local boundary

`src/energy_optimizer/ai_integration.py` provides `AISettings`, `OptionalAI` and
fixed application-local failure categories. These are not panel schemas or
capabilities. An injected async operation is called once, explicitly, with a total
deadline and cancellation propagation. A future contract adapter must implement
connect/read deadlines, response validation and policy mapping through the real
SDK. Operations must be genuinely asynchronous and cancellation-cooperative;
blocking I/O or a coroutine that swallows cancellation cannot satisfy the deadline.
No generic seam test proves those future transport properties.

No retries are performed, including on timeout or uncertain remote acceptance.
Cancellation does not retract a request already accepted by a server. Do not add
retries without the real contract's idempotency and accounting semantics. Raw SDK
exception text, request bodies and credentials must never reach status or logs.
No production adapter, decision/generation/tool schema or network client is
installed. Only the eventual contract adapter may interpret provider output.

Local non-secret configuration, read independently of core collector config:

```text
ENERGY_AI_ENABLED=false
ENERGY_AI_CONNECT_TIMEOUT_SECONDS=2
ENERGY_AI_READ_TIMEOUT_SECONDS=10
ENERGY_AI_TOTAL_TIMEOUT_SECONDS=15
```

Timeouts must be finite, positive, at most 60 seconds; connect/read must not exceed
total. Enabled accepts only `true` or `false`. Invalid AI config cannot prevent core
startup. Enabling this flag alone cannot create a backend: manual calls without a
bound adapter fail with `handoff_pending`. No credential files are created/read.

`GET /api/v1/ai/status` is a non-secret, read-only local configuration/readiness
surface behind the existing socket-peer Ingress policy and HA `panel_admin: true`.
It inherits the existing in-container loopback allowance; it is not independent
password authentication or proof of panel authentication. Direct LAN access is
denied and forwarded headers do not grant access. Responses are not cached;
POST and query parameters requesting execution are rejected. No new host port,
configuration mutation or inference endpoint is exposed.

This endpoint and the CLI use the same local status code. They do not contact the
panel or run inference. They distinguish unverified transport/auth, capability
permissions, worker health, panel policy and absent latest live test. Core watchdog
health does not depend on this status. No inference occurs on page open, startup,
collector ticks or ordinary tests.

From the repository root, using the isolated Python 3.12 development environment:

```powershell
.\.venv\Scripts\python.exe -m tools.ai_diagnostic
.\.venv\Scripts\python.exe -m pytest tests/test_ai_integration.py tests/test_dashboard.py -q
```

The diagnostic intentionally exits 2 until connected; it is not a live Decider
command. There are no live request/trace IDs to report.

## Project Codex gate

No global or project Codex settings were changed. No runtime/build credentials
were provisioned or reused. After the handoff, install only the documented Energy
build identity in project `.codex/config.toml`, preserving existing entries,
ChatGPT authentication, model/provider/base URL and global helper-off policy.
Use optional startup dependency and a small reviewed tool allowlist; do not expose
native shell/test tools to the app. Exact MCP names and interpreter remain pending.
Project configuration, tool allowlists and optional dependencies are described by
[official Codex MCP documentation](https://developers.openai.com/codex/mcp/).

Local decisions should be explicitly requested, not compulsory on coding turns.
Prefer deterministic code for exact checks and calculations. Discover capabilities
when designing a feature, not every turn. Offline/unknown/disabled means unavailable,
never fake results or cloud fallback. No production household data disclosure,
hardware commands, paid calls or business-feature activation is allowed here.

## Completion and rollback

Remaining live acceptance requires capability discovery and one bounded synthetic
Decider call from the actual NUC App adapter/runtime, NAS-backed panel attribution
under the runtime identity, then a fresh project Codex call under the separate
build identity with exact supported trace evidence. Host curl and panel fixtures
do not satisfy this. Missing/revoked keys, schema rejection, paused inference,
worker outage and accounting must be tested against the published SDK contract;
current local failure-category tests are not wire-contract validation.

Do not deploy concurrent release work. This preparation does not change App version,
image source ref or production configuration. Rollback of the local changes removes
the new module/CLI/status route and documentation reference, or leaves the local
flag false. No key exists to revoke yet. Eventual connection rollback must disable
only the dedicated adapter/MCP configuration and scoped keys, never alter hardware,
existing controllers, historical observations or database topology.
