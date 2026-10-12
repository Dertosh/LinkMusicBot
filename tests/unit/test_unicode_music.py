import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording
from linkmusicbot.search_ranking import rank_results
from linkmusicbot.security import normalize_query
from linkmusicbot.bot import LinkMusicBot
from unittest.mock import MagicMock


class UnicodeMusicTests(unittest.TestCase):
    def test_real_unicode_queries_and_mojibake_use_identical_search_terms(self):
        for title, artist in [("Jóga", "Björk"), ("Halo", "Beyoncé"),
                              ("Hoppípolla", "Sigur Rós"), ("Escape Artist", "Zoë Keating")]:
            with self.subTest(title=title):
                query = title + " " + artist
                broken = query.encode("utf8").decode("latin1")
                bot = LinkMusicBot.__new__(LinkMusicBot)
                service = MagicMock()
                service.service_name.return_value = "Apple Music"
                service.search.return_value = [Song(title, artist, "Album")]
                bot.search_service = service
                bot._music_services = [service]
                bot.make_iqr = lambda item: item
                for text in [query, broken]:
                    self.assertEqual(bot.handle_search(text)[0].title, title)
                    service.search.assert_called_with(normalize_query(query), n=10)

    def test_unicode_original_and_remix_stay_separate(self):
        for title, artist in [("Miraaž", "STEFAN"), ("Jóga", "Björk"), ("Déjà Vu", "Beyoncé"),
                              ("快眠!安眠!スヤリスト生活", "スヤリス姫"), ("Я не вернусь", "Снежа")]:
            with self.subTest(title=title):
                original = Song(title, artist, "")
                remix = Song(title + " (Remix)", artist, "")
                self.assertEqual(rank_results([remix, original], title + " " + artist)[0], original)
                self.assertEqual(rank_results([original, remix], title + " Remix")[0], remix)
                self.assertFalse(same_recording(original, remix.title, remix.artist))

    def test_normalization_handles_combining_marks_fullwidth_and_apostrophes(self):
        self.assertTrue(same_recording(Song("Jóga", "Björk", ""), "Jo\u0301ga", "Bjo\u0308rk"))
        self.assertTrue(same_recording(Song("DEMON'S SHOT", "Artist", ""), "DEMON’S SHOT", "Ａｒｔｉｓｔ"))
        self.assertFalse(same_recording(Song("Jóga", "Björk", ""), "Jóga", "Cover Band"))

    def test_official_unicode_youtube_titles_preserve_the_selected_song(self):
        service = YouTube()
        for title, artist in [("Miraaž", "STEFAN"), ("Jóga", "Björk"), ("Déjà Vu", "Beyoncé")]:
            with self.subTest(title=title):
                payload = {"items": [{"snippet": {"title": artist + " – " + title + " (Official Lyrics video)",
                                                    "channelTitle": artist}}]}
                url = "https://www.youtube.com/watch?v=OL1lo6zBGbM"
                with patch.object(service, "_get", return_value=payload):
                    song = service.link_to_song(url)
                self.assertEqual((song.title, song.artist), (title, artist))
                self.assertEqual(song.service_links["YouTube"], url)
