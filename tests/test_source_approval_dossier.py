"""Offline retention/review checks; passing these never grants production authority."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / 'source-approval' / 'draftkings-la-nba-fullgame-2way-moneyline-v1'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class SourceApprovalDossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = read(ROOT / 'review.json')
        cls.interpretation = read(ROOT / cls.review['interpretation_file'])
        cls.cases = read(ROOT / cls.review['adverse_cases_file'])
        cls.sources = {}
        cls.manifests = sorted((ROOT / 'captures').glob('*/manifest.json'))
        for path in cls.manifests:
            for source in read(path)['sources']:
                if source['id'] in cls.sources:
                    raise AssertionError('Ambiguous capture ID: explicit review binding needed')
                cls.sources[source['id']] = (path.parent, source)

    def test_all_ten_responses_and_derivatives_match_capture_digests(self):
        self.assertEqual(10, len(self.sources))
        for identifier, (directory, source) in self.sources.items():
            with self.subTest(source=identifier):
                self.assertEqual(200, source['http_status'])
                self.assertFalse(source['credentials_sent'])
                self.assertLessEqual(datetime.fromisoformat(source['requested_at']),
                                     datetime.fromisoformat(source['received_at']))
                for name, sha in [('body_file', 'body_sha256'), ('text_file', 'text_sha256'),
                                  ('links_file', 'links_sha256')]:
                    content = (directory / source[name]).read_bytes()
                    self.assertEqual(source[sha], hashlib.sha256(content).hexdigest())
                self.assertEqual(source['body_bytes'], (directory / source['body_file']).stat().st_size)

    def test_frozen_capture_plan_and_script_are_verified_when_retained(self):
        retained_count = 0
        for path in self.manifests:
            manifest = read(path)
            for name, sha in [('plan.json', 'plan_sha256'), ('capture_script.py', 'capture_script_sha256')]:
                artifact = path.parent / name
                if artifact.exists():
                    retained_count += 1
                    self.assertEqual(manifest[sha], hashlib.sha256(artifact.read_bytes()).hexdigest())
        self.assertGreaterEqual(retained_count, 2)

    def test_review_binds_exact_retained_bundle_and_accounts_for_shells(self):
        used = set()
        for binding in self.review['source_bundle']:
            directory, source = self.sources[binding['source_id']]
            self.assertEqual(binding['capture'], directory.name)
            self.assertEqual(binding['sha256'], source['body_sha256'])
            used.add(binding['source_id'])
        excluded = {item['source_id'] for item in self.review['excluded_substantive_sources']}
        self.assertFalse(used & excluded)
        self.assertEqual(set(self.sources), used | excluded)
        self.assertIn('dk_la_basketball_json', used)
        self.assertIn('dk_la_general_json', used)

    def test_rejection_cannot_be_mistaken_for_an_admission(self):
        self.assertEqual('rejected', self.review['decision'])
        self.assertEqual('no_push_two_way', self.review['requested_assertion_class'])
        self.assertFalse(self.review['production_admissible'])
        self.assertFalse(self.review['reviewer']['production_approval_authority'])
        self.assertEqual([], self.review['authorized_assertion_classes'])
        self.assertEqual([], self.review['runtime_policy_grants'])
        self.assertFalse(self.interpretation['executable'])
        self.assertFalse(self.interpretation['production_admissible'])
        self.assertEqual('push_capable', self.interpretation['review_classification'])
        self.assertEqual('none', self.interpretation['admission_action'])
        self.assertNotEqual('corner.settlement_rules_evidence/1', self.interpretation['format'])

    def test_real_louisiana_rule_content_and_adverse_clauses_were_retained(self):
        docs = {}
        for identifier in ('dk_la_general_json', 'dk_la_market_json', 'dk_la_basketball_json'):
            directory, source = self.sources[identifier]
            self.assertIn('/US-LA-SB_ent/', source['url'])
            docs[identifier] = read(directory / source['body_file'])
            self.assertTrue(docs[identifier]['rich_text_editor'])
        general = docs['dk_la_general_json']['rich_text_editor']
        basketball = docs['dk_la_basketball_json']['rich_text_editor']
        self.assertIn('Louisiana Sportsbook House Rules', general)
        self.assertIn('such bet will be settled as Push', general)
        self.assertEqual('Basketball', docs['dk_la_basketball_json']['display_name'])
        self.assertIn('less than five minutes', basketball)
        self.assertIn('last instance of play', basketball)
        self.assertIn('four calendar days', basketball)

    def test_publisher_metadata_is_provenance_not_a_manufactured_effective_period(self):
        for item in self.interpretation['publisher_metadata']:
            directory, source = self.sources[item['source_id']]
            doc = read(directory / source['body_file'])
            self.assertEqual(item['uid'], doc['uid'])
            self.assertEqual(item['cms_version'], doc['_version'])
            self.assertEqual(item['cms_updated_at'], doc['updated_at'])
            self.assertEqual(item['cms_published_at'], doc['publish_details']['time'])
        self.assertIsNone(self.interpretation['governing_effective_from'])
        self.assertIsNone(self.interpretation['governing_effective_until'])
        self.assertEqual('US-LA', self.interpretation['candidate_scope']['jurisdiction'])
        self.assertIsNone(self.interpretation['candidate_scope']['actual_offering_binding'])

    def test_adverse_cases_preserve_counterexample_and_calendar_boundaries(self):
        self.assertTrue(self.cases['all_cases_hypothetical'])
        cases = {case['id']: case for case in self.cases['cases']}
        self.assertEqual(len(cases), len(self.cases['cases']))
        self.assertEqual('deny_no_push_approval', cases['tied_late_interruption']['expected'])
        self.assertEqual([100, 100], cases['tied_late_interruption']['given']['score'])
        for case in cases.values():
            self.assertTrue(set(case['sources']) <= set(self.sources))
        window = self.interpretation['interruption_interpretation']['completion_window']
        self.assertEqual(2, window['ordinary_calendar_days'])
        self.assertEqual(4, window['postseason_calendar_days'])
        self.assertTrue(window['not_a_duration_hours_ttl'])
        self.assertFalse(self.review['observed_real_settlement_incident'])

    def test_missing_applicability_and_withdrawal_requirements_remain_explicit(self):
        self.assertFalse(self.review['completeness']['production_applicability_complete'])
        self.assertTrue(self.review['completeness']['unresolved'])
        requirements = self.review['future_approval_requirements']
        self.assertTrue(requirements['new_review_required'])
        self.assertTrue(requirements['withdrawal_triggers'])
        self.assertFalse(requirements['current_review_expires_into_approval'])


if __name__ == '__main__':
    unittest.main()
