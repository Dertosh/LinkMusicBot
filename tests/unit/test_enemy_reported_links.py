import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from linkmusicbot.models import Song
from linkmusicbot.services.base import same_recording
from linkmusicbot.services.spotify import Spotify


class ReportedEnemyTests(unittest.TestCase):
    def test_reported_platform_metadata_and_separate_versions(self):
        data=json.loads((Path(__file__).parents[1]/'fixtures/enemy_recordings.json').read_text(encoding='utf-8'))
        source=data['spotify'];song=Song(source['title'],source['artist'],'')
        for expected,rows in [(True,data['matches']),(False,data['non_matches']),(False,data['unverified'])]:
            for row in rows:
                with self.subTest(url=row['url']):
                    self.assertEqual(same_recording(song,row['title'],row['artist']),expected)

    def test_spotify_source_retains_album_artwork(self):
        with patch.object(Spotify,'__init__',return_value=None):service=Spotify()
        image={'url':'https://i.scdn.co/image/cover','height':640,'width':640}
        service._spotify=Mock()
        service._spotify.track.return_value={'name':'Enemy','artists':[{'name':'Imagine Dragons'}],
                                            'album':{'name':'Enemy','images':[image]}}
        song=service.link_to_song('https://open.spotify.com/track/1r9xUipOqoNwggBpENDsvJ')
        self.assertEqual(song.cover_art,image)
