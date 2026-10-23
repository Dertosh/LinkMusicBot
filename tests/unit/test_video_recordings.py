import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording
from linkmusicbot.youtube_music import video_music_metadata


class VideoRecordingTests(unittest.TestCase):
    def test_producer_and_anime_notes_are_not_recording_title(self):
        song = YouTube._snippet_song({'title':'Awich - Frontiers (Prod. Chaki Zulu) / Shangri-La Frontier シャングリラ・フロンティア OP','channelTitle':'Awich'})
        self.assertEqual((song.title,song.artist),('Frontiers','Awich'))
        self.assertFalse(same_recording(song,'Frontiers (Instrumental)','Awich'))

    def test_label_upload_uses_music_catalog_title_and_artist(self):
        snippet={'title':'Ёлка - На воздушном шаре','channelTitle':'ELLO','categoryId':'24'}
        music={'videoId':'zy5pKrUBUN4','title':'На большом воздушном шаре','artists':[{'name':"el'ka"}],'videoType':'MUSIC_VIDEO_TYPE_OMV'}
        with patch.object(YouTube,'_get',return_value={'items':[{'snippet':snippet}]}), patch('linkmusicbot.services.youtube.video_music_metadata',return_value=music):
            song=YouTube().link_to_song('https://youtu.be/zy5pKrUBUN4')
        self.assertTrue(same_recording(song,'На большом воздушном шаре','Yolka'))
        self.assertTrue(same_recording(song,'На большом воздушном шаре','Elka'))

    def test_cover_remix_credits_override_conflicting_catalog_version(self):
        snippet={'title':'Oliver Tree - Miss You (Bemax Cover Remix) I’m Your Treasure Box [AMV]','channelTitle':'Bemax - ビマックス','categoryId':'24'}
        music={'title':'Miss You (Slowed + Reverb)','artists':[{'name':'Bemax'}],'videoType':'MUSIC_VIDEO_TYPE_OMV'}
        with patch.object(YouTube,'_get',return_value={'items':[{'snippet':snippet}]}), patch('linkmusicbot.services.youtube.video_music_metadata',return_value=music):
            song=YouTube().link_to_song('https://youtu.be/TOoC7aXkpMs')
        self.assertEqual((song.title,song.artist),('Miss You (Cover Remix by Bemax)','Bemax'))
        self.assertTrue(same_recording(song,'Miss You','Bemax'))
        self.assertFalse(same_recording(song,'Miss You (Slowed + Reverb)','Bemax'))
        self.assertFalse(same_recording(song,'Miss You','Oliver Tree & Robin Schulz'))

    def test_unverified_non_music_video_cannot_use_oembed_to_bypass_check(self):
        snippet={'title':'Artist - A video','channelTitle':'Artist','categoryId':'22'}
        with patch.object(YouTube,'_get',return_value={'items':[{'snippet':snippet}]}), patch('linkmusicbot.services.youtube.video_music_metadata',return_value=None), patch('linkmusicbot.services.youtube.fetch_text',return_value='{"title":"Artist - A video","author_name":"Artist"}'):
            with self.assertRaises(ValueError):
                YouTube().link_to_song('https://youtu.be/abcdefghijk')

    def test_watch_metadata_rejects_recommended_video_and_non_track_types(self):
        for video,kind in [('other123456','MUSIC_VIDEO_TYPE_OMV'),('abcdefghijk','MUSIC_VIDEO_TYPE_UGC'),('abcdefghijk','MUSIC_VIDEO_TYPE_OFFICIAL_SOURCE_MUSIC')]:
            with patch('linkmusicbot.youtube_music.YTMusic') as client:
                client.return_value.get_watch_playlist.return_value={'tracks':[{'videoId':video,'videoType':kind,'title':'Song','artists':[{'name':'Artist'}]}]}
                self.assertIsNone(video_music_metadata('abcdefghijk'))

    def test_russian_cover_keeps_language_and_own_performer(self):
        song=YouTube._snippet_song({'title':'[League of Legends RUS] THE BADDEST (Cover by Sati Akura)','channelTitle':'Sati Akura'})
        self.assertIn('(Russian Ver.)',song.title)
        self.assertFalse(same_recording(song,'THE BADDEST','K/DA'))
