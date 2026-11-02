"""Local betting ledger: bets and cash movements in SQLite.

Money is integer cents, odds are exact decimals, and nothing here talks to the network. Wallet
balances and bankroll history are never stored: they are derived from these rows, so editing or
deleting a record cannot leave a second copy of the truth behind.

A bet's cash effect: a cash stake leaves the book's balance when the bet is placed and the
returned amount arrives when it settles. A bonus (free) bet never touches the balance at
placement, and a win returns only the winnings.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from corner import tool_settings
from corner.parlay_tracker import prepare_legs, suggested_result, LEG_RESULTS
STRATEGIES = ('ev', 'arbitrage', 'middle', 'promo', 'prop', 'manual', 'parlay')
STATUSES = ('pending', 'won', 'lost', 'push', 'void', 'cashout')
RESULTS = ('won', 'lost', 'push', 'void', 'cashout')
CASH_KINDS = ('deposit', 'withdrawal', 'transfer', 'adjustment')
STAKE_TYPES = ('cash', 'bonus', 'credit')
VAULT = 'vault'
MAX_CENTS = 100_000_000_00
BOOK = re.compile(r'^[a-z0-9_]{1,40}$')
MAX_LEGS = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  username_key TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  session_epoch INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bets (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id),
  client_key TEXT NOT NULL,
  group_id TEXT,
  created_at TEXT NOT NULL,
  placed_at TEXT NOT NULL,
  strategy TEXT NOT NULL,
  sport_key TEXT NOT NULL DEFAULT '',
  matchup TEXT NOT NULL,
  starts_at TEXT,
  market TEXT NOT NULL DEFAULT '',
  selection TEXT NOT NULL,
  book TEXT NOT NULL,
  odds TEXT NOT NULL,
  stake_cents INTEGER NOT NULL,
  stake_type TEXT NOT NULL DEFAULT 'cash',
  status TEXT NOT NULL DEFAULT 'pending',
  returned_cents INTEGER,
  settled_at TEXT,
  fair_prob TEXT,
  ev_ratio TEXT,
  ref TEXT NOT NULL DEFAULT '{}',
  clv TEXT,
  notes TEXT NOT NULL DEFAULT '',
  parlay_legs TEXT NOT NULL DEFAULT '[]',
  UNIQUE (user_id, client_key)
);
CREATE INDEX IF NOT EXISTS bets_user_placed ON bets(user_id, placed_at);
CREATE INDEX IF NOT EXISTS bets_user_status ON bets(user_id, status);
CREATE TABLE IF NOT EXISTS cash (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id),
  client_key TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  book TEXT NOT NULL,
  to_book TEXT,
  note TEXT NOT NULL DEFAULT '',
  UNIQUE (user_id, client_key)
);
CREATE INDEX IF NOT EXISTS cash_user_when ON cash(user_id, occurred_at);
CREATE TABLE IF NOT EXISTS tool_settings (
  user_id TEXT NOT NULL REFERENCES users(id),
  tool TEXT NOT NULL,
  settings TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, tool)
);
CREATE TABLE IF NOT EXISTS presets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  tool TEXT NOT NULL,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL,
  settings TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, tool, name_key)
);
"""
BET_COLUMNS = ('id, client_key, group_id, created_at, placed_at, strategy, sport_key, matchup, starts_at, market, selection, '
               'book, odds, stake_cents, stake_type, status, returned_cents, settled_at, fair_prob, ev_ratio, ref, clv, notes')
CASH_COLUMNS = 'id, client_key, occurred_at, kind, amount_cents, book, to_book, note'


class TrackerError(ValueError):
    def __init__(self, message, status=400, code='invalid'):
        super().__init__(message)
        self.status, self.code = status, code


def _fail(message, status=400, code='invalid'):
    raise TrackerError(message, status, code)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def to_cents(value, label='amount', *, signed=False, allow_zero=False):
    """Dollars (string or number) -> integer cents. At most two decimals; no float rounding."""
    if isinstance(value, bool):
        _fail(f'{label}: a dollar amount is required')
    raw = str(value).strip()
    if not re.match(r'^-?\d{1,12}(\.\d{1,2})?$', raw):
        _fail(f'{label}: enter a dollar amount such as 25 or 25.50 (no more than two decimals)')
    amount = Decimal(raw)
    cents = int(amount * 100)
    if not signed and (cents < 0 or (cents == 0 and not allow_zero)):
        _fail(f'{label}: must be greater than zero')
    if abs(cents) > MAX_CENTS:
        _fail(f'{label}: too large')
    return cents


