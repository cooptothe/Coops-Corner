import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from corner.collection_quota import LiveGovernor
from corner.collection_policy import POOLS,PROTECTED,TOTAL,BUDGET_VERSION
from corner.credit_governor import Refused
from pipelines.collection_budget_upgrade import upgrade,OLD_POOLS

class FullBudget(unittest.TestCase):
    def test_upgrade_preserves_accounting_and_audits_explicit_release(self):
        with tempfile.TemporaryDirectory() as folder:
            g=LiveGovernor(Path(folder)/'ledger.sqlite3')
            now=datetime(2026,11,1,18,tzinfo=timezone.utc)
            g.configure_cycle('nov',now.replace(day=1,hour=0),now.replace(month=12,day=1,hour=0))
            g.bind('nov','a'*64,12,TOTAL-12,{**{p:0 for p in POOLS},'main':12},now,'test')
            g.db.execute('UPDATE quota_policy SET version=?,limits_json=?,protected=?',('pregame-lab-history-100k-v1',json.dumps(OLD_POOLS),1500000))
            quota=dict(provider_used=12,provider_remaining=TOTAL-12)
            with self.assertRaises(Refused):upgrade(g,now,{**quota,'provider_used':13,'provider_remaining':TOTAL-13},'a'*64)
            self.assertEqual(upgrade(g,now,quota,'a'*64),'nov')
            self.assertEqual(g._binding(g.db,now)['used'],12)
            self.assertEqual(sum(g.accounted(g.db,'nov').values()),12)
            self.assertEqual(sum(POOLS.values()),TOTAL)
            self.assertEqual(PROTECTED,0)
            self.assertEqual(g.db.execute('SELECT version FROM quota_policy').fetchone()[0],BUDGET_VERSION)
            self.assertEqual(upgrade(g,now,quota,'a'*64),'nov')
            self.assertEqual(g.db.execute("SELECT count(*) FROM quota_audit WHERE action='full-budget-policy-approved'").fetchone()[0],1)
            g.close()

    def test_full_quota_still_refuses_next_paid_request(self):
        from unittest.mock import patch
        from corner.collection_policy import Job,STANDARD
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as folder:
            g=LiveGovernor(Path(folder)/'ledger.sqlite3')
            now=datetime(2026,11,1,18,tzinfo=timezone.utc)
            g.configure_cycle('nov',now.replace(day=1,hour=0),now.replace(month=12,day=1,hour=0))
            g.bind('nov','a'*64,TOTAL-1,1,{**POOLS,'main':POOLS['main']-1},now,'test')
            g.acquire('test',now)
            with self.assertRaises(Refused):
                g.claim(Job('main','basketball_nba','standard',STANDARD,('h2h','spreads','totals'),starts_at=(now+timedelta(hours=1)).isoformat()),'test',now)
            self.assertEqual(g.db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)
            g.close()
