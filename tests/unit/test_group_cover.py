import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services import YouTube, Spotify
from linkmusicbot.services.base import same_recording


class GroupCoverTests(unittest.TestCase):
    def test_group_cover_enriched_without_substituting_original(self):
        snippet={'title':'Into You - Ariana Grande【God Complex Cover】','channelTitle':'Derivakat',
                 'categoryId':'10','description':'Vocalists:\n@isaacorva\n@RIHSURI\n@Derivakat\n@YukiXK'}
        expected=Song('Into You','God Complex & Derivakat & Yuki & Isaa Corva & RIHSURI & Cartian','Into You')
        expected.duration_ms=242853
        expected.service_links={'Spotify':'https://open.spotify.com/track/138RV2zJv5qbdw3f9W6LAb'}
        wrong=Song('Into You','Ariana Grande','');wrong.duration_ms=244453
        wrong.service_links={'Spotify':'https://open.spotify.com/track/76FZM38RC8XaAjJ77CVTNe'}
        response={'items':[{'snippet':snippet,'contentDetails':{'duration':'PT4M3S'}}]}
        with patch.object(YouTube,'_get',return_value=response),patch.object(Spotify,'__init__',return_value=None),patch.object(Spotify,'search',return_value=iter([wrong,expected])):
            song=YouTube().link_to_song('https://www.youtube.com/watch?v=rjr_BhxDY-g')
        self.assertEqual(song.title,'Into You')
        self.assertEqual(song.artist,expected.artist)
        self.assertTrue(song.service_links['YouTube'].endswith('rjr_BhxDY-g'))
        self.assertEqual(song.service_links['Spotify'],expected.service_links['Spotify'])
        self.assertTrue(same_recording(song,'Into You (feat. Derivakat, Yuki, Isaa Corva, RIHSURI & Cartian)','God Complex'))
        self.assertFalse(same_recording(song,'Into You','Ariana Grande'))

    def test_wrong_duration_or_uploader_cannot_confirm_catalogue_cover(self):
        snippet={'title':'Into You - Ariana Grande【God Complex Cover】','channelTitle':'Derivakat','description':'Vocalists:\n@Derivakat'}
        wrong=Song('Into You','God Complex & Derivakat','');wrong.duration_ms=300000
        with patch.object(Spotify,'__init__',return_value=None),patch.object(Spotify,'search',return_value=iter([wrong])):
            fallback=YouTube._catalogue_cover(snippet,'PT4M3S')
        self.assertIn('Cover by God Complex',fallback.title)
        self.assertFalse(hasattr(fallback,'service_links'))
        self.assertIsNone(YouTube._catalogue_cover(dict(snippet,channelTitle='Reuploads'),'PT4M3S'))
