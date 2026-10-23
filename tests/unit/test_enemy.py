import unittest
from unittest.mock import patch

from linkmusicbot.models import Song
from linkmusicbot.services.base import same_recording, recording_query
from linkmusicbot.services.yandex_music import YandexMusic


class EnemyTests(unittest.TestCase):
    def setUp(self):
        self.source = Song('Enemy (with JID) - from the series Arcane League of Legends',
                           'Imagine Dragons & JID & Arcane & League of Legends', 'Enemy')
        self.target = Song('Enemy (from the series Arcane League of Legends)',
                           self.source.artist, 'Mercury - Act 1')

    def test_with_credit_matches_yandex_recording(self):
        self.assertTrue(same_recording(self.source, self.target.title, self.target.artist))
        self.assertNotIn('(with JID)', recording_query(self.source))
        self.target.service_links = {'Яндекс Музыка': 'https://music.yandex.ru/album/21002416/track/94074268'}
        with patch.object(YandexMusic, 'search', return_value=iter([self.target])):
            self.assertEqual(YandexMusic().song_to_link(self.source), self.target.service_links['Яндекс Музыка'])

    def test_distinct_performers_and_versions_stay_separate(self):
        self.assertFalse(same_recording(self.source, self.target.title, 'Imagine Dragons & Arcane & League of Legends'))
        for version in ['Opening Title Version', 'Live in Vegas', 'Remix']:
            self.assertFalse(same_recording(self.source, self.target.title + ' (' + version + ')', self.target.artist))

    def test_guest_in_title_is_required_even_when_absent_from_artist_field(self):
        source = Song('Enemy (with JID)', 'Imagine Dragons', '')
        self.assertTrue(same_recording(source, 'Enemy', 'Imagine Dragons & JID'))
        self.assertFalse(same_recording(source, 'Enemy', 'Imagine Dragons'))

    def test_opening_title_project_credit_and_title_format(self):
        source = Song('Enemy with JID - Opening Title Version', 'Arcane & Imagine Dragons & JID', '')
        target = Song('Enemy with JID (Opening Title Version)', 'Imagine Dragons & JID', '')
        self.assertTrue(same_recording(source, target.title, target.artist))
        self.assertTrue(same_recording(source, 'Enemy (Opening Title Version)', target.artist))
        self.assertFalse(same_recording(source, self.source.title, self.source.artist))
        self.assertFalse(same_recording(source, target.title, 'Imagine Dragons'))
        self.assertFalse(same_recording(source, target.title + ' (Remix)', target.artist))
        target.service_links = {'Яндекс Музыка': 'https://music.yandex.ru/album/41784359/track/132361542'}
        with patch.object(YandexMusic, 'search', return_value=iter([self.target, target])):
            self.assertEqual(YandexMusic().song_to_link(source), target.service_links['Яндекс Музыка'])
