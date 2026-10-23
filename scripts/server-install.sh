#!/bin/sh
# Usage: ENVF=/path/bot.env sh server-install.sh install [image.tar]
set -eu
IMAGE="${IMAGE:-linkmusicbot:local}"
NAME="${NAME:-linkmusicbot}"
ENVF="${ENVF:-$(dirname "$0")/bot.env}"
DATA_VOLUME="${DATA_VOLUME:-linkmusicbot_cache}"
command -v docker >/dev/null 2>&1 || { echo 'Docker is required.' >&2; exit 1; }
case "${1:-status}" in
  install|update)
    [ -f "$ENVF" ] || { echo "Create $ENVF from bot.env.example first." >&2; exit 1; }
    chmod 600 "$ENVF"
    if [ -n "${2:-}" ]; then docker load --input "$2"; fi
    docker image inspect "$IMAGE" >/dev/null
    # Some Docker DNS setups fail on Yandex while host DNS works.
    # Resolve on each install; HTTPS still verifies the original hostname.
    # Validate credentials without printing their values before replacing the container.
    docker run --rm --network none --env-file "$ENVF" --entrypoint python "$IMAGE" -c '
import os, sys
required = ("TELEGRAM_BOT_TOKEN", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "YOUTUBE_API_KEY")
missing = [key for key in required if not os.environ.get(key)]
if missing:
    print("Missing settings: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
'
    set --
    key_file="${SPOTIFY_TOKEN_KEY_HOST_FILE:-$(dirname "$ENVF")/spotify-token.key}"
    if [ -f "$key_file" ]; then
      set -- "$@" --mount "type=bind,source=$key_file,target=/run/secrets/spotify-token-key,readonly" \
        --env SPOTIFY_TOKEN_KEY_FILE=/run/secrets/spotify-token-key
      docker run --rm --network none "$@" --entrypoint python "$IMAGE" -c \
        'from pathlib import Path; from cryptography.fernet import Fernet; Fernet(Path("/run/secrets/spotify-token-key").read_text().strip())'
    fi
    if command -v getent >/dev/null 2>&1; then
      for host in api.music.yandex.net api.telegram.org itunes.apple.com music.apple.com accounts.spotify.com api.spotify.com www.googleapis.com www.youtube.com music.youtube.com; do
        resolved_ip=$(getent ahostsv4 "$host" | awk 'NR==1 {print $1}')
        if [ -n "$resolved_ip" ]; then
          set -- "$@" --add-host "$host:$resolved_ip"
        fi
      done
    fi
    if docker container inspect "$NAME" >/dev/null 2>&1; then docker rm -f "$NAME" >/dev/null; fi
    docker run -d "$@" --name "$NAME" --restart unless-stopped --init \
      --publish "127.0.0.1:8080:8080" \
      --env-file "$ENVF" --read-only --tmpfs /tmp --cap-drop ALL \
      --security-opt no-new-privileges --memory 256m --cpus 1 --pids-limit 64 \
      --mount "type=volume,source=$DATA_VOLUME,target=/app/data" "$IMAGE"
    ;;
  start|stop|restart) docker "$1" "$NAME" ;;
  status) docker ps -a --filter "name=^${NAME}$" ;;
  logs) docker logs --tail 50 "$NAME" ;;
  *) echo 'Usage: server-install.sh install|update [image.tar] | start|stop|restart|status|logs' >&2; exit 1 ;;
esac
