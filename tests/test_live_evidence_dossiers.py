"""Offline artifact checks only; never evidence of production approval."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "source-approval"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class LiveEvidenceDossierTests(unittest.TestCase):
    def test_live_capture_bytes_match_manifest(self):
        bundle = ROOT / "novig-real-quote-evidence/captures/20261002T111208373869Z"
        manifest = read(bundle / "manifest.json")
        for filename, field in (("response.body", "body_sha256"),
                                ("mapping-summary.json", "summary_sha256"),
                                ("capture_script.py", "capture_script_sha256")):
            self.assertEqual(manifest[field], hashlib.sha256((bundle / filename).read_bytes()).hexdigest())
        self.assertEqual(manifest["body_bytes"], (bundle / "response.body").stat().st_size)
        self.assertEqual(200, manifest["http_status"])
        self.assertFalse(manifest["credential_retained"])
        self.assertFalse(manifest["production_admissible"])
        self.assertNotIn("apiKey", manifest["public_parameters"])
        self.assertNotIn("?", manifest["endpoint"])

    def test_absence_is_retained_not_fabricated_quote(self):
        bundle = ROOT / "novig-real-quote-evidence/captures/20261002T111208373869Z"
        response = read(bundle / "response.body")
        summary = read(bundle / "mapping-summary.json")
        self.assertEqual(44, len(response))
        self.assertTrue(all(e["bookmakers"] == [] for e in response))
        self.assertEqual(len(response), summary["event_count"])
        self.assertEqual([], summary["novig_h2h_markets"])
        self.assertEqual(0, summary["complete_two_team_market_count"])
        self.assertFalse(summary["governing_contract_proven"])
        self.assertFalse(summary["pregame_authority_proven"])

    def test_draftkings_v2_preserves_rejected_v1(self):
        root = ROOT / "draftkings-la-nba-fullgame-conditional-v2"
        review = read(root / "review.json")
        historical = review["historical_review"]
        path = (root / historical["path"]).resolve()
        self.assertEqual(ROOT / "draftkings-la-nba-fullgame-2way-moneyline-v1/review.json", path)
        self.assertEqual(historical["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual("rejected", read(path)["decision"])
        self.assertEqual("no_push_two_way", read(path)["requested_assertion_class"])
        self.assertEqual("decisive_two_way", review["requested_assertion_class"])
        self.assertFalse(historical["semantic_reinterpretation_permitted"])

    def test_opening_new_review_cannot_authorize(self):
        review = read(ROOT / "draftkings-la-nba-fullgame-conditional-v2/review.json")
        self.assertEqual("insufficient_evidence", review["decision"])
        self.assertFalse(review["production_admissible"])
        self.assertFalse(review["executable"])
        self.assertFalse(review["provider_contacted"])
        self.assertEqual([], review["authorized_assertion_classes"])
        self.assertEqual([], review["runtime_policy_grants"])
        self.assertIsNone(review["approved_conditioning_contract"])
        self.assertIsNone(review["approved_invalidation_behavior"])
        self.assertFalse(review["evidence_inventory"]["complete_applicable_rules_universe"])


if __name__ == "__main__":
    unittest.main()
