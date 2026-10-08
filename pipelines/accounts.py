"""Account endpoints (register, sign in, sign out, who am I) and the session check the other services share.

The session is a signed JWT in an HttpOnly, SameSite=Strict cookie, so page scripts never see it and
other sites cannot ride it. Writes must also come from the local UI origin, and every request must
address the loopback host (blocks DNS-rebinding pages).
"""
import os
from pathlib import Path
import threading

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from corner import auth
from corner.tracker_store import TrackerError, TrackerStore

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get('CORNER_TRACKER_DB') or ROOT / 'retained' / 'tracker.sqlite3')
SECRET_PATH = ROOT / 'retained' / 'auth_secret'
COOKIE = 'corner_session'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '[::1]'}
UNAUTHENTICATED = {'error': 'Sign in to continue.', 'code': 'auth_required'}


def host_ok(request):
    host = (request.headers.get('host') or '').lower()
    name = host.rsplit(':', 1)[0] if not host.startswith('[') else host.split(']')[0] + ']'
    return name in LOCAL_HOSTS


def reply(code, body, headers=None):
    return JSONResponse(body, status_code=code, headers={'Cache-Control': 'no-store', **(headers or {})})


class AuthContext:
    """The database, signing key and allowed origins shared by every service that needs a signed-in user."""

    def __init__(self, store=None, secret=None, allowed_origins=None):
        self._store, self._secret, self._origins = store, secret, allowed_origins
        self._lazy = threading.Lock()

    @property
    def store(self):
        with self._lazy:
            if self._store is None:
                self._store = TrackerStore(DB_PATH)
            return self._store

    @property
    def secret(self):
        with self._lazy:
            if self._secret is None:
                self._secret = auth.load_secret(SECRET_PATH)
            return self._secret

    @property
    def origins(self):
        if self._origins is not None:
            return self._origins
        from pipelines.refresh_service import ALLOWED_ORIGINS
        return ALLOWED_ORIGINS

    def user(self, request):
        """The signed-in account for this request ({id, username}), or None."""
        token = request.cookies.get(COOKIE)
        return auth.session_user(self.secret, token, self.store.user_by_id)

    def check(self, request, *, write):
        """None when the request may proceed, else the error response to send."""
        if not host_ok(request):
            return reply(403, {'error': 'Host not allowed.'})
        if write and request.headers.get('origin') not in self.origins:
            return reply(403, {'error': 'Origin not allowed.'})
        return None

    def require(self, request, *, write):
        """(user, None) for a signed-in request, or (None, error response)."""
        blocked = self.check(request, write=write)
        if blocked:
            return None, blocked
        user = self.user(request)
        if not user:
            return None, reply(401, UNAUTHENTICATED)
        return user, None


def _secure(request):
    return request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https'


def _set_session(response, request, secret, user, *, remember, epoch=0):
    """Remembered sessions get a 30-day cookie; otherwise a browser-session cookie (gone when the browser
    closes), and the token itself also expires after 12 hours."""
    token = auth.issue_token(secret, user['id'], user['username'], epoch=epoch, remember=remember)
    response.set_cookie(COOKIE, token, max_age=auth.REMEMBER_TTL if remember else None,
                        httponly=True, samesite='strict', secure=_secure(request), path='/')
    return response


