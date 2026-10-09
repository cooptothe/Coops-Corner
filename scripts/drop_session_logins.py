"""Drops leftover temporary tools-API database logins (corner_tools_session_*).

api.run_local creates one SELECT-only login per run and removes it when it is stopped with Ctrl+C. A killed
process cannot clean up, so scripts\\stop-services.ps1 runs this once every service is down. Run only while no
tools API is running: a running one needs its own login.
"""
import os
import sys

sys.path.insert(0, os.getcwd())

try:
    import psycopg2
    from psycopg2 import sql

    from config import DB_CONFIG

    conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
except Exception as error:
    print(f'  (database not reachable, skipped login cleanup: {type(error).__name__})')
    raise SystemExit(0)

conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE 'corner\\_tools\\_session\\_%'")
    names = [row[0] for row in cur.fetchall()]
    for name in names:
        cur.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(name)))
        cur.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
conn.close()
print(f'Removed {len(names)} leftover temporary database login(s).' if names else 'No leftover database logins.')
