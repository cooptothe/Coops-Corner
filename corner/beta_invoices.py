"""Offline invoice rehearsal. Quotes and claims are never settlement evidence.

No chain requests or payment enablement occur here. Only explicit operator
approval of reviewed evidence can change membership. The full account database backup covers these tables.
"""
import json
import math
import re
import secrets
import time
from corner import beta_access as beta, beta_terms as terms
from corner.beta_receiving import validate_receivers
from corner.tracker_store import TrackerError


class BetaInvoices:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        with store._lock:
            store._db.executescript("""
            CREATE TABLE IF NOT EXISTS beta_payment_requests (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
              asset TEXT NOT NULL, terms_version TEXT NOT NULL,
              accepted_at REAL NOT NULL, created_at REAL NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('requested','quoted','submitted','expired','cancelled','approved')),
              quote_json TEXT, expires_at REAL, transaction_id TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS beta_one_open_payment
              ON beta_payment_requests(user_id) WHERE state IN ('requested','quoted','submitted');
            CREATE UNIQUE INDEX IF NOT EXISTS beta_claim_once
              ON beta_payment_requests(asset,transaction_id) WHERE transaction_id IS NOT NULL;
            """)

    def _run(self, operation):
        with self.store._lock:
            db = self.store._db
            db.execute('BEGIN IMMEDIATE')
            try:
                result = operation(db)
                db.execute('COMMIT')
                return result
            except BaseException:
                db.execute('ROLLBACK')
                raise

    def _member(self, db, user_id):
        row = db.execute("SELECT 1 FROM beta_members WHERE user_id=? AND role='member' AND state='active' AND access_kind='preview'", (user_id,)).fetchone()
        if not row:
            raise TrackerError('An active preview membership is required.', 403, 'payment_access')

    def _owned(self, db, user_id, ident):
        row = db.execute('SELECT * FROM beta_payment_requests WHERE id=? AND user_id=?', (ident, user_id)).fetchone()
        if not row:
            raise TrackerError('Payment request not found.', 404, 'payment_not_found')
        return row

    def _expire(self, db, user_id):
        db.execute("UPDATE beta_payment_requests SET state='expired' WHERE user_id=? AND state='quoted' AND expires_at<=?", (user_id, self.clock()))

    def request(self, user_id, asset, accepted_version):
        if asset not in terms.ASSETS or accepted_version != terms.VERSION:
            raise TrackerError('Choose a supported asset and accept the current terms.', 400, 'payment_terms')
        def write(db):
            self._member(db, user_id)
            now = self.clock()
            if now >= terms.BETA_END:
                raise TrackerError('The beta payment period has ended.', 409, 'payment_closed')
            self._expire(db, user_id)
            prior = db.execute("SELECT * FROM beta_payment_requests WHERE user_id=? AND state IN ('requested','quoted','submitted')", (user_id,)).fetchone()
            if prior:
                if prior['asset'] != asset or prior['terms_version'] != accepted_version:
                    raise TrackerError('Resolve your existing payment request first.', 409, 'payment_pending')
                return prior['id']
            ident = secrets.token_hex(16)
            db.execute('INSERT INTO beta_payment_requests(id,user_id,asset,terms_version,accepted_at,created_at,state) VALUES(?,?,?,?,?,?,?)', (ident,user_id,asset,accepted_version,now,now,'requested'))
            beta.audit(db,user_id,'request_payment',ident,accepted_version)
            return ident
        return self._run(write)

    def quote(self, actor, ident, *, usd_per_coin, observed_at, source, receiving):
        # Operator supplies reviewed evidence; no fetched or invented rate.
        receivers = validate_receivers(receiving)
        if not isinstance(source,str) or not 1 <= len(source.strip()) <= 300:
            raise TrackerError('Record the independently checked rate source.',400,'payment_quote')
        now = self.clock()
        if type(observed_at) not in (int,float) or not math.isfinite(observed_at) or not 0 <= now-observed_at <= 60:
            raise TrackerError('A rate observed within the last minute is required.',400,'payment_quote')
        def write(db):
            beta.require_operator(db,actor)
            row = db.execute('SELECT * FROM beta_payment_requests WHERE id=?',(ident,)).fetchone()
            if not row or row['state'] != 'requested' or row['terms_version'] != terms.VERSION:
                raise TrackerError('A current unquoted payment request is required.',409,'payment_state')
            self._member(db,row['user_id'])
            expires = min(now+600, observed_at+600, terms.BETA_END)
            if expires <= now:
                raise TrackerError('The beta payment period has ended.',409,'payment_closed')
            amount = terms.quote_amount(row['asset'],usd_per_coin)
            quote = {**amount, **receivers[row['asset']], 'observed_at':observed_at,
                     'source':source.strip(),'expires_at':expires,'quote_id':ident,
                     'rehearsal_only':True,'send_funds':False}
            db.execute("UPDATE beta_payment_requests SET state='quoted',quote_json=?,expires_at=? WHERE id=?",(json.dumps(quote,sort_keys=True),expires,ident))
            beta.audit(db,actor,'quote_payment_rehearsal',ident)
            return quote
        return self._run(write)

    def submit(self,user_id,ident,transaction_id):
        def write(db):
            self._member(db,user_id)
            row = self._owned(db,user_id,ident)
            # Hashes/transaction references are a member claim, never proof.
            value = transaction_id.strip().lower() if isinstance(transaction_id,str) else ''
            pattern = r'[0-9a-f]{64}' if row['asset'] in ('XRP','XLM') else r'0[.]0[.][0-9]+@[0-9]+[.][0-9]{1,9}'
            if not re.fullmatch(pattern,value):
                raise TrackerError('Enter the native transaction reference.',400,'payment_reference')
            if row['state'] == 'submitted':
                if row['transaction_id'] != value:
                    raise TrackerError('This request already has a reference under review.',409,'payment_pending')
                return 'submitted'
            if row['state'] not in ('quoted','expired'):
                raise TrackerError('A quoted request is required.',409,'payment_state')
            prior = db.execute('SELECT id FROM beta_payment_requests WHERE asset=? AND transaction_id=?',(row['asset'],value)).fetchone()
            if prior:
                raise TrackerError('This reference is already under review. Contact support.',409,'payment_pending')
            other = db.execute("SELECT id FROM beta_payment_requests WHERE user_id=? AND id!=? AND state IN ('requested','quoted','submitted')", (user_id,ident)).fetchone()
            if other:
                raise TrackerError('Another payment request is open. Contact support to reconcile this transfer; do not send again.',409,'payment_pending')
            # Even late claims are retained for review, without granting access.
            db.execute("UPDATE beta_payment_requests SET state='submitted',transaction_id=? WHERE id=?",(value,ident))
            beta.audit(db,user_id,'submit_payment_claim',ident,'late' if self.clock()>=row['expires_at'] else 'on_time_claim')
            return 'submitted'
        return self._run(write)

    def cancel(self,user_id,ident):
        def write(db):
            row = self._owned(db,user_id,ident)
            if row['state'] == 'submitted':
                raise TrackerError('A submitted payment needs operator review; do not send again.',409,'payment_pending')
            if row['state'] != 'cancelled':
                db.execute("UPDATE beta_payment_requests SET state='cancelled' WHERE id=?",(ident,))
                beta.audit(db,user_id,'cancel_payment_request',ident)
        return self._run(write)

    def status(self,user_id,ident):
        def read(db):
            self._expire(db,user_id)
            row = self._owned(db,user_id,ident)
            # Public status deliberately omits receiving instructions during rehearsal.
            return {'id':row['id'],'asset':row['asset'],'state':row['state'],
                    'expires_at':row['expires_at'],'terms_version':row['terms_version'],
                    'transaction_id':row['transaction_id'],'payments_enabled':False}
        return self._run(read)

    def approve(self,actor,ident,*,evidence,delivered_base_units,destination,memo,received_at,transfer_index=0):
        """Explicit operator attestation, not an automatic chain verifier.

        All invoice, receipt, membership and audit changes commit together.
        Wrong amount/destination/memo or late transfers require manual resolution;
        this command never adjusts a quote or invents settlement evidence.
        """
        from corner.beta_billing import BetaBilling
        if not isinstance(evidence,str) or not 10 <= len(evidence.strip()) <= 300:
            raise TrackerError('Record the independent wallet/explorer review reference.',400,'payment_review')
        if type(received_at) not in (int,float) or not math.isfinite(received_at):
            raise TrackerError('A reviewed receipt timestamp is required.',400,'payment_review')
        billing = BetaBilling(self.store)
        def write(db):
            beta.require_operator(db,actor)
            row = db.execute('SELECT * FROM beta_payment_requests WHERE id=?',(ident,)).fetchone()
            if not row or row['state'] not in ('submitted','approved'):
                raise TrackerError('A submitted payment claim is required.',409,'payment_state')
            quote = json.loads(row['quote_json'])
            if (delivered_base_units != quote['amount_base_units'] or destination != quote['address']
                    or memo != quote['memo'] or not row['created_at'] <= received_at < quote['expires_at']
                    or received_at > self.clock()):
                raise TrackerError('Amount, destination, memo or receipt time differs from the invoice. Resolve privately; do not request a second payment.',409,'payment_review')
            username = db.execute('SELECT username_key FROM users WHERE id=?',(row['user_id'],)).fetchone()[0]
            receipt = dict(network=quote['network'],asset_id=row['asset'],transaction_id=row['transaction_id'],
                destination=destination,amount_base_units=delivered_base_units,quote_id=ident,
                quote_evidence=quote['source']+'; observed='+str(quote['observed_at']),terms_version=row['terms_version'],
                settlement_evidence=evidence.strip(),transfer_index=transfer_index,usd_cents=5000,settled=True)
            receipt_id = billing.verify(actor,username,receipt)
            result = billing.fulfill(actor,receipt_id)
            if row['state'] != 'approved':
                db.execute("UPDATE beta_payment_requests SET state='approved' WHERE id=?",(ident,))
                beta.audit(db,actor,'approve_invoice',ident,receipt_id)
            return {**result,'request_id':ident,'state':'approved'}
        # Billing's inner operations use this transaction, never a partial grant.
        with billing.atomic_review():
            return self._run(write)
