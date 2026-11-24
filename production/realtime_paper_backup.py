"""Isolated backup prototype; no production baseline has been bound to this file.

The caller must own the old Runtime's unique business executor. A successful
result describes only a frozen temporary tree; it is not a published ZIP.
"""
from __future__ import annotations

from contextlib import closing, ExitStack
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time
import shutil


PAPER_PATH = "web/realtime-paper/realtime-paper.sqlite3"
WW_PAPER_PATH = "web/realtime-paper-ww/realtime-paper.sqlite3"
HISTORY_PATHS = {"realtime_paper_history": "web/realtime-paper-history",
                 "realtime_paper_ww_history": "web/realtime-paper-ww-history"}
HISTORY_BACKUP_SCHEMA = "simple-etf.paper-accepted-history-backup.v1"
BACKUP_SCHEMA = "simple-etf.realtime-paper-business-backup.v1"


class BusinessBackupError(RuntimeError):
    """A deliberately generic error, safe for the existing job error surface."""


def _fail():
    raise BusinessBackupError("BUSINESS_BACKUP_FAILED")


def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def _linked(path):
    return path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _reject_link_chain(path):
    for part in (path, *path.parents):
        if _linked(part):
            _fail()


def _lexists(path):
    return os.path.lexists(path)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _fail()
    return remaining


def _source_path(home, paper_service, relative=PAPER_PATH):
    _reject_link_chain(home)
    if not home.is_dir():
        _fail()
    if relative not in (PAPER_PATH, WW_PAPER_PATH):
        _fail()
    path = home / relative
    _reject_link_chain(path)
    if (not (home / "web").is_dir()
            or not path.parent.is_dir()
            or not path.is_file()
            or not stat.S_ISREG(path.stat().st_mode)):
        _fail()
    ledger_path = _absolute(paper_service.ledger.path)
    if ledger_path != path or ledger_path.resolve(strict=True) != path.resolve(strict=True):
        _fail()
    return path


def _destination(path, home, *, require_empty):
    _reject_link_chain(path)
    if not path.is_dir():
        _fail()
    resolved, source = path.resolve(strict=True), home.resolve(strict=True)
    # The actual Runtime creates etf-backup-* directly inside home/web/scratch.
    # copy_business excludes the entire web tree, so that location cannot copy
    # itself recursively. No other destination inside home is accepted.
    if source.is_relative_to(resolved):
        _fail()
    if resolved.is_relative_to(source):
        scratch = home / "web/scratch"
        _reject_link_chain(scratch)
        if not scratch.is_dir() or resolved.parent != scratch.resolve(strict=True):
            _fail()
    if _lexists(path / "web"):
        _fail()
    if require_empty and next(path.iterdir(), None) is not None:
        _fail()


def _verify_snapshot(path, deadline):
    _remaining(deadline)
    # immutable is safe only for this finished, privately owned snapshot.
    uri = path.as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        check = connection.execute("PRAGMA integrity_check").fetchall()
        if check != [("ok",)]:
            _fail()
        rows = connection.execute("SELECT id,data FROM ledger LIMIT 2").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            _fail()
        data = json.loads(rows[0][1])
        required = {
            "revision", "account", "positions", "orders", "fills", "quotes",
            "signal", "plan", "events", "observations", "commands", "reset_at",
        }
        if not isinstance(data, dict) or not required.issubset(data):
            _fail()
        if (type(data["revision"]) is not int or data["revision"] < 0
                or not isinstance(data["reset_at"], str) or not data["reset_at"]):
            _fail()
        for name in ("positions", "quotes", "observations", "commands"):
            if not isinstance(data[name], dict):
                _fail()
        for name in ("orders", "fills", "events"):
            if not isinstance(data[name], list):
                _fail()
        for name in ("account", "signal", "plan"):
            if data[name] is not None and not isinstance(data[name], dict):
                _fail()
    _remaining(deadline)


def _sqlite_snapshot(source, target, deadline):
    with closing(sqlite3.connect(
        source.as_uri() + "?mode=ro", uri=True,
        timeout=min(0.1, _remaining(deadline)), isolation_level=None,
    )) as old, closing(sqlite3.connect(target, timeout=0.1)) as new:
        old.execute("PRAGMA query_only=ON")

        def progress(_status, _remaining_pages, _total_pages):
            _remaining(deadline)

        old.backup(new, pages=64, progress=progress, sleep=0.01)
    _remaining(deadline)
    _verify_snapshot(target, deadline)
    # No destination WAL/SHM/journal may be required for this standalone file.
    if any(_lexists(Path(str(target) + suffix)) for suffix in ("-wal", "-shm", "-journal")):
        _fail()


