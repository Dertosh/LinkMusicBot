import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from cryptography.fernet import Fernet
from linkmusicbot.spotify_account import SpotifyAccount, AccountError, NotConnected, SCOPE


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=str(Path(self.folder.name)/'private.sqlite3')
        self.key=Fernet.generate_key()
        self.account=SpotifyAccount('client','https://music.example.com/spotify/callback',self.key,self.path)
        self.token={'access_token':'private-access','refresh_token':'private-refresh',
                    'expires_in':3600,'scope':SCOPE}

    def tearDown(self):
        self.account.close();self.folder.cleanup()

    def connect(self,user=1):
        params=parse_qs(urlparse(self.account.begin(user)).query)
        with patch.object(self.account,'_request',return_value=(200,self.token)) as request:
            self.account.complete(params['state'][0],'code')
        return params,request

    @staticmethod
    def playback(**extra):
        return dict({'is_playing':True,'currently_playing_type':'track','item':{
            'id':'1r9xUipOqoNwggBpENDsvJ','name':'Enemy','artists':[{'name':'Imagine Dragons'},{'name':'JID'}],
            'album':{'name':'Enemy','images':[{'url':'https://i.scdn.co/image/cover'}]},'duration_ms':173381}},**extra)

    def test_pkce_one_use_state_and_encrypted_storage(self):
        params,request=self.connect()
        self.assertEqual(params['code_challenge_method'],['S256'])
        self.assertEqual(params['scope'],[SCOPE])
        self.assertIn('code_verifier',request.call_args.kwargs['data'])
        blob=self.account.db.execute('SELECT token FROM accounts').fetchone()[0]
        self.assertNotIn(b'private-access',blob);self.assertNotIn(b'private-refresh',blob)
        with self.assertRaises(AccountError):self.account.complete(params['state'][0],'replay')

    def test_state_expiry_replacement_and_denial(self):
        state=parse_qs(urlparse(self.account.begin(1)).query)['state'][0]
        self.account.begin(1)
        with self.assertRaises(AccountError):self.account.complete(state,'old')
        state=parse_qs(urlparse(self.account.begin(1)).query)['state'][0]
        with self.account.db:self.account.db.execute('UPDATE states SET expires=0')
        with self.assertRaises(AccountError):self.account.complete(state,'expired')
        state=parse_qs(urlparse(self.account.begin(1)).query)['state'][0]
        with self.assertRaises(AccountError):self.account.complete(state,denied=True)

    def test_current_user_isolation_cover_and_source_link(self):
        self.connect()
        with patch.object(self.account,'_request',return_value=(200,self.playback())):
            song=self.account.current(1)
            self.assertEqual(song.title,'Enemy');self.assertEqual(song.duration_ms,173381)
            self.assertIsNotNone(song.cover_art)
            self.assertTrue(song.service_links['Spotify'].endswith('1r9xUipOqoNwggBpENDsvJ'))
            with self.assertRaises(NotConnected):self.account.current(2)

    def test_no_playback_paused_episode_ad_and_local_are_not_tracks(self):
        self.connect()
        payloads=[(204,{}),(200,self.playback(is_playing=False)),
                  (200,self.playback(currently_playing_type='episode')),
                  (200,self.playback(currently_playing_type='ad',item=None)),
                  (200,self.playback(item={'id':'local','is_local':True}))]
        for response in payloads:
            with self.subTest(response=response),patch.object(self.account,'_request',return_value=response):
                self.assertIsNone(self.account.current(1))

    def test_refresh_rotation_omission_and_persistence(self):
        self.connect()
        token=self.account._decrypt(self.account.db.execute('SELECT token FROM accounts').fetchone()[0])
        token['expires_at']=0
        with self.account.db:self.account.db.execute('UPDATE accounts SET token=?',(self.account._encrypt(token),))
        with patch.object(self.account,'_request',side_effect=[(200,{'access_token':'new','expires_in':3600}),(200,self.playback())]):
            self.account.current(1)
        self.account.close()
        self.account=SpotifyAccount('client','https://music.example.com/spotify/callback',self.key,self.path)
        saved=self.account._decrypt(self.account.db.execute('SELECT token FROM accounts').fetchone()[0])
        self.assertEqual(saved['refresh_token'],'private-refresh')
        self.assertEqual(saved['access_token'],'new')

    def test_expired_refresh_requires_reconnect(self):
        self.connect()
        with patch.object(self.account,'_request',side_effect=[(401,{}),(400,{'error':'invalid_grant'})]):
            with self.assertRaises(NotConnected):self.account.current(1)
        self.assertIsNone(self.account.db.execute('SELECT token FROM accounts').fetchone())

    def test_disconnect_removes_tokens_and_pending_authorization(self):
        self.connect();state=parse_qs(urlparse(self.account.begin(1)).query)['state'][0]
        self.account.disconnect(1)
        with self.assertRaises(NotConnected):self.account.current(1)
        with self.assertRaises(AccountError):self.account.complete(state,'code')

    def test_missing_scope_and_temporary_error(self):
        with self.assertRaises(AccountError):self.account._save(1,dict(self.token,scope=''))
        self.connect()
        with patch.object(self.account,'_request',return_value=(429,{'error':'private-token-value'})):
            with self.assertRaises(AccountError) as error:self.account.current(1)
        self.assertNotIn('private-token-value',str(error.exception))

    def test_invalid_callback_uri(self):
        for url in ['http://example.com/spotify/callback','https://example.com/other','https://user:pass@example.com/spotify/callback']:
            with self.subTest(url=url),self.assertRaises(ValueError):
                SpotifyAccount('client',url,self.key,self.path)

    def test_two_connected_accounts_use_separate_access_tokens(self):
        self.account._save(1,dict(self.token,access_token='alice'))
        self.account._save(2,dict(self.token,access_token='bob'))
        with patch.object(self.account,'_request',return_value=(200,self.playback())) as request:
            self.account.current(1);self.account.current(2)
        self.assertEqual([call.kwargs['headers']['Authorization'] for call in request.call_args_list],
                         ['Bearer alice','Bearer bob'])
