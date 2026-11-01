import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from corner.collection_quota import LiveGovernor
from corner.credit_governor import Refused
from corner.collection_policy import POOLS, TOTAL
from pipelines.collection_rollover import bind_month

class Rollover(unittest.TestCase):
    def test_new_binding_preserves_old_and_refuses_rebinding(self):
        with tempfile.TemporaryDirectory() as tmp:
            g=LiveGovernor(Path(tmp)/'ledger.sqlite3')
            old=datetime(2026,10,1,tzinfo=timezone.utc)
            now=datetime(2026,11,1,14,tzinfo=timezone.utc)
            g.configure_cycle('oct',old,now.replace(hour=0))
            g.bind('oct','a'*64,0,TOTAL,{p:0 for p in POOLS},old,'test')
            q=dict(provider_used=0,provider_remaining=TOTAL,last_request_charge=0,
                quota_cycle_start_utc='2026-11-01T00:00:00+00:00',next_quota_reset_utc='2026-12-01T00:00:00+00:00')
            for bad in ({**q,'provider_used':3,'provider_remaining':TOTAL-3},):
                with self.assertRaises(Refused): bind_month(g,now,bad,'a'*64)
            with self.assertRaises(Refused): bind_month(g,now,q,'b'*64)
            self.assertEqual(bind_month(g,now,q,'a'*64)[0],'quota-2026-11')
            self.assertEqual(g.db.execute('SELECT count(*) FROM quota_bindings').fetchone()[0],2)
            with self.assertRaises(Refused): bind_month(g,now,q,'a'*64)
            g.close()
