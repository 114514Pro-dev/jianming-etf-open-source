"""Deep-research financial views from collected data or verified local originals.

The legacy supplement is deliberately separate from the saved AI report. Its
old report did not freeze a financial manifest; matching cached materials never
proves that the old AI used these numbers or that they form a PIT data vintage.
"""
from copy import deepcopy
from datetime import date, datetime
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import debt_recovery as recovery
from .data import normalize, _merge
from .debt_data import ADAPTER_VERSION, normalize_debt_record
from .deep_research import admitted_bundle

VERSION = "deep-financial-1.0"


def _instant(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def analyze_bundle(bundle, analyzer, *, peers=None, cache_dir=None):
    """Reuse the existing deterministic engines without ordinary reports or AI."""
    work = deepcopy(bundle)
    code = work.get("company", {}).get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("deep_financial_company_missing")
    cutoff = date.fromisoformat(str(work["company"].get("as_of") or work.get("as_of"))).isoformat()
    history = work.get("history")
    if not isinstance(history, list) or any(not isinstance(row, dict) or row.get("code") != code for row in history):
        raise ValueError("deep_financial_history_identity_invalid")
    work["as_of"] = cutoff
    work["documents"] = admitted_bundle(work, code, cutoff)["documents"]
    report = analyzer(work, peers=peers or [])
    if not isinstance(report, dict):
        raise ValueError("deep_financial_report_invalid")
    # Same dated input, independent from a later market scan or current quote.
    if cache_dir is not None and report.get("company"):
        from .price_data import prepare_price_panel
        from .price_quality import build_price_quality_panel, legacy_market_reference
        sources = work.get("sources") or []
        try:
            report["price_quality_panel"] = prepare_price_panel(report, work["company"],
                {"companies": [work["company"]], "sources": sources}, sources, cache_dir, {},
                as_of=cutoff, original_sources=sources)
        except (ValueError, TypeError, KeyError, OSError, ArithmeticError):
            report["price_quality_panel"] = build_price_quality_panel(report,
                legacy_market_reference(work["company"], sources), [], as_of=cutoff,
                research_purpose="current_research")
    return report, {"version": VERSION, "mode": "deep_collected_financial_data",
        "source_fetched_at": work.get("fetched_at"), "financial_as_of": cutoff,
        "history_rows": len(history), "ai_call_required": False, "ordinary_report_unchanged": True,
        "note": "财务规则根据本次深研取得的财务数据独立计算；普通报告与旧AI不变，供应商数值尚未逐项与官方核验。"}


def recover_bundle(report, cache_dir):
    """Read only source-hashed local financials bound to legacy deep materials."""
    provenance = {"version": VERSION, "mode": "verified_deep_cache_supplement",
        "ai_call_required": False, "ordinary_report_unchanged": True,
        "raw_hashes_rechecked": False, "verified_sources": [],
        "note": "根据与原深研文档匹配的本地缓存补算；旧报告未冻结财务清单，不能证明旧AI使用过这些数值，不是严格历史时点数据。"}
    gaps = []
    try:
        code = report.get("company_code")
        generated = _instant(report.get("generated_at"))
        if generated is None:
            raise recovery.RecoveryError("deep_generated_time_missing")
        cached, issues = recovery.read_cached_company_bundle(cache_dir, code)
        if cached is None:
            return None, provenance, issues
        fetched = _instant(cached.get("fetched_at"))
        if fetched is None or fetched > generated:
            raise recovery.RecoveryError("deep_cache_newer_than_report_or_undated")
        cutoff = date.fromisoformat(str(cached["company"].get("as_of")))
        if cutoff > fetched.date() or cutoff > generated.date():
            raise recovery.RecoveryError("deep_cache_financial_cutoff_after_report")
        provenance.update(source_report_generated_at=report["generated_at"],
            source_fetched_at=cached["fetched_at"], financial_as_of=cutoff.isoformat())
        documents = cached.get("documents")
        saved = report.get("sources")
        if not isinstance(documents, list) or not isinstance(saved, list) or not saved:
            raise recovery.RecoveryError("deep_document_manifest_missing")
        admitted = admitted_bundle(cached, code, cutoff.isoformat())["documents"]
        indexed = {doc["id"]: doc for doc in admitted}
        if len(indexed) != len(admitted) or len(saved) != len(indexed):
            raise recovery.RecoveryError("deep_cached_document_set_mismatch")
        for doc in saved:
            other = indexed.get(doc.get("id")) if isinstance(doc, dict) else None
            if (not other or any(doc.get(key) != other.get(key) for key in
                    ("id", "company_code", "url", "published_at", "sha256"))
                    or not re.fullmatch(r"[a-f0-9]{64}", str(doc.get("sha256") or ""))):
                raise recovery.RecoveryError("deep_cached_document_identity_mismatch")
            if doc.get("pages") != [p["page"] for p in other.get("pages", [])]:
                raise recovery.RecoveryError("deep_cached_document_pages_mismatch")
        manifest = cached.get("sources")
        if not isinstance(manifest, list):
            raise recovery.RecoveryError("deep_financial_source_manifest_missing")
        root = Path(os.path.abspath(os.fspath(cache_dir)))
        candidates = [s for s in manifest if isinstance(s, dict) and recovery._report(s) in recovery.SUPPORTED_REPORTS]
        if not candidates or len(candidates) > recovery.MAX_SOURCE_FILES:
            raise recovery.RecoveryError("deep_financial_source_count_invalid")
        if len({s.get("id") for s in candidates}) != len(candidates):
            raise recovery.RecoveryError("deep_financial_source_identity_conflict")
        history, debt, count, verified = {}, [], [0], []
        # Rebuild in DataClient's statement order, preserving revision handling.
        order = lambda s: (0 if recovery._report(s).endswith("MAINFINADATA") else
            1 if recovery._report(s).endswith("GINCOME") else 2 if recovery._report(s).endswith("BALANCE") else 3)
        for source in sorted(candidates, key=order):
            observed, digest = _instant(source.get("fetched_at")), source.get("sha256")
            endpoint = urlsplit(source.get("url") or "")
            if (not recovery._source_id(source.get("id")) or observed is None or observed > fetched
                    or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or endpoint.scheme != "https" or endpoint.netloc != "datacenter-web.eastmoney.com"
                    or endpoint.path != "/api/data/v1/get"):
                raise recovery.RecoveryError("deep_financial_source_metadata_invalid")
            content = recovery._read_source(root, source.get("raw_file"), digest,
                recovery.MAX_TOTAL_BYTES - count[0], count)
            rows = recovery._decode_rows(content, code)
            if len(debt) + len(rows) > recovery.MAX_RECORDS:
                raise recovery.RecoveryError("deep_financial_row_limit")
            rows.sort(key=lambda row: (row.get("NOTICE_DATE") or "", row.get("UPDATE_DATE") or ""))
            for row in rows:
                debt.append(normalize_debt_record(row, source["id"], recovery._report(source), source))
                if row.get("CURRENCY") not in (None, "CNY"):
                    continue
                normalized = normalize(row, source["id"])
                period = normalized.get("report_date")
                if not period:
                    continue
                if period not in history:
                    history[period] = normalized
                else:
                    _merge(history[period], normalized)
            verified.append(deepcopy(source))
        ordered = sorted(history.values(), key=lambda row: row["report_date"], reverse=True)
        if not ordered:
            raise recovery.RecoveryError("deep_financial_history_unavailable")
        for row in ordered:
            row["source_ids"] = sorted({s["source_id"] for s in row.get("source_records", []) if s.get("source_id")})
        # Retain only descriptive metadata; every financial scalar and its
        # provenance is rebuilt above rather than trusted from normalized JSON.
        company = {key: deepcopy(cached["company"].get(key)) for key in
            ("code", "name", "exchange", "industry", "listing_state", "listing_unverified")}
        company.update(ordered[0])
        company["as_of"] = cutoff.isoformat()
        company["name"] = cached["company"].get("name") or company["name"]
        company["industry"] = cached["company"].get("industry") or company.get("industry")
        bundle = {"company": company, "history": ordered, "documents": admitted,
            "sources": verified, "as_of": cutoff.isoformat(), "fetched_at": cached["fetched_at"],
            "debt_financial_records": debt, "debt_adapter_version": ADAPTER_VERSION,
            "warnings": [provenance["note"], "补算仅恢复已核验的财务原始缓存；未沿用未核验的旧报价、归一化数字或评分。"]}
        from .business_data import prepare_business_bundle
        from .industry_data import prepare_industry_bundle
        bundle.update(prepare_business_bundle(bundle, root, as_of=cutoff.isoformat()))
        bundle.update(prepare_industry_bundle(bundle, root, as_of=cutoff.isoformat()))
        provenance.update(raw_hashes_rechecked=True, history_rows=len(ordered),
            verified_sources=[{"source_id": s["id"], "sha256": s["sha256"],
                "report_type": recovery._report(s)} for s in verified])
        return bundle, provenance, gaps
    except recovery.RecoveryError as exc:
        gaps.append({"code": str(exc)})
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        gaps.append({"code": "deep_financial_cache_unavailable_or_invalid"})
    return None, provenance, gaps


def financial_supplement(report, cache_dir, analyzer):
    """Build a separate read-only view; never mutate the published report."""
    result = {"status": "unavailable", "report": None, "read_only": True,
        "ai_call_required": False, "source_report_generated_at": report.get("generated_at"),
        "source_fetched_at": None, "financial_as_of": None, "provenance": {}, "gaps": [], "sources": []}
    bundle, provenance, gaps = recover_bundle(report, cache_dir)
    result.update(provenance=provenance, gaps=gaps, source_fetched_at=provenance.get("source_fetched_at"),
        financial_as_of=provenance.get("financial_as_of"))
    if bundle is not None:
        try:
            result["report"], _ = analyze_bundle(bundle, analyzer, cache_dir=cache_dir)
            result["status"] = "available"
            result["sources"] = deepcopy(bundle.get("sources") or [])
        except (ValueError, TypeError, KeyError, OSError, ArithmeticError, RecursionError):
            result["gaps"].append({"code": "deep_financial_supplement_analysis_failed"})
    return result
