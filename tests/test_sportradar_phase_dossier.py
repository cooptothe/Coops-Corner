"""Offline dossier checks only; these do not approve a phase authority."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1] / 'source-approval' / 'sportradar-nba-game-phase-v1'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


class SportradarPhaseDossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = read(ROOT / 'review.json')

    def test_review_is_not_an_authority_grant(self):
        self.assertEqual('insufficient_evidence', self.review['decision'])
        self.assertEqual('supported_pregame', self.review['requested_assertion_class'])
        self.assertFalse(self.review['production_admissible'])
        self.assertFalse(self.review['reviewer']['production_approval_authority'])
        self.assertEqual([], self.review['authorized_assertion_classes'])
        self.assertEqual([], self.review['runtime_policy_grants'])
        self.assertIsNone(self.review['approval_freshness_bound_seconds'])
        self.assertTrue(self.review['new_review_revision_required_for_approval'])

    def test_exact_reviewed_documentation_bundle_matches_manifest_and_bytes(self):
        self.assertEqual(4, len(self.review['source_bundle']))
        self.assertEqual(4, len({b['source_id'] for b in self.review['source_bundle']}))
        for binding in self.review['source_bundle']:
            directory = ROOT / 'captures' / binding['capture']
            manifest = read(directory / 'manifest.json')
            self.assertEqual('published_documentation_not_live_game_evidence', manifest['evidence_class'])
            source = next(s for s in manifest['sources'] if s['id'] == binding['source_id'])
            self.assertEqual(binding['sha256'], source['body_sha256'])
            self.assertEqual(200, source['http_status'])
            self.assertFalse(source['credentials_sent'])
            self.assertLessEqual(datetime.fromisoformat(source['requested_at']),
                                 datetime.fromisoformat(source['received_at']))
            for name, sha in [('body_file', 'body_sha256'), ('text_file', 'text_sha256'),
                              ('links_file', 'links_sha256')]:
                path = directory / source[name]
                self.assertEqual(directory.resolve(), path.parent.resolve())
                self.assertEqual(source[sha], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(source['body_bytes'], (directory / source['body_file']).stat().st_size)

    def test_capture_implementation_plan_and_helper_are_frozen(self):
        for capture in {b['capture'] for b in self.review['source_bundle']}:
            directory = ROOT / 'captures' / capture
            manifest = read(directory / 'manifest.json')
            for name, sha in [('plan.json', 'plan_sha256'), ('capture_script.py', 'capture_script_sha256'),
                              ('retention_helper.py', 'retention_helper_sha256')]:
                self.assertEqual(manifest[sha], hashlib.sha256((directory / name).read_bytes()).hexdigest())
            for source in read(directory / 'plan.json')['sources']:
                url = urlsplit(source['url'])
                self.assertEqual('https', url.scheme)
                self.assertEqual('developer.sportradar.com', url.netloc)
                self.assertFalse(url.query)

    def test_document_content_contains_the_reviewed_adverse_details(self):
        docs = {}
        for binding in self.review['source_bundle']:
            directory = ROOT / 'captures' / binding['capture']
            docs[binding['source_id']] = (directory / (binding['source_id'] + '.txt')).read_text(encoding='utf-8')
        self.assertIn('not linked within the API', docs['nba_status_workflow'])
        self.assertIn('before it starts or during play', docs['nba_status_workflow'])
        self.assertIn('60 seconds', docs['nba_play_by_play'])
        self.assertIn('3 seconds', docs['nba_play_by_play'])
        self.assertIn('not game status updates', docs['nba_push'])
        self.assertIn('rare exceptions', docs['account_access'])

    def test_live_evidence_and_access_are_explicitly_missing(self):
        inventory = self.review['evidence_inventory']
        for key in ('provider_clarifications', 'real_transition_captures', 'real_adverse_incidents'):
            self.assertEqual([], inventory[key])
        self.assertFalse(inventory['complete_production_evidence_universe'])
        self.assertFalse(self.review['provider_contacted'])
        self.assertFalse(self.review['production_loader_implemented'])
        self.assertTrue(self.review['unresolved'])

    def test_scope_is_fixed_but_not_falsely_bound_to_a_real_event(self):
        scope = self.review['candidate_scope']
        self.assertEqual(['Pinnacle', 'Novig'], scope['required_references'])
        self.assertEqual('DraftKings', scope['target'])
        self.assertEqual('US-LA', scope['target_jurisdiction'])
        for key in ('canonical_event_id', 'event_crosswalk', 'access_entitlement', 'season_type'):
            self.assertIsNone(scope[key])
        self.assertEqual([], scope['settlement_approvals'])
        self.assertFalse(scope['current_odds_availability_verified'])


if __name__ == '__main__':
    unittest.main()
