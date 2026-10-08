"""Foreground local tools API over retained pre-game quotes, with an ephemeral SELECT-only login.

No provider requests. Ctrl+C stops the server and removes only this session's login.
Run: python -m api.run_local --port 8765
"""
import argparse
import secrets
from uuid import uuid4

TABLES = ('events', 'competitions', 'participants', 'event_participants', 'markets',
          'market_types', 'scopes', 'sportsbooks', 'outcomes', 'outcome_sides',
          'odds_observations', 'quote_states', 'providers', 'trusted_current_quotes', 'quote_links')


def main():
    parser = argparse.ArgumentParser(description='Database-backed tools API (read-only, no provider calls).')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    import psycopg2
    from psycopg2 import sql
    import uvicorn
    from config import DB_CONFIG
    from api.app import create_app
    from api.database import LiveCatalog
    from corner import auth
    from corner.tracker_store import read_user
    from pipelines.accounts import DB_PATH, SECRET_PATH

    # Every /api/v1 call needs a signed-in account; the key and accounts are the refresh service's.
    secret = auth.load_secret(SECRET_PATH)

    def signed_in(token):
        return auth.session_user(secret, token, lambda user_id: read_user(DB_PATH, user_id)) is not None

    role, password = 'corner_tools_session_' + uuid4().hex, secrets.token_urlsafe(32)
    created = False
    try:
        with psycopg2.connect(**DB_CONFIG) as conn, conn.cursor() as cur:
            cur.execute('SELECT current_database()')
            database = cur.fetchone()[0]
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT').format(sql.Identifier(role)), (password,))
            created = True
            cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), sql.Identifier(role)))
            cur.execute(sql.SQL('GRANT USAGE ON SCHEMA corner TO {}').format(sql.Identifier(role)))
            cur.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                sql.SQL(',').join(sql.Identifier('corner', name) for name in TABLES), sql.Identifier(role)))
        conn.close()
        login = {**DB_CONFIG, 'user': role, 'password': password, 'dbname': database, 'connect_timeout': 3,
                 'options': '-c statement_timeout=8000'}
        catalog = LiveCatalog(lambda: psycopg2.connect(**login))
        print(f'Tools API on 127.0.0.1:{args.port} over retained pre-game quotes; no provider polling. '
              f'{len(catalog.games)} games, {len(catalog.rows)} tool rows. Ctrl+C stops and removes the session login.', flush=True)
        uvicorn.run(create_app(data_mode='database', catalog=catalog, session_check=signed_in), host='127.0.0.1', port=args.port,
                    access_log=False, timeout_graceful_shutdown=5)
    except KeyboardInterrupt:
        pass
    finally:
        if created:
            cleanup = psycopg2.connect(**DB_CONFIG)
            try:
                with cleanup.cursor() as cur:
                    cur.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                    cur.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
                cleanup.commit()
                print('Temporary tools login removed.', flush=True)
            finally:
                cleanup.close()


if __name__ == '__main__':
    main()
