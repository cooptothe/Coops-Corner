import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from api.app import create_app
from api.catalog import FixtureCatalog
from api.database import LiveCatalog, build_raw, keep_latest_capture

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
START = NOW + timedelta(hours=5)
EVENT = '11111111-1111-1111-1111-111111111111'


def q(book, market, side, odds, point=None, name=None, age=60, event=EVENT):
    return dict(event_id=event, competition_code='nba', competition_name='NBA', scheduled_start=START,
                market_code=market, scope_code='full_game', side=side, point=None if point is None else Decimal(point),
                selection_name=name, book_code=book, book_name=book.title(), decimal_odds=Decimal(odds),
                observed_at=NOW - timedelta(seconds=age), provider_updated_at=None)


PEOPLE = [(EVENT, 'home', 'Hawks'), (EVENT, 'away', 'Bears')]


def board():
    rows = []
    for book, home, away in (('draftkings', '2.20', '1.95'), ('pinnacle', '1.95', '2.10'), ('prophetx', '1.93', '2.08')):
        rows += [q(book, 'moneyline', 'home', home), q(book, 'moneyline', 'away', away)]
    for book, over, under, line in (('draftkings', '1.91', '1.91', '220.5'), ('pinnacle', '1.95', '1.95', '221.5')):
        rows += [q(book, 'total', 'over', over, line), q(book, 'total', 'under', under, line)]
    for book, home, away, line in (('draftkings', '1.91', '1.91', '-3.5'), ('pinnacle', '1.91', '1.91', '-1.5')):
        rows += [q(book, 'spread', 'home', home, line), q(book, 'spread', 'away', away, str(-Decimal(line)))]
    return rows


