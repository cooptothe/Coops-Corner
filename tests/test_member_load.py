"""Isolated real HTTP acceptance: temporary accounts, no production state."""
import unittest
from api.catalog import FixtureCatalog
from pipelines.member_load import rehearse, summary, ROUTES

class MemberLoad(unittest.TestCase):
    def test_http_sessions_access_privacy_and_revocation(self):
        result = rehearse(FixtureCatalog(), sessions=2, rounds=1)
        self.assertEqual(result['result'], 'passed')
        self.assertEqual(set(result['per_route']), set(ROUTES))
        self.assertTrue(all(stats['samples']==2 for stats in result['per_route'].values()))
        self.assertTrue(result['anonymous_denied'])
        self.assertTrue(result['invalid_sessions_denied'])
        self.assertTrue(result['suspension_revokes_copied_token'])
        self.assertTrue(result['private_responses_no_store'])
        self.assertEqual(result['production_account_mutations'],0)

    def test_load_is_bounded_before_resources_are_opened(self):
        for kwargs in ({'sessions':0},{'sessions':11},{'rounds':0},{'rounds':6},{'budget_ms':0}):
            with self.assertRaises(ValueError):rehearse(None, **kwargs)

    def test_tail_latency_uses_nearest_rank(self):
        self.assertEqual(summary(list(range(1,21)))['p95_ms'],19)

if __name__=='__main__':unittest.main()
