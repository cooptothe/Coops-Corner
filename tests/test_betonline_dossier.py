"""Offline integrity and boundary checks; never production authority proof."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "source-approval"
DOSSIER = ROOT / "betonline-nba-fullgame-conditional-v1"
QUOTE = ROOT / "product-applicability-betonline-v1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BetOnlineDossierTests(unittest.TestCase):
    def test_research_scope_is_explicit_and_does_not_activate_runtime(self):
        decision = read(QUOTE / "scope-decision.json")
        self.assertEqual(["pinnacle", "betonlineag"], decision["required_references"])
        self.assertEqual("deferred_not_rejected", decision["novig_disposition"])
        for field in ("production_admissible", "runtime_generations_modified",
                      "existing_frozen_commands_modified", "automatic_fallback_permitted", "emailing_permitted"):
            self.assertFalse(decision[field])

    def test_live_quote_retained_but_betonline_absence_not_filled(self):
        bundle = QUOTE / "captures/20261002T120312455406Z"
        manifest = read(bundle / "manifest.json")
        for filename, field in (("response.body", "body_sha256"),
                                ("mapping-summary.json", "summary_sha256"),
                                ("capture_script.py", "capture_script_sha256")):
            self.assertEqual(manifest[field], sha(bundle / filename))
        self.assertEqual("draftkings,pinnacle,betonlineag", manifest["public_parameters"]["bookmakers"])
        events = read(bundle / "response.body")
        self.assertEqual(44, len(events))
        self.assertFalse(any(b["key"] == "betonlineag" for e in events for b in e["bookmakers"]))
        self.assertEqual({"draftkings": 44, "pinnacle": 12, "betonlineag": 0},
                         read(bundle / "mapping-summary.json")["complete_markets_by_book"])

    def test_failed_source_attempts_and_denial_bodies_preserved(self):
        manifests = sorted((DOSSIER / "captures").glob("*/manifest.json"))
        self.assertEqual(2, len(manifests))
        for path in manifests:
            manifest = read(path)
            for filename, field in (("plan.json", "plan_sha256"),
                                    ("capture_script.py", "capture_script_sha256"),
                                    ("retention_helper.py", "retention_helper_sha256")):
                self.assertEqual(manifest[field], sha(path.parent / filename))
            for source in manifest["sources"]:
                for filename, field in (("body_file", "body_sha256"),
                                        ("text_file", "text_sha256"),
                                        ("links_file", "links_sha256")):
                    if filename in source:
                        self.assertEqual(source[field], sha(path.parent / source[filename]))
        first = read(manifests[0])
        second = read(manifests[1])
        self.assertTrue(all(s["capture_status"] == "capture_error" for s in first["sources"][:2]))
        self.assertTrue(all(s["http_status"] == 403 for s in second["sources"][:2]))
        self.assertTrue(second["tls_trust_store"]["certificate_verification"])
        self.assertTrue(second["tls_trust_store"]["hostname_verification"])

    def test_no_rules_approval_inferred_from_directory_or_previews(self):
        review = read(DOSSIER / "review.json")
        self.assertEqual("insufficient_evidence", review["decision"])
        self.assertEqual(["odds_api_bookmakers"], [s["source_id"] for s in review["source_bundle"]])
        self.assertEqual(0, review["evidence_inventory"]["retained_substantive_operator_rule_bodies"])
        self.assertEqual(0, review["quote_capture"]["betonline_market_count"])
        self.assertFalse(review["production_admissible"])
        self.assertFalse(review["provider_contacted"])
        self.assertEqual([], review["runtime_policy_grants"])
        self.assertEqual([], review["authorized_assertion_classes"])
        self.assertIsNone(review["approved_conditioning_contract"])


if __name__ == "__main__":
    unittest.main()
