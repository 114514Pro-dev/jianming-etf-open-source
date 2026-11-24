"""Private, revocable browser sessions, independent of trading data.

Only a digest of the bearer cookie is persisted. SQLite transactions make a
successful login/logout durable before the HTTP response is sent.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
import time


DEVICE_TTL = 180 * 24 * 60 * 60
RENEW_WINDOW = 30 * 24 * 60 * 60
MAX_DEVICES = 64
MAX_STORE_BYTES = 2 * 1024 * 1024
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class SessionStoreUnavailable(Exception):
    """The private store cannot safely authorize or persist a session."""


class PersistentSessions:
    def __init__(self, home, password_hash, *, clock=time.time):
        self.home = Path(home).absolute()
        self.directory = self.home / "web" / "auth-sessions"
        self.path = self.directory / "devices.sqlite3"
        self.fingerprint = hashlib.sha256(password_hash.encode("utf-8")).hexdigest()
        self.clock = clock
        self.lock = threading.RLock()

    def _now(self):
        value = self.clock()
        if not isinstance(value, (int, float)) or not 0 <= value < 2**53:
            raise SessionStoreUnavailable("Invalid session clock")
        return int(value)

    @staticmethod
    def _directory(path, *, private=False):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
            raise SessionStoreUnavailable("Unsafe session directory")
        if os.name == "posix":
            if info.st_mode & 0o022:
                raise SessionStoreUnavailable("Writable session parent")
            if private and (stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid()):
                raise SessionStoreUnavailable("Session directory is not private")

    @staticmethod
    def _file(path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_nlink != 1:
            raise SessionStoreUnavailable("Unsafe session file")
        if os.name == "posix" and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()):
            raise SessionStoreUnavailable("Session file is not private")
        if info.st_size > MAX_STORE_BYTES:
            raise SessionStoreUnavailable("Session store exceeds its bound")
        return info

    def _connect(self, create):
        # Do not resolve first: a symlink must be rejected, not silently followed.
        if any(parent.is_symlink() for parent in self.home.parents):
            raise SessionStoreUnavailable("Unsafe session home")
        for part in (self.home, self.home / "web"):
            if not part.exists() and not part.is_symlink():
                if not create:
                    return None, False
                part.mkdir(mode=0o700)
            self._directory(part)
        if not self.directory.exists() and not self.directory.is_symlink():
            if not create:
                return None, False
            try:
                self.directory.mkdir(mode=0o700)
            except FileExistsError:
                pass
        self._directory(self.directory, private=True)
        new = False
        if not self.path.exists() and not self.path.is_symlink():
            if not create:
                return None, False
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                os.close(fd)
                new = True
            except FileExistsError:
                pass
        before = self._file(self.path)
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                if suffix != "-journal":
                    raise SessionStoreUnavailable("Unexpected session journal mode")
                try:
                    self._file(sidecar)
                except FileNotFoundError:
                    # Another connection may commit and remove its rollback
                    # journal after the existence check. Other failures still
                    # reject the store, as do any observed WAL/SHM sidecars.
                    pass
        if not new:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(fd)
                header = os.read(fd, 100)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise SessionStoreUnavailable("Session file changed")
            finally:
                os.close(fd)
            if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
                raise SessionStoreUnavailable("Invalid session database")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=3, isolation_level=None)
        try:
            after = self._file(self.path)
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                raise SessionStoreUnavailable("Session file changed")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise SessionStoreUnavailable("Unexpected session journal mode")
            return connection, new
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def _transaction(self, *, create=False):
        connection = None
        with self.lock:
            try:
                connection, new = self._connect(create)
                if connection is None:
                    yield None
                    return
                connection.execute("BEGIN IMMEDIATE")
                if new:
                    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    connection.execute("CREATE TABLE devices (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
                    connection.execute("INSERT INTO metadata VALUES ('credential_fingerprint', ?)", (self.fingerprint,))
                    connection.execute("PRAGMA user_version=1")
                objects = set(connection.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
                if connection.execute("PRAGMA user_version").fetchone()[0] != 1 or objects != {("table", "metadata"), ("table", "devices")}:
                    raise SessionStoreUnavailable("Invalid session schema")
                rows = connection.execute("SELECT key,value FROM metadata").fetchall()
                if len(rows) != 1 or rows[0][0] != "credential_fingerprint" or not re.fullmatch(r"[a-f0-9]{64}", rows[0][1]):
                    raise SessionStoreUnavailable("Invalid session credential binding")
                if rows[0][1] != self.fingerprint:
                    connection.execute("DELETE FROM devices")
                    connection.execute("UPDATE metadata SET value=? WHERE key='credential_fingerprint'", (self.fingerprint,))
                count = connection.execute("SELECT count(*) FROM devices").fetchone()[0]
                if count > MAX_DEVICES:
                    raise SessionStoreUnavailable("Too many saved sessions")
                yield connection
                connection.commit()
                self._file(self.path)
                if new and os.name == "posix":
                    for directory in (self.directory, self.directory.parent, self.home):
                        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
            except (OSError, sqlite3.Error, ValueError, TypeError) as error:
                raise SessionStoreUnavailable("Private session storage unavailable") from error
            finally:
                if connection is not None:
                    try:
                        if connection.in_transaction:
                            connection.rollback()
                    finally:
                        connection.close()

    @staticmethod
    def _digest(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def issue(self):
        now = self._now()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires = now + DEVICE_TTL
        with self._transaction(create=True) as connection:
            connection.execute("DELETE FROM devices WHERE expires_at<=?", (now,))
            count = connection.execute("SELECT count(*) FROM devices").fetchone()[0]
            if count >= MAX_DEVICES:
                connection.execute("DELETE FROM devices WHERE token_hash IN (SELECT token_hash FROM devices ORDER BY expires_at,token_hash LIMIT ?)", (count - MAX_DEVICES + 1,))
            connection.execute("INSERT INTO devices VALUES (?,?,?,?)", (self._digest(token), csrf, now, expires))
        return token, {"csrf": csrf, "expires": expires, "remembered": True}

    def lookup(self, token, *, renew=False):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            return None
        now = self._now()
        result = None
        with self._transaction() as connection:
            if connection is None:
                return None
            key = self._digest(token)
            row = connection.execute("SELECT csrf,issued_at,expires_at FROM devices WHERE token_hash=?", (key,)).fetchone()
            if row is None:
                return None
            csrf, issued, expires = row
            if not isinstance(csrf, str) or not TOKEN.fullmatch(csrf) or type(issued) is not int or type(expires) is not int or not 0 <= issued < expires or issued > now + 300 or expires > now + DEVICE_TTL + 300:
                raise SessionStoreUnavailable("Invalid session record")
            if expires <= now:
                connection.execute("DELETE FROM devices WHERE token_hash=?", (key,))
                return None
            refreshed = bool(renew and expires - now <= RENEW_WINDOW)
            if refreshed:
                expires = now + DEVICE_TTL
                connection.execute("UPDATE devices SET expires_at=? WHERE token_hash=?", (expires, key))
            result = {"csrf": csrf, "expires": expires, "remembered": True, "renewed": refreshed}
        return result

    def revoke(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            return
        with self._transaction() as connection:
            if connection is not None:
                connection.execute("DELETE FROM devices WHERE token_hash=?", (self._digest(token),))
