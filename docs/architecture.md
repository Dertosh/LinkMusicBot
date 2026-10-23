# Project layout

Inline cards first use a web preview. Bot API media errors trigger a retry as
photo (cached Telegram file ID when available), then text without a preview.
No duplicate format choices are shown. Canonical cached cards keep previews
disabled; the transport adds the desired format. Bot API inline updates expose
chat type but no destination chat ID, so permissions cannot be preflighted for
arbitrary chats. Client-only failures during the user's send are not reported
to the bot and cannot trigger an automatic retry.
Set TELEGRAM_COVER_STORAGE_CHAT_ID to a storage channel where this bot can post
photos. Selected cover URLs are uploaded there once; covers.sqlite3 persists
bot-scoped file IDs in the production data volume. Without that setting, photo
cards use remote URLs and no unrequested storage messages are sent.

Cold inline song URLs return a source-only preview with a loading indicator.
`progressive_inline.py` resolves other services in background and edits chosen
inline messages as results arrive. BotFather inline feedback must be 100%.
Loading cards are never persisted; completed cards enter the normal lazy cache.
Jobs are bounded to 256 in memory and expire after 30 minutes once complete.
A choice received after restart can reconstruct its job from the original URL.

- `linkmusicbot/bot.py`: Telegram handlers, debounce, service orchestration and cache lookup.
- `linkmusicbot/presentation.py`: card text, thumbnails, link previews and button layout.
- `linkmusicbot/models.py`: songs and albums.
- `linkmusicbot/services/`: Apple Music, Spotify, YouTube and Yandex Music adapters.
- `linkmusicbot/youtube_fetch.py`: bounded metadata-only yt-dlp search.
- `linkmusicbot/security.py`: URL validation, HTTP bounds, rate limits and in-memory cache.
- `linkmusicbot/library.py`: permanent SQLite catalog and query cache.
- `linkmusicbot/settings.py`: environment settings and legacy config.py compatibility.
- `scripts/`: Windows/Linux build, test and server installation commands.
- `tests/unit/`: offline unit tests with service requests mocked.

Lookup order: memory cache, persistent query cache/local catalog, music services.
Cached results are served immediately; the inline handler schedules a coalesced
background refresh on demand after `MUSIC_CACHE_REFRESH_SECONDS` (12 hours by
default). Retry attempts are persisted separately so failures do not stamp the
old snapshot as fresh. A worker slot and the existing global rate guard bound
refresh work. Old snapshots remain available when providers fail.
Service searches are merged before rendering to avoid a per-result fan-out of
network calls. Exact title/artist/version matches share their known direct URLs;
unresolved buttons retain search URLs. Query spelling variants are tried across
providers. Stable result IDs preserve the selected card through cache refresh.
Results populate the permanent catalog. Production stores it in the
`linkmusicbot_cache` Docker volume; updates must preserve that volume.

Root launchers/import wrappers preserve previous commands. Docker starts the
package with `python -m linkmusicbot`. Secrets stay in server-side `bot.env` and
are passed through `--env-file`; source and Docker image do not contain them.
