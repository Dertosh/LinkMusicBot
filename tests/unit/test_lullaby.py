import unittest
from unittest.mock import Mock, patch
from linkmusicbot.models import Song
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.services.base import compare_recordings
from linkmusicbot.services.spotify import Spotify


class LullabyTests(unittest.TestCase):
    def setUp(self):
        self.apple = Song('Колыбельная тишины', 'Jenia Lubich', '')
        self.apple.duration_ms = 184388

    def test_localized_artist_and_film_annotation_merge(self):
        for title in ['Колыбельная тишины', 'Колыбельная тишины (Из к/ф "Он - дракон")',
                      'Колыбельная тишины (из фильма «Он – дракон»)']:
            with self.subTest(title=title):
                self.assertEqual(compare_recordings(self.apple, title, 'Женя Любич', duration_ms=184380).status, 'match')

    def test_cover_remix_and_duration_conflict_still_rejected(self):
        for title, artist, duration in [
            ('Колыбельная тишины', 'Елизавета Бородулина', 169534),
            ('Колыбельная тишины (Remix)', 'Женя Любич', 184388),
            ('Колыбельная тишины', 'Женя Любич', 225010)]:
            self.assertNotEqual(compare_recordings(self.apple, title, artist, duration_ms=duration).status, 'match')

    def test_title_search_merges_spotify_into_apple_card(self):
        apple, spotify = Mock(), Mock()
        apple.service_name.return_value = 'Apple Music'
        spotify.service_name.return_value = 'Spotify'
        self.apple.service_links = {'Apple Music': 'https://music.apple.com/us/song/1196299660'}
        target = Song('Колыбельная тишины', 'Женя Любич', '')
        target.duration_ms = 184388
        target.service_links = {'Spotify': 'https://open.spotify.com/track/3hBgLzdEsV3O8hUSVsVLMc'}
        apple.search.return_value = [self.apple]
        spotify.search.return_value = [target]
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot.search_service = apple; bot._music_services = [apple, spotify]
        bot.make_iqr = lambda item: item
        with patch('linkmusicbot.bot.query_variants', return_value=['колыбельная тишины']):
            results = bot.handle_search('колыбельная тишины')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].service_links['Spotify'], target.service_links['Spotify'])

    def test_source_conversion_falls_back_to_title_with_strict_metadata_check(self):
        service = Spotify.__new__(Spotify)
        service._spotify = Mock()
        target = {'name': 'Колыбельная тишины', 'artists': [{'name': 'Женя Любич'}],
                  'duration_ms': 184388, 'album': {'name': '', 'images': []},
                  'external_urls': {'spotify': 'https://open.spotify.com/track/3hBgLzdEsV3O8hUSVsVLMc'}}
        service._spotify.search.side_effect = lambda q, **kwargs: {'tracks': {'items': [target] if q == self.apple.title else []}}
        self.assertEqual(service.song_to_link(self.apple), target['external_urls']['spotify'])
