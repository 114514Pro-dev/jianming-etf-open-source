"""Nonblocking, process-held lease for one persistent research store.

Every service and offline writer must take the same lease. The file is retained:
deleting a live lock file would allow two processes to lock different inodes.
Windows uses a one-byte CRT lock; Unix uses advisory flock. The operating system
releases either lock when its owning process exits, including abnormal exits.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path


class StoreLease:
    """Acquire store/.service.lock immediately, without waiting on another owner.

    Occupancy is a ValueError with a user-facing message. Path, permissions and
    disk failures remain their original OSError subclasses, so callers must not
    describe those failures as another running instance. close() is idempotent.
    """

    def __init__(self, store_dir):
        self.store_dir = Path(store_dir).expanduser().resolve()
        self.lock_path = self.store_dir / '.service.lock'
        self._fd = None
        self.acquire()

    @property
    def held(self):
        return self._fd is not None

    @staticmethod
    def _lock(fd):
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            # Windows byte-range locks may cover bytes past EOF. Lock before
            # writing anything so a fresh empty lock file has no creation race.
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(fd):
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)

    @staticmethod
    def _occupied(exc):
        # Only called for errors from the lock operation itself. In particular,
        # PermissionError from mkdir/open is never converted into "in use".
        if os.name == 'nt':
            return getattr(exc, 'winerror', None) == 33 or exc.errno in (errno.EACCES, errno.EAGAIN)
        return exc.errno in (errno.EACCES, errno.EAGAIN)

    def acquire(self):
        if self._fd is not None:
            return self
        self.store_dir.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0)
        fd = os.open(self.lock_path, flags, 0o600)
        try:
            os.set_inheritable(fd, False)
            try:
                self._lock(fd)
            except OSError as exc:
                if self._occupied(exc):
                    raise ValueError(
                        '此研究资料目录正在被另一个程序或备份操作使用，请先关闭该实例后重试：'
                        + str(self.store_dir)
                    ) from exc
                raise
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def close(self):
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            self._unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def __del__(self):
        # Explicit close/context-manager use is preferred. This only prevents a
        # descriptor leak after a partially constructed or discarded object.
        try:
            self.close()
        except Exception:
            pass
