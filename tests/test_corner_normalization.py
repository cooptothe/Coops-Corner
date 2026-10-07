import json
import unittest
from pathlib import Path

from corner.normalization import normalize_event


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "odds_api" / "v4"


class CornerNormalizationTests(unittest.TestCase):
    def test_featured_nfl_normalizes_main_markets_with_deterministic_locators(self):
        event = json.loads((FIXTURES / "nfl_featured_source_ids_t1.json").read_text())

        quotes = normalize_event(event)

        self.assertEqual(24, len(quotes))
        self.assertEqual(24, len({quote.source_record_key for quote in quotes}))
        self.assertEqual(
            "event[32367f882fac1a0c20a6335619922025]/bookmaker[draftkings]/market[h2h:0]/outcome[0]",
            quotes[0].source_record_key,
        )
        self.assertEqual("moneyline", quotes[0].market_type_code)
        self.assertEqual("home", quotes[0].outcome_side_code)
        self.assertEqual("Los Angeles Rams", quotes[0].selected_participant_name)

        total = next(quote for quote in quotes if quote.provider_market_key == "totals")
        self.assertEqual("over", total.outcome_side_code)
        self.assertIsNone(total.selected_participant_name)
        self.assertEqual("47.5", str(total.point))

    def test_soccer_draw_is_a_moneyline_outcome_without_selected_participant(self):
        event = json.loads((FIXTURES / "soccer_three_way.json").read_text())

        draw_quotes = [quote for quote in normalize_event(event) if quote.outcome_side_code == "draw"]

        self.assertEqual(3, len(draw_quotes))
        self.assertTrue(all(quote.market_type_code == "moneyline" for quote in draw_quotes))
        self.assertTrue(all(quote.selected_participant_name is None for quote in draw_quotes))

    def test_player_prop_preserves_raw_description_as_market_subject(self):
        event = json.loads((FIXTURES / "nfl_player_pass_tds.json").read_text())

        quotes = normalize_event(event)

        self.assertEqual(4, len(quotes))
        self.assertTrue(all(quote.market_type_code == "player_pass_tds" for quote in quotes))
        self.assertTrue(all(quote.outcome_side_code in {"over", "under"} for quote in quotes))
        self.assertTrue(all(quote.selected_participant_name is None for quote in quotes))
        self.assertEqual({"Matthew Stafford", "Jaxson Dart"}, {quote.subject_participant_name for quote in quotes})
        self.assertEqual("1.5", str(quotes[0].point))


if __name__ == "__main__":
    unittest.main()
