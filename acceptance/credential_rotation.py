"""Disposable PostgreSQL rotation checks; no OS provisioning or implicit targets.

Passwords/verifiers stay in memory. Session revocation is restricted to a held,
identified probe session, never a broad termination of service-role sessions.
"""
from contextlib import closing
from datetime import datetime
import re
import secrets

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from corner import deployment as d, versioned_dispatch as dispatch, versioned_reconciliation as discovery
from run_scm_acceptance import require, wait_for


class Rotation:
    def __init__(self, fixture, report):
        self.fixture, self.report = fixture, report
        self.login = fixture.logins['execution']
        self.database = fixture.database_name
        require(re.fullmatch(r'corner_login_test_[0-9a-f]{16}', self.login), 'not a disposable LOGIN')
        require(re.fullmatch(r'corner_channels_test_[0-9a-f]{32}', self.database), 'not a disposable database')
        self.config = fixture.host_config('execution')
        require(self.config.value['database']['dbname'] == self.database, 'fixture target mismatch')
        self.old_secret = fixture.passwords['execution']
        self.new_secret = secrets.token_urlsafe(40)
        self.probe = None
        self.binding = None
        self.verifier = None
        self.report['session_rotation_policy'] = 'stop_drain_revoke_exact_residual_sessions_before_restart/1'

    def connect(self, secret, *, name='corner-rotation-auth-probe'):
        return psycopg2.connect(**self.config.value['database'], user=self.login, password=secret,
            connect_timeout=5, application_name=name, options='-c statement_timeout=5000')

    def role_fingerprint(self):
        with self.fixture.conn.cursor() as cur:
            cur.execute('SELECT current_database()')
            require(cur.fetchone()[0] == self.database, 'administrator target mismatch')
            cur.execute('''SELECT oid,rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,
                rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil::text,rolconfig
                FROM pg_roles WHERE rolname=%s''', (self.login,))
            role = cur.fetchone()
            require(role and role[6] and not any((role[2], role[4], role[5], role[7], role[8])), 'unexpected privileged LOGIN')
            cur.execute('''SELECT roleid,member,grantor,admin_option,inherit_option,set_option
                FROM pg_auth_members WHERE member=%s ORDER BY roleid,grantor''', (role[0],))
            memberships = cur.fetchall()
            fingerprint = d.digest({'role': role, 'memberships': memberships,
                                    'privileges': d.privilege_digest(cur, self.login)})
        self.fixture.conn.commit()
        return fingerprint

    def positive(self, secret):
        with closing(self.connect(secret)) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT session_user,current_user,current_database()')
                require(cur.fetchone() == (self.login, self.login, self.database), 'authentication identity changed')

    def reject_old(self):
        # Positive controls surround each negative probe. Network/DNS failures
        # must never masquerade as successful password revocation.
        for _ in range(3):
            self.positive(self.new_secret)
            try:
                conn = self.connect(self.old_secret)
            except psycopg2.OperationalError as error:
                code = error.pgcode
                # libpq connection failures may not expose a diagnostic SQLSTATE.
                # Require explicit auth rejection in that case; do not report text.
                require(code == '28P01' or ('password authentication failed for user "' + self.login + '"') in str(error),
                        'connection failure was not demonstrably password rejection')
            else:
                conn.close()
                raise AssertionError('revoked secret still authenticates')
            self.positive(self.new_secret)
        self.report['checks']['old_secret_rejected_on_new_connections'] = 'passed'
        self.report['negative_authentication_attempts'] = 3

    def open_old_session(self):
        require(self.probe is None, 'session already open')
        self.probe = self.connect(self.old_secret, name='corner-rotation-held-session')
        with self.probe.cursor() as cur:
            cur.execute('SELECT pg_backend_pid()')
            pid = cur.fetchone()[0]
        self.probe.commit()
        with self.fixture.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('''SELECT pid,backend_start,usename,datname,application_name FROM pg_stat_activity
                WHERE pid=%s AND usename=%s AND datname=%s AND backend_type='client backend' ''',
                (pid, self.login, self.database))
            self.binding = dict(cur.fetchone() or {})
        self.fixture.conn.commit()
        require(self.binding.get('application_name') == 'corner-rotation-held-session', 'wrong probe session')
        self.report['held_session'] = self.binding.copy()

    def rotate(self):
        self.before_role = self.role_fingerprint()
        self.verifier = psycopg2.extensions.encrypt_password(self.new_secret, self.login, self.fixture.conn,
                                                            algorithm='scram-sha-256')
        require(self.verifier.startswith('SCRAM-SHA-256$'), 'expected SCRAM verifier')
        with self.fixture.conn.cursor() as cur:
            cur.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(self.login), sql.Literal(self.verifier)))
        self.fixture.conn.commit()
        require(self.role_fingerprint() == self.before_role, 'rotation changed role identity or privileges')
        self.report['role_identity_sha256'] = self.before_role
        self.report['checks']['same_login_role_memberships_and_privileges'] = 'passed'

    def revoke_old_session(self):
        require(self.probe is not None and self.binding is not None, 'no held session')
        # This is intentional proof of the distinction: changing a password did
        # not revoke an already authenticated connection.
        with self.probe.cursor() as cur:
            cur.execute('SELECT session_user,current_user,pg_backend_pid()')
            require(cur.fetchone() == (self.login, self.login, self.binding['pid']), 'old session unexpectedly changed')
        self.probe.commit()
        self.report['checks']['old_authenticated_session_survives_password_change'] = 'passed'
        with self.fixture.conn.cursor() as cur:
            cur.execute('''SELECT pg_terminate_backend(pid,5000) FROM pg_stat_activity
                WHERE pid=%(pid)s AND backend_start=%(backend_start)s AND usename=%(usename)s
                AND datname=%(datname)s AND application_name=%(application_name)s
                AND backend_type='client backend' AND pid<>pg_backend_pid()''', self.binding)
            require(cur.fetchall() == [(True,)], 'exact session termination not confirmed')
        self.fixture.conn.commit()
        try:
            with self.probe.cursor() as cur: cur.execute('SELECT 1')
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            pass
        else:
            raise AssertionError('terminated session remains usable')
        self.probe.close(); self.probe = None
        self.require_no_sessions()
        self.report['checks']['exact_old_session_terminated_and_absent'] = 'passed'

    def require_no_sessions(self):
        def absent():
            with self.fixture.conn.cursor() as cur:
                cur.execute('SELECT count(*) FROM pg_stat_activity WHERE usename=%s AND datname=%s',
                            (self.login, self.database))
                count = cur.fetchone()[0]
            self.fixture.conn.commit()
            return count == 0
        wait_for(absent, 10)

    def close(self):
        if self.probe is not None:
            self.probe.close(); self.probe = None


