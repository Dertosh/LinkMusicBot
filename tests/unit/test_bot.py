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
        self.assertIn("/results?", result.reply_markup.inline_keyboard[0][0].url)
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