class DatabaseCatalogTests(unittest.TestCase):
    def test_board_builds_real_tools(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        self.assertEqual('database', catalog.data_mode)
        self.assertTrue(catalog.snapshot_id.startswith('database:'))
        self.assertEqual(1, len(catalog.games))
        self.assertEqual('basketball_nba', catalog.games[0].sport_key)
        self.assertEqual('Bears at Hawks', catalog.games[0].name)
        kinds = {r.kind for r in catalog.rows}
        self.assertIn('arbitrage', kinds)  # 2.20 draftkings home vs 2.10 pinnacle away
        self.assertIn('low_hold', kinds)
        self.assertIn('positive_ev', kinds)
        self.assertTrue(all(x.evidence_kind == 'retained_provider_quote' for x in catalog.quotes))
        self.assertEqual(NOW - timedelta(seconds=60), catalog.captured_at)

    def test_every_supported_book_is_a_target(self):
        rows = board() + [q('fanduel', 'moneyline', 'home', '2.30'), q('fanduel', 'moneyline', 'away', '1.90')]
        raw = build_raw(rows, PEOPLE, now=NOW)
        self.assertEqual(['draftkings', 'fanduel', 'pinnacle', 'prophetx'], raw['target_books'])
        catalog = FixtureCatalog(raw=raw)
        ev_books = {b for r in catalog.rows if r.kind == 'positive_ev' for b in r.sportsbook_ids}
        self.assertIn('fanduel', ev_books)
        self.assertEqual(['draftkings'], build_raw(rows, PEOPLE, now=NOW, targets=('draftkings',))['target_books'])

    def test_ev_requires_every_reference_book(self):
        rows = [r for r in board() if r['book_code'] != 'prophetx']
        catalog = FixtureCatalog(raw=build_raw(rows, PEOPLE, now=NOW))
        self.assertNotIn('positive_ev', {r.kind for r in catalog.rows})

    def test_incomplete_books_and_unsupported_lines_are_skipped(self):
        rows = [r for r in board() if not (r['book_code'] == 'draftkings' and r['side'] == 'away' and r['market_code'] == 'moneyline')]
        rows += [q('pinnacle', 'spread', 'home', '1.9', '-2.25'), q('pinnacle', 'spread', 'away', '1.9', '2.25')]
        catalog = FixtureCatalog(raw=build_raw(rows, PEOPLE, now=NOW))
        h2h = [x for x in catalog.quotes if x.market_key == 'h2h']
        self.assertNotIn('draftkings', {x.sportsbook_id for x in h2h})
        self.assertFalse([x for x in catalog.quotes if x.point == '-2.25'])

    def test_middle_between_lines(self):
        rows = [q('draftkings', 'total', 'over', '1.91', '218.5'), q('draftkings', 'total', 'under', '1.91', '218.5'),
                q('pinnacle', 'total', 'over', '1.91', '224.5'), q('pinnacle', 'total', 'under', '1.91', '224.5')]
        catalog = FixtureCatalog(raw=build_raw(rows, PEOPLE, now=NOW))
        self.assertIn('middle', {r.kind for r in catalog.rows})

    def test_unknown_event_participants_are_skipped(self):
        catalog = FixtureCatalog(raw=build_raw(board(), [], now=NOW))
        self.assertEqual((), catalog.games)
        self.assertEqual((), catalog.rows)

    def test_three_way_requires_draw_on_every_book(self):
        rows = []
        for book in ('draftkings', 'pinnacle'):
            rows += [q(book, 'moneyline', 'home', '2.5'), q(book, 'moneyline', 'away', '3.1')]
        rows.append(q('pinnacle', 'moneyline', 'draw', '3.4'))
        catalog = FixtureCatalog(raw=build_raw(rows, PEOPLE, now=NOW))
        self.assertEqual({'pinnacle'}, {x.sportsbook_id for x in catalog.quotes})

    def test_arbitrage_profit_is_not_floored_to_zero(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        moneyline = [r for r in catalog.rows if r.kind == 'arbitrage' and r.market_key == 'h2h']
        self.assertTrue(moneyline)
        self.assertTrue(all(Decimal(r.minimum_profit) > 0 for r in moneyline))

    def test_whole_number_line_keeps_refund_floor(self):
        rows = [q('draftkings', 'spread', 'home', '2.20', '-3'), q('draftkings', 'spread', 'away', '1.70', '3'),
                q('pinnacle', 'spread', 'home', '1.70', '-3'), q('pinnacle', 'spread', 'away', '2.20', '3')]
        raw = build_raw(rows, PEOPLE, now=NOW)
        self.assertTrue(all(c['refund_possible'] for c in raw['contracts']))
        catalog = FixtureCatalog(raw=raw)
        arbs = [r for r in catalog.rows if r.kind == 'arbitrage']
        self.assertTrue(arbs)
        self.assertTrue(all(Decimal(r.minimum_profit) == 0 for r in arbs))

    def test_pulled_lines_do_not_survive_a_newer_capture(self):
        old, new = 'payload-old', 'payload-new'
        earlier = [dict(r, provider_payload_id=old, observed_at=NOW - timedelta(minutes=40)) for r in board()]
        # The newer capture still has DraftKings' moneyline but no longer carries its spread or total.
        newer = [dict(r, provider_payload_id=new, observed_at=NOW - timedelta(minutes=2))
                 for r in board() if not (r['book_code'] == 'draftkings' and r['market_code'] != 'moneyline')]
        kept = keep_latest_capture(earlier + newer)
        self.assertTrue(all(r['provider_payload_id'] == new for r in kept))
        self.assertEqual(len(newer), len(kept))
        self.assertFalse([r for r in kept if r['book_code'] == 'draftkings' and r['market_code'] != 'moneyline'])

    def test_each_game_uses_its_own_newest_capture(self):
        other = '22222222-2222-2222-2222-222222222222'
        a_old = [dict(r, provider_payload_id='p1', observed_at=NOW - timedelta(hours=1)) for r in board()]
        b_new = [dict(r, event_id=other, provider_payload_id='p2', observed_at=NOW - timedelta(minutes=1))
                 for r in board()]
        kept = keep_latest_capture(a_old + b_new)
        # A newer capture of another game must not discard this game's only prices.
        self.assertEqual({EVENT: 'p1', other: 'p2'}, {str(r['event_id']): r['provider_payload_id'] for r in kept})

    def test_rows_without_a_payload_id_are_left_alone(self):
        rows = board()
        self.assertEqual(len(rows), len(keep_latest_capture(rows)))
        self.assertEqual([], keep_latest_capture([]))

    def test_api_serves_database_mode(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        client = TestClient(create_app(data_mode='database', catalog=catalog))
        res = client.get('/api/v1/tools/arbitrage', headers={'host': '127.0.0.1'})
        self.assertEqual(200, res.status_code, res.text)
        self.assertEqual('database', res.json()['meta']['data_mode'])
        self.assertEqual('database', res.headers['x-corner-data-mode'])
        self.assertIn('availability_unverified', res.json()['meta']['warnings'])
        self.assertTrue(res.json()['data']['items'])
        with self.assertRaises(ValueError):
            create_app(data_mode='database')
        with self.assertRaises(ValueError):
            create_app(data_mode='fixture', catalog=catalog)

    def test_quotes_carry_validated_links_per_selection(self):
        rows = board()
        for row in rows:
            if row['book_code'] == 'draftkings' and row['market_code'] == 'moneyline':
                row['event_url'] = 'https://sportsbook.draftkings.com/event/1'
                row['outcome_url'] = f"https://sportsbook.draftkings.com/?outcomes={row['side']}"
            if row['book_code'] == 'pinnacle' and row['market_code'] == 'moneyline' and row['side'] == 'home':
                row['outcome_url'] = 'https://evil.example/steal'  # a link outside the sportsbook's own domain is dropped
        catalog = FixtureCatalog(raw=build_raw(rows, PEOPLE, now=NOW))
        by = {(x.sportsbook_id, x.market_key, x.side): x for x in catalog.quotes if x.contract_id.endswith(':h2h')}
        home, away = by[('draftkings', 'h2h', 'home')], by[('draftkings', 'h2h', 'away')]
        self.assertEqual(home.links.outcome, 'https://sportsbook.draftkings.com/?outcomes=home')
        self.assertEqual(away.links.outcome, 'https://sportsbook.draftkings.com/?outcomes=away')
        self.assertEqual(home.links.event, 'https://sportsbook.draftkings.com/event/1')
        self.assertIsNone(home.links.market)
        self.assertIsNone(by[('pinnacle', 'h2h', 'home')].links)
        self.assertIsNone(by[('prophetx', 'h2h', 'home')].links)
        client = TestClient(create_app(data_mode='database', catalog=catalog))
        game = catalog.games[0].id
        quotes = client.get(f'/api/v1/games/{game}/odds', params={'limit': 100}, headers={'host': '127.0.0.1'}).json()['data']['items']
        linked = [x for x in quotes if x['links']]
        self.assertTrue(linked)
        self.assertEqual(set(linked[0]['links']), {'event', 'market', 'outcome'})
    def test_live_catalog_keeps_last_good_snapshot_on_failure(self):
        calls = []

        class Conn:
            def set_session(self, **kw): pass
            def close(self): pass

        def connect():
            calls.append(1)
            if len(calls) > 1:
                raise RuntimeError('db down')
            return Conn()

        import api.database as db
        original = db.load_raw
        db.load_raw = lambda conn, **kw: build_raw(board(), PEOPLE, now=NOW)
        try:
            live = LiveCatalog(connect, ttl_seconds=-1, max_age_seconds=1800)
            first = live.snapshot_id
            self.assertEqual(first, live.snapshot_id)
            self.assertGreater(len(calls), 1)
        finally:
            db.load_raw = original


if __name__ == '__main__':
    unittest.main()
