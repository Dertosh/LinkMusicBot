import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle,
                      InputTextMessageContent, LinkPreviewOptions)
from linkmusicbot.library import LocalLibrary, search_text


def track(title="The Sun", artist="Maroon 5", link="https://music.youtube.com/watch?v=abcdefghijk"):
    return InlineQueryResultArticle(
        id=title, title=title, description=artist,
        thumbnail_url="https://i.scdn.co/image/cover",
        input_message_content=InputTextMessageContent(
            title, link_preview_options=LinkPreviewOptions(is_disabled=True)),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("YouTube", url=link)]]))


class LibraryTests(unittest.TestCase):
    def test_legacy_cached_web_preview_is_disabled_without_losing_thumbnail(self):
        result = track()
        data = result.to_dict()
        data['input_message_content']['link_preview_options'] = {
            'url': 'https://i.scdn.co/image/cover', 'prefer_large_media': True}
        import json
        restored = self.library._decode(json.dumps([data]))[0]
        self.assertTrue(restored.input_message_content.link_preview_options.is_disabled)
        self.assertEqual(restored.thumbnail_url, result.thumbnail_url)

    def test_local_catalog_handles_diacritics_and_fullwidth_prefix(self):
        self.library.put("known", [track("Jóga", "Björk")])
        self.assertEqual(self.library.get("joga bjork")[0].title, "Jóga")
        self.assertEqual(self.library.get("ＪＯＧＡ")[0].description, "Björk")

    def test_original_precedes_recent_versions_in_local_search(self):
        self.library.put("original", [track("Song", "Artist")])
        for title in ["Song (Remix)", "Song (Live)", "Song (Acoustic)"]:
            self.library.put(title, [track(title, "Artist")])
        self.assertEqual(self.library.get("song artist")[0].title, "Song")
        self.assertEqual(self.library.get("song artist remix")[0].title, "Song (Remix)")

    def test_feature_credit_does_not_demote_original(self):
        self.library.put("original", [track("Song (feat. Guest)", "Artist")])
        self.library.put("remix", [track("Song (Remix)", "Artist")])
        self.assertEqual(self.library.get("song artist")[0].title, "Song (feat. Guest)")

    def test_old_cached_order_is_ranked_without_changing_links(self):
        remix = track("Song (Remix)", "Artist", "https://music.youtube.com/watch?v=remix")
        original = track("Song", "Artist", "https://music.youtube.com/watch?v=original")
        self.library.put("song artist", [remix, original])
        results = self.library.get("song artist")
        self.assertEqual(results[0].to_dict(), original.to_dict())
        self.assertEqual(results[1].to_dict(), remix.to_dict())

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.library = LocalLibrary(str(Path(folder.name) / "nested/music.sqlite3"))
        self.addCleanup(self.library.db.close)

    def test_empty_result_is_cached_and_lazily_rechecked(self):
        self.library.put("missing", [])
        self.assertEqual(self.library.get("missing"), [])
        self.assertFalse(self.library.needs_refresh("missing"))
        self.assertEqual(self.library.db.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 1)

    def test_serialization_preserves_links_cover_and_message(self):
        result = track()
        self.library.put("query", [result])
        self.assertEqual(self.library.get("query")[0].to_dict(), result.to_dict())

    def test_same_track_updates_link_without_duplicate(self):
        self.library.put("first", [track()])
        updated = track(link="https://music.youtube.com/watch?v=12345678901")
        self.library.put("second", [updated])
        self.assertEqual(self.library.db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 1)
        self.assertEqual(self.library.get("maroon")[0].reply_markup.inline_keyboard[0][0].url,
                         "https://music.youtube.com/watch?v=12345678901")

    def test_all_search_terms_are_required(self):
        self.library.put("query", [track()])
        self.assertEqual(self.library.get("sun maroon")[0].title, "The Sun")
        self.assertIsNone(self.library.get("sun metallica"))

    def test_exact_title_ranks_before_newer_partial_match(self):
        with patch("linkmusicbot.library.time.time", return_value=100):
            self.library.put("old", [track()])
        with patch("linkmusicbot.library.time.time", return_value=200):
            self.library.put("new", [track("The Sun Returns")])
            self.assertEqual(self.library.get("the sun")[0].title, "The Sun")

    def test_local_results_use_configured_limit(self):
        for number in range(4):
            self.library.put(str(number), [track("Sun " + str(number))])
        self.assertEqual(len(self.library.get("sun")), 4)
        self.library.result_limit = 3
        self.assertEqual(len(self.library.get("sun")), 3)

    def test_unicode_and_apostrophes_are_normalized(self):
        self.library.put("query", [track("DEMON’S SHOT", "Исполнитель")])
        self.assertEqual(self.library.get("demons-shot исполнитель")[0].title, "DEMON’S SHOT")
        self.assertEqual(search_text("  DEMON'S   SHOT! "), "demons shot")

    def test_empty_and_sql_like_queries_do_not_match_all_rows(self):
        self.library.put("query", [track()])
        for query in ("", " ", "!!!", "' OR 1=1 --"):
            with self.subTest(query=query):
                self.assertIsNone(self.library.get(query))
        self.assertEqual(self.library.db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 1)

    def test_old_query_remains_available_but_requires_lazy_refresh(self):
        url = "https://music.apple.com/song/123"
        with patch("linkmusicbot.library.time.time", return_value=100):
            self.library.put(url, [track()])
        with patch("linkmusicbot.library.time.time", return_value=100 + 7 * 86400):
            self.assertEqual(self.library.get(url)[0].title, "The Sun")
            self.assertTrue(self.library.needs_refresh(url))
        with patch("linkmusicbot.library.time.time", return_value=100 + 365 * 86400):
            self.library.put("new", [track("Other")])
            self.assertEqual(self.library.get("the sun")[0].title, "The Sun")

    def test_query_pruning_keeps_permanent_catalog(self):
        self.library.put("initial", [track()])
        with self.library.db:
            self.library.db.executemany("INSERT INTO queries VALUES (?, ?, ?)",
                                       [(f"q{i}", "[]", 100) for i in range(5001)])
        with patch("linkmusicbot.library.time.time", return_value=101):
            self.library.put("latest", [track("Other")])
        self.assertEqual(self.library.db.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 5000)
        self.assertEqual(self.library.db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 2)

    def test_concurrent_reads_and_writes(self):
        def operation(number):
            query = f"query-{number}"
            self.library.put(query, [track(f"Song {number}")])
            return self.library.get(query)[0].title
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(operation, range(16)))
        self.assertEqual(results, [f"Song {number}" for number in range(16)])
