import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from linkmusicbot.usage import UsageStats


class UsageTests(unittest.TestCase):
    def test_daily_user_totals_persist_without_query_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'usage.sqlite3');stats=UsageStats(path)
            one=SimpleNamespace(id=1,username='one');two=SimpleNamespace(id=2,username=None)
            stats.record(one,'inline');stats.record(one,'inline');stats.record(two,'start')
            one.username='renamed';stats.record(one,'current')
            report=stats.report()
            self.assertEqual(report['unique_users'],2)
            self.assertEqual(report['events'],{'current':1,'inline':2,'start':1})
            self.assertEqual(report['users'][0],{'telegram_id':1,'username':'renamed','requests':3})
            self.assertIsNotNone(report['recording_started_utc'])
            stats.close();stats=UsageStats(path)
            self.assertEqual(stats.report()['events']['inline'],2)
            stats.close()
