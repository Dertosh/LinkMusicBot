# LinkMusicBot

[@LinkMusicBot](https://t.me/LinkMusicBot) is an inline Telegram
bot that converts between various music services. To use, type
@LinkMusicBot into a Telegram chat followed by the link to a song or album.
For example, `@LinkMusicBot https://open.spotify.com/track/1ysj4ThiNp8jQ8l7Y3Ef8c`.
Then tap the suggestion that comes up to send a message with links
to the song or album on different streaming platforms.

## Project structure

```text
linkmusicbot/
  __main__.py          # python -m linkmusicbot
  bot.py               # Telegram handlers and result conversion
  presentation.py      # Cards, covers and button layout
  library.py           # Permanent SQLite catalog and local search
  settings.py          # Environment and legacy config.py settings
  youtube_fetch.py     # Bounded yt-dlp metadata search
  models.py            # Song and Album
  security.py          # Safe HTTP, request limits and cache
  services/
    base.py            # Shared service interface
    apple_music.py
    spotify.py
    youtube.py
scripts/
  build-docker.ps1     # Windows build
  build-docker.sh      # Linux build
tests/
  unit/                # Offline unit tests by component
docs/
  architecture.md      # Module responsibilities and lookup flow
config.py.example      # Copy to config.py; never commit real credentials
requirements.txt       # Direct dependencies
requirements.lock      # Pinned dependencies and hashes
Dockerfile
docker-compose.yml
```

Root `bot.py`, `converter.py`, `security.py` and build scripts remain small
compatibility entry points for previous commands/imports. Application code lives
in `linkmusicbot`; configuration stays in the project root for both local and
Docker execution. Run commands from the project root, except build scripts which
locate it automatically.

## Setup

```shell
python3 -m pip install --require-hashes --only-binary=:all: -r requirements.lock
cp config.py.example config.py
vim config.py
```

Enter your credentials for the Spotify, Telegram, and YouTube APIs into
`config.py`.

### Docker

Requires Docker Engine on Linux, or Docker Desktop with Linux containers on Windows.
Build scripts work from any current directory and stop on errors. They do not start
the bot or require credentials.

Windows (PowerShell):

```powershell
.\scripts\build-docker.ps1
```

Linux (Bash):

```bash
bash ./scripts/build-docker.sh
```

An optional first argument changes the image tag. The default is `linkmusicbot:local`.
Create `config.py` from `config.py.example`, fill in your credentials, enable inline
mode for your bot in BotFather, then start it:

```shell
docker compose up -d
```

The configuration is mounted read-only and is not included in the image. To stop
the bot, run `docker compose down`.

### Security and verification

Service buttons display service names without emoji icons.

Outbound page fetches accept only HTTPS on service-specific hosts, validate each
redirect and reject non-public DNS results. TLS verification stays enabled; use
trusted DNS (the DNS pre-check is not IP pinning). Implicit proxies and `.netrc`
credentials are disabled for page fetches. Responses are limited to 2 MiB with
timeouts and a cooperative 30-second conversion budget. Spotify requests use
5-second timeouts, no API retries, validated IDs and in-memory token caching.

The bot accepts at most one query per user every 5 seconds and 10 queries per
minute globally, converts at most two requests concurrently, returns at most two
search results, and caches up to 256 queries for 30 minutes. Tracking parameters
such as `si` and `utm_*` are excluded from cache keys; simultaneous identical
requests share one conversion. The cache is in memory and resets on restart.
Inline results use text cards with thumbnails; sent messages request a large
cover link preview (its rendering depends on Telegram's preview support).
Title searches try Apple first, then Spotify, then YouTube on empty results or
service errors. YouTube fallback consumes the configured daily search budget.
The source button opens the matched item; other buttons resolve the first match
for its title and artist (YouTube results use the channel name). These additional
lookups happen only on cache misses. Link conversion
continues to look up matching items across services.
Apple Music conversion searches the Japanese storefront for Japanese metadata
and prioritizes exact title/artist matches over remixes, covers and TV edits.
YouTube searches have
When YouTube's local or API quota is exhausted, the bot tries metadata-only
`yt-dlp` search; if it fails, the button opens a YouTube search instead of disappearing.
a separate rolling 24-hour budget of 50 calls (`youtube_search_limit` in config;
0 disables searching). This budget also counts failed attempts. Limits are in-process
and reset on restart; multiple replicas need shared limits. Existing HTML scraping
depends on the current Apple/YouTube page format and may fail if it changes.

The Python base image is pinned by digest. Docker installs only wheels from `requirements.lock`, with exact versions and
SHA-256 verification. Hashes ensure reproducibility, not absence of malicious code;
review and audit dependency updates. `requirements.txt` lists direct dependencies
for regeneration of the lock with `uv pip compile --python-version 3.11
--python-platform linux --generate-hashes --only-binary :all: -o requirements.lock
requirements.txt`. The unavailable `pawt` dependency has been replaced by
`python-telegram-bot`.

Run offline regression tests in the built image (no credentials or API calls):

Windows: `./scripts/test.ps1`. Linux: `sh ./scripts/test.sh`.
These build a separate `linkmusicbot:tests` image and run the unit suite with
network disabled, a read-only filesystem and temporary SQLite databases.
Tests cover HTTP destination checks, Apple/Spotify/YouTube adapters, quota and
yt-dlp fallbacks, Telegram handlers, cache concurrency and permanent local search.

```shell
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --mount type=bind,source="<absolute path to repo>/tests",target=/tests,readonly linkmusicbot:local python -m unittest discover -s /tests -v
```

## Usage

### Persistent local search

Titles, artists, covers, query results and service links are saved in SQLite at
`data/music.sqlite3` (`MUSIC_CACHE_PATH` overrides the path). Exact query results
are reused for 7 days; local title/artist search uses a permanent catalog.
Tracks and service links have no automatic expiry or count-based deletion.
The query cache keeps at most 5,000 queries. Docker uses a named
volume; container updates preserve it. Do not delete the volume during updates.
YouTube quota exhaustion tries metadata-only `yt-dlp` search with a 6-second
timeout, then falls back to a search URL. Videos are not downloaded.

### Production: separate bot.env (same approach as Kashka)

Credentials stay on the server in `bot.env` and are passed through Docker's
`--env-file`. They are not included in the image. Environment settings override
legacy `config.py`; a production container does not need that file.

On the server, put `scripts/server-install.sh` and `bot.env.example` in the
installation directory, then:

```sh
umask 077
cp bot.env.example bot.env
nano bot.env
sh server-install.sh install
sh server-install.sh status
```

For an image update: `sh server-install.sh update /path/to/image.tar`.
The script also supports `start`, `stop`, `restart`, and `logs`.
An alternative is `docker compose -f docker-compose.prod.yml up -d` with `bot.env`
beside that Compose file. Run only one instance per Telegram token; stop the local
bot before starting production. Changes to `bot.env` require container recreation
with `install`/`update` (a restart alone does not reload environment variables).

```shell
python3 -m linkmusicbot
```
