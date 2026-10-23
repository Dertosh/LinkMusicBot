import unittest
from linkmusicbot.models import Song
from linkmusicbot.services.base import same_recording


class MetadataMatchingTests(unittest.TestCase):
    def test_word_order_and_punctuation(self):
        self.assertTrue(same_recording(Song('Shine Bright Tonight', 'Artist', ''), 'Tonight: Shine Bright', 'Artist'))
        self.assertFalse(same_recording(Song('Shine Bright Tonight', 'Artist', ''), 'Shine', 'Artist'))

    def test_shared_words_need_duration_evidence(self):
        s=Song('One Two Three Four Five Six', 'Artist', '')
        s.duration_ms=180000
        self.assertFalse(same_recording(s, 'One Two Three Four Five Six Seven', 'Artist'))
        self.assertTrue(same_recording(s, 'One Two Three Four Five Six Seven', 'Artist', duration_ms=181000))
        self.assertFalse(same_recording(s, 'One Two Three Four Five Six Seven', 'Artist', duration_ms=190000))

    def test_isrc_never_overrides_artist_or_version(self):
        s=Song('Different Localized Title', 'Artist', '');s.isrc='US1234567890'
        self.assertTrue(same_recording(s, 'Translated Title', 'Artist', isrc=s.isrc))
        self.assertFalse(same_recording(s, 'Translated Title', 'Other Artist', isrc=s.isrc))
        self.assertFalse(same_recording(s, 'Translated Title (Remix)', 'Artist', isrc=s.isrc))
        self.assertFalse(same_recording(s, 'Translated Title', 'Artist', isrc='US0000000000'))
