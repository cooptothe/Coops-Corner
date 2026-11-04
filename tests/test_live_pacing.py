from datetime import timedelta
import unittest
from unittest.mock import patch
from corner.live_pacing import plan,FLOORS
from corner.collection_policy import Job,STANDARD,EXCHANGE,interval
from tests import test_collection_live as fixture

NOW=fixture.NOW
def event(sport,start):return {'id':sport+str(start),'sport_key':sport,'commence_time':start.isoformat()}
def pacing(events,**kwargs):
    inputs=dict(spent_month=0,spent_today=0,monthly_cap=500000,daily_cap=20000,available_main=7900000)
    inputs.update(kwargs)
    return plan(NOW,NOW+timedelta(days=30),{'events':events},**inputs)

class PacingTests(unittest.TestCase):
    def test_quiet_slate_reaches_provider_floors_without_raising_caps(self):
        result=pacing([event('basketball_nba',NOW)])
        self.assertEqual(result['interval_seconds'],FLOORS)
        self.assertEqual(result['monthly_cap'],500000)
        self.assertEqual(result['daily_cap'],20000)

    def test_busy_slate_is_paced_across_the_budget_and_both_groups(self):
        result=pacing([event('tennis_atp_'+str(i),NOW) for i in range(20)])
        intervals=result['interval_seconds']
        self.assertGreaterEqual(intervals['standard'],40)
        self.assertGreaterEqual(intervals['exchange'],10)
        hours=result['forecast_league_hours_remaining']
        demand=hours*3600*3*sum(1/p for p in intervals.values())
        self.assertLessEqual(demand,result['remaining_today_paced']+1)
        self.assertEqual(intervals['standard'],intervals['exchange'])

    def test_overlapping_events_in_one_league_are_one_group_not_one_request_each(self):
        one=pacing([event('basketball_nba',NOW)])
        many=pacing([event('basketball_nba',NOW) for _ in range(20)])
        self.assertEqual(one,many)

    def test_caps_and_main_headroom_bound_the_available_budget(self):
        for inputs in ({'spent_month':500000},{'spent_today':20000},{'available_main':0}):
            self.assertEqual(pacing([event('basketball_nba',NOW)],**inputs)['remaining_today_paced'],0)
        self.assertLessEqual(pacing([event('basketball_nba',NOW)],available_main=300)['remaining_today_paced'],300)

    def test_main_and_prop_intervals_are_unchanged(self):
        self.assertEqual(interval('main','standard',NOW,NOW+timedelta(hours=1)),60)
        self.assertEqual(interval('props','exchange',NOW,NOW+timedelta(hours=1)),40)

class LiveLedgerPacing(unittest.TestCase):
    setUp=fixture.LiveTests.setUp
    tearDown=fixture.LiveTests.tearDown
    bind=fixture.LiveTests.bind
    acquire=fixture.LiveTests.acquire

    def test_funded_periods_are_persisted_and_cadence_still_fences_early_claims(self):
        self.bind();self.acquire()
        self.g.configure_live_pacing({'events':[event('basketball_nba',NOW)]},'worker',NOW)
        job=Job('live','basketball_nba','exchange',EXCHANGE,('h2h','spreads','totals'))
        self.assertEqual(self.g.period(job,NOW),10)
        with patch('corner.live_odds.enabled',return_value=True):
            self.g.prepare_due(job,'worker',NOW);token=self.g.claim(job,'worker',NOW)
            self.g.finish(job,token,'worker',NOW,fixture.headers(3,3),[])
            self.assertFalse(self.g.ready(job,NOW+timedelta(seconds=9)))
            self.assertTrue(self.g.ready(job,NOW+timedelta(seconds=10)))
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM live_pacing_state').fetchone()[0],1)
        self.assertEqual(self.g._binding(self.g.db,NOW)['used'],3)

    def test_zero_pacing_budget_prevents_first_request_too(self):
        self.bind();self.acquire()
        self.g._live_pacing={'remaining_today_paced':0,'interval_seconds':{'standard':86400,'exchange':86400}}
        job=Job('live','basketball_nba','standard',STANDARD,('h2h','spreads','totals'))
        self.assertFalse(self.g.ready(job,NOW))
        with self.assertRaisesRegex(ValueError,'pacing allowance'):self.g.claim(job,'worker',NOW)


if __name__=='__main__':unittest.main()


class LivePriorityTests(LiveLedgerPacing):
    def test_live_gets_first_two_slots_and_pregame_still_runs(self):
        from pipelines.collection_runner import Runner
        self.bind(); calls=[]; used=0
        sports=['basketball_nba','baseball_mlb','icehockey_nhl']
        inventory={'active_sport_keys':sports,'events':[], 'discovered_at':NOW.isoformat()}
        live=[Job('live',sport,'standard',STANDARD,('h2h','spreads','totals')) for sport in sports]
        def transport(g,job,token,owner):
            nonlocal used
            calls.append(job);used+=job.cost
            return 200,[],fixture.headers(used,job.cost),NOW
        runner=Runner(self.g,lambda:inventory,transport,clock=lambda:NOW,live_jobs=lambda *_:live,max_jobs=4)
        with patch('corner.live_odds.enabled',return_value=True):
            self.assertEqual(runner.tick()['executed'],4)
        self.assertTrue(all(job.kind=='live' for job in calls[:2]))
        self.assertTrue(any(job.kind=='main' for job in calls[2:]))

class LiveCacheTests(unittest.TestCase):
    def test_methods_share_their_own_two_second_result_and_expire(self):
        from corner import live_odds
        from pathlib import Path
        with patch.object(live_odds,'_cache',{}), patch.object(live_odds,'feed') as build, patch.object(live_odds.time,'monotonic',return_value=100) as clock:
            build.side_effect=lambda path,devig_method:{'method':devig_method}
            first=live_odds.cached_feed(Path('simulation.sqlite3'),'power')
            live_odds.cached_feed(Path('simulation.sqlite3'),'worst_case')
            self.assertIs(first,live_odds.cached_feed(Path('simulation.sqlite3'),'power'))
            self.assertEqual(build.call_count,2)
            clock.return_value=103
            self.assertIsNot(first,live_odds.cached_feed(Path('simulation.sqlite3'),'power'))
            self.assertEqual(build.call_count,3)
