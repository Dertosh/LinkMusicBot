import unittest
from unittest.mock import MagicMock, patch

from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording
from linkmusicbot.security import QuotaExceeded
from linkmusicbot.youtube_music import search_music


class RequestedFixes(unittest.TestCase):
    def test_remix_credits_moved_between_title_and_artists(self):
        song = Song('Cry For Me - Shirobeats, Kiwwi Remix', 'Ironmouse & HalaCG & Bubi & Kiwwi & shirobeats', '')
        self.assertTrue(same_recording(song, 'Cry For Me (Shirobeats, Kiwwi Remix)', 'Ironmouse, HalaCG & Bubi'))
        for title, artist in [('Cry For Me', 'Ironmouse, HalaCG & Bubi'),
                              ('Cry For Me (Other Remix)', 'Ironmouse, HalaCG & Bubi'),
                              ('Cry For Me (Shirobeats, Kiwwi Remix)', 'Other Artist')]:
            self.assertFalse(same_recording(song, title, artist))

    def test_requested_artist_aliases_preserve_wrong_artist_rejection(self):
        for title, source, target in [('МОЙ РАЙ', 'MakSim', 'МакSим'), ('Прованс', 'Yolka', 'Ёлка'),
                                      ('Black Flame', 'KID PHENOMENON from EXILE TRIBE', 'KID PHENOMENON')]:
            self.assertTrue(same_recording(Song(title, source, ''), title, target))
            self.assertFalse(same_recording(Song(title, source, ''), title, 'Other Artist'))

    def test_youtube_music_prefers_audio_then_official_video_and_skips_other_types(self):
        def entry(identifier, kind, artists=None):
            return {'title': 'Song', 'videoId': identifier, 'videoType': kind,
                    'artists': artists if artists is not None else [{'name': 'Artist'}]}
        data = [entry('official123', 'MUSIC_VIDEO_TYPE_OMV'), entry('audio123456', 'MUSIC_VIDEO_TYPE_ATV'),
                entry('user1234567', 'MUSIC_VIDEO_TYPE_UGC'), entry('invalid', 'MUSIC_VIDEO_TYPE_ATV'),
                entry('noartist123', 'MUSIC_VIDEO_TYPE_ATV', [])]
        with patch('linkmusicbot.youtube_music.YTMusic') as client:
            client.return_value.search.return_value = data
            client.return_value.get_song.return_value = {}
            result = search_music('Artist Song')
        self.assertEqual([s.service_links['YouTube'] for s in result],
                         ['https://www.youtube.com/watch?v=audio123456', 'https://www.youtube.com/watch?v=official123'])

    def test_official_top_card_without_artist_resolves_metadata(self):
        entry = {'title': 'Black Flame', 'videoId': 'os8CNopeu7Q', 'videoType': 'MUSIC_VIDEO_TYPE_OMV'}
        with patch('linkmusicbot.youtube_music.YTMusic') as client:
            client.return_value.search.return_value = [entry]
            client.return_value.get_song.return_value = {'videoDetails': {'title': 'KID PHENOMENON | "Black Flame" Music Video', 'author': 'KID PHENOMENON'}}
            result = search_music('Black Flame KID PHENOMENON')
        self.assertEqual((result[0].title, result[0].artist), ('Black Flame', 'KID PHENOMENON'))

    def test_official_russian_video_title_matches_mixed_artist_alias(self):
        parsed = YouTube._snippet_song({'title': 'МакSим - Мой Рай (официальный клип)', 'channelTitle': 'Maksim'})
        self.assertTrue(same_recording(Song('МОЙ РАЙ', 'MakSim', ''), parsed.title, parsed.artist))

    def test_quota_fallback_matches_recording_instead_of_first_result(self):
        wrong = Song('Song (Remix)', 'Artist', '')
        correct = Song('Song', 'Artist', '')
        correct.service_links = {'YouTube': 'https://www.youtube.com/watch?v=audio123456'}
        with patch.object(YouTube, '_get', side_effect=QuotaExceeded()), \
                patch('linkmusicbot.services.youtube.search_music', return_value=[wrong, correct]):
            self.assertEqual(YouTube().song_to_link(Song('Song', 'Artist', '')), correct.service_links['YouTube'])

    def test_youtube_music_error_leaves_search_fallback(self):
        with patch.object(YouTube, '_get', side_effect=QuotaExceeded()), \
                patch('linkmusicbot.services.youtube.search_music', side_effect=TimeoutError):
            self.assertIn('/results?', YouTube().song_to_link(Song('Song', 'Artist', '')))
