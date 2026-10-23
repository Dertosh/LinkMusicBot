import unittest
from linkmusicbot.models import Song
from linkmusicbot.services.base import compare_recordings


class ChacarronTests(unittest.TestCase):
    def setUp(self):
        self.song = Song('Chacarrón', 'El Chombo & Andy Val', '')
        self.song.duration_ms = 180062

    def test_original_credit_variation_requires_matching_duration(self):
        self.assertEqual(compare_recordings(self.song, 'Chacarrón', 'El Chombo', duration_ms=181000).status, 'match')
        self.assertNotEqual(compare_recordings(self.song, 'Chacarrón', 'El Chombo').status, 'match')

    def test_radio_edit_karaoke_new_version_and_covers_are_not_original(self):
        for title, artist, duration in [
            ('Chacarron (Radio Edit)', 'El Chombo', 166733),
            ('Chacarron (Karaoke Version)', 'El Chombo', 166507),
            ('Chacarron 3.0', 'El Chombo & Andy Val', 180062),
            ('Chacarrón', 'The Harmony Group', 180062),
            ('Chacarrón', 'El Chombo & Another Singer', 180062)]:
            self.assertNotEqual(compare_recordings(self.song, title, artist, duration_ms=duration).status, 'match')

    def test_missing_guest_is_not_globally_ignored(self):
        song = Song('Other Song', 'El Chombo & Andy Val', '')
        song.duration_ms = 180062
        self.assertNotEqual(compare_recordings(song, 'Other Song', 'El Chombo', duration_ms=180062).status, 'match')
