import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services.base import durations_match, same_recording


class DurationToleranceTests(unittest.TestCase):
    def test_rounding_padding_and_long_tracks(self):
        self.assertTrue(durations_match(173381,174000))
        self.assertTrue(durations_match(180000,183000))
        self.assertFalse(durations_match(180000,183001))
        self.assertTrue(durations_match(600000,608000))
        self.assertFalse(durations_match(3600000,3610001))

    def test_configurable_minimum(self):
        with patch.dict('linkmusicbot.services.base.secrets', duration_tolerance_ms=5000):
            self.assertTrue(durations_match(180000,184000))

    def test_missing_invalid_and_conflicting_duration(self):
        for value in [None,0,-1,float('nan'),float('inf'),'180000',True]:
            self.assertIsNone(durations_match(value,180000))
        s=Song('Enemy','Imagine Dragons & JID','');s.duration_ms=173381
        self.assertFalse(same_recording(s,s.title,s.artist,duration_ms=186133))
        self.assertTrue(same_recording(s,s.title,s.artist,duration_ms=174000))
        self.assertFalse(same_recording(s,s.title,'Imagine Dragons',duration_ms=174000))
