import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from corner.featured_markets import (FEATURED_MARKETS, FeaturedMarketError,
                                    normalize_featured_payload, request_markets, snapshot_document)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/odds_api/v4/featured_six_markets_demo.json"
NOW = datetime(2030, 1, 1, 19, tzinfo=timezone.utc)


class FeaturedMarketTests(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()
        self.data = json.loads(self.raw)

    def normalize(self, data):
        return normalize_featured_payload(json.dumps(data).encode(), received_at=NOW)

    def test_all_six_markets_keep_direction_and_full_outcome_population(self):
        result = normalize_featured_payload(self.raw, received_at=NOW)
        self.assertEqual(set(FEATURED_MARKETS), {q.market_key for q in result.quotes})
        self.assertEqual(25, len(result.quotes))
        self.assertEqual(25, len({q.quote_id for q in result.quotes}))
        self.assertEqual(3, sum(q.selection_side == "draw" for q in result.quotes))
        self.assertEqual(8, sum(q.scope == "competition" for q in result.quotes))
        self.assertEqual(7, sum(q.bet_side == "lay" for q in result.quotes))
        self.assertTrue(all(q.decimal_odds > 1 for q in result.quotes))

    def test_quote_locator_resolves_exact_source_and_hash(self):
        result = normalize_featured_payload(self.raw, received_at=NOW)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), result.payload_sha256)
        for quote in result.quotes:
            source = self.data
            for part in quote.source_pointer.split("/")[1:]:
                source = source[int(part)] if isinstance(source, list) else source[part]
            self.assertEqual(source["name"], quote.selection_name)
        self.assertEqual(result, normalize_featured_payload(self.raw, received_at=NOW))

    def test_provider_timestamps_are_not_fabricated_from_receipt(self):
        result = normalize_featured_payload(self.raw, received_at=NOW)
        first = result.quotes[0]
        self.assertEqual("demo-event-a", first.bookmaker_sid)
        self.assertEqual(58, first.provider_updated_at.second)
        self.assertTrue(all(q.provider_updated_at is None for q in result.quotes
                            if q.bookmaker_key == "demo_book_b"))

    def test_decimal_precision_round_trip_without_float(self):
        raw = self.raw.replace(b'"price": 3.4', b'"price": 3.12345678901234567890123456789', 1)
        result = normalize_featured_payload(raw, received_at=NOW)
        self.assertEqual(Decimal("3.12345678901234567890123456789"), result.quotes[0].decimal_odds)
        view = snapshot_document(result)
        self.assertEqual("3.12345678901234567890123456789", view["quotes"][0]["decimal_odds"])
        self.assertEqual("2030-01-01T19:00:00.000000Z", view["received_at"])
        json.dumps(view)

    def test_out_of_scope_markets_are_reported_not_normalized(self):
        for key in ("player_points", "unknown_alternate_team_totals", "h2h_q1", "team_totals_h1", "h2h_3_way"):
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                data[0]["bookmakers"][0]["markets"].append({"key": key, "outcomes": []})
                result = self.normalize(data)
                self.assertEqual(25, len(result.quotes))
                self.assertEqual(key, result.excluded_markets[0].market_key)

    def test_request_planning_respects_catalog_and_automatic_lays(self):
        self.assertEqual(("h2h", "spreads", "totals"), request_markets(has_outrights=False))
        self.assertEqual(("outrights",), request_markets(has_outrights=True))
        self.assertEqual(("h2h",), request_markets(has_outrights=False, requested=("h2h_lay",)))
        self.assertEqual(("outrights",), request_markets(has_outrights=True, requested=("outrights_lay",)))
        for kwargs in ({"has_outrights": None}, {"has_outrights": False, "requested": ()},
                       {"has_outrights": False, "requested": ("outrights",)},
                       {"has_outrights": True, "requested": ("spreads",)},
                       {"has_outrights": False, "requested": ("player_points",)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(FeaturedMarketError):
                request_markets(**kwargs)

    def test_malformed_decimal_prices_rejected(self):
        for price in (None, True, "NaN", "Infinity", "bad"):
            with self.subTest(price=price):
                self.data[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = price
                with self.assertRaises(FeaturedMarketError):
                    self.normalize(self.data)

    def test_non_bettable_price_excluded_without_changing_other_quotes(self):
        original = self.normalize(self.data)
        for price in (1, 0, -110):
            with self.subTest(price=price):
                data = copy.deepcopy(self.data)
                data[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = price
                result = self.normalize(data)
                self.assertEqual(len(original.quotes) - 1, len(result.quotes))
                self.assertTrue(all(q.decimal_odds > 1 for q in result.quotes))
                excluded = [e for e in result.excluded_markets
                            if e.reason == "invalid_decimal_price_excluded"]
                self.assertEqual(1, len(excluded))
                self.assertEqual(result, self.normalize(data))

    def test_missing_and_invalid_lines_rejected(self):
        for point in (None, True, "NaN", "Infinity"):
            with self.subTest(point=point):
                self.data[0]["bookmakers"][0]["markets"][1]["outcomes"][0]["point"] = point
                with self.assertRaises(FeaturedMarketError):
                    self.normalize(self.data)

    def test_line_on_moneyline_rejected(self):
        self.data[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["point"] = 1
        with self.assertRaises(FeaturedMarketError):
            self.normalize(self.data)

    def test_unknown_game_selection_rejected(self):
        self.data[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["name"] = "Another Team"
        with self.assertRaises(FeaturedMarketError):
            self.normalize(self.data)

    def test_empty_response_and_single_event_supported(self):
        self.assertEqual((), self.normalize([]).quotes)
        self.assertEqual(17, len(self.normalize(self.data[0]).quotes))

    def test_duplicate_quote_event_and_book_rejected(self):
        mutations = [lambda d: d.append(copy.deepcopy(d[0])),
                     lambda d: d[0]["bookmakers"].append(copy.deepcopy(d[0]["bookmakers"][0])),
                     lambda d: d[0]["bookmakers"][0]["markets"].append(
                         copy.deepcopy(d[0]["bookmakers"][0]["markets"][0]))]
        for mutate in mutations:
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.assertRaises(FeaturedMarketError):
                self.normalize(data)

    def test_invalid_json_shapes_and_duplicate_keys_rejected(self):
        for raw in (b'{"id":"one","id":"two"}', b'[{"id":"e","sport_key":"s","bookmakers":null}]',
                    b'NaN', b'null', b'42', b'"event"', b'{'):
            with self.subTest(raw=raw), self.assertRaises(FeaturedMarketError):
                normalize_featured_payload(raw, received_at=NOW)

    def test_naive_time_and_non_bytes_rejected(self):
        with self.assertRaises(FeaturedMarketError):
            normalize_featured_payload(self.raw, received_at=NOW.replace(tzinfo=None))
        with self.assertRaises(FeaturedMarketError):
            normalize_featured_payload(self.raw.decode(), received_at=NOW)


if __name__ == "__main__":
    unittest.main()
