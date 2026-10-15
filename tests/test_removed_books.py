import json
import unittest
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal

from api.database import build_raw
from corner.links import clean_url
from corner.prop_markets import normalize_event, market_meta, build_bets
from corner.reference_weights import normalized_reference_weights
from pipelines.odds_ingestion import PARAMS, sanitize
from pipelines.props_ingestion import BOOKS
from tests.test_database_catalog import board, q, PEOPLE, NOW


class RemovedBooksTests(unittest.TestCase):
    def test_explicit_request_override_is_rejected_before_network_access(self):
        from pipelines.odds_ingestion import capture
        with patch('pipelines.odds_ingestion.ODDS_API_KEY', 'test-key'), \
                patch('pipelines.odds_ingestion.requests.Session') as session:
            with self.assertRaisesRegex(ValueError, 'Withdrawn sportsbook'):
                capture(Path('unused-removal-test-capture'), {'bookmakers': 'draftkings,betonlineag'})
            session.assert_not_called()

    def test_retained_board_and_overrides_cannot_restore_removed_book(self):
        rows = board() + [q('betonlineag', 'moneyline', side, '4') for side in ('home', 'away')]
        raw = build_raw(rows, PEOPLE, now=NOW, references=('pinnacle', 'betonlineag'),
                        targets=('draftkings', 'betonlineag'))
        self.assertNotIn('betonlineag', json.dumps(raw))

    def test_requests_and_links_exclude_removed_book(self):
        self.assertNotIn('betonlineag', PARAMS['bookmakers'].split(','))
        self.assertNotIn('betonlineag', BOOKS.split(','))
        self.assertEqual(12, len(PARAMS['bookmakers'].split(',')))
        self.assertEqual(14, len(BOOKS.split(',')))
        self.assertIsNone(clean_url('https://www.betonline.ag/sportsbook', 'betonlineag'))
        self.assertEqual({'pinnacle': Decimal(1)}, normalized_reference_weights(['pinnacle', 'betonlineag']))

    def test_unexpected_provider_book_is_removed(self):
        body = json.dumps([{'bookmakers': [{'key': 'betonlineag', 'markets': []}]}]).encode()
        self.assertEqual([], json.loads(sanitize(body))[0]['bookmakers'])
        event = {'bookmakers': [{'key': 'betonlineag', 'markets': []}]}
        self.assertEqual([], normalize_event(event, 'player_points', market_meta('basketball_nba', 'player_points')))

    def test_retained_props_cannot_become_targets_or_references(self):
        quotes = [dict(book=b, player='Player', point='20.5', side=s, price='2')
                  for b in ('betonlineag', 'pinnacle', 'fanduel') for s in (0, 1)]
        events = {'event': dict(sport_key='basketball_nba', markets={'player_points': {'quotes': quotes}})}
        # The removed book cannot provide a second reference for the remaining two books.
        self.assertEqual([], build_bets(events))
