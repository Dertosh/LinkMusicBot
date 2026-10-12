param([string]$Image = 'linkmusicbot:local')
$ErrorActionPreference = 'Stop'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Install Docker Desktop and enable Linux containers first.'
}
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $DockerOS = & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is unavailable. Start Docker Desktop.' }
    if ($DockerOS -ne 'linux') { throw 'Switch Docker Desktop to Linux containers.' }
    & docker build --pull --tag $Image .
    if ($LASTEXITCODE -ne 0) { throw 'Docker build failed.' }
    Write-Host "Built $Image. Configure config.py, then run: docker compose up -d"
} finally {
    Pop-Location
}
