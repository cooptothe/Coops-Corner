import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("novig_capture", Path(__file__).resolve().parents[1] / "source-approval/capture_novig_quote.py")
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class Raw(io.BytesIO):
    def read(self, count, decode_content=False):
        return super().read(count)


class Session:
    def __init__(self, body, status=200, error=False):
        self.body, self.status, self.error = body, status, error
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        assert kwargs["allow_redirects"] is False
        assert kwargs["params"]["includeLinks"] == "true"
        assert kwargs["params"]["includeSids"] == "true"
        if self.error:
            raise RuntimeError("https://example.invalid?apiKey=PRIVATE_KEY")
        class Response:
            status_code = self.status
            headers = {"Content-Type": "application/json", "Set-Cookie": "PRIVATE_KEY"}
            raw = Raw(self.body)
            def __enter__(self): return self
            def __exit__(self, *args): pass
        return Response()


class QuoteCaptureTests(unittest.TestCase):
    def test_explicit_betonline_research_scope_not_novig_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            class ScopeSession(Session):
                def get(self, url, **kwargs):
                    assert kwargs["params"]["bookmakers"] == "draftkings,pinnacle,betonlineag"
                    return super().get(url, **kwargs)
            result = capture.capture("PRIVATE_KEY", ScopeSession(b'[]'), Path(temp) / "capture",
                                     ("draftkings", "pinnacle", "betonlineag"))
            self.assertEqual("no_complete_candidate_quotes", result["status"])
            self.assertEqual("draftkings,pinnacle,betonlineag", result["public_parameters"]["bookmakers"])

    def test_candidate_scope_accounts_for_missing_books(self):
        body = b'[{"sport_key":"basketball_nba","id":"e","home_team":"A","away_team":"B","bookmakers":[{"key":"draftkings","sid":"x","markets":[{"key":"h2h","outcomes":[{"name":"A","price":1.9},{"name":"B","price":2.1}]}]}]}]'
        result = capture.summarize(body, ("draftkings", "pinnacle", "novig"))
        self.assertEqual({"draftkings": 1, "pinnacle": 0, "novig": 0}, result["complete_markets_by_book"])
        self.assertNotIn("novig_h2h_markets", result)
        self.assertFalse(result["governing_contract_proven"])

    def test_no_automatic_alternate_book_scope(self):
        with self.assertRaisesRegex(ValueError, "unsupported_research_scope"):
            capture.capture("PRIVATE_KEY", None, None, ("betonline",))

    def run_capture(self, body, status=200, error=False):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "capture"
            session = Session(body, status, error)
            result = capture.capture("PRIVATE_KEY", session, target)
            files = {p.name: p.read_bytes() for p in target.iterdir()}
            self.assertEqual(session.calls, 1)
            self.assertNotIn(b"PRIVATE_KEY", b"".join(files.values()))
            return result, files

    def test_empty_retained_without_fabrication(self):
        result, files = self.run_capture(b"[ ]\n")
        self.assertEqual(result["status"], "no_complete_novig_quote")
        self.assertEqual(files["response.body"], b"[ ]\n")

    def test_exception_does_not_retain_secret_url(self):
        result, files = self.run_capture(b"", error=True)
        self.assertEqual(result["status"], "capture_failed")
        self.assertNotIn("response.body", files)

    def test_echoed_secret_refuses_body(self):
        result, files = self.run_capture(b'{"message":"PRIVATE_KEY"}', 401)
        self.assertEqual(result["status"], "capture_failed")
        self.assertNotIn("response.body", files)

    def test_http_failure_retained_not_approved(self):
        result, files = self.run_capture(b'{"message":"quota reached"}', 429)
        self.assertEqual(result["status"], "http_error_retained")
        self.assertFalse(result["production_admissible"])

    def test_raw_and_source_ids_preserved(self):
        body = b'[{"sport_key":"basketball_nba","id":"e1","home_team":"A","away_team":"B","bookmakers":[{"key":"novig","sid":"source1","markets":[{"key":"h2h","outcomes":[{"name":"A","price":1.9},{"name":"B","price":2.1}]}]}]}]'
        result, files = self.run_capture(body)
        self.assertEqual(result["status"], "novig_quote_retained")
        self.assertEqual(files["response.body"], body)
        summary = json.loads(files["mapping-summary.json"])
        self.assertFalse(summary["governing_contract_proven"])
        self.assertEqual(summary["novig_h2h_markets"][0]["full_bookmaker_object"]["sid"], "source1")


if __name__ == "__main__":
    unittest.main()
