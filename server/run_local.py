"""Foreground local board API with an ephemeral SELECT-only database login.

No provider requests. Ctrl+C stops Java and removes only this session's login.
This is a development launcher, not a Windows service/deployment installer.
"""
import os
import argparse
from pathlib import Path
import secrets
import subprocess
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from config import DB_CONFIG

ROOT = Path(__file__).resolve().parents[1]
TABLES = ('events', 'competitions', 'participants', 'event_participants', 'markets',
          'market_types', 'scopes', 'sportsbooks', 'outcomes', 'outcome_sides',
          'odds_observations', 'quote_states', 'providers', 'trusted_current_quotes')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--accounts',action='store_true',help='Enable local personal records with a separate restricted login')
    parser.add_argument('--initialize-accounts',action='store_true',help='Apply migration 014 if the personal schema is absent')
    args=parser.parse_args()
    role = 'corner_board_session_' + uuid4().hex
    account_role = 'corner_personal_session_' + uuid4().hex
    account_password = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(32)
    process = None
    created = False
    account_created = False
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT current_database()')
                database = cur.fetchone()[0]
                if args.initialize_accounts:
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext('corner-personal-schema-014'))")
                    cur.execute("SELECT to_regnamespace('corner_app')")
                    if cur.fetchone()[0] is None:
                        migration=(ROOT/'db/migrations/014_personal_records.sql').read_text()
                        cur.execute(migration.replace('BEGIN;','').replace('COMMIT;',''))
                if args.accounts:
                    cur.execute('SELECT username FROM corner_app.users LIMIT 0')
                    cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT').format(sql.Identifier(account_role)),(account_password,))
                    cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database),sql.Identifier(account_role)))
                    cur.execute(sql.SQL('GRANT USAGE ON SCHEMA corner_app TO {}').format(sql.Identifier(account_role)))
                    cur.execute(sql.SQL('GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA corner_app TO {}').format(sql.Identifier(account_role)))
                    cur.execute(sql.SQL('GRANT UPDATE(id) ON corner_app.users TO {}').format(sql.Identifier(account_role)))
                    cur.execute(sql.SQL('GRANT UPDATE ON corner_app.auth_limits TO {}').format(sql.Identifier(account_role)))
                    cur.execute(sql.SQL('GRANT DELETE ON corner_app.sessions TO {}').format(sql.Identifier(account_role)))
                cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT').format(sql.Identifier(role)), (password,))
                cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT USAGE ON SCHEMA corner TO {}').format(sql.Identifier(role)))
                cur.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    sql.SQL(',').join(sql.Identifier('corner', name) for name in
                        TABLES + (('event_provider_identities',) if os.environ.get('CORNER_LIVE_ENABLED') == 'true' else ())), sql.Identifier(role)))
            conn.commit()
            created = True
            account_created = args.accounts
        conn.close()
        env = os.environ.copy()
        env.update(CORNER_MARKET_JDBC_URL=f"jdbc:postgresql://{DB_CONFIG.get('host', '127.0.0.1')}:{DB_CONFIG.get('port', 5432)}/{database}?connectTimeout=3&socketTimeout=8",
                   CORNER_MARKET_DB_USER=role, CORNER_MARKET_DB_PASSWORD=password,
                   CORNER_MARKET_PORT='8080', CORNER_MARKET_DATASET='retained')
        if args.accounts:
            env.update(CORNER_ACCOUNTS_ENABLED='true',CORNER_ACCOUNTS_JDBC_URL=env['CORNER_MARKET_JDBC_URL'],
                       CORNER_ACCOUNTS_DB_USER=account_role,CORNER_ACCOUNTS_DB_PASSWORD=account_password)
        else:
            env['CORNER_ACCOUNTS_ENABLED']='false'
        java = os.getenv('CORNER_JAVA', str(ROOT / '.tools/jdk-21.0.12.1+1/bin/java.exe'))
        process = subprocess.Popen([java, '-jar', str(ROOT / 'server/target/market-api-0.1.0.jar')], env=env,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print('Local read-only board API on :8080; no provider polling. Ctrl+C stops and removes the session login.', flush=True)
        if args.accounts:
            print('Local accounts and retrospective records enabled with a separate restricted login.',flush=True)
        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if created:
            # This generated login owns no objects; DROP OWNED revokes its grants.
            cleanup = psycopg2.connect(**DB_CONFIG)
            try:
                with cleanup.cursor() as cur:
                    cur.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                    cur.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
                    if account_created:
                        cur.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(account_role)))
                        cur.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(account_role)))
                cleanup.commit()
                print('Temporary board login removed.', flush=True)
            finally:
                cleanup.close()


if __name__ == '__main__':
    main()
