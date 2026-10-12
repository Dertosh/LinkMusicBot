param([string]$Image = 'linkmusicbot:local')
# Backwards-compatible entry point.
& (Join-Path $PSScriptRoot 'scripts/build-docker.ps1') -Image $Image
