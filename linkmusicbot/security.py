"""Bounded outbound HTTP and in-process abuse protection."""
import ipaddress
import socket
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

APPLE_HOSTS = {"itunes.apple.com", "music.apple.com"}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
MAX_BYTES = 2 * 1024 * 1024
_deadline = ContextVar("request_deadline", default=None)


def normalize_query(query):
    query = query.strip()
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
    with requests.Session() as session:
        session.trust_env = False  # no implicit proxies or .netrc credentials
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
                return data.decode(response.encoding or "utf-8", errors="replace")
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

    def allow(self, user):
        now = time.monotonic()
        with self.lock:
            while self.global_requests and self.global_requests[0] <= now - 60:
                self.global_requests.popleft()
            if now - self.users.get(user, -float("inf")) < 5:
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
    def __init__(self, limit=100):
        self.limit = max(0, int(limit))
        self.calls = deque()
        self.lock = Lock()

    def reserve(self):
        if self.limit == 0:
            return
        now = time.monotonic()
        with self.lock:
            while self.calls and self.calls[0] <= now - 86400:
                self.calls.popleft()
            if len(self.calls) >= self.limit:
                raise QuotaExceeded("YouTube search budget exhausted")
            self.calls.append(now)
