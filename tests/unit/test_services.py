import json
import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.modules["config"] = types.SimpleNamespace(secrets={})
from linkmusicbot.models import Album, Song
from linkmusicbot.services import AppleMusic, Spotify, YouTube
from linkmusicbot.security import QuotaExceeded, SearchQuota
from linkmusicbot.youtube_fetch import first_video
from requests.exceptions import HTTPError
from linkmusicbot.services.base import same_recording, recording_query


def schema_page(payload):
    return '<script type="application/ld+json">' + json.dumps(payload) + '</script>'


class MatchingRegressionTests(unittest.TestCase):
    def test_feature_credit_matches_collaborating_artists(self):
        song = Song("Я не вернусь (feat. Kyle Kujira)", "Снежа", "Single")
        self.assertEqual(recording_query(song), "Я не вернусь Снежа Kyle Kujira")
        self.assertTrue(same_recording(song, "Я не вернусь", "Снежа & Kyle Kujira"))
        self.assertTrue(same_recording(song, "Я не вернусь", "Kyle Kujira & Снежа"))
        self.assertFalse(same_recording(song, "Я не вернусь", "Снежа"))
        self.assertFalse(same_recording(song, "Я не вернусь (Remix)", "Снежа & Kyle Kujira"))
        self.assertFalse(same_recording(song, "Я не вернусь", "ВИА Гра"))

    def test_apple_text_search_requests_songs(self):
        with patch.object(AppleMusic, "_search", return_value={"results": []}) as search:
            list(AppleMusic().search("я не вернусь Снежа", n=2))
        self.assertEqual(search.call_args.kwargs["entity"], "song")

    def test_apple_rejects_cover_and_remix(self):
        for title, artist in [("Song", "Other"), ("Song (Remix)", "Artist")]:
            with self.subTest(title=title), patch.object(AppleMusic, "_search", return_value={"resultCount": 1, "results": [{"trackName": title, "artistName": artist, "trackViewUrl": "wrong"}]}):
                with self.assertRaises(ValueError):
                    AppleMusic().song_to_link(Song("Song", "Artist", "Album"))

    def test_apple_rejects_wrong_album(self):
        with patch.object(AppleMusic, "_search", return_value={"resultCount": 1, "results": [{"collectionName": "Album", "artistName": "Other"}]}):
            with self.assertRaises(ValueError):
                AppleMusic().album_to_link(Album("Album", "Artist"))

    def test_spotify_skips_wrong_first_result(self):
        service = Spotify.__new__(Spotify)
        service._spotify = MagicMock()
        def entry(title, artist, url):
            return {"name": title, "artists": [{"name": artist}], "album": {"images": []}, "external_urls": {"spotify": url}}
        service._spotify.search.return_value = {"tracks": {"items": [entry("Song", "Other", "wrong"), entry("Song", "Artist", "correct")]}}
        self.assertEqual(service.song_to_link(Song("Song", "Artist", "Album")), "correct")
        service._spotify.search.return_value = {"tracks": {"items": [entry("Song (Remix)", "Artist", "wrong")]}}
        with self.assertRaises(ValueError):
            service.song_to_link(Song("Song", "Artist", "Album"))

    def test_youtube_does_not_return_unverified_video(self):
        with patch.object(YouTube, "_get", return_value={"items": [{"id": {"videoId": "abcdefghijk"}, "snippet": {"title": "Other", "channelTitle": "Artist - Topic"}}]}):
            self.assertIn("/results?", YouTube().song_to_link(Song("Song", "Artist", "Album")))

    def test_youtube_quota_fallback_does_not_guess(self):
        with patch.object(YouTube, "_get", side_effect=QuotaExceeded()), patch("linkmusicbot.services.youtube.first_video") as fetch:
            self.assertIn("/results?", YouTube().song_to_link(Song("Song", "Artist", "Album")))
            fetch.assert_not_called()


