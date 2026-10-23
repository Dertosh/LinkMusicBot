import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from linkmusicbot.library import LocalLibrary
from linkmusicbot.bot import LinkMusicBot, _RECHECKING_CACHE
from linkmusicbot.security import QueryGuard
from linkmusicbot.models import Song
from unit.test_library import track


class CacheRevisionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.library=LocalLibrary(str(Path(self.folder.name)/'cache.sqlite3'))
        self.addCleanup(self.library.db.close)

    def test_new_algorithm_keeps_snapshot_but_requires_refresh(self):
        self.library.put('song',[track('Old')])
        self.assertFalse(self.library.needs_refresh('song'))
        self.library.mark_refresh('song')
        self.library.revision='next-algorithm'
        self.assertTrue(self.library.needs_refresh('song'))
        self.assertEqual(self.library.get('song')[0].title,'Old')
        self.library.mark_refresh('song')
        self.assertFalse(self.library.needs_refresh('song'))
        self.library.put('song',[track('New')])
        self.assertFalse(self.library.needs_refresh('song'))
        self.assertEqual(self.library.get('song')[0].title,'New')

    def test_revision_depends_on_search_implementation(self):
        from linkmusicbot.cache_revision import search_revision
        original=search_revision()
        try:
            search_revision.cache_clear()
            with patch.object(Path,'read_bytes',return_value=b'changed implementation'):
                self.assertNotEqual(search_revision(),original)
        finally:search_revision.cache_clear()

    def test_legacy_database_and_quota_records_are_preserved(self):
        with self.library.db:
            self.library.db.execute('INSERT INTO queries VALUES (?,?,?)',('legacy','[]',9999999999))
            self.library.db.execute('CREATE TABLE youtube_search_calls(called REAL)')
            self.library.db.execute('INSERT INTO youtube_search_calls VALUES (123)')
        self.assertTrue(self.library.needs_refresh('legacy'))
        self.assertEqual(self.library.get('legacy'),[])
        self.assertEqual(self.library.db.execute('SELECT called FROM youtube_search_calls').fetchone()[0],123)

    def test_refresh_failure_does_not_stamp_old_result_as_new(self):
        self.library.put('song',[track('Old')]);self.library.revision='next'
        bot=LinkMusicBot.__new__(LinkMusicBot);bot._library=self.library;bot._guard=QueryGuard()
        bot.handle_search=Mock(return_value=[])
        bot._refresh_query('song')
        self.assertTrue(self.library.needs_refresh('song'))
        self.assertEqual(self.library.get('song')[0].title,'Old')
        self.assertFalse(_RECHECKING_CACHE.get())

    def test_recheck_cannot_return_only_old_local_candidates(self):
        self.library.put('song',[track('Old Song')])
        bot=LinkMusicBot.__new__(LinkMusicBot);bot._library=self.library;bot._guard=QueryGuard()
        service=Mock();service.service_name.return_value='Spotify';service.search.return_value=[]
        bot.search_service=service;bot._music_services=[service];bot.make_iqr=Mock()
        bot._refresh_query('song')
        self.assertEqual(self.library.get('song')[0].title,'Old Song')
        bot.make_iqr.assert_not_called()

    def test_recheck_requests_links_instead_of_reusing_old_cross_links(self):
        from telegram import InlineKeyboardButton
        from linkmusicbot.presentation import build_result
        song=Song('Song','Artist','')
        self.library.put('song',[build_result(song,[[InlineKeyboardButton('Spotify',url='https://open.spotify.com/track/old')]])])
        bot=LinkMusicBot.__new__(LinkMusicBot);bot._library=self.library
        service=Mock();service.service_name.return_value='Spotify'
        service.object_to_link.return_value='https://open.spotify.com/track/new'
        service.can_handle_link.return_value=True;bot._music_services=[service]
        token=_RECHECKING_CACHE.set(True)
        try:result=bot.make_iqr(song)
        finally:_RECHECKING_CACHE.reset(token)
        service.object_to_link.assert_called_once()
        passed = service.object_to_link.call_args.args[0]
        self.assertEqual((passed.title, passed.artist, passed.album), (song.title, song.artist, song.album))
        self.assertEqual(result.reply_markup.inline_keyboard[0][0].url,'https://open.spotify.com/track/new')
