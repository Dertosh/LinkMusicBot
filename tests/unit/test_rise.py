import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording
from linkmusicbot.youtube_music import search_music

SNIPPET={'title':'RISE (ft. The Glitch Mob, Mako, and The Word Alive) | Worlds 2018 - League of Legends',
         'channelTitle':'League of Legends','categoryId':'20'}


class RiseTests(unittest.TestCase):
    def test_search_does_not_send_artist_separators_as_query_operators(self):
        with patch('linkmusicbot.youtube_music.YTMusic') as client:
            client.return_value.search.return_value=[]
            search_music('RISE League of Legends & Mako')
            self.assertEqual(client.return_value.search.call_args.args[0],'RISE League of Legends Mako')

    def test_event_title_preserves_all_performers(self):
        song=YouTube._snippet_song(SNIPPET)
        self.assertEqual(song.title,'RISE')
        self.assertTrue(same_recording(song,'RISE','League of Legends & Mako & The Word Alive & The Glitch Mob'))
        self.assertTrue(same_recording(song,'RISE (feat. The Glitch Mob)','League of Legends Music, Mako & The Word Alive'))
        self.assertFalse(same_recording(song,'RISE (Remix)','League of Legends & BOBBY & Mako & The Word Alive & The Glitch Mob'))

    def test_gaming_category_requires_catalog_confirmation(self):
        candidate=Song('RISE (feat. The Glitch Mob)','League of Legends & Mako & The Word Alive','')
        with patch.object(YouTube,'_get',return_value={'items':[{'snippet':SNIPPET}]}), patch('linkmusicbot.services.youtube.video_music_metadata',return_value=None), patch('linkmusicbot.services.youtube.search_music',return_value=[candidate]):
            self.assertEqual(YouTube().link_to_song('https://youtu.be/fB8TyLTD7EE').service_links['YouTube'],'https://youtu.be/fB8TyLTD7EE')

    def test_unknown_uploader_and_wrong_catalog_recording_are_rejected(self):
        self.assertIsNone(YouTube._snippet_song(dict(SNIPPET,channelTitle='Unknown')))
        with patch.object(YouTube,'_get',return_value={'items':[{'snippet':SNIPPET}]}), patch('linkmusicbot.services.youtube.video_music_metadata',return_value=None), patch('linkmusicbot.services.youtube.search_music',return_value=[Song('RISE','Other Artist','')]), patch('linkmusicbot.services.youtube.fetch_text',return_value='{}'):
            with self.assertRaises(ValueError):YouTube().link_to_song('https://youtu.be/fB8TyLTD7EE')
