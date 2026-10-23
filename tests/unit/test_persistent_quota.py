import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from linkmusicbot.security import SearchQuota, QuotaExceeded
from linkmusicbot.services import YouTube


class PersistentQuotaTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / "music.sqlite3")

    def quota(self, limit=2):
        quota = SearchQuota(limit, self.path)
        self.addCleanup(quota.db.close)
        return quota

    def test_count_survives_recreation(self):
        self.quota().reserve()
        restarted = self.quota()
        self.assertEqual(restarted.status()["used"], 1)
        restarted.reserve()
        with self.assertRaises(QuotaExceeded):
            self.quota().reserve()

    def test_old_reservations_expire_after_24_hours(self):
        quota = self.quota(1)
        with patch("linkmusicbot.security.time.time", return_value=100):
            quota.reserve()
        with patch("linkmusicbot.security.time.time", return_value=86500):
            self.quota(1).reserve()
            self.assertEqual(quota.status()["used"], 1)

    def test_remote_exhaustion_survives_restart(self):
        with patch("linkmusicbot.security.time.time", return_value=100):
            self.quota().mark_exhausted()
            with self.assertRaises(QuotaExceeded):
                self.quota().reserve()
        with patch("linkmusicbot.security.time.time", return_value=86500):
            self.quota().reserve()

    def test_concurrent_instances_cannot_exceed_shared_limit(self):
        instances = [self.quota(3) for _ in range(10)]
        def reserve(quota):
            try:
                quota.reserve()
                return True
            except QuotaExceeded:
                return False
        with ThreadPoolExecutor(max_workers=10) as pool:
            self.assertEqual(sum(pool.map(reserve, instances)), 3)
        self.assertEqual(instances[0].status()["used"], 3)

    def test_rate_limit_is_temporary_and_metadata_has_separate_budget(self):
        service = YouTube()
        service._search_quota = self.quota()
        payload = {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}
        with patch("linkmusicbot.security.time.time", return_value=100):
            service._record_quota_error(service._SEARCH_PATH, payload)
            self.assertEqual(service._search_quota.status()["blocked_until"], 160)
        with patch("linkmusicbot.security.time.time", return_value=160):
            restarted = self.quota()
            restarted.reserve()
            service._record_quota_error(service._PLAYLIST_PATH,
                                       {"error": {"errors": [{"reason": "quotaExceeded"}]}})
            restarted.reserve()

    def test_unlimited_mode_still_counts_and_respects_remote_block(self):
        quota = self.quota(0)
        quota.reserve()
        self.assertEqual(quota.status()["used"], 1)
        quota.mark_exhausted()
        with self.assertRaises(QuotaExceeded):
            self.quota(0).reserve()
