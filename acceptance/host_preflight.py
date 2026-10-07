"""Administrator-run READ-ONLY preflight; NOT an installer or acceptance result.

Never invokes WinSW, creates a service/account/database, or reads/writes a vault.
The existing DB_CONFIG is used only for a read-only setup-authority check, never
passed to a service. Output deliberately excludes passwords and exception text.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def windows_access():
    if os.name != 'nt': raise RuntimeError('Windows required')
    from ctypes import wintypes as w
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.IsUserAnAdmin.argtypes = []
    shell.IsUserAnAdmin.restype = w.BOOL
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.OpenSCManagerW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
    advapi.OpenSCManagerW.restype = w.HANDLE
    advapi.CloseServiceHandle.argtypes = [w.HANDLE]
    advapi.CloseServiceHandle.restype = w.BOOL
    handle = advapi.OpenSCManagerW(None, None, 2)  # Request rights; do not create anything.
    error = 0 if handle else ctypes.get_last_error()
    if handle: advapi.CloseServiceHandle(handle)
    return {'administrator': bool(shell.IsUserAnAdmin()),
            'scm_create_service_access': error == 0, 'scm_error': error}


def artifact_check(path):
    manifest = json.loads((ROOT / 'acceptance/winsw-artifact.json').read_text(encoding='utf-8'))
    with Path(path).open('rb') as binary:
        digest = hashlib.file_digest(binary, 'sha256').hexdigest()
        size = binary.seek(0, os.SEEK_END)
    return {'version': manifest['version'], 'sha256_matches': digest == manifest['sha256'],
            'size_matches': size == manifest['size_bytes'], 'executed': False}


def database_check():
    import psycopg2
    from config import DB_CONFIG
    # Restrict this parent-only check to the already agreed local installation.
    if DB_CONFIG.get('host', 'localhost') not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('local setup connection required')
    conn = psycopg2.connect(**dict(DB_CONFIG, connect_timeout=5,
        application_name='corner-host-readonly-preflight', options='-c default_transaction_read_only=on -c statement_timeout=5000'))
    try:
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute('SHOW server_version_num')
            version = int(cur.fetchone()[0])
            cur.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')
            superuser, createdb, createrole = cur.fetchone()
            return {'postgresql_18': 180000 <= version < 190000,
                    'setup_can_create_disposable_database': bool(superuser or createdb),
                    'setup_can_create_disposable_roles': bool(superuser or createrole),
                    'read_only_check': True, 'database_created': False}
    finally:
        try: conn.rollback()
        finally: conn.close()


def dependency_check():
    import psycopg2
    from corner import host_service, versioned_dispatch  # imports only; no run/build/claim
    return {'python_64_bit': struct.calcsize('P') == 8,
            'host_modules_imported': True, 'pinned_handler_count': len(versioned_dispatch.HANDLERS)}


def collect(path):
    report = {'format': 'corner.host-preflight/1', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'read_only', 'installation_performed': False, 'installed_acceptance': 'not_performed', 'checks': {}}
    for name, check in (('windows', windows_access), ('winsw', lambda: artifact_check(path)),
                        ('python', dependency_check), ('database', database_check)):
        try: report['checks'][name] = check()
        except Exception as error:
            report['checks'][name] = {'error_type': type(error).__name__, 'status': 'check_failed'}
    checks = report['checks']
    report['preflight_ok'] = all((
        checks['windows'].get('administrator') is True,
        checks['windows'].get('scm_create_service_access') is True,
        checks['winsw'].get('sha256_matches') is True,
        checks['winsw'].get('size_matches') is True,
        checks['python'].get('python_64_bit') is True,
        checks['python'].get('host_modules_imported') is True,
        checks['database'].get('postgresql_18') is True,
        checks['database'].get('setup_can_create_disposable_database') is True,
        checks['database'].get('setup_can_create_disposable_roles') is True,
    ))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--winsw', type=Path, required=True, help='Downloaded pinned WinSW binary; never executed')
    args = parser.parse_args(argv)
    report = collect(args.winsw)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['preflight_ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
