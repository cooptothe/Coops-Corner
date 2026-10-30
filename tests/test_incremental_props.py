from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch
from pipelines import props_ingestion as props
from corner.prop_markets import build_bets
from tests.test_alternate_props import data, NOW

class IncrementalProps(unittest.TestCase):
    def setUp(self):
        props._pricing_cache.clear();self.addCleanup(props._pricing_cache.clear)
        self.data=data()
        event=self.data['events']['event-1']
        event['markets']['player_threes']=deepcopy(event['markets']['player_threes_alternate'])
        event['markets']['player_assists']=deepcopy(event['markets']['player_threes_alternate'])

    def expected(self):
        events=props.prune(deepcopy(self.data),NOW,props.MAX_AGE)['events']
        return build_bets(events,fallback_margin='0.10',include_dfs=False)

    def test_unchanged_pairs_reuse_and_current_metadata_is_preserved(self):
        with patch.object(props,'load',side_effect=lambda:deepcopy(self.data)),patch.object(props,'build_bets',wraps=build_bets) as compute:
            initial=props.bets(NOW)
            self.assertEqual(initial,self.expected())
            self.assertEqual(compute.call_count,2)
            for stored in self.data['events']['event-1']['markets'].values():
                for quote in stored['quotes']:
                    quote['updated_at']=NOW.isoformat()
                    quote['links']={'event':'https://example.com/new'}
                    quote['source_ids']={'outcome':'new-id'}
            self.assertEqual(props.bets(NOW),self.expected())
            self.assertEqual(compute.call_count,2)
            self.data['events']['event-1']['markets']['player_threes_alternate']['quotes'][0]['price']='2.3'
            self.assertEqual(props.bets(NOW),self.expected())
            self.assertEqual(compute.call_count,3)

    def test_compact_feed_preserves_every_row_that_can_pass_a_supported_method(self):
        with patch.object(props,'load',side_effect=lambda:deepcopy(self.data)):
            full=props.bets(NOW)
            compact=props.bets(NOW,feed_only=True)
        self.assertTrue(full)
        wanted=[b for b in full if props.feed_candidate(b)]
        self.assertEqual(compact,wanted)
        self.assertTrue(compact)
        self.assertLess(len(compact),len(full))

    def test_a_positive_alternative_method_is_not_lost(self):
        bet={'ev':'-0.1','sharps':['fanduel','pinnacle'],'devig_comparisons':[{'method':'power','ev':'0.01'}]}
        self.assertTrue(props.feed_candidate(bet))
        self.assertFalse(props.feed_candidate({**bet,'sharps':['betmgm','bovada']}))
        self.assertFalse(props.feed_candidate({**bet,'devig_comparisons':[]}))
