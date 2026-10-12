#!/usr/bin/env bash
set -euo pipefail
# Backwards-compatible entry point.
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/scripts/build-docker.sh" "$@"
