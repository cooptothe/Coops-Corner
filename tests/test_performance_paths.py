"""The speed-ups must never change an answer: each is checked against the plain computation it replaces."""
import itertools
import random
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

import api.catalog as catalog_module
import api.database as db
from api.app import create_app
from api.catalog import FixtureCatalog, _middles_for, paginate
from api.database import LiveCatalog, build_raw
from api.models import ToolQuery
from corner.featured_middles import LineBet, find_middles
from corner.featured_tools import ToolInputError
from tests.test_database_catalog import NOW, PEOPLE, board, q

D = Decimal
CONTRACT = 'event:totals:rules'


def bet(n, book, side, line, odds='1.91', market='totals', contract=CONTRACT):
    return LineBet(f'q{n:03d}', book, contract, market, side, D(line), D(odds), D(100), D(0))


def plain(bets, refund=True):
    return find_middles(bets, refund_possible=refund)


class MiddleFilterTests(unittest.TestCase):
    def setUp(self):
        catalog_module._MIDDLES.clear()
        catalog_module._WINDOWS.clear()

    def test_same_result_as_the_full_search_on_random_boards(self):
        rng = random.Random(7)
        for _ in range(60):
            bets, n = [], 0
            for book in ('a', 'b', 'c', 'd'):
                for side in ('over', 'under'):
                    if rng.random() < 0.8:
                        n += 1
                        bets.append(bet(n, book, side, str(rng.choice([212, 212.5, 213, 213.5, 214.25, 215]))))
            refund = rng.random() < 0.5
            self.assertEqual(plain(bets, refund), _middles_for(bets, refund))
            self.assertEqual(plain(bets, refund), _middles_for(bets, refund))  # and again, from the memo

    def test_spreads_with_quarter_lines_match(self):
        rng = random.Random(11)
        for _ in range(40):
            bets, n = [], 0
            for book in ('a', 'b', 'c'):
                line = rng.choice([-7, -6.5, -6.25, -5.5, -3, -2.75])
                for side, sign in (('home', 1), ('away', -1)):
                    n += 1
                    bets.append(bet(n, book, side, str(line * sign), market='spreads', contract='event:spreads:rules'))
            self.assertEqual(plain(bets, False), _middles_for(bets, False))

    def test_a_pair_in_one_book_is_never_a_middle(self):
        bets = [bet(1, 'a', 'over', '210'), bet(2, 'a', 'under', '215')]
        self.assertEqual((), _middles_for(bets, True))

    def test_an_oversized_game_still_fails_as_before(self):
        bets = [bet(i, f'book{i}', 'over' if i % 2 else 'under', '212') for i in range(1, 260)]
        with self.assertRaises(ToolInputError):
            plain(bets)
        with self.assertRaises(ToolInputError):
            _middles_for(bets, True)

    def test_window_answers_are_remembered_by_line_not_odds(self):
        first = [bet(1, 'a', 'over', '212'), bet(2, 'b', 'under', '215')]
        _middles_for(first, True)
        known = len(catalog_module._WINDOWS)
        second = [bet(3, 'c', 'over', '212', odds='1.50'), bet(4, 'd', 'under', '215', odds='3.10')]
        _middles_for(second, True)
        self.assertEqual(known, len(catalog_module._WINDOWS))


class Cursor:
    """Answers the fingerprint statements, and counts how often the heavy quote query runs."""
    def __init__(self, conn):
        self.conn, self.last = conn, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.last = sql
        if sql == db.QUOTE_SQL:
            self.conn.quote_runs += 1
        elif sql in db.FINGERPRINT_SQL:
            if self.conn.broken:
                raise RuntimeError('no access')
        elif sql == db.PARTICIPANT_SQL:
            self.conn.participant_runs += 1

    def fetchone(self):
        return (self.conn.version, None)

    def fetchall(self):
        if self.last == db.QUOTE_SQL:
            return self.conn.rows
        return [dict(event_id=e, role=r, display_name=n) for e, r, n in PEOPLE]


class Conn:
    def __init__(self, rows, version=1, broken=False):
        self.rows, self.version, self.broken = rows, version, broken
        self.quote_runs = self.participant_runs = self.rollbacks = 0

    def cursor(self, **kw):
        return Cursor(self)

    def rollback(self):
        self.rollbacks += 1


