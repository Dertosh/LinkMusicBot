import unittest
from linkmusicbot.services import YouTube
from linkmusicbot.models import Song
from linkmusicbot.services.base import same_recording


class PirozhkovTests(unittest.TestCase):
    def test_stage_name_and_pipe_audio_suffix(self):
        song = YouTube._snippet_song({'title': 'Артур Пирожков - Зацепила | AUDIO |', 'channelTitle': 'Александр Ревва'})
        self.assertEqual((song.title, song.artist), ('Зацепила', 'Артур Пирожков'))
        self.assertTrue(same_recording(song, 'Зацепила', 'Александр Ревва'))
        self.assertFalse(same_recording(song, 'Зацепила (Remix)', 'Артур Пирожков'))

    def test_other_uploader_is_not_treated_as_performer(self):
        self.assertIsNone(YouTube._snippet_song({'title': 'Артур Пирожков - Зацепила | AUDIO |', 'channelTitle': 'Other'}))
