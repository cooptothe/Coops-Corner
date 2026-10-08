"""Tracker store tests: money exactness, settlement rules, idempotency, validation. No network."""
import sqlite3
import tempfile
import unittest

from corner import tracker_store as ts


def bet(**over):
    base = {'client_key': 'k1', 'strategy': 'ev', 'matchup': 'A at B', 'selection': 'B -3.5', 'book': 'DraftKings',
            'odds': '1.91', 'stake': '100', 'sport_key': 'basketball_nba'}
    base.update(over)
    return base


class Store(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = ts.TrackerStore(f'{tmp.name}/t.sqlite3')
        self.addCleanup(self.db.close)
        self.store = self.db.ledger(self.db.create_user('Ann', 'ann', 'hash')['id'])

    def add(self, **over):
        return self.store.add_bets([bet(**over)])[0]

    def test_money_is_exact_cents_and_rejects_float_noise(self):
        self.assertEqual(ts.to_cents('19.99'), 1999)
        self.assertEqual(ts.to_cents('0.30'), 30)
        for bad in ('1.005', '-5', '0', 'abc', '', True, '1e3', 'NaN'):
            with self.assertRaises(ts.TrackerError, msg=repr(bad)):
                ts.to_cents(bad)
        self.assertEqual(ts.to_cents('-12.50', signed=True), -1250)

    def test_odds_are_validated_and_normalized(self):
        self.assertEqual(ts.parse_odds('2.0'), '2')
        self.assertEqual(ts.parse_odds('1.909091'), '1.909091')
        for bad in ('1', '0.5', '1001', 'x', '-2'):
            with self.assertRaises(ts.TrackerError):
                ts.parse_odds(bad)

    def test_payouts_by_result_for_cash_and_bonus_stakes(self):
        self.assertEqual(ts.payout_cents(10000, '1.91', 'cash', 'won'), 19100)
        self.assertEqual(ts.payout_cents(10000, '1.91', 'cash', 'lost'), 0)
        self.assertEqual(ts.payout_cents(10000, '1.91', 'cash', 'push'), 10000)
        self.assertEqual(ts.payout_cents(10000, '1.91', 'cash', 'void'), 10000)
        # A bonus bet pays winnings only and costs nothing when it loses or voids.
        self.assertEqual(ts.payout_cents(10000, '4', 'bonus', 'won'), 30000)
        for result in ('lost', 'push', 'void'):
            self.assertEqual(ts.payout_cents(10000, '4', 'bonus', result), 0)
        # Site credit pays out the credit as well on a win, and returns no cash otherwise.
        self.assertEqual(ts.payout_cents(10000, '4', 'credit', 'won'), 40000)
        for result in ('lost', 'push', 'void'):
            self.assertEqual(ts.payout_cents(10000, '4', 'credit', result), 0)
        self.assertEqual(ts.payout_cents(10000, '2', 'cash', 'cashout', cashout_cents=6500), 6500)
        with self.assertRaises(ts.TrackerError):
            ts.payout_cents(10000, '2', 'cash', 'cashout')

    def test_rounding_is_half_up_to_the_cent(self):
        self.assertEqual(ts.payout_cents(333, '1.5', 'cash', 'won'), 500)   # 499.5 -> 500
        self.assertEqual(ts.payout_cents(1, '1.5', 'cash', 'won'), 2)       # 1.5 -> 2

    def test_profit_is_returned_minus_cash_outlay(self):
        won = self.add(client_key='w')
        self.assertIsNone(ts.profit_cents(won))
        settled = self.store.settle_bet(won['id'], 'won')
        self.assertEqual(ts.profit_cents(settled), 9100)
        free = self.add(client_key='f', stake_type='bonus', odds='4')
        self.assertEqual(ts.profit_cents(self.store.settle_bet(free['id'], 'won')), 30000)
        self.assertEqual(ts.profit_cents(self.store.settle_bet(free['id'], 'lost')), 0)

    def test_adding_is_idempotent_and_atomic(self):
        first = self.add()
        again = self.add(stake='999')  # same client key: the stored bet wins, nothing is duplicated
        self.assertEqual((again['id'], again['stake_cents']), (first['id'], 10000))
        self.assertEqual(len(self.store.state()['bets']), 1)
        legs = [bet(client_key='a1', group_id='g'), bet(client_key='a2', group_id='g', stake='bad')]
        with self.assertRaises(ts.TrackerError):
            self.store.add_bets(legs)
        self.assertEqual(len(self.store.state()['bets']), 1)  # the good leg was not kept
        saved = self.store.add_bets([bet(client_key='b1', group_id='g'), bet(client_key='b2', group_id='g')])
        self.assertEqual({b['group_id'] for b in saved}, {'g'})

    def test_book_names_become_codes_and_bad_input_is_refused(self):
        self.assertEqual(self.add(client_key='x', book='theScore Bet')['book'], 'thescore_bet')
        for over in ({'strategy': 'lucky'}, {'matchup': ''}, {'selection': ' '}, {'book': '!!'}, {'stake_type': 'gift'},
                     {'placed_at': '2099-01-01T00:00:00Z'}, {'placed_at': 'yesterday'}):
            with self.assertRaises(ts.TrackerError, msg=str(over)):
                self.store.add_bets([bet(client_key='bad', **over)])
        with self.assertRaises(ts.TrackerError):
            self.store.add_bets([])

    def test_editing_recalculates_a_settled_payout(self):
        b = self.add()
        self.store.settle_bet(b['id'], 'won')
        edited = self.store.update_bet(b['id'], {'odds': '2.5', 'stake': '50'})
        self.assertEqual((edited['stake_cents'], edited['returned_cents'], edited['status']), (5000, 12500, 'won'))
        with self.assertRaises(ts.TrackerError):
            self.store.update_bet(b['id'], {})
        with self.assertRaises(ts.TrackerError):
            self.store.update_bet(b['id'], {'odds': '0.9'})
        self.assertEqual(self.store.bet(b['id'])['odds'], '2.5')  # a refused edit changes nothing

    def test_settle_reopen_delete_and_missing_ids(self):
        b = self.add()
        self.assertEqual(self.store.settle_bet(b['id'], 'push')['returned_cents'], 10000)
        self.assertEqual(self.store.settle_bet(b['id'], 'cashout', returned='72.5')['returned_cents'], 7250)
        reopened = self.store.reopen_bet(b['id'])
        self.assertEqual((reopened['status'], reopened['returned_cents'], reopened['settled_at']), ('pending', None, None))
        self.store.delete_bet(b['id'])
        for call in (lambda: self.store.bet(b['id']), lambda: self.store.settle_bet(b['id'], 'won'),
                     lambda: self.store.delete_bet(b['id'])):
            with self.assertRaises(ts.TrackerError) as ctx:
                call()
            self.assertEqual(ctx.exception.status, 404)

    def test_settled_time_cannot_precede_placement(self):
        b = self.add(placed_at='2026-01-02T12:00:00+00:00')
        out = self.store.settle_bet(b['id'], 'won', settled_at='2026-01-01T00:00:00+00:00')
        self.assertGreaterEqual(out['settled_at'], out['placed_at'])

    def test_cash_entries(self):
        d = self.store.add_cash({'client_key': 'c1', 'kind': 'deposit', 'book': 'fanduel', 'amount': '500'})
        self.assertEqual((d['amount_cents'], d['book']), (50000, 'fanduel'))
        self.assertEqual(self.store.add_cash({'client_key': 'c1', 'kind': 'deposit', 'book': 'fanduel', 'amount': '9'})['id'], d['id'])
        t = self.store.add_cash({'client_key': 'c2', 'kind': 'transfer', 'book': 'vault', 'to_book': 'fanduel', 'amount': '100'})
        self.assertEqual(t['to_book'], 'fanduel')
        a = self.store.add_cash({'client_key': 'c3', 'kind': 'adjustment', 'book': 'fanduel', 'amount': '-12.34'})
        self.assertEqual(a['amount_cents'], -1234)
        for bad in ({'kind': 'transfer', 'book': 'a', 'to_book': 'a', 'amount': '5'},
                    {'kind': 'transfer', 'book': 'a', 'amount': '5'},
                    {'kind': 'deposit', 'book': 'a', 'amount': '-5'},
                    {'kind': 'bonus', 'book': 'a', 'amount': '5'},
                    {'kind': 'adjustment', 'book': 'a', 'amount': '0'},
                    {'kind': 'deposit', 'book': 'a', 'amount': '5', 'occurred_at': '2099-01-01'}):
            with self.assertRaises(ts.TrackerError, msg=str(bad)):
                self.store.add_cash({'client_key': 'bad', **bad})
        self.store.delete_cash(d['id'])
        self.assertEqual(len(self.store.state()['cash']), 2)

    def test_ref_metadata_is_limited_to_plain_values(self):
        ok = self.add(client_key='r', ref={'game_id': 'abc', 'point': -3.5, 'side': 'home'})
        self.assertEqual(ok['ref']['point'], -3.5)
        for bad in ({'Nested': {'a': 1}}, {'ok': {'a': 1}}, {'k': 'x' * 300}, 'text'):
            with self.assertRaises(ts.TrackerError):
                self.add(client_key='bad', ref=bad)

    def test_state_survives_reopening_the_file(self):
        self.add()
        path = self.db.path
        user = self.store.user_id
        self.db.close()
        reopened = ts.TrackerStore(path)
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.ledger(user).state()['bets']), 1)
        self.db = reopened


