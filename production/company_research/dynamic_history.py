"""Append-only observed financial evaluations, independent of paid research/account data.

These are observations made by this application, never reconstructed historical
availability. Reads do not write, prune, or repair records. An A -> B -> A change
is three observations; repeated unchanged scans and restarts are one.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _change(previous, current):
    if not previous:
        return None, ["首次记录；此前评价历史未回填"]
    if previous.get("version") != current.get("version"):
        return None, ["评价规则版本更新；不同版本不计算分数升降"]
    reasons = []
    same_period = previous.get("report_date") == current.get("report_date")
    same_industry = previous.get("industry") == current.get("industry")
    same_coverage = previous.get("coverage") == current.get("coverage")
    if not same_period:
        reasons.append("财务报告期更新；不同报告期分开观察")
    if not same_industry:
        reasons.append("行业分组变化；不同分组不计算分数升降")
    if not same_coverage:
        reasons.append("资料覆盖变化；不能把补齐资料当作经营改善")
    if previous.get("status") != current.get("status"):
        reasons.append("评价适用性或风险状态变化")
    if previous.get("risk") != current.get("risk"):
        reasons.append("风险提示变化，请查看具体事项")
    if previous.get("company_fingerprint") != current.get("company_fingerprint"):
        reasons.append("公司财务或披露条件变化；同报告期变化可能来自资料修订")
    if previous.get("peer_fingerprint") != current.get("peer_fingerprint"):
        reasons.append("同行成员或财务数据变化；相对位置变化不等于公司自身变化")
    delta = None
    before, after = previous.get("relative_score"), current.get("relative_score")
    if (same_period and same_industry and same_coverage
            and previous.get("status") == current.get("status") == "ready"
            and type(before) in (int, float) and type(after) in (int, float)):
        delta = round(after - before, 2)
    return delta, reasons or ["评价依据更新"]


def _snapshot(evaluation):
    """Keep sufficient original inputs to audit reasons, not a current overwritten view."""
    keys = ("version", "code", "status", "relative_score", "legacy_score", "industry",
            "report_date", "announced_at", "as_of", "peer_count", "coverage", "metrics",
            "risk", "evidence", "company_fingerprint", "peer_fingerprint", "input_fingerprint")
    return {key: deepcopy(evaluation.get(key)) for key in keys}


def _decode(raw, code):
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get("code") != code
            or not isinstance(value.get("version"), str)
            or not isinstance(value.get("reasons"), list)
            or not isinstance(value.get("observed_at"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("input_fingerprint")))):
        raise ValueError("Invalid saved evaluation observation")
    if datetime.fromisoformat(value["observed_at"]).tzinfo is None:
        raise ValueError("Observation timezone missing")
    return value


class EvaluationHistory:
    def __init__(self, path):
        self.path = Path(path).absolute()
        if self.path.is_symlink():
            raise ValueError("Evaluation history path cannot be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    version TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS observation_company ON observations(code,id);
            """)

    @contextmanager
    def _db(self, readonly=False):
        if self.path.is_symlink():
            raise ValueError("Evaluation history path cannot be a symlink")
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro" if readonly else str(self.path),
                             uri=readonly, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            if readonly:
                db.execute("PRAGMA query_only=ON")
            with db:
                yield db
        finally:
            db.close()

    def record(self, evaluations, *, observed_at):
        time = datetime.fromisoformat(observed_at)
        if time.tzinfo is None:
            raise ValueError("Observation time must include its timezone")
        inserted = 0
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = {row["code"]: row for row in db.execute(
                "SELECT o.* FROM observations o JOIN (SELECT code,max(id) id FROM observations GROUP BY code) x ON o.id=x.id")}
            for code, evaluation in sorted(evaluations.items()):
                if not re.fullmatch(r"\d{6}", code) or evaluation.get("code") != code:
                    raise ValueError("Invalid evaluation company identity")
                version = evaluation.get("version")
                fingerprint = evaluation.get("input_fingerprint")
                if not isinstance(version, str) or not re.fullmatch(r"[a-f0-9]{64}", str(fingerprint)):
                    raise ValueError("Evaluation version and fingerprint are required")
                previous_row = latest.get(code)
                if previous_row and previous_row["version"] == version and previous_row["fingerprint"] == fingerprint:
                    continue
                if previous_row and datetime.fromisoformat(previous_row["observed_at"]) > time:
                    raise ValueError("Refuse a backdated observation")
                previous = _decode(previous_row["payload"], code) if previous_row else None
                record = _snapshot(evaluation)
                delta, reasons = _change(previous, record)
                record.update(observed_at=observed_at, delta=delta, reasons=reasons,
                              previous_observed_at=previous_row["observed_at"] if previous_row else None)
                db.execute("INSERT INTO observations(code,observed_at,version,fingerprint,payload) VALUES(?,?,?,?,?)",
                    (code, observed_at, version, fingerprint, _encode(record)))
                inserted += 1
        return inserted

    def views(self, evaluations, *, include_history=False):
        codes = list(evaluations)
        if not codes:
            return {}
        if any(not re.fullmatch(r"\d{6}", code) for code in codes):
            raise ValueError("Invalid evaluation company identity")
        result = {}
        with self._db(readonly=True) as db:
            for code, current in evaluations.items():
                latest = db.execute("SELECT payload FROM observations WHERE code=? ORDER BY id DESC LIMIT 1", (code,)).fetchone()
                count = db.execute("SELECT count(*) FROM observations WHERE code=?", (code,)).fetchone()[0]
                last = _decode(latest["payload"], code) if latest else None
                matched = bool(last and last.get("version") == current.get("version")
                               and last.get("input_fingerprint") == current.get("input_fingerprint"))
                tracking = {"status": "first_record" if matched and count == 1 else "recorded" if matched else "pending",
                    "observed_at": last.get("observed_at") if matched else None,
                    "previous_observed_at": last.get("previous_observed_at") if matched else last.get("observed_at") if last else None,
                    "delta": last.get("delta") if matched else None,
                    "reasons": last.get("reasons", []) if matched else ["当前评价尚待后台记录；保留已有观察历史"],
                    "history_count": count, "historical_pit_usable": False}
                result[code] = {"tracking": tracking}
                if include_history:
                    rows = db.execute("SELECT payload FROM observations WHERE code=? ORDER BY id DESC LIMIT 20", (code,)).fetchall()
                    keys = ("observed_at", "version", "report_date", "relative_score", "legacy_score", "delta", "reasons")
                    records = [_decode(row["payload"], code) for row in rows]
                    result[code]["history"] = [{k: record.get(k) for k in keys} for record in records]
        return result
