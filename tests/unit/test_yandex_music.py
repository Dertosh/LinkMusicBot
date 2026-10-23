import unittest
from unittest.mock import MagicMock, patch

from linkmusicbot.models import Album, Song
from linkmusicbot.services.yandex_music import YandexMusic
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.security import normalize_query


def track(identifier=63823):
    return {"id": identifier, "title": "The Sun", "artists": [{"name": "Maroon 5"}],
            "albums": [{"id": 478721, "title": "Songs About Jane"}],
            "coverUri": "avatars.yandex.net/get-music-content/cover/%%"}


class YandexTests(unittest.TestCase):
    def test_toy_retries_title_and_matches_editorial_note(self):
        song = Song("Toy", "Netta", "Toy")
        video = dict(track(39918274), title="TOY", version="Music Video Version",
                     artists=[{"name": "Netta"}])
        original = dict(track(39786405), title="Toy", version="Израиль. Победитель на «Евровидении-2018»",
                        artists=[{"name": "Netta"}], albums=[{"id": 11165199, "title": "Goody Bag EP"}])
        wrong = dict(original, artists=[{"name": "Young Fathers"}])
        with patch.object(self.service, "_get", side_effect=[
            {"tracks": {"results": [video]}}, {"tracks": {"results": [wrong, original]}}
        ]) as get:
            link = self.service.song_to_link(song)
        self.assertEqual(link, "https://music.yandex.ru/album/11165199/track/39786405")
        self.assertEqual([c.args[1]["text"] for c in get.call_args_list], ["Toy Netta", "Toy"])

    def test_editorial_note_does_not_remove_musical_version(self):
        original = Song("Toy", "Netta", "")
        for version in ["Remix", "Live", "Music Video Version", "Sagi Kariv Remix"]:
            candidate = Song("Toy (" + version + ")", "Netta", "")
            self.assertFalse(self.service._same_item(original, candidate))
        annotated_remix = Song("Toy (Remix) (Израиль. Победитель на «Евровидении-2018»)", "Netta", "")
        self.assertFalse(self.service._same_item(original, annotated_remix))

    def test_wrong_first_track_does_not_hide_correct_match(self):
        wrong = dict(track(1), title="Other Song")
        with patch.object(self.service, "_get", return_value={"tracks": {"results": [wrong, track()]}}):
            link = self.service.song_to_link(Song("The Sun", "Maroon 5", "Album"))
        self.assertTrue(link.endswith("/track/63823"))

    def test_same_title_by_other_artist_opens_search(self):
        wrong = dict(track(), artists=[{"name": "Other Artist"}])
        with patch.object(self.service, "_get", return_value={"tracks": {"results": [wrong]}}):
            link = self.service.song_to_link(Song("The Sun", "Maroon 5", "Album"))
        self.assertIn("/search?", link)

    def test_remix_is_not_selected_for_original(self):
        remix = dict(track(), version="Remix")
        with patch.object(self.service, "_get", return_value={"tracks": {"results": [remix]}}):
            self.assertIn("/search?", self.service.song_to_link(Song("The Sun", "Maroon 5", "Album")))

    def test_formatting_difference_matches(self):
        with patch.object(self.service, "_get", return_value={"tracks": {"results": [track()]}}):
            link = self.service.song_to_link(Song("THE SUN!", "MAROON ５", "Album"))
        self.assertTrue(link.endswith("/track/63823"))

    def test_other_album_artist_opens_search(self):
        with patch.object(self.service, "_get", return_value={"albums": {"results": [
                {"id": 1, "title": "Album", "artists": [{"name": "Other Artist"}]}]}}):
            self.assertIn("/search?", self.service.album_to_link(Album("Album", "Artist")))

    def test_existing_cached_card_gains_yandex_button_once(self):
        from threading import BoundedSemaphore
        from linkmusicbot.security import QueryGuard
        from telegram import InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._music_services = [self.service]
        bot._guard = QueryGuard()
        bot._work_slots = BoundedSemaphore(2)
        bot._guard.put("the sun", [InlineQueryResultArticle(
            "old", "The Sun", InputTextMessageContent("Song"), description="Maroon 5",
            reply_markup=InlineKeyboardMarkup([]))])
        with patch.object(self.service, "_get", return_value={"tracks": {"results": [track()]}}) as get:
            result = bot._build_results("the sun")
            bot._build_results("the sun")
        get.assert_called_once()
        self.assertEqual(result[0].reply_markup.inline_keyboard[0][0].text, "Яндекс Музыка")
        self.assertIn("/track/63823", result[0].reply_markup.inline_keyboard[0][0].url)

    def setUp(self):
        self.service = YandexMusic()

    def test_allowed_domains_require_https(self):
        for host in ("music.yandex.ru", "music.yandex.com", "music.yandex.by", "music.yandex.kz"):
            self.assertTrue(self.service.can_handle_link(f"https://{host}/album/1/track/2"))
        for url in ("http://music.yandex.ru/track/2", "https://music.yandex.ru.evil.test/track/2"):
            self.assertFalse(self.service.can_handle_link(url))

    def test_album_track_link_reads_metadata(self):
        with patch.object(self.service, "_get", return_value=[track()]) as get:
            song = self.service.link_to_object("https://music.yandex.ru/album/478721/track/63823?utm_source=share")
        get.assert_called_once_with("/tracks/63823")
        self.assertEqual((song.title, song.artist), ("The Sun", "Maroon 5"))
        self.assertEqual(song.service_links["Яндекс Музыка"], "https://music.yandex.ru/album/478721/track/63823")
        self.assertIn("600x600", song.cover_art["url"])
        self.assertEqual(list(song.service_links), ["Яндекс Музыка"])

    def test_bare_track_link(self):
        with patch.object(self.service, "_get", return_value=[track()]):
            self.assertIsInstance(self.service.link_to_object("https://music.yandex.com/track/63823"), Song)

    def test_album_link(self):
        payload = {"id": 1, "title": "Album", "artists": [{"name": "Artist"}]}
        with patch.object(self.service, "_get", return_value=payload) as get:
            album = self.service.link_to_object("https://music.yandex.ru/album/1")
        get.assert_called_once_with("/albums/1")
        self.assertIsInstance(album, Album)

    def test_invalid_paths_do_not_reach_api(self):
        with patch.object(self.service, "_get") as get:
            for url in ("https://evil.test/track/1", "https://music.yandex.ru/track/../../1",
                        "https://music.yandex.ru/track/abc"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.service.link_to_song(url)
        get.assert_not_called()

    def test_search_is_bounded_and_skips_unavailable_tracks(self):
        unavailable = dict(track(), available=False)
        with patch.object(self.service, "_get", return_value={"tracks": {"results": [unavailable, track(), track(2)]}}):
            results = list(self.service.search("song", n=2))
        self.assertEqual(len(results), 1)

    def test_song_conversion_returns_first_track(self):
        with patch.object(self.service, "_get", return_value={"tracks": {"results": [track()]}}):
            link = self.service.song_to_link(Song("The Sun", "Maroon 5", "Album"))
        self.assertTrue(link.endswith("/track/63823"))

    def test_album_conversion_returns_album(self):
        with patch.object(self.service, "_get", return_value={"albums": {"results": [
                {"id": 1, "title": "Album", "artists": [{"name": "Artist"}]}]}}):
            self.assertEqual(self.service.album_to_link(Album("Album", "Artist")), "https://music.yandex.ru/album/1")

    def test_failure_returns_search_link(self):
        with patch.object(self.service, "_get", side_effect=ValueError()):
            link = self.service.song_to_link(Song("A & B", "Artist", "Album"))
        self.assertIn("/search?text=", link)
        self.assertIn("%26", link)

    def test_empty_search_returns_search_link(self):
        with patch.object(self.service, "_get", return_value={"tracks": {"results": []}}):
            self.assertIn("/search?", self.service.song_to_link(Song("Song", "Artist", "Album")))

    def test_untrusted_cover_is_ignored(self):
        data = dict(track(), coverUri="https://evil.test/cover/%%")
        self.assertIsNone(self.service._song(data).cover_art)

    def test_track_without_album_and_version(self):
        data = dict(track(), albums=[], version="Remix")
        song = self.service._song(data)
        self.assertEqual(song.title, "The Sun (Remix)")
        self.assertEqual(song.service_links["Яндекс Музыка"], "https://music.yandex.ru/track/63823")

    def test_api_failure_cooldown_avoids_repeated_requests(self):
        with patch("linkmusicbot.services.yandex_music.fetch_text", side_effect=ValueError()) as fetch:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    self.service._get("/search")
        fetch.assert_called_once()

    def test_tracking_parameters_normalize_for_cache(self):
        self.assertEqual(normalize_query("https://music.yandex.ru/album/1/track/2?utm_source=share"),
                         "https://music.yandex.ru/album/1/track/2")

    def test_yandex_button_and_cover_render(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._music_services = [self.service]
        item = self.service._song(track())
        result = bot.make_iqr(item)
        self.assertEqual(result.reply_markup.inline_keyboard[0][0].text, "Яндекс Музыка")
        self.assertIn("avatars.yandex.net", result.thumbnail_url)
