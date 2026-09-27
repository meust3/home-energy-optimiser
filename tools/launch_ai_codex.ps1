param(
    [Parameter(Mandatory)][string]$BuildKeyFile,
    [string]$Python,
    [switch]$Inspect,
    [switch]$Probe,
    [Guid]$OperationId = [Guid]::Empty
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path $PSScriptRoot -Parent
if (-not $Python) { $Python = Join-Path $repository '.venv/Scripts/python.exe' }
$Python = (Resolve-Path -LiteralPath $Python).Path.Replace('\', '/')
$BuildKeyFile = (Resolve-Path -LiteralPath $BuildKeyFile).Path.Replace('\', '/')
if ((Split-Path $BuildKeyFile -Leaf) -ne 'build-development.key' -or
    (Split-Path (Split-Path $BuildKeyFile -Parent) -Leaf) -ne 'home-energy') {
    throw 'Use only the protected home-energy build-development slot'
}
if ($Probe -and ($OperationId -eq [Guid]::Empty)) {
    throw 'The probe requires an explicit stable OperationId; no automatic retry'
}
if ($Probe -and $Inspect) { throw 'Choose Inspect or Probe' }
# Exact scoped overrides from contract 1.0.0; no global config/auth/routing edits.
$arguments = @('-C', $repository,
    '-c', "mcp_servers.panel_consumer.command=`"$Python`"",
    '-c', 'mcp_servers.panel_consumer.args=["-m","panel_mcp"]',
    '-c', "mcp_servers.panel_consumer.env.PANEL_CONSUMER_KEY_FILE=`"$BuildKeyFile`"",
    '-c', 'mcp_servers.panel_consumer.env.PANEL_BASE_URL="http://127.0.0.1:8787"',
    '-c', 'mcp_servers.panel_consumer.enabled_tools=["panel_health","panel_capabilities","panel_decide"]',
    '-c', 'mcp_servers.panel_consumer.required=false',
    '-c', 'mcp_servers.panel_consumer.startup_timeout_sec=10',
    '-c', 'mcp_servers.panel_consumer.tool_timeout_sec=20')
if ($Inspect) { $arguments += @('mcp', 'get', 'panel_consumer', '--json') }
if ($Probe) {
    $evidence = Join-Path $repository '.local/ai-control-panel'
    New-Item -ItemType Directory -Path $evidence -Force | Out-Null
    $prompt = "Verify this project's explicitly requested shared panel connection only. Do not edit files, run shell commands, browse, or call other tools. Call panel_consumer.panel_health and panel_consumer.panel_capabilities once each. Require project home-energy, caller codex_build, environment development. If identity differs or local decision policy is unavailable, report the blocker and stop. Otherwise call panel_consumer.panel_decide exactly once with operation_id $OperationId, feature diagnostic, input_kind synthetic_diagnostic, state 'Synthetic reading is three days old', and questions containing stale with type noul and instructions 'Is the reading stale?'. Never retry or generate another UUID. Report the returned principal, status, trace_id, event_id and metadata_delivery exactly; do not claim hardware operation, savings or a Codex tool-call ID. No paid calls."
    $arguments += @('exec', '--sandbox', 'read-only', '--json', '-o',
        (Join-Path $evidence 'codex-probe-result.txt'), $prompt)
    & codex @arguments 1> (Join-Path $evidence 'codex-probe.jsonl') 2> (Join-Path $evidence 'codex-probe.stderr')
} else {
    & codex @arguments
}
exit $LASTEXITCODE
