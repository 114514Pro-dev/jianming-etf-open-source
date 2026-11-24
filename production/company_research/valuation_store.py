"""Append-only user forecasts. Read/preview never creates a database."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid


class RevisionConflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ValuationStore:
    def __init__(self, path):
        self.path = Path(path)

    def _check_path(self):
        for path in (self.path, *self.path.parents):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("估值留档路径不能是符号链接或目录联接")

    def history(self, code):
        self._check_path()
        if not self.path.is_file():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            # A concurrent first writer may have created the file but not yet
            # committed its schema. There are no committed forecasts to read.
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='predictions'").fetchone():
                return []
            return [json.loads(row[0]) for row in db.execute(
                "SELECT record FROM predictions WHERE company_code=? ORDER BY seq DESC LIMIT 20", (code,))]

    def save(self, code, payload, result, context, revision_note, expected_latest_id):
        self._check_path()
        digest = hashlib.sha256(canonical({"payload": payload, "result": result, "context": context,
                                          "revision_note": revision_note}).encode()).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_path()
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS predictions (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, company_code TEXT NOT NULL, digest TEXT NOT NULL, record TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS predictions_company ON predictions(company_code,seq)")
            db.execute("CREATE TRIGGER IF NOT EXISTS predictions_no_update BEFORE UPDATE ON predictions BEGIN SELECT RAISE(ABORT,'immutable_prediction'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS predictions_no_delete BEFORE DELETE ON predictions BEGIN SELECT RAISE(ABORT,'immutable_prediction'); END")
            previous = db.execute("SELECT id,digest,record FROM predictions WHERE company_code=? ORDER BY seq DESC LIMIT 1", (code,)).fetchone()
            if previous and previous[1] == digest:
                return json.loads(previous[2])
            if expected_latest_id != (previous[0] if previous else None):
                raise RevisionConflict("已出现新的估值留档，请重新读取后核对，再保存此次修订。")
            record = {"id": uuid.uuid4().hex, "company_code": code,
                      "observed_at": datetime.now(timezone.utc).isoformat(),
                      "payload": payload, "result": result, "context": context,
                      "revision_note": revision_note, "previous_id": previous[0] if previous else None,
                      "fingerprint": digest}
            db.execute("INSERT INTO predictions(id,company_code,digest,record) VALUES(?,?,?,?)",
                       (record["id"], code, digest, canonical(record)))
            return record
