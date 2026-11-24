"""Independent scenario API: saved public material + explicit user assumptions.

No supplier requests, AI calls, report rewrites or ranking changes.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import math
import re

from .industry_data import build_industry_view
from .debt_recovery import read_cached_company_bundle, _read_source, MAX_FILE_BYTES
from .deep_research import admitted_bundle
from .valuation_scenarios import evaluate
from .valuation_store import ValuationStore


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def number(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) and value > 0 else None
    except OverflowError:
        return None


def _ordinary_subject(doc, saved, cached, cache_dir, code):
    """Recover legacy PDF subject only from a saved, hash-checked announcement row.

    Older ordinary reports lack a frozen PDF hash and PDFs lack company_code.
    The saved CNINFO source hash can still bind the announcement id, security,
    URL and publication date. This does not verify the cached PDF text/hash.
    """
    if doc.get("company_code") not in (None, code):
        return False
    sid = doc.get("source_id")
    sources = saved.get("sources")
    cached_sources = cached.get("sources")
    a = [s for s in sources if isinstance(s, dict) and s.get("id") == sid] if isinstance(sources, list) else []
    b = [s for s in cached_sources if isinstance(s, dict) and s.get("id") == sid] if isinstance(cached_sources, list) else []
    if len(a) != 1 or len(b) != 1:
        return False
    old, current = a[0], b[0]
    if (old.get("url") != "https://www.cninfo.com.cn/new/hisAnnouncement/query"
            or not re.fullmatch(r"[a-f0-9]{64}", str(old.get("sha256") or ""))
            or any(old.get(k) != current.get(k) for k in ("url", "sha256", "parameters"))):
        return False
    try:
        raw = json.loads(_read_source(cache_dir, current.get("raw_file"), old["sha256"], MAX_FILE_BYTES, [0]).decode("utf-8-sig"))
        rows = raw.get("announcements") if isinstance(raw, dict) else None
        matches = [r for r in rows if isinstance(r, dict) and str(r.get("announcementId")) == doc.get("id")] if isinstance(rows, list) else []
        if len(matches) != 1:
            return False
        row = matches[0]
        stamp = row.get("announcementTime")
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            return False
        published = datetime.fromtimestamp(stamp / 1000, timezone(timedelta(hours=8))).date().isoformat()
        return (row.get("secCode") == code and published == doc.get("published_at")
                and "https://static.cninfo.com.cn/" + str(row.get("adjunctUrl")) == doc.get("url"))
    except (OSError, ValueError, TypeError, OverflowError):
        return False


class ValuationService:
    def __init__(self, research):
        self.research = research
        self.store = ValuationStore(research.folder / "valuation-scenarios.sqlite3")

    def _context(self, code):
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("股票代码须为6位数字")
        research = self.research
        company = research._company(code)
        recovered = deepcopy(research._industry_market_inputs().get(code, {}))
        if not recovered:
            recovered = {k: deepcopy(company[k]) for k in
                         ("industry_adapter_version", "industry_profile_input", "industry_data_recovery") if k in company}
        profile = build_industry_view({"company": company, **recovered}, as_of=company.get("as_of"))
        reasons = []
        if profile["classification"]["model"] != "general":
            reasons.append("当前行业为“" + profile["classification"]["label"] + "”；本模型仅开放普通非金融企业，专项行业需另建估值模型。")
        if profile["earnings_status"] != "positive":
            reasons.append("当前可追溯的合并净利润与归母净利润未同时确认正值，暂不开放盈利倍数估值。")
        try:
            valid_snapshot_date = (isinstance(company.get("as_of"), str)
                and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", company["as_of"])
                and date.fromisoformat(company["as_of"]) <= date.fromisoformat(today()))
        except ValueError:
            valid_snapshot_date = False
        if not valid_snapshot_date:
            reasons.append("财务快照日期缺失或晚于今天，需先核对资料。")
        screen = company.get("screen") if isinstance(company.get("screen"), dict) else {}
        flags = [deepcopy(f) for name in ("flags", "risks") for f in (screen.get(name) or [])
                 if isinstance(f, dict)]
        if screen.get("risk_level") in ("high", "高", "高风险") or any(
                f.get("level", f.get("severity")) in ("high", "高", "高风险") for f in flags):
            reasons.append("已有明确的高风险财务或治理事项，须先核查，暂不开放盈利倍数估值。")
        documents, seen, ambiguous = [], {}, set()
        for folder, report_path in (("cache", "reports"), ("deep-cache", "deep-reports")):
            saved = read(research.folder / report_path / (code + ".json"))
            if report_path == "reports":
                if saved.get("company", {}).get("code") != code:
                    continue
                manifest = (saved.get("report") or {}).get("evidence") or []
            else:
                if saved.get("company_code") != code:
                    continue
                manifest = saved.get("sources") or []
            identities, duplicates = {}, set()
            for entry in manifest if isinstance(manifest, list) else []:
                if not isinstance(entry, dict):
                    continue
                identity = str(entry.get("id"))
                if identity in identities:
                    duplicates.add(identity)
                identities[identity] = entry
            for identity in duplicates:
                identities.pop(identity, None)
            cached, _ = read_cached_company_bundle(research.folder / folder, code)
            if not cached:
                continue
            legacy_subjects = set()
            for candidate in cached.get("documents", []) if isinstance(cached.get("documents"), list) else []:
                if not isinstance(candidate, dict):
                    continue
                original = identities.get(str(candidate.get("id")))
                if (folder == "cache" and original and (not original.get("sha256") or not candidate.get("company_code"))
                        and _ordinary_subject(candidate, saved, cached, research.folder / folder, code)):
                    candidate["company_code"] = code
                    legacy_subjects.add(candidate["id"])
            for doc in admitted_bundle(cached, code, today())["documents"]:
                original = identities.get(doc["id"])
                if not original or not doc["pages"] or any(original.get(k) != doc.get(k) for k in ("url", "published_at")):
                    continue
                frozen_hash = original.get("sha256")
                if (frozen_hash and frozen_hash != doc["sha256"]) or (not frozen_hash and doc["id"] not in legacy_subjects):
                    continue
                identity = (doc["url"], doc["published_at"], doc["sha256"])
                if doc["id"] in seen:
                    if seen[doc["id"]] != identity:
                        ambiguous.add(doc["id"])
                    continue
                seen[doc["id"]] = identity
                documents.append({**{k: deepcopy(doc[k]) for k in ("id", "title", "url", "published_at", "sha256", "pages")},
                    "hash_basis": "saved_manifest_and_current_cache_match" if frozen_hash else "current_cache_only_not_previously_frozen",
                    "subject_basis": "hash_checked_announcement_row" if doc["id"] in legacy_subjects else "explicit_document_company_code"})
        documents = [d for d in documents if d["id"] not in ambiguous]
        # Do not infer total shares from market cap/price or confuse free float
        # with total issued shares. The user supplies a dated share-count basis.
        context = {"as_of": today(), "data_as_of": company.get("as_of"),
                   "reference_price": number(company.get("price")),
                   "reference_date": company.get("valuation_as_of"),
                   "reference_basis": company.get("quote_source_id") or "",
                   "share_count_yi": None, "share_count_basis": "", "report_date": company.get("report_date"),
                   "industry_profile": profile, "evidence_sources": documents,
                   "risks": flags,
                   "limitations": ["盈利倍数与股息情景计算，仅依赖显式假设；不能代替完整企业估值。",
                                   "当前快照不支持历史回测；预测年度为估值日起未来三个连续12个月。",
                                   "引用匹配只确认已存原文，不证明假设正确或风险已排除。"]}
        return {"company": {"code": code, "name": company.get("name")},
                "eligibility": {"allowed": not reasons, "reasons": reasons}, "context": context}

    def get(self, code):
        current = self._context(code)
        history = self.store.history(code)
        return {**current, "latest": history[0] if history else None, "history": history}

    def _preview(self, code, payload):
        current = self._context(code)
        if not current["eligibility"]["allowed"]:
            raise ValueError("；".join(current["eligibility"]["reasons"]))
        result = evaluate(payload, company_code=code, as_of_today=today())
        payload = result["inputs"]
        if payload["as_of"] != today():
            raise ValueError("本轮仅使用当前快照，新增估值的截止日必须为今天；历史留档可阅读但不能用当前资料回填。")
        context = current["context"]
        if payload["as_of"] < context["data_as_of"]:
            raise ValueError("估值日早于当前财务快照，不能将现在的资料用于历史估值。")
        verified = []
        for ref in payload["evidence_refs"]:
            doc = next((d for d in context["evidence_sources"] if d["id"] == ref["source_id"]), None)
            page = next((p for p in doc["pages"] if p["page"] == ref["page"]), None) if doc else None
            compact = lambda s: re.sub(r"\s+", "", s)
            if (not page or doc["published_at"] > payload["as_of"] or compact(ref["quote"]) not in compact(page["text"])):
                raise ValueError("依据中的来源、页码或摘录无法在该公司已保存且当时已公开的原文中匹配。")
            verified.append({**deepcopy(ref), **{k: doc[k] for k in ("title", "url", "published_at", "sha256", "hash_basis", "subject_basis")}})
        # Freeze only cited excerpts, not full book-sized documents on every save.
        frozen = {k: deepcopy(v) for k, v in context.items() if k != "evidence_sources"}
        frozen["evidence_refs"] = verified
        frozen["company"] = current["company"]
        return result, frozen

    def preview(self, code, payload):
        return self._preview(code, payload)[0]

    def save(self, code, body):
        if not isinstance(body, dict) or set(body) != {"payload", "revision_note", "expected_latest_id"}:
            raise ValueError("保存请求须包含假设、修订说明及最新留档编号。")
        note = body["revision_note"]
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise ValueError("请填写本次建立或修订预测的原因（最多2000字）。")
        expected = body["expected_latest_id"]
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{32}", expected)):
            raise ValueError("最新留档编号无效，请重新读取。")
        result, context = self._preview(code, body["payload"])
        record = self.store.save(code, result["inputs"], result, context, note.strip(), expected)
        return {"record": record, "latest": record, "history": self.store.history(code)}
