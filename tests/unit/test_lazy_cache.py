import asyncio
import tempfile
import unittest
from pathlib import Path
from threading import BoundedSemaphore
from threading import Event
from unittest.mock import MagicMock, patch

from linkmusicbot.bot import LinkMusicBot
from linkmusicbot.library import LocalLibrary
from linkmusicbot.security import QueryGuard
from unit.test_library import track


class LazyCacheTests(unittest.TestCase):
    def test_cancelled_background_task_keeps_slot_until_worker_finishes(self):
        self.library.put("song", [track("Old")])
        with self.library.db:
            self.library.db.execute("UPDATE queries SET updated=0")
        started, finish = Event(), Event()
        def worker(query):
            started.set()
            finish.wait(3)
        self.bot._refresh_query = worker
        async def run():
            self.bot._schedule_refresh("song")
            task = next(iter(self.bot._refresh_tasks))
            await asyncio.to_thread(started.wait, 1)
            self.assertTrue(started.is_set())
            task.cancel()
            await asyncio.sleep(0)
            self.assertIn("song", self.bot._refreshing)
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(run())
        self.assertNotIn("song", self.bot._refreshing)
        self.assertTrue(self.bot._work_slots.acquire(False))

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.library = LocalLibrary(str(Path(self.folder.name) / "cache.sqlite3"), refresh_seconds=100)
        self.addCleanup(self.library.db.close)
        self.bot = LinkMusicBot.__new__(LinkMusicBot)
        self.bot._library = self.library
        self.bot._guard = QueryGuard()
        self.bot._work_slots = BoundedSemaphore(2)
        self.bot._refreshing, self.bot._refresh_tasks = set(), set()

    def test_interval_stale_snapshot_and_retry_cooldown(self):
        with patch("linkmusicbot.library.time.time", return_value=100):
            self.library.put("song", [track("Old")])
        with patch("linkmusicbot.library.time.time", return_value=199):
            self.assertFalse(self.library.needs_refresh("song"))
        with patch("linkmusicbot.library.time.time", return_value=200):
            self.assertTrue(self.library.needs_refresh("song"))
            self.assertEqual(self.library.get("song")[0].title, "Old")
            self.library.mark_refresh("song")
            self.assertFalse(self.library.needs_refresh("song"))
        with patch("linkmusicbot.library.time.time", return_value=260):
            self.assertTrue(self.library.needs_refresh("song"))

    def test_duplicate_requests_start_only_one_background_refresh(self):
        self.library.put("song", [track("Old")])
        with self.library.db:
            self.library.db.execute("UPDATE queries SET updated=0")
        self.bot.handle_search = MagicMock(return_value=[track("New")])
        async def run():
            self.bot._schedule_refresh("song")
            self.bot._schedule_refresh("song")
            self.assertEqual(len(self.bot._refreshing), 1)
            await asyncio.gather(*self.bot._refresh_tasks)
        asyncio.run(run())
        self.bot.handle_search.assert_called_once_with("song")
        self.assertEqual(self.library.get("song")[0].title, "New")
        self.assertFalse(self.library.needs_refresh("song"))
        self.assertTrue(self.bot._work_slots.acquire(False))

    def test_empty_refresh_does_not_erase_previous_results(self):
        self.library.put("song", [track("Old")])
        self.bot.handle_search = MagicMock(return_value=[])
        self.bot._refresh_query("song")
        self.assertEqual(self.library.get("song")[0].title, "Old")

    def test_background_keeps_interactive_slot_and_separate_rate_budget(self):
        for query in ['one','two']:self.library.put(query,[track('Old')])
        with self.library.db:self.library.db.execute('UPDATE queries SET updated=0')
        started,finish=Event(),Event()
        def worker(query):
            started.set();finish.wait(3)
        self.bot._refresh_query=worker
        async def run():
            self.bot._schedule_refresh('one')
            await asyncio.to_thread(started.wait,1)
            self.bot._schedule_refresh('two')
            self.assertEqual(self.bot._refreshing,{'one'})
            self.assertTrue(self.bot._work_slots.acquire(False))
            self.bot._work_slots.release()
            self.assertEqual(len(self.bot._guard.global_requests),0)
            finish.set();await asyncio.gather(*self.bot._refresh_tasks)
        asyncio.run(run())

    def test_failed_refresh_keeps_cache_and_releases_worker(self):
        self.library.put("song", [track("Old")])
        with self.library.db:
            self.library.db.execute("UPDATE queries SET updated=0")
        self.bot.handle_search = MagicMock(side_effect=ValueError("service unavailable"))
        async def run():
            self.bot._schedule_refresh("song")
            await asyncio.gather(*self.bot._refresh_tasks)
        with patch("linkmusicbot.bot.logging.warning"):
            asyncio.run(run())
        self.assertEqual(self.library.get("song")[0].title, "Old")
        self.assertFalse(self.library.needs_refresh("song"))
        self.assertTrue(self.bot._work_slots.acquire(False))
