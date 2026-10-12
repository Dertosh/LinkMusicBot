#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker build --tag linkmusicbot:tests "$root"
docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL \
    --security-opt no-new-privileges \
    --mount "type=bind,source=$root/tests,target=/tests,readonly" \
    linkmusicbot:tests python -m unittest discover -s /tests -v
