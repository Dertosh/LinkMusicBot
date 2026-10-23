from http.client import HTTPConnection
from unittest.mock import Mock
import unittest
from linkmusicbot.spotify_callback import start_callback
from linkmusicbot.spotify_account import AccountError


class CallbackTests(unittest.TestCase):
    def test_callback_no_cache_and_duplicate_state_rejected(self):
        account=Mock();server=start_callback(account,host='127.0.0.1',port=0)
        try:
            for path,expected in [('/spotify/callback?state=abc&code=secret',200),
                                  ('/spotify/callback?state=a&state=b&code=secret',400),('/other',404)]:
                connection=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                connection.request('GET',path);response=connection.getresponse()
                self.assertEqual(response.status,expected)
                self.assertEqual(response.getheader('Cache-Control'),'no-store')
                self.assertNotIn(b'secret',response.read());connection.close()
            account.complete.assert_called_once_with('abc','secret',False)
        finally:server.shutdown();server.server_close()
