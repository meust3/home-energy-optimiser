param(
    [Parameter(Mandatory)][string]$Image,
    [Parameter(Mandatory)][string]$HandoffDirectory,
    [Parameter(Mandatory)][ValidatePattern('^https://')][string]$BaseUrl,
    [ValidateSet('production', 'test', 'development')][string]$Environment = 'production',
    [Guid]$OperationId = [Guid]::Empty
)
$ErrorActionPreference = 'Stop'
$energyRoot = Split-Path $PSScriptRoot -Parent
$handoffRoot = (Resolve-Path -LiteralPath $HandoffDirectory).Path
if ((Split-Path $handoffRoot -Leaf) -ne 'home-energy') {
    throw 'Use only the protected home-energy handoff directory'
}
if ($Image -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Use an inspected immutable image ID' }
if ($OperationId -ne [Guid]::Empty -and $Environment -ne 'development') {
    throw 'Production and test runtime identities permit discovery only'
}
$wheels = Join-Path $energyRoot '.local/ai-control-panel/wheels'
if (-not (Test-Path -LiteralPath $wheels)) { throw 'Prepare the pinned SDK dependency wheels first' }
$arguments = @('run', '--rm', '--read-only', '--user', '10001:10001',
    '--network', 'bridge', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--tmpfs', '/tmp:rw,nosuid,size=128m',
    '--mount', "type=bind,source=$energyRoot/src,target=/consumer/src,readonly",
    '--mount', "type=bind,source=$energyRoot/tools,target=/consumer/tools,readonly",
    '--mount', "type=bind,source=$wheels,target=/wheels,readonly")
foreach ($file in @("runtime-$Environment.key", 'ca.crt', 'client.crt', 'client.key')) {
    $source = (Resolve-Path -LiteralPath (Join-Path $handoffRoot $file)).Path
    $arguments += @('--mount', "type=bind,source=$source,target=/run/energy-ai/$file,readonly")
}
$arguments += @('-e', 'PYTHONPATH=/consumer/src:/consumer:/tmp/site',
    '-e', 'ENERGY_AI_ENABLED=true', '-e', "ENERGY_AI_ENVIRONMENT=$Environment",
    '-e', "ENERGY_AI_BASE_URL=$BaseUrl", '-e', "ENERGY_AI_KEY_FILE=/run/energy-ai/runtime-$Environment.key",
    '-e', 'ENERGY_AI_CA_FILE=/run/energy-ai/ca.crt', '-e', 'ENERGY_AI_CERT_FILE=/run/energy-ai/client.crt',
    '-e', 'ENERGY_AI_CERT_KEY_FILE=/run/energy-ai/client.key', '--entrypoint', 'sh', $Image)
$mode = if ($OperationId -eq [Guid]::Empty) { '--discover' } else { "--decide --operation-id $OperationId" }
$arguments += @('-c', "python -m pip install --quiet --no-index --no-deps --find-links /wheels --target /tmp/site ai-control-panel-client==1.0.1 httpx==0.28.1 httpcore==1.0.9 anyio==4.15.1 h11==0.16.0 && python -m tools.ai_diagnostic $mode")
# A disposable diagnostic process. Never starts the image's collector entrypoint.
& docker @arguments
exit $LASTEXITCODE
