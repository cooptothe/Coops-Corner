"""CLV coverage, exact matching, immutable closing evidence and correlated parlays."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from corner import clv
from pipelines import tracker_clv as worker

NOW = datetime(2026, 10, 17, 20, tzinfo=timezone.utc)
START = NOW-timedelta(hours=1)
GAME = '11111111-1111-4111-8111-111111111111'

def row(side, point=None, book='pinnacle'):
    return dict(book=book, side=side, point=point, decimal_odds='1.9')

def bet(**extra):
    return dict(id='a', odds='2.1', starts_at=START.isoformat(), ref=dict(game_id=GAME, market_key='h2h', side='home'), clv=None, **extra)

class Store:
    def __init__(self, bets): self.bets=bets
    def state(self): return {'bets':self.bets}
    def set_clv(self, key, value): next(b for b in self.bets if b['id']==key)['clv']=value
    def bet(self, key): return next(b for b in self.bets if b['id']==key)

class Coverage(unittest.TestCase):
    def test_new_markets_devig_complete_exact_pairs(self):
        for market, sides, point in [('alternate_spreads', ('home','away'), -3.5), ('alternate_totals', ('over','under'), 2.5), ('btts', ('yes','no'), None), ('draw_no_bet', ('home','away'), None), ('team_totals', ('over','under'), 1.5), ('prop_pair', ('yes','no'), None)]:
            second=-point if market=='alternate_spreads' else point
            out=clv.measure(dict(market_key=market, side=sides[0], point=point), '2.1', [row(sides[0],point),row(sides[1],second)], {'pinnacle'}, at='t')
            self.assertEqual(out['pct'],'0.05',market)
    def test_global_three_way_shape_rejects_partial_two_way_book(self):
        rows=[row('home'),row('away'),row('draw',book='other')]
        self.assertIsNone(clv.measure(dict(market_key='h2h',side='home'),'2',rows,{'pinnacle','other'},at='t')['pct'])
    def test_every_manual_bet_has_honest_status(self):
        value=bet();value['ref']={};value['starts_at']=None
        store=Store([value]);worker.measure_pending(store,now=NOW)
        self.assertEqual(value['clv']['status'],'unavailable')
    def test_parlay_records_each_leg_without_independence_assumption(self):
        a=bet();a.update(key='leg1',selection='Home')
        b=bet();b.update(key='leg2',selection='Other home')
        value=bet(legs=[a,b]);store=Store([value])
        worker.measure_pending(store,fetch=lambda *args:(START,[row('home'),row('away')]),now=NOW)
        self.assertIsNone(value['clv']['pct'])
        self.assertEqual([l['pct'] for l in value['clv']['legs']],['0.05','0.05'])
        self.assertIn('combined',value['clv']['reason'])
    def test_props_only_exact_player_and_line_close(self):
        value=bet();value['ref'].update(market_key='prop',prop_market='player_points',player='A',side='over',point=20.5)
        with patch.object(worker,'fetch_props_close',return_value=(START,[row('over',20.5),row('under',20.5)])):
            worker.measure_pending(Store([value]),now=NOW)
        self.assertEqual(value['clv']['pct'],'0.05')
    def test_local_scope_withdrawal_does_not_reuse_old_price(self):
        from pipelines import props_ingestion as props
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'latest.json'
            data={'events':{'event':{'commence_time':START.isoformat(),'sport_key':'basketball_nba','markets':{'player_points':{'captured_at':(START-timedelta(seconds=90)).isoformat(),'quotes':[dict(book='pinnacle',player='A',side=0,point='20.5',price='1.9',updated_at=(START-timedelta(seconds=90)).isoformat())]}}}}}
            worker.retain_local_props(data,path);path.write_text(json.dumps(data),encoding='utf-8')
            data['events']['event']['markets']['player_points'].update(captured_at=(START-timedelta(seconds=30)).isoformat(),quotes=[])
            worker.retain_local_props(data,path);path.write_text(json.dumps(data),encoding='utf-8')
            with patch.object(props,'STORE',path),patch('corner.collection_readers.store_path',return_value=None):
                _,rows=worker.fetch_props_close(dict(game_id='event',prop_market='player_points',player='A'),START.isoformat())
            self.assertEqual(rows,[])
    def test_failed_fetch_is_retryable_and_does_not_store_no_close(self):
        value=bet()
        with self.assertRaises(RuntimeError): worker.measure_pending(Store([value]),fetch=lambda *a:(_ for _ in ()).throw(RuntimeError()),now=NOW)
        self.assertIsNone(value['clv'])
    def test_scheduler_retains_withdrawals_and_restart_history(self):
        from corner.credit_governor import Governor
        from corner.collection_policy import Job
        from pipelines.collection_publication import read_props
        captured=START-timedelta(seconds=90)
        job=Job('props','basketball_nba','standard',('pinnacle',),('player_points',),'event',START.isoformat())
        event=dict(id='event',sport_key='basketball_nba',commence_time=START.isoformat(),home_team='H',away_team='A',bookmakers=[dict(key='pinnacle',last_update=captured.isoformat(),markets=[dict(key='player_points',last_update=captured.isoformat(),outcomes=[dict(name='Over',description='A',point=20.5,price=1.9),dict(name='Under',description='A',point=20.5,price=1.9)])])])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'live.sqlite3'
            g=Governor(path)
            with g.transaction() as db: g._publish(db,job,[event],captured)
            self.assertEqual(g.db.execute('SELECT count(*) FROM clv_scopes').fetchone()[0],1)
            event['bookmakers']=[]
            with g.transaction() as db: g._publish(db,job,[event],START-timedelta(seconds=30))
            g.close()
            with patch('corner.collection_readers.store_path',return_value=path):
                _,rows=worker.fetch_props_close(dict(game_id='event',prop_market='player_points',player='A'),START.isoformat())
            self.assertEqual(rows,[])
            self.assertEqual(read_props(path,now=NOW),{'events':{}})

    def test_late_live_capture_not_accepted_as_close(self):
        self.assertIn('ob.observed_at <= e.scheduled_start',worker.CLOSE_SQL)
        self.assertIn('q.provider_updated_at <= e.scheduled_start',worker.CLOSE_SQL)

if __name__=='__main__': unittest.main()