def parse_odds(value):
    raw = str(value).strip()
    if raw.startswith('+'):
        _fail('odds: send decimal odds such as 2.10, not American odds')
    try:
        odds = Decimal(raw)
    except (InvalidOperation, ValueError):
        _fail('odds: enter decimal odds greater than 1')
    if not odds.is_finite() or not Decimal(1) < odds <= Decimal(1000):
        _fail('odds: decimal odds must be above 1 and at most 1000')
    return format(odds.quantize(Decimal('0.000001'), ROUND_HALF_UP).normalize(), 'f')


def optional_ratio(value, label):
    if value in (None, ''):
        return None
    try:
        ratio = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        _fail(f'{label}: not a number')
    if not ratio.is_finite() or abs(ratio) > 100:
        _fail(f'{label}: out of range')
    return format(ratio.quantize(Decimal('0.000001')).normalize(), 'f')


def parse_when(value, label, *, default_now=False):
    if value in (None, ''):
        if default_now:
            return now_iso()
        return None
    try:
        when = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        _fail(f'{label}: not a valid date and time')
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat()


def text(value, label, *, required=False, limit=200):
    value = '' if value is None else str(value).strip()
    if required and not value:
        _fail(f'{label} is required')
    if len(value) > limit:
        _fail(f'{label}: at most {limit} characters')
    return value


def book_code(value, label='book'):
    code = re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')
    if not BOOK.match(code):
        _fail(f'{label}: choose a sportsbook')
    return code


def clean_ref(value):
    """Plain scalar metadata (game, side, line, quote ids) used for live grading and closing lines."""
    if value in (None, ''):
        return {}
    if not isinstance(value, dict) or len(value) > 24:
        _fail('ref: expected a small object')
    out = {}
    for key, item in value.items():
        if not isinstance(key, str) or not re.match(r'^[a-z_]{1,30}$', key):
            _fail('ref: invalid key')
        if item is not None and not isinstance(item, (str, int, float, bool)):
            _fail('ref: values must be plain text or numbers')
        if isinstance(item, str) and len(item) > 200:
            _fail('ref: value too long')
        out[key] = item
    return out


def payout_cents(stake_cents, odds, stake_type, result, *, cashout_cents=None):
    """Total cash that comes back to the book balance when a bet settles."""
    if result not in RESULTS:
        _fail('result: choose won, lost, push, void or cashout')
    if result == 'cashout':
        if cashout_cents is None:
            _fail('A cash-out needs the amount you were paid')
        return cashout_cents
    odds = Decimal(odds)
    if stake_type == 'bonus':
        # A bonus bet pays winnings only; the free stake itself is never returned.
        if result == 'won':
            return int((Decimal(stake_cents) * (odds - 1)).quantize(Decimal(1), ROUND_HALF_UP))
        return 0
    if stake_type == 'credit':
        # Site credit is paid out in full on a win (stake included); a loss or refund returns no cash.
        if result == 'won':
            return int((Decimal(stake_cents) * odds).quantize(Decimal(1), ROUND_HALF_UP))
        return 0
    if result == 'won':
        return int((Decimal(stake_cents) * odds).quantize(Decimal(1), ROUND_HALF_UP))
    if result == 'lost':
        return 0
    return stake_cents


def outlay_cents(bet):
    return bet['stake_cents'] if bet['stake_type'] == 'cash' else 0


def profit_cents(bet):
    """Realized profit of a settled bet; None while it is pending."""
    if bet['status'] == 'pending' or bet['returned_cents'] is None:
        return None
    return bet['returned_cents'] - outlay_cents(bet)


def _bet_row(row):
    bet = dict(row)
    bet.pop('user_id', None)
    bet['ref'] = json.loads(bet['ref'] or '{}')
    bet['clv'] = json.loads(bet['clv']) if bet['clv'] else None
    legs = json.loads(bet.pop('parlay_legs', '[]'))
    if legs:
        bet['legs'] = legs
        bet['suggested_result'] = suggested_result(legs)
    return bet


