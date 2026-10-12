#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! command -v docker >/dev/null 2>&1; then
    echo 'Install Docker Engine or Docker Desktop first.' >&2
    exit 1
fi
docker info >/dev/null
docker build --pull --tag "${1:-linkmusicbot:local}" .
echo 'Build complete. Configure config.py, then run: docker compose up -d'
