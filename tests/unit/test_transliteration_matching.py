import unittest
from unittest.mock import Mock, patch
from linkmusicbot.models import Song
from linkmusicbot.services.base import compare_recordings, same_recording, query_variants, recording_query
from linkmusicbot.search_ranking import query_matches


class TransliterationMatchingTests(unittest.TestCase):
    def test_cross_script_names_and_titles_require_metadata(self):
        cases=[('Привет мир','Марина','Privet mir','Marina'),
               ('Καλημέρα','Νίκος','Kalimera','Nikos'),
               ('Песня','Ольга','Pesnya','Olga')]
        for title,artist,other_title,other_artist in cases:
            with self.subTest(title=title):
                song=Song(title,artist,'');song.duration_ms=180000
                self.assertFalse(same_recording(song,other_title,other_artist))
                match=compare_recordings(song,other_title,other_artist,duration_ms=181000)
                self.assertEqual(match.status,'match',match)
                self.assertGreaterEqual(match.title_percent,98)
                self.assertTrue(query_matches(other_title,other_artist,title+' '+artist))

    def test_native_query_stays_first_and_transliteration_is_added(self):
        queries=query_variants('Привет Марина')
        self.assertEqual(queries[0],'Привет Марина')
        self.assertIn('privet marina', [q.casefold() for q in queries])
        self.assertEqual(query_variants('Die With A Smile'),['Die With A Smile'])

    def test_punctuation_guest_credits_and_word_order(self):
        song=Song('Shine! Bright? feat. Guest - Remix','Singer','')
        self.assertTrue(same_recording(song,'Shine Bright (Remix)','Singer & Guest'))
        self.assertIn('Guest',recording_query(song))
        self.assertFalse(same_recording(song,'Shine Bright','Singer & Guest'))
        self.assertEqual(compare_recordings(Song('Shine Bright Tonight','Singer',''),
            'Tonight (Shine Bright)','Singer').status,'match')

    def test_high_similarity_never_overrides_wrong_artist_or_version(self):
        song=Song('A Very Long Song Title','Artist','');song.duration_ms=180000
        for title,artist in [('A Very Long Song Title (Live)','Artist'),
                             ('A Very Long Song Title','Cover Artist'),
                             ('A Very Long Song Title (Remix)','Artist')]:
            result=compare_recordings(song,title,artist,duration_ms=180000)
            self.assertNotEqual(result.status,'match')

    def test_missing_guest_is_unverified_not_declared_different(self):
        song=Song('Enemy','Imagine Dragons & JID','');song.duration_ms=173381
        result=compare_recordings(song,'Enemy','Imagine Dragons',duration_ms=174000)
        self.assertEqual(result.status,'unverified')
        self.assertIn('incomplete_or_different_performer_credits',result.reasons)

    def test_percent_is_not_acceptance_threshold(self):
        song=Song('A Very Long Song Title','Artist','');song.duration_ms=180000
        result=compare_recordings(song,song.title,song.artist,duration_ms=210000)
        self.assertGreater(result.score,80)
        self.assertEqual(result.status,'different')

    def test_spotify_scores_all_candidates_instead_of_picking_first(self):
        from linkmusicbot.services import Spotify
        song=Song('A Very Long Song Title Here','Singer','Album');song.duration_ms=180000
        def entry(title,identifier):
            return {'name':title,'artists':[{'name':'Singer'}],'duration_ms':180000,
                    'album':{'name':'Album','images':[]},'external_urls':{'spotify':identifier}}
        with patch.object(Spotify,'__init__',return_value=None):service=Spotify()
        service._spotify=Mock()
        service._spotify.search.return_value={'tracks':{'items':[
            entry(song.title+' Bonus','near'),entry(song.title,'exact')]}}
        self.assertEqual(service.song_to_link(song),'exact')

    def test_local_catalogue_has_transliterated_terms_without_duplicate_ids(self):
        import tempfile
        from pathlib import Path
        from linkmusicbot.library import LocalLibrary
        from linkmusicbot.presentation import build_result
        with tempfile.TemporaryDirectory() as folder:
            library=LocalLibrary(str(Path(folder)/'cache.sqlite3'))
            try:
                result=build_result(Song('Привет мир','Марина',''),[])
                library.put('Привет мир',[result]);library.put('privet mir',[result])
                self.assertEqual(library.get_local('privet mir marina')[0].title,'Привет мир')
                self.assertEqual(library.db.execute('SELECT COUNT(*) FROM tracks').fetchone()[0],1)
            finally:library.db.close()
