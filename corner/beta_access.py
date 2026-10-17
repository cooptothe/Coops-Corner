"""Private beta access. Mutations run in the caller's BEGIN IMMEDIATE transaction.

Invites reserve one of ten member seats. Suspension retains its seat; explicit
closure releases it. Only hashed, expiring, identity-bound invite codes persist.
An operator issues paid invites only after independently verifying the receipt.
"""
import hashlib
import os
import secrets
import time

from corner.tracker_store import TrackerError

LIMIT = 10


def enabled():
    value = os.environ.get('CORNER_PRIVATE_BETA', '0')
    if value not in ('0', '1'):
        raise RuntimeError('CORNER_PRIVATE_BETA must be 0 or 1.')
    return value == '1'


def fail(message, code='access_denied', status=403):
    raise TrackerError(message, status, code)


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS beta_members (
      user_id TEXT PRIMARY KEY REFERENCES users(id),
      role TEXT NOT NULL CHECK(role IN ('admin','member')),
      state TEXT NOT NULL CHECK(state IN ('active','suspended','closed')),
      founder INTEGER NOT NULL DEFAULT 0 CHECK(founder IN (0,1)),
      access_kind TEXT NOT NULL CHECK(access_kind IN ('operator','paid_beta','preview')),
      evidence TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS beta_one_admin
      ON beta_members(role) WHERE role='admin';
    CREATE TABLE IF NOT EXISTS beta_invites (
      id TEXT PRIMARY KEY,
      token_hash TEXT NOT NULL UNIQUE,
      username_key TEXT NOT NULL,
      expires_at REAL NOT NULL,
      revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
      redeemed_by TEXT REFERENCES users(id),
      access_kind TEXT NOT NULL CHECK(access_kind IN ('paid_beta','preview')),
      evidence TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS beta_trials (
      user_id TEXT PRIMARY KEY REFERENCES users(id),
      started_at REAL NOT NULL,
      started_by TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS beta_audit (
      id INTEGER PRIMARY KEY,
      actor TEXT NOT NULL,
      action TEXT NOT NULL,
      subject TEXT NOT NULL,
      detail TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    ''')


def audit(db, actor, action, subject, detail=''):
    db.execute('INSERT INTO beta_audit(actor,action,subject,detail,created_at) VALUES(?,?,?,?,?)',
               (actor, action, subject, detail, time.time()))


def occupied(db, now=None):
    now = time.time() if now is None else now
    members = db.execute("SELECT count(*) FROM beta_members WHERE role='member' AND state!='closed'").fetchone()[0]
    invites = db.execute('SELECT count(*) FROM beta_invites WHERE revoked=0 AND redeemed_by IS NULL AND expires_at>?', (now,)).fetchone()[0]
    return members + invites


def decorate(db, row):
    if row is None or not enabled():
        return row
    row = dict(row)
    membership = db.execute('SELECT role,state,founder,access_kind FROM beta_members WHERE user_id=?', (row['id'],)).fetchone()
    row.update(beta_role=membership[0] if membership else None,
               beta_state=membership[1] if membership else None,
               beta_founder=bool(membership[2]) if membership else False,
               beta_access_kind=membership[3] if membership else None)
    if trials_enabled():
        trial = db.execute('SELECT started_at FROM beta_trials WHERE user_id=?', (row['id'],)).fetchone()
        row['beta_trial_started_at'] = trial[0] if trial else None
        row['beta_member_created_at'] = db.execute('SELECT created_at FROM beta_members WHERE user_id=?', (row['id'],)).fetchone()[0] if membership else None
    return row


def trials_enabled():
    value = os.environ.get('CORNER_BETA_TRIALS', '0')
    if value not in ('0', '1'):
        raise RuntimeError('CORNER_BETA_TRIALS must be 0 or 1.')
    return enabled() and value == '1'


def access_status(row, now=None):
    from corner import beta_terms
    if not trials_enabled():
        return {'state': 'preview', 'expires_at': None, 'allowed': active(row), 'enforced': False}
    if not active(row):
        return {'state': 'unavailable', 'expires_at': None, 'allowed': False, 'enforced': True}
    kind = row.get('beta_access_kind')
    start = row.get('beta_trial_started_at') if kind == 'preview' else row.get('beta_member_created_at')
    if kind != 'operator' and start is None:
        result = {'state': 'not_started', 'expires_at': None}
    else:
        result = beta_terms.entitlement(kind, start or 0, time.time() if now is None else now)
    return {**result, 'allowed': result['state'] in ('operator', 'trial', 'paid'), 'enforced': True}


def start_trial(db, actor, username_key):
    from corner import beta_terms
    require_operator(db, actor)
    member = db.execute("SELECT m.user_id FROM beta_members m JOIN users u ON u.id=m.user_id WHERE u.username_key=? AND m.state='active' AND m.access_kind='preview'", (username_key,)).fetchone()
    if not member:
        fail('An active preview member is required.', status=409)
    existing = db.execute('SELECT started_at FROM beta_trials WHERE user_id=?', (member[0],)).fetchone()
    if existing:
        return existing[0]
    now = time.time()
    if not beta_terms.trial_available(now):
        fail('A full two-day trial is no longer available.', status=409)
    db.execute('INSERT INTO beta_trials VALUES(?,?,?)', (member[0], now, actor))
    audit(db, actor, 'start_trial', member[0])
    return now


def active(row):
    return not enabled() or bool(row and row.get('beta_state') == 'active' and row.get('beta_role') in ('admin', 'member'))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def enroll(db, user_id, username_key, token):
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        fail('A valid private beta invitation is required.', 'invite_required')
    invite = db.execute('SELECT * FROM beta_invites WHERE token_hash=?', (digest(token),)).fetchone()
    now = time.time()
    if (not invite or invite['revoked'] or invite['redeemed_by'] or invite['expires_at'] <= now
            or invite['username_key'] != username_key):
        fail('This invitation is invalid, expired, or belongs to another username.', 'invalid_invite')
    if occupied(db, now) > LIMIT:
        fail('The private beta is full.', 'beta_full', 409)
    paid = invite['access_kind'] == 'paid_beta'
    db.execute('INSERT INTO beta_members VALUES(?,?,?,?,?,?,?)',
               (user_id, 'member', 'active', int(paid), invite['access_kind'], invite['evidence'], now))
    if not paid and trials_enabled():
        from corner import beta_terms
        if not beta_terms.trial_available(now):
            fail('A full two-day trial is no longer available.', status=409)
        db.execute('INSERT INTO beta_trials VALUES(?,?,?)', (user_id, now, user_id))
    db.execute('UPDATE beta_invites SET redeemed_by=? WHERE id=?', (user_id, invite['id']))
    audit(db, user_id, 'redeem_invite', invite['id'])


def require_operator(db, actor):
    row = db.execute("SELECT 1 FROM beta_members WHERE user_id=? AND role='admin' AND state='active'", (actor,)).fetchone()
    if not row:
        fail('An active operator account is required.')


def bootstrap(db, username_key):
    """Only the server operator can invoke this CLI action; never called by signup."""
    user = db.execute('SELECT id FROM users WHERE username_key=?', (username_key,)).fetchone()
    if not user:
        fail('Create the intended staging account before bootstrapping.', status=404)
    if db.execute("SELECT 1 FROM beta_members WHERE role='admin'").fetchone():
        fail('An operator is already assigned; no automatic replacement.', status=409)
    if db.execute('SELECT 1 FROM beta_members WHERE user_id=?', (user[0],)).fetchone():
        fail('This account already has a membership.', status=409)
    db.execute('INSERT INTO beta_members VALUES(?,?,?,?,?,?,?)',
               (user[0], 'admin', 'active', 0, 'operator', 'server bootstrap', time.time()))
    db.execute('UPDATE users SET session_epoch=session_epoch+1 WHERE id=?', (user[0],))
    audit(db, 'server_operator', 'bootstrap', user[0])
    return user[0]


def issue(db, actor, username_key, *, hours=48, access_kind, evidence):
    require_operator(db, actor)
    if not isinstance(hours, int) or not 1 <= hours <= 168:
        fail('Invitation lifetime must be 1-168 hours.', status=400)
    if access_kind not in ('paid_beta', 'preview') or not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 300:
        fail('Record paid receipt verification or an explicit preview reason.', status=400)
    if db.execute('SELECT 1 FROM users WHERE username_key=?', (username_key,)).fetchone():
        fail('That username exists; grant the existing account explicitly.', status=409)
    if db.execute('SELECT 1 FROM beta_invites WHERE username_key=? AND revoked=0 AND redeemed_by IS NULL AND expires_at>?', (username_key, time.time())).fetchone():
        fail('This username already has a live invitation.', status=409)
    if occupied(db) >= LIMIT:
        fail('All ten beta seats are active or reserved.', 'beta_full', 409)
    token = secrets.token_urlsafe(32)
    invite_id = secrets.token_hex(12)
    db.execute('INSERT INTO beta_invites(id,token_hash,username_key,expires_at,access_kind,evidence,created_at) VALUES(?,?,?,?,?,?,?)',
               (invite_id, digest(token), username_key, time.time()+hours*3600, access_kind, evidence.strip(), time.time()))
    audit(db, actor, 'issue_invite', invite_id, access_kind)
    return invite_id, token


def grant(db, actor, username_key, access_kind, evidence):
    require_operator(db, actor)
    if access_kind not in ('paid_beta', 'preview') or not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 300:
        fail('Record receipt verification or explicit preview reason.', status=400)
    user = db.execute('SELECT id FROM users WHERE username_key=?', (username_key,)).fetchone()
    if not user:
        fail('Account not found.', status=404)
    if db.execute('SELECT 1 FROM beta_members WHERE user_id=?', (user[0],)).fetchone():
        fail('Account already enrolled; use the state command.', status=409)
    if occupied(db) >= LIMIT:
        fail('All ten beta seats are active or reserved.', 'beta_full', 409)
    # Do not retain a second reserved invitation for this existing account.
    db.execute('INSERT INTO beta_members VALUES(?,?,?,?,?,?,?)',
               (user[0], 'member', 'active', int(access_kind == 'paid_beta'), access_kind, evidence.strip(), time.time()))
    db.execute('UPDATE users SET session_epoch=session_epoch+1 WHERE id=?', (user[0],))
    audit(db, actor, 'grant', user[0], access_kind)


def state(db, actor, username_key, value):
    require_operator(db, actor)
    if value not in ('active', 'suspended', 'closed'):
        fail('Unknown access state.', status=400)
    row = db.execute('SELECT m.* FROM beta_members m JOIN users u ON u.id=m.user_id WHERE u.username_key=?', (username_key,)).fetchone()
    if not row or row['role'] == 'admin':
        fail('Use a member account; operator access cannot be changed here.', status=409)
    if row['state'] == 'closed' and value != 'closed' and occupied(db) >= LIMIT:
        fail('All ten beta seats are active or reserved.', 'beta_full', 409)
    db.execute('UPDATE beta_members SET state=? WHERE user_id=?', (value, row['user_id']))
    db.execute('UPDATE users SET session_epoch=session_epoch+1 WHERE id=?', (row['user_id'],))
    audit(db, actor, 'state', row['user_id'], value)


def revoke(db, actor, invite_id):
    require_operator(db, actor)
    changed = db.execute('UPDATE beta_invites SET revoked=1 WHERE id=? AND redeemed_by IS NULL AND revoked=0', (invite_id,)).rowcount
    if not changed:
        fail('Unused invitation not found.', status=404)
    audit(db, actor, 'revoke_invite', invite_id)
