import json
import unittest
from linkmusicbot.security import youtube_music_url
from linkmusicbot.library import LocalLibrary
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.models import Song
from linkmusicbot.presentation import build_result


class MusicLinksTests(unittest.TestCase):
    def test_direct_and_short_links_preserve_video_id(self):
        for url in ['https://www.youtube.com/watch?v=OL1lo6zBGbM', 'https://youtu.be/OL1lo6zBGbM']:
            self.assertEqual(youtube_music_url(url), 'https://music.youtube.com/watch?v=OL1lo6zBGbM')

    def test_search_uses_music_query_format(self):
        self.assertEqual(youtube_music_url('https://www.youtube.com/results?search_query=NYUSHA'),
                         'https://music.youtube.com/search?q=NYUSHA')

    def test_cached_buttons_are_converted_without_api_calls(self):
        result = build_result(Song('Song', 'Artist', ''), [[LinkMusicBot.service_button('YouTube', 'https://youtu.be/OL1lo6zBGbM')]])
        data = result.to_dict()
        data['reply_markup']['inline_keyboard'][0][0]['url'] = 'https://www.youtube.com/watch?v=OL1lo6zBGbM'
        decoded = LocalLibrary._decode(json.dumps([data]))[0]
        self.assertEqual(decoded.reply_markup.inline_keyboard[0][0].url, 'https://music.youtube.com/watch?v=OL1lo6zBGbM')
