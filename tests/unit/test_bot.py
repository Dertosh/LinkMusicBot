import asyncio
import sys
import types
import unittest
from threading import BoundedSemaphore
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules["config"] = types.SimpleNamespace(secrets={})
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.security import QueryGuard
from linkmusicbot.models import Song
from telegram.error import BadRequest


class BotTests(unittest.TestCase):
    def test_title_search_resolves_missing_links_on_every_platform(self):
        services = []
        for name, url in [('Apple Music', 'https://music.apple.com/us/song/1'),
                          ('Spotify', 'https://open.spotify.com/track/1'),
                          ('YouTube', 'https://www.youtube.com/watch?v=IAuzNXGmkL4'),
                          ('Яндекс Музыка', 'https://music.yandex.ru/album/1/track/1')]:
            service = MagicMock()
            service.service_name.return_value = name
            service.search.return_value = []
            service.song_to_link.return_value = url
            services.append(service)
        song = Song('Цвет настроения синий', 'Philipp Kirkorov', '')
        song.service_links = {'Spotify': services[1].song_to_link.return_value}
        services[1].search.return_value = [song]
        self.bot.search_service = services[0]
        self.bot._music_services = services
        self.bot.make_iqr = lambda item: item
        results = self.bot.handle_search('Цвет настроения синий')
        for service in services:
            self.assertEqual(results[0].service_links[service.service_name()], service.song_to_link.return_value)
        services[1].song_to_link.assert_not_called()
        services[0].song_to_link.assert_called_once()
        services[2].song_to_link.assert_called_once()
        services[3].song_to_link.assert_called_once()

    def test_refresh_keeps_verified_direct_link_when_provider_falls_back(self):
        from linkmusicbot.presentation import build_result
        from telegram import InlineKeyboardButton
        service = MagicMock()
        service.service_name.return_value = "YouTube"
        service.can_handle_link.return_value = True
        self.bot._music_services = [service]
        song = Song("Song", "Artist", "")
        cached = build_result(song, [[InlineKeyboardButton("YouTube", url="https://youtube.com/watch?v=OL1lo6zBGbM")]])
        fresh = build_result(song, [[InlineKeyboardButton("YouTube", url="https://www.youtube.com/results?search_query=Song")]])
        retained = self.bot._retain_direct_links(fresh, cached)
        self.assertEqual(retained.reply_markup.inline_keyboard[0][0].url, cached.reply_markup.inline_keyboard[0][0].url)

    def test_provider_search_retains_known_local_prefix_candidates(self):
        import tempfile
        from pathlib import Path
        from linkmusicbot.library import LocalLibrary
        from linkmusicbot.presentation import build_result
        with tempfile.TemporaryDirectory() as folder:
            library = LocalLibrary(str(Path(folder) / "cache.sqlite3"))
            try:
                library.put("known", [build_result(Song("DEMON'S SHOT", "Aiobahn +81", ""), [])])
                library.put("legacy", [build_result(Song("DEMON'S SHOT (Official MV)", "Uploader", ""), [])])
                service = MagicMock()
                service.service_name.return_value = "Apple Music"
                service.search.return_value = [Song("Demons", "Imagine Dragons", "")]
                self.bot.search_service = service
                self.bot._music_services = [service]
                self.bot._library = library
                results = self.bot.handle_search("demon's")
                self.assertIn("DEMON'S SHOT", [r.title for r in results])
                self.assertNotIn("DEMON'S SHOT (Official MV)", [r.title for r in results])
            finally:
                library.db.close()
    def test_cover_link_keeps_selected_cover_first_and_adds_other_performers(self):
        from linkmusicbot.presentation import build_result
        cover = build_result(Song("Rabbit Hole (Cover by Sati Akura)", "Sati Akura", ""), [])
        duplicate = build_result(Song("Rabbit Hole", "Sati Akura", ""), [])
        other = build_result(Song("Rabbit Hole", "Other Performer", ""), [])
        self.bot.handle_link = MagicMock(return_value=cover)
        self.bot.handle_search = MagicMock(return_value=[duplicate, other])
        results = self.bot._link_results("https://youtu.be/vpcra3YEAN0")
        self.assertEqual(results, [cover, other])
        self.bot.handle_search.assert_called_once_with("Rabbit Hole")
    def test_pagination_reuses_cached_snapshot_without_provider_calls(self):
        cached = list(range(15))
        self.bot._guard.put("song", cached)
        self.bot._build_results = MagicMock()
        update = MagicMock()
        update.inline_query.query = "song"
        update.inline_query.offset = "10"
        update.inline_query.from_user.id = 1
        update.inline_query.answer = AsyncMock()
        asyncio.run(self.bot.inline_query_handler(update, None))
        update.inline_query.answer.assert_awaited_once_with(cached[10:], cache_time=60, is_personal=True)
        self.bot._build_results.assert_not_called()

    def test_unrelated_provider_results_are_filtered(self):
        service = MagicMock()
        service.service_name.return_value = "Apple Music"
        service.search.return_value = [Song("Miraaž", "STEFAN", ""), Song("Mājas", "MUUD", "")]
        self.bot.search_service = service
        self.bot._music_services = [service]
        self.bot.make_iqr = lambda item: item
        self.assertEqual([s.title for s in self.bot.handle_search("Miraaž Stefan")], ["Miraaž"])
    def test_multi_platform_search_merges_links_and_keeps_versions(self):
        apple, spotify = MagicMock(), MagicMock()
        apple.service_name.return_value = "Apple Music"
        spotify.service_name.return_value = "Spotify"
        original = Song("Song", "Artist", "Album")
        original.service_links = {"Apple Music": "https://music.apple.com/song/1"}
        duplicate = Song("Song", "Artist", "Album")
        duplicate.service_links = {"Spotify": "https://open.spotify.com/track/1"}
        remix = Song("Song (Remix)", "Artist", "Album")
        remix.service_links = {"Spotify": "https://open.spotify.com/track/2"}
        apple.search.return_value = [original]
        spotify.search.return_value = [duplicate, remix]
        self.bot.search_service = apple
        self.bot._music_services = [apple, spotify]
        self.bot.make_iqr = lambda item: item
        items = self.bot.handle_search("Song")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].service_links["Spotify"], "https://open.spotify.com/track/1")
        self.assertEqual(items[1].service_links["Spotify"], "https://open.spotify.com/track/2")

    def test_more_than_two_candidates_and_short_title_prefix(self):
        service = MagicMock()
        service.service_name.return_value = "Apple Music"
        service.search.return_value = [Song("Demon's Long Title", "A", ""),
            Song("Demon's", "B", ""), Song("Demons", "C", ""), Song("Demon's Shot", "D", "")]
        self.bot.search_service = service
        self.bot._music_services = [service]
        self.bot.make_iqr = lambda item: item
        items = self.bot.handle_search("demon's")
        self.assertEqual(len(items), 4)
        self.assertIn(items[0].title, ["Demons", "Demon's"])
        self.assertIn("Demon's Shot", [s.title for s in items])
    def test_all_search_services_prioritize_original_beyond_first_two(self):
        for name in ["Apple Music", "Spotify", "YouTube", "Яндекс Музыка"]:
            with self.subTest(service=name):
                service = MagicMock()
                service.service_name.return_value = name
                songs = [Song("Song (Remix)", "Artist", "Album"),
                         Song("Song (Live)", "Artist", "Album"), Song("Song", "Artist", "Album")]
                service.search.return_value = songs
                self.bot.search_service = service
                self.bot._music_services = [service]
                self.bot.make_iqr = lambda item: item
                results = self.bot.handle_search("Song Artist")
                self.assertEqual(results[0].title, "Song")
                service.search.assert_called_with("song artist", n=10)
                results = self.bot.handle_search("Song Artist Remix")
                self.assertEqual(results[0].title, "Song (Remix)")

    def test_selected_variant_keeps_its_message_and_service_link(self):
        service = MagicMock()
        service.service_name.return_value = "Apple Music"
        service.can_handle_link.return_value = True
        original = Song("Song", "Artist", "Album")
        remix = Song("Song (Remix)", "Artist", "Album")
        original.service_links = {"Apple Music": "https://music.apple.com/jp/song/original/1"}
        remix.service_links = {"Apple Music": "https://music.apple.com/jp/song/remix/2"}
        service.search.return_value = [original, remix]
        self.bot.search_service = service
        self.bot._music_services = [service]
        results = self.bot.handle_search("Song")
        self.assertNotEqual(results[0].id, results[1].id)
        for result, item in zip(results, [original, remix]):
            self.assertEqual(result.title, item.title)
            self.assertIn(item.title, result.input_message_content.message_text)
            self.assertEqual(result.reply_markup.inline_keyboard[0][0].url,
                             item.service_links["Apple Music"])
        service.object_to_link.assert_not_called()

    def test_help_contains_upstream_attribution(self):
        for language in ("ru", "en"):
            update, context = MagicMock(), MagicMock()
            update.effective_user.language_code = language
            update.effective_message.reply_text = AsyncMock()
            context.bot.username = "SongHubbot"
            asyncio.run(self.bot.message_handler(update, context))
            text = update.effective_message.reply_text.call_args.args[0]
            self.assertIn("@LinkMusicBot", text)
            self.assertIn("https://github.com/jarhill0/LinkMusicBot", text)

    def test_profile_descriptions_fit_telegram_limits(self):
        from linkmusicbot.about import DESCRIPTIONS, SHORT_DESCRIPTIONS
        for text in DESCRIPTIONS.values():
            self.assertLessEqual(len(text), 512)
        for text in SHORT_DESCRIPTIONS.values():
            self.assertLessEqual(len(text), 120)

    def setUp(self):
        self.bot = LinkMusicBot.__new__(LinkMusicBot)
        self.bot._guard = QueryGuard()
        self.bot._work_slots = BoundedSemaphore(2)

    def test_worker_slot_is_released_after_error(self):
        self.bot.handle_link = MagicMock(side_effect=ValueError("failure"))
        with self.assertRaises(ValueError):
            self.bot._build_results("song")
        self.assertTrue(self.bot._work_slots.acquire(False))
        self.assertTrue(self.bot._work_slots.acquire(False))
        self.assertFalse(self.bot._work_slots.acquire(False))

    def test_busy_workers_do_not_call_services(self):
        self.bot._work_slots.acquire()
        self.bot._work_slots.acquire()
        self.bot.handle_link = MagicMock()
        self.assertEqual(self.bot._build_results("song"), [])
        self.bot.handle_link.assert_not_called()

    def test_memory_cache_is_available_even_when_workers_busy(self):
        self.bot._work_slots.acquire()
        self.bot._work_slots.acquire()
        self.bot._guard.put("song", ["cached"])
        self.assertEqual(self.bot._build_results("song"), ["cached"])

    def test_unsupported_url_is_not_sent_to_text_search(self):
        self.bot.handle_link = MagicMock(return_value=None)
        self.bot.handle_search = MagicMock()
        self.assertEqual(self.bot._build_results("https://example.com/track"), [])
        self.bot.handle_search.assert_not_called()

    def test_results_are_saved_in_persistent_library(self):
        self.bot._library = MagicMock()
        self.bot._library.get.return_value = None
        self.bot.handle_link = MagicMock(return_value="result")
        self.assertEqual(self.bot._build_results("song"), ["result"])
        self.bot._library.put.assert_called_once_with("song", ["result"])

    def test_source_link_is_reused_without_api_call(self):
        service = MagicMock()
        service.service_name.return_value = "Spotify"
        service.can_handle_link.return_value = True
        self.bot._music_services = [service]
        song = Song("Title", "Artist", "Album")
        song.service_links = {"Spotify": "https://open.spotify.com/track/123"}
        result = self.bot.make_iqr(song)
        service.object_to_link.assert_not_called()
        self.assertEqual(result.reply_markup.inline_keyboard[0][0].url, song.service_links["Spotify"])

    def test_one_broken_service_does_not_remove_other_buttons(self):
        broken, working = MagicMock(), MagicMock()
        broken.service_name.return_value = "YouTube"
        broken.object_to_link.side_effect = ValueError("failed")
        working.service_name.return_value = "Spotify"
        working.object_to_link.return_value = "https://open.spotify.com/track/123"
        working.can_handle_link.return_value = True
        self.bot._music_services = [broken, working]
        result = self.bot.make_iqr(Song("Title", "Artist", "Album"))
        self.assertEqual(result.reply_markup.inline_keyboard[0][0].text, "YouTube")
        self.assertIn("https://music.youtube.com/search?", result.reply_markup.inline_keyboard[0][0].url)
        self.assertEqual(result.reply_markup.inline_keyboard[1][0].text, "Spotify")

    def test_untrusted_cover_is_not_used_in_preview(self):
        self.bot._music_services = []
        song = Song("Title", "Artist", "Album")
        song.cover_art = {"url": "https://evil.example/cover.jpg"}
        result = self.bot.make_iqr(song)
        self.assertIsNone(result.thumbnail_url)
        self.assertTrue(result.input_message_content.link_preview_options.is_disabled)

    def test_cached_inline_query_does_not_consume_rate_limit(self):
        self.bot._guard.put("song", ["cached"])
        self.bot._guard.allow = MagicMock(return_value=False)
        update = MagicMock()
        update.inline_query.query = "song"
        update.inline_query.from_user.id = 1
        update.inline_query.answer = AsyncMock()
        asyncio.run(self.bot.inline_query_handler(update, None))
        self.bot._guard.allow.assert_not_called()
        update.inline_query.answer.assert_awaited_once_with(["cached"], cache_time=60, is_personal=True)

    def test_inline_failure_answers_without_caching_empty_response(self):
        self.bot._build_results = MagicMock(side_effect=ValueError("secret failure"))
        update = MagicMock()
        update.inline_query.query = "song"
        update.inline_query.from_user.id = 1
        update.inline_query.answer = AsyncMock()
        with patch("linkmusicbot.bot.logging.warning") as log:
            asyncio.run(self.bot.inline_query_handler(update, None))
        update.inline_query.answer.assert_awaited_once_with([], cache_time=0, is_personal=True)
        self.assertNotIn("secret failure", str(log.call_args))

    def test_error_logs_redact_credentials_and_urls(self):
        context = MagicMock()
        context.error = BadRequest("failed test-secret https://example.com/token")
        with patch.dict("linkmusicbot.bot.secrets", telegram_token="test-secret"), \
                patch("linkmusicbot.bot.logging.warning") as log:
            asyncio.run(self.bot.error_handler(None, context))
        self.assertNotIn("test-secret", str(log.call_args))
        self.assertNotIn("https://example.com", str(log.call_args))
