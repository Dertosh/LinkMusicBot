import unittest
from threading import Barrier
from unittest.mock import patch

from linkmusicbot.bot import LinkMusicBot, _RECHECKING_CACHE
from linkmusicbot.models import Song
from linkmusicbot.security import request_budget, check_budget


class ParallelServiceTests(unittest.TestCase):
    def test_workers_share_deadline_and_refresh_context(self):
        token = _RECHECKING_CACHE.set(True)
        try:
            with request_budget(-1):
                def work(service):
                    self.assertTrue(_RECHECKING_CACHE.get())
                    with self.assertRaises(TimeoutError):
                        check_budget()
                    return service
                self.assertEqual(LinkMusicBot._parallel_services([1, 2], work), [1, 2])
        finally:
            _RECHECKING_CACHE.reset(token)

    def services(self, mode):
        barrier = Barrier(2, timeout=3)
        class Provider:
            def __init__(self, name, url):
                self.name, self.url = name, url
            def service_name(self):
                return self.name
            def can_handle_link(self, link):
                return True
            def search(self, query, n):
                barrier.wait()
                return [Song('Song', 'Artist', '')]
            def object_to_link(self, item):
                barrier.wait()
                # Each worker must see the original metadata despite changes
                # made by the other provider's client.
                self_test.assertEqual(item.title, 'Song')
                item.title = self.name
                return self.url
        self_test = self
        return [Provider('Apple Music', 'https://music.apple.com/us/song/1'),
                Provider('Spotify', 'https://open.spotify.com/track/1')]

    def test_link_resolution_overlaps_without_mutating_source_or_button_order(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._music_services = self.services('links')
        source = Song('Song', 'Artist', '')
        result = bot.make_iqr(source)
        self.assertEqual(source.title, 'Song')
        self.assertEqual([row[0].text for row in result.reply_markup.inline_keyboard], ['Apple Music', 'Spotify'])

    def test_title_search_overlaps_and_merges_in_provider_order(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        bot._music_services = self.services('search')
        bot.search_service = bot._music_services[0]
        bot.make_iqr = lambda item: item
        with patch('linkmusicbot.bot.query_variants', return_value=['Song']):
            results = bot.handle_search('Song')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, 'Song')
