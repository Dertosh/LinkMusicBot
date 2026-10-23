import unittest
from unittest.mock import Mock, patch
from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.models import Song
from linkmusicbot.security import fetch_text, http_session_scope


class ProviderEfficiencyTests(unittest.TestCase):
    def test_ready_cards_need_no_pool_or_network(self):
        bot = LinkMusicBot.__new__(LinkMusicBot)
        service = Mock()
        service.service_name.return_value = 'Spotify'
        service.can_handle_link.return_value = True
        bot._music_services = [service]
        song = Song('Song', 'Artist', '')
        song.service_links = {'Spotify': 'https://open.spotify.com/search/Song'}
        with patch('linkmusicbot.bot.ThreadPoolExecutor') as executor:
            result = bot.make_iqr(song)
        executor.assert_not_called()
        service.object_to_link.assert_not_called()
        self.assertEqual(result.reply_markup.inline_keyboard[0][0].url, song.service_links['Spotify'])

    def test_connection_reuse_is_scoped_and_cleanup_survives_failure(self):
        session = Mock()
        response = Mock()
        response.headers = {}
        response.iter_content.return_value = [b'{}']
        session.get.return_value.__enter__ = Mock(return_value=response)
        session.get.return_value.__exit__ = Mock(return_value=False)
        with patch('linkmusicbot.security.requests.Session', return_value=session) as factory, \
             patch('linkmusicbot.security.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]):
            with self.assertRaises(ValueError):
                with http_session_scope():
                    for _ in range(2):
                        self.assertEqual(fetch_text('https://example.com', {'example.com'}), '{}')
                    raise ValueError('test cleanup')
            factory.assert_called_once()
            session.close.assert_called_once()
            self.assertFalse(session.trust_env)
            self.assertEqual(session.cookies.clear.call_count, 2)
            with http_session_scope():
                fetch_text('https://example.com', {'example.com'})
            self.assertEqual(factory.call_count, 2)
