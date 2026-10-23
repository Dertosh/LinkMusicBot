param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Reports = Join-Path $ProjectRoot 'data/diagnostics'
New-Item -ItemType Directory -Force $Reports | Out-Null
& docker build --tag linkmusicbot:diagnostics $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Diagnostic image build failed.' }
$Options = @('run','--rm','--read-only','--tmpfs','/tmp','--cap-drop','ALL','--security-opt','no-new-privileges')
$EnvFile = Join-Path $ProjectRoot 'bot.env'
if (Test-Path -LiteralPath $EnvFile) { $Options += @('--env-file', $EnvFile) }
foreach ($Key in @('SPOTIFY_CLIENT_ID','SPOTIFY_CLIENT_SECRET','YOUTUBE_API_KEY')) {
    if (Test-Path "Env:$Key") { $Options += @('--env', $Key) }
}
$Config = Join-Path $ProjectRoot 'config.py'
if (Test-Path -LiteralPath $Config) { $Options += @('--mount', "type=bind,source=$Config,target=/app/config.py,readonly") }
$Options += @('--mount', "type=bind,source=$PSScriptRoot,target=/app/scripts,readonly",
    '--mount', "type=bind,source=$ProjectRoot/tests,target=/app/tests,readonly",
    '--mount', "type=bind,source=$Reports,target=/diagnostics",
    'linkmusicbot:diagnostics','python','scripts/diagnose_search.py','--output','/diagnostics/report.json')
& docker @Options @Arguments
$Result = $LASTEXITCODE
Write-Host "Report: $Reports/report.json"
exit $Result
