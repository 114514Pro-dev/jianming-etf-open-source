"""Bounded, read-only adapters for business observations and issuer text.

Filesystem primitives and strict JSON/subject validation are reused from the
phase-2 recovery boundary. This adapter never downloads, writes or calls AI.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import re

from . import debt_recovery as recovery
from .business_capital import BUSINESS_CAPITAL_VERSION, analyze_business_capital

BUSINESS_ADAPTER_VERSION = "business-data-1.0"
BUSINESS_RECOVERY_VERSION = "business-cache-recovery-1.0"


def _date(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value).isoformat()
        return parsed if parsed == value else None
    except ValueError:
        return None


def _gap(code, source=None):
    source = source if isinstance(source, dict) else {}
    return {"code": code, "source_id": source.get("id"),
            "report_type": recovery._report(source)}


def recover_business_statements(bundle, cache_dir):
    """Recover original F10 statements, checking every referenced raw hash.

    Versioned in-bundle statement copies are not a bypass for raw validation.
    Source gaps contain IDs/reasons only, never local filesystem paths.
    """
    output = {"version": BUSINESS_RECOVERY_VERSION, "adapter_version": BUSINESS_ADAPTER_VERSION,
              "mode": "verified_local_raw", "status": "unavailable", "statements": [], "sources": [], "gaps": [],
              "coverage": {"candidate_sources": 0, "verified_sources": 0, "raw_rows": 0,
                           "read_bytes": 0, "raw_hashes_rechecked": False}}
    company = bundle.get("company") if isinstance(bundle, dict) else None
    code = company.get("code") if isinstance(company, dict) else None
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        output["gaps"].append(_gap("company_code_invalid")); return output
    manifest = bundle.get("sources")
    if not isinstance(manifest, list):
        output["gaps"].append(_gap("source_manifest_missing")); return output
    candidates, fingerprints, invalid_fingerprints = [], {}, set()
    for source in manifest:
        if not isinstance(source, dict):
            output["gaps"].append(_gap("source_manifest_entry_invalid")); continue
        sid, report = source.get("id"), recovery._report(source)
        if recovery._source_id(sid):
            try:
                fingerprint = json.dumps({key: source.get(key) for key in
                    ("parameters", "report_type", "raw_file", "sha256", "url", "source_url")},
                    sort_keys=True, ensure_ascii=True, allow_nan=False)
                fingerprints.setdefault(sid, set()).add(fingerprint)
            except (TypeError, ValueError, RecursionError):
                invalid_fingerprints.add(sid)
        if isinstance(report, str) and report in recovery.SUPPORTED_REPORTS:
            candidates.append(source)
        elif isinstance(report, str) and report.startswith("RPT_F10_FINANCE_"):
            output["gaps"].append(_gap("source_report_type_unsupported", source))
    output["coverage"]["candidate_sources"] = len(candidates)
    if not candidates:
        output["gaps"].append(_gap("no_supported_statement_sources")); return output
    try:
        root = Path(os.path.abspath(os.fspath(cache_dir)))
        recovery._check_chain(root)
        if not root.is_dir():
            raise recovery.RecoveryError("cache_root_not_directory")
    except recovery.RecoveryError as exc:
        output["gaps"].append(_gap(str(exc))); return output
    except (OSError, ValueError, TypeError):
        output["gaps"].append(_gap("cache_root_unavailable")); return output
    processed, read_counter = set(), [0]
    for index, source in enumerate(candidates):
        sid = source.get("id")
        issue = None
        if index >= recovery.MAX_SOURCE_FILES:
            issue = "source_count_limit"
        elif not recovery._source_id(sid):
            issue = "source_id_missing_or_invalid"
        elif sid in processed:
            continue
        elif sid in invalid_fingerprints:
            issue = "source_metadata_not_json"
        elif len(fingerprints[sid]) != 1:
            issue = "source_identity_conflict"
        elif not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[a-fA-F0-9]{64}", source["sha256"]):
            issue = "source_sha256_missing_or_invalid"
        if recovery._source_id(sid):
            processed.add(sid)
        if issue:
            output["gaps"].append(_gap(issue, source)); continue
        summary = {"source_id": sid, "report_type": recovery._report(source), "sha256": source["sha256"],
                   "status": "rejected", "rows": 0}
        output["sources"].append(summary)
        try:
            content = recovery._read_source(root, source.get("raw_file"), source["sha256"],
                                           recovery.MAX_TOTAL_BYTES - read_counter[0], read_counter)
            rows = recovery._decode_rows(content, code)
            if any(row.get(key) is not None and not isinstance(row[key], str)
                   for row in rows for key in ("CURRENCY", "SCOPE", "STATEMENT_SCOPE", "UNIT", "AMOUNT_UNIT",
                                               "FLOW_BASIS", "flow_basis", "REPORT_TYPE", "PERIOD_START", "EPS_UNIT")):
                raise recovery.RecoveryError("raw_statement_metadata_invalid")
            if output["coverage"]["raw_rows"] + len(rows) > recovery.MAX_RECORDS:
                raise recovery.RecoveryError("total_record_limit")
        except recovery.RecoveryError as exc:
            issue = str(exc)
        except FileNotFoundError:
            issue = "raw_file_missing"
        except (OSError, ValueError, TypeError, RecursionError):
            issue = "raw_read_or_decode_failed"
        if issue:
            summary["reason"] = issue
            output["gaps"].append(_gap(issue, source)); continue
        output["statements"].append({"report_type": recovery._report(source),
                                     "source": deepcopy(source), "rows": rows})
        summary.update(status="verified", rows=len(rows))
        output["coverage"]["verified_sources"] += 1
        output["coverage"]["raw_rows"] += len(rows)
    output["coverage"].update(read_bytes=read_counter[0], raw_hashes_rechecked=bool(output["statements"]))
    if output["statements"]:
        output["status"] = "partial" if output["gaps"] else "recovered"
    return output


TOPICS = {
    "competitive_position_candidate": ("核心竞争力", "竞争优势", "销售模式", "前五名客户", "前五大客户", "前五名供应商", "前五大供应商"),
    "capital_use_candidate": ("研发投入", "研发费用", "募集资金", "利润分配", "股份回购", "企业合并", "资本公积转增"),
}


def locate_issuer_material(company, documents, sources, *, as_of):
    """Locate exact cached page slices, without interpreting their assertions.

    A match is a navigation aid, never proof that a claim/event is true. All
    material remains issuer context; no independent support or event is inferred.
    """
    company = company if isinstance(company, dict) else {}
    cutoff, code = _date(as_of), company.get("code")
    output = {"evidence": [], "gaps": [], "documents_bound": 0}
    if not cutoff:
        output["gaps"].append({"code": "financial_cutoff_missing"}); return output
    source_ids = {s["id"] for s in sources if isinstance(s, dict) and recovery._source_id(s.get("id"))} if isinstance(sources, list) else set()
    identities = {}
    for doc in documents if isinstance(documents, list) else []:
        if isinstance(doc, dict) and isinstance(doc.get("id"), str):
            identities.setdefault(doc["id"], []).append(doc)
    for identity, group in list(identities.items())[:16]:
        doc = group[0]
        if len(group) != 1:
            output["gaps"].append({"code": "document_identity_conflict", "source_id": identity}); continue
        published = _date(doc.get("published_at"))
        title = doc.get("title") if isinstance(doc.get("title"), str) else ""
        period_match = re.search(r"(20\d{2})\s*(?:年\s*)?(半年度|年度)", title)
        period = (period_match[1] + ("-06-30" if period_match[2] == "半年度" else "-12-31")) if period_match else None
        pages = doc.get("pages")
        page_list = pages if isinstance(pages, list) else []
        # These real reports place their issuer/security-code information on
        # physical pages 1, 6 or 9, following cover/contents pages.
        front_text = "\n".join(p.get("text", "") for p in page_list[:12] if isinstance(p, dict) and isinstance(p.get("text"), str))
        valid = (isinstance(code, str) and re.fullmatch(r"[0-9]{6}", code)
                 and isinstance(doc.get("source_id"), str) and doc["source_id"] in source_ids
                 and isinstance(doc.get("sha256"), str) and re.fullmatch(r"[a-fA-F0-9]{64}", doc["sha256"])
                 and isinstance(doc.get("url"), str) and doc["url"].startswith("https://")
                 and doc.get("extraction_status") == "complete" and published and period and period <= published <= cutoff
                 and re.search(r"(?:证券代码|股票代码|公司代码)[\s:：]*" + re.escape(code) + r"(?!\d)", front_text))
        if not valid:
            output["gaps"].append({"code": "document_subject_time_or_text_unbound", "source_id": identity}); continue
        output["documents_bound"] += 1
        counts = {key: 0 for key in TOPICS}
        for page in page_list[:500]:
            if not isinstance(page, dict) or not isinstance(page.get("text"), str):
                continue
            page_no, text = page.get("page"), page["text"]
            if isinstance(page_no, bool) or not isinstance(page_no, int) or page_no <= 0 or len(text) > 200000:
                continue
            if "目录" in text[:400] or "目 录" in text[:400]:
                continue
            for topic, needles in TOPICS.items():
                if counts[topic] >= 2:
                    continue
                matches = [text.find(word) for word in needles if word in text]
                if not matches:
                    continue
                offset = min(matches)
                excerpt = text[max(0, offset - 180):min(len(text), offset + 1800)]
                if not excerpt.strip():
                    continue
                counts[topic] += 1
                output["evidence"].append({"id": f"issuer-{identity}-p{page_no}-{topic}",
                    "company_code": code, "report_date": period, "announced_at": published,
                    "source_id": doc["source_id"], "source_url": doc["url"], "document_id": identity, "page": page_no,
                    "origin": "issuer_disclosure", "publisher_relationship": "issuer", "publisher": company.get("name"),
                    "perspective": "context", "topic": topic, "text": excerpt,
                    "document_sha256": doc["sha256"], "location_basis": "exact_slice_of_cached_pdf_page_text",
                    "candidate_only": True})
    if not output["evidence"]:
        output["gaps"].append({"code": "issuer_candidate_text_unavailable"})
    return output


def prepare_business_bundle(bundle, cache_dir, *, as_of):
    """Return only new deterministic fields; never mutate the input bundle."""
    recovered = recover_business_statements(bundle, cache_dir)
    text = locate_issuer_material(bundle.get("company") or {}, bundle.get("documents") or [],
                                  bundle.get("sources") or [], as_of=as_of)
    recovered["gaps"].extend(text["gaps"])
    recovered["coverage"]["documents_bound"] = text["documents_bound"]
    recovered["coverage"]["issuer_candidate_excerpts"] = len(text["evidence"])
    if recovered["statements"] and recovered["gaps"]:
        recovered["status"] = "partial"
    return {"business_adapter_version": BUSINESS_ADAPTER_VERSION,
            "business_statements": recovered.pop("statements"),
            "business_qualitative_evidence": text["evidence"], "business_data_recovery": recovered}


def build_business_view(bundle, *, as_of, industry_model=None):
    """Pure report addition using the adapter output; no financial score changes."""
    company = deepcopy(bundle.get("company") or {})
    current = bundle.get("business_adapter_version") == BUSINESS_ADAPTER_VERSION
    statements = bundle.get("business_statements") if current else []
    evidence = bundle.get("business_qualitative_evidence") if current else []
    meta = deepcopy(bundle.get("business_data_recovery")) if current and isinstance(bundle.get("business_data_recovery"), dict) else {
        "version": BUSINESS_RECOVERY_VERSION, "adapter_version": BUSINESS_ADAPTER_VERSION,
        "status": "unavailable", "sources": [], "coverage": {},
        "gaps": [{"code": "business_adapter_missing_or_outdated"}]}
    if not _date(as_of):
        statements, evidence = [], []
        meta["gaps"].append({"code": "financial_cutoff_missing"})
    # An unversioned or malformed adapter is unavailable, not a fallback to the
    # old scalar financial table. Explicit schema version is required.
    statements = statements if isinstance(statements, list) else []
    evidence = evidence if isinstance(evidence, list) else []
    if not _date(as_of) and not _date(company.get("report_date")):
        section = {"version": BUSINESS_CAPITAL_VERSION, "status": "unavailable", "code": company.get("code"),
                   "label": "生意与资金使用：缺少可确认财务截止", "anchor_year": None, "as_of": None,
                   "years": [], "windows": [], "evidence": [], "evidence_groups": {}, "capital_events": [], "gaps": [],
                   "competitive_advantage": {"status": "insufficient", "rating": None, "proven": False},
                   "capital_allocation_quality": {"status": "insufficient", "rating": None},
                   "coverage": {"official_values_verified": 0}, "limitations": []}
    else:
        section = analyze_business_capital(company, statements, as_of=_date(as_of), qualitative_evidence=evidence,
                                           capital_events=[], industry_model=industry_model)
    originals = {e.get("id"): e for e in evidence if isinstance(e, dict) and isinstance(e.get("id"), str)}
    for item in section["evidence"]:
        original = originals.get(item.get("id"), {})
        item["source_ref"]["document_sha256"] = original.get("document_sha256")
        item["location_basis"] = original.get("location_basis")
        item["candidate_only"] = True
    section["data_recovery"] = meta
    for gap in meta.get("gaps", []):
        section["gaps"].append({"key": "source_recovery:" + str(gap.get("code")),
                               "reason": gap.get("code"), "source_id": gap.get("source_id"),
                               "report_type": gap.get("report_type")})
    return section


def recover_saved_business_view(stored, cache_dir):
    """Use the saved report's identities and cutoff, never a later snapshot."""
    company = deepcopy(stored.get("company")) if isinstance(stored.get("company"), dict) else {}
    report = stored.get("report") if isinstance(stored.get("report"), dict) else {}
    as_of = _date(company.get("as_of")) or _date(str(stored.get("updated_at") or "")[:10]) or _date(company.get("announced_at"))
    cached, gaps = recovery.read_cached_company_bundle(cache_dir, company.get("code"))
    sources = deepcopy(stored.get("sources") or company.get("sources") or [])
    if not isinstance(sources, list):
        sources = []
    # Missing saved source identity cannot be filled with a newer manifest.
    if not sources:
        gaps.append({"code": "saved_source_manifest_missing"})
    saved_evidence = report.get("evidence")
    if not isinstance(saved_evidence, list):
        saved_evidence = []
        gaps.append({"code": "saved_evidence_manifest_invalid"})
    saved_docs = {str(d["id"]): d for d in saved_evidence if isinstance(d, dict) and d.get("id")}
    documents = []
    cached_documents = cached.get("documents") if isinstance(cached, dict) else []
    if not isinstance(cached_documents, list):
        cached_documents = []
        gaps.append({"code": "cached_document_manifest_invalid"})
    for doc in cached_documents:
        if not isinstance(doc, dict) or str(doc.get("id") or "") not in saved_docs:
            continue
        saved_doc = saved_docs[str(doc["id"])]
        if (not saved_doc.get("url") or not saved_doc.get("published_at")
            or any(saved_doc.get(key) is not None and saved_doc.get(key) != doc.get(key) for key in ("url", "published_at", "sha256"))):
            gaps.append({"code": "saved_document_identity_mismatch", "source_id": doc.get("id")}); continue
        if not saved_doc.get("sha256"):
            gaps.append({"code": "saved_document_hash_not_frozen", "source_id": doc.get("id")})
        # Only originally available text pages are candidates for the old view.
        allowed_pages = saved_doc.get("pages")
        if not isinstance(allowed_pages, list):
            gaps.append({"code": "saved_document_page_manifest_missing", "source_id": doc.get("id")}); continue
        if not isinstance(doc.get("pages"), list):
            gaps.append({"code": "cached_document_pages_invalid", "source_id": doc.get("id")}); continue
        copy_doc = deepcopy(doc)
        copy_doc["pages"] = [p for p in doc.get("pages", []) if isinstance(p, dict) and p.get("page") in allowed_pages]
        # The old report retained the PDF identity, not necessarily the ID of a
        # later announcement-list request. Bind the excerpt to that saved PDF.
        copy_doc["source_id"] = str(doc["id"])
        sources.append({"id": str(doc["id"]), "url": saved_doc["url"],
                        "published_at": saved_doc["published_at"], "sha256": doc.get("sha256")})
        documents.append(copy_doc)
    if not as_of:
        sources, documents = [], []
        gaps.append({"code": "saved_financial_cutoff_missing"})
    bundle = {"company": company, "sources": sources, "documents": documents}
    bundle.update(prepare_business_bundle(bundle, cache_dir, as_of=as_of))
    bundle["business_data_recovery"]["gaps"].extend(gaps)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    flags = summary.get("flags")
    if not isinstance(flags, list):
        flags = []
        bundle["business_data_recovery"]["gaps"].append({"code": "saved_summary_flags_invalid"})
    if any(isinstance(f, dict) and f.get("code") in {"source_conflict", "conflicting_period"} for f in flags):
        bundle["business_data_recovery"]["gaps"].append({"code": "saved_source_conflict_unresolved"})
    if bundle["business_data_recovery"]["gaps"] and bundle["business_statements"]:
        bundle["business_data_recovery"]["status"] = "partial"
    return build_business_view(bundle, as_of=as_of, industry_model=summary.get("industry_model"))
