"""Read-only source-bound compatibility for legacy dynamic-evaluation inputs.

Early market snapshots stored field IDs without field-level dates. Recover only
absent date keys from the exact original source, after SHA/subject/period/value
and basis validation. An explicit unknown date stays unknown. Neither market
snapshots nor paid reports are changed; this boundary only returns a new view.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import debt_recovery as recovery
from .data import normalize
from .dynamic_evaluation import _date, _number

VERSION = "dynamic-source-view-1.0"
CPD = "RPT_LICO_FN_CPD"
INCOME = "RPT_F10_FINANCE_GINCOME"
BALANCE = "RPT_DMSK_FN_BALANCE"
CASHFLOW = "RPT_DMSK_FN_CASHFLOW"
FIELD_REPORTS = {
    "roe": {CPD}, "revenue_yoy": {CPD, INCOME}, "revenue": {CPD, INCOME},
    "parent_profit": {CPD, INCOME}, "net_profit": {INCOME}, "adjusted_profit": {CPD, INCOME},
    "op_cashflow": {CASHFLOW}, "debt_ratio": {BALANCE}, "total_assets": {BALANCE},
    "total_liabilities": {BALANCE}, "cash": {BALANCE}, "profit_yoy": {CPD, INCOME},
}
REPORTS = {CPD, INCOME, BALANCE, CASHFLOW}


class _UseOriginalCopy(Exception):
    pass


def _copy_json_graph(value, memo, depth):
    kind = type(value)
    if value is None or kind is str or kind is bool or kind is int or kind is float:
        return value
    if (kind is not dict and kind is not list) or depth > 64:
        raise _UseOriginalCopy
    identity = id(value)
    prior = memo.get(identity)
    if prior is not None:
        return prior
    if kind is dict:
        result = value.copy()
        memo[identity] = result
        for key, item in value.items():
            if type(key) is not str:
                raise _UseOriginalCopy
            item_kind = type(item)
            if not (item is None or item_kind is str or item_kind is bool
                    or item_kind is int or item_kind is float):
                result[key] = _copy_json_graph(item, memo, depth + 1)
    else:
        result = value.copy()
        memo[identity] = result
        for index, item in enumerate(value):
            item_kind = type(item)
            if not (item is None or item_kind is str or item_kind is bool
                    or item_kind is int or item_kind is float):
                result[index] = _copy_json_graph(item, memo, depth + 1)
    return result


def _copy_view_data(value, *, _plain_copy=None):
    """Copy a plain JSON object graph without per-scalar deepcopy dispatch.

    Keep all fields, order, aliases and cycles. Other Python types and deep
    graphs use the original whole-graph protocol; never mix custom hooks into
    a partially copied graph. Leave the exception scope before that fallback
    so its traceback and partial copies can be released first.
    """
    if _plain_copy is not None:
        _plain_copy[0] = False
    memo = {}
    try:
        result = _copy_json_graph(value, memo, 0)
    except _UseOriginalCopy:
        memo.clear()
    else:
        if _plain_copy is not None:
            _plain_copy[0] = True
        return result
    return deepcopy(value)


def _supported(source):
    report = recovery._report(source)
    return isinstance(report, str) and report in REPORTS


def cache_key(sources, cache_dir):
    """Content key covering all four allowed financial tables, including failure.

    Hash current bytes, not mtimes or expected hashes alone; missing, corrupt,
    changed and restored sources consequently invalidate the derived view.
    This is a local cache key, distinct from financial/peer fingerprints.
    """
    selected = [s for s in sources if isinstance(s, dict) and _supported(s)] if isinstance(sources, list) else []
    signatures = sorted({json.dumps(s, sort_keys=True, ensure_ascii=True, default=str) for s in selected})
    root, count, content_keys = Path(os.path.abspath(os.fspath(cache_dir))), [0], {}
    records = []
    for signature in signatures[:recovery.MAX_SOURCE_FILES]:
        source = json.loads(signature)
        raw_file = source.get("raw_file")
        file_key = json.dumps(raw_file, sort_keys=True, ensure_ascii=True)
        if file_key not in content_keys:
            try:
                content = recovery._read_source(root, raw_file, None, recovery.MAX_TOTAL_BYTES - count[0], count)
                content_keys[file_key] = {"sha256": hashlib.sha256(content).hexdigest()}
            except recovery.RecoveryError as exc:
                content_keys[file_key] = {"error": str(exc)}
            except (OSError, TypeError, ValueError):
                content_keys[file_key] = {"error": "raw_unavailable"}
        records.append([signature, content_keys[file_key]])
    if len(signatures) > recovery.MAX_SOURCE_FILES:
        records.append(["source_count_limit", signatures[recovery.MAX_SOURCE_FILES:]])
    return hashlib.sha256(json.dumps([VERSION, records], sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _raw_date(value):
    if not isinstance(value, str):
        return None
    if _date(value):
        return value
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _load(sources, needed, cache_dir, cutoff):
    grouped = defaultdict(list)
    for source in sources if isinstance(sources, list) else []:
        if isinstance(source, dict) and isinstance(source.get("id"), str) and source["id"] in needed:
            grouped[source["id"]].append(source)
    root, counter, count_rows = Path(os.path.abspath(os.fspath(cache_dir))), [0], 0
    loaded = {}
    for sid in sorted(grouped):
        candidates = grouped[sid]
        try:
            signatures = {json.dumps(s, sort_keys=True, ensure_ascii=True) for s in candidates}
            if len(signatures) != 1 or len(loaded) >= recovery.MAX_SOURCE_FILES:
                continue
            source = candidates[0]
            report = recovery._report(source)
            url = urlsplit(source.get("url") or "")
            fetched = _raw_date(source.get("fetched_at"))
            if (not _supported(source) or url.scheme != "https" or url.hostname != "datacenter-web.eastmoney.com"
                    or url.path != "/api/data/v1/get" or not fetched or fetched > cutoff
                    or not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[a-fA-F0-9]{64}", source["sha256"])):
                continue
            content = recovery._read_source(root, source.get("raw_file"), source["sha256"],
                                            recovery.MAX_TOTAL_BYTES - counter[0], counter)
            value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=recovery._unique_object,
                               parse_constant=recovery._invalid_constant)
            if not isinstance(value, dict) or value.get("success") is False or value.get("code") not in (None, 0):
                continue
            raw_rows = value.get("result", {}).get("data") if isinstance(value.get("result"), dict) else None
            if not isinstance(raw_rows, list) or not raw_rows or len(raw_rows) > recovery.MAX_ROWS_PER_FILE:
                continue
            count_rows += len(raw_rows)
            # Four whole-market financial tables; each remains bounded by the
            # shared 64 MiB/64 file boundary, not an unbounded scan of paths.
            if count_rows > 40000:
                break
            indexed = defaultdict(list)
            for raw in raw_rows:
                if not isinstance(raw, dict) or not isinstance(raw.get("SECURITY_CODE"), str):
                    continue
                if not re.fullmatch(r"[0-9]{6}", raw["SECURITY_CODE"]):
                    continue
                indexed[raw["SECURITY_CODE"]].append(raw)
            loaded[sid] = {"report": report, "rows": indexed}
        except (recovery.RecoveryError, OSError, ValueError, TypeError, UnicodeError, RecursionError):
            continue
    return loaded


def _validated_meta(company, key, bound, table, cutoff, *, _normalized=None):
    period = _date(company.get("report_date"))
    if not period or table["report"] not in FIELD_REPORTS[key]:
        return None
    rows = [r for r in table["rows"].get(company.get("code"), [])
            if _raw_date(r.get("REPORT_DATE") or r.get("REPORTDATE")) == period]
    if not rows:
        return None
    observed = []
    for raw in rows:
        published = _raw_date(raw.get("NOTICE_DATE"))
        if not published or not period <= published <= cutoff:
            return None
        if raw.get("UPDATE_DATE") not in (None, ""):
            updated = _raw_date(raw["UPDATE_DATE"])
            if not updated or updated > cutoff:
                return None
        if "CURRENCY" in raw and raw["CURRENCY"] != "CNY":
            return None
        if any(k in raw and raw[k] not in ("元", "人民币元", "CNY") for k in ("UNIT", "AMOUNT_UNIT")):
            return None
        if any(k in raw and raw[k] not in ("consolidated", "合并") for k in ("SCOPE", "STATEMENT_SCOPE")):
            return None
        if raw.get("ORG_TYPE") in ("银行", "保险", "证券"):
            return None
        if any(k in raw and raw[k] not in ("year_to_date", "累计") for k in ("FLOW_BASIS", "flow_basis")):
            return None
        if "PERIOD_START" in raw and _raw_date(raw["PERIOD_START"]) != period[:4] + "-01-01":
            return None
        source_id = bound.get("source_id")
        if _normalized is None or type(source_id) is not str:
            normalized = normalize(raw, source_id)
        else:
            # Reuse only the pure converter's result, never a field validation.
            # _load owns these raw rows throughout this company's verification.
            identity = (id(raw), source_id)
            normalized = _normalized.get(identity)
            if normalized is None:
                normalized = normalize(raw, source_id)
                if len(_normalized) < 16:
                    _normalized[identity] = normalized
        value = _number(normalized.get(key))
        saved = _number(company.get(key))
        normalized_source = normalized.get("field_sources", {}).get(key, {})
        if (value is None or saved is None or not math.isclose(value, saved, rel_tol=1e-8, abs_tol=1e-6)
                or normalized_source.get("field") != bound.get("field")):
            return None
        if any(k in bound and bound[k] != expected for k, expected in (("report_date", period), ("announced_at", published))):
            # Explicit null or another version is not legacy omission.
            return None
        observed.append((value, published))
    if any(item != observed[0] for item in observed):
        return None
    return {"report_date": period, "announced_at": observed[0][1]}


def recover_dynamic_rows(rows, sources, cache_dir, *, as_of):
    """Return independent rows with verified field dates; never writes or calls AI.

    Only scalar financial fields already present are used. Raw files cannot add
    another company's values or upgrade an existing industry permission.
    """
    cutoff = _date(as_of)
    if not cutoff:
        raise ValueError("as_of must be a valid YYYY-MM-DD date")
    result = _copy_view_data(rows)
    needed = set()
    for row in result:
        if not isinstance(row, dict):
            continue
        fields = row.get("field_sources")
        if not isinstance(fields, dict):
            continue
        for key in FIELD_REPORTS:
            bound = fields.get(key)
            if isinstance(bound, dict) and isinstance(bound.get("source_id"), str):
                needed.add(bound["source_id"])
    loaded = _load(sources, needed, cache_dir, cutoff)
    for row in result:
        if not isinstance(row, dict):
            continue
        fields = row.get("field_sources")
        if not isinstance(fields, dict):
            continue
        restored, invalid = [], []
        normalized = {}
        for key in FIELD_REPORTS:
            bound = fields.get(key)
            if not isinstance(bound, dict) or _number(row.get(key)) is None:
                continue
            sid = bound.get("source_id")
            table = loaded.get(sid) if isinstance(sid, str) else None
            try:
                dates = _validated_meta(row, key, bound, table, cutoff, _normalized=normalized) if table else None
            except (ValueError, TypeError, OverflowError):
                dates = None
            if dates:
                if any(k not in bound for k in dates):
                    restored.append(key)
                bound.update(dates)
            else:
                # Make source validation failure visible even if a historical
                # snapshot already contains unsupported field dates.
                bound["status"] = "metadata_invalid"
                invalid.append(key)
        row["dynamic_source_recovery"] = {"version": VERSION, "recovered_fields": restored,
                                          "invalid_fields": invalid, "status": "partial" if invalid else "verified"}
    return result
