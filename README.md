# LinkMusicBot

Personal Spotify linking, `/current`, and inline `@SongHubbot current` setup:
[Spotify authorization and current track](docs/spotify-account.md).

This project is a fork of [jarhill0/LinkMusicBot](https://github.com/jarhill0/LinkMusicBot)
and the original [@LinkMusicBot](https://t.me/LinkMusicBot). The deployed fork is
[@SongHubbot](https://t.me/SongHubbot). Attribution appears in `/start` and in the
localized Telegram profile. Update profile text with
`python -m scripts.configure_bot_profile` using the configured bot credentials.

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
    yandex_music.py
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
requests share one conversion. SQLite snapshots survive restarts; the memory cache is repopulated from SQLite.
Inline results use text cards with thumbnails; sent messages request a large
cover link preview (its rendering depends on Telegram's preview support).
Title searches merge Apple, Spotify, Yandex Music, verified YouTube metadata and the local catalog. Source buttons preserve the selected item; other buttons use verified title/artist/version matches or search URLs.
Apple Music conversion searches the Japanese storefront for Japanese metadata
and prioritizes exact title/artist matches over remixes, covers and TV edits.
YouTube Data API searches use a persistent rolling 24-hour budget of 100 calls by default (YOUTUBE_SEARCH_LIMIT; 0 removes the local cap). Failed attempts count too. SQLite reservations and provider exhaustion survive restarts. Exhausted searches use public YouTube Music metadata through ytmusicapi, prioritizing audio tracks (ATV) over official videos (OMV) and checking the recording's title, artist and version. Official cards missing artists are resolved through video metadata. If a recording cannot be confirmed, its button opens search. Metadata also uses the videos API and public oEmbed fallback.

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
Live API checks are separate from unit tests and require no SSH, production server or Telegram token. Run `powershell -File scripts/test-live.ps1` on Windows or `bash scripts/test-live.sh` on Linux. Docker builds a diagnostic image and checks the regression cases in `tests/live/search_cases.json`. Local `bot.env`, `config.py` or environment variables provide optional API credentials; YouTube Music works without a YouTube API key. Reports and the isolated persistent quota counter are written to `data/diagnostics/`. Requests consume the quotas of the configured API accounts. Exit code 1 means a search fallback, missing recording or API error; missing Spotify credentials are reported as skipped. For a custom track use `--title "QUEEN" --artist "LiSA" --platforms youtube apple`. With Python dependencies installed, the equivalent command is `python scripts/diagnose_search.py`.

Add `--channel-cases` to the live diagnostic command to check the 16 source videos in `tests/live/youtube_channel_cases.json` and their cross-platform matches. Source checks compare parsed title/artist against the fixture and preserve the selected video ID. These cases cover collaborations, official music/lyric videos, game-theme annotations, Japanese original-song credits and catalogue spelling differences. Promotional clips and complete concerts are covered by negative unit tests.

Apple lookups fall back to public server-rendered Apple Music search when the iTunes index returns no matching recording. Search results are checked against the requested title, performers and version; related songs by the same performer are not substituted. Explicit Russian and English versions stay separate.

Tests cover HTTP destination checks, Apple/Spotify/YouTube adapters, quota and
yt-dlp fallbacks, Telegram handlers, cache concurrency and permanent local search.

```shell
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --mount type=bind,source="<absolute path to repo>/tests",target=/tests,readonly linkmusicbot:local python -m unittest discover -s /tests -v
```

## Usage

### Yandex Music

Supports `/album/<id>/track/<id>`, `/track/<id>` and `/album/<id>` links on
`music.yandex.ru`, `.com`, `.by` and `.kz`. Public metadata is read without audio
downloads or account credentials using the unofficial `api.music.yandex.net`
interface. Search by title falls back to Yandex after Spotify; conversions use
a matching title and artist (including version names), or a search URL when no
reliable match exists or the metadata API is unavailable.
The same permanent local catalog caches Yandex titles, cover art and links.
The server installer resolves the API hostname through host DNS on each update
and adds it to the container hosts when available; TLS verification remains enabled.

### Persistent local search

Titles, artists, covers, query results and service links are saved in SQLite at
`data/music.sqlite3` (`MUSIC_CACHE_PATH` overrides the path). Exact query results
are reused for 7 days; local title/artist search uses a permanent catalog.
Tracks and service links have no automatic expiry or count-based deletion.
The query cache keeps at most 5,000 queries. Docker uses a named
volume; container updates preserve it. Do not delete the volume during updates.
Inline search merges Apple Music, Spotify, Yandex Music and verified YouTube
metadata. Duplicate recordings are merged; versions retain separate cards and
links. Missing direct matches use a service search URL. YouTube links use the
videos API and public oEmbed preview as a fallback; audio/video is not downloaded.
The YouTube search counter and provider-exhaustion state are stored in the same
SQLite database as the catalog. Reservations are atomic across threads/processes
and survive container updates/restarts. The local budget uses a conservative
rolling 24-hour window; it is not a live reading of Google's project quota.

Configure these settings in `bot.env` (or the equivalent keys in `config.py`):

| Environment setting | Default | Meaning |
| --- | --- | --- |
| `INLINE_RESULT_LIMIT` | `10` | Results per inline page, from 1 to 50 |
| `INLINE_DEBOUNCE_MS` | `600` | Pause after the last input before searching |
| `MUSIC_CACHE_REFRESH_SECONDS` | `43200` | Lazy refresh interval: 12 hours |

Exact inline snapshots, including empty responses, persist in SQLite. Up to
50 candidates are cached; scrolling serves subsequent pages from
that same snapshot without querying providers again. Every query word must
match a title/artist word prefix before a candidate is included.
After the refresh interval, the next request immediately receives the existing snapshot
and schedules one background refresh. Idle queries cause no service calls.
Failed or empty refreshes preserve previous useful results and retry no sooner
than 60 seconds later. The permanent local catalog also supplies short queries;
results found only locally trigger a lazy service search for that query.

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
