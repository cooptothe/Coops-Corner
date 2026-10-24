"""Explicit provider-cycle binding and audited, conservative quota reconciliation."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3

from corner.collection_policy import POOLS, TOTAL, PROTECTED, BUDGET_VERSION, aware
from corner.credit_governor import Governor, Refused


def key_identity(key):
    if not key:
        raise ValueError('Provider credential required')
    return hashlib.sha256(key.encode()).hexdigest()


def quota_headers(headers):
    values = []
    for key in ('x-requests-used', 'x-requests-remaining', 'x-requests-last'):
        value = headers.get(key)
        if isinstance(value, bool) or not str(value).isdigit():
            raise Refused('Missing or invalid provider quota header')
        values.append(int(value))
    used, remaining, actual = values
    if used + remaining != TOTAL or min(values) < 0:
        raise Refused('Provider total differs from approved 15M cycle')
    return used, remaining, actual


class LiveGovernor(Governor):
    def __init__(self, path):
        path = Path(path)
        if 'simulation' in path.name.lower():
            raise ValueError('Live quota cannot use simulation state')
        super().__init__(path)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS collection_quarantine(
            job_key TEXT PRIMARY KEY REFERENCES jobs(key), token TEXT NOT NULL,
            created REAL NOT NULL, code TEXT NOT NULL, detail TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS collection_retry_cooldowns(
            job_key TEXT PRIMARY KEY REFERENCES jobs(key), retry_after REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS quota_bindings(
            cycle_id TEXT PRIMARY KEY REFERENCES cycles(id), key_hash TEXT NOT NULL,
            used INTEGER NOT NULL, checked REAL NOT NULL,
            offsets TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS quota_policy(
            cycle_id TEXT PRIMARY KEY REFERENCES cycles(id), version TEXT NOT NULL,
            limits_json TEXT NOT NULL, total INTEGER NOT NULL, protected INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS quota_inventory(
            token TEXT PRIMARY KEY, cycle_id TEXT NOT NULL REFERENCES cycles(id),
            owner TEXT NOT NULL, started REAL NOT NULL, state TEXT NOT NULL,
            actual INTEGER);
          CREATE TABLE IF NOT EXISTS quota_audit(
            id INTEGER PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL,
            evidence TEXT NOT NULL, detail TEXT NOT NULL);
        ''')

    def ready(self, job, now):
        if self.db.execute('SELECT 1 FROM collection_retry_cooldowns WHERE job_key=? AND retry_after>?',(job.key,now.timestamp())).fetchone():
            return False
        if self.db.execute('SELECT 1 FROM collection_quarantine WHERE job_key=?', (job.key,)).fetchone():
            return False
        return super().ready(job, now)

    def claim(self, job, owner, now):
        if self.db.execute('SELECT 1 FROM collection_retry_cooldowns WHERE job_key=? AND retry_after>?',(job.key,now.timestamp())).fetchone():
            raise Refused('Recovered transport scope is cooling down')
        if self.db.execute('SELECT 1 FROM collection_quarantine WHERE job_key=?', (job.key,)).fetchone():
            raise Refused('Scope quarantined; review before any new purchase')
        return super().claim(job, owner, now)

    def quarantine(self, db, job_key, token, now, code, detail):
        db.execute('INSERT OR IGNORE INTO collection_quarantine VALUES(?,?,?,?,?)',
                   (job_key, token, now.timestamp(), code, json.dumps(detail, sort_keys=True)))
        db.execute("UPDATE jobs SET state='blocked',last_error=? WHERE key=?", (code, job_key))

    def _audit(self, db, now, action, evidence, detail):
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 500:
            raise ValueError('Short non-secret operator evidence required')
        db.execute('INSERT INTO quota_audit(at,action,evidence,detail) VALUES(?,?,?,?)',
                   (aware(now).timestamp(), action, evidence, json.dumps(detail, sort_keys=True)))

    def _offline(self, db, now):
        stamp = aware(now).timestamp()
        if db.execute('SELECT 1 FROM lease WHERE until_at>?', (stamp,)).fetchone():
            raise Refused('Stop worker and wait for its lease to expire before reconciliation')
        if db.execute("SELECT 1 FROM attempts WHERE state='inflight'").fetchone() or db.execute("SELECT 1 FROM quota_inventory WHERE state='inflight'").fetchone():
            raise Refused('Inflight requests require lease recovery first')

    def bind(self, cycle, key_hash, used, remaining, offsets, now, evidence):
        if used + remaining != TOTAL or type(used) is not int or type(remaining) is not int or used < 0 or remaining <= PROTECTED:
            raise Refused('Invalid provider cycle quota')
        if set(offsets) != set(POOLS) or any(type(v) is not int or not 0 <= v <= POOLS[k] for k, v in offsets.items()) or sum(offsets.values()) != used:
            raise Refused('Allocate all preexisting usage explicitly within pool limits')
        if len(key_hash) != 64 or any(c not in '0123456789abcdef' for c in key_hash):
            raise ValueError('Invalid credential identity')
        with self.transaction() as db:
            self._offline(db, now)
            if not db.execute('SELECT 1 FROM cycles WHERE id=? AND starts<=? AND ends>?', (cycle, now.timestamp(), now.timestamp())).fetchone():
                raise Refused('Explicit current billing cycle required')
            if db.execute('SELECT 1 FROM quota_bindings WHERE cycle_id=?', (cycle,)).fetchone() or db.execute('SELECT 1 FROM attempts WHERE cycle_id=?', (cycle,)).fetchone():
                raise Refused('Existing cycle cannot be rebound or reset')
            db.execute('INSERT INTO quota_bindings VALUES(?,?,?,?,?)',
                       (cycle, key_hash, used, now.timestamp(), json.dumps(offsets)))
            db.execute('INSERT INTO quota_policy VALUES(?,?,?,?,?)',(cycle,BUDGET_VERSION,json.dumps(POOLS,sort_keys=True),TOTAL,PROTECTED))
            self._audit(db, now, 'bind', evidence, {'cycle': cycle, 'used': used, 'offsets': offsets})

    def accounted(self, db, cycle):
        sums = super().accounted(db, cycle)
        row = db.execute('SELECT offsets FROM quota_bindings WHERE cycle_id=?', (cycle,)).fetchone()
        if row:
            for pool, amount in json.loads(row[0]).items():
                sums[pool] = sums.get(pool, 0) + amount
        metadata = db.execute('SELECT coalesce(sum(coalesce(actual,1)),0) FROM quota_inventory WHERE cycle_id=?', (cycle,)).fetchone()[0]
        sums['metadata'] = sums.get('metadata', 0) + metadata
        return sums

    def _binding(self, db, now):
        row = db.execute('SELECT b.* FROM quota_bindings b JOIN cycles c ON c.id=b.cycle_id WHERE c.starts<=? AND c.ends>?', (now.timestamp(), now.timestamp())).fetchone()
        if row is None:
            raise Refused('No bound provider billing cycle')
        policy=db.execute('SELECT version,limits_json,total,protected FROM quota_policy WHERE cycle_id=?',(row['cycle_id'],)).fetchone()
        if not policy or policy[0]!=BUDGET_VERSION or json.loads(policy[1])!=POOLS or policy[2]!=TOTAL or policy[3]!=PROTECTED:
            raise Refused('Budget policy missing or changed; explicit review required, never reset the cycle')
        return row

    def authorize(self, owner, now, key_hash, *, inventory=False):
        with self.transaction() as db:
            self._fence(db, owner, now.timestamp())
            row = self._binding(db, now)
            if row['key_hash'] != key_hash:
                raise Refused('Provider credential differs from bound cycle')
            if db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]:
                raise Refused('Collection paused')
            if db.execute("SELECT 1 FROM attempts WHERE state='unknown'").fetchone() or db.execute("SELECT 1 FROM quota_inventory WHERE state IN ('unknown','inflight')").fetchone():
                raise Refused('Uncertain prior provider request')
            if not inventory and not 0 <= now.timestamp() - row['checked'] < 300:
                raise Refused('Fresh provider quota confirmation required')
            amounts = self.accounted(db, row['cycle_id'])
            if sum(amounts.values()) >= TOTAL - PROTECTED or TOTAL - row['used'] <= PROTECTED:
                raise Refused('Protected reserve reached')
            if inventory:
                if amounts.get('metadata', 0) >= POOLS['metadata']:
                    raise Refused('Metadata pool exhausted')
                token = secrets.token_hex(24)
                db.execute("INSERT INTO quota_inventory VALUES(?,?,?,?, 'inflight',NULL)",
                           (token, row['cycle_id'], owner, now.timestamp()))
                return token

    def _check(self, db, now, headers):
        row = self._binding(db, now)
        used, remaining, actual = quota_headers(headers)
        if used != row['used'] + actual:
            raise Refused('Provider quota drift; no automatic baseline adjustment')
        if remaining <= PROTECTED:
            raise Refused('Provider protected reserve reached')
        db.execute('UPDATE quota_bindings SET used=?,checked=? WHERE cycle_id=?',
                   (used, now.timestamp(), row['cycle_id']))
        return actual

    def inventory_finish(self, token, owner, now, headers, status):
        reason = ''
        with self.transaction() as db:
            self._fence(db, owner, now.timestamp())
            row = db.execute("SELECT * FROM quota_inventory WHERE token=? AND owner=? AND state='inflight'", (token, owner)).fetchone()
            if not row:
                raise Refused('Inventory permit already used or missing')
            try:
                actual = self._check(db, now, headers)
            except Refused as error:
                actual = None
                reason = str(error)
            else:
                if actual != 0 or status != 200:
                    reason = 'Inventory endpoint charged credits or returned an error'
            db.execute('UPDATE quota_inventory SET state=?,actual=? WHERE token=?',
                       ('unknown' if actual is None else 'settled', actual, token))
            if reason:
                db.execute('UPDATE controls SET paused=? WHERE id=1', (reason,))
            self._audit(db, now, 'inventory', 'provider response', {'token': token, 'actual': actual, 'reason': reason})
        if reason:
            raise Refused(reason)

    def inventory_unknown(self, token, owner, now):
        with self.transaction() as db:
            self._fence(db, owner, now.timestamp())
            db.execute("UPDATE quota_inventory SET state='unknown' WHERE token=? AND owner=? AND state='inflight'", (token, owner))
            db.execute("UPDATE controls SET paused='Uncertain inventory response' WHERE id=1")

    def acquire(self, owner, now, seconds=120):
        acquired = super().acquire(owner, now, seconds)
        if acquired:
            with self.transaction() as db:
                if db.execute("SELECT 1 FROM quota_inventory WHERE state='inflight' AND (owner<>? OR started<=?)", (owner, now.timestamp() - seconds)).fetchone():
                    db.execute("UPDATE quota_inventory SET state='unknown' WHERE state='inflight'")
                    db.execute("UPDATE controls SET paused='Uncertain inventory request after worker recovery' WHERE id=1")
        return acquired

    def finish(self, job, token, owner, now, headers, payload, status=200):
        reason = ''
        with self.transaction() as db:
            self._fence(db, owner, now.timestamp())
            if not db.execute("SELECT 1 FROM attempts WHERE token=? AND owner=? AND state='inflight'", (token, owner)).fetchone():
                raise Refused('Unknown/completed reservation')
            try:
                self._check(db, now, headers)
            except Refused as error:
                reason = str(error)
                db.execute('UPDATE controls SET paused=? WHERE id=1', (reason,))
            actual = quota_headers(headers)[2] if not reason else None
            self._audit(db, now, 'odds-response', 'provider response',
                        {'token': token, 'reason': reason, 'actual': actual,
                         'http_status': status, 'charge_verified': not bool(reason)})
        # A crash between quota evidence and settlement conservatively leaves an
        # unknown reservation. Quota drift must never publish a successful scope.
        def rejected(code):
            with self.transaction() as db:
                self._fence(db, owner, now.timestamp())
                attempt = db.execute("SELECT reserved FROM attempts WHERE token=? AND state='inflight'", (token,)).fetchone()
                if not attempt or actual is None or actual > attempt[0]:
                    raise Refused('Unverified charge cannot be quarantined automatically')
                db.execute("UPDATE attempts SET state='settled',actual=?,finished=? WHERE token=?", (actual, now.timestamp(), token))
                encoded = json.dumps(payload, separators=(',', ':'))
                self.quarantine(db, job.key, token, now, code,
                                {'kind': job.kind, 'sport': job.sport, 'event_id': job.event_id,
                                 'actual': actual, 'http_status': status,
                                 'payload': payload if len(encoded.encode()) <= 1048576 else None})
                if job.kind == 'live':
                    db.execute('UPDATE live_captures SET captured=0 WHERE sport=? AND book_group=?',(job.sport,job.group))
                for book in job.books:
                    for market in job.response_markets:
                        db.execute('UPDATE snapshots SET expires_at=min(expires_at,?) WHERE kind=? AND sport=? AND book=? AND market=?' +
                                   (' AND event_id=?' if job.event_id else ''),
                                   (now.timestamp(),job.kind,job.sport,book,market) + ((job.event_id,) if job.event_id else ()))
                self._audit(db, now, 'quarantine', 'Verified provider charge; invalid scope excluded',
                            {'token': token, 'job_key': job.key, 'code': code, 'actual': actual})
            return 'quarantined'

        reservation = self.db.execute('SELECT reserved FROM attempts WHERE token=?', (token,)).fetchone()[0]
        if not reason and actual <= reservation and status in (400, 404, 422):
            return rejected('provider_scope_rejected')
        try:
            result = super().finish(job, token, owner, now, headers, payload, 503 if reason else status)
        except (ValueError, TypeError, KeyError, AttributeError, sqlite3.IntegrityError) as error:
            if reason or isinstance(error, Refused) or actual is None or actual > reservation:
                raise
            codes = {'Mismatched event': 'event_mismatch', 'Mismatched props event': 'event_mismatch',
                     'Unexpected bookmaker': 'book_mismatch', 'Unexpected market': 'market_mismatch',
                     'Future provider timestamp': 'future_source_timestamp', 'Expected event list': 'invalid_envelope'}
            return rejected(codes.get(str(error), 'snapshot_' + type(error).__name__))
        if reason:
            with self.transaction() as db:
                self._fence(db, owner, now.timestamp())
                db.execute('UPDATE controls SET paused=? WHERE id=1', (reason,))
        return result

    def reconcile(self, now, used, remaining, offsets, settlements, inventory, evidence):
        """Offline operator-only accounting. Never publishes or re-dates a quote.

        settlements/inventory map unresolved tokens to externally verified costs.
        Missing evidence is not evidence of zero cost. Existing offsets cannot
        decrease, and total accounted usage must equal current provider usage.
        """
        if type(used) is not int or type(remaining) is not int or used < 0 or remaining < 0 or used + remaining != TOTAL:
            raise Refused('Invalid verified provider quota')
        with self.transaction() as db:
            self._offline(db, now)
            binding = self._binding(db, now)
            if used < binding['used']:
                raise Refused('Quota went backwards; verify billing cycle, never reset automatically')
            old_offsets = json.loads(binding['offsets'])
            if set(offsets) != set(POOLS) or any(type(v) is not int or v < old_offsets[k] or v > POOLS[k] for k, v in offsets.items()):
                raise Refused('External usage allocations cannot decrease or exceed pool limits')
            changed = []
            for table, values in (('attempts', settlements), ('quota_inventory', inventory)):
                for token, actual in values.items():
                    if type(actual) is not int or actual < 0:
                        raise Refused('Verified costs must be nonnegative integers')
                    row = db.execute('SELECT * FROM ' + table + " WHERE token=? AND state='unknown' AND cycle_id=?", (token, binding['cycle_id'])).fetchone()
                    if not row:
                        raise Refused('Only unresolved requests in the current cycle may be reconciled')
                    db.execute('UPDATE ' + table + " SET state='settled',actual=? WHERE token=?", (actual, token))
                    changed.append({'kind': table, 'token': token, 'actual': actual})
            if db.execute("SELECT 1 FROM attempts WHERE state='unknown'").fetchone() or db.execute("SELECT 1 FROM quota_inventory WHERE state='unknown'").fetchone():
                raise Refused('All uncertain requests must be accounted before reconciliation')
            db.execute('UPDATE quota_bindings SET offsets=?,used=?,checked=? WHERE cycle_id=?',
                       (json.dumps(offsets), used, now.timestamp(), binding['cycle_id']))
            amounts = self.accounted(db, binding['cycle_id'])
            if sum(amounts.values()) != used or any(v > POOLS[k] for k, v in amounts.items()):
                raise Refused('Ledger/pool allocation does not match verified provider usage')
            self._audit(db, now, 'reconcile', evidence,
                        {'cycle': binding['cycle_id'], 'used': used, 'offsets': offsets,
                         'old_offsets': old_offsets, 'settlements': changed})
            db.execute("UPDATE controls SET paused='Reconciled; explicit operator resume required' WHERE id=1")

    def resume(self, now, evidence):
        with self.transaction() as db:
            self._offline(db, now)
            latest = db.execute('SELECT action FROM quota_audit ORDER BY id DESC LIMIT 1').fetchone()
            if latest is None or latest[0] != 'reconcile':
                raise Refused('Explicit quota reconciliation must immediately precede resume')
            row = self._binding(db, now)
            if not 0 <= now.timestamp() - row['checked'] < 300:
                raise Refused('Fresh offline quota reconciliation required')
            if db.execute("SELECT 1 FROM attempts WHERE state IN ('unknown','inflight')").fetchone() or db.execute("SELECT 1 FROM quota_inventory WHERE state IN ('unknown','inflight')").fetchone():
                raise Refused('Unresolved requests prohibit resume')
            amounts = self.accounted(db, row['cycle_id'])
            if sum(amounts.values()) != row['used'] or row['used'] >= TOTAL - PROTECTED or any(v > POOLS[k] for k, v in amounts.items()):
                raise Refused('Quota reconciliation or reserve check failed')
            # Do not replay missed ticks or invent a successful capture.
            db.execute("UPDATE jobs SET state='idle' WHERE state='blocked'")
            db.execute("UPDATE controls SET paused='' WHERE id=1")
            self._audit(db, now, 'resume', evidence, {'cycle': row['cycle_id'], 'used': row['used']})
