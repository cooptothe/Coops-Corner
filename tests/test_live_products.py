from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import unittest
from api.models import EVRow, CoverRow, MiddleRow, Quote
from corner.live_tools import opportunities
from pipelines.live_odds_status import status
from tests import test_live_odds as fixtures
NOW, event, block = fixtures.NOW, fixtures.event, fixtures.block

class LiveProducts(unittest.TestCase):
    def books(self):
        return [{'key':b,'markets':[block(price=price)]} for b,price in
                [('pinnacle',1.9),('fanduel',1.9),('draftkings',2.4)]]
    def test_shared_feed_contract_has_exact_quotes_and_full_math(self):
        items=opportunities(event(self.books()))
        self.assertTrue(any(c['kind']=='ev' for c in items))
        self.assertTrue(any(c['kind']=='arbitrage' for c in items))
        for c in items:
            row=c['tool_row']
            model=EVRow if c['kind']=='ev' else CoverRow
            model.model_validate(row)
            quotes={q['id']:Quote.model_validate(q) for q in c['quotes']}
            self.assertTrue(set(row['quote_ids'])<=quotes.keys())
            if c['kind']=='ev':
                calc=row['calculation']
                self.assertGreater(len(calc['reference_books']),1)
                for ref in calc['reference_books']:
                    self.assertTrue(set(ref['quote_ids'])<=quotes.keys())
                self.assertTrue(calc['devig_comparisons'])
    def test_middle_adapter_keeps_payoff_states_and_actual_side_lines(self):
        a=block('totals');b=block('totals')
        for o in a['outcomes']:o['point']=200.5
        for o in b['outcomes']:o['point']=204.5
        items=opportunities(event([{'key':'draftkings','markets':[a]},{'key':'fanduel','markets':[b]}]))
        mids=[c for c in items if c['kind']=='middle']
        self.assertTrue(mids)
        for c in mids:
            MiddleRow.model_validate(c['tool_row'])
            self.assertTrue(c['tool_row']['calculation']['payoff']['states'])
            self.assertEqual({q['point'] for q in c['quotes']},{'200.5','204.5'})
    def test_selected_devig_is_applied_before_positive_edge_filter(self):
        for method in ('current','multiplicative','additive','power','shin','worst_case'):
            for c in opportunities(event(self.books()),method):
                if c['kind']=='ev':
                    calc=c['tool_row']['calculation']
                    self.assertGreater(float(calc['conditional_ev_ratio_on_capital']),0)
                    self.assertEqual(calc['devig_method'],'proportional_reputation_weighted_consensus' if method=='current' else method)

class ProductRoutes(unittest.TestCase):
    client=fixtures.LiveRoutes.client
    def test_devig_query_is_bounded_and_owner_only(self):
        self.assertEqual(self.client({'username':'wonya'}).get('/api/v1/live-stoppages?devig_method=bad').status_code,422)
        self.assertEqual(self.client({'username':'other'}).get('/api/v1/live-stoppages?devig_method=power').status_code,403)
        self.assertEqual(self.client({'username':'wonya'}).get('/api/v1/live-stoppages?devig_method=power').json()['devig_method'],'power')

class ProductCapture(unittest.TestCase):
    setUp=fixtures.LiveData.setUp
    tearDown=fixtures.LiveData.tearDown
    publish=fixtures.LiveData.publish
    def test_read_only_diagnostic_reports_real_capture_age(self):
        self.publish('standard',[event([{'key':'draftkings','markets':[block()]}])])
        with patch('corner.live_odds.config',return_value={}):
            result=status(self.path,NOW)
        self.assertEqual(result['fresh_capture_groups'],1)
        self.assertEqual(result['active_markets'],1)
        self.assertEqual(result['provider_calls_by_check'],0)
        self.assertEqual(status(self.path,NOW+timedelta(seconds=91))['fresh_capture_groups'],0)
