"""Persistent cache and local title search, independent of service credentials."""
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from threading import Lock

from telegram import InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, LinkPreviewOptions
from .search_ranking import rank_results, search_rank
from .settings import secrets
from .security import normalize_query
from .text_encoding import repair_text
from .recording_match import romanized, romanized_variants
from .cache_revision import search_revision


def search_text(value):
    value = unicodedata.normalize("NFKC", repair_text(value))
    value = "".join(c for c in unicodedata.normalize("NFKD", value)
                    if not ("\u0300" <= c <= "\u036f"))
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold().replace("'", "").replace("’", "")).split())


class LocalLibrary:
    def __init__(self, path, refresh_seconds=None, result_limit=None):
        self.refresh_seconds = refresh_seconds or secrets.get("cache_refresh_seconds", 43200)
        self.result_limit = result_limit or 50
        self.revision = search_revision()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.create_function("search_priority", 2, lambda payload, query:
                                self._priority(payload, query))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS queries (query TEXT PRIMARY KEY, payload TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS tracks (id TEXT PRIMARY KEY, title TEXT, terms TEXT, payload TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS refresh_attempts (query TEXT PRIMARY KEY, attempted REAL);
            CREATE TABLE IF NOT EXISTS search_cache_versions
                (query TEXT PRIMARY KEY, result_revision TEXT, attempt_revision TEXT);
        """)

    @staticmethod
    def _priority(payload, query):
        relevance, preferred, _ = search_rank(json.loads(payload)[0]["title"], query)
        return relevance * 2 + preferred

    @staticmethod
    def _decode(payload):
        from .security import youtube_music_url
        results = []
        for data in json.loads(payload):
            content = data.get('input_message_content', {})
            if isinstance(content, dict) and 'message_text' in content:
                data['input_message_content'] = InputTextMessageContent(
                    content['message_text'], link_preview_options=LinkPreviewOptions(is_disabled=True))
            markup = data.get("reply_markup") or {"inline_keyboard": []}
            for row in markup.get("inline_keyboard", []):
                for button in row:
                    if button.get("text") == "YouTube" and button.get("url"):
                        button["url"] = youtube_music_url(button["url"])
            data["reply_markup"] = InlineKeyboardMarkup.de_json(markup, None)
            results.append(InlineQueryResultArticle.de_json(data, None))
        return results

    def get(self, query):
        query = normalize_query(query)
        with self.lock:
            row = self.db.execute("SELECT payload FROM queries WHERE query=?", (query,)).fetchone()
            if row:
                return rank_results(self._decode(row[0]), query)
        return self.get_local(query)

    def get_local(self, query):
        query = normalize_query(query)
        with self.lock:
            if "://" in query:
                return None
            tokens = search_text(query).split()
            if not tokens:
                return None
            sql = "SELECT payload FROM tracks WHERE " + " AND ".join(
                "instr(terms, ?) > 0" for _ in tokens)
            sql += " ORDER BY search_priority(payload, ?) DESC, (title=?) DESC, length(title), updated DESC LIMIT ?"
            rows = self.db.execute(sql, [*tokens, query, search_text(query), self.result_limit]).fetchall()
            return [self._decode(row[0])[0] for row in rows] or None

    def put(self, query, results):
        query = normalize_query(query)
        now = time.time()
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO queries VALUES (?, ?, ?)",
                            (query, json.dumps([result.to_dict() for result in results]), now))
            self.db.execute('INSERT INTO search_cache_versions(query,result_revision) VALUES (?,?) '
                            'ON CONFLICT(query) DO UPDATE SET result_revision=excluded.result_revision',
                            (query,self.revision))
            for result in results:
                title = search_text(result.title)
                terms = search_text(result.title + " " + (result.description or ""))
                identifier = hashlib.sha256(terms.encode()).hexdigest()
                for latin in romanized_variants(result.title+' '+(result.description or '')):
                    latin_terms = search_text(latin)
                    if latin_terms and latin_terms not in terms:
                        terms += ' '+latin_terms
                self.db.execute("INSERT OR REPLACE INTO tracks VALUES (?, ?, ?, ?, ?)",
                                (identifier, title, terms, json.dumps([result.to_dict()]), now))
            self.db.execute("DELETE FROM queries WHERE rowid NOT IN "
                            "(SELECT rowid FROM queries ORDER BY updated DESC LIMIT 5000)")
            self.db.execute("DELETE FROM refresh_attempts WHERE attempted<?", (now - 86400,))
            self.db.execute('DELETE FROM search_cache_versions WHERE query NOT IN (SELECT query FROM queries) '
                            'AND query NOT IN (SELECT query FROM refresh_attempts)')

    def needs_refresh(self, query):
        query = normalize_query(query)
        with self.lock:
            row = self.db.execute("SELECT updated FROM queries WHERE query=?", (query,)).fetchone()
            attempt = self.db.execute("SELECT attempted FROM refresh_attempts WHERE query=?", (query,)).fetchone()
            version = self.db.execute('SELECT result_revision,attempt_revision FROM search_cache_versions WHERE query=?', (query,)).fetchone()
        now = time.time()
        stale = not row or row[0] <= now-self.refresh_seconds or not version or version[0] != self.revision
        retry_allowed = not attempt or not version or version[1] != self.revision or attempt[0] <= now-60
        return stale and retry_allowed

    def mark_refresh(self, query):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO refresh_attempts VALUES (?, ?)",
                            (normalize_query(query), time.time()))
            self.db.execute('INSERT INTO search_cache_versions(query,attempt_revision) VALUES (?,?) '
                            'ON CONFLICT(query) DO UPDATE SET attempt_revision=excluded.attempt_revision',
                            (normalize_query(query),self.revision))
