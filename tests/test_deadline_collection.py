import json,tempfile,unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from corner.deadline_pacing import plan as pace,remaining_seconds,END
from corner.collection_policy import Job,STANDARD,EXCHANGE,PROP_STANDARD,FAMILIES,parse,job_allowed,plan,POOLS,TOTAL
from corner.collection_quota import LiveGovernor
from corner.credit_governor import Refused
from pipelines.collection_budget_upgrade import upgrade

NOW=parse('2026-11-04T20:00:00Z');CYCLE_END=parse('2026-12-01T00:00:00Z')
def jobs():
    start=(NOW+timedelta(hours=1)).isoformat()
    return [Job('main','basketball_nba','standard',STANDARD,('h2h','spreads','totals'),starts_at=start),
            Job('props','basketball_nba','standard',PROP_STANDARD,tuple(m.key for m in FAMILIES['basketball']),'nba-game',start)]
def headers(used,charge):return {'x-requests-used':str(used),'x-requests-remaining':str(TOTAL-used),'x-requests-last':str(charge)}

class DeadlineMath(unittest.TestCase):
    def test_budget_ends_nov20_instead_of_quota_reset(self):
        self.assertEqual(remaining_seconds(NOW,CYCLE_END),298*3600)
        self.assertEqual(remaining_seconds(END,CYCLE_END),0)
        p=pace(NOW,CYCLE_END,jobs(),14244123)
        self.assertAlmostEqual(p['target_credits_per_hour'],47799.07,places=2)
        self.assertEqual(p['deadline_utc'],END.isoformat())

    def test_busy_days_get_more_budget_than_quiet_future_days(self):
        end=parse('2026-11-06T06:00:00Z')
        uniform=pace(NOW,end,jobs(),100000)
        weighted=pace(NOW,end,jobs(),100000,day_weights={'2026-11-04':2,'2026-11-05':1})
        self.assertGreater(weighted['target_credits_per_hour'],uniform['target_credits_per_hour'])
        self.assertTrue(weighted['schedule_weighted'])
        self.assertEqual(weighted['remaining_regular_hours'],uniform['remaining_regular_hours'])

    def test_low_demand_reaches_floors_and_reports_capacity_shortfall(self):
        js=jobs()+[Job('live','basketball_nba','exchange',EXCHANGE,('h2h','spreads','totals'))]
        p=pace(NOW,CYCLE_END,js,14244123)
        self.assertEqual(p['state'],'source_capacity_limited')
        self.assertEqual([p['interval_seconds'][j.key] for j in js],[60,60,10])

    def test_dense_slate_is_paced_and_prioritizes_near_games(self):
        js=jobs()
        distant=Job('props','basketball_nba','standard',PROP_STANDARD,js[1].markets,'later',(NOW+timedelta(hours=18)).isoformat())
        p=pace(NOW,CYCLE_END,js+[distant],1000)
        self.assertLessEqual(p['expected_credits_per_hour'],p['target_credits_per_hour']+0.01)
        self.assertGreater(p['interval_seconds'][distant.key],p['interval_seconds'][js[1].key])

    def test_verified_empty_responses_do_not_artificially_consume_budget(self):
        js=jobs();sample={j.key:{'actual':0,'reserved':j.cost} for j in js}
        p=pace(NOW,CYCLE_END,js,1000,sample)
        self.assertEqual(p['expected_credits_per_hour'],0)
        self.assertEqual(p['interval_seconds'][js[0].key],60)

    def test_additional_admission_keeps_its_reviewed_poll_bound(self):
        from corner.additional_markets import SCHEDULED_ADDITIONAL_MARKETS
        from corner.collection_policy import interval
        j=Job('additional','basketball_nba','exchange',EXCHANGE,SCHEDULED_ADDITIONAL_MARKETS,'alt-game',(NOW+timedelta(minutes=75)).isoformat())
        p=pace(NOW,CYCLE_END,[j],14000000)
        self.assertGreaterEqual(p['interval_seconds'][j.key],interval(j.kind,j.group,NOW,parse(j.starts_at)))

    def test_campaign_does_not_pay_for_an_empty_pregame_league(self):
        self.assertEqual(plan(NOW,['basketball_nba'],[]),[])

    def test_overnight_is_sport_and_event_scoped(self):
        now=parse('2026-11-05T08:00:00Z') # 2am Central
        start=(now+timedelta(hours=1)).isoformat()
        soccer=Job('main','soccer_epl','standard',STANDARD,('h2h','spreads','totals'),starts_at=start)
        tennis=Job('live','tennis_atp_paris_masters','exchange',EXCHANGE,('h2h','spreads','totals'))
        self.assertTrue(job_allowed(soccer,now));self.assertTrue(job_allowed(tennis,now))
        self.assertFalse(job_allowed(jobs()[0],now))
        self.assertFalse(job_allowed(Job('main','soccer_epl','standard',STANDARD,('h2h','spreads','totals')),now))
        self.assertFalse(job_allowed(soccer,END))
        self.assertTrue(job_allowed(jobs()[0],parse('2026-11-05T05:00:00Z'))) # 11pm

