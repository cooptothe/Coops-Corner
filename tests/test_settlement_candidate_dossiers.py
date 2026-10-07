"""Offline checks for unapproved v2 research; no domain/runtime authorization."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / 'source-approval'
NAMES = ('pinnacle-nba-fullgame-conditional-v1', 'novig-nba-fullgame-conditional-v1',
         'novig-nba-fullgame-conditional-v2')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class SettlementCandidateDossierTests(unittest.TestCase):
    def test_retained_sources_and_derivatives_match_review_and_manifest(self):
        for name in NAMES:
            root = ROOT / name
            review = read(root / 'review.json')
            self.assertEqual(2 if name.startswith('pinnacle') else 4, len(review['source_bundle']))
            self.assertEqual(len(review['source_bundle']), len({b['source_id'] for b in review['source_bundle']}))
            for binding in review['source_bundle']:
                directory = root / 'captures' / binding['capture']
                manifest = read(directory / 'manifest.json')
                source = next(s for s in manifest['sources'] if s['id'] == binding['source_id'])
                self.assertEqual(binding['sha256'], source['body_sha256'])
                self.assertEqual(200, source['http_status'])
                self.assertFalse(source['credentials_sent'])
                self.assertLessEqual(datetime.fromisoformat(source['requested_at']),
                                     datetime.fromisoformat(source['received_at']))
                for filename, sha in [('body_file', 'body_sha256'), ('text_file', 'text_sha256'),
                                      ('links_file', 'links_sha256')]:
                    path = directory / source[filename]
                    self.assertEqual(directory.resolve(), path.parent.resolve())
                    self.assertEqual(source[sha], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(source['body_bytes'], (directory / source['body_file']).stat().st_size)

    def test_capture_plans_and_implementations_are_frozen(self):
        for name in NAMES:
            root = ROOT / name
            review = read(root / 'review.json')
            for capture in {b['capture'] for b in review['source_bundle']}:
                directory = root / 'captures' / capture
                manifest = read(directory / 'manifest.json')
                for filename, sha in [('plan.json', 'plan_sha256'), ('capture_script.py', 'capture_script_sha256'),
                                      ('retention_helper.py', 'retention_helper_sha256')]:
                    self.assertEqual(manifest[sha], hashlib.sha256((directory / filename).read_bytes()).hexdigest())
                self.assertEqual({s['id'] for s in manifest['sources']},
                                 {s['id'] for s in read(directory / 'plan.json')['sources']})

    def test_neither_review_grants_production_authority_or_completeness(self):
        for name in NAMES:
            review = read(ROOT / name / 'review.json')
            self.assertEqual('insufficient_evidence', review['decision'])
            self.assertEqual('decisive_settlement_conditional', review['calculation_basis_under_review'])
            self.assertFalse(review['production_admissible'])
            self.assertFalse(review['executable'])
            self.assertFalse(review['reviewer']['production_approval_authority'])
            self.assertFalse(review['provider_contacted'])
            self.assertEqual([], review['runtime_policy_grants'])
            self.assertEqual([], review['authorized_assertion_classes'])
            self.assertIsNone(review['approved_conditioning_contract'])
            self.assertIsNone(review['approved_invalidation_behavior'])
            self.assertEqual('not_established', review['compatibility_with_target_and_other_reference'])
            self.assertFalse(review['evidence_inventory']['complete_applicable_rules_universe'])
            self.assertTrue(review['evidence_inventory']['missing'])
            self.assertTrue(review['new_review_revision_required_for_approval'])

    def test_scope_and_effective_period_are_not_invented(self):
        for name in NAMES:
            review = read(ROOT / name / 'review.json')
            scope = review['candidate_scope']
            self.assertEqual('NBA', scope['competition'])
            for key in ('rules_jurisdiction', 'provider_product_binding', 'canonical_market_id',
                        'canonical_sportsbook_id', 'actual_offering_binding'):
                self.assertIsNone(scope[key])
            self.assertFalse(scope['current_provider_availability_verified'])
            self.assertIsNone(review['governing_effective_from'])
            self.assertIsNone(review['governing_effective_until'])

    def test_novig_adverse_economics_and_missing_contract_are_not_erased(self):
        root = ROOT / NAMES[1]
        review = read(root / 'review.json')
        directory = root / 'captures' / review['source_bundle'][0]['capture']
        self.assertIn('FVS is a settlement, not a refund', (directory / 'novig_fvs.txt').read_text(encoding='utf-8'))
        contracts = (directory / 'novig_contracts.txt').read_text(encoding='utf-8').splitlines()
        self.assertIn('WNBA Winner Series', contracts)
        self.assertNotIn('NBA Winner Series', contracts)
        self.assertFalse(review['public_fvs_is_stake_refund'])
        self.assertIsNone(review['public_fvs_applies_to_exact_candidate_quote'])
        self.assertFalse(review['absence_from_index_proves_no_nba_product'])

    def test_pinnacle_rules_retain_duration_and_economic_context(self):
        root = ROOT / NAMES[0]
        review = read(root / 'review.json')
        directory = root / 'captures' / review['source_bundle'][0]['capture']
        rules = (directory / 'pinnacle_rules.txt').read_text(encoding='utf-8')
        for phrase in ('43 minutes', '30 hours', '12 hours', 'Refund a bet', 'all overtimes'):
            self.assertIn(phrase, rules)
        self.assertIn('tied_late_interruption', review['adverse_review_cases'])

    def test_novig_revision_two_preserves_previous_review_bytes(self):
        root = ROOT / NAMES[2]
        review = read(root / 'review.json')
        previous = review['previous_review']
        path = (root / previous['path']).resolve()
        self.assertEqual((ROOT / NAMES[1] / 'review.json').resolve(), path)
        self.assertEqual(previous['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual('insufficient_evidence', read(path)['decision'])

    def test_brand_mapping_is_not_contract_or_fvs_applicability(self):
        review = read(ROOT / NAMES[2] / 'review.json')
        mapping = review['public_directory_mapping']
        self.assertEqual('novig', mapping['bookmaker_key'])
        self.assertEqual('us_ex', mapping['region'])
        self.assertFalse(mapping['establishes_exact_contract'])
        self.assertIsNone(review['public_fvs_applies_to_exact_candidate_quote'])
        self.assertFalse(review['live_api_called'])
        self.assertFalse(review['reference_scope_changed'])

    def test_mapping_revision_contains_real_docs_not_a_fabricated_quote(self):
        root = ROOT / NAMES[2]
        review = read(root / 'review.json')
        directory = root / 'captures' / review['source_bundle'][0]['capture']
        directory_text = (directory / 'odds_api_bookmakers.txt').read_text(encoding='utf-8')
        self.assertIn('us_ex\nnovig', directory_text)
        api_text = (directory / 'odds_api_v4.txt').read_text(encoding='utf-8')
        self.assertIn('includeLinks', api_text)
        self.assertIn('includeSids', api_text)
        self.assertIn('For NBA single games: Winner', (directory / 'novig_sports.txt').read_text(encoding='utf-8'))
        self.assertFalse(review['candidate_scope']['current_provider_availability_verified'])


if __name__ == '__main__':
    unittest.main()