def qualification_request(fixture):
    routed, _ = fixture.routed()
    fixture.conn.commit()
    result = discovery.sweep(fixture.conn, obligation='qualification', channel_id=fixture.channel['id'])
    item = next(i for i in result['items'] if i['candidate_id'] == routed['id'])
    require(item['status'] == 'newly_requested', 'expected new routed qualification obligation')
    fixture.conn.commit()
    return {'id': item['request_id']}


def frozen(fixture, request):
    with fixture.conn.cursor(cursor_factory=RealDictCursor) as cur:
        row = dispatch.prepared(cur, request['id'])
    fixture.conn.commit()
    require(row is not None, 'no frozen qualification command')
    return dict(row)


def verify_result(fixture, request, original, expected_authority):
    def read():
        row = fixture.execution(request)
        fixture.conn.commit()
        require(row['status'] not in ('blocked', 'waiting'), 'qualification did not complete')
        return row if row['status'] == 'completed' else None
    execution = wait_for(read, 45)
    require(frozen(fixture, request) == original, 'frozen command changed across rotation')
    document = original['command_snapshot']
    inner = document['command'] if document.get('format') == dispatch.COMMAND_FORMAT else document
    require(inner['authority'] == expected_authority, 'command authority changed')
    with fixture.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('''SELECT id,authority_kind,authority_id,qualification_key,decided_at
            FROM corner.qualification_decisions WHERE authority_kind=%s AND authority_id=%s AND qualification_key=%s''',
            (expected_authority['kind'], expected_authority['identifier'], inner['domain_command_key']))
        decisions = cur.fetchall()
    fixture.conn.commit()
    require(len(decisions) == 1 and decisions[0]['id'] == execution['qualification_decision_id'], 'result identity conflict')
    require(decisions[0]['decided_at'] == datetime.fromisoformat(inner['payload']['decided_at']), 'decision time changed')
    return {'request_id': request['id'], 'preparation_id': original['id'],
            'command_sha256': bytes(original['command_sha256']).hex(),
            'domain_authority': expected_authority, 'domain_command_key': inner['domain_command_key'],
            'qualification_id': decisions[0]['id'], 'decided_at': decisions[0]['decided_at'],
            'claim_count': execution['claim_count'],
            'status': execution['status']}
