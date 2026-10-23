# Spotify account and current track

Commands in the bot:

- `/connect_spotify` in a private chat starts Spotify authorization (PKCE).
- `/disconnect_spotify` deletes stored tokens and pending authorization links.
- `/current` sends the currently playing track with artwork and service buttons.
- `@SongHubbot current` shows that user's current track, ready to send into a chat.

Only `user-read-currently-playing` is requested. Paused playback, ads, episodes,
local files and no active playback return “nothing is playing”. Inline results
are personal and use Telegram `cache_time=0`. Playback responses and user/current
associations are not saved in the public music catalogue. Service links can be
search links when no verified cross-platform match exists.

## Configure the callback

1. Choose `https://YOUR_DOMAIN/spotify/callback` and register the exact URI in
   Spotify Developer Dashboard for the existing Spotify application. In development
   mode, ensure your Spotify account is permitted to use that application.
2. Set `SPOTIFY_REDIRECT_URI` in the server's `bot.env` (or `spotify_redirect_uri`
   in local `config.py`). An empty URI disables account authorization and HTTP.
3. Generate a **stable** Fernet encryption key, for example:

   ```sh
   umask 077
   docker run --rm --entrypoint python linkmusicbot:local -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' > spotify-token.key
   sudo chown 10001:10001 spotify-token.key
   chmod 600 spotify-token.key
   ```

   Keep it outside Git and back it up separately from the database. Rotating or
   losing this key requires reconnecting accounts. The installer mounts the file
   beside `bot.env` at `/run/secrets/spotify-token-key`. Override its host location
   with `SPOTIFY_TOKEN_KEY_HOST_FILE` when invoking the installer. For Compose use
   `docker-compose.prod.yml` plus `docker-compose.spotify.yml`.
   `SPOTIFY_TOKEN_KEY` can also supply the key directly, but a mounted secret is preferred.
4. Route **only** `/spotify/callback` through an HTTPS reverse proxy to the bot's
   port 8080. Installer/Compose publish it on host **127.0.0.1:8080**, not a public
   interface. A proxy in a separate container needs a shared Docker network and
   upstream `http://linkmusicbot:8080`; its own 127.0.0.1 is not the Docker host.
   Disable callback access logging (query parameters contain authorization codes).
   Limit concurrent requests and request rate at the public proxy.
5. Update the container, then use `/connect_spotify` and approve access on Spotify.
   The callback page confirms connection; return to Telegram and use `/current`.

Nginx location example inside your existing HTTPS virtual host:

```nginx
location = /spotify/callback {
    access_log off;
    proxy_pass http://127.0.0.1:8080;
    proxy_connect_timeout 3s;
    proxy_read_timeout 20s;
}
```

Tokens and pending PKCE verifiers are encrypted with Fernet in the separate
`data/spotify-accounts.sqlite3` database on the persistent Docker volume. OAuth
states expire after ten minutes, are single use and replaced by a new connection
request from the same Telegram user. Tokens refresh automatically; invalid/expired
refresh tokens require a new authorization. Token lifetime is not assumed permanent.

For local-only authorization an explicit loopback callback is supported:
`http://127.0.0.1:8080/spotify/callback`, registered in Spotify Dashboard. With a
remote bot use `ssh -N -L 8080:127.0.0.1:8080 laptop-small` before opening the login
link on the local computer. Other bot users need the public HTTPS callback.
