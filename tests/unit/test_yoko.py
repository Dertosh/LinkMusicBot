import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording
from linkmusicbot.search_ranking import query_matches


class YokoTests(unittest.TestCase):
    def test_romanization_variants_need_matching_metadata(self):
        source=Song('Прятки',"YO'KO",'');source.duration_ms=182069
        self.assertTrue(same_recording(source,'Прятки','ЙОКО',duration_ms=182060))
        self.assertFalse(same_recording(source,'Прятки','ЙОКО'))
        self.assertFalse(same_recording(source,'Прятки','Yoko Kanno',duration_ms=182069))
        self.assertFalse(same_recording(source,'Прятки (Remix)','ЙОКО',duration_ms=182069))
        self.assertTrue(query_matches('Прятки','ЙОКО',"Прятки YO'KO"))

    def test_youtube_timing_is_used_for_cross_script_performers(self):
        source=Song('Прятки',"YO'KO",'');source.duration_ms=182069
        snippet={'title':'Прятки','channelTitle':'ЙОКО - Topic','_duration_ms':182000}
        response={'items':[{'id':{'videoId':'6DteEzoqdQM'},'snippet':snippet}]}
        with patch.object(YouTube,'_get',return_value=response),patch.object(YouTube,'_metadata_snippets',return_value={'6DteEzoqdQM':snippet}):
            self.assertTrue(YouTube().song_to_link(source).endswith('6DteEzoqdQM'))
