# Energy consumer preparation evidence — 2026-09-27

This is an isolated Windows consumer test, not a deployed/live AI connection.
Contract/client version: **none available**. Panel HEAD was checked at discovery
and once after implementation: `10446b1c5d8b531358bfca766c9bfd042d39c984` both times.
The three requested committed contract/handoff paths were absent. Existing pilot
documentation did not establish the missing Energy-specific handoff.

## Implemented and verified

- Application-local optional async boundary; fixed failure categories, no automatic
  retry or fallback, cancellation propagation and cooperative total deadline.
- Independent non-secret settings validation, disabled default, no credentials or
  invented panel endpoint/schema/capability names.
- Existing Ingress-protected `GET /api/v1/ai/status`, no-store response, no inference
  or network I/O, no POST/config mutation. Tests exercise permitted and denied
  socket-peer access, invalid configuration and forbidden execution parameters.
- CLI uses the same local status function and returns non-ready (exit 2).
- Explicit injected outage leaves identical synthetic parsed observations and
  deterministic household load profiles. Core regression suites pass.

The development `.venv` uses bundled Python 3.12 and the repository's declared
`.[dev]` dependencies. No global Python installation was modified. Initial sandbox
dependency download failed; an approved install into `.venv` succeeded. Existing
pytest temporary/cache locations had permissions conflicts; tests used fresh
ignored workspace paths and disabled cacheprovider. Black required a workspace
`BLACK_CACHE_DIR` to avoid its inaccessible default cache. These changes did not
alter production/test logic or relax live-service access policies.

Commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ai_integration.py tests/test_dashboard.py -q --tb=short -p no:cacheprovider --basetemp=.venv/ai-test-temp
# 45 passed, 6 skipped (PostgreSQL compatibility cases lack TEST_POSTGRES_URL)

.\.venv\Scripts\python.exe -m pytest tests/test_collector_health.py tests/test_home_assistant.py tests/test_home_assistant_app.py tests/test_run_collector.py tests/test_energy_flow.py tests/test_historian_profile.py tests/test_reserve.py tests/test_forecast_operations.py tests/test_shadow_decisioning.py -q --tb=short -p no:cacheprovider --basetemp=.venv/ai-regression-temp
# 224 passed, 1 skipped

.\.venv\Scripts\python.exe -m ruff check --no-cache src/energy_optimizer/ai_integration.py src/energy_optimizer/dashboard_web.py tools/ai_diagnostic.py tests/test_ai_integration.py tests/test_dashboard.py
# Passed

$env:BLACK_CACHE_DIR = Join-Path $PWD '.venv/black-cache'
.\.venv\Scripts\python.exe -m black --workers 1 --check src/energy_optimizer/ai_integration.py src/energy_optimizer/dashboard_web.py tools/ai_diagnostic.py tests/test_ai_integration.py tests/test_dashboard.py

node --test tests/dashboard_chart.test.cjs
# 3 passed, using the bundled Node executable

.\.venv\Scripts\python.exe -m tools.ai_diagnostic
# configuration=valid, enabled=false, connection=handoff_pending,
# all remote readiness facets unverified, contract_version=null,
# latest_manual_live_test=null, automatic/paid/hardware flags false
```

Ruff, Black and Git whitespace checks passed. This change has no frontend bundle
or build dependency change. Existing JavaScript chart tests passed. No PostgreSQL
test database or production database was used in this task.

## Not implemented or verified while the contract is pending

| Acceptance item | Result |
| --- | --- |
| Real SDK-backed Energy adapter | Pending committed contract/artifact |
| Runtime scoped key and verified encrypted route | Pending Energy handoff |
| Authenticated panel capability discovery | Not performed |
| Live synthetic Decider call from NUC App | Not performed |
| NAS-backed runtime trace attribution | No trace generated |
| Project MCP installation / fresh build identity call | Pending handoff; not performed |
| Contract schema/auth/pause/worker/idempotency tests | Pending contract; local categories only tested |
| Cloud generation / provider tools | Unconfigured and unverified; no paid calls |
| HA App deployment | Not performed; image/version/config unchanged |

No other repository, global Codex configuration, shared credential or service was
modified. Existing concurrent acceptance-document and skill changes remain outside
this task. See [integration notes](ai-control-panel.md) for topology, credential
gate, future verification and rollback boundaries.