def _copy_history(home, destination, relative, deadline):
    """Copy immutable accepted history only while both source writers are guarded."""
    source = home / relative
    _reject_link_chain(source)
    if not _lexists(source):
        return None
    if not source.is_dir():
        _fail()
    from realtime_paper_history import AcceptedHistory
    files = []
    # Inspect each allowed directory before traversing it; never recurse through
    # a source junction/symlink or collect an unbounded tree before timeout checks.
    for section in source.iterdir():
        _remaining(deadline)
        _reject_link_chain(section)
        if section.name not in ('checkpoints', 'audits') or not section.is_dir():
            _fail()
        for path in section.iterdir():
            _remaining(deadline)
            _reject_link_chain(path)
            if (not path.is_file() or not stat.S_ISREG(path.stat().st_mode)
                    or path.suffix != '.json' or len(files) >= 20000):
                _fail()
            inside = path.relative_to(source)
            AcceptedHistory._read(path)  # Validate its embedded integrity digest.
            target = destination / relative / inside
            _reject_link_chain(target)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if _lexists(target):
                _fail()
            shutil.copyfile(path, target)
            os.chmod(target, 0o600)
            AcceptedHistory._read(target)
            files.append((Path(relative) / inside).as_posix())
    return dict(schema=HISTORY_BACKUP_SCHEMA, path=relative, files=sorted(files),
                method='guarded-file-copy', integrity='verified')


def snapshot_business_for_backup(
    home, destination, copy_business, paper_service, timeout=15, *, additional_services=None,
):
    """Freeze old business plus the exact paper DB into an empty trusted temp dir.

    Lock ordering: caller-owned Runtime executor -> public paper backup_guard.
    Destinations may be external temporary trees or new direct children of the
    actual Runtime's home/web/scratch. Every existing ancestor must be link-free.
    The timeout bounds guard acquisition and SQLite retries. The synchronous old
    copy callback cannot be preempted; its elapsed time is checked on return.
    The default 15 seconds is a prototype default, not a production size budget:
    the host must explicitly set a suitable timeout from actual backup size and
    measured copy duration so previously supported large backups can complete.
    The caller owns disposal of any partial temporary tree after an error.
    """
    targets = []
    try:
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            _fail()
        deadline = time.monotonic() + timeout
        if paper_service is None or not callable(getattr(paper_service, "backup_guard", None)):
            _fail()
        if not callable(copy_business):
            _fail()
        home, destination = _absolute(home), _absolute(destination)
        services = [(PAPER_PATH, paper_service)]
        extra = additional_services or {}
        if not isinstance(extra, dict) or set(extra) - {"D0I-BOND-WW"}:
            _fail()
        ww = extra.get("D0I-BOND-WW")
        # Never silently omit an existing independently writable WW ledger.
        if ww is None and (_lexists(home / WW_PAPER_PATH)
                           or _lexists(home / HISTORY_PATHS['realtime_paper_ww_history'])):
            _fail()
        if ww is not None:
            if not callable(getattr(ww, "backup_guard", None)):
                _fail()
            services.append((WW_PAPER_PATH, ww))
        for relative, service in services:
            _source_path(home, service, relative)
        _destination(destination, home, require_empty=True)
        completed = False
        histories = {}
        with ExitStack() as guards:
            for _, service in services:
                guards.enter_context(service.backup_guard(timeout=_remaining(deadline)))
            _remaining(deadline)
            started = datetime.now(timezone.utc).isoformat()
            copy_business(home, destination)
            _remaining(deadline)
            # The old callback must still exclude the complete web directory.
            _destination(destination, home, require_empty=False)
            (destination / "web").mkdir(mode=0o700)
            for relative, service in services:
                source = _source_path(home, service, relative)
                target = destination / relative
                target.parent.mkdir(mode=0o700)
                _reject_link_chain(target)
                if _lexists(target):
                    _fail()
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                descriptor = os.open(target, flags, 0o600)
                targets.append(target)
                os.close(descriptor)
                _sqlite_snapshot(source, target, deadline)
                _remaining(deadline)
            for key, relative in HISTORY_PATHS.items():
                history = _copy_history(home, destination, relative, deadline)
                if history is not None:
                    histories[key] = history
            completed = True
        # A context manager may suppress an exception from its body.
        # Successful release alone does not prove the snapshot finished.
        if not completed:
            _fail()
        # Returning success also requires the guard's successful release.
        _remaining(deadline)
        component = {
            "schema": BACKUP_SCHEMA,
            "path": PAPER_PATH,
            "snapshot_started_at": started,
            "snapshot_completed_at": datetime.now(timezone.utc).isoformat(),
            "method": "sqlite-backup-api",
            "integrity": "verified",
        }
        extras = dict(histories)
        if ww is not None:
            extras["realtime_paper_ww"] = {
                **component, "path": WW_PAPER_PATH, "strategy": "D0I-BOND-WW"}
        if extras:
            component["additional_components"] = extras
        return component
    except Exception:
        # A failed scratch tree must never be packaged or registered by callers.
        for target in targets:
            for suffix in ("", "-wal", "-shm", "-journal"):
                try:
                    Path(str(target) + suffix).unlink(missing_ok=True)
                except OSError:
                    pass
        raise BusinessBackupError("BUSINESS_BACKUP_FAILED") from None
