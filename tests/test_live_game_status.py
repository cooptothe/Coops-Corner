from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch, Mock
from pipelines import live_game_status as status
from pipelines.live_odds_service import LiveGame

NOW = datetime(2026,10,23,21,tzinfo=timezone.utc).timestamp()
def event(name='STATUS_IN_PROGRESS',state='in',detail='4:13 - 2nd'):
    return {'id':'123','date':'2026-10-23T20:00:00Z','competitions':[{'status':{'type':{'name':name,'state':state,'shortDetail':detail}},'competitors':[
        {'homeAway':'home','team':{'displayName':'Milwaukee Bucks'}},
        {'homeAway':'away','team':{'displayName':'Chicago Bulls'}}]}]}

class GameStatus(unittest.TestCase):
    def test_breaks_are_explicit_and_independent_of_book_prices(self):
        for name in ('STATUS_HALFTIME','STATUS_END_PERIOD','STATUS_INTERMISSION','STATUS_TIMEOUT','STATUS_DELAYED','STATUS_SUSPENDED'):
            item=status.classify(event(name),NOW,NOW)
            self.assertEqual(item['game_status'],'paused',name)
            self.assertTrue(item['game_stoppage_confirmed'])
        self.assertEqual(status.classify(event(),NOW,NOW)['game_status'],'in_play')
        self.assertEqual(status.classify(event('STATUS_FINAL','post'),NOW,NOW)['game_status'],'finished')
        self.assertEqual(status.classify(event('STATUS_SCHEDULED','pre'),NOW,NOW)['game_status'],'not_started')
    def test_expired_status_never_claims_a_stoppage(self):
        item=status.classify(event('STATUS_HALFTIME'),NOW,NOW-31)
        self.assertEqual(item['game_status'],'unknown')
        self.assertFalse(item['game_stoppage_confirmed'])
    def test_timeout_requires_latest_play_with_recent_wallclock(self):
        play={'type':{'text':'Full Timeout'},'wallclock':datetime.fromtimestamp(NOW-10,timezone.utc).isoformat()}
        self.assertEqual(status.classify(event(),NOW,NOW,[play])['game_status'],'paused')
        self.assertEqual(status.classify(event(),NOW,NOW,[play,{'type':{'text':'Jump Shot'}}])['game_status'],'in_play')
        self.assertEqual(status.classify(event(),NOW+40,NOW+40,[play])['game_status'],'in_play')
        self.assertEqual(status.classify(event(),NOW,NOW,[{'type':{'text':'Timeout'}}])['game_status'],'in_play')

class StatusCache(unittest.TestCase):
    def setUp(self):
        status._cache.clear();status._pending.clear()
        self.pool=patch.object(status,'_pool',Mock()).start()
        self.addCleanup(patch.stopall)
    def test_reads_are_nonblocking_and_shared_and_bounded(self):
        for _ in range(20):self.assertIsNone(status.cached('same',NOW))
        self.assertEqual(status._pool.submit.call_count,1)
        for i in range(100):status.cached(str(i),NOW)
        self.assertEqual(len(status._pending),32)
    def test_failure_does_not_reuse_old_status(self):
        status._cache['x']=(NOW-31,event('STATUS_HALFTIME'))
        self.assertIsNone(status.cached('x',NOW))
        with patch.object(status,'_fetch',side_effect=RuntimeError('upstream unavailable')),patch.object(status.time,'time',return_value=NOW):status._load('x')
        self.assertIsNone(status.cached('x',NOW))
    def payload(self):
        return {'events':[{'id':'odds-1','sport_key':'basketball_nba','away_team':'Chicago Bulls','home_team':'Milwaukee Bucks','commence_time':'2026-10-23T20:00:00Z','status':'no_active_lines','opportunities':[{'x':1}],'tool_rows':[],'quotes':[]}]}
    def test_matched_game_uses_espn_not_missing_prices_and_preserves_original(self):
        payload=self.payload();original=deepcopy(payload)
        with patch.object(status,'cached',return_value=(NOW,{'events':[event()]})),patch.object(status.time,'time',return_value=NOW):
            enriched=status.enrich(payload)
        self.assertEqual(enriched['events'][0]['game_status'],'in_play')
        self.assertFalse(enriched['events'][0]['game_stoppage_confirmed'])
        self.assertEqual(payload,original)
    def test_single_wrong_date_or_other_matchup_is_not_joined(self):
        wrong=event('STATUS_HALFTIME');wrong['date']='2026-10-20T20:00:00Z'
        with patch.object(status,'cached',return_value=(NOW,{'events':[wrong]})),patch.object(status.time,'time',return_value=NOW):
            self.assertEqual(status.enrich(self.payload())['events'][0]['game_status'],'unknown')
    def test_halftime_still_has_odds_and_final_clears_opportunities(self):
        for name,state in [('STATUS_HALFTIME','in'),('STATUS_FINAL','post')]:
            with patch.object(status,'cached',return_value=(NOW,{'events':[event(name,state)]})),patch.object(status.time,'time',return_value=NOW):
                item=status.enrich(self.payload())['events'][0]
            self.assertEqual(bool(item['opportunities']),name=='STATUS_HALFTIME')
