import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services.youtube import YouTube


class OfficialReferenceTests(unittest.TestCase):
    def test_reference_requires_matching_official_metadata(self):
        song = Song('Die With A Smile', 'Lady Gaga & Bruno Mars', '')
        results = {'items': [{'id': {'videoId': 'sQtWPcAyL6g'}, 'snippet': {
            'title': 'Lyrics', 'channelTitle': 'Unknown',
            'description': 'Official video: https://www.youtube.com/watch?v=kPa7bsKwL-c'}}]}
        official = {'title': 'Lady Gaga, Bruno Mars - Die With A Smile (Official Music Video)',
                    'channelTitle': 'LadyGagaVEVO', 'categoryId': '10'}
        for title, artist, category, expected in [
            (official['title'], 'LadyGagaVEVO', '10', True),
            (official['title'], 'Unknown', '10', False),
            ('Lady Gaga, Bruno Mars - Other Song', 'LadyGagaVEVO', '10', False),
            ('Lady Gaga, Bruno Mars - Die With A Smile (Live)', 'LadyGagaVEVO', '10', False),
            (official['title'], 'LadyGagaVEVO', '22', False),
        ]:
            with self.subTest(title=title, artist=artist, category=category):
                with patch.object(YouTube, '_get', return_value=results), patch.object(
                    YouTube, '_metadata_snippets', side_effect=[{}, {'kPa7bsKwL-c': dict(official, title=title, channelTitle=artist, categoryId=category)}]
                ), patch('linkmusicbot.services.youtube.search_music', return_value=[]):
                    url = YouTube().song_to_link(song)
                self.assertEqual(url == 'https://www.youtube.com/watch?v=kPa7bsKwL-c', expected)