def read_user(path, user_id):
    """An account row through a read-only connection, for other processes that only need to check a session."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        db = sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=2)
    except sqlite3.Error:
        return None
    try:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT id, username, session_epoch FROM users WHERE id=?', (user_id,)).fetchone()
        from corner import beta_access
        return beta_access.decorate(db, dict(row) if row else None)
    except sqlite3.Error:
        return None
    finally:
        db.close()


def _cash_row(row):
    entry = dict(row)
    entry.pop('user_id', None)
    return entry


class TrackerStore:
    """The database: accounts, plus one ledger per user (see ledger()). Every bet and cash row belongs to a user."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA journal_mode=WAL')
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('PRAGMA foreign_keys=ON')
        self._upgrade_unscoped_tables()
        self._add_session_epoch()
        self._db.executescript(SCHEMA)
        if 'parlay_legs' not in [r['name'] for r in self._db.execute('PRAGMA table_info(bets)')]:
            self._db.execute("ALTER TABLE bets ADD COLUMN parlay_legs TEXT NOT NULL DEFAULT '[]'")
        self._copy_unscoped_rows()
        from corner import beta_access
        beta_access.initialize(self._db)

    def close(self):
        with self._lock:
            self._db.close()

    # -- upgrading a database from before accounts existed -------------------------------------
    # Those rows have no owner. They stay NULL (visible to nobody) until the first account is created,
    # which adopts them, so a single-user database keeps its history.
    def _upgrade_unscoped_tables(self):
        with self._lock:
            old = [t for t in ('bets', 'cash')
                   if (cols := [r['name'] for r in self._db.execute(f'PRAGMA table_info({t})')]) and 'user_id' not in cols]
            if not old:
                return
            self._db.execute('BEGIN IMMEDIATE')
            try:
                for index in ('bets_placed', 'bets_status', 'cash_when'):
                    self._db.execute(f'DROP INDEX IF EXISTS {index}')
                for table in old:
                    self._db.execute(f'DROP TABLE IF EXISTS {table}_old')
                    self._db.execute(f'ALTER TABLE {table} RENAME TO {table}_old')
                self._db.execute('COMMIT')
            except Exception:
                self._db.execute('ROLLBACK')
                raise

    def _copy_unscoped_rows(self):
        with self._lock:
            for table, columns in (('bets', BET_COLUMNS), ('cash', CASH_COLUMNS)):
                if not self._db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (f'{table}_old',)).fetchone():
                    continue
                self._db.execute('BEGIN IMMEDIATE')
                try:
                    self._db.execute(f'INSERT OR IGNORE INTO {table}({columns}) SELECT {columns} FROM {table}_old')
                    self._db.execute(f'DROP TABLE {table}_old')
                    self._db.execute('COMMIT')
                except Exception:
                    self._db.execute('ROLLBACK')
                    raise

    def _add_session_epoch(self):
        with self._lock:
            columns = [r['name'] for r in self._db.execute('PRAGMA table_info(users)')]
            if columns and 'session_epoch' not in columns:
                self._db.execute('ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0')

    # -- accounts -------------------------------------------------------------------------------
    def create_user(self, username, username_key, password_hash, invite_token=None):
        """A new account; the username must be unused (case-insensitively). The first account adopts any unowned rows."""
        user_id = uuid.uuid4().hex
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                first = self._db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
                self._db.execute('INSERT INTO users(id,username,username_key,password_hash,created_at) VALUES(?,?,?,?,?)',
                                 (user_id, username, username_key, password_hash, now_iso()))
                from corner import beta_access
                if beta_access.enabled() or beta_access.family_invitation(self._db,invite_token):
                    beta_access.enroll(self._db, user_id, username_key, invite_token)
                if first and not beta_access.enabled():
                    self._db.execute('UPDATE bets SET user_id=? WHERE user_id IS NULL', (user_id,))
                    self._db.execute('UPDATE cash SET user_id=? WHERE user_id IS NULL', (user_id,))
                self._db.execute('COMMIT')
            except sqlite3.IntegrityError:
                self._db.execute('ROLLBACK')
                _fail('That username is already taken. Try another.', 409, 'username_taken')
            except Exception:
                self._db.execute('ROLLBACK')
                raise
        user = {'id': user_id, 'username': username}
        row = self.user_by_id(user_id)
        if beta_access.enabled() or row.get('beta_cohort') in ('friend','family'):
            user.update(role=row['beta_role'], access_kind=row['beta_access_kind'], founder=row['beta_founder'], cohort=row.get('beta_cohort'), friend_rates=row.get('beta_friend_rates'))
        return user

    def user_by_key(self, username_key):
        with self._lock:
            row = self._db.execute('SELECT * FROM users WHERE username_key=?', (username_key,)).fetchone()
        from corner import beta_access
        with self._lock:
            return beta_access.decorate(self._db, dict(row) if row else None)

    def user_by_id(self, user_id):
        with self._lock:
            row = self._db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        from corner import beta_access
        with self._lock:
            return beta_access.decorate(self._db, dict(row) if row else None)

    def list_users(self):
        with self._lock:
            rows = self._db.execute('SELECT id, username, created_at FROM users ORDER BY created_at, username_key').fetchall()
        return [dict(r) for r in rows]

    def set_password(self, user_id, password_hash):
        """Replace a password and sign out every session issued before now (the epoch is part of each token)."""
        with self._lock:
            cursor = self._db.execute('UPDATE users SET password_hash=?, session_epoch=session_epoch+1 WHERE id=?',
                                      (password_hash, user_id))
            if cursor.rowcount != 1:
                _fail('That account no longer exists', 404, 'not_found')
            return self._db.execute('SELECT session_epoch FROM users WHERE id=?', (user_id,)).fetchone()[0]

    def revoke_sessions(self, user_id):
        with self._lock:
            cursor = self._db.execute('UPDATE users SET session_epoch=session_epoch+1 WHERE id=?', (user_id,))
            if cursor.rowcount != 1:
                _fail('That account no longer exists', 404, 'not_found')

    def ledger(self, user_id):
        return Ledger(self, user_id)