class AppleTests(unittest.TestCase):
    def test_the_sun_exact_title_beats_partial_titles(self):
        def entry(title, artist, url):
            return {"wrapperType": "track", "trackName": title, "artistName": artist,
                    "collectionName": "Album", "trackViewUrl": url}
        payload = {"results": [entry("A Chapter in the Sun", "Other", "partial"),
                               entry("The Sun (Live)", "Maroon 5", "live"),
                               entry("The Sun", "Maroon 5", "original")]}
        with patch.object(self.service, "_search", return_value=payload):
            items = list(self.service.search("The Sun Maroon 5", n=2))
        self.assertEqual(items[0].service_links["Apple Music"], "original")

    def test_japanese_search_original_first_with_distinct_remix_link(self):
        title = "快眠!安眠!スヤリスト生活"
        def entry(suffix, url):
            return {"wrapperType": "track", "trackName": title + suffix,
                    "artistName": "Artist", "collectionName": "Album", "trackViewUrl": url}
        payload = {"results": [entry(" (DC Mizey Remix)", "remix"), entry("", "original"),
                               entry("", "duplicate"), entry(" (TV Size)", "tv"),
                               {"wrapperType": "track", "trackName": "安眠", "artistName": "Other",
                                "collectionName": "Other", "trackViewUrl": "unrelated"}]}
        with patch.object(self.service, "_search", return_value=payload) as search:
            items = list(self.service.search(title, n=2))
        self.assertEqual(search.call_args.kwargs["country"], "JP")
        self.assertGreaterEqual(search.call_args.kwargs["limit"], 20)
        self.assertEqual([s.service_links["Apple Music"] for s in items], ["original", "remix"])
        self.assertEqual(items[1].title, title + " (DC Mizey Remix)")
        with patch.object(self.service, "_search", return_value=payload):
            items = list(self.service.search(title + " Remix", n=2))
        self.assertEqual(items[0].service_links["Apple Music"], "remix")

    def test_original_japanese_track_preferred_over_first_remix(self):
        title, artist = "快眠!安眠!スヤリスト生活", "スヤリス姫 (CV.水瀬いのり)"
        payload = {"resultCount": 3, "results": [
            {"trackName": title + " (DC Mizey Remix)", "artistName": artist, "trackViewUrl": "https://music.apple.com/jp/song/remix/1"},
            {"trackName": title, "artistName": artist, "trackViewUrl": "https://music.apple.com/jp/song/original/2"},
            {"trackName": title + " (TV Size)", "artistName": artist, "trackViewUrl": "https://music.apple.com/jp/song/tv/3"}]}
        with patch.object(self.service, "_search", return_value=payload) as search:
            link = self.service.song_to_link(Song(title, artist, "Album"))
        self.assertIn("original", link)
        self.assertEqual(search.call_args.kwargs["country"], "JP")

    def test_explicit_remix_title_is_preserved(self):
        payload = {"resultCount": 2, "results": [
            {"trackName": "Song", "artistName": "Artist", "trackViewUrl": "original"},
            {"trackName": "Song (Remix)", "artistName": "Artist", "trackViewUrl": "remix"}]}
        with patch.object(self.service, "_search", return_value=payload):
            self.assertEqual(self.service.song_to_link(Song("Song (Remix)", "Artist", "Album")), "remix")

    def test_exact_artist_preferred_over_cover(self):
        payload = {"resultCount": 2, "results": [
            {"trackName": "Song", "artistName": "Cover Band", "trackViewUrl": "cover"},
            {"trackName": "Song", "artistName": "Artist", "trackViewUrl": "original"}]}
        with patch.object(self.service, "_search", return_value=payload):
            self.assertEqual(self.service.song_to_link(Song("Song", "Artist", "Album")), "original")

    def test_empty_japanese_store_retries_us(self):
        payload = {"resultCount": 1, "results": [{"trackName": "曲", "artistName": "Artist", "trackViewUrl": "found"}]}
        with patch.object(self.service, "_search", side_effect=[{"resultCount": 0, "results": []}, payload]) as search:
            self.assertEqual(self.service.song_to_link(Song("曲", "Artist", "Album")), "found")
        self.assertEqual(search.call_args.kwargs["country"], "US")

    def setUp(self):
        self.service = AppleMusic()
        self.url = "https://music.apple.com/us/album/name/123"

    def test_album_graph_and_multiple_artists(self):
        payload = {"@graph": [{"@type": "MusicAlbum", "name": "Album &amp; title",
                    "byArtist": [{"name": "A"}, {"name": "B"}]}]}
        with patch("linkmusicbot.services.apple_music.fetch_text", return_value=schema_page(payload)):
            album = self.service.link_to_object(self.url)
        self.assertIsInstance(album, Album)
        self.assertEqual(album.title, "Album & title")
        self.assertEqual(album.artist, "A & B")

    def test_legacy_track_selector_on_album_page(self):
        payload = {"@type": "MusicAlbum", "name": "Album", "byArtist": {"name": "Artist"}}
        html = schema_page(payload) + '<div class="is-deep-linked"><span class="table__row__headline">Song</span></div>'
        with patch("linkmusicbot.services.apple_music.fetch_text", return_value=html):
            song = self.service.link_to_object(self.url + "?i=42")
        self.assertEqual((song.title, song.artist, song.album), ("Song", "Artist", "Album"))

    def test_malformed_schema_does_not_hide_next_valid_schema(self):
        valid = {"@type": "MusicAlbum", "name": "Album", "byArtist": {"name": "Artist"}}
        html = '<script type="application/ld+json">not json</script>' + schema_page([valid])
        with patch("linkmusicbot.services.apple_music.fetch_text", return_value=html):
            self.assertEqual(self.service.link_to_album(self.url).title, "Album")

    def test_missing_metadata_is_rejected(self):
        with patch("linkmusicbot.services.apple_music.fetch_text", return_value="<html></html>"):
            with self.assertRaises(ValueError):
                self.service.link_to_album(self.url)

    def test_untrusted_url_is_rejected_before_fetch(self):
        with patch("linkmusicbot.services.apple_music.fetch_text") as fetch:
            with self.assertRaises(ValueError):
                self.service.link_to_song("https://evil.example/song/123")
        fetch.assert_not_called()

    def test_empty_search_returns_no_items(self):
        with patch.object(self.service, "_search", return_value={"results": []}):
            self.assertEqual(list(self.service.search("unknown")), [])


