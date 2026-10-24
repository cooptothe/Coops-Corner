from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from corner.collection_policy import STANDARD

from corner.collection_policy import EXCHANGE, Job
from corner.collection_quota import LiveGovernor, key_identity
from corner.credit_governor import Refused
from pipelines.collection_exchange_repair import repair
from tests.test_collection_live import NOW, ZERO, headers


class ExchangeCompanionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'collection-live.sqlite3'
        self.g=LiveGovernor(self.path)
        self.g.configure_cycle('cycle',NOW-timedelta(days=1),NOW+timedelta(days=20))
        self.g.bind('cycle',key_identity('fixture'),0,15000000,ZERO,NOW,'fixture')
        self.g.acquire('worker',NOW)
        self.job=Job('main','basketball_nba','exchange',EXCHANGE,('h2h','spreads','totals'))

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def payload(self,extra='h2h_lay'):
        return [{'id':'event','sport_key':'basketball_nba','commence_time':(NOW+timedelta(hours=2)).isoformat(),
            'home_team':'Home','away_team':'Away','bookmakers':[
                {'key':book,'title':book,'last_update':NOW.isoformat(),'markets':[
                    {'key':market,'outcomes':[{'name':'Home','price':2.1},{'name':'Away','price':1.9}]}
                    for market in (('h2h',extra) if book=='betfair_ex_uk' else ('h2h',))]}
                for book in ('betfair_ex_uk','novig')]}]

    def finish(self,payload):
        self.g.prepare_due(self.job,'worker',NOW)
        token=self.g.claim(self.job,'worker',NOW)
        return token,self.g.finish(self.job,token,'worker',NOW,headers(3,3),payload)

    def test_companion_kept_and_other_books_publish_without_extra_charge(self):
        token,result=self.finish(self.payload())
        self.assertEqual(result,'published')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM snapshots').fetchone()[0],3)
        self.assertEqual(self.g.db.execute("SELECT count(*) FROM snapshots WHERE market='h2h_lay'").fetchone()[0],1)
        self.assertEqual(self.g.db.execute('SELECT actual FROM attempts').fetchone()[0],3)
        self.assertIn('h2h_lay',self.g.db.execute('SELECT payload FROM publication_outbox').fetchone()[0])
        # Withdrawal of a previously quoted lay must remove its old snapshot.
        self.g._publish(self.g.db,self.job,self.payload('h2h_lay')[:0],NOW+timedelta(seconds=1))
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM snapshots').fetchone()[0],0)

    def test_unrelated_unrequested_market_remains_quarantined(self):
        _,result=self.finish(self.payload('player_points'))
        self.assertEqual(result,'quarantined')
        self.assertEqual(repair(self.path,now=NOW)['eligible_scopes'],0)

    def test_companion_does_not_expand_standard_request_scope(self):
        self.job=Job('main','basketball_nba','standard',STANDARD,('h2h','spreads','totals'))
        payload=self.payload()
        payload[0]['bookmakers']=payload[0]['bookmakers'][:1]
        payload[0]['bookmakers'][0]['key']='draftkings'
        _,result=self.finish(payload)
        self.assertEqual(result,'quarantined')
        self.assertEqual(self.g.db.execute('SELECT code FROM collection_quarantine').fetchone()[0],'market_mismatch')

    def test_rejection_expires_previous_lay_snapshot_too(self):
        self.g._publish(self.g.db,self.job,self.payload(),NOW)
        self.assertEqual(self.g.db.execute("SELECT count(*) FROM snapshots WHERE market='h2h_lay' AND expires_at>?",(NOW.timestamp(),)).fetchone()[0],1)
        _,result=self.finish(self.payload('player_points'))
        self.assertEqual(result,'quarantined')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM snapshots WHERE expires_at>?',(NOW.timestamp(),)).fetchone()[0],0)

    def old_quarantine(self):
        token,_=self.finish(self.payload('player_points'))
        detail=json.loads(self.g.db.execute('SELECT detail FROM collection_quarantine').fetchone()[0])
        detail['payload']=self.payload()
        self.g.db.execute('UPDATE collection_quarantine SET detail=?',(json.dumps(detail),))
        return token

    def test_repair_archives_evidence_preserves_accounting_and_does_not_publish(self):
        self.old_quarantine()
        before=[tuple(r) for r in self.g.db.execute('SELECT * FROM attempts')]
        due=self.g.db.execute('SELECT next_due,last_started FROM jobs').fetchone()
        self.assertEqual(repair(self.path,now=NOW)['eligible_scopes'],1)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM collection_quarantine').fetchone()[0],1)
        self.g.release('worker')
        result=repair(self.path,apply=True,now=NOW)
        self.assertEqual(result['released_scopes'],1)
        self.assertEqual([tuple(r) for r in self.g.db.execute('SELECT * FROM attempts')],before)
        self.assertEqual(tuple(self.g.db.execute('SELECT next_due,last_started FROM jobs').fetchone()),tuple(due))
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM exchange_quarantine_archive').fetchone()[0],1)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM publication_outbox').fetchone()[0],0)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM snapshots').fetchone()[0],0)
        self.assertEqual(repair(self.path,apply=True,now=NOW)['released_scopes'],0)

    def test_repair_refuses_active_worker_and_missing_charge_evidence(self):
        self.old_quarantine()
        with self.assertRaises(Refused):repair(self.path,apply=True,now=NOW)
        self.g.db.execute("DELETE FROM quota_audit WHERE action='odds-response'")
        self.assertEqual(repair(self.path,now=NOW)['eligible_scopes'],0)


if __name__=='__main__':unittest.main()
