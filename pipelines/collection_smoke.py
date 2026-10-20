"""Explicit one-shot, at-most-three-credit main-market commissioning test.

Never clears the collector pause or enables a service. A durable singleton
prevents a second purchase, including after a crash or an empty response.
"""
import argparse
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess

from dotenv import dotenv_values
from corner.collection_activation import APPROVAL, ROOT, STATE, RETAINED
from corner.collection_maintenance import maintenance_lock
from corner.collection_policy import Job, STANDARD, SPORTS, TOTAL, parse, open_now
from corner.collection_quota import LiveGovernor, key_identity
from corner.credit_governor import Refused
from pipelines import collection_onboarding as onboarding
from pipelines.collection_live import writer
from pipelines.collection_provider import Provider
from pipelines.collection_publication import MainPublisher
from pipelines.recovery_probe import reject_collectors, write_private


def clock():
    return datetime.now(timezone.utc)


def preflight():
    if os.name != 'posix' or Path.cwd().resolve() != ROOT:
        raise Refused('Run from the VPS application directory')
    values = onboarding.disabled_config()
    stage = dotenv_values(onboarding.STAGING)
    billing_path = stage.get('CORNER_BILLING_CONFIG')
    if billing_path and json.loads(Path(billing_path).read_text()).get('payments_enabled') is True:
        raise Refused('Checkout must remain disabled during commissioning')
    expected = {'CORNER_COLLECTION_DB': str(STATE),
                'CORNER_COLLECTION_RETAINED': str(RETAINED),
                'CORNER_COLLECTION_DB_HOST': '127.0.0.1',
                'CORNER_COLLECTION_DB_PORT': '5432',
                'CORNER_COLLECTION_DB_NAME': 'corner_staging',
                'CORNER_COLLECTION_DB_USER': 'corner_collection_writer'}
    if any(values.get(k) != v for k, v in expected.items()) or not values.get('ODDS_API_KEY'):
        raise Refused('Dedicated disabled worker configuration required')
    onboarding.private_file(STATE)
    if APPROVAL.exists() and json.loads(APPROVAL.read_text()).get('approved') is True:
        raise Refused('Recurring activation approval must remain disabled')
    listing = subprocess.check_output(['systemctl', 'list-unit-files', '--type=service,timer',
                                      '--no-legend', '--no-pager'], text=True,
                                     stderr=subprocess.DEVNULL, timeout=15)
    reject_collectors(listing)
    for path in (RETAINED, RETAINED/'smoke', RETAINED/'smoke'/'result.json'):
        if path.is_symlink():
            raise Refused('Retained path symlink refused')
    return values


def prepare(g):
    g.db.execute('''CREATE TABLE IF NOT EXISTS commissioning_smoke(
        id INTEGER PRIMARY KEY CHECK(id=1), token TEXT UNIQUE NOT NULL REFERENCES attempts(token),
        job TEXT NOT NULL, created REAL NOT NULL)''')


def reserve(g, owner, now, key, job, quota):
    """Only this explicit permit may buy while paused; normal authorize is unchanged."""
    job.validate()
    if job.kind != 'main' or job.group != 'standard' or job.cost != 3 or not open_now(now):
        raise Refused('One standard three-market request during collection hours only')
    if (quota.get('provider_used') != 0 or quota.get('provider_remaining') != TOTAL
            or quota.get('last_request_charge') != 0
            or not 0 <= (now-parse(quota['checked_at_utc'])).total_seconds() < 60):
        raise Refused('Fresh zero-usage provider quota required')
    with g.transaction() as db:
        g._fence(db, owner, now.timestamp())
        binding = g._binding(db, now)
        if binding['key_hash'] != key_identity(key) or binding['used'] != 0:
            raise Refused('Bound credential or usage changed')
        if (not db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]
                or db.execute('SELECT 1 FROM attempts').fetchone()
                or db.execute('SELECT 1 FROM commissioning_smoke').fetchone()
                or db.execute('SELECT 1 FROM quota_inventory').fetchone()):
            raise Refused('Initial paused, unused ledger required; never reset accounting')
        token = secrets.token_hex(24)
        stamp = now.timestamp()
        db.execute("INSERT INTO jobs(key,next_due,state,last_started) VALUES(?,?,'inflight',?)",
                   (job.key, stamp+60, stamp))
        db.execute("INSERT INTO attempts(token,job_key,cycle_id,pool,reserved,state,owner,started) VALUES(?,?,?,'main',3,'inflight',?,?)",
                   (token, job.key, binding['cycle_id'], owner, stamp))
        db.execute('INSERT INTO commissioning_smoke VALUES(1,?,?,?)',
                   (token, json.dumps(asdict(job)), stamp))
        g._audit(db, now, 'commissioning-reservation', 'Owner-authorized one-shot maximum three credits',
                 {'token': token, 'sport': job.sport, 'ceiling': 3})
        return token


