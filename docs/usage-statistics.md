# Usage statistics

Daily counters start when this feature is deployed; historical Telegram users
cannot be reconstructed from the shared song catalogue or query cache.

`data/usage.sqlite3` stores Telegram ID, current username (if provided), first/last
observation time and daily counts for inline requests and commands. It does not
store query text, message text, chat IDs, Spotify accounts or OAuth tokens.
Dates are UTC. Inline counts are requests after debounce, not songs sent or
unique listening sessions. `/start` and ordinary private messages count as `start`.
Names/IDs are for the operator; no public `/stats` command exposes other users.

Read a local database without modifying it:

```sh
python scripts/usage_report.py --db data/usage.sqlite3
```

Or run inside the production container (only aggregate fields and user IDs/names):

```sh
docker exec linkmusicbot python -c 'import json; from linkmusicbot.usage import UsageStats; s=UsageStats("/app/data/usage.sqlite3"); print(json.dumps(s.report(),ensure_ascii=False,indent=2)); s.close()'
```

These counters do not include diagnostic searches performed by maintenance scripts.