class SpotifyTests(unittest.TestCase):
    def test_album_conversion_without_cover(self):
        self.service._spotify.search.return_value = {"albums": {"total": 1, "items": [{
            "name": "Album", "artists": [{"name": "Artist"}], "images": [], "external_urls": {"spotify": "https://open.spotify.com/album/first"}}]}}
        album = Album("Album", "Artist")
        self.assertEqual(self.service.album_to_link(album), "https://open.spotify.com/album/first")
        self.assertIsNone(album.cover_art)

    def setUp(self):
        self.service = Spotify.__new__(Spotify)
        self.service._spotify = MagicMock()

    def test_link_uses_validated_id_and_ignores_tracking(self):
        identifier = "1ysj4ThiNp8jQ8l7Y3Ef8c"
        self.service._spotify.track.return_value = {
            "name": "Song", "artists": [{"name": "Artist"}], "album": {"name": "Album"}}
        song = self.service.link_to_song("https://open.spotify.com/track/" + identifier + "?si=abc")
        self.service._spotify.track.assert_called_once_with(identifier)
        self.assertEqual(song.title, "Song")

    def test_invalid_id_does_not_reach_api(self):
        with self.assertRaises(ValueError):
            self.service.link_to_song("https://open.spotify.com/track/not-an-id")
        self.service._spotify.track.assert_not_called()

    def test_empty_search_has_no_results(self):
        self.service._spotify.search.return_value = {"tracks": {"items": []}}
        self.assertEqual(list(self.service.search("unknown")), [])

    def test_conversion_uses_first_match_and_handles_missing_cover(self):
        first = {"name": "Song", "artists": [{"name": "Artist"}], "external_urls": {"spotify": "https://open.spotify.com/track/first"}, "album": {"images": []}}
        second = {"name": "Other", "artists": [{"name": "Artist"}], "external_urls": {"spotify": "https://open.spotify.com/track/second"}, "album": {"images": []}}
        self.service._spotify.search.return_value = {"tracks": {"total": 2, "items": [first, second]}}
        song = Song("Song", "Artist", "Album")
        self.assertEqual(self.service.song_to_link(song), first["external_urls"]["spotify"])
        self.assertIsNone(song.cover_art)

    def test_no_matches_after_naive_retry(self):
        self.service._spotify.search.return_value = {"tracks": {"total": 0, "items": []}}
        with self.assertRaises(ValueError):
            self.service.song_to_link(Song("Song", "Artist", "Album"))
        self.assertEqual(self.service._spotify.search.call_count, 2)


