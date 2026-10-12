$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TestsPath = Join-Path $ProjectRoot 'tests'
& docker build --tag linkmusicbot:tests $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Test image build failed.' }
& docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL `
    --security-opt no-new-privileges `
    --mount "type=bind,source=$TestsPath,target=/tests,readonly" `
    linkmusicbot:tests python -m unittest discover -s /tests -v
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }
