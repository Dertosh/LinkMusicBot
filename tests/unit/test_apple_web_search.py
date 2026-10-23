import json
import unittest
from unittest.mock import patch
from linkmusicbot.models import Song
from linkmusicbot.services import AppleMusic
from linkmusicbot.services import YouTube
from linkmusicbot.services.base import same_recording


def page(items):
    return '<script id="serialized-server-data" type="application/json">'+json.dumps({'data':[{'data':{'sections':[{'items':items},{'items':items}]}}]})+'</script>'


def item(title, artist, identifier):
    return {'title':title,'subtitle':'Song · '+artist,'contentDescriptor':{'kind':'song','url':'https://music.apple.com/us/song/'+str(identifier)}}


class AppleWebSearchTests(unittest.TestCase):
    def test_translated_video_title_merges_only_its_language_version(self):
        russian=Song('Po Jian | Break the Cocoon (Russian Ver.) (Cover by Sati Akura)','Sati Akura','')
        self.assertTrue(same_recording(russian,'Po Jian (Russian Ver.)','Sati Akura'))
        self.assertFalse(same_recording(russian,'Po Jian (English Ver.)','Sati Akura'))
        english=YouTube._snippet_song({'title':'[Soul Land ENG] Po Jian (Cover by Sati Akura)','channelTitle':'Sati Akura'})
        self.assertIn('(English Ver.)',english.title)
        self.assertFalse(same_recording(english,'Po Jian (Russian Ver.)','Sati Akura'))
    def test_empty_itunes_index_uses_verified_public_search(self):
        with patch.object(AppleMusic,'_search',return_value={'resultCount':0,'results':[]}), patch('linkmusicbot.services.apple_music.fetch_text',return_value=page([item('Miss You','Bemax',1680948749)])):
            self.assertEqual(AppleMusic().song_to_link(Song('Miss You (Cover Remix by Bemax)','Bemax','')), 'https://music.apple.com/us/song/1680948749')
            self.assertEqual(len(list(AppleMusic().search('Miss You Bemax'))),1)

    def test_related_search_results_do_not_substitute_a_different_song(self):
        items=[item('Po Jian (Russian Ver.)','Sati Akura',1545027211),item('Po Jian (English Ver.)','Sati Akura',1545027205)]
        with patch.object(AppleMusic,'_search',return_value={'resultCount':0,'results':[]}), patch('linkmusicbot.services.apple_music.fetch_text',return_value=page(items)):
            with self.assertRaises(ValueError):
                AppleMusic().song_to_link(Song('THE BADDEST (Russian Ver.)','Sati Akura',''))
            self.assertEqual(AppleMusic().song_to_link(Song('Po Jian (Russian Ver.)','Sati Akura','')), 'https://music.apple.com/us/song/1545027211')
            self.assertEqual(AppleMusic().song_to_link(Song('Po Jian (English Ver.)','Sati Akura','')), 'https://music.apple.com/us/song/1545027205')

    def test_versions_and_external_destinations_are_rejected(self):
        data=[item('Miss You (Slowed + Reverb)','Bemax',1681319648), item('Miss You','Other Artist',123)]
        malicious=item('Miss You','Bemax',123);malicious['contentDescriptor']['url']='https://example.com/song/123';data.append(malicious)
        with patch.object(AppleMusic,'_search',return_value={'resultCount':0,'results':[]}), patch('linkmusicbot.services.apple_music.fetch_text',return_value=page(data)):
            with self.assertRaises(ValueError):AppleMusic().song_to_link(Song('Miss You','Bemax',''))
