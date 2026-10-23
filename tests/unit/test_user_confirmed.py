import json
from pathlib import Path
import unittest
from linkmusicbot.models import Song
from linkmusicbot.services.base import same_recording


class UserConfirmedRecordingTests(unittest.TestCase):
    def test_all_confirmed_platform_metadata_matches_selected_recording(self):
        cases=json.loads((Path(__file__).parents[1]/'live/user_confirmed.json').read_text(encoding='utf-8'))
        for case in cases:
            source=Song(case['title'],case['artist'],'')
            for match in case['matches']:
                with self.subTest(track=case['title'],platform=match['platform'],url=match['url']):
                    self.assertTrue(same_recording(source,match['title'],match['artist']))
                    self.assertTrue(same_recording(Song(match['title'],match['artist'],''),source.title,source.artist))
                    self.assertNotIn('/search',match['url'])
                    self.assertNotIn('/results',match['url'])

    def test_confirmed_opening_version_does_not_match_full_enemy(self):
        source=Song('Enemy with JID - Opening Title Version','Arcane & Imagine Dragons & JID','')
        self.assertFalse(same_recording(source,'Enemy (with JID) - from the series Arcane League of Legends',
                                        'Imagine Dragons & JID & Arcane & League of Legends'))
