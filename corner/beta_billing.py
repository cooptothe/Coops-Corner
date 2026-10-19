"""Offline, operator-reviewed beta receipt ledger. Never verifies or sends funds.

All mutations own a BEGIN IMMEDIATE transaction on the existing account store.
No public endpoint, wallet keys, pricing oracle, or automatic chain trust exists.
"""
from contextlib import contextmanager
import threading
import hashlib
import json
import re
import secrets
import time
from corner import beta_access as beta
from corner import auth
from corner import beta_terms as terms
from corner.tracker_store import TrackerError


def text(value, name, limit=300):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise TrackerError(f'{name}: a nonempty value of at most {limit} characters is required.', 400, 'invalid_payment')
    return value.strip()


class BetaBilling:
    def __init__(self, store):
        self.store = store
        self._review = threading.local()
        with store._lock:
            store._db.executescript('''
            CREATE TABLE IF NOT EXISTS beta_payment_receipts (
              id TEXT PRIMARY KEY,
              network TEXT NOT NULL,
              transaction_id TEXT NOT NULL,
              transfer_index INTEGER NOT NULL CHECK(transfer_index >= 0),
              username_key TEXT NOT NULL,
              receipt_json TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('verified','fulfilled','refunded')),
              invite_id TEXT,
              user_id TEXT,
              refund_json TEXT,
              created_at REAL NOT NULL,
              UNIQUE(network,transaction_id,transfer_index)
            );
            ''')

    @contextmanager
    def atomic_review(self):
        """Only internal invoice review may join its already locked transaction."""
        self._review.join = True
        try:
            yield
        finally:
            self._review.join = False

    def _transaction(self, actor, operation):
        with self.store._lock:
            db = self.store._db
            if getattr(self._review, 'join', False) and db.in_transaction:
                beta.require_operator(db, actor)
                return operation(db)
            db.execute('BEGIN IMMEDIATE')
            try:
                beta.require_operator(db, actor)
                result = operation(db)
                db.execute('COMMIT')
                return result
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def verify(self, actor, username_key, receipt):
        """Operator attests an independently checked, settled payment, not a claim.

        Network and asset identify the exact chain/token; transaction ID must be
        normalized by the operator to that chain's canonical spelling. Amount is
        an integer base-unit string. No exchange-rate arithmetic happens here.
        """
        username_key = auth.clean_username(username_key)[1]
        required = ('network', 'asset_id', 'transaction_id', 'destination',
                    'amount_base_units', 'quote_id', 'quote_evidence', 'terms_version',
                    'settlement_evidence')
        if not isinstance(receipt, dict) or set(receipt) != set(required) | {'transfer_index', 'usd_cents', 'settled'}:
            raise TrackerError('Complete reviewed receipt evidence is required.', 400, 'invalid_payment')
        clean = {key: text(receipt[key], key) for key in required}
        # These planned assets use hash/numeric transaction identifiers. The
        # real verifier must still enforce exact configured chain/token IDs.
        clean['transaction_id'] = clean['transaction_id'].lower()
        clean['network'] = clean['network'].lower()
        if clean['asset_id'] not in terms.ASSETS or clean['network'] != terms.ASSETS[clean['asset_id']][0]:
            raise TrackerError('Use XRP, HBAR or XLM on its configured native network.', 400, 'invalid_payment')
        amount = clean['amount_base_units']
        if not re.fullmatch(r'[1-9][0-9]{0,77}', amount):
            raise TrackerError('Use positive integer base units, without decimal rounding.', 400, 'invalid_payment')
        index = receipt['transfer_index']
        if type(index) is not int or not 0 <= index <= 2147483647 or receipt['settled'] is not True or type(receipt['usd_cents']) is not int or receipt['usd_cents'] != 5000:
            raise TrackerError('A settled, independently reviewed $50 beta receipt is required.', 400, 'invalid_payment')
        clean.update(transfer_index=index, usd_cents=5000, settled=True)
        encoded = json.dumps(clean, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(encoded.encode()).hexdigest()

        def write(db):
            prior = db.execute('SELECT * FROM beta_payment_receipts WHERE network=? AND transaction_id=? AND transfer_index=?',
                               (clean['network'], clean['transaction_id'], index)).fetchone()
            if prior:
                if prior['username_key'] != username_key or prior['receipt_sha256'] != digest:
                    raise TrackerError('This transfer is already recorded with different evidence or recipient.', 409, 'receipt_reused')
                return prior['id']
            ident = secrets.token_hex(16)
            db.execute('INSERT INTO beta_payment_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, clean['network'], clean['transaction_id'], index, username_key,
                        encoded, digest, 'verified', None, None, None, time.time()))
            beta.audit(db, actor, 'verify_payment', ident, digest)
            return ident
        return self._transaction(actor, write)

    def fulfill(self, actor, receipt_id):
        """Atomically reserve an invitation or promote an existing preview member.

        Invite secrets are returned once. A repeated call returns no token and
        cannot create a second seat, grant or invitation.
        """
        def write(db):
            row = db.execute('SELECT * FROM beta_payment_receipts WHERE id=?', (receipt_id,)).fetchone()
            if not row or row['state'] == 'refunded':
                raise TrackerError('A verified, non-refunded receipt is required.', 409, 'payment_state')
            if row['state'] == 'fulfilled':
                return {'receipt_id':receipt_id, 'reused':True, 'invitation_code':None}
            user = db.execute('SELECT id FROM users WHERE username_key=?', (row['username_key'],)).fetchone()
            invite_id = token = None
            user_id = user[0] if user else None
            evidence = f'payment:{receipt_id}'
            if user:
                member = db.execute('SELECT * FROM beta_members WHERE user_id=?', (user_id,)).fetchone()
                if member:
                    if member['role'] != 'member' or member['state'] != 'active' or member['access_kind'] != 'preview' or member['cohort']!='beta':
                        raise TrackerError('Only an active preview member can be upgraded here.', 409, 'payment_state')
                    db.execute("UPDATE beta_members SET access_kind='paid_beta',founder=1,evidence=? WHERE user_id=?", (evidence,user_id))
                    db.execute('UPDATE users SET session_epoch=session_epoch+1 WHERE id=?', (user_id,))
                else:
                    beta.grant(db, actor, row['username_key'], 'paid_beta', evidence)
            else:
                invite_id, token = beta.issue(db, actor, row['username_key'], access_kind='paid_beta', evidence=evidence)
            db.execute("UPDATE beta_payment_receipts SET state='fulfilled',invite_id=?,user_id=? WHERE id=?", (invite_id,user_id,receipt_id))
            beta.audit(db, actor, 'fulfill_payment', receipt_id)
            return {'receipt_id':receipt_id, 'reused':False, 'invitation_code':token}
        return self._transaction(actor, write)
