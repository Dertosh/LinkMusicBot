# Project layout

- `linkmusicbot/bot.py`: Telegram handlers, debounce, service orchestration and cache lookup.
- `linkmusicbot/presentation.py`: card text, thumbnails, link previews and button layout.
- `linkmusicbot/models.py`: songs and albums.
- `linkmusicbot/services/`: Apple Music, Spotify and YouTube adapters.
- `linkmusicbot/youtube_fetch.py`: bounded metadata-only yt-dlp search.
- `linkmusicbot/security.py`: URL validation, HTTP bounds, rate limits and in-memory cache.
- `linkmusicbot/library.py`: permanent SQLite catalog and query cache.
- `linkmusicbot/settings.py`: environment settings and legacy config.py compatibility.
- `scripts/`: Windows/Linux build, test and server installation commands.
- `tests/unit/`: offline unit tests with service requests mocked.

Lookup order: memory cache, persistent query cache/local catalog, music services.
Results populate the permanent catalog. Production stores it in the
`linkmusicbot_cache` Docker volume; updates must preserve that volume.

Root launchers/import wrappers preserve previous commands. Docker starts the
package with `python -m linkmusicbot`. Secrets stay in server-side `bot.env` and
are passed through `--env-file`; source and Docker image do not contain them.
