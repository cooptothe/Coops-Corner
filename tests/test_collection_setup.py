from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from corner.collection_policy import POOLS,TOTAL,PROTECTED
from corner.collection_quota import LiveGovernor
from corner.credit_governor import Refused
from pipelines.collection_setup import initialize,status,SetupError
NOW=datetime(2026,10,20,16,tzinfo=timezone.utc)
KEY='synthetic-key-never-log'
def quota():
    return dict(result='verified_disabled_setup',quota_total=TOTAL,provider_used=0,provider_remaining=TOTAL,
        last_request_charge=0,quota_cycle_start_utc='2026-10-01T00:00:00+00:00',next_quota_reset_utc='2026-11-01T00:00:00+00:00',checked_at_utc=NOW.isoformat())
class Setup(unittest.TestCase):
    def test_new_ledger_paused_budget_preserved_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collection-live.sqlite3'
            result=initialize(path,KEY,quota(),NOW,'a'*40)
            self.assertTrue(result['paused']);self.assertEqual(sum(result['pools'].values())+result['protected_reserve'],TOTAL)
            self.assertEqual(result['pools']['history'],0);self.assertEqual(result['pools']['main'],7500000)
            self.assertNotIn(KEY,json.dumps(result));self.assertEqual(result['next_quota_reset_utc'],'2026-11-01T00:00:00+00:00')
            with self.assertRaises(SetupError):initialize(path,KEY,quota(),NOW,'a'*40)
            g=LiveGovernor(path)
            try:
                self.assertTrue(g.acquire('test',NOW))
                with self.assertRaises(Refused):g.authorize('test',NOW,'x'*64)
            finally:g.close()
            self.assertTrue(status(path)['paused'])
    def test_nonzero_or_stale_usage_never_creates_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collection-live.sqlite3'
            for changes in ({'provider_used':3,'provider_remaining':TOTAL-3},{'checked_at_utc':'2026-10-19T00:00:00+00:00'},{'next_quota_reset_utc':'2026-11-20T00:00:00+00:00'}):
                with self.assertRaises(SetupError):initialize(path,KEY,{**quota(),**changes},NOW,'a'*40)
                self.assertFalse(path.exists())
    def test_changed_policy_or_legacy_missing_policy_refuses_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collection-live.sqlite3';initialize(path,KEY,quota(),NOW,'a'*40)
            g=LiveGovernor(path)
            try:
                g.db.execute('DELETE FROM quota_policy')
                with self.assertRaises(Refused):g._binding(g.db,NOW)
            finally:g.close()
if __name__=='__main__':unittest.main()