class Accounts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = f'{tmp.name}/t.sqlite3'
        self.db = ts.TrackerStore(self.path)
        self.addCleanup(self.db.close)
        self.ann = self.db.ledger(self.db.create_user('Ann', 'ann', 'h1')['id'])
        self.bob = self.db.ledger(self.db.create_user('Bob', 'bob', 'h2')['id'])

    def test_usernames_are_unique_ignoring_case(self):
        with self.assertRaises(ts.TrackerError) as raised:
            self.db.create_user('ANN', 'ann', 'x')
        self.assertEqual((raised.exception.status, raised.exception.code), (409, 'username_taken'))
        self.assertEqual(self.db.user_by_key('ann')['username'], 'Ann')
        self.assertIsNone(self.db.user_by_key('carol'))

    def test_a_user_sees_and_changes_only_their_own_rows(self):
        mine = self.ann.add_bets([bet(client_key='same')])[0]
        theirs = self.bob.add_bets([bet(client_key='same', selection='Bob only')])[0]
        self.assertNotEqual(mine['id'], theirs['id'])  # the same client key is fine across users
        self.assertEqual([b['id'] for b in self.ann.state()['bets']], [mine['id']])
        self.assertNotIn('user_id', mine)
        for attempt in (lambda: self.bob.bet(mine['id']), lambda: self.bob.settle_bet(mine['id'], 'won'),
                        lambda: self.bob.reopen_bet(mine['id']), lambda: self.bob.delete_bet(mine['id']),
                        lambda: self.bob.update_bet(mine['id'], {'odds': '3'})):
            with self.assertRaises(ts.TrackerError) as raised:
                attempt()
            self.assertEqual(raised.exception.status, 404)
        self.bob.set_clv(mine['id'], {'pct': '0.5'})
        self.assertEqual(self.ann.bet(mine['id'])['status'], 'pending')
        self.assertIsNone(self.ann.bet(mine['id'])['clv'])

    def test_cash_is_private_too(self):
        entry = self.ann.add_cash({'client_key': 'c', 'kind': 'deposit', 'book': 'fanduel', 'amount': '50'})
        self.assertEqual(self.bob.state()['cash'], [])
        with self.assertRaises(ts.TrackerError):
            self.bob.delete_cash(entry['id'])
        self.assertEqual(len(self.ann.state()['cash']), 1)
        other = self.bob.add_cash({'client_key': 'c', 'kind': 'deposit', 'book': 'fanduel', 'amount': '7'})
        self.assertNotEqual(other['id'], entry['id'])

    def test_a_ledger_needs_a_user_and_a_real_one(self):
        with self.assertRaises(ValueError):
            self.db.ledger('')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.ledger('no-such-user').add_bets([bet()])


