import unittest
from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording, query_variants
from linkmusicbot.search_ranking import query_matches, rank_results


class KotikRegressionTests(unittest.TestCase):
    def test_official_bilingual_video_is_parsed(self):
        snippet = {'title': 'Alexander Rybak - "Котик" / "Kotik" (Official Music Video)', 'channelTitle': 'AlexanderRybakVideo'}
        song = YouTube._snippet_song(snippet)
        self.assertEqual((song.title, song.artist), ('Котик', 'Alexander Rybak'))
        snippet['channelTitle'] = 'OtherVideo'
        self.assertIsNone(YouTube._snippet_song(snippet))

    def test_catalog_spellings_merge_without_merging_remixes_or_other_artists(self):
        song = Song('Котик', 'Alexander Rybak', '')
        self.assertTrue(same_recording(song, 'KOTIK', 'Александр Рыбак'))
        self.assertFalse(same_recording(song, 'KOTIK', 'S.NEKROZOV'))
        self.assertFalse(same_recording(song, 'Kotik (Remix)', 'Alexander Rybak'))

    def test_title_search_does_not_drop_translated_catalog_spelling(self):
        self.assertTrue(query_matches('KOTIK', 'Alexander Rybak', 'котик'))
        self.assertTrue(query_matches('KOTIK', 'Александр Рыбак', 'котик alexander rybak'))
        self.assertIn('kotik', query_variants('котик'))

    def test_alias_ranking_and_multi_platform_confirmation(self):
        known = Song('KOTIK', 'Alexander Rybak', '')
        known.service_links = {'Spotify': 'https://open.spotify.com/track/example', 'YouTube': 'https://music.youtube.com/watch?v=KxxEcOWdZsg'}
        other = Song('Котик', 'Other', '')
        other.service_links = {'Apple Music': 'https://music.apple.com/us/song/example/123'}
        self.assertEqual(rank_results([other, known], 'котик')[0], known)
