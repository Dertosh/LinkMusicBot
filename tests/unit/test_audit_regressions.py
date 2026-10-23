import unittest
from linkmusicbot.search_ranking import query_matches
from linkmusicbot.services.base import query_variants, same_recording
from linkmusicbot.services import YouTube
from linkmusicbot.models import Song


class AuditRegressions(unittest.TestCase):
    def test_compact_artist_and_decorated_video_query(self):
        self.assertTrue(query_matches('The Sun','Maroon 5','maroon5 the sun'))
        self.assertIn('maroon 5 the sun',query_variants('maroon5 the sun'))
        self.assertTrue(query_matches('QUEEN','LiSA','LiSA『QUEEN』MUSiC CLiP'))

    def test_pseudonym_and_typo_retrieval(self):
        self.assertTrue(query_matches('Невеста',"Глюк'oZa",'глюкоза невеста'))
        self.assertTrue(same_recording(Song('Невеста','Глюкоза',''),'Невеста',"Глюк'oZa"))
        self.assertTrue(query_matches('#ЛЯШКИВКУСНЯШКИ','ЯКОРЪ','ляшкивкуснягки'))
        self.assertTrue(query_matches('#ЛЯШКИВКУСНЯШКИ','ЯКОРЪ','ляшкитакиевкусняшки'))
        self.assertFalse(query_matches('Harvey','Alex G','alex gurulev remix'))

    def test_official_channel_and_japanese_title_brackets(self):
        song=YouTube._snippet_song({'title':'LiSA『QUEEN』MUSiC CLiP','channelTitle':'LiSA Official YouTube'})
        self.assertEqual((song.title,song.artist),('QUEEN','LiSA'))
        self.assertIsNone(YouTube._snippet_song({'title':'LiSA『QUEEN』MUSiC CLiP','channelTitle':'Other Official YouTube'}))

    def test_russian_cover_matches_catalog_version_without_matching_english(self):
        song=YouTube._snippet_song({'title':'[VOCALOID на русском] Rabbit Hole (Cover by Sati Akura)','channelTitle':'Sati Akura'})
        self.assertTrue(same_recording(song,'Rabbit Hole (Russian Ver.)','Sati Akura'))
        self.assertTrue(same_recording(song,'Rabbit Hole - Russian ver.','Sati Akura'))
        self.assertTrue(same_recording(song,'Rabbit Hole','Sati Akura'))
        self.assertFalse(same_recording(song,'Rabbit Hole (English Version)','Sati Akura'))
        self.assertFalse(same_recording(song,'Rabbit Hole (Russian Ver.)','DECO*27'))
        self.assertFalse(same_recording(song,'Rabbit Hole (Remix)','Sati Akura'))
