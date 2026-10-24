import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording
from linkmusicbot.youtube_music import search_music


class OfficialClipTests(unittest.TestCase):
    def test_official_audio_marked_omv_does_not_hide_actual_clip(self):
        source = Song('Цвет настроения синий', 'Philipp Kirkorov', '')
        videos = []
        for identifier in ('i1OQf2FEyKs', 'IAuzNXGmkL4'):
            candidate = Song(source.title, source.artist, '')
            candidate.video_type = 'MUSIC_VIDEO_TYPE_OMV'
            candidate.service_links = {'YouTube': 'https://www.youtube.com/watch?v=' + identifier}
            videos.append(candidate)
        metadata = {'i1OQf2FEyKs': {'title': 'Филипп Киркоров - Цвет настроения синий I Official Audio | 2018'},
                    'IAuzNXGmkL4': {'title': 'Филипп Киркоров - Цвет настроения синий'}}
        with patch('linkmusicbot.services.youtube.search_music', return_value=videos), patch.object(
                YouTube, '_metadata_snippets', return_value=metadata):
            self.assertEqual(YouTube().song_to_link(source), videos[1].service_links['YouTube'])

    def test_verified_artist_spellings_work_across_catalogues(self):
        for title in ('Цвет настроения синий', 'Романы', 'Стеснение пропало'):
            song = Song(title, 'Филипп Киркоров', '')
            for artist in ('Philipp Kirkorov', 'Filipp Kirkorov'):
                self.assertTrue(same_recording(song, title, artist))
            self.assertFalse(same_recording(song, title + ' (Remix)', 'Philipp Kirkorov'))
            self.assertFalse(same_recording(song, title, 'Other Artist'))

    def test_premiere_annotation_is_not_part_of_recording_title(self):
        for title in ('Романы', 'Цвет настроения синий'):
            song = YouTube._snippet_song({'title': 'Филипп Киркоров - ' + title + ' (Премьера клипа 2020)',
                                         'channelTitle': 'Филипп Киркоров'})
            self.assertEqual(song.title, title)
        live = YouTube._snippet_song({'title': 'Филипп Киркоров - Романы (Live)', 'channelTitle': 'Филипп Киркоров'})
        self.assertIn('Live', live.title)

    def test_official_clip_can_have_intro_but_other_versions_cannot_replace_song(self):
        source = Song('Цвет настроения синий', 'Филипп Киркоров', '')
        source.duration_ms = 202540
        for title, artist, expected in [('Цвет настроения синий', 'Philipp Kirkorov', True),
                                       ('Цвет настроения синий (Live)', 'Philipp Kirkorov', False),
                                       ('Цвет настроения синий', 'Other Artist', False)]:
            candidate = Song(title, artist, '')
            candidate.duration_ms = 241000
            candidate.video_type = 'MUSIC_VIDEO_TYPE_OMV'
            candidate.service_links = {'YouTube': 'https://www.youtube.com/watch?v=IAuzNXGmkL4'}
            with patch('linkmusicbot.services.youtube.search_music', return_value=[candidate]), patch.object(
                    YouTube, '_get', return_value={'items': []}):
                result = YouTube().song_to_link(source)
            self.assertEqual(result == candidate.service_links['YouTube'], expected)

    def test_music_search_preserves_type_and_duration(self):
        entries = [{'videoId': 'IAuzNXGmkL4', 'title': 'Цвет настроения синий',
                    'artists': [{'name': 'Philipp Kirkorov'}], 'duration': '4:01',
                    'videoType': 'MUSIC_VIDEO_TYPE_OMV'}]
        with patch('linkmusicbot.youtube_music.YTMusic') as client:
            client.return_value.search.return_value = entries
            results = search_music('Цвет настроения синий', prefer_videos=True)
            self.assertEqual(results[0].duration_ms, 241000)
            self.assertEqual(results[0].video_type, 'MUSIC_VIDEO_TYPE_OMV')
            self.assertEqual(client.return_value.search.call_args.kwargs['filter'], 'videos')
