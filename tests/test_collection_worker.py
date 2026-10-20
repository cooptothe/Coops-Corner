import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from corner.collection_policy import (plan, parse, open_now, interval, STANDARD, EXCHANGE,
                                      PROP_STANDARD, SPORTS, Job, POOLS)
from corner.credit_governor import Governor, Refused
from pipelines.collection_worker import tick,fixture_transport

NOW=parse('2026-10-16T15:00:00Z')
START=(NOW+timedelta(minutes=10)).isoformat()


def event(ident='event1',start=START,sport='basketball_nba'):
    return {'id':ident,'sport_key':sport,'commence_time':start,
            'home_team':'Simulation home','away_team':'Simulation away'}


def payload(job,now=NOW,ident='event1'):
    e=event(ident=ident)
    e['sport_key']=job.sport
    e['bookmakers']=[{'key':job.books[0],'last_update':now.isoformat(),
                     'markets':[{'key':job.markets[0],'last_update':now.isoformat(),
                                 'outcomes':[{'name':'Over','description':'Simulated player','point':10.5,'price':2.1}]}]}]
    return [e]


class Policy(unittest.TestCase):
    def test_catalog_matches_current_code_and_book_groups_disjoint(self):
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'pipelines/refresh_service.py').read_text())
        sports=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SPORTS' for t in n.targets))
        self.assertEqual(set(sports),set(SPORTS))
        self.assertFalse(set(STANDARD)&set(EXCHANGE))
        self.assertEqual(len(STANDARD+EXCHANGE),12)
        self.assertEqual(len(PROP_STANDARD+EXCHANGE),14)
        self.assertNotIn('betonlineag',STANDARD+EXCHANGE+PROP_STANDARD)

    def test_central_boundaries_and_dst(self):
        for day in ('2026-10-16','2026-11-01','2027-03-14'):
            import pytz
            zone=pytz.timezone('America/Chicago')
            self.assertFalse(open_now(zone.localize(datetime.fromisoformat(day+'T07:59:59'))))
            self.assertTrue(open_now(zone.localize(datetime.fromisoformat(day+'T08:00:00'))))
            self.assertTrue(open_now(zone.localize(datetime.fromisoformat(day+'T23:59:59'))))
            self.assertFalse(open_now(zone.localize(datetime.fromisoformat(day+'T00:00:00'))))
        with self.assertRaises(ValueError): open_now(datetime(2026,10,16))

    def test_props_bands_and_main_floor(self):
        for seconds,standard,exchange in [(900,60,20),(901,60,20),(7200,60,20),(7201,300,300),(21600,300,300),(21601,3600,3600)]:
            for group,expected in [('standard',standard),('exchange',exchange)]:
                self.assertEqual(interval('props',group,NOW,NOW+timedelta(seconds=seconds)),expected)
        self.assertEqual(interval('main','standard',NOW),300)
        self.assertEqual(interval('main','exchange',NOW),20)

    def test_all_families_no_event_cap_and_no_started_events(self):
        sportkeys=[s for s in SPORTS if s not in ('tennis_atp','tennis_wta')]
        events=[event(str(i),sport=s) for i,s in enumerate(sportkeys)]
        jobs=plan(NOW,sportkeys,events+events)
        self.assertEqual(len([j for j in jobs if j.kind=='props']),24)
        self.assertEqual(sum(len(j.markets) for j in jobs if j.kind=='props'),135*2)
        self.assertEqual(len(plan(NOW,['basketball_nba'],[event(str(i)) for i in range(50)])),102)
        self.assertEqual(len(plan(NOW,['basketball_nba'],[event(start=NOW.isoformat())])),2)
        self.assertEqual(plan(parse('2026-10-16T06:00:00Z'),sportkeys,events),[])
        with self.assertRaises(ValueError): plan(NOW,['tennis_atp'],[])


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'simulation.sqlite3'
        self.g=Governor(self.path)
        self.g.configure_cycle('test',NOW-timedelta(days=1),NOW+timedelta(days=30))
        self.g.acquire('worker',NOW)
        self.jobs=plan(NOW,['basketball_nba'],[event()])
        self.main,self.fast,self.prop,self.propfast=self.jobs

    def tearDown(self):
        self.g.close();self.tmp.cleanup()

    def complete(self,job,at=NOW,body=None,charge=None):
        self.g.prepare_due(job,'worker',at)
        token=self.g.claim(job,'worker',at)
        self.g.finish(job,token,'worker',at,{'x-requests-last':str(job.cost if charge is None else charge),'x-requests-remaining':'15000000'},payload(job,at) if body is None else body)
        return token

    def test_reserve_reconcile_actual_and_duplicate_completion(self):
        token=self.complete(self.main,charge=1)
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'],1)
        with self.assertRaises(Refused): self.g.claim(self.main,'worker',NOW)
        with self.assertRaises(Refused): self.g.finish(self.main,token,'worker',NOW,{},[])
        self.assertEqual(len(self.g.snapshots(NOW)),1)

    def test_single_lease_and_concurrent_budget_reservations(self):
        self.assertFalse(self.g.acquire('other',NOW))
        def claim(i):
            g=Governor(self.path)
            try:
                try: g.claim(self.main,'worker',NOW);return True
                except Refused: return False
            finally:g.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(claim,range(8))),1)
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'],3)

    def test_graceful_release_preserves_cadence_for_replacement(self):
        self.complete(self.main)
        self.g.release('worker')
        self.assertTrue(self.g.acquire('replacement',NOW))
        self.assertFalse(self.g.ready(self.main,NOW))
        with self.assertRaises(Refused):self.g.claim(self.main,'replacement',NOW)

    def test_budget_does_not_spend_reserve_and_no_cycle_reset(self):
        with patch.dict(POOLS,{'main':3}):
            self.complete(self.main)
            with self.assertRaises(Refused): self.g.claim(self.fast,'worker',NOW)
        with self.assertRaises(Refused):self.g.configure_cycle('overlap',NOW,NOW+timedelta(days=5))
        with self.assertRaises(Refused):self.g.configure_cycle('test',NOW,NOW+timedelta(days=1))
        self.assertEqual(len(self.g.status()['cycles']),1)

    def test_restart_keeps_reservation_unknown_and_prevents_retry(self):
        token=self.g.claim(self.main,'worker',NOW)
        self.g.close();self.g=Governor(self.path)
        later=NOW+timedelta(seconds=121)
        self.assertTrue(self.g.acquire('replacement',later))
        self.assertEqual(self.g.status()['unknown_attempts'],1)
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'],3)
        with self.assertRaises(Refused):self.g.claim(self.main,'replacement',later)
        with self.assertRaises(Refused):self.g.finish(self.main,token,'worker',later,{'x-requests-last':'0'},[])

    def test_timeout_and_missing_header_keep_worst_case_cost(self):
        token=self.g.claim(self.main,'worker',NOW)
        self.g.unknown(token,'worker',NOW)
        other=self.g.claim(self.fast,'worker',NOW)
        self.assertEqual(self.g.finish(self.fast,other,'worker',NOW,{},[]),'unknown')
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'],6)
        self.assertEqual(self.g.status()['unknown_attempts'],2)

    def test_overcharge_and_provider_errors_pause_all_work(self):
        token=self.g.claim(self.main,'worker',NOW)
        self.assertEqual(self.g.finish(self.main,token,'worker',NOW,{'x-requests-last':'9','x-requests-remaining':'14999991'},[]),'paused')
        self.assertEqual(self.g.status()['cycles'][0]['accounted']['main'],9)
        with self.assertRaises(Refused):self.g.claim(self.fast,'worker',NOW)

    def test_split_groups_and_events_never_erase_each_other(self):
        self.complete(self.main);self.complete(self.fast)
        self.complete(self.prop);self.complete(self.propfast)
        other=plan(NOW,['basketball_nba'],[event('event2')])[2]
        self.complete(other,body=payload(other,ident='event2'))
        self.assertEqual(len(self.g.snapshots(NOW)),5)
        later=NOW+timedelta(seconds=60)
        self.complete(self.prop,later,body=[])
        remaining=self.g.snapshots(later)
        self.assertTrue(any(q['event']['id']=='event2' for q in remaining))
        self.assertFalse(any(q['market']['key']==self.prop.markets[0] and q['book']['key']==self.prop.books[0] and q['event']['id']=='event1' for q in remaining))

    def test_stale_quotes_expire_without_new_capture(self):
        self.complete(self.main)
        self.assertEqual(len(self.g.snapshots(NOW+timedelta(seconds=359))),1)
        self.assertEqual(self.g.snapshots(NOW+timedelta(seconds=360)),[])

    def test_no_replay_after_skipped_ticks_and_source_floors_persist(self):
        self.complete(self.main)
        self.assertFalse(self.g.ready(self.main,NOW+timedelta(seconds=299)))
        self.assertTrue(self.g.ready(self.main,NOW+timedelta(seconds=300)))
        self.g.close();self.g=Governor(self.path)
        self.assertFalse(self.g.ready(self.main,NOW+timedelta(seconds=299)))

    def test_closed_window_and_expired_cycle_never_reserve(self):
        closed=parse('2026-10-17T06:00:00Z')
        self.g.acquire('worker',closed)
        with self.assertRaises(Refused):self.g.claim(self.main,'worker',closed)
        after=NOW+timedelta(days=31)
        self.g.acquire('worker',after)
        with self.assertRaises(Refused):self.g.claim(self.main,'worker',after)
        self.assertEqual(self.g.status()['cycles'][0]['accounted'],{})

    def test_nearer_props_band_accelerates_without_replaying_missed_work(self):
        start=NOW+timedelta(hours=6,seconds=10)
        job=plan(NOW,['basketball_nba'],[event(start=start.isoformat())])[2]
        token=self.g.claim(job,'worker',NOW)
        self.g.finish(job,token,'worker',NOW,{'x-requests-last':str(job.cost),'x-requests-remaining':'15000000'},[])
        later=NOW+timedelta(seconds=900)
        self.g.acquire('worker',later)
        self.assertTrue(self.g.ready(job,later))
        self.g.prepare_due(job,'worker',later)
        self.assertTrue(self.g.claim(job,'worker',later))

    def test_fixture_tick_never_calls_provider_or_duplicates_members(self):
        manifest={'active_sport_keys':['basketball_nba'],'events':[event()]}
        first=tick(self.g,manifest,NOW,'worker',fixture_transport(manifest))
        second=tick(self.g,manifest,NOW,'worker',fixture_transport(manifest))
        self.assertEqual((first['executed'],second['executed']),(4,0))
        self.assertEqual(first['provider_calls'],0)
        self.assertFalse(first['feed_publication'])


if __name__=='__main__': unittest.main()
