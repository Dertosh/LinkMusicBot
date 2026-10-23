#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
mkdir -p "$PROJECT_ROOT/data/diagnostics"
docker build --tag linkmusicbot:diagnostics "$PROJECT_ROOT"
options=(run --rm --user "$(id -u):$(id -g)" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges)
if [ -f "$PROJECT_ROOT/bot.env" ]; then
    options+=(--env-file "$PROJECT_ROOT/bot.env")
fi
for key in SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET YOUTUBE_API_KEY; do
    if [[ -v "$key" ]]; then options+=(--env "$key"); fi
done
if [ -f "$PROJECT_ROOT/config.py" ]; then
    options+=(--mount "type=bind,source=$PROJECT_ROOT/config.py,target=/app/config.py,readonly")
fi
docker run "${options[@]}" \
    --mount "type=bind,source=$PROJECT_ROOT/scripts,target=/app/scripts,readonly" \
    --mount "type=bind,source=$PROJECT_ROOT/tests,target=/app/tests,readonly" \
    --mount "type=bind,source=$PROJECT_ROOT/data/diagnostics,target=/diagnostics" \
    linkmusicbot:diagnostics python scripts/diagnose_search.py --output /diagnostics/report.json "$@"