class Upgrade(unittest.TestCase):
    OLD = """
    CREATE TABLE bets (id TEXT PRIMARY KEY, client_key TEXT NOT NULL UNIQUE, group_id TEXT, created_at TEXT NOT NULL,
      placed_at TEXT NOT NULL, strategy TEXT NOT NULL, sport_key TEXT NOT NULL DEFAULT '', matchup TEXT NOT NULL,
      starts_at TEXT, market TEXT NOT NULL DEFAULT '', selection TEXT NOT NULL, book TEXT NOT NULL, odds TEXT NOT NULL,
      stake_cents INTEGER NOT NULL, stake_type TEXT NOT NULL DEFAULT 'cash', status TEXT NOT NULL DEFAULT 'pending',
      returned_cents INTEGER, settled_at TEXT, fair_prob TEXT, ev_ratio TEXT, ref TEXT NOT NULL DEFAULT '{}', clv TEXT,
      notes TEXT NOT NULL DEFAULT '');
    CREATE INDEX bets_placed ON bets(placed_at);
    CREATE INDEX bets_status ON bets(status);
    CREATE TABLE cash (id TEXT PRIMARY KEY, client_key TEXT NOT NULL UNIQUE, occurred_at TEXT NOT NULL, kind TEXT NOT NULL,
      amount_cents INTEGER NOT NULL, book TEXT NOT NULL, to_book TEXT, note TEXT NOT NULL DEFAULT '');
    CREATE INDEX cash_when ON cash(occurred_at);
    INSERT INTO bets(id,client_key,created_at,placed_at,strategy,matchup,selection,book,odds,stake_cents)
      VALUES('b1','old-1','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','manual','A at B','A','fanduel','2',1000);
    INSERT INTO cash(id,client_key,occurred_at,kind,amount_cents,book) VALUES('c1','old-c','2026-01-01T00:00:00+00:00','deposit',5000,'fanduel');
    """

    def test_existing_single_user_data_goes_to_the_first_account_only(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = f'{tmp.name}/t.sqlite3'
        raw = sqlite3.connect(path)
        raw.executescript(self.OLD)
        raw.close()
        db = ts.TrackerStore(path)
        self.addCleanup(db.close)
        # Nobody owns the old rows yet, so no account can see them.
        stranger = db.ledger(db.create_user('First', 'first', 'h')['id'])
        self.assertEqual([b['id'] for b in stranger.state()['bets']], ['b1'])
        self.assertEqual(len(stranger.state()['cash']), 1)
        second = db.ledger(db.create_user('Second', 'second', 'h')['id'])
        self.assertEqual(second.state(), {'bets': [], 'cash': []})
        # The upgraded table keeps working, with keys unique per user.
        self.assertEqual(second.add_bets([bet(client_key='old-1')])[0]['client_key'], 'old-1')
        reopened = ts.TrackerStore(path)
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.ledger(stranger.user_id).state()['bets']), 1)
        check = sqlite3.connect(path)
        self.addCleanup(check.close)
        tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('bets_old', tables)

if __name__ == '__main__':
    unittest.main()
