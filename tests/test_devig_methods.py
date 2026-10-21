import unittest
from decimal import Decimal as D
from unittest.mock import patch
from corner.devig_methods import distributions, pooled_distributions, comparisons
from corner.featured_ev import calculate_featured_ev
from corner.featured_tools import MatchedMarket, Offer
from corner import prop_markets as pm
from tests.test_prop_markets import EVENT


class DevigMethods(unittest.TestCase):
    def test_binary_known_values_shin_identity_and_power(self):
        methods=dict(distributions((D('1.5'),D('2.5'))))
        for actual, expected in zip(methods['multiplicative'], (D('.625'),D('.375'))):
            self.assertLess(abs(actual-expected),D('1e-26'))
        self.assertLess(abs(methods['additive'][0]-D(19)/30),D('1e-26'))
        self.assertEqual(methods['additive'],methods['shin'])
        self.assertAlmostEqual(float(methods['power'][0]),.63792,places=5)
        for pair in methods.values():
            self.assertLess(abs(sum(pair)-1),D('1e-26'))

    def test_three_way_and_invalid_additive(self):
        for name, values in distributions((D('1.4'),D('4.2'),D('9'))):
            self.assertLess(abs(sum(values)-1),D('1e-26'), name)
            self.assertTrue(all(0<=p<=1 for p in values))
        methods=dict(distributions((D('1.1'),D('1.1'),D('100'))))
        self.assertNotIn('additive',methods)
        self.assertIn('shin',methods)
        self.assertNotIn('shin',dict(distributions((D('3'),D('3')))))
        with self.assertRaises(ValueError):distributions((D('1'),D('2')))
        with self.assertRaises(ValueError):pooled_distributions(())

    def test_weighted_consensus_worst_case_and_lay_fees(self):
        populations=(((D('1.5'),D('2.5')),D('4')),((D('1.91'),D('1.91')),D('1')))
        for lay in (False,True):
            rows=comparisons(populations,1,D('2.75'),D('.02'),lay=lay)
            self.assertEqual(rows[-1]['method'],'worst_case')
            self.assertEqual(rows[-1]['ev'],min(r['ev'] for r in rows[:-1]))
        pooled=dict(pooled_distributions(populations))
        self.assertLess(abs(pooled['multiplicative'][0]-D('.6')),D('1e-26'))

    def test_main_headline_unchanged_and_target_excluded(self):
        market=MatchedMarket('game','totals',('over','under'),False)
        refs=tuple(Offer(b+s,'game','totals',s,b,D(p),D(0))
                   for b in ('fanduel','pinnacle') for s,p in [('over','1.5'),('under','2.5')])
        target=Offer('target','game','totals','under','draftkings',D('2.75'),D(0))
        result=calculate_featured_ev(market,target,refs,required_reference_books=('fanduel','pinnacle'))
        self.assertEqual(result.conditional_fair_probability,D('.375'))
        self.assertEqual(result.conditional_ev_ratio_on_capital,D('.03125'))
        self.assertEqual(len(result.devig_comparisons),5)

    def test_props_headlines_unchanged_and_missing_pair_not_invented(self):
        meta=pm.market_meta('basketball_nba','player_points')
        quotes=pm.normalize_event(EVENT,'player_points',meta)
        def bets(quotes):
            return pm.build_bets({'event':{'sport_key':'basketball_nba','home_team':'H','away_team':'A',
                'commence_time':'2030-01-01T00:00:00Z',
                'markets':{'player_points':{'captured_at':'x','quotes':quotes}}}},fallback_margin='.1')
        actual=bets(quotes)
        with patch.object(pm,'comparisons',return_value=()):
            prior=bets(quotes)
        for a,b in zip(actual,prior):
            self.assertEqual({k:v for k,v in a.items() if k!='devig_comparisons'},
                             {k:v for k,v in b.items() if k!='devig_comparisons'})
        modeled=bets([q for q in quotes if q['side']==0])
        self.assertTrue(modeled)
        self.assertTrue(all(b['devig_comparisons'] is None for b in modeled))

    def test_selected_method_qualifies_before_filtering_and_has_separate_cache(self):
        from api.database import build_raw
        from api.catalog import FixtureCatalog
        from api.app import create_app
        from fastapi.testclient import TestClient
        from tests.test_database_catalog import q, PEOPLE, NOW
        rows=[q(book,'moneyline',side,price)
              for book,prices in [('draftkings',('1.58','2.75')),('fanduel',('1.5','2.5')),('betmgm',('1.5','2.5'))]
              for side,price in zip(('home','away'),prices)]
        catalog=FixtureCatalog(raw=build_raw(rows,PEOPLE,now=NOW))
        def dk_home(rows):
            return [r for r in rows if catalog.quote_map[r.calculation.target_quote_id].sportsbook_id=='draftkings'
                    and catalog.quote_map[r.calculation.target_quote_id].side=='home']
        self.assertFalse(dk_home(catalog.ev_rows('current')))
        self.assertTrue(dk_home(catalog.ev_rows('power')))
        self.assertFalse(dk_home(catalog.ev_rows('multiplicative')))
        self.assertIs(catalog.ev_rows('power'),catalog.ev_rows('power'))
        with TestClient(create_app(data_mode='database',catalog=catalog),base_url='http://127.0.0.1') as client:
            power=client.get('/api/v1/tools/positive_ev',params={'devig_method':'power','limit':1000})
            self.assertEqual(power.status_code,200,power.text)
            items=power.json()['data']['items']
            self.assertTrue(items)
            self.assertTrue(all(r['calculation']['devig_method']=='power' for r in items))
            self.assertEqual(client.get('/api/v1/tools/positive_ev?devig_method=invalid').status_code,422)
            self.assertEqual(client.get('/api/v1/tools/middle?devig_method=power').status_code,422)

    def test_selected_reference_probabilities_match_pooled_headline(self):
        market=MatchedMarket('game','h2h',('away','home'),False)
        refs=tuple(Offer(b+s,'game','h2h',s,b,D(p),D(0)) for b in ('fanduel','pinnacle')
                   for s,p in [('away','2.5'),('home','1.5')])
        target=Offer('t','game','h2h','home','draftkings',D('1.58'),D(0))
        for method in ('power','additive','shin','worst_case'):
            result=calculate_featured_ev(market,target,refs,required_reference_books=('fanduel','pinnacle'),devig_method=method)
            pooled=sum(dict(book.probabilities)['home']*book.weight for book in result.reference_books)
            self.assertLess(abs(pooled-result.conditional_fair_probability),D('1e-26'))
            self.assertLess(abs(sum(dict(result.conditional_probabilities).values())-1),D('1e-26'))
