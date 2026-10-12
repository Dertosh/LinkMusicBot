"""Persistent cache and local title search, independent of service credentials."""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from threading import Lock

from telegram import InlineKeyboardMarkup, InlineQueryResultArticle


def search_text(value):
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold().replace("'", "").replace("’", "")).split())


class LocalLibrary:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS queries (query TEXT PRIMARY KEY, payload TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS tracks (id TEXT PRIMARY KEY, title TEXT, terms TEXT, payload TEXT, updated REAL);
        """)

    @staticmethod
    def _decode(payload):
        results = []
        for data in json.loads(payload):
            data["reply_markup"] = InlineKeyboardMarkup.de_json(data["reply_markup"], None)
            results.append(InlineQueryResultArticle.de_json(data, None))
        return results

    def get(self, query):
        with self.lock:
            row = self.db.execute("SELECT payload FROM queries WHERE query=? AND updated>?",
                                  (query, time.time() - 7 * 86400)).fetchone()
            if row:
                return self._decode(row[0])
            if "://" in query:
                return None
            tokens = search_text(query).split()
            if not tokens:
                return None
            sql = "SELECT payload FROM tracks WHERE " + " AND ".join(
                "instr(terms, ?) > 0" for _ in tokens)
            sql += " ORDER BY (title=?) DESC, updated DESC LIMIT 2"
            rows = self.db.execute(sql, [*tokens, search_text(query)]).fetchall()
            return [self._decode(row[0])[0] for row in rows] or None

    def put(self, query, results):
        if not results:
            return
        now = time.time()
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO queries VALUES (?, ?, ?)",
                            (query, json.dumps([result.to_dict() for result in results]), now))
            for result in results:
                title = search_text(result.title)
                terms = search_text(result.title + " " + (result.description or ""))
                identifier = hashlib.sha256(terms.encode()).hexdigest()
                self.db.execute("INSERT OR REPLACE INTO tracks VALUES (?, ?, ?, ?, ?)",
                                (identifier, title, terms, json.dumps([result.to_dict()]), now))
            self.db.execute("DELETE FROM queries WHERE updated<?", (now - 7 * 86400,))
            self.db.execute("DELETE FROM queries WHERE rowid NOT IN "
                            "(SELECT rowid FROM queries ORDER BY updated DESC LIMIT 5000)")
