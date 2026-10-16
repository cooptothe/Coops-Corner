"""Cooperative, bounded checkpoint lock. Never creates/replaces the lock inode.

Linux uses flock: worker shared, backup/admin exclusive. Windows offline tests
serialize all holders with msvcrt; actual shared-reader behavior is tested on VPS.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import time

LOCK = Path('/srv/corner/config/collection-maintenance.lock')


class MaintenanceBusy(TimeoutError):
    pass


@contextmanager
def maintenance_lock(path=LOCK, *, exclusive=False, timeout=300, should_stop=None):
    if timeout < 0:
        raise ValueError('Negative lock timeout')
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Maintenance lock symlink refused')
    # flock does not require write access on a local Linux filesystem. This
    # keeps the backup unit's config directory read-only under ProtectSystem.
    fd = os.open(path, (os.O_RDWR if os.name == 'nt' else os.O_RDONLY) | getattr(os, 'O_NOFOLLOW', 0))
    locked = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name != 'nt' and stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError('A private, regular maintenance lock is required')
        deadline = time.monotonic() + timeout
        while True:
            if should_stop and should_stop():
                raise MaintenanceBusy('Shutdown requested while waiting for maintenance')
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                locked = True
                current = path.stat()
                if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                    raise ValueError('Maintenance lock was replaced')
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline:
                    raise MaintenanceBusy('Maintenance lock timeout') from None
                time.sleep(min(.05, max(0, deadline-time.monotonic())))
        yield
    finally:
        if locked:
            if os.name == 'nt':
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