def read(conn, cache, now=NOW):
    return db.read_source(conn, now=now, max_age=timedelta(hours=1), cache=cache)


class SourceCacheTests(unittest.TestCase):
    def test_an_unchanged_database_is_not_read_again(self):
        conn, cache = Conn(board()), {}
        first = read(conn, cache)
        again = read(conn, cache)
        self.assertEqual(1, conn.quote_runs)
        self.assertEqual(first, again)

    def test_a_changed_fingerprint_reads_again(self):
        conn, cache = Conn(board()), {}
        read(conn, cache)
        conn.version = 2
        read(conn, cache)
        self.assertEqual(2, conn.quote_runs)

    def test_started_games_and_stale_quotes_drop_out_of_the_cached_rows(self):
        conn, cache = Conn(board()), {}
        read(conn, cache)
        start = board()[0]['scheduled_start']
        rows, _ = read(conn, cache, now=start + timedelta(minutes=1))
        self.assertEqual([], rows)
        rows, _ = read(conn, cache, now=NOW + timedelta(hours=2))  # every quote is now older than the max age
        self.assertEqual([], rows)
        self.assertEqual(1, conn.quote_runs)

    def test_cached_rows_match_a_fresh_read_at_the_later_time(self):
        later = NOW + timedelta(minutes=30)
        cached_conn, cache = Conn(board()), {}
        read(cached_conn, cache)
        from_cache, _ = read(cached_conn, cache, now=later)
        self.assertEqual(1, cached_conn.quote_runs)
        expected = [r for r in board() if r['scheduled_start'] > later and r['observed_at'] >= later - timedelta(hours=1)]
        self.assertEqual(expected, from_cache)

    def test_an_unreadable_fingerprint_means_no_caching(self):
        conn, cache = Conn(board(), broken=True), {}
        read(conn, cache)
        read(conn, cache)
        self.assertEqual(2, conn.quote_runs)
        self.assertGreaterEqual(conn.rollbacks, 1)

    def test_without_a_cache_it_always_reads(self):
        conn = Conn(board())
        db.read_source(conn, now=NOW, max_age=timedelta(hours=1))
        db.read_source(conn, now=NOW, max_age=timedelta(hours=1))
        self.assertEqual(2, conn.quote_runs)

    def test_old_cache_is_not_trusted(self):
        conn, cache = Conn(board()), {}
        read(conn, cache)
        cache['at'] -= db.SOURCE_MAX_AGE_SECONDS + 1
        read(conn, cache)
        self.assertEqual(2, conn.quote_runs)


class LiveCatalogReuseTests(unittest.TestCase):
    def live(self, rows):
        original = db.load_raw
        self.addCleanup(setattr, db, 'load_raw', original)
        state = {'rows': rows}
        db.load_raw = lambda conn, **kw: build_raw(state['rows'], PEOPLE, now=NOW)

        class C:
            def set_session(self, **kw): pass
            def close(self): pass

        return LiveCatalog(lambda: C(), max_age_seconds=1800), state

    def test_identical_input_keeps_the_same_catalog(self):
        live, _ = self.live(board())
        inner, snapshot = live._inner, live.snapshot_id
        live.reload()
        self.assertIs(inner, live._inner)
        self.assertEqual(snapshot, live.snapshot_id)

    def test_changed_input_builds_a_new_catalog(self):
        live, state = self.live(board())
        inner, snapshot = live._inner, live.snapshot_id
        state['rows'] = board() + [q('fanduel', 'moneyline', 'home', '2.30'), q('fanduel', 'moneyline', 'away', '1.90')]
        live.reload()
        self.assertIsNot(inner, live._inner)
        self.assertNotEqual(snapshot, live.snapshot_id)