def dispatch(g, provider, owner, job, token, now):
    """Commit the spent permit before HTTP; no retry if the result is uncertain."""
    job.validate()
    provider.gate()
    if not g.acquire(owner, now):
        raise Refused('One-shot lease was lost before dispatch')
    with g.transaction() as db:
        g._fence(db, owner, now.timestamp())
        row = db.execute("SELECT * FROM attempts WHERE token=? AND owner=? AND state='inflight'",
                         (token, owner)).fetchone()
        permit = db.execute('SELECT token,job FROM commissioning_smoke WHERE id=1').fetchone()
        if (row is None or permit is None or permit[0] != token
                or json.loads(permit[1]) != json.loads(json.dumps(asdict(job)))
                or row['reserved'] != 3 or row['job_key'] != job.key
                or not 0 <= now.timestamp()-row['started'] < 5
                or db.execute('SELECT 1 FROM dispatches WHERE token=?', (token,)).fetchone()):
            raise Refused('One-shot permit missing, expired, or already dispatched')
        db.execute('INSERT INTO dispatches VALUES(?,?)', (token, now.timestamp()))
    params = {'bookmakers': ','.join(job.books), 'markets': ','.join(job.markets),
              'oddsFormat': 'decimal', 'dateFormat': 'iso', 'includeLinks': 'true', 'includeSids': 'true',
              'commenceTimeFrom': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
              'commenceTimeTo': (now+timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')}
    return provider._get('/'+job.sport+'/odds', params)


def publish_replay(g, publisher, connect, now):
    row = g.db.execute('SELECT o.* FROM publication_outbox o JOIN commissioning_smoke s ON s.token=o.token WHERE s.id=1').fetchone()
    if row is None:
        raise Refused('No successful captured response to publish; no repeat purchase allowed')
    record = json.loads(row['payload'])
    publisher(row['token'], record)

    def counts():
        with closing(connect()) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT (SELECT count(*) FROM corner.provider_payloads), '
                            '(SELECT count(*) FROM corner.odds_observations), '
                            '(SELECT count(*) FROM corner.quote_links)')
                return tuple(cur.fetchone())
    before = counts()
    publisher(row['token'], record)
    if counts() != before:
        raise Refused('Publication replay changed payload, observation or link totals')
    with g.transaction() as db:
        db.execute('UPDATE publication_outbox SET published_at=coalesce(published_at,?) WHERE token=?',
                   (now.timestamp(), row['token']))
    return len(record['events'])


@contextmanager
def authority_environment():
    changes = {'CORNER_PRIVATE_BETA': '1', 'CORNER_COLLECTION_DB': str(STATE)}
    old = {k: os.environ.get(k) for k in changes}
    os.environ.update(changes)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def reader_check():
    import psycopg2
    from api.database import LiveCatalog
    from api.app import create_app
    from fastapi.testclient import TestClient
    values = dotenv_values(onboarding.STAGING)

    def connect():
        conn = psycopg2.connect(host=values['DB_HOST'], port=values['DB_PORT'],
                               dbname=values['DB_NAME'], user=values['DB_USER'],
                               password=values['DB_PASSWORD'], connect_timeout=5,
                               options='-c statement_timeout=15000')
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(),current_user,has_table_privilege(current_user,'corner.odds_observations','INSERT'),has_table_privilege(current_user,'corner.provider_payloads','SELECT')")
                database, user, writes, raw = cur.fetchone()
                if database != 'corner_staging' or user == 'corner_collection_writer' or writes or raw:
                    raise Refused('Restricted staging feed reader required')
            conn.rollback()
            return conn
        except BaseException:
            conn.close()
            raise
    with authority_environment():
        catalog = LiveCatalog(connect)
        app = create_app(data_mode='database', catalog=catalog,
                         session_check=lambda token: token == 'isolated-smoke-session')
        with TestClient(app, base_url='http://127.0.0.1') as client:
            if client.get('/api/v1/quotes').status_code != 401:
                raise Refused('Anonymous quote access was not denied')
            client.cookies.set('corner_session', 'isolated-smoke-session')
            response = client.get('/api/v1/quotes')
            if response.status_code != 200:
                raise Refused('Session-gated quote API failed')
            count = len(catalog.quotes)
            return {'restricted_reader_quotes': count, 'fresh_quotes_visible': count > 0,
                    'api_auth_harness': 'passed', 'public_member_journey': 'not tested by this harness'}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-three-credit-smoke', action='store_true')
    parser.add_argument('--sport', choices=SPORTS, default='icehockey_nhl')
    args = parser.parse_args()
    g = provider = None
    owner = secrets.token_hex(16)
    step = 'disabled_preflight'
    try:
        values = preflight()
        with maintenance_lock(exclusive=True):
            values = preflight()
            g = LiveGovernor(STATE)
            if not g.db.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]:
                raise Refused('Collector must remain paused')
            g._binding(g.db, clock())
            step = 'writer_and_reader_preflight'
            conn = writer(values)
            conn.close()
            reader_check()  # verify reader privileges and auth boundary before buying
            if not open_now(clock()):
                raise Refused('The commissioning request must run during the 16-hour collection window')
            if not args.execute_three_credit_smoke:
                print(json.dumps({'result': 'ready_for_explicit_three_credit_smoke', 'provider_calls': 0,
                                  'collector_paused': True, 'worker_started': False}))
                return 0
            if not g.acquire(owner, clock()):
                raise Refused('Another lease is active')
            prepare(g)
            prior = g.db.execute('SELECT * FROM commissioning_smoke WHERE id=1').fetchone()
            paid_calls = 0
            if prior is None:
                step = 'zero_credit_quota_and_event_preflight'
                quota = onboarding.verify_key(values['ODDS_API_KEY'])
                provider = Provider(key=values['ODDS_API_KEY'], enabled=True, clock=clock)
                status, events, headers = provider._get('/'+args.sport+'/events', {'dateFormat': 'iso'})
                Provider._free_response(status, headers)
                if (headers.get('x-requests-used') != str(quota['provider_used'])
                        or headers.get('x-requests-remaining') != str(quota['provider_remaining'])
                        or not isinstance(events, list)
                        or not any(e.get('sport_key') == args.sport and clock() < parse(e['commence_time']) <= clock()+timedelta(hours=24) for e in events)):
                    raise Refused('No upcoming events or quota changed; no paid request made')
                job = Job('main', args.sport, 'standard', STANDARD, ('h2h','spreads','totals'))
                step = 'durable_three_credit_reservation'
                token = reserve(g, owner, clock(), values['ODDS_API_KEY'], job, quota)
                step = 'one_shot_odds_dispatch'
                try:
                    status, payload, headers = dispatch(g, provider, owner, job, token, clock())
                    paid_calls = 1
                    result = g.finish(job, token, owner, clock(), headers, payload, status)
                    if result != 'published':
                        raise Refused('Provider response not publishable; no retry')
                except BaseException:
                    if g.db.execute("SELECT 1 FROM attempts WHERE token=? AND state='inflight'", (token,)).fetchone():
                        g.unknown(token, owner, clock())
                    raise
            else:
                attempt = g.db.execute('SELECT state FROM attempts WHERE token=?', (prior['token'],)).fetchone()
                if attempt is None or attempt[0] != 'settled':
                    raise Refused('Uncertain prior smoke; reconcile privately, never purchase again')
            step = 'restricted_writer_publication_and_replay'
            connect = lambda: writer(values)
            event_count = publish_replay(g, MainPublisher(RETAINED, connect), connect, clock())
            step = 'restricted_reader_feed_verification'
            feed = reader_check()
            result = dict(result='smoke_passed' if feed['fresh_quotes_visible'] else 'publication_passed_freshness_incomplete',
                          paid_odds_calls_this_run=paid_calls, lifetime_paid_request_limit=1, reserved_credit_ceiling=3,
                          provider_used=g._binding(g.db, clock())['used'], captured_events=event_count,
                          replay_counts_unchanged=True, collector_paused=True, worker_started=False,
                          historical_calls=0, recurring_activation=False, **feed)
            write_private(RETAINED/'smoke'/'result.json', result)
            print(json.dumps(result, indent=2))
            return 0 if feed['fresh_quotes_visible'] else 1
    except (Exception, KeyboardInterrupt):
        print(json.dumps({'result': 'refused', 'step': step, 'automatic_retry': False,
                          'action': 'Preserve ledger and retained captures; do not reset the one-shot permit.'}))
        return 1
    finally:
        if provider:
            provider.close()
        if g:
            try:
                g.release(owner)
            except Refused:
                pass
            g.close()


if __name__ == '__main__':
    raise SystemExit(main())
