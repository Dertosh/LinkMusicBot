import unittest
from unittest.mock import Mock, patch
from linkmusicbot.services.spotify import Spotify


class SpotifySourceTests(unittest.TestCase):
    def test_selected_track_id_survives_duplicate_releases(self):
        with patch.object(Spotify, '__init__', return_value=None):
            service = Spotify()
        service._spotify = Mock()
        service._spotify.track.return_value = {
            'name': 'Enemy', 'artists': [{'name': 'Imagine Dragons'}],
            'album': {'name': 'Enemy'},
            'external_urls': {'spotify': 'https://open.spotify.com/track/3CIyK1V4JEJkg02E4EJnDl'},
        }
        link = 'https://open.spotify.com/track/1r9xUipOqoNwggBpENDsvJ'
        item = service.link_to_song(link + '?si=shared')
        self.assertEqual(item.service_links['Spotify'], link)
        service._spotify.search.assert_not_called()