class PagingTests(unittest.TestCase):
    def test_a_memoized_page_equals_the_plain_page(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        rows = [r for r in catalog.rows if r.kind == 'positive_ev']
        for descending in (True, False):
            for offset in (0, 1):
                query = ToolQuery(limit=2, offset=offset, sort='conditional_ev_ratio', descending=descending)
                plain_page = paginate(rows, query, ('conditional_ev_ratio',))
                memo = {}
                built = []
                memoized = paginate(lambda: built.append(1) or rows, query, ('conditional_ev_ratio',), memo=memo, memo_key='k')
                again = paginate(lambda: built.append(1) or rows, query, ('conditional_ev_ratio',), memo=memo, memo_key='k')
                self.assertEqual(plain_page, memoized)
                self.assertEqual(plain_page, again)
                self.assertEqual(1, len(built))

    def test_every_page_through_the_api_is_the_same_with_the_memo(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        client = TestClient(create_app(data_mode='database', catalog=catalog))
        headers = {'host': '127.0.0.1'}

        def pages(kind):
            out, offset = [], 0
            while offset is not None:
                body = client.get(f'/api/v1/tools/{kind}', params={'limit': 2, 'offset': offset}, headers=headers).json()['data']
                out += [i['id'] for i in body['items']]
                offset = body['next_offset']
            return out

        for kind in ('positive_ev', 'arbitrage', 'low_hold', 'middle'):
            catalog.memo.clear()
            cold = pages(kind)
            self.assertTrue(catalog.memo)
            self.assertEqual(cold, pages(kind))  # now served from the memo
            self.assertEqual(len(cold), len(set(cold)))
        self.assertTrue(pages('positive_ev'))

    def test_bulk_quotes_equal_the_per_game_quotes(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        client = TestClient(create_app(data_mode='database', catalog=catalog))
        headers = {'host': '127.0.0.1'}
        bulk, offset = [], 0
        while offset is not None:
            body = client.get('/api/v1/quotes', params={'limit': 7, 'offset': offset, 'snapshot_id': catalog.snapshot_id},
                              headers=headers).json()['data']
            self.assertEqual(len(catalog.quotes), body['total'])
            bulk += body['items']
            offset = body['next_offset']
        per_game = []
        for game in catalog.games:
            per_game += client.get(f'/api/v1/games/{game.id}/odds', params={'limit': 100}, headers=headers).json()['data']['items']
        self.assertEqual(sorted(per_game, key=lambda x: x['id']), sorted(bulk, key=lambda x: x['id']))
        self.assertEqual(len(bulk), len({x['id'] for x in bulk}))

    def test_bulk_quotes_limits_and_snapshot_check(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        client = TestClient(create_app(data_mode='database', catalog=catalog))
        headers = {'host': '127.0.0.1'}
        self.assertEqual(200, client.get('/api/v1/quotes', params={'limit': 1000, 'offset': 20000}, headers=headers).status_code)
        self.assertEqual(422, client.get('/api/v1/quotes', params={'limit': 1001}, headers=headers).status_code)
        self.assertEqual(422, client.get('/api/v1/quotes', params={'offset': 100001}, headers=headers).status_code)
        self.assertEqual(409, client.get('/api/v1/quotes', params={'snapshot_id': 'database:other'}, headers=headers).status_code)
        # the per-game route keeps its original bounds
        game = catalog.games[0].id
        self.assertEqual(422, client.get(f'/api/v1/games/{game}/odds', params={'limit': 101}, headers=headers).status_code)

    def test_per_game_odds_use_the_index(self):
        catalog = FixtureCatalog(raw=build_raw(board(), PEOPLE, now=NOW))
        game = catalog.games[0]
        self.assertEqual(game.quote_count, len(catalog.quotes_by_game[game.id]))
        self.assertEqual(sorted(q_.id for q_ in catalog.quotes), sorted(q_.id for q_ in itertools.chain(*catalog.quotes_by_game.values())))


if __name__ == '__main__':
    unittest.main()


class SnapshotConcurrencyTests(unittest.TestCase):
    def test_concurrent_readers_build_once_and_nested_cache_is_reentrant(self):
        from api.catalog import SnapshotMemo
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import time
        memo=SnapshotMemo(); calls=[]; start=threading.Barrier(12)
        def build():
            calls.append(1);time.sleep(.01)
            return memo.get_or_create('nested',lambda:('same snapshot',))
        def read(_):
            start.wait()
            return memo.get_or_create('page',build)
        with ThreadPoolExecutor(max_workers=12) as pool:
            values=list(pool.map(read,range(12)))
        self.assertEqual(len(calls),1)
        self.assertTrue(all(value is values[0] for value in values))
        for key in range(300):memo.get_or_create(key,lambda:key)
        self.assertLessEqual(len(memo),256)
