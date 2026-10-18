"""Recorded alternate capture -> EV, arbs, middles and promo; no network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from corner import prop_markets as pm
from corner.prop_tools import merge_props
from corner.manual_markets import markets_for_event
from api.catalog import FixtureCatalog
from api.database import build_raw
from api.models import PromoRequest
from pipelines import props_ingestion as ing

NOW=datetime.now(timezone.utc)

def data():
    quotes=[]
    for book, sides in [('pinnacle', (2,2)),('fanduel',(2,2)),('draftkings',(3,1.2))]:
        for line in ('1.5','2.5'):
            quotes.extend(dict(player='Player One',book=book,side=i,point=line,price=str(price)) for i,price in enumerate(sides))
    return {'events':{'event-1':dict(sport_key='basketball_nba',home_team='Home',away_team='Away',
        commence_time=(NOW+timedelta(hours=2)).isoformat(),markets={
        'player_threes_alternate':dict(captured_at=NOW.isoformat(),quotes=quotes)})}}

def catalog(payload):
    now=datetime.now(timezone.utc)
    return FixtureCatalog(raw=merge_props(build_raw([],[],now=now),now=now,data=payload))

class AlternateProps(unittest.TestCase):
    def test_every_documented_cash_alternate_is_selectable(self):
        for family,bases in pm.ALTERNATE_BASES.items():
            sport={'football':'americanfootball_nfl','basketball':'basketball_nba','baseball':'baseball_mlb','hockey':'icehockey_nhl','soccer':'soccer_epl'}[family]
            for base in bases:
                self.assertIsNotNone(pm.market_meta(sport,base+'_alternate'))
        self.assertIsNone(pm.market_meta('basketball_nba','player_points_q1_alternate'))
        self.assertIsNone(pm.market_meta('soccer_epl','player_goal_scorer_anytime_alternate'))

    def test_manual_capture_to_multiline_ev_and_tools(self):
        original=data();event=original['events']['event-1']
        event['commence_time'] = '2030-01-01T20:00:00+00:00'
        payload=dict(id='event-1',sport_key=event['sport_key'],home_team='Home',away_team='Away',commence_time=event['commence_time'],bookmakers=[])
        for book in ('pinnacle','fanduel','draftkings'):
            outcomes=[dict(name=('Over','Under')[q['side']],description=q['player'],point=float(q['point']),price=float(q['price'])) for q in event['markets']['player_threes_alternate']['quotes'] if q['book']==book]
            payload['bookmakers'].append(dict(key=book,markets=[dict(key='player_threes_alternate',outcomes=outcomes)]))
        with tempfile.TemporaryDirectory() as folder, patch.object(ing,'STORE',Path(folder)/'latest.json'),patch.object(ing,'ODDS_API_KEY','fixture'),patch.object(ing,'plan',return_value=([payload],{'x-requests-remaining':'100'})),patch.object(ing,'fetch',return_value=(200,json.dumps(payload).encode(),{'x-requests-last':'2','x-requests-remaining':'98'})) as fetch:
            result=ing.capture('basketball_nba',['player_threes_alternate'],1,now=datetime(2030,1,1,18,tzinfo=timezone.utc))
            self.assertEqual(result['events'],1)
            self.assertEqual(fetch.call_args.args[2]['markets'],'player_threes_alternate')
            saved=json.loads(ing.STORE.read_text())
            bets=pm.build_bets(saved['events'],fallback_margin='0.10',include_dfs=True)
            self.assertEqual({b['point'] for b in bets if b['book']=='draftkings'},{'1.5','2.5'})
            c=catalog(saved)
            self.assertTrue(any(r.kind=='arbitrage' for r in c.rows))
            self.assertTrue(any(r.kind=='middle' for r in c.rows))
            self.assertFalse(any(r.kind=='positive_ev' for r in c.rows)) # dedicated props pricing unchanged
            qs=list(c.quotes)
            over=next(q for q in qs if q.sportsbook_id=='draftkings' and q.side=='over')
            under=next(q for q in qs if q.contract_id==over.contract_id and q.sportsbook_id=='pinnacle' and q.side=='under')
            command=PromoRequest(snapshot_id=c.snapshot_id,contract_id=over.contract_id,promo_quote_id=over.id,hedge_quote_id=under.id,hedge_type='opposite_back',terms=dict(terms_id='test',kind='bonus_stake_not_returned',face_value='100',eligible_stake_cap='100',minimum_decimal_odds='1.5',loss_refund_cap='0',eligibility_evidence_id='test',bonus_restored_on_void=True))
            self.assertIsNotNone(c.promo(command))
            from api.app import create_app
            from fastapi.testclient import TestClient
            with TestClient(create_app(data_mode='database',catalog=c,session_check=lambda t:t=='member'),base_url='http://127.0.0.1') as client:
                self.assertEqual(client.get('/api/v1/quotes').status_code,401)
                client.cookies.set('corner_session','member')
                response=client.get('/api/v1/quotes')
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(all(q['market_key']=='player_threes_alternate' for q in response.json()['data']['items']))
                response=client.post('/api/v1/calculators/promo',json=command.model_dump())
                self.assertEqual(response.status_code,200,response.text)

    def test_player_event_expiry_and_dfs_isolation(self):
        original=data();payload=deepcopy(original)
        qs=payload['events']['event-1']['markets']['player_threes_alternate']['quotes']
        for q in qs:
            if q['book']=='pinnacle':q['player']='Another Player'
            if q['book']=='fanduel':q['book']='prizepicks'
        c=catalog(payload)
        self.assertFalse(any(r.kind=='arbitrage' for r in c.rows))
        self.assertFalse(any(q.sportsbook_id=='prizepicks' for q in c.quotes))
        expired=deepcopy(original)
        expired['events']['event-1']['markets']['player_threes_alternate']['captured_at']=(NOW-timedelta(hours=3)).isoformat()
        self.assertFalse(catalog(expired).quotes)
        self.assertEqual(original,data())

    def test_alternate_history_and_projection_use_base_statistic(self):
        from pipelines.trends_service import stat_specs
        from corner.prop_projection import plan
        self.assertEqual(stat_specs('basketball_nba','player_threes_alternate'),stat_specs('basketball_nba','player_threes'))
        self.assertEqual(plan('americanfootball_nfl','player_pass_yds_alternate'),plan('americanfootball_nfl','player_pass_yds'))

    def test_scheduler_scope_is_not_expanded_by_manual_catalog(self):
        from corner.collection_policy import FAMILIES
        self.assertFalse(any(m.key.endswith('_alternate') for values in FAMILIES.values() for m in values))

    def test_standard_cash_references_price_exact_alternate_contract_only(self):
        payload=data();e=payload['events']['event-1'];all_quotes=e['markets']['player_threes_alternate']['quotes']
        e['markets']['player_threes_alternate']['quotes']=[q for q in all_quotes if q['book']=='draftkings']
        e['markets']['player_threes']=dict(captured_at=NOW.isoformat(),quotes=[q for q in all_quotes if q['book']!='draftkings'])
        rows=pm.build_bets(payload['events'],fallback_margin='0.10',include_dfs=True)
        targets=[r for r in rows if r['book']=='draftkings']
        self.assertEqual({r['market_key'] for r in targets},{'player_threes_alternate'})
        self.assertEqual({r['point'] for r in targets},{'1.5','2.5'})
        for q in e['markets']['player_threes']['quotes']:q['point']='9.5'
        self.assertFalse(any(r['book']=='draftkings' for r in pm.build_bets(payload['events'],fallback_margin='0.10',include_dfs=True)))

    def test_one_sided_cash_quotes_can_hedge_without_full_book_pairs(self):
        payload=data()
        stored=payload['events']['event-1']['markets']['player_threes_alternate']
        stored['quotes']=[q for q in stored['quotes'] if q['book']=='draftkings' and q['side']==0 or q['book']=='pinnacle' and q['side']==1]
        c=catalog(payload)
        self.assertTrue(any(r.kind=='arbitrage' for r in c.rows))
        self.assertTrue(any(r.kind=='middle' for r in c.rows))

    def test_standard_and_alternate_exact_line_deduplicate_and_share_middles(self):
        payload=data();e=payload['events']['event-1'];original=deepcopy(e['markets']['player_threes_alternate'])
        e['markets']['player_threes']=original
        c=catalog(payload)
        self.assertEqual(len(c.quotes),12)
        self.assertTrue(any(r.kind=='arbitrage' for r in c.rows))

    def test_best_middle_pairs_match_exhaustive_window_ranking(self):
        from corner.prop_tools import best_middles
        from corner.featured_middles import LineBet, find_middles
        bets=[]
        for side in ('over','under'):
            for line in ('1.5','2.5','3.5'):
                for book,odds in [('a','1.9'),('b','2.1'),('c','2.3')]:
                    bets.append(LineBet(f'{side}:{line}:{book}',book,'same-player-stat','totals',side,Decimal(line),Decimal(odds),Decimal(100),Decimal('.02')))
        full=find_middles(bets,refund_possible=True)
        best=best_middles(bets,True)
        windows={r.double_win_ranges for r in full}
        self.assertEqual({r.double_win_ranges for r in best},windows)
        for result in best:
            same=[r for r in full if r.double_win_ranges==result.double_win_ranges]
            self.assertEqual(result.payoff.minimum_modeled_profit,max(r.payoff.minimum_modeled_profit for r in same))
            self.assertEqual(result.payoff.maximum_modeled_profit,max(r.payoff.maximum_modeled_profit for r in same if r.payoff.minimum_modeled_profit==result.payoff.minimum_modeled_profit))

    def test_manual_main_capture_handles_all_events_and_separate_charge_limits(self):
        from pipelines import odds_ingestion as board
        events=[dict(id=f'e{i}',sport_key='basketball_nba',home_team='H',away_team='A',commence_time=(NOW+timedelta(hours=2)).isoformat(),bookmakers=[]) for i in range(5)]
        def fetch(session,url,params):
            remaining={'x-requests-remaining':'1000','x-requests-last':'0'}
            if url==board.BASE+'/':return 200,json.dumps([dict(key='basketball_nba',active=True)]).encode(),remaining
            if '/events/' in url:
                event_id=url.split('/events/')[1].split('/')[0]
                return 200,json.dumps(next(e for e in events if e['id']==event_id)).encode(),{**remaining,'x-requests-last':str(len(params['markets'].split(','))*board.BOOKMAKER_REGIONS)}
            return 200,json.dumps(events).encode(),{**remaining,'x-requests-last':'6'}
        with tempfile.TemporaryDirectory() as folder,patch.object(board,'ODDS_API_KEY','fixture'),patch.object(board,'fetch',side_effect=fetch) as request:
            destination=Path(folder)/'capture'
            board.capture(destination,sport='basketball_nba')
            self.assertEqual(len(list((destination/'additional').glob('*/manifest.json'))),5)
            self.assertEqual(request.call_count,7)
            self.assertEqual(json.loads((destination/'manifest.json').read_text())['planned_credits'],6+sum(len(markets_for_event(board.ADDITIONAL_MARKETS,e['commence_time'],NOW))*board.BOOKMAKER_REGIONS for e in events))

if __name__=='__main__':unittest.main()
