import unittest
from dataclasses import replace
from decimal import Decimal as D
from time import perf_counter
from corner.featured_ev import calculate_featured_ev, _reference_consensus
from corner.featured_tools import MatchedMarket, Offer, ToolInputError


class ConsensusCache(unittest.TestCase):
    def test_exact_cache_and_price_invalidation(self):
        market = MatchedMarket('game-total', 'totals', ('over', 'under'), False)
        books = ('pinnacle', 'fanduel', 'betmgm', 'betrivers')
        refs = tuple(Offer(f'{b}-{s}', market.contract_id, 'totals', s, b, D('1.91'), D(0))
                     for b in books for s in market.selection_ids)
        target = Offer('target', market.contract_id, 'totals', 'over', 'draftkings', D('2.2'), D(0))
        def calc(offers=refs):
            return calculate_featured_ev(market, target, offers, required_reference_books=books,
                                         sport_key='basketball_nba')
        _reference_consensus.cache_clear()
        cold = calc()
        self.assertEqual(cold, calc())
        self.assertEqual(_reference_consensus.cache_info().hits, 1)
        changed = (replace(refs[0], decimal_odds=D('2.5')), *refs[1:])
        self.assertNotEqual(cold.conditional_fair_probability, calc(changed).conditional_fair_probability)
        with self.assertRaises(ToolInputError):
            calc((*refs, refs[0]))
        with self.assertRaises(ToolInputError):
            calc(refs[:-1])
        started = perf_counter()
        for _ in range(1000):
            _reference_consensus.cache_clear()
            self.assertEqual(cold, calc())
        uncached = perf_counter() - started
        started = perf_counter()
        for _ in range(1000):
            self.assertEqual(cold, calc())
        cached = perf_counter() - started
        print(f'Exact repeated calculation: uncached={uncached:.3f}s cached={cached:.3f}s')
