import json
from pathlib import Path
import unittest
from unittest.mock import patch

from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording
from linkmusicbot.security import normalize_query
from linkmusicbot.search_ranking import query_matches


CASES = json.loads((Path(__file__).resolve().parents[1] / 'live/youtube_channel_cases.json').read_text(encoding='utf-8'))


class YouTubeChannelTests(unittest.TestCase):
    def test_native_prefixes_survive_catalog_alias_normalization(self):
        self.assertTrue(query_matches('ウィマーマ・サーガ', 'しぐれうい', 'ウィマーマ'))
        self.assertTrue(query_matches('Wishing Umbrella', 'しぐれうい', 'しぐれ'))
        self.assertTrue(query_matches('Невеста', "Глюк'oZa", 'глюк'))

    def test_markdown_escaped_shared_link_is_normalized(self):
        self.assertEqual(normalize_query(r'https\://youtu.be/RuHbs3306RI?si=tracking'),
                         'https://youtu.be/RuHbs3306RI')

    def test_artist_channel_fixtures(self):
        for case in CASES:
            with self.subTest(video=case['video']):
                parsed = YouTube._snippet_song({'title': case['raw_title'], 'channelTitle': case['channel']})
                self.assertIsNotNone(parsed)
                self.assertEqual((parsed.title, parsed.artist), (case['title'], case['artist']))

    def test_source_links_keep_exact_selected_video(self):
        for case in CASES[:4]:
            link = 'https://youtu.be/' + case['video']
            snippet = {'title': case['raw_title'], 'channelTitle': case['channel']}
            with self.subTest(video=case['video']), patch.object(YouTube, '_get', return_value={'items': [{'snippet': snippet}]}):
                song = YouTube().link_to_song(link)
                self.assertEqual(song.service_links['YouTube'], link)
                self.assertEqual(song.title, case['title'])

    def test_unknown_uploaders_do_not_establish_performers(self):
        for case in CASES:
            with self.subTest(video=case['video']):
                self.assertIsNone(YouTube._snippet_song({'title': case['raw_title'], 'channelTitle': 'Unknown Uploader'}))

    def test_catalog_aliases_and_project_credit(self):
        self.assertTrue(same_recording(Song('ЖУ-ЖУ (Family Edit)', "Ленинград & Глюк'oZа & ST", ''),
                                       'Жу-Жу [Family Edit]', 'Leningrad & Glukoza & ST'))
        self.assertTrue(same_recording(Song('天天天国地獄国', 'Aiobahn +81 & ななひら & P丸様。', ''),
                                       '天天天国地獄国', 'Aiobahn +81 & Nanahira & P丸様｡'))
        self.assertTrue(same_recording(Song('ウィマーマ・サーガ', 'しぐれうい', ''), 'UiMa-Ma Saga', 'Ui Shigure'))
        song = Song('INTERNET YAMERO', 'Aiobahn +81 & KOTOKO', '')
        self.assertTrue(same_recording(song, 'Internet Yamero', 'NEEDY GIRL OVERDOSE & KOTOKO & Aiobahn +81'))
        self.assertFalse(same_recording(song, 'Internet Yamero', 'Whybaby_ff & NEEDY GIRL OVERDOSE & KOTOKO & Aiobahn +81'))
        self.assertFalse(same_recording(song, 'Internet Yamero (Anime version)', 'Aiobahn +81'))
        self.assertFalse(same_recording(song, 'Internet Yamero', 'Sati Akura'))
        self.assertFalse(same_recording(Song('ЖУ-ЖУ (Family Edit)', 'Leningrad & Glukoza & ST', ''), 'Жу-Жу', 'Leningrad & Glukoza & ST'))

    def test_promos_and_full_concerts_are_not_single_songs(self):
        for title, channel in [('Glukoza - нож [mv teaser]', 'Glukoza'), ('Aiobahn - YouTube Music Weekend 8.0', 'Aiobahn'),
                               ('Aiobahn feat. ヰ世界情緒 - new world #shorts', 'Aiobahn'),
                               ('しぐれうい - Birthday Live 【全3曲ライブフル映像】', 'しぐれうい')]:
            self.assertIsNone(YouTube._snippet_song({'title': title, 'channelTitle': channel}))
