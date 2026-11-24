"""Durable, isolated company research. Never imports or calls trading engines."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .industry_data import (INDUSTRY_ADAPTER_VERSION, INDUSTRY_GATE_VERSION, build_industry_view,
    recover_saved_industry_view, recover_scan_industry_inputs, apply_industry_policy_to_screen, apply_industry_policy_to_report)
from .industry_policy import INDUSTRY_POLICY_VERSION

CN = timezone(timedelta(hours=8))
FINAL = {"succeeded", "partial", "failed", "cancelled", "interrupted"}
DEFAULTS = {"auto_scan": False, "auto_ai": False, "ai_daily_limit": 0, "provider": "openai_compatible",
            "deep_research_rounds": 6,
            "base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-pro",
            "max_output_tokens": 4500, "timeout": 90}
# The 1.5 AI adapter receives source excerpts, not the deterministic score report.
# Preserve existing paid evidence when only the financial rules gain a new view.
# An AI input/contract change must instead change the adapter/evidence version.
AI_CACHE_RULES_VERSION = "company-research-rules-1.0"


def stamp():
    return datetime.now(CN).isoformat(timespec="seconds")


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _market_json_pieces(value):
    """Encode plain market objects in order, one company at a time."""
    if (type(value) is not dict or not all(type(key) is str for key in value)
            or type(value.get("companies")) is not list):
        yield encode(value)
        return
    yield "{"
    for index, (key, item) in enumerate(value.items()):
        if index:
            yield ","
        yield encode(key)
        yield ":"
        if key == "companies":
            yield "["
            for company_index, company in enumerate(item):
                if company_index:
                    yield ","
                yield encode(company)
            yield "]"
        else:
            yield encode(item)
    yield "}"


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + secrets.token_hex(5) + ".tmp")
    try:
        with tmp.open("x", encoding="utf8") as f:
            os.chmod(tmp, 0o600)
            f.write(encode(value))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read(path, default):
    try:
        return json.loads(Path(path).read_text("utf8"))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def evidence_fingerprint(value):
    """Observation timestamps do not create a new paid research request."""
    if isinstance(value, dict):
        result = {k: evidence_fingerprint(v) for k, v in value.items()
                if k not in {"as_of", "fetched_at", "downloaded_at", "retrieved_at", "updated_at", "screen", "ai_status",
                             "debt_financial_records", "debt_adapter_version", "debt_adapter", "debt_governance", "data_recovery",
                             "business_statements", "business_adapter_version", "business_qualitative_evidence",
                             "business_data_recovery", "business_capital", "industry_adapter_version", "industry_profile_input",
                             "industry_data_recovery", "industry_profile", "industry_applicability",
                             "price_quality_panel", "price_quality_refresh"}}
        # These two field-level annotations were added by rules 1.1. The AI
        # evidence adapter does not receive them; keep 1.0 saved signatures
        # compatible while retaining document/row publication dates and values.
        fields = result.get("field_sources")
        if isinstance(fields, dict):
            result["field_sources"] = {
                key: {k: v for k, v in source.items() if k not in {"report_date", "announced_at"}}
                if isinstance(source, dict) else source for key, source in fields.items()}
        return result
    if isinstance(value, list):
        return [evidence_fingerprint(v) for v in value]
    return value


class ResearchService:
    def __init__(self, folder, *, data_client=None, screen=None, analyzer=None,
                 ai_factory=None, deep_data_client=None, deep_ai_factory=None, start=True):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.halt = threading.Event()
        self.wake = threading.Event()
        self.stop_events = {}
        self.settings_path = self.folder / "settings.private.json"
        self.config = {**DEFAULTS, **read(self.settings_path, {})}
        if data_client is None:
            self._install_seed()
        self.snapshot = read(self.folder / "market.json", {"companies": [], "coverage": {}})
        self.dbpath = self.folder / "research.sqlite3"
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, code TEXT, status TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_usage (
              id TEXT PRIMARY KEY, day TEXT NOT NULL, job_id TEXT NOT NULL,
              status TEXT NOT NULL, usage TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created_at);
            """)
            for row in db.execute("SELECT id,payload FROM jobs WHERE status='running'").fetchall():
                job = json.loads(row["payload"])
                job.update(status="interrupted", message="服务重启中断了研究，可重新运行", updated_at=stamp())
                db.execute("UPDATE jobs SET status=?,updated_at=?,payload=? WHERE id=?",
                           (job["status"], job["updated_at"], encode(job), row["id"]))
        if data_client is None:
            from .data import DataClient
            data_client = DataClient(self.folder / "cache")
        if screen is None or analyzer is None:
            from .engine import screen_company, analyze_company
            screen = screen or screen_company
            analyzer = analyzer or analyze_company
        if ai_factory is None:
            from .ai import AIClient
            ai_factory = AIClient
        self.data, self.screen, self.analyzer, self.ai_factory = data_client, screen, analyzer, ai_factory
        self.deep_data, self.deep_ai_factory = deep_data_client, deep_ai_factory
        self._deep_library_cache = {}
        self._evaluation_history = None
        self._dynamic_tracking_error = None
        self._record_dynamic_evaluations()
        self.thread = threading.Thread(target=self._loop, name="company-research", daemon=True)
        if start:
            self.thread.start()

    def _install_seed(self):
        """First-use public snapshot only; never overwrite persisted research."""
        if (self.folder / "market.json").exists():
            return
        seed = Path(__file__).resolve().parent / "seed"
        manifest = read(seed / "manifest.json", {})
        records = manifest.get("files", {})
        if not records:
            return
        # Validate the entire bundle before publication without retaining all
        # decoded source trees. The market file remains the last commit marker.
        with tempfile.TemporaryDirectory(prefix=".seed-", dir=self.folder) as temporary:
            staged_root = Path(temporary)
            validated = []
            for relative, sha in records.items():
                path = Path(relative)
                if path.is_absolute() or ".." in path.parts or str(path).startswith("\\") or ":" in relative:
                    raise ValueError("初始研究资料路径无效")
                if relative not in {"market.json", "cache/scan-latest.json"} and not re.fullmatch(r"cache/raw/[a-f0-9]{64}-[a-f0-9]{16}\.json", relative):
                    raise ValueError("初始研究资料包含非公开数据路径")
                with gzip.open(seed / (relative + ".gz"), "rb") as f:
                    raw = f.read(100_000_001)
                if len(raw) > 100_000_000 or hashlib.sha256(raw).hexdigest() != sha:
                    raise ValueError("初始研究资料校验未通过")
                content = json.loads(raw)
                del raw
                staged = staged_root / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                with staged.open("x", encoding="utf8") as f:
                    os.chmod(staged, 0o600)
                    for piece in _market_json_pieces(content):
                        for offset in range(0, len(piece), 64 * 1024):
                            f.write(piece[offset:offset + 64 * 1024])
                        del piece
                    f.flush()
                    os.fsync(f.fileno())
                del content
                validated.append(relative)
            for relative in validated:
                destination = self.folder / relative
                if relative != "market.json" and not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged_root / relative, destination)
            if "market.json" in validated:
                os.replace(staged_root / "market.json", self.folder / "market.json")

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.dbpath, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def public_settings(self):
        with self.lock:
            result = {k: self.config.get(k, v) for k, v in DEFAULTS.items()}
            result["key_configured"] = bool(self.config.get("api_key"))
        return result

    def set_settings(self, body):
        if not isinstance(body, dict) or set(body) - set(DEFAULTS) - {"api_key", "clear_api_key"}:
            raise ValueError("研究设置含未知字段")
        with self.lock:
            new = {**self.config, **{k: v for k, v in body.items() if k in DEFAULTS}}
            if type(new["auto_scan"]) is not bool or type(new["auto_ai"]) is not bool:
                raise ValueError("自动扫描设置无效")
            if type(new["ai_daily_limit"]) is not int or not 0 <= new["ai_daily_limit"] <= 100:
                raise ValueError("AI每日调用上限须为0至100次")
            if type(new["deep_research_rounds"]) is not int or new["deep_research_rounds"] not in (3, 6):
                raise ValueError("深度研究轮数须为3或6")
            if new["provider"] not in {"openai", "openai_compatible"}:
                raise ValueError("AI服务类型无效")
            if not isinstance(new["base_url"], str):
                raise ValueError("API地址无效")
            new["base_url"] = new["base_url"].rstrip("/")
            if new["base_url"] not in {"https://api.openai.com/v1", "https://api.deepseek.com/v1", "https://api.deepseek.com"}:
                raise ValueError("目前仅支持OpenAI或DeepSeek的官方HTTPS接口")
            if new["provider"] == "openai" and new["base_url"] != "https://api.openai.com/v1":
                raise ValueError("OpenAI接口类型须使用OpenAI官方地址；DeepSeek请选择兼容接口")
            if not isinstance(new["model"], str) or len(new["model"]) > 100 or (new["model"] and not re.fullmatch(r"[A-Za-z0-9_.:/-]+", new["model"])):
                raise ValueError("模型名称无效")
            if type(new["max_output_tokens"]) is not int or not 500 <= new["max_output_tokens"] <= 12000:
                raise ValueError("输出长度上限无效")
            if type(new["timeout"]) is not int or not 15 <= new["timeout"] <= 120:
                raise ValueError("AI超时须为15至120秒")
            old_host = urlsplit(self.config["base_url"]).hostname
            if old_host != urlsplit(new["base_url"]).hostname:
                new.pop("api_key", None)
            if body.get("clear_api_key") is True:
                new.pop("api_key", None)
            if body.get("api_key"):
                key = body["api_key"]
                if not isinstance(key, str) or not 10 <= len(key) <= 512 or any(c.isspace() for c in key):
                    raise ValueError("API密钥格式无效")
                new["api_key"] = key
            if any(new.get(k) != self.config.get(k) for k in ("api_key", "model", "provider", "base_url")):
                new["ai_revision"] = secrets.token_hex(8)
            save(self.settings_path, new)
            self.config = new
        self.wake.set()
        return self.public_settings()

    def ai_status(self):
        settings = self.public_settings()
        current = datetime.now(CN)
        day = current.date().isoformat()
        with self.db() as db:
            used = db.execute("SELECT count(*) FROM ai_usage WHERE day=?", (day,)).fetchone()[0]
        configured = settings["key_configured"] and bool(settings["model"])
        status = "ready" if configured else "unconfigured"
        if configured and used >= settings["ai_daily_limit"]:
            status = "limit_reached"
        return {"status": status, "configured": configured, "used_today": used,
                "daily_limit": settings["ai_daily_limit"], "day": day,
                "remaining": max(0, settings["ai_daily_limit"] - used), "limit_scope": "local_daily_limit",
                "reset_at": (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                "reset_timezone": "Asia/Shanghai",
                "model": settings["model"], "provider": settings["provider"],
                "message": {"ready": "AI接口已配置", "unconfigured": "尚未配置AI密钥和模型，财务筛选可单独运行",
                            "limit_reached": "本程序今日AI调用次数已用尽或上限设为0，北京时间次日0时重置；不是供应商余额检查，财务筛选可继续"}[status]}

    def summary(self):
        with self.lock:
            coverage = copy.deepcopy(self._industry_market_view()["coverage"])
            updated = self.snapshot.get("updated_at")
        with self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE kind='scan' ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
            active_count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            active = db.execute("SELECT id,kind,code,status,created_at,updated_at FROM jobs "
                                "WHERE status IN ('queued','running') ORDER BY created_at,rowid LIMIT 32").fetchall()
        return {"coverage": coverage, "scan": json.loads(row[0]) if row else None,
                "active_jobs": [dict(zip(("id", "kind", "code", "status", "created_at", "updated_at"), item)) for item in active],
                "active_job_count": active_count,
                "settings": self.public_settings(), "ai_status": self.ai_status(), "updated_at": updated}

    def companies(self, query="", industry="", candidate="", sort="quality", offset=0, limit=100):
        if len(query) > 100 or len(industry) > 100 or not 0 <= offset <= 50000 or not 1 <= limit <= 500:
            raise ValueError("公司筛选参数无效")
        with self.lock:
            rows = self._industry_market_view()["rows"]
        query = query.strip().lower()
        rows = [c for c in rows if (not query or query in (str(c.get("code", "")) + str(c.get("name", ""))).lower())
                and (not industry or c.get("industry") == industry)
                and (candidate not in {"true", "1", "yes"} or c.get("screen", {}).get("candidate"))]
        if sort == "code":
            rows.sort(key=lambda c: c["code"])
        elif sort == "risk":
            ranks = {"low": 0, "medium": 1, "high": 2, "unknown": 3, "低": 0, "中": 1, "高": 2}
            rows.sort(key=lambda c: (ranks.get(c.get("screen", {}).get("risk_level"), 3), c["code"]))
        elif sort == "valuation":
            rows.sort(key=lambda c: (c.get("pe_ttm") is None or c.get("pe_ttm", 0) <= 0,
                                     c.get("pe_ttm") if isinstance(c.get("pe_ttm"), (int, float)) and c["pe_ttm"] > 0 else float("inf"), c["code"]))
        elif sort == "dynamic":
            evaluations = self._dynamic_market_view()
            def dynamic_order(company):
                score = evaluations.get(company["code"], {}).get("relative_score")
                return (score is None, -score if score is not None else 0, company["code"])
            rows.sort(key=dynamic_order)
        else:
            rows.sort(key=lambda c: (-(c.get("screen", {}).get("quality_score") or -1), c["code"]))
        selected = copy.deepcopy(rows[offset:offset + limit])
        evaluations = self._dynamic_views([c["code"] for c in selected])
        for company in selected:
            company["dynamic_evaluation"] = evaluations.get(company["code"])
        return {"companies": selected, "total": len(rows), "offset": offset, "limit": limit}

    def _company(self, code):
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            raise ValueError("股票代码须为6位数字")
        with self.lock:
            company = next((c for c in self.snapshot.get("companies", []) if c["code"] == code), None)
            if not company:
                raise ValueError("公司不在已核验的扫描快照内，请先运行全市场扫描")
            return copy.deepcopy(company)

    def company(self, code):
        company = self._company(code)
        detail = read(self.folder / "reports" / (code + ".json"), {})
        stored_detail = copy.deepcopy(detail)
        with self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE code=? AND kind='analyze' ORDER BY created_at DESC,rowid DESC LIMIT 1", (code,)).fetchone()
        result = {"company": company, "screen": company.get("screen"), "report": None,
                  "ai": {"status": "not_analyzed"}, **detail,
                  "job": json.loads(row[0]) if row else None}
        if not detail:
            with self.lock:
                sources = [s for s in self.snapshot.get("sources", []) if s.get("id") in company.get("source_ids", []) or s.get("id") == company.get("quote_source_id")]
                peers = [c for c in self.snapshot.get("companies", []) if c.get("industry") == company.get("industry") and c.get("report_date") == company.get("report_date")]
            current_industry = copy.deepcopy(self._industry_market_inputs().get(code, {}))
            if not current_industry:
                current_industry = {k: copy.deepcopy(company[k]) for k in
                    ("industry_adapter_version", "industry_profile_input", "industry_data_recovery") if k in company}
            result["report"] = self.analyzer({"company": company, "sources": sources, "history": [], "documents": [],
                                              **current_industry,
                                              "warnings": ["这里只包含最近一期财务快照；点击补齐资料可取得历年财务与官方财报正文。"]}, peers=peers)
            current_profile = build_industry_view({"company": company, **current_industry}, as_of=company.get("as_of"))
            apply_industry_policy_to_report(result["report"], current_profile)
            result["screen"] = self._screen_ui(company, self.screen(company, peers=peers), current_profile)
            result["sources"] = sources
            result["company"]["sources"] = sources
            result["company"]["financials"] = [{**company, "period": company.get("report_date"), "operating_cash_flow": company.get("op_cashflow")}]
            result["company"]["peers"] = sorted((c for c in peers if c["code"] != code), key=lambda c: -(c.get("screen", {}).get("quality_score") or -1))[:8]
        result["report_stale"] = bool(detail and detail.get("market_fingerprint") != self._market_fingerprint(company))
        result["valuation_updated"] = False
        result["analysis_valuation_as_of"] = detail.get("company", {}).get("valuation_as_of")
        market_quote_date = company.get("valuation_as_of") or ""
        detail_quote_date = result["analysis_valuation_as_of"] or ""
        if detail and market_quote_date >= detail_quote_date:
            price_keys = ("pe_ttm", "pb", "price", "market_cap", "valuation_as_of", "valuation_basis", "quote_fetched_at", "quote_source_id")
            result["valuation_updated"] = any(detail.get("company", {}).get(k) != company.get(k)
                                               for k in ("pe_ttm", "pb", "price", "valuation_as_of"))
            # Current prices are read-only overlays, not a reason to pay for AI again.
            # Keep financial history, quality and model claims at their original dates.
            for k in price_keys:
                result["company"][k] = company.get(k)
            field_sources = result["company"].setdefault("field_sources", {})
            for k in ("pe_ttm", "pb", "price", "market_cap"):
                field_sources.pop(k, None)
                if k in company.get("field_sources", {}):
                    field_sources[k] = copy.deepcopy(company["field_sources"][k])
            if company.get("quote_source_id"):
                result["company"]["source_ids"] = sorted(set(result["company"].get("source_ids", [])) | {company["quote_source_id"]})
            latest_screen = company.get("screen", {})
            result["screen"]["valuation"] = copy.deepcopy(latest_screen.get("valuation", {}))
            result["screen"]["valuation_label"] = latest_screen.get("valuation_label")
            price_metrics = {m["key"]: m for m in latest_screen.get("metrics", []) if m.get("key") in {"pe_ttm", "pb"}}
            result["screen"]["metrics"] = [copy.deepcopy(price_metrics.get(m.get("key"), m)) for m in result["screen"].get("metrics", [])]
            result["company"]["screen"] = copy.deepcopy(result["screen"])
            if result.get("report"):
                result["report"]["valuation"] = {"pe_ttm": company.get("pe_ttm"), "pb": company.get("pb"),
                    "as_of": company.get("valuation_as_of"), "label": latest_screen.get("valuation_label"),
                    "note": "此处为最新市场快照估值；AI解读保留生成时的证据和时间。"}
            with self.lock:
                quote_sources = [s for s in self.snapshot.get("sources", []) if s.get("id") == company.get("quote_source_id")]
            for source in quote_sources:
                for target in (result, result["company"]):
                    target["sources"] = [s for s in target.get("sources", []) if s.get("id") != source["id"]] + [copy.deepcopy(source)]
        self._refresh_long_term_view(result, detail)
        self._refresh_debt_governance_view(result, stored_detail)
        self._refresh_business_capital_view(result, stored_detail)
        self._refresh_industry_view(result, stored_detail)
        self._refresh_price_quality_view(result, stored_detail)
        # A detail can lag behind a later market scan; make both timestamps visible.
        result["market_updated_at"] = self.snapshot.get("updated_at")
        result["dynamic_evaluation"] = self._dynamic_detail(code, result.get("report"))
        from .quality_checks import build_quality_checks
        result["quality_checks"] = build_quality_checks(result.get("report"), company_code=code)
        return result

    @staticmethod
    def _refresh_long_term_view(result, stored):
        """Recompute a new read-only rules view from the original saved evidence.

        This does not rewrite saved reports, their AI responses, timestamps or
        scores. A quotation overlay must never become a new financial as-of date.
        Missing original PDF values remain unverified, even if links are present.
        """
        from .long_term import LONG_TERM_VERSION, analyze_long_term
        report = result.get("report")
        if not isinstance(report, dict):
            return
        quality = report.setdefault("quality", {})
        if not isinstance(quality, dict):
            return
        current = quality.get("long_term")
        if isinstance(current, dict) and current.get("version") == LONG_TERM_VERSION:
            result["long_term_refresh"] = {"from_saved_data": bool(stored),
                "source_report_updated_at": stored.get("updated_at") if stored else None,
                "rules_version": LONG_TERM_VERSION, "ai_call_required": False}
            return
        old_company = stored.get("company") if isinstance(stored, dict) else None
        company = copy.deepcopy(old_company if isinstance(old_company, dict) else result.get("company", {}))
        history = quality.get("history")
        if not isinstance(history, list) or not history:
            history = company.get("financials") or []
        canonical = []
        for row in history:
            if not isinstance(row, dict):
                continue
            row = copy.deepcopy(row)
            row.setdefault("report_date", row.get("period") or row.get("report_period"))
            if "op_cashflow" not in row:
                row["op_cashflow"] = row.get("operating_cash_flow")
            canonical.append(row)
        as_of = company.get("as_of") or (stored.get("updated_at", "")[:10] if stored else None)
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        old_conflict = any(isinstance(f, dict) and f.get("code") in {"conflicting_period", "source_conflict"}
                           for f in summary.get("flags", []))
        conflicts = ([r.get("report_date") for r in canonical] or [company.get("report_date")]) if old_conflict else None
        quality["long_term"] = analyze_long_term(company, canonical, as_of=as_of,
            documents=report.get("evidence") or [],
            conflicts=conflicts, industry_model=summary.get("industry_model"))
        result["long_term_refresh"] = {"from_saved_data": bool(stored),
            "source_report_updated_at": stored.get("updated_at") if stored else None,
            "rules_version": quality["long_term"].get("version"), "ai_call_required": False}

    def _refresh_debt_governance_view(self, result, stored):
        """Add the versioned debt view without changing saved research or AI.

        The original report fixes the subject, cutoff and source identities.
        Full cached text is supplemental evidence only for its saved document
        IDs; a newer company cache never becomes a newer financial snapshot.
        """
        from .debt_data import ADAPTER_VERSION, enrich_debt_bundle
        from .debt_governance import VERSION, build_debt_governance
        from .debt_recovery import SUPPORTED_REPORTS, read_cached_company_bundle, recover_debt_records
        report = result.get("report")
        if not isinstance(report, dict):
            return
        existing = report.get("debt_governance")
        refresh = {"from_saved_data": bool(stored), "source_report_updated_at": stored.get("updated_at") if stored else None,
                   "rules_version": VERSION, "adapter_version": ADAPTER_VERSION, "ai_call_required": False}
        if isinstance(existing, dict) and existing.get("engine_version") == VERSION:
            result["debt_governance_refresh"] = {**refresh, "as_of": existing.get("as_of"),
                "recovery_status": (existing.get("data_recovery") or {}).get("status")}
            return
        old_company = stored.get("company") if isinstance(stored, dict) else None
        company = copy.deepcopy(old_company if isinstance(old_company, dict) else result.get("company", {}))
        code = str(company.get("code") or "")
        as_of = company.get("as_of") or (stored.get("updated_at", "")[:10] if stored else None) or company.get("announced_at")
        try:
            as_of = datetime.fromisoformat(str(as_of)[:10]).date().isoformat()
        except (TypeError, ValueError):
            as_of = None
        quality = report.get("quality") if isinstance(report.get("quality"), dict) else {}
        history = quality.get("history") or company.get("financials") or []
        canonical = []
        for original in history if isinstance(history, list) else []:
            if not isinstance(original, dict):
                continue
            row = copy.deepcopy(original)
            row.setdefault("report_date", row.get("period") or row.get("report_period"))
            canonical.append(row)
        cache_dir = getattr(self.data, "cache_dir", self.folder / "cache")
        cached, cache_gaps = read_cached_company_bundle(cache_dir, code)
        sources = copy.deepcopy(stored.get("sources") or company.get("sources") or result.get("sources") or [])
        if not isinstance(sources, list):
            sources = []
        if not sources and cached:
            sources = copy.deepcopy(cached.get("sources") or [])
            cache_gaps.append({"code": "saved_source_manifest_missing_using_company_cache"})
        debt_bundle = {"company": company, "history": canonical, "as_of": as_of,
                       "sources": sources, "documents": []}
        evidence = {str(item["id"]): item for item in report.get("evidence", [])
                    if isinstance(item, dict) and item.get("id")}
        if cached:
            for doc in cached.get("documents") or []:
                if not isinstance(doc, dict) or str(doc.get("id") or "") not in evidence:
                    continue
                saved_doc = evidence[str(doc["id"])]
                if any(saved_doc.get(key) is not None and doc.get(key) != saved_doc.get(key)
                       for key in ("url", "published_at", "sha256")):
                    cache_gaps.append({"code": "saved_document_identity_mismatch", "source_id": doc.get("id")})
                    continue
                debt_bundle["documents"].append(copy.deepcopy(doc))
            expected_sources = {s.get("id"): s for s in sources if isinstance(s, dict) and isinstance(s.get("id"), str)
                and isinstance(s.get("parameters"), dict) and isinstance(s["parameters"].get("reportName"), str)
                and s["parameters"].get("reportName") in SUPPORTED_REPORTS}
            cached_sources = {s.get("id"): s for s in cached.get("sources", []) if isinstance(s, dict) and isinstance(s.get("id"), str)}
            records = cached.get("debt_financial_records")
            # A current normalized cache is reusable only when it represents
            # the same complete set of statement IDs as the saved report.
            if (isinstance(records, list) and records
                    and all(isinstance(r, dict) and isinstance(r.get("source_id"), str) for r in records)
                    and {r.get("source_id") for r in records} == set(expected_sources)
                    and all(sid in cached_sources and all(expected_sources[sid].get(k) == cached_sources[sid].get(k)
                        for k in ("sha256", "raw_file", "parameters", "report_type", "url", "source_url")) for sid in expected_sources)):
                debt_bundle["debt_adapter_version"] = cached.get("debt_adapter_version")
                debt_bundle["debt_financial_records"] = copy.deepcopy(records)
            elif records:
                cache_gaps.append({"code": "cached_normalized_sources_not_saved"})
        if not debt_bundle["documents"]:
            cache_gaps.append({"code": "saved_document_text_unavailable"})
        if not as_of:
            cache_gaps.append({"code": "saved_financial_cutoff_missing"})
            # Do not admit supplemental evidence under an invented historical
            # cutoff. Original scalar facts remain explicitly undated.
            debt_bundle["documents"] = []
            debt_bundle["sources"] = []
            debt_bundle.pop("debt_financial_records", None)
        recovery = recover_debt_records(debt_bundle, cache_dir)
        recovery["gaps"].extend(cache_gaps)
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        old_conflict = any(isinstance(flag, dict) and flag.get("code") in {"conflicting_period", "source_conflict"}
                           for flag in summary.get("flags", []))
        if old_conflict:
            recovery["gaps"].append({"code": "saved_source_conflict_unresolved"})
        if recovery["gaps"] and recovery["records"]:
            recovery["status"] = "partial"
        section = build_debt_governance(enrich_debt_bundle(debt_bundle, recovery["records"], as_of=as_of), as_of=as_of)
        section["data_recovery"] = {key: copy.deepcopy(value) for key, value in recovery.items() if key != "records"}
        for gap in recovery["gaps"]:
            section["gaps"].append({"key": "source_recovery:" + str(gap.get("code")), "state": "needs_review",
                "label": "本地来源恢复存在缺口，未联网补齐或填零", "reason": gap.get("code"),
                "source_id": gap.get("source_id"), "report_type": gap.get("report_type")})
        if old_conflict:
            section["priority_risks"].append({"code": "saved_source_conflict", "level": "high",
                "message": "原报告保留来源冲突，尚未逐项核清；新增债务资料不能清除该风险。", "evidence_refs": []})
        report["debt_governance"] = section
        result["debt_governance_refresh"] = {**refresh, "as_of": section.get("as_of"), "recovery_status": recovery["status"]}

    def _refresh_business_capital_view(self, result, stored):
        """Append only the versioned read-only business view; no paid work."""
        from .business_capital import BUSINESS_CAPITAL_VERSION
        from .business_data import BUSINESS_ADAPTER_VERSION, recover_saved_business_view
        report = result.get("report")
        if not isinstance(report, dict):
            return
        existing = report.get("business_capital")
        if not isinstance(existing, dict) or existing.get("version") != BUSINESS_CAPITAL_VERSION:
            if not isinstance(stored, dict) or not stored.get("company"):
                return
            existing = recover_saved_business_view(stored, getattr(self.data, "cache_dir", self.folder / "cache"))
            report["business_capital"] = existing
        result["business_capital_refresh"] = {"from_saved_data": bool(stored),
            "source_report_updated_at": stored.get("updated_at") if stored else None,
            "rules_version": BUSINESS_CAPITAL_VERSION, "adapter_version": BUSINESS_ADAPTER_VERSION,
            "ai_call_required": False, "as_of": existing.get("as_of"),
            "recovery_status": (existing.get("data_recovery") if isinstance(existing.get("data_recovery"), dict) else {}).get("status")}

    def deep_company(self, code):
        """Read only the independent deep report; never collect or call AI."""
        from .deep_research import VERSION, library_summary
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            raise ValueError("股票代码须为6位数字")
        try:
            report = read(self.folder / "deep-reports" / (code + ".json"), None)
        except RecursionError:
            report = None
        if not isinstance(report, dict) or report.get("version") != VERSION or report.get("company_code") != code:
            report = None
        try:
            company = self._company(code)
        except ValueError:
            try:
                summary = library_summary(report, code)
            except (TypeError, ValueError, KeyError, RecursionError):
                summary = None
            if summary is None:
                raise ValueError("公司不在当前扫描快照内，且没有可验证的已保存深研报告") from None
            company = {"code": code, "name": summary["name"]}
        with self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE code=? AND kind='deep' ORDER BY created_at DESC,rowid DESC LIMIT 1", (code,)).fetchone()
        usage = self.ai_status()
        result = {"company": {"code": code, "name": company.get("name") or code}, "report": report,
                "job": json.loads(row[0]) if row else None, "ai_usage": usage,
                "preflight": self._deep_preflight(code, usage)}
        # Legacy deep jobs collected annual data but accidentally saved the
        # pre-collection ordinary report. Recover a separate read-only view;
        # never rewrite the original report, its AI claims or generated date.
        if report and not isinstance(report.get("financial_context"), dict):
            from .deep_financial import financial_supplement
            result["financial_supplement"] = financial_supplement(report,
                getattr(self.deep_data, "cache_dir", self.folder / "deep-cache"), self.analyzer)
        supplement = result.get("financial_supplement") or {}
        financial = supplement.get("report") if supplement.get("status") == "available" else (report or {}).get("financial_report")
        if isinstance(financial, dict) and isinstance(financial.get("report"), dict):
            financial = financial["report"]
        result["dynamic_evaluation"] = self._dynamic_detail(code, financial)
        from .quality_checks import build_quality_checks
        # A recovered view belongs to this exact saved deep report. Do not let
        # a stale or cross-company supplement supply the independent checklist.
        check_financial = (report or {}).get("financial_report")
        if isinstance(check_financial, dict) and isinstance(check_financial.get("report"), dict):
            check_financial = check_financial["report"]
        recovered = supplement.get("report")
        if (report and supplement.get("status") == "available"
                and isinstance(recovered, dict)
                and isinstance(recovered.get("company"), dict)
                and recovered["company"].get("code") == code
                and supplement.get("source_report_generated_at") == report.get("generated_at")
                and report.get("generated_at")):
            check_financial = recovered
        result["quality_checks"] = build_quality_checks(check_financial, company_code=code)
        return result

    def _dynamic_market_view(self):
        """An independent current view; never attach new data to saved financial/AI input."""
        from .dynamic_evaluation import build_market_evaluations
        from .dynamic_data import recover_dynamic_rows, cache_key
        with self.lock:
            state = self._industry_market_view()
            sources = self.snapshot.get("sources") or []
            cache_dir = getattr(self.data, "cache_dir", self.folder / "cache")
            key = cache_key(sources, cache_dir)
            if "dynamic_evaluations" not in state or state.get("dynamic_source_key") != key:
                cutoff = str(self.snapshot.get("updated_at") or self.snapshot.get("coverage", {}).get("as_of") or stamp())[:10]
                rows = recover_dynamic_rows(state["rows"], sources, cache_dir, as_of=cutoff)
                evaluations = build_market_evaluations(rows, as_of=cutoff)
                if cache_key(sources, cache_dir) != key:
                    raise ValueError("Dynamic financial originals changed during verification; retry")
                state["dynamic_evaluations"] = evaluations
                state["dynamic_source_key"] = key
            return state["dynamic_evaluations"]

    def _record_dynamic_evaluations(self):
        """Write only new observations after startup/successful scans; no historic backfill."""
        try:
            from .dynamic_history import EvaluationHistory
            with self.lock:
                if self._evaluation_history is None:
                    self._evaluation_history = EvaluationHistory(self.folder / "dynamic-evaluations.sqlite3")
                self._evaluation_history.record(self._dynamic_market_view(), observed_at=stamp())
                self._dynamic_tracking_error = None
        except (OSError, ValueError, TypeError, KeyError, ArithmeticError, RecursionError, sqlite3.Error):
            # Research and trading remain usable if the independent observation store fails.
            self._dynamic_tracking_error = "动态评价观察记录暂不可用；原报告与账户保留"

    def _dynamic_views(self, codes, *, detail=False):
        try:
            current = self._dynamic_market_view()
            values = {code: copy.deepcopy(current[code]) for code in codes if code in current}
        except (OSError, ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
            return {}
        tracked = {}
        if self._evaluation_history is not None and not self._dynamic_tracking_error:
            try:
                tracked = self._evaluation_history.views(values, include_history=detail)
            except (OSError, ValueError, TypeError, KeyError, RecursionError, sqlite3.Error):
                tracked = {}
        for code, value in values.items():
            value.update(tracked.get(code, {"tracking": {"status": "unavailable", "observed_at": None,
                "previous_observed_at": None, "delta": None, "history_count": 0,
                "reasons": ["变化记录暂不可用；不从当前资料推造历史"], "historical_pit_usable": False}}))
            if detail:
                value.setdefault("history", [])
            value["price_separate"] = True
        return values

    def _dynamic_detail(self, code, financial=None):
        try:
            return self._dynamic_detail_impl(code, financial)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError, sqlite3.Error):
            # A malformed optional overlay must never hide the existing report.
            return None

    def _dynamic_detail_impl(self, code, financial=None):
        value = self._dynamic_views([code], detail=True).get(code)
        if value is None:
            return None
        sources = [(financial, "current_detail")]
        # Reuse existing saved deep annual data for the new view only; the ordinary
        # saved report and its former financial cutoff are not rewritten.
        def mapping(value):
            return value if isinstance(value, dict) else {}
        existing_coverage = mapping(mapping(mapping(mapping(financial).get("quality")).get("long_term")).get("coverage"))
        complete = existing_coverage.get("complete_years")
        if type(complete) not in (int, float) or complete < 3:
            from .deep_research import VERSION
            saved = read(self.folder / "deep-reports" / (code + ".json"), None)
            if isinstance(saved, dict) and saved.get("version") == VERSION and saved.get("company_code") == code:
                if isinstance(saved.get("financial_context"), dict):
                    candidate = saved.get("financial_report")
                    if isinstance(candidate, dict) and isinstance(candidate.get("report"), dict):
                        candidate = candidate["report"]
                    sources.append((candidate, "saved_deep_report"))
                else:
                    from .deep_financial import financial_supplement
                    recovered = financial_supplement(saved,
                        getattr(self.deep_data, "cache_dir", self.folder / "deep-cache"), self.analyzer)
                    if recovered.get("status") == "available":
                        sources.append((recovered.get("report"), "verified_deep_cache_supplement"))
        candidates = []
        for report, source in sources:
            if not isinstance(report, dict):
                continue
            owner = mapping(report.get("company"))
            if owner.get("code") != code:
                continue
            long_term = mapping(report.get("quality")).get("long_term")
            coverage = mapping(mapping(long_term).get("coverage"))
            if (isinstance(long_term, dict) and type(coverage.get("complete_years")) is int
                    and 0 <= coverage["complete_years"] <= 5
                    and type(coverage.get("consecutive_years")) is int
                    and 0 <= coverage["consecutive_years"] <= 5):
                candidates.append((long_term, source))
        if candidates:
            long_term, source = max(candidates, key=lambda pair: (str(pair[0].get("as_of") or ""),
                (pair[0].get("coverage") or {}).get("complete_years") or 0))
            coverage = long_term.get("coverage") or {}
            value["long_term"] = {"status": long_term.get("status"), "label": long_term.get("label"),
                "as_of": long_term.get("as_of"), "complete_years": coverage.get("complete_years", 0),
                "consecutive_years": coverage.get("consecutive_years", 0), "target_years": 5,
                "source": source, "official_verified": False, "historical_pit_usable": False}
        else:
            value["long_term"] = {"status": "insufficient", "label": "多年资料尚未补齐；不能从单期推断长期稳定",
                "as_of": None, "complete_years": 0, "consecutive_years": 0, "target_years": 5,
                "source": "unavailable", "official_verified": False, "historical_pit_usable": False}
        return value

    def deep_library(self, query="", industry="", offset=0, limit=100):
        """List validated small saved-report summaries, with no collection or AI."""
        from .deep_research import library_summary
        if (not isinstance(query, str) or not isinstance(industry, str) or len(query) > 100 or len(industry) > 100
                or type(offset) is not int or not 0 <= offset <= 50000
                or type(limit) is not int or not 1 <= limit <= 200):
            raise ValueError("已深度研究筛选参数无效")
        with self.lock:
            rows, current_cache = [], {}
            companies = {c.get("code"): c for c in self.snapshot.get("companies", []) if isinstance(c, dict)}
            folder = self.folder / "deep-reports"
            paths = folder.glob("*.json") if folder.is_dir() and not folder.is_symlink() else ()
            for path in paths:
                if not re.fullmatch(r"\d{6}\.json", path.name) or path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                    signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                    if stat.st_size > 8_000_000:
                        continue
                    cached = self._deep_library_cache.get(path.name)
                    if cached and cached[0] == signature:
                        summary = cached[1]
                    else:
                        summary = library_summary(read(path, None), path.stem)
                except (OSError, TypeError, ValueError, KeyError, RecursionError):
                    # One damaged report cannot hide other companies.
                    continue
                current_cache[path.name] = (signature, summary)
                if summary:
                    row = dict(summary)
                    label = companies.get(row["code"], {}).get("industry")
                    row["industry"] = label if isinstance(label, str) else ""
                    rows.append(row)
            self._deep_library_cache = current_cache
        industries = sorted({r["industry"] for r in rows if r["industry"]})
        query, industry = query.strip().casefold(), industry.strip()
        rows = [r for r in rows if (not query or query in " ".join((r["code"], r["name"], r["industry"])).casefold())
                and (not industry or r["industry"] == industry)]
        rows.sort(key=lambda r: r["code"])
        rows.sort(key=lambda r: datetime.fromisoformat(r["generated_at"]), reverse=True)
        return {"companies": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit,
                "industries": industries}

    def _deep_preflight(self, code, usage=None, planned_rounds=None):
        """Cheap local hint only; cached quotes are still validated after collection."""
        from .deep_research import VERSION, PROMPT_VERSION, SUCCESS, round_specs
        planned_rounds = self.public_settings()["deep_research_rounds"] if planned_rounds is None else planned_rounds
        specs = round_specs(planned_rounds)
        usage = self.ai_status() if usage is None else usage
        has_cached = False
        folder = self.folder / "deep-cache" / "rounds" / code
        if folder.is_dir() and not folder.is_symlink():
            for path in folder.glob("*.json"):
                if not re.fullmatch(r"[a-f0-9]{64}\.json", path.name) or path.is_symlink():
                    continue
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                except OSError:
                    continue
                saved = read(path, {})
                result = saved.get("result") if isinstance(saved, dict) else None
                if (isinstance(result, dict) and saved.get("version") == VERSION
                        and saved.get("prompt_version") == PROMPT_VERSION and saved.get("company_code") == code
                        and saved.get("round_key") in {r["key"] for r in specs}
                        and saved.get("fingerprint") == path.stem and result.get("company_code") == code
                        and result.get("status") in SUCCESS and isinstance(result.get("claims"), list)):
                    has_cached = True
                    break
        blocked = bool(usage["configured"] and usage["remaining"] == 0 and not has_cached)
        state = "limit_reached" if blocked else "unconfigured" if not usage["configured"] else "cache_may_resume" if usage["remaining"] == 0 else "ready"
        messages = {
            "limit_reached": ("本程序AI每日调用上限设为0，且没有可复用轮次线索；深研尚未启动，原报告保留。次日计数重置不会改变这个上限。"
                              if usage["daily_limit"] == 0 else "本程序今日AI调用次数已用尽，且没有可复用轮次线索；深研尚未启动，原报告保留。北京时间次日0时重置。"),
            "unconfigured": "尚未配置AI，本次只整理公开资料，不会生成AI完成状态。",
            "cache_may_resume": "发现该公司的已保存轮次，可核对并复用；今天不发起新AI请求，缓存是否仍适用需核对当前资料。",
            "ready": f"可开始研究，最多请求{planned_rounds}次；已核对的缓存轮次不重复计次，剩余次数不足时保存部分结果。"}
        return {"blocked": blocked, "status": state, "remaining": usage["remaining"], "max_requests": planned_rounds,
                "has_cached_rounds": has_cached, "limit_scope": "local_daily_limit",
                "reset_at": usage["reset_at"], "message": messages[state]}

    def submit(self, kind, code=None, force=False):
        if kind not in {"scan", "analyze", "deep"}:
            raise ValueError("研究任务类型无效")
        source_company = self._company(code) if kind in {"analyze", "deep"} else None
        if type(force) is not bool:
            raise ValueError("强制更新设置无效")
        with self.lock, self.db() as db:
            existing = [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM jobs WHERE kind=? AND COALESCE(code,'')=? AND status IN ('queued','running') ORDER BY created_at,rowid",
                (kind, code or "")).fetchall()]
            if existing:
                if kind != "scan" or not force:
                    return existing[0]
                forced = next((item for item in existing if item.get("force") is True), None)
                if forced:
                    return forced
                queued = next((item for item in existing if item["status"] == "queued"), None)
                if queued:
                    queued.update(force=True, updated_at=stamp())
                    db.execute("UPDATE jobs SET updated_at=?,payload=? WHERE id=?",
                               (queued["updated_at"], encode(queued), queued["id"]))
                    self.wake.set()
                    return queued
                # An active cached scan has already frozen its request policy.
                # Queue one fresh follow-up instead of losing the user's request.
            if db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 32:
                raise ValueError("研究队列已满，请等待正在运行的任务")
            now = stamp()
            job = {"id": secrets.token_hex(12), "kind": kind, "code": code, "force": force,
                   "status": "queued", "progress": 0, "message": "等待研究线程处理",
                   "created_at": now, "updated_at": now, "error": None}
            if source_company is not None:
                job.update(input_fingerprint=self._market_fingerprint(source_company), ai_revision=self.config.get("ai_revision"))
            if kind == "deep":
                planned = self.config["deep_research_rounds"]
                job.update(phase="queued", ai_rounds_completed=0, ai_rounds_planned=planned,
                           deep_research_rounds=planned)
                preflight = self._deep_preflight(code, planned_rounds=planned)
                job["preflight"] = preflight
                if preflight["blocked"]:
                    previous = read(self.folder / "deep-reports" / (code + ".json"), None)
                    from .deep_research import VERSION
                    job.update(status="partial", phase="budget_blocked", ai_status="limit_reached", progress=0,
                               message=preflight["message"], report_preserved=isinstance(previous, dict)
                               and previous.get("company_code") == code and previous.get("version") == VERSION)
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)", (job["id"], kind, code, job["status"], now, now, encode(job)))
        self.wake.set()
        return job

    def job(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("研究任务不存在")
        return json.loads(row[0])

    def _update(self, job_id, **change):
        with self.lock, self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            job = json.loads(row[0])
            job.update(change, updated_at=stamp())
            db.execute("UPDATE jobs SET status=?,updated_at=?,payload=? WHERE id=?", (job["status"], job["updated_at"], encode(job), job_id))
        return job

    def cancel(self, job_id):
        with self.lock:
            job = self.job(job_id)
            if job["status"] in FINAL:
                return job
            if job["status"] == "queued":
                return self._update(job_id, status="cancelled", message="任务已取消")
            self.stop_events.setdefault(job_id, threading.Event()).set()
            return self._update(job_id, cancel_requested=True, message="已请求取消，等待当前网络请求结束")

    def _progress(self, job_id, *args, **kwargs):
        value = args[0] if args else kwargs
        if isinstance(value, str):
            value = {"message": value}
        if isinstance(value, (float, int)):
            value = {"progress": value, "message": str(args[1]) if len(args) > 1 else "扫描中"}
        if not isinstance(value, dict):
            return
        fields = {k: v for k, v in value.items() if k in {"progress", "message", "processed", "total", "phase"}}
        if "completed" in value:
            fields["processed"] = value["completed"]
        if value.get("stage"):
            labels = {"universe": "补充市场估值", "RPT_F10_ORG_BASICINFO": "核对存续A股名单",
                      "RPT_LICO_FN_CPD": "读取最新财务摘要", "RPT_DMSK_FN_BALANCE": "读取资产负债表",
                      "RPT_DMSK_FN_CASHFLOW": "读取现金流量表", "RPT_F10_FINANCE_GINCOME": "读取利润表"}
            label = labels.get(value["stage"], "采集公开财务资料")
            fields["message"] = label + (f"（{value['page']}/{value['pages']}页）" if value.get("pages") else "")
        if fields:
            self._update(job_id, **fields)

    @staticmethod
    def _screen_ui(company, screen, profile=None):
        from .dynamic_data import _copy_view_data
        plain_copy = [False]
        screen = _copy_view_data(screen, _plain_copy=plain_copy)
        screen["candidate"] = bool(screen.get("eligible", screen.get("candidate", False)))
        screen.setdefault("status", "assessed" if screen.get("quality_score") is not None else "insufficient")
        screen.setdefault("summary", screen.get("reason", ""))
        valuation = {"pe": company.get("pe_ttm"), "pb": company.get("pb"), "as_of": company.get("valuation_as_of"), "label": screen.get("valuation_label", "数据不足")}
        if plain_copy[0] and "valuation" not in screen:
            valuation = _copy_view_data(valuation)
        screen.setdefault("valuation", valuation)
        return apply_industry_policy_to_screen(screen, profile or ResearchService._industry_profile(company),
            _already_copied=plain_copy[0])

    @staticmethod
    def _industry_profile(company):
        bundle = {"company": company}
        for key in ("industry_adapter_version", "industry_profile_input", "industry_data_recovery"):
            if key in company:
                bundle[key] = company[key]
        return build_industry_view(bundle, as_of=company.get("as_of"))

    def _industry_content_fingerprint(self):
        """Re-read source bytes on every lookup, including unchanged mtimes.

        No decoded reports or derived permissions are reused solely by object
        identity. Unsafe/unreadable or over-budget sources disable caching.
        """
        from . import debt_recovery as recovery
        from .industry_data import SCAN_REPORTS
        try:
            root = Path(os.path.abspath(os.fspath(getattr(self.data, "cache_dir", self.folder / "cache"))))
            digest = hashlib.sha256()
            for piece in _market_json_pieces(self.snapshot):
                for offset in range(0, len(piece), 64 * 1024):
                    digest.update(piece[offset:offset + 64 * 1024].encode("utf-8"))
                del piece
            digest.update(encode([str(root), INDUSTRY_ADAPTER_VERSION, INDUSTRY_GATE_VERSION,
                                  INDUSTRY_POLICY_VERSION]).encode("utf-8"))
            seen, read_counter = set(), [0]
            for source in self.snapshot.get("sources", []):
                if not isinstance(source, dict) or recovery._report(source) not in SCAN_REPORTS:
                    continue
                raw_file = source.get("raw_file")
                # The guarded reader rejects paths before they reach the set.
                parts = tuple(recovery._relative_parts(raw_file))
                if parts in seen:
                    continue
                if len(seen) >= recovery.MAX_SOURCE_FILES:
                    return None
                seen.add(parts)
                content = recovery._read_source(root, raw_file, None,
                    recovery.MAX_TOTAL_BYTES - read_counter[0], read_counter)
                digest.update(encode([raw_file, hashlib.sha256(content).hexdigest()]).encode("utf-8"))
            return digest.hexdigest()
        except (OSError, ValueError, TypeError, RecursionError):
            return None

    def _industry_market_state(self):
        with self.lock:
            snapshot = self.snapshot
            key = self._industry_content_fingerprint()
            state = getattr(self, "_industry_derived_cache", None)
            if (key is not None and state is not None and state["snapshot"] is snapshot
                    and state["key"] == key and state["screen"] is self.screen):
                return state
            # Drop both recovered inputs and derived rows together. A missing
            # original can become available again without a scan or restart.
            self._industry_derived_cache = None
            inputs = recover_scan_industry_inputs(snapshot,
                getattr(self.data, "cache_dir", self.folder / "cache")) if snapshot.get("sources") else {}
            if key is not None and (self.snapshot is not snapshot or self._industry_content_fingerprint() != key):
                raise ValueError("Industry source state changed during validation; retry")
            state = {"snapshot": snapshot, "key": key, "screen": self.screen, "inputs": inputs}
            if key is not None:
                self._industry_derived_cache = state
            return state

    def _industry_market_inputs(self):
        return self._industry_market_state()["inputs"]

    def _industry_market_view(self):
        with self.lock:
            state = self._industry_market_state()
            if "rows" not in state:
                companies = self._industry_rows(self.snapshot.get("companies", []), _recovered=state["inputs"])
                coverage = copy.deepcopy(self.snapshot.get("coverage", {}))
                coverage.update(candidate_count=sum(bool(c.get("screen", {}).get("candidate")) for c in companies),
                                industries=sorted({c.get("industry") for c in companies if c.get("industry")}))
                coverage.update(industry_gate_version=INDUSTRY_GATE_VERSION,
                    general_ranking_allowed_count=sum(c["screen"]["industry_applicability"]["general_ranking_allowed"] for c in companies),
                    industry_unresolved_count=sum(c["industry_profile"]["classification"]["model"] in {"unknown", "financial_unresolved"} for c in companies),
                    current_supplier_classification_count=sum(c["industry_profile"].get("temporal_visibility") == "current_snapshot_only_not_historical_pit" for c in companies),
                    historical_pit_usable_count=0,
                    assessable_count=sum(c["screen"].get("quality_score") is not None for c in companies))
                coverage["missing_count"] = len(companies) - coverage["assessable_count"]
                state.update(rows=companies, coverage=coverage)
            return state

    def _industry_rows(self, companies, *, _recovered=None):
        from .dynamic_data import _copy_view_data
        rows = _copy_view_data(companies)
        recovered = self._industry_market_inputs() if _recovered is None else _recovered
        grouped = defaultdict(list)
        for peer in self.snapshot.get("companies", []):
            grouped[peer.get("industry")].append(peer)
        for company in rows:
            # Newly checked raw sources take precedence over persisted adapter
            # fields, including a failed hash/path validation after restart.
            if company.get("code") in recovered:
                company.update(_copy_view_data(recovered[company["code"]]))
            profile = self._industry_profile(company)
            company["industry_profile"] = profile
            legacy_screen = company.get("screen")
            prior_gate = legacy_screen.get("industry_applicability") if isinstance(legacy_screen, dict) else None
            if (not legacy_screen or isinstance(prior_gate, dict) and not prior_gate.get("general_ranking_allowed")
                    and profile["modules"]["general_screen"]["status"] == "conditional"):
                legacy_screen = self.screen(company, peers=grouped[company.get("industry")])
            company["screen"] = self._screen_ui(company, legacy_screen, profile)
        return rows

    def _refresh_industry_view(self, result, stored):
        report = result.get("report")
        if not isinstance(report, dict):
            return
        original = stored.get("company") if isinstance(stored.get("company"), dict) else result.get("company", {})
        cutoff = original.get("as_of") or str(stored.get("updated_at") or "")[:10] or None
        if stored:
            # Persisted applicability is not a bypass for changed/missing local
            # originals. Recheck the saved sources while leaving its AI/dates
            # and on-disk report untouched.
            cache_dir = getattr(self.data, "cache_dir", self.folder / "cache")
            profile = recover_saved_industry_view(stored, cache_dir,
                current_input=self._industry_market_inputs().get(original.get("code")))
        else:
            profile = report.get("industry_profile") or self._industry_profile(original)
        apply_industry_policy_to_report(report, profile)
        result["screen"] = apply_industry_policy_to_screen(result.get("screen"), profile)
        result["company"]["screen"] = copy.deepcopy(result["screen"])
        peers = result["company"].get("peers")
        if isinstance(peers, list):
            result["company"]["peers"] = self._industry_rows(peers)
        result["industry_profile_refresh"] = {"rules_version": INDUSTRY_GATE_VERSION, "as_of": profile.get("as_of"),
            "source_report_updated_at": stored.get("updated_at"), "from_saved_data": bool(stored), "ai_call_required": False}

    def _refresh_price_quality_view(self, result, stored):
        """Read-only current quote context; no saved AI/date/fingerprint rewrite."""
        from .price_data import prepare_price_panel, VERSION as PRICE_DATA_VERSION
        from .price_quality import build_price_quality_panel, legacy_market_reference, VERSION as PRICE_QUALITY_VERSION
        report = result.get("report")
        if not isinstance(report, dict):
            return
        company = result.get("company") if isinstance(result.get("company"), dict) else {}
        sources = result.get("sources") if isinstance(result.get("sources"), list) else []
        old_sources = stored.get("sources") if isinstance(stored, dict) else None
        cutoff = stamp()[:10]
        try:
            panel = prepare_price_panel(report, company, self.snapshot, sources,
                getattr(self.data, "cache_dir", self.folder / "cache"), self._industry_market_inputs(),
                as_of=cutoff, original_sources=old_sources)
        except (ValueError, TypeError, KeyError, OSError, ArithmeticError):
            panel = build_price_quality_panel(report, legacy_market_reference(company, sources), [],
                as_of=cutoff, research_purpose="current_research")
            panel["data_recovery"] = {"adapter_version": PRICE_DATA_VERSION, "status": "unavailable",
                "gaps": [{"code": "price_local_recovery_failed"}], "missing_originals_fetched": False}
        report["price_quality_panel"] = panel
        result["price_quality_refresh"] = {"rules_version": PRICE_QUALITY_VERSION, "adapter_version": PRICE_DATA_VERSION,
            "source_report_updated_at": stored.get("updated_at") if isinstance(stored, dict) else None,
            "evaluation_as_of": cutoff, "financial_as_of": company.get("as_of"), "ai_call_required": False,
            "mode": "current_supplier_reference_separate_from_saved_financial_date"}

    @staticmethod
    def _market_fingerprint(company):
        from .engine import FINANCIAL_FIELDS
        # Daily prices are not a reason to re-read an unchanged annual report.
        keys = [k for k in FINANCIAL_FIELDS if k not in {"pe_ttm", "pb"}]
        keys += ["report_date", "announced_at", "name", "industry"]
        return hashlib.sha256(encode({k: company.get(k) for k in keys}).encode()).hexdigest()

    def _scan(self, job, stop):
        refresh = {"requested_fresh": job.get("force", False), "measurement_available": False,
                   "network_requests": None, "cache_hits": None,
                   "source_fetched_at_min": None, "source_fetched_at_max": None,
                   "started_at": stamp(), "completed_at": None, "status": "running"}
        self._update(job["id"], source_refresh=copy.deepcopy(refresh))
        request_scope = getattr(self.data, "request_scope", None)
        scope = request_scope(fresh=refresh["requested_fresh"]) if callable(request_scope) else nullcontext(None)
        measured = None
        try:
            with scope as measured:
                status, message = self._scan_result(job, stop)
            refresh["status"] = "complete" if status == "succeeded" else status
            return status, message
        except Exception:
            refresh["status"] = "cancelled" if stop.is_set() or self.halt.is_set() else "failed"
            raise
        finally:
            if isinstance(measured, dict):
                for key in ("measurement_available", "network_requests", "cache_hits", "source_fetched_at_min", "source_fetched_at_max"):
                    if key in measured:
                        refresh[key] = measured[key]
            refresh["completed_at"] = stamp()
            self._update(job["id"], source_refresh=copy.deepcopy(refresh))

    def _scan_result(self, job, stop):
        result = self.data.scan(progress=lambda *a, **k: self._progress(job["id"], *a, **k), cancel=stop)
        if stop.is_set() or self.halt.is_set():
            return "cancelled", "扫描已取消，保留上次完整结果"
        companies = result.get("companies", [])
        if not companies or len({c["code"] for c in companies}) != len(companies):
            raise ValueError("扫描结果为空或股票代码重复，保留上次完整结果")
        if result.get("coverage", {}).get("complete") is False and self.snapshot.get("coverage", {}).get("complete") is True:
            save(self.folder / "last-partial-attempt.json", result)
            self._update(job["id"], attempted_coverage=result["coverage"])
            return "partial", "本次部分财报来源未齐，继续显示上次完整快照；本次采集证据另存"
        grouped = defaultdict(list)
        for c in companies:
            grouped[c.get("industry")].append(c)
        for c in companies:
            c["screen"] = self._screen_ui(c, self.screen(c, peers=grouped[c.get("industry")]))
            c["report_period"] = c.get("report_date")
            previous = read(self.folder / "reports" / (c["code"] + ".json"), {})
            c["ai_status"] = previous.get("ai", {}).get("status", "not_analyzed")
        coverage = result.setdefault("coverage", {})
        coverage.setdefault("universe_verified", coverage.get("universe_complete") is True)
        coverage.setdefault("as_of", coverage.get("fetched_at"))
        coverage.setdefault("report_period", coverage.get("report_date"))
        coverage.setdefault("financial_count", sum(bool(c.get("report_date")) for c in companies))
        coverage["revenue_missing_count"] = sum(c.get("revenue") is None for c in companies)
        coverage["assessable_count"] = sum(c["screen"].get("quality_score") is not None for c in companies)
        coverage["financial_missing_count"] = max(0, (coverage.get("universe_total") or len(companies)) - coverage["financial_count"])
        coverage["missing_count"] = len(companies) - coverage["assessable_count"]
        result["updated_at"] = stamp()
        if stop.is_set() or self.halt.is_set():
            return "cancelled", "扫描已取消，保留上次完整结果"
        save(self.folder / "market.json", result)
        with self.lock:
            self.snapshot = result
        self._record_dynamic_evaluations()
        if not coverage.get("universe_verified") or coverage.get("complete") is False:
            return "partial", "已保存取得的公司资料；部分来源未齐，详见覆盖统计"
        return "succeeded", "财报扫描完成，已重新核对资料；数值与排序未必变化，估值覆盖另列"

    def _reserve_ai(self, job_id):
        with self.lock, self.db() as db:
            config = copy.deepcopy(self.config)
            if not config.get("api_key") or not config.get("model"):
                return None, config, "unconfigured"
            day = datetime.now(CN).date().isoformat()
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT count(*) FROM ai_usage WHERE day=?", (day,)).fetchone()[0]
            if used >= config["ai_daily_limit"]:
                return None, config, "limit_reached"
            usage_id = secrets.token_hex(12)
            db.execute("INSERT INTO ai_usage VALUES(?,?,?,?,?)", (usage_id, day, job_id, "attempted", "{}"))
        return usage_id, config, "ready"

    def _analyze(self, job, stop):
        self._progress(job["id"], {"progress": 10, "message": "获取公司历年财务与公告证据"})
        bundle = self.data.company(job["code"], progress=lambda *a, **k: self._progress(job["id"], *a, **k), cancel=stop)
        if stop.is_set() or self.halt.is_set():
            return "cancelled", "分析已取消"
        base = self._company(job["code"])
        bundle["company"] = {**base, **bundle.get("company", {})}
        with self.lock:
            peers = [c for c in self.snapshot.get("companies", []) if c.get("industry") == base.get("industry")]
        report = self.analyzer(bundle, peers=peers)
        company = copy.deepcopy(bundle["company"])
        company["financials"] = [{**h, "period": h.get("report_date"), "operating_cash_flow": h.get("op_cashflow")} for h in bundle.get("history", [])]
        company["sources"] = bundle.get("sources", [])
        company["peers"] = sorted(peers, key=lambda c: -(c.get("screen", {}).get("quality_score") or -1))[:8]
        profile = build_industry_view(bundle, as_of=bundle.get("as_of") or company.get("as_of"))
        apply_industry_policy_to_report(report, profile)
        screen = self._screen_ui(company, self.screen(company, peers=peers), profile)
        result = {"company": company, "screen": screen, "report": report, "updated_at": stamp(),
                  "sources": bundle.get("sources", []), "ai": {"status": "unconfigured"},
                  "market_fingerprint": self._market_fingerprint(base)}
        from .ai import AI_VERSION
        signature = hashlib.sha256(encode(evidence_fingerprint({"company": bundle["company"],
                                          "history": bundle.get("history", []), "documents": bundle.get("documents", []),
                                          "model": self.config.get("model"), "provider": self.config.get("provider"), "base_url": self.config.get("base_url"),
                                          "engine_version": AI_CACHE_RULES_VERSION, "adapter_version": AI_VERSION})).encode()).hexdigest()
        previous = read(self.folder / "reports" / (job["code"] + ".json"), {})
        if not job.get("force") and previous.get("fingerprint") == signature and previous.get("ai", {}).get("status") in {"succeeded", "completed", "success", "abstained", "evidence_only"}:
            result["ai"] = previous["ai"]
            result["ai"]["cached"] = True
        else:
            self._progress(job["id"], {"progress": 65, "message": "财务指标已计算，准备AI阅读证据"})
            if stop.is_set() or self.halt.is_set():
                return "cancelled", "分析已取消"
            usage_id, config, status = self._reserve_ai(job["id"])
            if status == "ready":
                try:
                    result["ai"] = self.ai_factory(config).analyze(report, bundle)
                except Exception:
                    result["ai"] = {"status": "failed", "message": "AI接口请求失败；财务分析已保留，可检查密钥、模型或额度"}
                with self.db() as db:
                    if result["ai"].get("status") in {"unconfigured", "invalid_configuration", "insufficient_evidence"}:
                        # These adapter states are returned before any network request.
                        db.execute("DELETE FROM ai_usage WHERE id=?", (usage_id,))
                    else:
                        db.execute("UPDATE ai_usage SET status=?,usage=? WHERE id=?", (result["ai"].get("status", "unknown"), encode(result["ai"].get("usage", {})), usage_id))
            else:
                result["ai"] = {"status": status, "message": self.ai_status()["message"]}
        result["fingerprint"] = signature
        result["updated_at"] = stamp()
        if stop.is_set() or self.halt.is_set():
            return "cancelled", "分析已取消；已发出的AI请求仍计入次数"
        save(self.folder / "reports" / (job["code"] + ".json"), result)
        ai_state = result["ai"].get("status", "unknown")
        cooldown = 3 if ai_state == "insufficient_evidence" else 1 if ai_state in {"error", "failed", "invalid_output", "refused", "incomplete", "invalid_configuration"} else 0
        self._update(job["id"], ai_status=ai_state,
                     next_auto_retry_at=(datetime.now(CN) + timedelta(days=cooldown)).isoformat(timespec="seconds") if cooldown else None)
        with self.lock:
            refreshed = copy.deepcopy(self.snapshot)
            for c in refreshed.get("companies", []):
                if c["code"] == job["code"]:
                    c["ai_status"] = result["ai"].get("status", "unknown")
                    # Only the same saved financial snapshot may carry this
                    # dated policy input into lists and automatic candidate use.
                    if all(c.get(k) == bundle["company"].get(k) for k in ("report_date", "as_of")):
                        for key in ("industry_adapter_version", "industry_profile_input", "industry_data_recovery"):
                            if key in bundle:
                                c[key] = copy.deepcopy(bundle[key])
            refreshed["updated_at"] = stamp()
            save(self.folder / "market.json", refreshed)
            self.snapshot = refreshed
        if ai_state == "evidence_only":
            return "succeeded", "原文证据与待核查问题已整理；不是公司完整结论"
        ok = result["ai"].get("status") in {"succeeded", "completed", "success", "abstained"}
        return ("succeeded", "财务与AI分析已更新" if result["ai"].get("status") != "abstained" else "AI已阅读现有证据，并明确保留判断") if ok else ("partial", "财务分析已保存，AI：" + result["ai"].get("message", result["ai"].get("status", "未完成")))

    def _deep(self, job, stop):
        from .deep_data import DeepDataClient
        from .deep_research import (VERSION, PROMPT_VERSION, SUCCESS, PRE_REQUEST, FocusedAIClient,
                                    admitted_bundle, round_bundle, fingerprint, validated_round, make_report,
                                    round_specs, preserves_topic_coverage)
        code = job["code"]
        target = self.folder / "deep-reports" / (code + ".json")
        previous = self.deep_company(code)["report"]
        planned = job.get("deep_research_rounds", 3)
        specs = round_specs(planned)
        preflight = self._deep_preflight(code, planned_rounds=planned)
        self._update(job["id"], preflight=preflight)
        if preflight["blocked"]:
            self._update(job["id"], phase="budget_blocked", ai_status="limit_reached", report_preserved=bool(previous))
            return "partial", preflight["message"]
        self._update(job["id"], phase="financial_context", progress=5, message="保留现有五类财务结果与原研究日期")
        financial = self.company(code)
        financial.pop("dynamic_evaluation", None)
        if financial.get("company", {}).get("code") != code:
            raise ValueError("deep_financial_identity_mismatch")
        if stop.is_set() or self.halt.is_set():
            return "cancelled", "深度研究已取消，原报告保留"
        if self.deep_data is None:
            self.deep_data = DeepDataClient(self.folder / "deep-cache")
        self._update(job["id"], phase="documents", progress=10, message="读取限量多年度官方财报与补充公告")
        old_ttl = getattr(self.deep_data, "cache_seconds", None)
        if job.get("force") and old_ttl is not None:
            self.deep_data.cache_seconds = 0
        try:
            raw = self.deep_data.company(code, progress=lambda *a, **k: self._progress(job["id"], *a, **k), cancel=stop)
        finally:
            if old_ttl is not None:
                self.deep_data.cache_seconds = old_ttl
        bundle = admitted_bundle(raw, code, stamp()[:10])
        financial_context = None
        financial_sources = []
        if isinstance(raw.get("history"), list) and raw["history"]:
            from .deep_financial import analyze_bundle
            with self.lock:
                peers = [copy.deepcopy(c) for c in self.snapshot.get("companies", [])
                         if c.get("industry") == raw.get("company", {}).get("industry") and c.get("code") != code]
            current_financial, financial_context = analyze_bundle(raw, self.analyzer, peers=peers,
                cache_dir=getattr(self.deep_data, "cache_dir", self.folder / "deep-cache"))
            financial = {"company": copy.deepcopy(raw["company"]), "report": current_financial}
            financial_sources = copy.deepcopy(raw.get("sources") or [])
        if stop.is_set() or self.halt.is_set():
            return "cancelled", "深度研究已取消，原报告保留"
        rounds, request_failed = [], False
        for position, spec in enumerate(specs):
            if stop.is_set() or self.halt.is_set():
                self._update(job["id"], report_preserved=bool(previous))
                return "cancelled", "深度研究已取消；已发出的请求计次，成功轮次可在下次复用"
            rb = round_bundle(bundle, spec)
            with self.lock:
                config = copy.deepcopy(self.config)
            signature, coverage = fingerprint(rb, spec, config)
            cache_dir = self.folder / "deep-cache" / "rounds" / code

            def cached(sig):
                saved = read(cache_dir / (sig + ".json"), {})
                if (isinstance(saved, dict) and saved.get("version") == VERSION and saved.get("prompt_version") == PROMPT_VERSION
                        and saved.get("company_code") == code and saved.get("round_key") == spec["key"] and saved.get("fingerprint") == sig):
                    result = validated_round(saved.get("result"), rb, spec)
                    if result["status"] in SUCCESS:
                        return result
                return None

            result = cached(signature)
            was_cached = result is not None
            self._update(job["id"], phase=spec["key"], progress=42 + int(position * 51 / planned),
                         message=f"主题 {position + 1}/{planned}：{spec['title']}" + ("（复用已核对结果）" if was_cached else ""))
            if result is None:
                if request_failed:
                    result = {"status": "not_requested", "claims": [], "message": "前一轮失败，后续轮次未自动继续请求。"}
                elif not coverage["selected_pages"]:
                    result = {"status": "insufficient_evidence", "claims": [], "message": "缺少本主题可核对正文，未请求AI。"}
                else:
                    usage_id, config, state = self._reserve_ai(job["id"])
                    if stop.is_set() or self.halt.is_set():
                        if usage_id:
                            with self.db() as db:
                                db.execute("DELETE FROM ai_usage WHERE id=?", (usage_id,))
                        self._update(job["id"], report_preserved=bool(previous))
                        return "cancelled", "深度研究已取消，未发出的请求不计次"
                    actual_signature, coverage = fingerprint(rb, spec, config)
                    if actual_signature != signature:
                        signature = actual_signature
                        result = cached(signature)
                        was_cached = result is not None
                    if result is not None:
                        if usage_id:
                            with self.db() as db:
                                db.execute("DELETE FROM ai_usage WHERE id=?", (usage_id,))
                    elif state != "ready":
                        result = {"status": state, "claims": [], "message": self.ai_status()["message"]}
                    else:
                        try:
                            client = (self.deep_ai_factory or FocusedAIClient)(config, spec["key"])
                            raw_result = client.analyze(financial.get("report") or {}, rb)
                            result = validated_round(raw_result, rb, spec)
                        except Exception:
                            result = {"status": "failed", "claims": [], "message": "本轮AI请求或校验失败，未重试。"}
                        with self.db() as db:
                            if result["status"] in PRE_REQUEST:
                                db.execute("DELETE FROM ai_usage WHERE id=?", (usage_id,))
                            else:
                                db.execute("UPDATE ai_usage SET status=?,usage=? WHERE id=?",
                                           (result["status"], encode(result.get("usage", {})), usage_id))
                        if result["status"] in SUCCESS:
                            # Commit paid successful work before cancellation or
                            # report publication so a later click can reuse it.
                            save(cache_dir / (signature + ".json"), {"version": VERSION, "prompt_version": PROMPT_VERSION,
                                 "company_code": code, "round_key": spec["key"], "fingerprint": signature, "result": result})
                        elif result["status"] not in PRE_REQUEST:
                            request_failed = True
            rounds.append({**result, "key": spec["key"], "cached": was_cached, "fingerprint": signature,
                           "evidence_coverage": result.get("evidence_coverage", coverage)})
            self._update(job["id"], ai_rounds_completed=sum(r["status"] in SUCCESS for r in rounds),
                         ai_status=result["status"], documents=len(bundle["documents"]))
            if result.get("error_code"):
                self._update(job["id"], error_code=result["error_code"], http_status=result.get("http_status"),
                             ai_error_message=result["message"])
        if stop.is_set() or self.halt.is_set():
            self._update(job["id"], report_preserved=bool(previous))
            return "cancelled", "深度研究已取消；原报告保留，已发出的请求仍计次"
        if request_failed and previous:
            self._update(job["id"], report_preserved=True, phase="failed")
            return "failed", "本次深研有请求失败，保留上份报告；已成功的新轮次可下次复用"
        report = make_report(bundle, rounds, financial.get("report") or {}, stamp(), planned_rounds=planned)
        if financial_context is not None:
            report["financial_context"] = financial_context
            report["financial_sources"] = financial_sources
        with self.lock:
            if stop.is_set() or self.halt.is_set():
                return "cancelled", "深度研究已取消，原报告保留"
            if previous and (not preserves_topic_coverage(previous, report)
                             or previous.get("status") == "completed" and report["status"] != "completed"):
                save(self.folder / "deep-reports" / "attempts" / (job["id"] + ".json"), report)
                self._update(job["id"], report_preserved=True, partial_report_saved=True, phase="saved_partial_attempt")
                return "partial", "本次资料或额度不足，部分资料另存；继续展示证据更完整的上份深研报告"
            save(target, report)
        self._update(job["id"], phase="saved", report_preserved=False,
                     report_generated_at=report["generated_at"], ai_status=report["status"])
        if report["status"] == "completed":
            return "succeeded", f"{planned}轮深研原文已整理；仍需阅读资料范围、反证与缺口"
        return "partial", "已保存部分深研资料；部分主题未完成或保留判断，不是完整AI研究"

    def run_once(self):
        with self.lock, self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
            if not row:
                return False
            job = json.loads(row[0])
            stop = self.stop_events.setdefault(job["id"], threading.Event())
            self._update(job["id"], status="running", message="研究任务已开始")
        try:
            handler = {"scan": self._scan, "analyze": self._analyze, "deep": self._deep}[job["kind"]]
            status, message = handler(job, stop)
            self._update(job["id"], status=status, message=message, progress=100 if status in {"succeeded", "partial"} else 0)
        except Exception as exc:
            # Do not persist URLs with credentials, model responses or exception bodies.
            status = "cancelled" if stop.is_set() or self.halt.is_set() else "failed"
            self._update(job["id"], status=status, error=type(exc).__name__,
                         message="研究已取消" if status == "cancelled" else "数据获取或分析失败，保留此前结果；可稍后重试",
                         next_auto_retry_at=(datetime.now(CN) + timedelta(hours=6)).isoformat(timespec="seconds") if status == "failed" else None)
        finally:
            with self.lock:
                self.stop_events.pop(job["id"], None)
        return True

    def schedule_once(self):
        if not self.config.get("auto_scan"):
            return
        day = datetime.now(CN).date().isoformat()
        with self.db() as db:
            row = db.execute("SELECT created_at FROM jobs WHERE kind='scan' ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
        if not row or row[0][:10] < day:
            self.submit("scan")
            return
        if not self.config.get("auto_ai") or self.ai_status()["status"] != "ready":
            return
        with self.db() as db:
            pending = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            attempted = {r[0] for r in db.execute("SELECT code FROM jobs WHERE kind='analyze' AND created_at>=?", (day,))}
            latest = {r["code"]: json.loads(r["payload"]) for r in db.execute(
                "SELECT code,payload FROM jobs WHERE rowid IN (SELECT max(rowid) FROM jobs "
                "WHERE kind='analyze' AND status NOT IN ('cancelled','interrupted') GROUP BY code)")}
        if pending:
            return
        if len(attempted) >= min(50, self.config["ai_daily_limit"] * 2):
            return
        with self.lock:
            pool = [c for c in self._industry_rows(self.snapshot.get("companies", [])) if c.get("screen", {}).get("candidate")]
            pool.sort(key=lambda c: (c.get("ai_status") in {"succeeded", "completed", "success", "abstained", "evidence_only"},
                                     latest.get(c["code"], {}).get("created_at", ""),
                                     -(c.get("screen", {}).get("quality_score") or -1), c["code"]))
        for c in pool:
            if c["code"] in attempted:
                continue
            last = latest.get(c["code"], {})
            if last.get("next_auto_retry_at") and last.get("input_fingerprint") == self._market_fingerprint(c) and last.get("ai_revision") == self.config.get("ai_revision"):
                try:
                    if datetime.fromisoformat(last["next_auto_retry_at"]) > datetime.now(CN):
                        continue
                except (ValueError, TypeError):
                    pass
            old = read(self.folder / "reports" / (c["code"] + ".json"), {})
            if old.get("ai", {}).get("status") in {"succeeded", "completed", "success", "abstained", "evidence_only"} and old.get("market_fingerprint") == self._market_fingerprint(c):
                try:
                    last = datetime.fromisoformat(old["updated_at"])
                    if datetime.now(CN) - last < timedelta(days=7):
                        continue
                except (ValueError, KeyError, TypeError):
                    pass
            self.submit("analyze", c["code"])
            break

    def _loop(self):
        while not self.halt.is_set():
            try:
                self.schedule_once()
                if self.run_once():
                    continue
            except Exception:
                pass  # Keep trading independent if this module has storage/network trouble.
            self.wake.wait(30)
            self.wake.clear()

    def close(self):
        self.halt.set()
        self.wake.set()
        with self.lock:
            for event in self.stop_events.values():
                event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=10)
