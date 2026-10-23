import unittest
from unittest.mock import patch

from linkmusicbot.models import Song
from linkmusicbot.services.yandex_music import YandexMusic
from linkmusicbot.security import normalize_query
from linkmusicbot.bot import LinkMusicBot


class YandexCatalogueFallbackTests(unittest.TestCase):
    def test_title_search_enriches_missing_yandex_recording(self):
        from unittest.mock import Mock
        bot = LinkMusicBot.__new__(LinkMusicBot)
        apple = Mock()
        apple.service_name.return_value = 'Apple Music'
        apple.search.return_value = [self.song]
        self.song.service_links = {'Apple Music': 'https://music.apple.com/us/song/1'}
        bot.search_service = apple
        bot._music_services = [apple, self.service]
        bot.make_iqr = lambda item: item
        with patch.object(self.service, '_get', side_effect=self.lookup):
            results = bot.handle_search("DEMON'S SHOT Aiobahn +81 DEMONDICE")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].service_links[self.service.service_name()],
                         'https://music.yandex.ru/album/44512222/track/123')

    def setUp(self):
        self.service = YandexMusic()
        self.song = Song("DEMON'S SHOT", 'Aiobahn +81 & DEMONDICE', "DEMON'S SHOT")
        self.song.duration_ms = 255238
        self.track = {'id': 123, 'title': "DEMON'S SHOT", 'durationMs': 255250,
                      'artists': [{'name': 'Aiobahn +81'}, {'name': 'DEMONDICE'}],
                      'albums': [{'id': 44512222, 'title': "DEMON'S SHOT"}]}

    def lookup(self, path, params):
        if path.startswith('/artists/'):
            return {'tracks': [self.track]}
        if params['type'] == 'artist':
            return {'artists': {'results': [{'id': 22988048, 'name': 'Aiobahn +81'}]}}
        return {'tracks': {'results': []}}

    def test_catalogue_finds_release_missing_from_search_index(self):
        with patch.object(self.service, '_get', side_effect=self.lookup) as get:
            self.assertEqual(self.service.song_to_link(self.song), 'https://music.yandex.ru/album/44512222/track/123')
        calls = [c for c in get.call_args_list if c.args[0].startswith('/artists/')]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[1], {'page': 0, 'page-size': 100})

    def test_catalogue_does_not_accept_wrong_artist_duration_or_version(self):
        for change in [{'artists': [{'name': 'untruct'}]}, {'durationMs': 277100},
                       {'version': 'Remix'}, {'available': False}]:
            with self.subTest(change=change), patch.object(self.service, '_get', side_effect=self.lookup):
                original = self.track
                self.track = dict(original, **change)
                self.assertIn('/search?', self.service.song_to_link(self.song))
                self.track = original

    def test_unrelated_artist_search_result_is_not_scanned(self):
        with patch.object(self.service, '_get', return_value={'artists': {'results': [{'id': 1, 'name': 'Other'}]}}) as get:
            self.assertIn('/search?', self.service.song_to_link(self.song))
        self.assertFalse(any(c.args[0].startswith('/artists/') for c in get.call_args_list))

    def test_spotify_tracking_parameter_shares_cache_key(self):
        url = 'https://open.spotify.com/track/6NDdZaUIXJfto2riSCDQcQ'
        self.assertEqual(normalize_query(url + '?si=043a3b283d9041cf'), normalize_query(url))
