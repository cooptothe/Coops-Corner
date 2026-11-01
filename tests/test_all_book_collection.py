import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from corner.collection_policy import (ALL_BOOKS, STANDARD, PROP_STANDARD, PROP_EXCHANGE, EXCHANGE,
    LEGACY_STANDARD, Job, plan, interval, POOLS, TOTAL, PROTECTED, ALL_BOOKS_PROFILE, CADENCE_VERSION)
from corner.credit_governor import Governor, Refused
from pipelines.collection_provider import Provider
from pipelines.collection_publication import MainPublisher
from pipelines.odds_ingestion import PARAMS
from pipelines.props_ingestion import BOOKS
from tests.test_collection_adapters import NOW, event, Session, Response
from tests.test_collection_live import ActivationTests


class AllBookCollection(unittest.TestCase):
    def test_exact_sixteen_books_in_every_scope_and_manual_requests(self):
        expected={'betfair_ex_uk','betmgm','betonlineag','betopenly','betrivers','bovada',
            'williamhill_us','draftkings','fanatics','fanduel','kalshi','novig','pinnacle',
            'polymarket_us','prophetx','espnbet'}
        self.assertEqual(set(ALL_BOOKS),expected)
        self.assertEqual(len(ALL_BOOKS),16)
        self.assertEqual(set(PARAMS['bookmakers'].split(',')),expected)
        self.assertEqual(set(BOOKS.split(',')),expected-{'betfair_ex_uk'})
        jobs=plan(NOW,['basketball_nba'],[event()],additional=True)
        for kind in ('main','additional','props'):
            scopes=[j for j in jobs if j.kind==kind]
            self.assertEqual(len(scopes),2)
            self.assertEqual({b for j in scopes for b in j.books},expected-{'betfair_ex_uk'} if kind=='props' else expected)
            self.assertTrue(all(j.cost==len(j.markets) for j in scopes))

    def test_all_countdown_boundaries_and_no_subminute_exchange_polling(self):
        gates={'main': [(7200, 60), (10800, 90), (14400, 120), (21600, 180), (28800, 300), (43200, 600), (86400, 900)], 'props': [(10800, 60), (14400, 90), (21600, 120), (28800, 180), (43200, 240), (86400, 300)], 'additional': [(600, 60), (1200, 90), (1800, 120), (2700, 180), (3600, 240), (5400, 480), (7200, 600)]}
        for kind,bands in gates.items():
            lower=1
            for upper,seconds in bands:
                for remaining in (lower,upper):
                    for group in ('standard','exchange'):
                        self.assertEqual(interval(kind,group,NOW,NOW+timedelta(seconds=remaining)),seconds)
                        self.assertGreaterEqual(seconds,60)
                lower=upper+1

    def test_budgeted_exchange_dispatch_requires_approval_and_keeps_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            g=Governor(Path(folder)/'collection-live.sqlite3')
            try:
                g.configure_cycle('test',NOW-timedelta(days=1),NOW+timedelta(days=20));g.acquire('worker',NOW)
                job=next(j for j in plan(NOW,['basketball_nba'],[event()]) if j.kind=='main' and j.group=='exchange')
                token=g.claim(job,'worker',NOW)
                session=Session([Response([],charge='3')])
                blocked=Provider(key='test-secret',enabled=True,session=session,clock=lambda:NOW)
                with self.assertRaises(Refused):blocked.odds(g,job,token,'worker')
                self.assertFalse(session.calls)
                provider=Provider(key='test-secret',enabled=True,budgeted_pregame=True,session=session,clock=lambda:NOW)
                result=provider.odds(g,job,token,'worker')
                self.assertEqual(result[0],200)
                self.assertEqual(session.calls[0][1]['params']['includeBetLimits'],'true')
                self.assertEqual(session.calls[0][1]['params']['bookmakers'],','.join(EXCHANGE))
                self.assertEqual(g.db.execute('SELECT reserved FROM attempts WHERE token=?',(token,)).fetchone()[0],3)
                with self.assertRaises(Refused):provider.odds(g,job,token,'worker')
                self.assertEqual(len(session.calls),1)
            finally:g.close()

    def test_old_nine_book_capture_replays_with_its_original_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy=Job('main','basketball_nba','standard',LEGACY_STANDARD,('h2h','spreads','totals'))
            with self.assertRaises(ValueError):legacy.validate()
            manifests=[]
            pub=MainPublisher(folder,lambda:None,lambda path,**kwargs:manifests.append(json.loads((path/'manifest.json').read_text())))
            record={'job':asdict(legacy),'events':[],'captured_at':NOW.isoformat()}
            pub('a'*48,record);pub('a'*48,record)
            self.assertEqual(manifests[0],manifests[1])
            self.assertEqual(manifests[0]['parameters']['bookmakers'],','.join(LEGACY_STANDARD))

    def test_saved_forecast_preserves_pool_caps_and_reserve(self):
        forecast=json.loads((Path(__file__).resolve().parents[1]/'corner/ALL_BOOKS_FORECAST.json').read_text())
        self.assertLessEqual(forecast['props_total'],POOLS['props'])
        self.assertEqual(forecast['planning_total'],forecast['main_live_additional_shared_pool_cap']+forecast['props_total']+600000)
        self.assertLessEqual(forecast['planning_total'],TOTAL-PROTECTED)
        self.assertEqual(sum(POOLS.values()),TOTAL-PROTECTED)
        self.assertEqual(forecast['live_subcap_within_main'],500000)
        self.assertEqual(forecast['guaranteed_credit_savings_from_betfair_props_removal'],0)
        self.assertEqual(forecast['requested_props_books'],15)


class AllBookActivation(ActivationTests):
    def setUp(self):
        super().setUp()
        self.approval.update(profile=ALL_BOOKS_PROFILE,requested_books=list(ALL_BOOKS),cadence_version=CADENCE_VERSION)
        self.approval['evidence'].pop('exchange_classification_verified')
        self.approval['evidence'].pop('full_slate_throughput_measured')

    def test_scope_or_cadence_drift_refuses(self):
        self.approval['requested_books'].pop()
        with self.assertRaises(Refused):self.check()
        self.approval['requested_books']=list(ALL_BOOKS)
        self.approval['cadence_version']='unreviewed'
        with self.assertRaises(Refused):self.check()
