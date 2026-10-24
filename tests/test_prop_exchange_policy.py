import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from corner.collection_policy import ALL_BOOKS, EXCHANGE, PROP_EXCHANGE, plan, Job
from corner.credit_governor import Governor
from corner.reference_weights import reference_weight, normalized_reference_weights
from corner.prop_markets import build_bets
from pipelines.collection_book_coverage import report
from pipelines.collection_provider import Provider
from pipelines.props_ingestion import BOOKS
from tests.test_one_sided_props import event as prop_event
from tests.test_collection_adapters import NOW, event, Session, Response


class PropsExchangePolicy(unittest.TestCase):
    def test_props_omit_betfair_but_keep_every_other_exchange_and_same_cost(self):
        expected=set(EXCHANGE)-{'betfair_ex_uk'}
        self.assertEqual(set(PROP_EXCHANGE),expected)
        self.assertEqual(set(BOOKS.split(',')) & set(EXCHANGE),expected)
        jobs=plan(NOW,['basketball_nba'],[event()],additional=True)
        for job in jobs:
            job.validate()
            if job.group=='exchange':
                self.assertEqual(set(job.books),expected if job.kind=='props' else set(EXCHANGE))
                self.assertEqual(job.cost,len(job.markets))
        old=next(j for j in jobs if j.kind=='props' and j.group=='exchange')
        with self.assertRaises(ValueError):
            Job(old.kind,old.sport,old.group,EXCHANGE,old.markets,old.event_id,old.starts_at).validate()

    def test_real_transport_parameters_request_all_remaining_props_exchanges(self):
        with tempfile.TemporaryDirectory() as folder:
            g=Governor(Path(folder)/'state.sqlite3')
            try:
                g.configure_cycle('test',NOW-timedelta(days=1),NOW+timedelta(days=5));g.acquire('worker',NOW)
                job=next(j for j in plan(NOW,['basketball_nba'],[event()]) if j.kind=='props' and j.group=='exchange')
                token=g.claim(job,'worker',NOW)
                session=Session([Response({},charge='0')])
                provider=Provider(key='synthetic',enabled=True,budgeted_pregame=True,session=session,clock=lambda:NOW)
                provider.odds(g,job,token,'worker')
                params=session.calls[0][1]['params']
                self.assertEqual(set(params['bookmakers'].split(',')),set(PROP_EXCHANGE))
                self.assertIn('polymarket_us',params['bookmakers'])
                self.assertEqual(params['includeBetLimits'],'true')
            finally:g.close()

    def test_retained_betfair_does_not_satisfy_props_quorum_or_change_fair_price(self):
        books={'fanduel':{0:2,1:2},'pinnacle':{0:2,1:2},'draftkings':{0:3,1:2}}
        baseline=build_bets({'e':prop_event(books)})
        with patch.dict('os.environ',{'CORNER_BETFAIR_COMMISSION':'.02'}):
            actual=build_bets({'e':prop_event({**books,'betfair_ex_uk':{0:20,1:1.1}})})
        self.assertEqual(baseline,actual)
        self.assertTrue(all('betfair_ex_uk' not in b['sharps'] for b in actual))
        self.assertEqual([],build_bets({'e':prop_event({'pinnacle':{0:2,1:2},'draftkings':{0:3,1:2},'betfair_ex_uk':{0:2,1:2}})}))
        for book in ('betfair_ex_uk','betfair_ex_eu','betfair_ex_au'):
            self.assertEqual(reference_weight(book,'basketball_nba',player_props=True),D(0))
        self.assertEqual(normalized_reference_weights(['betfair_ex_uk','pinnacle'],'basketball_nba',player_props=True),{'pinnacle':D(1)})
        self.assertGreater(reference_weight('betfair_ex_uk','soccer_epl'),0)

    def test_readonly_report_distinguishes_fresh_absent_and_excluded_books(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.sqlite3';g=Governor(path)
            now=datetime(2026,10,24,18,tzinfo=timezone.utc);stamp=now.timestamp()
            g.configure_cycle('quota-2026-10',datetime(2026,10,1,tzinfo=timezone.utc),datetime(2026,11,1,tzinfo=timezone.utc))
            payload=json.dumps({'market':{'outcomes':[{'price':2,'name':'Over'}]}})
            g.db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',('props','basketball_nba','e','polymarket_us','player_points',stamp+3600,stamp-10,stamp-5,stamp+100,payload))
            g.close()
            before=path.read_bytes()
            data=report(path,now=now,dashboard_used=459541)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(data['provider_calls'],0)
            self.assertEqual(data['budget']['provider_remaining_known'],14540459)
            self.assertEqual(data['budget']['usable_above_reserve'],13040459)
            books={b['book']:b['scopes'] for b in data['books']}
            self.assertEqual(books['polymarket_us']['props']['status'],'fresh_returned_quotes')
            self.assertEqual(books['betfair_ex_uk']['props']['status'],'excluded_from_props')
            self.assertTrue(books['betfair_ex_uk']['main']['requested'])
            self.assertEqual(books['novig']['props']['status'],'no_quotes_in_current_retained_store')
            self.assertEqual(set(data['requested_exchange_keys']['main']),set(EXCHANGE))
            self.assertEqual(set(data['requested_exchange_keys']['props']),set(PROP_EXCHANGE))
