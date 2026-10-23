"""Private Spotify authorization and playback, separate from the public catalogue."""
import base64
import hashlib
import json
import re
import secrets as random
import sqlite3
import time
from pathlib import Path
from threading import RLock
from urllib.parse import urlencode, urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken

from .models import Song

SCOPE = 'user-read-currently-playing'


class AccountError(Exception):
    """Safe error text: never include OAuth codes, response bodies or tokens."""


class NotConnected(AccountError):
    pass


class SpotifyAccount:
    def __init__(self, client_id, redirect_uri, encryption_key, path):
        uri = urlparse(redirect_uri)
        if (not client_id or uri.path != '/spotify/callback' or uri.query or uri.fragment
                or uri.username or uri.password or not uri.hostname
                or not (uri.scheme == 'https' or
                        uri.scheme == 'http' and uri.hostname in {'127.0.0.1', '::1'})):
            raise ValueError('Configure a valid Spotify callback URI')
        self.client_id, self.redirect_uri = client_id, redirect_uri
        self.cipher = Fernet(encryption_key)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        Path(path).chmod(0o600)
        self.lock = RLock()
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS accounts (user INTEGER PRIMARY KEY, token BLOB NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS states (state TEXT PRIMARY KEY, user INTEGER UNIQUE, verifier BLOB, expires REAL)')
        self.db.commit()

    def _encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value).encode())

    def _decrypt(self, value):
        try:
            return json.loads(self.cipher.decrypt(value))
        except (InvalidToken, ValueError):
            raise AccountError('Stored credentials cannot be read; reconnect Spotify.') from None

    def begin(self, user):
        state, verifier = random.token_urlsafe(32), random.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with self.lock, self.db:
            self.db.execute('DELETE FROM states WHERE expires<?', (time.time(),))
            self.db.execute('INSERT OR REPLACE INTO states VALUES (?,?,?,?)',
                            (hashlib.sha256(state.encode()).hexdigest(), user, self._encrypt(verifier), time.time()+600))
        return 'https://accounts.spotify.com/authorize?' + urlencode({
            'client_id': self.client_id, 'response_type': 'code', 'redirect_uri': self.redirect_uri,
            'scope': SCOPE, 'state': state, 'code_challenge_method': 'S256', 'code_challenge': challenge,
        })

    @staticmethod
    def _request(method, url, **kwargs):
        # Endpoints are constants in this module; do not forward browser-supplied URLs.
        try:
            with requests.Session() as session:
                session.trust_env = False
                with session.request(method, url, timeout=(3, 5), allow_redirects=False,
                                     stream=True, **kwargs) as response:
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > 1024 * 1024:
                            raise AccountError('Spotify response is too large.')
                    payload = json.loads(data) if data else {}
                    if not isinstance(payload, dict):
                        raise AccountError('Spotify returned an invalid response.')
                    return response.status_code, payload
        except (requests.RequestException, ValueError):
            raise AccountError('Spotify is temporarily unavailable.') from None

    def _save(self, user, token, previous=None):
        previous = previous or {}
        if not isinstance(token.get('access_token'), str) or not token['access_token']:
            raise AccountError('Spotify authorization failed.')
        refresh = token.get('refresh_token') or previous.get('refresh_token')
        scope = token.get('scope', previous.get('scope', ''))
        if not refresh or SCOPE not in scope.split():
            raise AccountError('Spotify did not grant playback access; reconnect.')
        saved = dict(access_token=token['access_token'], refresh_token=refresh,
                     scope=scope, expires_at=time.time()+int(token.get('expires_in', 3600)))
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO accounts VALUES (?,?)', (user, self._encrypt(saved)))
        return saved

    def complete(self, state, code=None, denied=False):
        # Serialize disconnect/new-login with an in-flight token exchange.
        with self.lock:
            return self._complete(state, code, denied)

    def _complete(self, state, code=None, denied=False):
        if not isinstance(state, str) or not 20 <= len(state) <= 128:
            raise AccountError('Invalid or expired authorization link.')
        with self.lock, self.db:
            digest = hashlib.sha256(state.encode()).hexdigest()
            row = self.db.execute('SELECT user,verifier,expires FROM states WHERE state=?', (digest,)).fetchone()
            self.db.execute('DELETE FROM states WHERE state=?', (digest,))
        if not row or row[2] < time.time():
            raise AccountError('Invalid or expired authorization link.')
        if denied or not isinstance(code, str) or not 1 <= len(code) <= 4096:
            raise AccountError('Authorization cancelled. Return to the bot to try again.')
        status, token = self._request('POST', 'https://accounts.spotify.com/api/token', data={
            'grant_type': 'authorization_code', 'client_id': self.client_id, 'code': code,
            'redirect_uri': self.redirect_uri, 'code_verifier': self._decrypt(row[1]),
        })
        if status != 200:
            raise AccountError('Spotify authorization failed. Request a new link in the bot.')
        self._save(row[0], token)

    def disconnect(self, user):
        with self.lock, self.db:
            self.db.execute('DELETE FROM accounts WHERE user=?', (user,))
            self.db.execute('DELETE FROM states WHERE user=?', (user,))

    def _refresh(self, user, token):
        status, payload = self._request('POST', 'https://accounts.spotify.com/api/token', data={
            'grant_type': 'refresh_token', 'refresh_token': token['refresh_token'], 'client_id': self.client_id,
        })
        if status == 400 and payload.get('error') == 'invalid_grant':
            self.disconnect(user)
            raise NotConnected('Reconnect Spotify with /connect_spotify.')
        if status != 200:
            raise AccountError('Spotify is temporarily unavailable.')
        return self._save(user, payload, token)

    def current(self, user):
        with self.lock:
            row = self.db.execute('SELECT token FROM accounts WHERE user=?', (user,)).fetchone()
            if not row:
                raise NotConnected('Connect Spotify with /connect_spotify.')
            token = self._decrypt(row[0])
            if token['expires_at'] <= time.time()+30:
                token = self._refresh(user, token)
            for attempt in range(2):
                status, payload = self._request('GET', 'https://api.spotify.com/v1/me/player/currently-playing',
                                                headers={'Authorization': 'Bearer '+token['access_token']})
                if status == 401 and attempt == 0:
                    token = self._refresh(user, token)
                    continue
                break
        if status == 204:
            return None
        if status in (401, 403):
            raise NotConnected('Playback access is unavailable; reconnect Spotify.')
        if status != 200:
            raise AccountError('Spotify is temporarily unavailable. Try again later.')
        track = payload.get('item') or {}
        if (not payload.get('is_playing') or payload.get('currently_playing_type') != 'track'
                or track.get('is_local') or not re.fullmatch(r'[A-Za-z0-9]{22}', str(track.get('id', '')))):
            return None
        song = Song(track['name'], ' & '.join(a['name'] for a in track.get('artists', [])),
                    track.get('album', {}).get('name', ''))
        song.duration_ms = track.get('duration_ms')
        song.isrc = track.get('external_ids', {}).get('isrc')
        images = track.get('album', {}).get('images', [])
        if images:
            song.cover_art = images[0]
        song.service_links = {'Spotify': 'https://open.spotify.com/track/'+track['id']}
        return song

    def close(self):
        self.db.close()
