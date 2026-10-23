"""Bounded outbound HTTP and in-process abuse protection."""
import ipaddress
import socket
import time
from collections import OrderedDict, deque
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from threading import Lock
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
import sqlite3
from pathlib import Path
from .text_encoding import repair_text

APPLE_HOSTS = {"itunes.apple.com", "music.apple.com"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
MAX_BYTES = 2 * 1024 * 1024

_http_session = ContextVar('music_http_session', default=None)


@contextmanager
def http_session_scope():
    """Reuse connections within one provider job; never share across workers."""
    holder = [None]
    token = _http_session.set(holder)
    try:
        yield
    finally:
        if holder[0] is not None:
            holder[0].close()
        _http_session.reset(token)


def youtube_music_url(url):
    if not valid_url(url, YOUTUBE_HOSTS):
        return url
    parsed = urlparse(url)
    if parsed.hostname == 'youtu.be':
        return 'https://music.youtube.com/watch?' + urlencode({'v': parsed.path.strip('/')})
    if parsed.path == '/results':
        params = dict(parse_qsl(parsed.query))
        return 'https://music.youtube.com/search?' + urlencode({'q': params.get('search_query', '')})
    return urlunparse(('https', 'music.youtube.com', parsed.path, '', parsed.query, ''))
_deadline = ContextVar("request_deadline", default=None)


def normalize_query(query):
    query = repair_text(query.strip())
    if query.startswith(r'https\://'):
        query = 'https://' + query[len(r'https\://'):]
    hosts = APPLE_HOSTS | YOUTUBE_HOSTS | {"open.spotify.com", "music.yandex.ru", "music.yandex.com", "music.yandex.by", "music.yandex.kz"}
    if valid_url(query, hosts):
        parsed = urlparse(query)
        # Preserve semantic selectors (Apple track i, YouTube v/list).
        params = sorted((key, value) for key, value in parse_qsl(parsed.query)
                        if key not in {"si", "feature", "share", "app", "spm"}
                        and not key.startswith("utm_"))
        return urlunparse(("https", parsed.hostname, parsed.path, "", urlencode(params), ""))
    return query if "://" in query else " ".join(query.split()).casefold()


def valid_url(url, hosts):
    try:
        parsed = urlparse(url)
        return (len(url) <= 2048 and not any(ord(c) <= 32 for c in url)
                and parsed.scheme == "https" and parsed.hostname in hosts
                and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None)
    except (ValueError, TypeError):
        return False


def check_budget():
    deadline = _deadline.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("Request budget exceeded")


@contextmanager
def request_budget(seconds=30):
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def fetch_text(url, hosts, params=None):
    """Validate every redirect; bound decompressed data and elapsed time.

    TLS verification remains enabled. Do not use untrusted DNS or proxies.
    """
    deadline = min(_deadline.get() or float("inf"), time.monotonic() + 25)
    holder = _http_session.get()
    if holder is not None and holder[0] is None:
        holder[0] = requests.Session()
    manager = nullcontext(holder[0]) if holder is not None else requests.Session()
    with manager as session:
        session.trust_env = False  # no implicit proxies or .netrc credentials
        session.cookies.clear()  # connection reuse must not persist site cookies
        for _ in range(4):
            check_budget()
            if not valid_url(url, hosts):
                raise ValueError("Disallowed URL")
            addresses = socket.getaddrinfo(urlparse(url).hostname, 443,
                                           type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global
                                    for a in addresses):
                raise ValueError("Non-public destination")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("HTTP deadline exceeded")
            with session.get(url, params=params, stream=True,
                             allow_redirects=False,
                             timeout=(min(5, remaining), min(5, remaining))) as response:
                params = None
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(response.url, response.headers["Location"])
                    continue
                response.raise_for_status()
                if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
                    raise ValueError("Response too large")
                data = bytearray()
                for chunk in response.iter_content(16384):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("HTTP deadline exceeded")
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("Response too large")
                content_type = response.headers.get("Content-Type", "")
                encoding = response.encoding if "charset=" in content_type.lower() else "utf-8"
                return data.decode(encoding or "utf-8", errors="replace")
        raise ValueError("Too many redirects")


class QueryGuard:
    def __init__(self):
        self.lock = Lock()
        self.users = OrderedDict()
        self.global_requests = deque()
        self.cache = OrderedDict()
        # Fixed stripes bound lock memory and coalesce simultaneous cache misses.
        self.query_locks = [Lock() for _ in range(32)]

    def query_lock(self, query):
        return self.query_locks[hash(query) % len(self.query_locks)]

    def allow(self, user, min_interval=5):
        now = time.monotonic()
        with self.lock:
            while self.global_requests and self.global_requests[0] <= now - 60:
                self.global_requests.popleft()
            if now - self.users.get(user, -float("inf")) < min_interval:
                return False
            if len(self.global_requests) >= 10:
                return False
            self.users[user] = now
            self.users.move_to_end(user)
            if len(self.users) > 4096:
                self.users.popitem(last=False)
            self.global_requests.append(now)
            return True

    def get(self, query):
        with self.lock:
            entry = self.cache.get(query)
            if entry is not None and entry[0] > time.monotonic():
                self.cache.move_to_end(query)
                return entry[1]
            self.cache.pop(query, None)
            return None

    def put(self, query, results):
        with self.lock:
            self.cache[query] = (time.monotonic() + 1800, results)
            self.cache.move_to_end(query)
            if len(self.cache) > 256:
                self.cache.popitem(last=False)


class QuotaExceeded(ValueError):
    pass


class SearchQuota:
    """Reserve a bounded number of YouTube searches in a rolling 24-hour window."""
    def __init__(self, limit=100, path=None):
        self.limit = max(0, int(limit))
        self.calls = deque()
        self.lock = Lock()
        self.db = None
        self.blocked_until = 0
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, timeout=5, check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS youtube_search_calls (called REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS youtube_search_calls_time ON youtube_search_calls(called);
                CREATE TABLE IF NOT EXISTS youtube_quota_state (id INTEGER PRIMARY KEY, blocked_until REAL NOT NULL);
            """)

    def reserve(self):
        if self.db is not None:
            now = time.time()
            with self.lock:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    self.db.execute("DELETE FROM youtube_search_calls WHERE called<=?", (now - 86400,))
                    row = self.db.execute("SELECT blocked_until FROM youtube_quota_state WHERE id=1").fetchone()
                    count = self.db.execute("SELECT count(*) FROM youtube_search_calls").fetchone()[0]
                    if (row and row[0] > now) or (self.limit and count >= self.limit):
                        raise QuotaExceeded("YouTube search budget exhausted")
                    self.db.execute("INSERT INTO youtube_search_calls VALUES (?)", (now,))
                    self.db.commit()
                except BaseException:
                    self.db.rollback()
                    raise
            return
        if self.blocked_until > time.time():
            raise QuotaExceeded("YouTube API quota exhausted")
        if self.limit == 0:
            return
        now = time.monotonic()
        with self.lock:
            while self.calls and self.calls[0] <= now - 86400:
                self.calls.popleft()
            if len(self.calls) >= self.limit:
                raise QuotaExceeded("YouTube search budget exhausted")
            self.calls.append(now)

    def mark_exhausted(self, seconds=86400):
        until = time.time() + seconds
        with self.lock:
            if self.db is not None:
                with self.db:
                    self.db.execute("INSERT INTO youtube_quota_state VALUES (1, ?) "
                                    "ON CONFLICT(id) DO UPDATE SET blocked_until=max(blocked_until, excluded.blocked_until)", (until,))
            else:
                self.blocked_until = until

    def status(self):
        now = time.time()
        with self.lock:
            if self.db is not None:
                count = self.db.execute("SELECT count(*) FROM youtube_search_calls WHERE called>?", (now - 86400,)).fetchone()[0]
                row = self.db.execute("SELECT blocked_until FROM youtube_quota_state WHERE id=1").fetchone()
                blocked = row[0] if row else 0
            else:
                count, blocked = len(self.calls), self.blocked_until
        return {"used": count, "limit": self.limit, "blocked_until": blocked if blocked > now else 0}
