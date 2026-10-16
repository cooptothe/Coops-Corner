from contextlib import closing
import multiprocessing as mp
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

try:
    from corner.collection_maintenance import maintenance_lock, MaintenanceBusy
except ModuleNotFoundError as error:
    if error.name not in ('corner', 'corner.collection_maintenance'):
        raise
    from collection_maintenance import maintenance_lock, MaintenanceBusy


def hold(path, exclusive, ready, release):
    with maintenance_lock(path, exclusive=exclusive, timeout=3):
        ready.set()
        if not release.wait(10):
            raise RuntimeError('Disposable holder timed out')


def attempt_tick(path, marker, result):
    try:
        with maintenance_lock(path, timeout=.1):
            Path(marker).write_text('tick entered', encoding='utf-8')
        result.put('entered')
    except MaintenanceBusy:
        result.put('maintenance')


def fake_collection_tick(path, database, capture, ready, release):
    with maintenance_lock(path, timeout=3):
        with closing(sqlite3.connect(database)) as db:
            db.execute("UPDATE attempts SET state='inflight'")
            db.commit()
            ready.set()
            if not release.wait(10):
                raise RuntimeError('Disposable capture timed out')
            Path(capture).write_text('retained fixture bytes', encoding='utf-8')
            db.execute("UPDATE attempts SET state='settled'")
            db.commit()


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/'maintenance.lock'
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        self.ctx = mp.get_context('spawn')
        self.children = []

    def tearDown(self):
        for process, release in self.children:
            # A killed Windows process can leave its Event's internal lock held.
            # Never touch that Event after termination; the OS file lock is what
            # this test deliberately verifies is released by process death.
            if process.is_alive():
                release.set()
                process.join(3)
            if process.is_alive():
                process.terminate()
                process.join(3)
        self.temp.cleanup()

    def child_holder(self, exclusive):
        ready, release = self.ctx.Event(), self.ctx.Event()
        process = self.ctx.Process(target=hold, args=(self.path, exclusive, ready, release))
        process.start()
        self.children.append((process, release))
        self.assertTrue(ready.wait(5))
        return process, release

    def test_missing_lock_is_not_created(self):
        absent = self.root/'absent.lock'
        with self.assertRaises(FileNotFoundError):
            with maintenance_lock(absent): pass
        self.assertFalse(absent.exists())

    def test_worker_tick_blocks_backup_until_finished(self):
        process, release = self.child_holder(False)
        with self.assertRaises(MaintenanceBusy):
            with maintenance_lock(self.path, exclusive=True, timeout=.1): pass
        release.set()
        process.join(5)
        self.assertEqual(process.exitcode, 0)
        with maintenance_lock(self.path, exclusive=True, timeout=1): pass

    def test_backup_prevents_new_tick_side_effects(self):
        result = self.ctx.Queue()
        marker = self.root/'should-not-exist'
        with maintenance_lock(self.path, exclusive=True):
            process = self.ctx.Process(target=attempt_tick, args=(self.path, marker, result))
            process.start()
            process.join(5)
            if process.is_alive():
                process.terminate(); process.join(3)
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(result.get(timeout=1), 'maintenance')
            self.assertFalse(marker.exists())
        result.close()
        result.join_thread()

    def test_process_crash_releases_os_lock(self):
        process, release = self.child_holder(True)
        process.terminate()
        process.join(5)
        with maintenance_lock(self.path, exclusive=True, timeout=1): pass

    def test_backup_exception_releases_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic backup failure'):
            with maintenance_lock(self.path, exclusive=True):
                raise RuntimeError('synthetic backup failure')
        with maintenance_lock(self.path, timeout=1): pass

    def test_shutdown_refuses_waiting_tick(self):
        with self.assertRaises(MaintenanceBusy):
            with maintenance_lock(self.path, should_stop=lambda: True):
                self.fail('Shutdown tick entered')

    def test_lock_contents_and_inode_unchanged(self):
        before = self.path.stat()
        with maintenance_lock(self.path, exclusive=True): pass
        self.assertEqual(self.path.read_bytes(), b'')
        self.assertEqual(self.path.stat().st_ino, before.st_ino)

    @unittest.skipIf(os.name == 'nt', 'Linux shared flock semantics verified on VPS')
    def test_shared_workers_can_coexist(self):
        self.child_holder(False)
        with maintenance_lock(self.path, timeout=.1): pass

    @unittest.skipIf(os.name == 'nt', 'Linux permission enforcement verified on VPS')
    def test_world_readable_lock_refused(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            with maintenance_lock(self.path): pass

    @unittest.skipIf(os.name == 'nt', 'Linux symlink creation verified on VPS')
    def test_symlink_refused(self):
        link = self.root/'symlink.lock'
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            with maintenance_lock(link): pass

    def test_checkpoint_cannot_capture_partial_tick(self):
        database, capture = self.root/'ledger.sqlite3', self.root/'response.body'
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE attempts(state TEXT)')
            db.execute("INSERT INTO attempts VALUES('idle')")
            db.commit()
        ready, release = self.ctx.Event(), self.ctx.Event()
        process = self.ctx.Process(target=fake_collection_tick, args=(self.path, database, capture, ready, release))
        process.start()
        self.children.append((process, release))
        self.assertTrue(ready.wait(5))
        timer = threading.Timer(.15, release.set)
        timer.start()
        try:
            with maintenance_lock(self.path, exclusive=True, timeout=3):
                with closing(sqlite3.connect(database)) as db:
                    self.assertEqual(db.execute('SELECT state FROM attempts').fetchone()[0], 'settled')
                self.assertEqual(capture.read_text(), 'retained fixture bytes')
        finally:
            timer.join(2)
        process.join(5)
        self.assertEqual(process.exitcode, 0)


if __name__ == '__main__':
    unittest.main()