class YouTubeTests(unittest.TestCase):
    def test_official_lyrics_link_preserves_source(self):
        url = "https://www.youtube.com/watch?v=OL1lo6zBGbM"
        payload = {"items": [{"snippet": {"title": "STEFAN - Miraaž (Official Lyrics video)", "channelTitle": "STEFAN"}}]}
        with patch.object(self.service, "_get", return_value=payload):
            song = self.service.link_to_song(url)
        self.assertEqual((song.title, song.artist), ("Miraaž", "STEFAN"))
        self.assertEqual(song.service_links["YouTube"], url)

    def test_official_video_search_matches_exact_song_and_version(self):
        payload = {"items": [{"id": {"videoId": "OL1lo6zBGbM"}, "snippet": {
            "title": "STEFAN - Miraaž (Official Lyrics video)", "channelTitle": "STEFAN"}}]}
        with patch.object(self.service, "_get", return_value=payload):
            self.assertIn("OL1lo6zBGbM", self.service.song_to_link(Song("Miraaž", "Stefan", "")))
            self.assertIn("/results?", self.service.song_to_link(Song("Miraaž (Remix)", "Stefan", "")))

    def test_unrelated_channel_cannot_establish_song_artist(self):
        self.assertIsNone(self.service._snippet_song({"title": "STEFAN - Miraaž (Official Lyrics video)", "channelTitle": "Other"}))

    def setUp(self):
        self.service = YouTube()

    def test_api_quota_http_error_is_translated(self):
        response = MagicMock()
        response.json.return_value = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
        with patch("linkmusicbot.services.youtube.fetch_text", side_effect=HTTPError(response=response)):
            with self.assertRaises(QuotaExceeded):
                self.service._get(self.service._SEARCH_PATH)

    def test_invalid_key_http_error_is_not_misreported_as_quota(self):
        response = MagicMock()
        response.json.return_value = {"error": {"errors": [{"reason": "keyInvalid"}]}}
        with patch("linkmusicbot.services.youtube.fetch_text", side_effect=HTTPError(response=response)):
            with self.assertRaises(HTTPError):
                self.service._get(self.service._SEARCH_PATH)

    def test_local_quota_blocks_api_before_network(self):
        self.service._search_quota = SearchQuota(1)
        self.service._search_quota.reserve()
        with patch("linkmusicbot.services.youtube.fetch_text") as fetch:
            with self.assertRaises(QuotaExceeded):
                self.service._get(self.service._SEARCH_PATH)
        fetch.assert_not_called()

    def test_api_parameters_are_not_mutated(self):
        params = {"q": "song"}
        with patch("linkmusicbot.services.youtube.fetch_text", return_value='{"items": []}'):
            self.service._get(self.service._SEARCH_PATH, params)
        self.assertEqual(params, {"q": "song"})

    def test_direct_video_is_used_without_fetch_fallback(self):
        payload = {"items": [{"id": {"videoId": "abcdefghijk"}, "snippet": {"title": "Song", "channelTitle": "Artist - Topic"}}]}
        with patch.object(self.service, "_get", return_value=payload), \
                patch("linkmusicbot.services.youtube.first_video") as fetch:
            link = self.service.song_to_link(Song("Song", "Artist", "Album"))
        self.assertEqual(link, "https://youtube.com/watch?v=abcdefghijk")
        fetch.assert_not_called()

    def test_fetch_timeout_returns_encoded_search_link(self):
        song = Song("A & B?", "Artist", "Album")
        with patch.object(self.service, "_get", side_effect=QuotaExceeded()), \
                patch("linkmusicbot.services.youtube.first_video", side_effect=subprocess.TimeoutExpired("yt-dlp", 6)):
            link = self.service.song_to_link(song)
        self.assertIn("search_query=", link)
        self.assertIn("%26", link)
        self.assertIn("%3F", link)

    def test_fetch_empty_or_invalid_json_is_rejected(self):
        for payload in ('{"entries":[]}', "not json"):
            with self.subTest(payload=payload), patch("linkmusicbot.youtube_fetch.subprocess.run",
                    return_value=MagicMock(stdout=payload)):
                with self.assertRaises(ValueError):
                    first_video("Song")

    def test_search_text_cannot_be_interpreted_by_shell(self):
        query = 'song; $(touch /tmp/should-not-exist)'
        with patch("linkmusicbot.youtube_fetch.subprocess.run",
                   return_value=MagicMock(stdout='{"entries":[{"id":"abcdefghijk"}]}')) as run:
            first_video(query)
        self.assertEqual(run.call_args.args[0][-1], "ytsearch1:" + query)
        self.assertFalse(run.call_args.kwargs.get("shell", False))
