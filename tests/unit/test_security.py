import asyncio
import socket
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Never load a developer's real credentials during tests.
sys.modules["config"] = types.SimpleNamespace(secrets={})
from linkmusicbot import security
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.services import AppleMusic, Spotify, YouTube
from linkmusicbot.models import Song


def response(url, status=200, chunks=(b"hello",), headers=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.url = url
    result.status_code = status
    result.headers = headers or {}
    result.encoding = "utf-8"
    result.iter_content.return_value = iter(chunks)
    return result


class HTTPTests(unittest.TestCase):
    def test_utf8_music_metadata_without_charset_ignores_latin1_default(self):
        for text in ["Miraaž", "Beyoncé", "Она не твоя", "快眠!安眠!スヤリスト生活"]:
            with self.subTest(text=text):
                reply = response("https://music.apple.com/", chunks=(text.encode("utf8"),),
                                 headers={"Content-Type": "text/html"})
                reply.encoding = "ISO-8859-1"
                self.session.get.return_value = reply
                self.assertEqual(security.fetch_text(reply.url, security.APPLE_HOSTS), text)

    def test_explicit_http_charset_is_respected(self):
        reply = response("https://music.apple.com/", chunks=("Beyoncé".encode("latin1"),),
                         headers={"Content-Type": "text/html; charset=iso-8859-1"})
        reply.encoding = "iso-8859-1"
        self.session.get.return_value = reply
        self.assertEqual(security.fetch_text(reply.url, security.APPLE_HOSTS), "Beyoncé")

    def setUp(self):
        self.session_patch = patch("linkmusicbot.security.requests.Session")
        self.session = self.session_patch.start().return_value.__enter__.return_value
        self.addCleanup(self.session_patch.stop)
        self.dns_patch = patch("linkmusicbot.security.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ])
        self.dns = self.dns_patch.start()
        self.addCleanup(self.dns_patch.stop)

    def test_reject_unsafe_urls_before_network(self):
        for url in ("http://youtube.com/watch?v=x", "https://youtube.com.evil.test/",
                    "https://user:pass@youtube.com/", "https://youtube.com:444/",
                    "https://127.0.0.1/", "https://youtube.com/\nfoo"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                security.fetch_text(url, security.YOUTUBE_HOSTS)
        self.session.get.assert_not_called()

    def test_redirect_to_private_or_external_host_is_rejected(self):
        for target in ("https://127.0.0.1/", "https://evil.test/", "http://youtube.com/"):
            self.session.get.reset_mock()
            self.session.get.return_value = response(
                "https://youtu.be/x", 302, headers={"Location": target})
            with self.assertRaises(ValueError):
                security.fetch_text("https://youtu.be/x", security.YOUTUBE_HOSTS)
            self.assertEqual(self.session.get.call_count, 1)

    def test_allowed_redirect_is_followed_without_original_params(self):
        self.session.get.side_effect = [
            response("https://youtu.be/x", 302, headers={
                "Location": "https://www.youtube.com/watch?v=x"}),
            response("https://www.youtube.com/watch?v=x"),
        ]
        self.assertEqual(security.fetch_text("https://youtu.be/x",
                                             security.YOUTUBE_HOSTS), "hello")
        self.assertFalse(self.session.trust_env)
        self.assertFalse(self.session.get.call_args.kwargs["allow_redirects"])

    def test_private_dns_is_rejected(self):
        self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                  ("192.168.1.1", 443))]
        with self.assertRaises(ValueError):
            security.fetch_text("https://youtube.com/", security.YOUTUBE_HOSTS)
        self.session.get.assert_not_called()

    def test_decompressed_body_size_is_bounded(self):
        self.session.get.return_value = response("https://youtube.com/", chunks=(b"123", b"456"))
        with patch("linkmusicbot.security.MAX_BYTES", 5), self.assertRaises(ValueError):
            security.fetch_text("https://youtube.com/", security.YOUTUBE_HOSTS)

    def test_content_length_is_bounded(self):
        self.session.get.return_value = response("https://youtube.com/", headers={
            "Content-Length": str(security.MAX_BYTES + 1)})
        with self.assertRaises(ValueError):
            security.fetch_text("https://youtube.com/", security.YOUTUBE_HOSTS)

    def test_status_errors_are_checked(self):
        self.session.get.return_value = response("https://youtube.com/")
        security.fetch_text("https://youtube.com/", security.YOUTUBE_HOSTS)
        self.session.get.return_value.raise_for_status.assert_called_once()

    def test_expired_budget_prevents_request(self):
        with security.request_budget(-1), self.assertRaises(TimeoutError):
            security.fetch_text("https://youtube.com/", security.YOUTUBE_HOSTS)
        self.session.get.assert_not_called()


class AbuseTests(unittest.TestCase):
    def test_persistent_library_search_survives_reopen(self):
        import tempfile
        from pathlib import Path
        from linkmusicbot.library import LocalLibrary
        from telegram import InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup
        result = InlineQueryResultArticle("test", "DEMON'S SHOT", InputTextMessageContent("Song"),
            description="Aiobahn +81", reply_markup=InlineKeyboardMarkup([
                [LinkMusicBot.service_button("YouTube", "https://www.youtube.com/watch?v=abcdefghijk")]]))
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "music.sqlite3")
            library = LocalLibrary(path)
            library.put("https://music.apple.com/us/song/x/123", [result])
            library.db.close()
            reopened = LocalLibrary(path)
            try:
                self.assertEqual(reopened.get("demons shot")[0].title, "DEMON'S SHOT")
                self.assertIn("watch?v=", reopened.get("aiobahn")[0].reply_markup.inline_keyboard[0][0].url)
                self.assertIsNone(reopened.get("unknown track"))
                with patch("linkmusicbot.library.time.time", return_value=4102444800):
                    self.assertEqual(reopened.get("demons shot")[0].title, "DEMON'S SHOT")
                    self.assertTrue(reopened.needs_refresh("https://music.apple.com/us/song/x/123"))
                bot = LinkMusicBot.__new__(LinkMusicBot)
                bot._guard = security.QueryGuard()
                bot._library = reopened
                bot.handle_link = MagicMock()
                self.assertEqual(bot._build_results("demons shot")[0].title, "DEMON'S SHOT")
                bot.handle_link.assert_not_called()
            finally:
                reopened.db.close()

    def test_youtube_fetch_uses_metadata_only_and_validates_id(self):
        from linkmusicbot.youtube_fetch import first_video
        completed = MagicMock(stdout='{"entries":[{"id":"abcdefghijk"}]}')
        with patch("linkmusicbot.youtube_fetch.subprocess.run", return_value=completed) as run:
            self.assertEqual(first_video("Song"), "https://www.youtube.com/watch?v=abcdefghijk")
            args = run.call_args.args[0]
            self.assertIn("--flat-playlist", args)
            self.assertIn("--skip-download", args)
            self.assertEqual(args[-1], "ytsearch1:Song")
            self.assertEqual(run.call_args.kwargs["timeout"], 6)
            completed.stdout = '{"entries":[{"id":"bad"}]}'
            with self.assertRaises(ValueError):
                first_video("Song")

    def test_youtube_quota_returns_search_without_verified_metadata(self):
        youtube = YouTube()
        with patch.object(youtube, "_get", side_effect=security.QuotaExceeded()), \
                patch("linkmusicbot.services.youtube.first_video", return_value="https://www.youtube.com/watch?v=abcdefghijk"):
            self.assertEqual(youtube.song_to_link(Song("Song", "Artist", "Album")),
                             "https://www.youtube.com/results?search_query=Song+Artist+topic")

    def test_youtube_quota_falls_back_to_search_link(self):
        from linkmusicbot.models import Album
        youtube = YouTube()
        with patch.object(youtube, "_get", side_effect=security.QuotaExceeded()), \
                patch("linkmusicbot.services.youtube.first_video", side_effect=ValueError()):
            for item in (Song("The Sun", "Maroon 5", "Songs"), Album("Songs", "Maroon 5")):
                link = youtube.object_to_link(item)
                self.assertTrue(link.startswith("https://www.youtube.com/results?"))
                self.assertIn("Maroon", link)
                self.assertTrue(youtube.can_handle_link(link))

    def test_youtube_remote_quota_is_recognized(self):
        import json
        youtube = YouTube()
        payload = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
        with patch("linkmusicbot.services.youtube.fetch_text", return_value=json.dumps(payload)):
            with self.assertRaises(security.QuotaExceeded):
                youtube._get(youtube._SEARCH_PATH)

    def test_environment_settings_override_legacy_config(self):
        from linkmusicbot.settings import load_settings
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test-env-token",
                                     "YOUTUBE_SEARCH_LIMIT": "25"}):
            settings = load_settings()
        self.assertEqual(settings["telegram_token"], "test-env-token")
        self.assertEqual(settings["youtube_search_limit"], 25)

    def test_cache_and_inline_settings_are_configurable(self):
        from linkmusicbot.settings import load_settings
        with patch.dict("os.environ", {"MUSIC_CACHE_REFRESH_SECONDS": "21600",
                                       "INLINE_RESULT_LIMIT": "20", "INLINE_DEBOUNCE_MS": "800"}):
            settings = load_settings()
        self.assertEqual(settings["cache_refresh_seconds"], 21600)
        self.assertEqual(settings["inline_result_limit"], 20)
        self.assertEqual(settings["inline_debounce_ms"], 800)

    def test_apple_artwork_uses_large_image(self):
        url = "https://is1-ssl.mzstatic.com/image/thumb/Music/cover.jpg/100x100bb.jpg"
        self.assertEqual(AppleMusic._large_artwork(url), url.replace("100x100", "600x600"))
        self.assertEqual(AppleMusic._large_artwork(url.replace("100x100", "486x486")),
                         url.replace("100x100", "600x600"))
        foreign = "https://example.com/100x100bb.jpg"
        self.assertEqual(AppleMusic._large_artwork(foreign), foreign)

    def test_typing_searches_only_latest_query(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._guard = security.QueryGuard()
        bot._build_results = MagicMock(return_value=[])
        first, last = MagicMock(), MagicMock()
        for update, query in ((first, "demon"), (last, "demon's")):
            update.inline_query.query = query
            update.inline_query.from_user.id = 1
            update.inline_query.answer = AsyncMock()
        async def run():
            task = asyncio.create_task(bot.inline_query_handler(first, None))
            await asyncio.sleep(0.01)
            await bot.inline_query_handler(last, None)
            await task
        asyncio.run(run())
        bot._build_results.assert_called_once_with("demon's")
        first.inline_query.answer.assert_not_called()
        last.inline_query.answer.assert_awaited_once_with([], cache_time=0, is_personal=True)

    def test_search_fallback_order_and_errors(self):
        for apple_error in (False, True):
            bot = LinkMusicBot.__new__(LinkMusicBot)
            apple, spotify, youtube = (MagicMock() for _ in range(3))
            for service, name in ((apple, "Apple Music"), (spotify, "Spotify"), (youtube, "YouTube")):
                service.service_name.return_value = name
            apple.search.return_value = []
            if apple_error:
                apple.search.side_effect = ValueError("unavailable")
            spotify_item = Song("Song Spotify", "Artist", "Album")
            youtube_item = Song("Song YouTube", "Artist", "Album")
            spotify.search.return_value = [spotify_item]
            youtube.search.return_value = [youtube_item]
            bot.search_service = apple
            bot._music_services = [apple, youtube, spotify]
            bot.make_iqr = MagicMock(side_effect=lambda item: item)
            with patch("linkmusicbot.bot.logging.warning"):
                self.assertEqual(bot.handle_search("song"), [spotify_item, youtube_item])
                youtube.search.assert_called_once()
                spotify.search.return_value = []
                self.assertEqual(bot.handle_search("song"), [youtube_item])
                youtube.search.return_value = []
                self.assertEqual(bot.handle_search("song"), [])

    def test_youtube_search_parses_metadata_without_scraping(self):
        youtube = YouTube()
        response = {"items": [{"id": {"videoId": "OL1lo6zBGbM"}, "snippet": {
            "title": "Song &amp; title", "channelTitle": "Channel - Topic"}}]}
        with patch.object(youtube, "_get", return_value=response):
            song = list(youtube.search("song"))[0]
        self.assertEqual(song.title, "Song & title")
        self.assertEqual(song.service_links["YouTube"], "https://youtube.com/watch?v=OL1lo6zBGbM")

    def test_spotify_search_parses_metadata(self):
        spotify = Spotify.__new__(Spotify)
        spotify._spotify = MagicMock()
        spotify._spotify.search.return_value = {"tracks": {"items": [{
            "name": "Song", "artists": [{"name": "Artist"}],
            "album": {"name": "Album", "images": []},
            "external_urls": {"spotify": "https://open.spotify.com/track/test"}}]}}
        song = list(spotify.search("song"))[0]
        self.assertEqual(song.artist, "Artist")
        self.assertEqual(song.service_links["Spotify"], "https://open.spotify.com/track/test")

    def test_name_search_resolves_other_platforms_to_tracks(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        apple = AppleMusic()
        spotify = MagicMock()
        spotify.service_name.return_value = "Spotify"
        spotify.can_handle_link.return_value = True
        youtube = MagicMock()
        youtube.service_name.return_value = "YouTube"
        youtube.can_handle_link.return_value = True
        bot._music_services = [apple, youtube, spotify]
        bot.search_service = apple
        payload = {"results": [{"wrapperType": "track", "trackName": "DEMON'S SHOT",
                   "artistName": "Aiobahn +81", "collectionName": "Single",
                   "trackViewUrl": "https://music.apple.com/us/song/demons-shot/6813022243",
                   "artworkUrl100": "https://is1-ssl.mzstatic.com/image/test.jpg"}]}
        with patch.object(apple, "_search", return_value=payload) as search:
            results = bot.handle_search("demons shot")
        search.assert_called_once()
        self.assertEqual(results[0].title, "DEMON'S SHOT")
        self.assertEqual(len(results[0].reply_markup.inline_keyboard), 3)
        spotify.object_to_link.assert_not_called()
        youtube.object_to_link.assert_not_called()

    def test_apple_song_path_and_modern_metadata(self):
        import json
        service = AppleMusic()
        link = "https://music.apple.com/us/song/demons-shot/6813022243"
        self.assertTrue(service.link_is_song(link))
        self.assertTrue(service.link_is_song("https://music.apple.com/us/album/x/1?i=2"))
        self.assertFalse(service.link_is_song("https://music.apple.com/us/album/x/1"))
        data = {"@type": "MusicComposition", "audio": {
            "@type": "MusicRecording", "name": "DEMON'S SHOT",
            "byArtist": [{"name": "Aiobahn +81"}, {"name": "DEMONDICE"}],
            "inAlbum": {"name": "Single", "image": "https://is1-ssl.mzstatic.com/image/test.jpg"}}}
        html = '<script type="application/ld+json">' + json.dumps(data) + '</script>'
        with patch("linkmusicbot.services.apple_music.fetch_text", return_value=html):
            song = service.link_to_object(link)
        self.assertEqual(song.title, "DEMON'S SHOT")
        self.assertEqual(song.artist, "Aiobahn +81 & DEMONDICE")
        self.assertEqual(song.service_links["Apple Music"], link)
        self.assertIn("mzstatic.com", song.cover_art["url"])

    def test_tracking_parameters_share_cache_and_only_fetch_once(self):
        from threading import BoundedSemaphore
        from concurrent.futures import ThreadPoolExecutor
        import time
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._guard = security.QueryGuard()
        bot._work_slots = BoundedSemaphore(2)
        def convert(query):
            time.sleep(0.03)
            return "result"
        bot.handle_link = MagicMock(side_effect=convert)
        link = "https://open.spotify.com/track/6NDdZaUIXJfto2riSCDQcQ"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(bot._build_results, link + "?si=" + token)
                       for token in ("a", "b")]
            self.assertEqual([future.result() for future in futures], [["result"], ["result"]])
        bot.handle_link.assert_called_once_with(link)
        self.assertEqual(bot._build_results(link + "?utm_source=test"), ["result"])
        self.assertEqual(bot.handle_link.call_count, 1)

    def test_normalization_preserves_track_selectors(self):
        self.assertEqual(security.normalize_query("  My   SONG  "), "my song")
        self.assertEqual(security.normalize_query("https://music.apple.com/album/x?i=42&si=x"),
                         "https://music.apple.com/album/x?i=42")
        self.assertEqual(security.normalize_query("https://youtube.com/watch?v=abc&si=x"),
                         "https://youtube.com/watch?v=abc")

    def test_private_help_uses_telegram_language(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        for language, expected in (("ru", "искать музыку"), ("ru-RU", "искать музыку"),
                                   ("en", "find music"), (None, "find music")):
            with self.subTest(language=language):
                update = MagicMock()
                update.effective_user.language_code = language
                update.effective_message.reply_text = AsyncMock()
                context = MagicMock()
                context.bot.username = "SongHubbot"
                asyncio.run(bot.message_handler(update, context))
                text = update.effective_message.reply_text.call_args.args[0]
                self.assertIn(expected, text)
                self.assertIn("@SongHubbot", text)
                self.assertNotIn("123456789", text)

    def test_service_buttons_have_no_icons(self):
        for name in ('Apple Music', 'Spotify', 'YouTube'):
            with patch.dict('linkmusicbot.bot.secrets', inline_custom_emoji_enabled=True,
                            service_custom_emoji_ids={name: '123456789'}):
                button = LinkMusicBot.service_button(name, 'https://example.com/')
                self.assertEqual(button.text, name)
                self.assertIsNone(button.icon_custom_emoji_id)

    def test_legacy_imports_preserve_public_classes(self):
        import bot
        import converter
        import security as legacy_security
        self.assertIs(bot.LinkMusicBot, LinkMusicBot)
        self.assertIs(converter.Song, Song)
        self.assertIs(converter.Spotify, Spotify)
        self.assertIs(legacy_security.QueryGuard, security.QueryGuard)

    def test_youtube_daily_budget(self):
        quota = security.SearchQuota(2)
        with patch("linkmusicbot.security.time.monotonic", return_value=100):
            quota.reserve()
            quota.reserve()
            with self.assertRaises(ValueError):
                quota.reserve()
        with patch("linkmusicbot.security.time.monotonic", return_value=86501):
            quota.reserve()
        unlimited = security.SearchQuota(0)
        for _ in range(100):
            unlimited.reserve()
        self.assertEqual(len(unlimited.calls), 0)

    def test_query_rate_limit_resets(self):
        guard = security.QueryGuard()
        with patch("linkmusicbot.security.time.monotonic", return_value=100):
            self.assertTrue(guard.allow(1))
            self.assertFalse(guard.allow(1))
        with patch("linkmusicbot.security.time.monotonic", return_value=106):
            self.assertTrue(guard.allow(1))

    def test_cache_expires_and_is_bounded(self):
        guard = security.QueryGuard()
        with patch("linkmusicbot.security.time.monotonic", return_value=100):
            guard.put("a", [])
            self.assertEqual(guard.get("a"), [])
            for number in range(300):
                guard.put(str(number), [])
            self.assertEqual(len(guard.cache), 256)
        with patch("linkmusicbot.security.time.monotonic", return_value=1901):
            self.assertIsNone(guard.get("299"))

    def test_service_url_validation_and_spotify_id(self):
        self.assertTrue(AppleMusic().can_handle_link("https://music.apple.com/us/album/x"))
        self.assertFalse(YouTube().can_handle_link("http://youtube.com/watch?v=x"))
        identifier = "1ysj4ThiNp8jQ8l7Y3Ef8c"
        self.assertEqual(Spotify._validated_id("https://open.spotify.com/track/" + identifier,
                                               "track"), identifier)
        with self.assertRaises(ValueError):
            Spotify._validated_id("https://open.spotify.com/track/../../users/x", "track")

    def test_bot_construction_without_network(self):
        with patch.dict("linkmusicbot.bot.secrets", spotify_client_id="test", spotify_client_secret="test"), \
                patch("linkmusicbot.bot.LocalLibrary"), patch('linkmusicbot.bot.UsageStats'), patch('linkmusicbot.bot.CoverStore'):
            bot = LinkMusicBot("123456:TEST_TOKEN")
        self.assertEqual(len(bot._music_services), 4)
        commands = {command for handler in bot.application.handlers[0]
                    for command in getattr(handler, 'commands', ())}
        self.assertTrue({'start', 'connect_spotify', 'disconnect_spotify', 'current'} <= commands)

    def test_cached_query_does_not_call_services(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        from threading import BoundedSemaphore
        bot._guard = security.QueryGuard()
        bot._work_slots = BoundedSemaphore(2)
        bot._guard.put("song", ["cached"])
        bot.handle_link = MagicMock()
        self.assertEqual(bot._build_results("song"), ["cached"])
        bot.handle_link.assert_not_called()

    def test_results_keep_visible_text_with_and_without_cover(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        service = MagicMock()
        service.object_to_link.return_value = "https://open.spotify.com/track/x"
        service.can_handle_link.return_value = True
        service.service_name.return_value = "Spotify"
        bot._music_services = [service]
        song = Song("Title", "Artist", "Album")
        self.assertEqual(bot.make_iqr(song).type, "article")
        song.cover_art = {"url": "https://i.scdn.co/image/test"}
        result = bot.make_iqr(song)
        self.assertEqual(result.type, "article")
        self.assertEqual(result.title, "Title")
        self.assertEqual(result.description, "Artist")
        self.assertEqual(result.thumbnail_url, song.cover_art["url"])
        self.assertEqual(len(result.reply_markup.inline_keyboard), 1)
        self.assertIn("Title", result.input_message_content.message_text)
        self.assertTrue(result.input_message_content.link_preview_options.is_disabled)

    def test_invalid_query_never_reaches_services(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._guard = security.QueryGuard()
        bot._build_results = MagicMock()
        update = MagicMock()
        update.inline_query.query = "x" * 513
        update.inline_query.answer = AsyncMock()
        asyncio.run(bot.inline_query_handler(update, None))
        bot._build_results.assert_not_called()
        update.inline_query.answer.assert_awaited_once_with(
            [], cache_time=0, is_personal=True)
        # Check real SDK signature as AsyncMock accepts unsupported keywords.
        import inspect
        from telegram import InlineQuery
        args, kwargs = update.inline_query.answer.call_args
        inspect.signature(InlineQuery.answer).bind(None, *args, **kwargs)


if __name__ == "__main__":
    unittest.main()
