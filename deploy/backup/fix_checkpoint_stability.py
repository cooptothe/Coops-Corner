"""Replace SQLite's connection-local change counter with a content check."""
import hashlib
from pathlib import Path
import os
import sqlite3
import tempfile


def ledger_fingerprint(connection):
    """Hash a consistent logical snapshot; never return private ledger rows."""
    if connection.in_transaction:
        raise RuntimeError('Unexpected ledger monitor transaction')
    connection.execute('BEGIN')
    try:
        digest = hashlib.sha256()
        for statement in connection.iterdump():
            encoded = statement.encode('utf-8')
            digest.update(len(encoded).to_bytes(8, 'big'))
            digest.update(encoded)
        return digest.digest()
    finally:
        connection.rollback()


def self_test(directory):
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        path = Path(temporary) / 'ledger.sqlite3'
        writer = sqlite3.connect(path)
        reader = None
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE controls (paused TEXT)')
            writer.execute("INSERT INTO controls VALUES ('paused')")
            writer.commit()
            reader = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            original = ledger_fingerprint(reader)
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            assert ledger_fingerprint(reader) == original, 'Checkpoint changed logical contents'
            writer.execute("UPDATE controls SET paused='changed'")
            writer.commit()
            assert ledger_fingerprint(reader) != original, 'Committed write not detected'
            original = ledger_fingerprint(reader)
            writer.execute('CREATE TABLE extra (value BLOB)')
            writer.commit()
            assert ledger_fingerprint(reader) != original, 'Schema change not detected'
            assert not reader.in_transaction, 'Read transaction leaked'
        finally:
            if reader is not None:
                reader.close()
            writer.close()
    print('Stability tests passed: checkpoint unchanged; data/schema writes detected.')


def install(path):
    import inspect
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Regular installed backup script required')
    source = path.read_text()
    replacements = {
        "sqlite_backup(live, data/'collection.sqlite3')":
            "sqlite_backup(live, data/'collection.sqlite3')\n                with closing(sqlite3.connect((data/'collection.sqlite3').resolve().as_uri()+'?mode=ro', uri=True)) as saved:\n                    if ledger_fingerprint(saved) != version:\n                        raise RuntimeError('Ledger snapshot differs from initial contents')",
        "version = monitor.execute('PRAGMA data_version').fetchone()[0]":
            'version = ledger_fingerprint(monitor)',
        "if monitor and monitor.execute('PRAGMA data_version').fetchone()[0] != version:":
            "step('scheduler-content-stability-check')\n            if monitor and ledger_fingerprint(monitor) != version:",
    }
    for old in replacements:
        if source.count(old) != 1:
            raise RuntimeError('Installed source differs; no files changed')
    if 'def ledger_fingerprint(' in source:
        raise RuntimeError('Patch already present; no files changed')
    updated = source
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    updated += '\n'  # helper must precede the main invocation
    marker = "if __name__ == '__main__':"
    if updated.count(marker) != 1:
        raise RuntimeError('Unexpected entry point; no files changed')
    updated = updated.replace(marker, inspect.getsource(ledger_fingerprint) + '\n\n' + marker)
    compile(updated, str(path), 'exec')
    backup = path.with_name(path.name + '.before-content-stability')
    with backup.open('x', encoding='utf-8') as stream:
        stream.write(source)
    os.chmod(backup, 0o644)
    descriptor, temporary = tempfile.mkstemp(prefix='.corner-backup-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Backup content-stability check installed; original script preserved.')


if __name__ == '__main__':
    import sys
    self_test(Path(sys.argv[1]).resolve())
    if len(sys.argv) == 3:
        install(Path(sys.argv[2]))