def create_router(ctx, logins=None, signups=None):
    router = APIRouter(prefix='/api/refresh/v1/auth')
    logins = logins or auth.Throttle(limit=8, window=900, lockout=300)
    signups = signups or auth.Throttle(limit=20, window=3600, lockout=3600)

    async def credentials(request):
        try:
            body = await request.json()
        except ValueError:
            raise auth.AuthError('The request body must be JSON') from None
        if not isinstance(body, dict):
            raise auth.AuthError('The request body must be an object')
        return body.get('username'), body.get('password'), body.get('remember') is True

    def failure(error):
        headers = {'Retry-After': str(error.retry_after)} if error.retry_after else None
        return reply(error.status, {'error': str(error), 'code': error.code}, headers)

    @router.post('/register')
    async def register(request: Request):
        blocked = ctx.check(request, write=True)
        if blocked:
            return blocked
        client = request.client.host if request.client else 'unknown'
        try:
            wait = signups.retry_after(client)
            if wait:
                raise auth.AuthError('Too many accounts were created from here. Try again later.', 429, 'throttled', wait)
            signups.fail(client)  # every attempt counts toward the cap
            username, password, remember = await credentials(request)
            name, key = auth.clean_username(username)
            auth.check_password(password, name)
            hashed = await run_in_threadpool(auth.hash_password, password)
            user = await run_in_threadpool(ctx.store.create_user, name, key, hashed)
        except auth.AuthError as error:
            return failure(error)
        except TrackerError as error:
            return reply(error.status, {'error': str(error), 'code': error.code})
        return _set_session(reply(200, {'user': user}), request, ctx.secret, user, remember=remember)

    @router.post('/login')
    async def login(request: Request):
        blocked = ctx.check(request, write=True)
        if blocked:
            return blocked
        try:
            username, password, remember = await credentials(request)
            key = username.strip().lower() if isinstance(username, str) else ''
            wait = logins.retry_after(key)
            if wait:
                raise auth.AuthError('Too many failed attempts. Try again in a few minutes.', 429, 'throttled', wait)
            row = await run_in_threadpool(ctx.store.user_by_key, key) if key else None
            if row:
                ok = isinstance(password, str) and await run_in_threadpool(auth.verify_password, password, row['password_hash'])
            else:
                await run_in_threadpool(auth.burn_password_check, password)
                ok = False
            if not ok:
                logins.fail(key)
                raise auth.AuthError('Incorrect username or password.', 401, 'bad_credentials')
        except auth.AuthError as error:
            return failure(error)
        logins.clear(key)
        user = {'id': row['id'], 'username': row['username']}
        return _set_session(reply(200, {'user': user}), request, ctx.secret, user, remember=remember,
                            epoch=row['session_epoch'])

    @router.post('/password')
    async def change_password(request: Request):
        """Change your own password. Every other signed-in device is signed out; this one stays signed in."""
        user, denied = ctx.require(request, write=True)
        if denied:
            return denied
        key = user['username'].lower()
        try:
            try:
                body = await request.json()
            except ValueError:
                raise auth.AuthError('The request body must be JSON') from None
            if not isinstance(body, dict):
                raise auth.AuthError('The request body must be an object')
            wait = logins.retry_after(key)
            if wait:
                raise auth.AuthError('Too many failed attempts. Try again in a few minutes.', 429, 'throttled', wait)
            current, new = body.get('current'), body.get('new')
            row = await run_in_threadpool(ctx.store.user_by_id, user['id'])
            if not (isinstance(current, str) and row
                    and await run_in_threadpool(auth.verify_password, current, row['password_hash'])):
                logins.fail(key)
                raise auth.AuthError('Your current password is not correct.', 403, 'bad_credentials')
            auth.check_password(new, user['username'])
            if new == current:
                raise auth.AuthError('Choose a password different from your current one.', code='bad_password')
            hashed = await run_in_threadpool(auth.hash_password, new)
            epoch = await run_in_threadpool(ctx.store.set_password, user['id'], hashed)
        except auth.AuthError as error:
            return failure(error)
        except TrackerError as error:
            return reply(error.status, {'error': str(error), 'code': error.code})
        logins.clear(key)
        return _set_session(reply(200, {'ok': True}), request, ctx.secret, user, remember=user['remember'], epoch=epoch)

    @router.post('/logout')
    async def logout(request: Request):
        blocked = ctx.check(request, write=True)
        if blocked:
            return blocked
        response = reply(200, {'ok': True})
        response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict', secure=_secure(request))
        return response

    @router.get('/me')
    async def me(request: Request):
        blocked = ctx.check(request, write=False)
        if blocked:
            return blocked
        user = await run_in_threadpool(ctx.user, request)
        return reply(200, {'user': user}) if user else reply(401, UNAUTHENTICATED)

    return router
