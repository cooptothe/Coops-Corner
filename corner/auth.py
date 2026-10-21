"""Accounts for the local app: username rules, password hashing, signed session tokens, login throttling.

Pure and stdlib-only. Passwords are hashed with scrypt (memory-hard, salted, parameters stored with
the hash so they can be raised later). Session tokens are standard HS256 JWTs carrying the user id,
username and an expiry; only the signature algorithm we issue is accepted.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

REMEMBER_TTL = 30 * 86400  # "remember me": a persistent cookie
SESSION_TTL = 12 * 3600  # otherwise a browser-session cookie, which the server also stops honouring after 12 hours
USERNAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{2,23}$')
PASSWORD_MIN, PASSWORD_MAX = 8, 128
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
SECRET_ENV = 'CORNER_AUTH_SECRET'


class AuthError(ValueError):
    def __init__(self, message, status=400, code='invalid', retry_after=None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after


# -- usernames and passwords ------------------------------------------------------------------

def clean_username(value):
    """(display name, case-insensitive key). Usernames are unique regardless of letter case."""
    name = value.strip() if isinstance(value, str) else ''
    if not USERNAME.match(name):
        raise AuthError('Usernames are 3-24 characters: letters, numbers, dots, dashes and underscores, '
                        'starting with a letter or number.', code='bad_username')
    return name, name.lower()


def check_password(value, username=''):
    if not isinstance(value, str) or not PASSWORD_MIN <= len(value) <= PASSWORD_MAX:
        raise AuthError(f'Passwords must be {PASSWORD_MIN} to {PASSWORD_MAX} characters.', code='bad_password')
    if username and value.lower() == username.lower():
        raise AuthError('Your password cannot be the same as your username.', code='bad_password')
    return value


def _scrypt(password, salt, n, r, p):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=128 * n * r * 2 + 2 ** 20)


def _b64(raw):
    return base64.b64encode(raw).decode('ascii')


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}'


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, digest = stored.split('$')
        if scheme != 'scrypt':
            return False
        n, r, p = int(n), int(r), int(p)
        if not (2 ** 10 <= n <= 2 ** 20 and 1 <= r <= 16 and 1 <= p <= 4):
            return False
        expected = base64.b64decode(digest)
        actual = _scrypt(password, base64.b64decode(salt), n, r, p)
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY = hash_password(secrets.token_hex(8))


def burn_password_check(password):
    """Spend the same time as a real check, so an unknown username is not distinguishable by speed."""
    verify_password(password if isinstance(password, str) else '', _DUMMY)


# -- session tokens (JWT, HS256) --------------------------------------------------------------

def _url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _unurl(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _sign(secret, signing_input):
    return hmac.new(secret.encode('utf-8'), signing_input.encode('ascii'), hashlib.sha256).digest()


def issue_token(secret, user_id, username, *, epoch=0, remember=True, now=None, ttl=None):
    now = int(time.time() if now is None else now)
    ttl = ttl if ttl is not None else REMEMBER_TTL if remember else SESSION_TTL
    header = _url(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    claims = _url(json.dumps({'sub': user_id, 'usr': username, 'ep': epoch, 'rm': bool(remember), 'iat': now,
                              'exp': now + ttl}, separators=(',', ':')).encode())
    signing_input = f'{header}.{claims}'
    return f'{signing_input}.{_url(_sign(secret, signing_input))}'


def verify_token(secret, token, *, now=None):
    """The token's claims, or None when it is malformed, forged, uses another algorithm, or has expired."""
    try:
        header_part, claims_part, signature = token.split('.')
        header = json.loads(_unurl(header_part))
        if header.get('alg') != 'HS256':
            return None
        if not hmac.compare_digest(_sign(secret, f'{header_part}.{claims_part}'), _unurl(signature)):
            return None
        claims = json.loads(_unurl(claims_part))
        if not isinstance(claims.get('sub'), str) or not isinstance(claims.get('exp'), int):
            return None
        if claims['exp'] <= (time.time() if now is None else now):
            return None
        return claims
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return None


def session_user(secret, token, lookup, *, member_access_required=True):
    """The {id, username, remember} a session token stands for, or None.

    `lookup(user_id)` returns the stored account row (or None). A token stops working when the account is
    gone or its password was changed or reset (the account's session_epoch no longer matches the token's).
    """
    claims = verify_token(secret, token) if token else None
    row = lookup(claims['sub']) if claims else None
    from corner import beta_access
    if not row or not beta_access.active(row) or claims.get('ep', 0) != row.get('session_epoch', 0):
        return None
    membership = beta_access.access_status(row)
    if member_access_required and not membership['allowed']:
        return None
    user = {'id': row['id'], 'username': row['username'], 'remember': claims.get('rm', True) is not False}
    if beta_access.enabled() or row.get('beta_cohort')=='family':
        user.update(role=row.get('beta_role'), access_kind=row.get('beta_access_kind'), founder=row.get('beta_founder', False), cohort=row.get('beta_cohort'), friend_rates=row.get('beta_friend_rates'))
    if beta_access.trials_enabled() or (beta_access.enabled() and row.get('beta_cohort')=='friend') or row.get('beta_cohort')=='family':
        user['membership'] = membership
    return user


def load_secret(path):
    """The signing key: CORNER_AUTH_SECRET if set, else a random key created once next to the data."""
    env = os.environ.get(SECRET_ENV, '').strip()
    if env:
        if len(env) < 32:
            raise AuthError(f'{SECRET_ENV} must be at least 32 characters.')
        return env
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        text = path.read_text(encoding='utf-8').strip()
        if len(text) < 32:
            raise AuthError(f'{path} does not hold a valid signing key.') from None
        return text
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(secrets.token_hex(32))
    return path.read_text(encoding='utf-8').strip()


# -- throttling -------------------------------------------------------------------------------

class Throttle:
    """After `limit` failures inside `window` seconds a key is locked for `lockout` seconds. In memory."""

    def __init__(self, limit=8, window=900, lockout=300, clock=time.monotonic):
        self.limit, self.window, self.lockout, self._clock = limit, window, lockout, clock
        self._state = {}
        self._lock = threading.Lock()

    def retry_after(self, key):
        with self._lock:
            entry = self._state.get(key)
            if not entry:
                return 0
            left = entry['locked_until'] - self._clock()
            return int(left) + 1 if left > 0 else 0

    def fail(self, key):
        now = self._clock()
        with self._lock:
            if len(self._state) > 5000:
                self._state = {k: v for k, v in self._state.items() if v['locked_until'] > now or v['fails']
                               and now - v['fails'][-1] < self.window}
            entry = self._state.setdefault(key, {'fails': [], 'locked_until': 0})
            entry['fails'] = [t for t in entry['fails'] if now - t < self.window] + [now]
            if len(entry['fails']) >= self.limit:
                entry['locked_until'] = now + self.lockout
                entry['fails'] = []

    def clear(self, key):
        with self._lock:
            self._state.pop(key, None)