class DeadlineLedger(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.g=LiveGovernor(Path(self.tmp.name)/'ledger.sqlite3')
        self.g.configure_cycle('nov',parse('2026-11-01T00:00:00Z'),CYCLE_END)
        self.g.bind('nov','a'*64,0,TOTAL,{k:0 for k in POOLS},NOW,'test')
        self.g.acquire('worker',NOW)
    def tearDown(self):self.g.close();self.tmp.cleanup()

    def test_dynamic_pool_transfer_preserves_global_limit_and_requests(self):
        js=jobs();self.g.configure_deadline_pacing(js,'worker',NOW)
        limits=self.g.pool_limits(self.g.db,'nov')
        self.assertEqual(sum(limits.values()),TOTAL)
        self.assertEqual(self.g.db.execute('SELECT ends FROM cycles').fetchone()[0],CYCLE_END.timestamp())
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)
        self.assertTrue(self.g.ready(js[0],NOW))
        self.g.prepare_due(js[0],'worker',NOW);token=self.g.claim(js[0],'worker',NOW)
        self.g.finish(js[0],token,'worker',NOW,headers(3,3),[])
        self.assertFalse(self.g.ready(js[0],NOW+timedelta(seconds=59)))
        self.assertTrue(self.g.ready(js[0],NOW+timedelta(seconds=60)))
        self.assertEqual(sum(self.g.accounted(self.g.db,'nov').values()),3)

    def test_transfer_preserves_an_outstanding_reservation(self):
        js=jobs();self.g.configure_deadline_pacing(js,'worker',NOW)
        self.g.prepare_due(js[0],'worker',NOW);token=self.g.claim(js[0],'worker',NOW)
        later=NOW+timedelta(seconds=61)
        self.g.configure_deadline_pacing([js[1]],'worker',later)
        self.assertGreaterEqual(self.g.pool_limits(self.g.db,'nov')['main'],3)
        self.g.finish(js[0],token,'worker',later,headers(3,3),[])
        self.assertEqual(sum(self.g.accounted(self.g.db,'nov').values()),3)

    def test_zero_cost_main_pool_retains_full_reservation_room(self):
        js=jobs()
        self.g.db.execute('INSERT INTO deadline_charge_samples VALUES(?,?,?,?)',(js[0].key,0,3,NOW.timestamp()))
        self.g.configure_deadline_pacing(js,'worker',NOW)
        self.assertGreaterEqual(self.g.pool_limits(self.g.db,'nov')['main'],3)
        self.g.prepare_due(js[0],'worker',NOW);token=self.g.claim(js[0],'worker',NOW)
        self.g.finish(js[0],token,'worker',NOW,headers(0,0),[])
        self.assertEqual(sum(self.g.accounted(self.g.db,'nov').values()),0)

    def test_free_inventory_still_works_with_zero_metadata_allocation(self):
        token=self.g.authorize('worker',NOW,'a'*64,inventory=True)
        self.g.inventory_finish(token,'worker',NOW,headers(0,0),200)
        self.assertEqual(self.g.db.execute('SELECT actual FROM quota_inventory').fetchone()[0],0)

    def test_low_storage_refuses_before_any_reservation_or_http(self):
        from types import SimpleNamespace
        self.g.configure_deadline_pacing(jobs(),'worker',NOW)
        with patch('shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(Refused,'Low storage'):
                self.g.claim(jobs()[0],'worker',NOW)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)

    def test_no_pacing_no_purchase_and_expired_deadline_no_purchase(self):
        with self.assertRaises(Refused):self.g.claim(jobs()[0],'worker',NOW)
        self.g.configure_deadline_pacing(jobs(),'worker',NOW)
        self.assertFalse(self.g.ready(jobs()[0],END))

    def test_final_full_charge_settles_exactly_at_fifteen_million(self):
        self.g.db.execute('UPDATE quota_bindings SET used=?,offsets=?',(TOTAL-3,json.dumps({'main':POOLS['main']-3,'props':POOLS['props'],'metadata':0,'history':0})))
        j=jobs()[0];self.g.configure_deadline_pacing([j],'worker',NOW)
        self.g.prepare_due(j,'worker',NOW);token=self.g.claim(j,'worker',NOW)
        self.g.finish(j,token,'worker',NOW,headers(TOTAL,3),[])
        row=self.g.db.execute('SELECT state,actual FROM attempts WHERE token=?',(token,)).fetchone()
        self.assertEqual(tuple(row),('settled',3))
        self.assertEqual(sum(self.g.accounted(self.g.db,'nov').values()),TOTAL)
        with self.assertRaises(Refused):self.g.claim(j,'worker',NOW+timedelta(days=1))

    def test_archived_october_policy_cannot_block_november_worker(self):
        from pipelines.collection_runner import Runner
        self.g.configure_cycle('oct',parse('2026-10-01T00:00:00Z'),parse('2026-11-01T00:00:00Z'))
        self.g.db.execute('INSERT INTO quota_policy VALUES(?,?,?,?,?)',('oct','full-quota-main-props-live-v2',json.dumps({'main':7500000,'props':7400000,'metadata':100000,'history':0}),TOTAL,0))
        runner=Runner(self.g,lambda:{'active_sport_keys':[],'events':[],'discovered_at':NOW.isoformat()},None,clock=lambda:NOW,owner='worker')
        result=runner.tick()
        self.assertEqual(result['executed'],0)
        self.assertNotEqual(result['state'],'paused')
        status=self.g.status()
        archived=next(c for c in status['cycles'] if c['id']=='oct')
        self.assertEqual(archived['remaining_pools']['main'],7500000)
        # Current-cycle validation must still reject an old policy version.
        self.g.db.execute("UPDATE quota_policy SET version='full-quota-main-props-live-v2' WHERE cycle_id='nov'")
        with self.assertRaises(Refused):self.g._binding(self.g.db,NOW)

    def test_v2_migration_is_idempotent_and_preserves_cycle(self):
        self.g.release('worker')
        prior={'main':7500000,'props':7400000,'metadata':100000,'history':0}
        self.g.db.execute('UPDATE quota_policy SET version=?,limits_json=?',('full-quota-main-props-live-v2',json.dumps(prior)))
        quota={'provider_used':0,'provider_remaining':TOTAL}
        self.assertEqual(upgrade(self.g,NOW,quota,'a'*64),'nov')
        self.assertEqual(upgrade(self.g,NOW,quota,'a'*64),'nov')
        self.assertEqual(self.g.pool_limits(self.g.db,'nov'),POOLS)
        self.assertEqual(self.g.db.execute("SELECT count(*) FROM quota_audit WHERE action='full-budget-policy-approved'").fetchone()[0],1)

    def test_storage_target_blocks_paid_calls_at_fifty_percent(self):
        from types import SimpleNamespace
        self.g.configure_deadline_pacing(jobs(),'worker',NOW)
        with patch.dict('os.environ',{'CORNER_STORAGE_TARGET_PERCENT':'50'}), patch('shutil.disk_usage',return_value=SimpleNamespace(free=10*1024**3,used=50,total=100)):
            with self.assertRaisesRegex(Refused,'Low storage'):self.g.claim(jobs()[0],'worker',NOW)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)
