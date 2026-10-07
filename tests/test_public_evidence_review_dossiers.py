"""Offline review integrity checks, not source authenticity or approval tests."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "source-approval"
DOSSIERS = ("draftkings-la-nba-fullgame-conditional-v2",
            "pinnacle-nba-fullgame-conditional-v1")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def reviews():
    return [read(ROOT / name / "reviews/public-evidence-2026-10-02.json")
            for name in DOSSIERS]


class PublicEvidenceReviewTests(unittest.TestCase):
    def test_all_retained_references_and_prior_reviews_match(self):
        for review in reviews():
            refs = [review["previous_review"], review["scope_reference"],
                    review["quote_evidence"], *review["sources"]]
            if "historical_v1" in review:
                refs.append(review["historical_v1"])
            for ref in refs:
                with self.subTest(path=ref["path"]):
                    self.assertEqual(ref["sha256"], hashlib.sha256(
                        (ROOT / ref["path"]).read_bytes()).hexdigest())
                    if "text_path" in ref:
                        self.assertEqual(ref["text_sha256"], hashlib.sha256(
                            (ROOT / ref["text_path"]).read_bytes()).hexdigest())

    def test_reported_offering_ids_exist_in_actual_retained_quote(self):
        for review in reviews():
            quote = review["quote_evidence"]
            events = read(ROOT / quote["path"])
            event = next(e for e in events if e["id"] == quote["event_id"])
            book = next(b for b in event["bookmakers"]
                        if b["key"] == quote["bookmaker_key"])
            market = next(m for m in book["markets"]
                          if m["key"] == quote["market_key"])
            self.assertEqual(quote["sport_key"], event["sport_key"])
            self.assertEqual(quote["bookmaker_sid"], book["sid"])
            self.assertEqual(quote["bookmaker_link"], book["link"])
            self.assertEqual(quote["market_sid"], market["sid"])
            self.assertEqual(quote["outcome_sids"],
                             [o["sid"] for o in market["outcomes"]])

    def test_current_corpus_completion_does_not_grant_authority(self):
        for review in reviews():
            self.assertEqual("current_corpus_review_complete", review["review_phase"])
            self.assertEqual("insufficient_evidence", review["decision"])
            for field in ("production_admissible", "complete_applicable_evidence_universe",
                          "provider_contacted_this_review", "new_network_capture_performed"):
                self.assertFalse(review[field])
            self.assertFalse(review["quote_evidence"]["offering_to_rules_binding_proven"])
            self.assertFalse(review["quote_evidence"]["positive_pregame_authority"])
            self.assertEqual([], review["authorized_assertion_classes"])
            self.assertEqual([], review["runtime_policy_grants"])
            self.assertIsNone(review["approved_conditioning_contract"])
            self.assertTrue(review["unresolved"])
            self.assertTrue(review["reopen_only_for"])
            self.assertTrue(review["new_review_required_for_approval"])

    def test_v1_rejection_and_revised_research_scope_are_preserved(self):
        dk = reviews()[0]
        self.assertEqual("rejected", read(ROOT / dk["historical_v1"]["path"])["decision"])
        self.assertFalse(dk["historical_v1"]["reinterpretation_permitted"])
        scope = read(ROOT / dk["scope_reference"]["path"])
        self.assertEqual(["pinnacle", "betonlineag"], scope["required_references"])
        self.assertEqual("deferred_not_rejected", scope["novig_disposition"])
        self.assertFalse(scope["runtime_generations_modified"])
        self.assertFalse(scope["emailing_permitted"])


if __name__ == "__main__":
    unittest.main()