class Ledger:
    """One user's bets and cash. Every query is constrained to that user's id."""

    def __init__(self, store, user_id):
        if not user_id:
            raise ValueError('A ledger needs a user')
        self._db, self._lock, self.user_id = store._db, store._lock, user_id

    # -- reads ------------------------------------------------------------------------------
    def state(self):
        with self._lock:
            bets = [_bet_row(r) for r in self._db.execute(
                'SELECT * FROM bets WHERE user_id=? ORDER BY placed_at, created_at, id', (self.user_id,))]
            cash = [_cash_row(r) for r in self._db.execute(
                'SELECT * FROM cash WHERE user_id=? ORDER BY occurred_at, id', (self.user_id,))]
        return {'bets': bets, 'cash': cash}

    def bet(self, bet_id):
        with self._lock:
            row = self._db.execute('SELECT * FROM bets WHERE id=? AND user_id=?', (bet_id, self.user_id)).fetchone()
        if not row:
            _fail('That bet no longer exists', 404, 'not_found')
        return _bet_row(row)

    # -- bets -------------------------------------------------------------------------------
    def _bet_values(self, data):
        if not isinstance(data, dict):
            _fail('A bet must be an object')
        strategy = text(data.get('strategy'), 'strategy', required=True, limit=20)
        if strategy not in STRATEGIES:
            _fail('strategy: unknown strategy')
        stake_type = text(data.get('stake_type') or 'cash', 'stake type', limit=10)
        if stake_type not in STAKE_TYPES:
            _fail('stake type: cash or bonus')
        placed = parse_when(data.get('placed_at'), 'placed at', default_now=True)
        legs = prepare_legs(data.get('legs'), book_code(data.get('book')), fail=_fail, text=text,
                            parse_odds=parse_odds, parse_when=parse_when, clean_ref=clean_ref) if strategy == 'parlay' else []
        if strategy != 'parlay' and data.get('legs'):
            _fail('Only a parlay can contain child legs')
        if datetime.fromisoformat(placed) > datetime.now(timezone.utc) + timedelta(days=1):
            _fail('placed at: cannot be in the future')
        return {
            'group_id': text(data.get('group_id'), 'group', limit=64) or None,
            'placed_at': placed,
            'strategy': strategy,
            'parlay_legs': json.dumps(legs, separators=(',', ':')),
            'sport_key': text(data.get('sport_key'), 'league', limit=60),
            'matchup': text(data.get('matchup'), 'event', required=True, limit=200),
            'starts_at': parse_when(data.get('starts_at'), 'start time'),
            'market': text(data.get('market'), 'market', limit=120),
            'selection': text(data.get('selection'), 'selection', required=True, limit=200),
            'book': book_code(data.get('book')),
            'odds': parse_odds(data.get('odds')),
            'stake_cents': to_cents(data.get('stake'), 'stake'),
            'stake_type': stake_type,
            'fair_prob': optional_ratio(data.get('fair_prob'), 'fair probability'),
            'ev_ratio': optional_ratio(data.get('ev_ratio'), 'edge'),
            'ref': json.dumps(clean_ref(data.get('ref')), separators=(',', ':')),
            'notes': text(data.get('notes'), 'notes', limit=500),
        }

    def add_bets(self, items):
        """Insert a play's legs atomically. A repeated client key returns the stored bet, never a duplicate."""
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_LEGS:
            _fail(f'Send between 1 and {MAX_LEGS} bets')
        prepared = []
        for item in items:
            key = text(item.get('client_key') if isinstance(item, dict) else None, 'client key', required=True, limit=64)
            prepared.append((key, self._bet_values(item)))
        saved = []
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                for key, v in prepared:
                    row = self._db.execute('SELECT * FROM bets WHERE client_key=? AND user_id=?', (key, self.user_id)).fetchone()
                    if row:
                        saved.append(_bet_row(row))
                        continue
                    bet_id = uuid.uuid4().hex
                    self._db.execute(
                        'INSERT INTO bets(id,user_id,client_key,group_id,created_at,placed_at,strategy,sport_key,matchup,starts_at,'
                        'market,selection,book,odds,stake_cents,stake_type,fair_prob,ev_ratio,ref,notes,parlay_legs) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (bet_id, self.user_id, key, v['group_id'], now_iso(), v['placed_at'], v['strategy'], v['sport_key'],
                         v['matchup'], v['starts_at'], v['market'], v['selection'], v['book'], v['odds'],
                         v['stake_cents'], v['stake_type'], v['fair_prob'], v['ev_ratio'], v['ref'], v['notes'], v['parlay_legs']))
                    saved.append(_bet_row(self._db.execute('SELECT * FROM bets WHERE id=?', (bet_id,)).fetchone()))
                self._db.execute('COMMIT')
            except Exception:
                self._db.execute('ROLLBACK')
                raise
        return saved

    EDITABLE = ('placed_at', 'strategy', 'matchup', 'market', 'selection', 'book', 'odds', 'stake', 'stake_type', 'notes')

    def set_parlay_leg(self, bet_id, key, result):
        if result not in LEG_RESULTS:
            _fail('Invalid parlay leg result')
        with self._lock:
            bet = self.bet(bet_id)
            if bet['strategy'] != 'parlay' or bet['status'] != 'pending':
                _fail('Reopen this parlay before changing its legs')
            legs = bet.get('legs', [])
            leg = next((leg for leg in legs if leg['key'] == key), None)
            if leg is None:
                _fail('That leg no longer exists', 404, 'not_found')
            leg['status'] = result
            self._db.execute('UPDATE bets SET parlay_legs=? WHERE id=? AND user_id=?',
                             (json.dumps(legs, separators=(',', ':')), bet_id, self.user_id))
            return self.bet(bet_id)

    def update_bet(self, bet_id, data):
        """Correct a bet. Fields not sent are kept; a settled bet's payout is recalculated from its result."""
        if isinstance(data, dict) and 'parlay_leg_key' in data:
            return self.set_parlay_leg(bet_id, data['parlay_leg_key'], data.get('parlay_leg_result'))
        bet = self.bet(bet_id)
        if not isinstance(data, dict) or not any(k in data for k in self.EDITABLE):
            _fail('Nothing to change')
        merged = {
            'legs': bet.get('legs'),
            'client_key': bet['client_key'], 'group_id': bet['group_id'], 'placed_at': bet['placed_at'],
            'strategy': bet['strategy'], 'sport_key': bet['sport_key'], 'matchup': bet['matchup'],
            'starts_at': bet['starts_at'], 'market': bet['market'], 'selection': bet['selection'],
            'book': bet['book'], 'odds': bet['odds'], 'stake': str(Decimal(bet['stake_cents']) / 100),
            'stake_type': bet['stake_type'], 'fair_prob': bet['fair_prob'], 'ev_ratio': bet['ev_ratio'],
            'ref': bet['ref'], 'notes': bet['notes'],
        }
        merged.update({k: data[k] for k in self.EDITABLE if k in data})
        v = self._bet_values(merged)
        returned = bet['returned_cents']
        if bet['status'] in ('won', 'lost', 'push', 'void') and not bet.get('legs'):
            returned = payout_cents(v['stake_cents'], v['odds'], v['stake_type'], bet['status'])
        with self._lock:
            self._db.execute(
                'UPDATE bets SET placed_at=?,strategy=?,matchup=?,market=?,selection=?,book=?,odds=?,stake_cents=?,'
                'stake_type=?,notes=?,returned_cents=? WHERE id=? AND user_id=?',
                (v['placed_at'], v['strategy'], v['matchup'], v['market'], v['selection'], v['book'], v['odds'],
                 v['stake_cents'], v['stake_type'], v['notes'], returned, bet_id, self.user_id))
        return self.bet(bet_id)

    def settle_bet(self, bet_id, result, *, returned=None, settled_at=None):
        bet = self.bet(bet_id)
        if bet.get('legs') and result == 'won' and any(l['status'] in ('void', 'push') for l in bet['legs']) and returned is None:
            _fail('Enter the actual returned amount for a parlay with void or pushed legs')
        cashout = None
        if result == 'cashout':
            cashout = to_cents(returned, 'cash-out amount', allow_zero=True)
        total = payout_cents(bet['stake_cents'], bet['odds'], bet['stake_type'], result, cashout_cents=cashout)
        if bet.get('legs') and result == 'won' and returned is not None:
            total = to_cents(returned, 'actual returned amount', allow_zero=True)
        when = parse_when(settled_at, 'settled at', default_now=True)
        if when < bet['placed_at']:
            when = bet['placed_at']
        with self._lock:
            self._db.execute('UPDATE bets SET status=?,returned_cents=?,settled_at=? WHERE id=? AND user_id=?',
                             (result, total, when, bet_id, self.user_id))
        return self.bet(bet_id)

    def reopen_bet(self, bet_id):
        self.bet(bet_id)
        with self._lock:
            self._db.execute("UPDATE bets SET status='pending',returned_cents=NULL,settled_at=NULL WHERE id=? AND user_id=?", (bet_id, self.user_id))
        return self.bet(bet_id)

    def delete_bet(self, bet_id):
        self.bet(bet_id)
        with self._lock:
            self._db.execute('DELETE FROM bets WHERE id=? AND user_id=?', (bet_id, self.user_id))

    def set_clv(self, bet_id, clv):
        with self._lock:
            self._db.execute('UPDATE bets SET clv=? WHERE id=? AND user_id=?',
                             (json.dumps(clv, separators=(',', ':')), bet_id, self.user_id))

    # -- cash -------------------------------------------------------------------------------
    def add_cash(self, data):
        if not isinstance(data, dict):
            _fail('A cash entry must be an object')
        key = text(data.get('client_key'), 'client key', required=True, limit=64)
        kind = text(data.get('kind'), 'kind', required=True, limit=20)
        if kind not in CASH_KINDS:
            _fail('kind: deposit, withdrawal, transfer or adjustment')
        where = book_code(data.get('book'), 'book')
        to_book = None
        if kind == 'transfer':
            to_book = book_code(data.get('to_book'), 'destination')
            if to_book == where:
                _fail('A transfer needs two different places')
        amount = to_cents(data.get('amount'), 'amount', signed=(kind == 'adjustment'), allow_zero=False)
        if kind == 'adjustment' and amount == 0:
            _fail('amount: an adjustment cannot be zero')
        occurred = parse_when(data.get('occurred_at'), 'date', default_now=True)
        if datetime.fromisoformat(occurred) > datetime.now(timezone.utc) + timedelta(days=1):
            _fail('date: cannot be in the future')
        with self._lock:
            row = self._db.execute('SELECT * FROM cash WHERE client_key=? AND user_id=?', (key, self.user_id)).fetchone()
            if row:
                return _cash_row(row)
            cash_id = uuid.uuid4().hex
            self._db.execute('INSERT INTO cash(id,user_id,client_key,occurred_at,kind,amount_cents,book,to_book,note) VALUES(?,?,?,?,?,?,?,?,?)',
                             (cash_id, self.user_id, key, occurred, kind, amount, where, to_book, text(data.get('note'), 'note', limit=300)))
            return _cash_row(self._db.execute('SELECT * FROM cash WHERE id=?', (cash_id,)).fetchone())

    def delete_cash(self, cash_id):
        with self._lock:
            found = self._db.execute('SELECT 1 FROM cash WHERE id=? AND user_id=?', (cash_id, self.user_id)).fetchone()
            if not found:
                _fail('That entry no longer exists', 404, 'not_found')
            self._db.execute('DELETE FROM cash WHERE id=? AND user_id=?', (cash_id, self.user_id))

    # -- saved tool settings and presets -----------------------------------------------------
    def settings(self):
        """Everything this account has saved: {'tools': {tool: settings}, 'presets': {tool: [preset, ...]}}."""
        with self._lock:
            tools = {r['tool']: json.loads(r['settings']) for r in self._db.execute(
                'SELECT tool, settings FROM tool_settings WHERE user_id=?', (self.user_id,))}
            presets = {}
            for r in self._db.execute('SELECT id, tool, name, settings FROM presets WHERE user_id=? ORDER BY name_key',
                                      (self.user_id,)):
                presets.setdefault(r['tool'], []).append(
                    {'id': r['id'], 'name': r['name'], 'settings': json.loads(r['settings'])})
        return {'tools': tools, 'presets': presets}

    def put_settings(self, tool, settings):
        try:
            tool, settings = tool_settings.clean_tool(tool), tool_settings.clean_settings(settings)
        except tool_settings.SettingsError as error:
            _fail(str(error), error.status, error.code)
        with self._lock:
            self._db.execute(
                'INSERT INTO tool_settings(user_id,tool,settings,updated_at) VALUES(?,?,?,?) '
                'ON CONFLICT(user_id,tool) DO UPDATE SET settings=excluded.settings, updated_at=excluded.updated_at',
                (self.user_id, tool, json.dumps(settings, separators=(',', ':')), now_iso()))
        return settings

    def save_preset(self, tool, name, settings):
        """Create a preset, or replace the one with the same name (any letter case)."""
        try:
            tool, settings = tool_settings.clean_tool(tool), tool_settings.clean_settings(settings)
            name, key = tool_settings.clean_name(name)
        except tool_settings.SettingsError as error:
            _fail(str(error), error.status, error.code)
        body, now = json.dumps(settings, separators=(',', ':')), now_iso()
        with self._lock:
            row = self._db.execute('SELECT id FROM presets WHERE user_id=? AND tool=? AND name_key=?',
                                   (self.user_id, tool, key)).fetchone()
            if row:
                self._db.execute('UPDATE presets SET name=?, settings=?, updated_at=? WHERE id=?', (name, body, now, row['id']))
                preset_id = row['id']
            else:
                count = self._db.execute('SELECT COUNT(*) FROM presets WHERE user_id=? AND tool=?',
                                         (self.user_id, tool)).fetchone()[0]
                if count >= tool_settings.MAX_PRESETS:
                    _fail(f'You can keep up to {tool_settings.MAX_PRESETS} presets per tool. Delete one first.', 409, 'too_many')
                preset_id = uuid.uuid4().hex
                self._db.execute(
                    'INSERT INTO presets(id,user_id,tool,name,name_key,settings,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                    (preset_id, self.user_id, tool, name, key, body, now, now))
        return {'id': preset_id, 'name': name, 'settings': settings}

    def delete_preset(self, preset_id):
        with self._lock:
            cursor = self._db.execute('DELETE FROM presets WHERE id=? AND user_id=?', (preset_id, self.user_id))
            if cursor.rowcount != 1:
                _fail('That preset no longer exists', 404, 'not_found')

    # -- backup -----------------------------------------------------------------------------
    def export(self):
        return {'format': 'corner.tracker/1', 'exported_at': now_iso(), **self.state()}
