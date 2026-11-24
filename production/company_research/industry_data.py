"""Source-bound industry applicability, independent of legacy six-factor math.

Only original, hash-checked local statement files are recovered. ORG_TYPE is a
supplier statement classification, not a verified regulatory licence. 'General'
is a statement template and never evidence of an ordinary nonfinancial sector.
"""
from copy import deepcopy
from datetime import date, datetime
import math
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .business_data import recover_business_statements
from . import debt_recovery as recovery
from .industry_policy import INDUSTRY_POLICY_VERSION, build_industry_profile

INDUSTRY_ADAPTER_VERSION = "industry-data-1.0"
INDUSTRY_GATE_VERSION = "industry-applicability-gate-1.0"
FINANCIAL_TYPES = {"银行": "bank", "保险": "insurance", "证券": "securities"}
PROFIT_FIELDS = {"net_profit": "NETPROFIT", "parent_profit": "PARENT_NETPROFIT"}

# Exact current supplier sectors, reviewed only for method applicability. The
# lookup is never applied to a free-floating company label: source/subject/hash
# and BOARD_NAME_2LEVEL must first match the original master-data response.
CURRENT_MAPPING_VERSION = "eastmoney-current-industry-1.0"
CURRENT_SECTORS = {
    "bank": {"银行Ⅱ"}, "insurance": {"保险Ⅱ"}, "securities": {"证券Ⅱ"},
    "financial_unresolved": {"多元金融"}, "property": {"房地产开发", "房地产服务"},
    "cyclical": {"玻璃玻纤", "炼化及贸易", "工业金属", "航运港口", "航空机场", "工程机械", "水泥", "农化制品",
        "化学纤维", "贵金属", "造纸", "化学原料", "煤炭开采", "化学制品", "冶钢原料", "金属新材料", "小金属",
        "特钢Ⅱ", "普钢", "焦炭Ⅱ", "能源金属", "风电设备", "光伏设备", "塑料", "油气开采Ⅱ", "橡胶",
        "非金属材料Ⅱ", "半导体", "油服工程", "电子化学品Ⅱ", "种植业", "养殖业", "林业Ⅱ", "渔业"},
    "general": {"一般零售", "轨交设备Ⅱ", "基础建设", "白色家电", "饰品", "农产品加工", "光学光电子", "消费电子",
        "电力", "医药商业", "汽车零部件", "专业工程", "IT服务Ⅱ", "环境治理", "通用设备", "电池", "装修建材",
        "其他电子Ⅱ", "通信设备", "计算机设备", "化学制药", "电视广播Ⅱ", "电网设备", "生物制品", "家电零部件Ⅱ",
        "燃气Ⅱ", "中药Ⅱ", "酒店餐饮", "铁路公路", "旅游及景区", "软件开发", "医疗服务", "地面兵装Ⅱ", "教育",
        "食品加工", "照明设备Ⅱ", "军工电子Ⅱ", "商用车", "环保设备Ⅱ", "航空装备Ⅱ", "白酒Ⅱ", "乘用车", "广告营销",
        "医疗美容", "物流", "房屋建设Ⅱ", "元件", "包装印刷", "数字媒体", "饲料", "休闲食品", "出版", "纺织制造",
        "非白酒", "汽车服务", "工程咨询服务Ⅱ", "黑色家电", "影视院线", "专业连锁Ⅱ", "通信服务", "饮料乳品",
        "专用设备", "家居用品", "摩托车及其他", "电机Ⅱ", "自动化设备", "个护用品", "服装家纺", "文娱用品",
        "小家电", "医疗器械", "互联网电商", "厨卫电器", "装修装饰Ⅱ", "其他电源设备Ⅱ", "专业服务", "游戏Ⅱ",
        "化妆品", "调味发酵品Ⅱ", "其他家电Ⅱ", "动物保健Ⅱ", "航天装备Ⅱ", "体育Ⅱ", "航海装备Ⅱ", "旅游零售Ⅱ"},
}
SCAN_REPORTS = {"RPT_F10_ORG_BASICINFO", "RPT_LICO_FN_CPD", "RPT_F10_FINANCE_GINCOME"}


def _read_scan_sources(sources, cache_dir):
    """Bounded multi-issuer variant of the reviewed local raw boundary."""
    loaded, gaps, signatures = {}, [], {}
    sources = sources if isinstance(sources, list) else []
    for source in sources:
        if isinstance(source, dict) and isinstance(source.get("id"), str):
            signatures.setdefault(source["id"], set()).add(json.dumps(source, sort_keys=True, ensure_ascii=True, default=str))
    root, count, total_rows = Path(os.path.abspath(os.fspath(cache_dir))), [0], 0
    for source in sources:
        if not isinstance(source, dict) or not isinstance(recovery._report(source), str) or recovery._report(source) not in SCAN_REPORTS:
            continue
        sid = source.get("id")
        if isinstance(sid, str) and sid in loaded:
            continue
        try:
            if not recovery._source_id(sid) or len(signatures.get(sid, [])) != 1:
                raise recovery.RecoveryError("scan_source_identity_conflict")
            if len(loaded) >= 64:
                raise recovery.RecoveryError("scan_source_count_limit")
            url = urlsplit(source.get("url") or "")
            if url.scheme != "https" or url.hostname != "datacenter-web.eastmoney.com" or url.path != "/api/data/v1/get":
                raise recovery.RecoveryError("scan_source_endpoint_unrecognized")
            if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[a-fA-F0-9]{64}", source["sha256"]):
                raise recovery.RecoveryError("scan_source_sha256_missing_or_invalid")
            if not _date(source.get("fetched_at")):
                raise recovery.RecoveryError("scan_observation_date_unknown")
            content = recovery._read_source(root, source.get("raw_file"), source["sha256"], recovery.MAX_TOTAL_BYTES - count[0], count)
            value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=recovery._unique_object, parse_constant=recovery._invalid_constant)
            if not isinstance(value, dict) or value.get("success") is False or value.get("code") not in (None, 0):
                raise recovery.RecoveryError("scan_raw_response_invalid")
            rows = value.get("result", {}).get("data") if isinstance(value.get("result"), dict) else None
            if not isinstance(rows, list) or not rows or len(rows) > recovery.MAX_ROWS_PER_FILE:
                raise recovery.RecoveryError("scan_raw_rows_invalid")
            if any(not isinstance(r, dict) or not isinstance(r.get("SECURITY_CODE"), str)
                   or not re.fullmatch(r"(?:[0-9]{6}|A[0-9]{5})", r["SECURITY_CODE"]) for r in rows):
                raise recovery.RecoveryError("scan_raw_subject_invalid")
            total_rows += len(rows)
            if total_rows > 20000:
                raise recovery.RecoveryError("scan_total_row_limit")
            indexed = {}
            for row in rows:
                # The real all-market GINCOME response includes Axxxxx issuer
                # codes despite its A-share filter. Only exact six-digit
                # subjects from the independently verified listed universe
                # can bind to a company; retain the exclusion count.
                if not re.fullmatch(r"[0-9]{6}", row["SECURITY_CODE"]):
                    continue
                indexed.setdefault(row["SECURITY_CODE"], []).append(row)
            loaded[sid] = {"source": source, "rows": indexed,
                "non_a_share_rows_excluded": sum(not re.fullmatch(r"[0-9]{6}", r["SECURITY_CODE"]) for r in rows)}
        except recovery.RecoveryError as exc:
            gaps.append(_gap(str(exc), sid))
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            gaps.append(_gap("scan_raw_unavailable_or_invalid", sid))
    return loaded, gaps


def recover_scan_industry_inputs(snapshot, cache_dir):
    """Recover current supplier observations, never historical announcement dates.

    Returns independent fields keyed by security code. No source or snapshot is
    modified, and no unknown value is replaced by zero. Each earnings field is
    bound to its own referenced source/period/publication instead of row dates.
    """
    loaded, source_gaps = _read_scan_sources(snapshot.get("sources"), cache_dir)
    result = {}
    for company in snapshot.get("companies", []) if isinstance(snapshot.get("companies"), list) else []:
        if not isinstance(company, dict): continue
        code, cutoff, period = company.get("code"), _date(company.get("as_of")), _date(company.get("report_date"))
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code): continue
        policy = {"code": code, "as_of": cutoff, "report_date": period, "net_profit": None, "parent_profit": None,
                  "field_sources": {}, "source_conflicts": [], "industry_classification": {"model": "unknown"}}
        gaps, refs = [], []
        sid = company.get("universe_source_id")
        master = loaded.get(sid) if isinstance(sid, str) else None
        rows = master["rows"].get(code, []) if master else []
        if master and recovery._report(master["source"]) == "RPT_F10_ORG_BASICINFO" and len(rows) == 1:
            source, raw = master["source"], rows[0]
            label, org = raw.get("BOARD_NAME_2LEVEL"), raw.get("ORG_TYPE")
            model = next((m for m, labels in CURRENT_SECTORS.items() if isinstance(label, str) and label in labels), "unknown")
            observed = _date(source.get("fetched_at"))
            valid = (cutoff and observed and observed <= cutoff and label == company.get("industry")
                     and raw.get("LISTING_STATE") == "0" and raw.get("SECURITY_TYPE") == "A股")
            if "LISTING_DATE" in raw and (not _date(raw["LISTING_DATE"]) or not observed or _date(raw["LISTING_DATE"]) > observed):
                valid = False
            if isinstance(org, str) and org in FINANCIAL_TYPES and model not in {FINANCIAL_TYPES[org], "financial_unresolved"}:
                valid = False
                gaps.append(_gap("current_classification_type_conflict", sid))
            if model == "general" and org != "通用":
                valid = False
                gaps.append(_gap("current_nonfinancial_statement_type_unresolved", sid))
            if valid and model != "unknown":
                policy["industry_classification"] = {"model": model, "source_id": sid, "observed_at": source["fetched_at"],
                    "announced_at": None, "temporal_basis": "supplier_current_snapshot", "report_type": "RPT_F10_ORG_BASICINFO",
                    "raw_field": "BOARD_NAME_2LEVEL", "raw_value": label, "supplier_org_type": org,
                    "mapping_version": CURRENT_MAPPING_VERSION, "sha256": source["sha256"], "source_url": source["url"],
                    "verification": "supplier_current_label_only", "historical_pit_usable": False}
                refs.append({"source_id": sid, "report_type": "RPT_F10_ORG_BASICINFO", "sha256": source["sha256"], "status": "verified"})
            else:
                gaps.append(_gap("current_classification_subject_time_or_mapping_unresolved", sid))
        else:
            gaps.append(_gap("current_classification_source_unavailable", sid))
        field_sources = company.get("field_sources")
        field_sources = field_sources if isinstance(field_sources, dict) else {}
        for key, expected_type in (("net_profit", "RPT_F10_FINANCE_GINCOME"), ("parent_profit", "RPT_LICO_FN_CPD")):
            bound = field_sources.get(key)
            bound = bound if isinstance(bound, dict) else {}
            sid = bound.get("source_id"); table = loaded.get(sid) if isinstance(sid, str) else None
            field = PROFIT_FIELDS[key]
            meta = {"source_id": sid, "field": field, "report_date": None, "announced_at": None, "status": "metadata_invalid"}
            policy["field_sources"][key] = meta
            if not table or recovery._report(table["source"]) != expected_type or bound.get("field") != field:
                gaps.append(_gap("profit_referenced_scan_source_unavailable", sid, key)); continue
            source = table["source"]
            rows = [r for r in table["rows"].get(code, []) if _date(r.get("REPORT_DATE", r.get("REPORTDATE"))) == period and period]
            if not cutoff or _date(source.get("fetched_at")) > cutoff:
                rows = []
            visible = [r for r in rows if (not _date(r.get("NOTICE_DATE")) or _date(r.get("NOTICE_DATE")) <= cutoff)
                       and (not _date(r.get("UPDATE_DATE")) or _date(r.get("UPDATE_DATE")) <= cutoff)]
            latest = max((_date(r.get("NOTICE_DATE")) for r in visible if _date(r.get("NOTICE_DATE"))), default=None)
            rows = [r for r in visible if _date(r.get("NOTICE_DATE")) in {latest, None}]
            finance_types = {FINANCIAL_TYPES[r["ORG_TYPE"]] for r in rows
                             if isinstance(r.get("ORG_TYPE"), str) and r["ORG_TYPE"] in FINANCIAL_TYPES}
            model = policy["industry_classification"]["model"]
            if finance_types and (len(finance_types) != 1 or model not in finance_types | {"financial_unresolved"}):
                policy["industry_classification"] = {"model": "unknown"}
                gaps.append(_gap("classification_statement_type_conflict", sid, "ORG_TYPE"))
            values = [_number(r.get(field)) for r in rows]
            currencies_ok = all("CURRENCY" not in r or r["CURRENCY"] == "CNY" for r in rows)
            units_ok = all(all(k not in r or r[k] in ("元", "人民币元", "CNY") for k in ("UNIT", "AMOUNT_UNIT")) for r in rows)
            scope_ok = all(all(k not in r or r[k] in ("consolidated", "合并") for k in ("SCOPE", "STATEMENT_SCOPE"))
                           and all(k not in r or r[k] in ("year_to_date", "累计") for k in ("FLOW_BASIS", "flow_basis"))
                           and ("PERIOD_START" not in r or _date(r["PERIOD_START"]) == period[:4] + "-01-01") for r in rows)
            dates_ok = (latest and period and period <= latest and all(_date(r.get("NOTICE_DATE")) for r in rows)
                and all("UPDATE_DATE" not in r or r["UPDATE_DATE"] in (None, "") or _date(r["UPDATE_DATE"]) for r in rows)
                and all(k not in bound or bound[k] == expected for k, expected in (("report_date", period), ("announced_at", latest))))
            same = bool(values) and all(v is not None and v == values[0] for v in values)
            stored_value = _number(company.get(key))
            matches = same and stored_value is not None and math.isclose(values[0], stored_value, rel_tol=1e-8, abs_tol=1e-6)
            conflicts = company.get("source_conflicts", [])
            conflicted = not isinstance(conflicts, list) or any(isinstance(c, dict) and c.get("field", c.get("key")) == key for c in conflicts)
            if dates_ok and currencies_ok and units_ok and scope_ok and matches and not conflicted:
                policy[key] = values[0]
                meta.update(report_date=period, announced_at=latest, status="reported_zero" if values[0] == 0 else "reported_value",
                    observed_at=source["fetched_at"], report_type=expected_type, sha256=source["sha256"],
                    verification="supplier_only", unit_basis="declared_supplier_endpoint_CNY_yuan", historical_pit_usable=False,
                    non_a_share_rows_excluded=table["non_a_share_rows_excluded"])
                refs.append({"source_id": sid, "report_type": expected_type, "sha256": source["sha256"], "status": "verified"})
            else:
                gaps.append(_gap("profit_scan_value_period_or_basis_unresolved", sid, key))
        relevant = {v.get("source_id") for v in field_sources.values() if isinstance(v, dict) and isinstance(v.get("source_id"), str)}
        if isinstance(company.get("universe_source_id"), str):
            relevant.add(company["universe_source_id"])
        supplied_type = company.get("financial_type")
        if isinstance(supplied_type, str) and supplied_type in FINANCIAL_TYPES and policy["industry_classification"]["model"] not in {FINANCIAL_TYPES[supplied_type], "financial_unresolved"}:
            policy["industry_classification"] = {"model": "unknown"}
            gaps.append(_gap("classification_statement_type_conflict", field="financial_type"))
        gaps.extend(deepcopy(g) for g in source_gaps if g.get("source_id") in relevant)
        result[code] = {"industry_adapter_version": INDUSTRY_ADAPTER_VERSION, "industry_profile_input": policy,
            "industry_data_recovery": {"version": INDUSTRY_ADAPTER_VERSION, "mode": "verified_current_scan_raw",
                "status": "partial" if gaps else "recovered", "sources": refs, "gaps": gaps,
                "coverage": {"raw_hashes_rechecked": bool(refs), "source_checks_attempted": True,
                             "verified_sources": len({r['source_id'] for r in refs})},
                "historical_pit_usable": False}}
    return result


def _date(value):
    if not isinstance(value, str):
        return None
    # Supplier dates are either dates or complete SQL/ISO timestamps.
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?", value):
        return None
    try:
        if len(value) > 10:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _gap(code, source_id=None, field=None):
    return {"code": code, "source_id": source_id, "field": field}


def adapt_industry_statements(company, statements, *, as_of):
    """Pure bounded mapping after safe raw recovery; do not change scalars.

    The original financial period is fixed. A newer row cannot advance it. Two
    earnings fields require explicit CNY and the declared F10 GINCOME schema.
    Known later publications supersede older values; an undated conflict cannot.
    """
    company = company if isinstance(company, dict) else {}
    cutoff, period = _date(as_of), _date(company.get("report_date"))
    policy = {"code": company.get("code"), "name": company.get("name"), "report_date": period,
              "as_of": cutoff, "field_sources": {}, "source_conflicts": [],
              "net_profit": None, "parent_profit": None}
    gaps, classification, candidates = [], [], {key: [] for key in PROFIT_FIELDS}
    for statement in statements if isinstance(statements, list) else []:
        if not isinstance(statement, dict):
            continue
        source = statement.get("source")
        source = source if isinstance(source, dict) else {}
        sid, kind = source.get("id"), statement.get("report_type")
        declared = (source.get("parameters") or {}).get("reportName") if isinstance(source.get("parameters"), dict) else None
        if not isinstance(sid, str) or not sid or kind != declared:
            gaps.append(_gap("statement_source_contract_invalid", sid)); continue
        for row in statement.get("rows", []) if isinstance(statement.get("rows"), list) else []:
            if not isinstance(row, dict) or _date(row.get("REPORT_DATE")) != period or not period:
                continue
            announced, updated = _date(row.get("NOTICE_DATE")), _date(row.get("UPDATE_DATE"))
            if not cutoff or period > cutoff or (announced and announced > cutoff) or (updated and updated > cutoff):
                gaps.append(_gap("statement_not_visible_at_cutoff", sid)); continue
            if announced and announced < period:
                gaps.append(_gap("announcement_before_report_period", sid)); continue
            bad_update = row.get("UPDATE_DATE") not in (None, "") and not updated
            if bad_update:
                gaps.append(_gap("provider_update_date_invalid", sid)); continue
            org = row.get("ORG_TYPE")
            if isinstance(org, str) and org in FINANCIAL_TYPES:
                classification.append({"model": FINANCIAL_TYPES[org], "raw_value": org,
                    "field": "ORG_TYPE", "source_id": sid, "report_type": kind,
                    "report_date": period, "announced_at": announced, "provider_updated_at": updated,
                    "verification": "supplier_statement_type_only", "sha256": source.get("sha256")})
            elif isinstance(org, str) and org in {"通用", "一般企业", "非金融"}:
                gaps.append(_gap("statement_template_not_industry_evidence", sid, "ORG_TYPE"))
            elif org:
                gaps.append(_gap("statement_type_mapping_unreviewed", sid, "ORG_TYPE"))
            if kind != "RPT_F10_FINANCE_GINCOME":
                continue
            raw_unit = row.get("UNIT", row.get("AMOUNT_UNIT"))
            absent_unit = "UNIT" not in row and "AMOUNT_UNIT" not in row
            factor = 1 if absent_unit else {"元": 1, "人民币元": 1, "CNY": 1, "万元": 10000, "人民币万元": 10000, "亿元": 100000000}.get(raw_unit) if isinstance(raw_unit, (str, type(None))) else None
            scope = row.get("SCOPE", row.get("STATEMENT_SCOPE", "consolidated"))
            flow = row.get("FLOW_BASIS", row.get("flow_basis", "year_to_date"))
            issues = []
            if row.get("CURRENCY") != "CNY": issues.append("profit_currency_unconfirmed")
            if factor is None: issues.append("profit_unit_unconfirmed")
            if not isinstance(scope, str) or scope not in {"consolidated", "合并"}: issues.append("profit_scope_unconfirmed")
            if not isinstance(flow, str) or flow not in {"year_to_date", "累计", "annual", "全年"}: issues.append("profit_flow_basis_invalid")
            if isinstance(flow, str) and flow in {"annual", "全年"} and not period.endswith("12-31"): issues.append("profit_flow_period_mismatch")
            if "PERIOD_START" in row and _date(row.get("PERIOD_START")) != period[:4] + "-01-01": issues.append("profit_start_period_invalid")
            for key, raw_field in PROFIT_FIELDS.items():
                if raw_field not in row:
                    continue
                value = _number(row[raw_field])
                if value is not None and factor is not None:
                    value *= factor
                    if not math.isfinite(value): value = None
                state = "metadata_invalid" if issues else "missing" if row[raw_field] is None else "invalid" if value is None else "reported_zero" if value == 0 else "reported_value"
                ref = {"source_id": sid, "field": raw_field, "report_type": kind, "report_date": period,
                       "announced_at": announced, "provider_updated_at": updated, "sha256": source.get("sha256"),
                       "currency": row.get("CURRENCY"), "scope": scope, "flow_basis": flow,
                       "unit_factor": factor, "unit_basis": "supplier_F10_yuan_contract" if absent_unit else "explicit_raw_unit",
                       "verification": "supplier_only"}
                candidates[key].append({"value": None if issues else value, "status": state,
                                        "announced_at": announced, "source_ref": ref, "issues": issues})
    if classification:
        # An unknown publication date cannot be sorted before dated evidence.
        latest = max((x["announced_at"] for x in classification if x["announced_at"]), default=None)
        selected = [x for x in classification if x["announced_at"] in {latest, None}]
        models = {x["model"] for x in selected}
        if len(models) != 1 or any(x["announced_at"] is None for x in selected):
            gaps.append(_gap("classification_conflict_or_publication_unknown"))
        else:
            policy["industry_classification"] = deepcopy(selected[0])
            policy["industry_classification"]["source_refs"] = deepcopy(selected)
    if "industry_classification" not in policy:
        policy["industry_classification"] = {"model": "unknown"}
        gaps.append(_gap("dated_industry_classification_unavailable"))
    for key, choices in candidates.items():
        latest = max((c["announced_at"] for c in choices if c["announced_at"]), default=None)
        selected = [c for c in choices if c["announced_at"] in {latest, None}]
        # Same-date nulls cannot erase a reported value. Invalid metadata does
        # block it; unknown publication never becomes visible by merging.
        evaluated = [c for c in selected if c["status"] != "missing"] or selected
        if not evaluated:
            policy["field_sources"][key] = {"source_id": None, "report_date": period, "announced_at": None}
            gaps.append(_gap("profit_raw_field_missing", field=key)); continue
        cell = evaluated[0]
        conflict = len({(c["value"], c["status"]) for c in evaluated}) > 1
        status = "conflict" if conflict else cell["status"]
        known_date = latest if all(c["announced_at"] for c in selected) else None
        policy[key] = cell["value"] if status in {"reported_value", "reported_zero"} and known_date else None
        policy["field_sources"][key] = {**deepcopy(cell["source_ref"]), "announced_at": known_date, "status": status,
            "source_refs": [deepcopy(c["source_ref"]) for c in selected],
            "superseded_source_refs": [deepcopy(c["source_ref"]) for c in choices if c not in selected]}
        if conflict:
            policy["source_conflicts"].append({"field": key})
        if policy[key] is None:
            gaps.append(_gap("profit_conflict" if conflict else "profit_metadata_or_value_unavailable", field=key))
        gaps.extend(_gap(issue, cell["source_ref"]["source_id"], key) for issue in cell["issues"])
    return policy, gaps


def prepare_industry_bundle(bundle, cache_dir, *, as_of):
    recovered = recover_business_statements(bundle, cache_dir)
    policy, gaps = adapt_industry_statements(bundle.get("company"), recovered.pop("statements"), as_of=as_of)
    recovered.update(version=INDUSTRY_ADAPTER_VERSION, adapter_version=INDUSTRY_ADAPTER_VERSION)
    recovered["gaps"].extend(gaps)
    if recovered["gaps"] and recovered["coverage"]["verified_sources"]:
        recovered["status"] = "partial"
    recovered["classification_basis"] = "dated_supplier_statement_type_only"
    current = recover_scan_industry_inputs({"companies": [bundle.get("company") or {}], "sources": bundle.get("sources")}, cache_dir)
    supplemental = current.get(policy.get("code"), {}).get("industry_profile_input", {}).get("industry_classification", {})
    if supplemental.get("temporal_basis") == "supplier_current_snapshot":
        original_model = policy.get("industry_classification", {}).get("model")
        conflict = original_model in {"bank", "insurance", "securities"} and original_model != supplemental.get("model")
        policy["industry_classification"] = {"model": "unknown"} if conflict else supplemental
        if conflict:
            recovered["gaps"].append(_gap("classification_statement_type_conflict"))
        recovered["classification_basis"] = "current_supplier_observation_not_announcement"
        recovered["gaps"] = [g for g in recovered["gaps"] if g.get("code") != "dated_industry_classification_unavailable"]
        recovered["sources"].append({"source_id": supplemental["source_id"], "sha256": supplemental["sha256"],
            "report_type": supplemental["report_type"], "status": "verified"})
    return {"industry_adapter_version": INDUSTRY_ADAPTER_VERSION, "industry_profile_input": policy,
            "industry_data_recovery": recovered}


def build_industry_view(bundle, *, as_of, purpose="current_research"):
    company = bundle.get("company") if isinstance(bundle.get("company"), dict) else {}
    policy = bundle.get("industry_profile_input")
    bound = (bundle.get("industry_adapter_version") == INDUSTRY_ADAPTER_VERSION and isinstance(policy, dict)
             and policy.get("code") == company.get("code") and policy.get("report_date") == _date(company.get("report_date"))
             and policy.get("as_of") == _date(as_of))
    if not bound:
        # Strict policy permits explicitly dated caller classifications, but
        # legacy name/label substrings and unbound financial aliases never do.
        from .dynamic_data import _copy_view_data
        policy = _copy_view_data(company)
        for key in PROFIT_FIELDS:
            fields = company.get("field_sources")
            field = fields.get(key) if isinstance(fields, dict) else None
            if not isinstance(field, dict) or not all(k in field for k in ("source_id", "report_date", "announced_at")):
                policy[key] = None
        meta = {"version": INDUSTRY_ADAPTER_VERSION, "status": "unavailable", "sources": [], "coverage": {},
                "gaps": [_gap("industry_adapter_missing_outdated_or_unbound")]}
    else:
        meta = deepcopy(bundle.get("industry_data_recovery"))
        meta = meta if isinstance(meta, dict) else {"status": "unavailable", "gaps": [_gap("industry_recovery_metadata_missing")]}
    profile = build_industry_profile(policy, as_of=_date(as_of), purpose=purpose)
    profile.update(code=company.get("code"), report_date=company.get("report_date"), adapter_version=INDUSTRY_ADAPTER_VERSION,
                   data_recovery=meta, earnings_sources=deepcopy(policy.get("field_sources", {})))
    profile["classification"]["observed_supplier_label"] = {"industry": company.get("industry"),
        "financial_type": company.get("financial_type"), "observed_at": company.get("as_of"),
        "announcement_date": None, "use": "current_label_only_not_historical_classification"}
    profile["limitations"].append("财报ORG_TYPE为供应商报表类型；通用模板不能证明普通行业，日期与哈希匹配也不代表官方逐值或严格PIT核验。")
    return profile


def recover_saved_industry_view(stored, cache_dir, *, current_input=None):
    company = deepcopy(stored.get("company")) if isinstance(stored.get("company"), dict) else {}
    cutoff = _date(company.get("as_of")) or _date(str(stored.get("updated_at") or "")[:10])
    sources = stored.get("sources") or company.get("sources") or []
    sources = deepcopy(sources) if isinstance(sources, list) else []
    bundle = {"company": company, "sources": sources if cutoff else []}
    bundle.update(prepare_industry_bundle(bundle, cache_dir, as_of=cutoff))
    current_input = current_input if isinstance(current_input, dict) else {}
    supplied_policy = current_input.get("industry_profile_input")
    supplied_policy = supplied_policy if isinstance(supplied_policy, dict) else {}
    supplemental = supplied_policy.get("industry_classification")
    supplemental = supplemental if isinstance(supplemental, dict) else {}
    if (supplemental.get("temporal_basis") == "supplier_current_snapshot"
        and supplemental.get("source_id") == company.get("universe_source_id")
        and supplemental.get("raw_value") == company.get("industry")
        and cutoff and _date(supplemental.get("observed_at")) and _date(supplemental["observed_at"]) <= cutoff):
        original_model = bundle["industry_profile_input"].get("industry_classification", {}).get("model")
        conflict = original_model in {"bank", "insurance", "securities"} and original_model != supplemental.get("model")
        bundle["industry_profile_input"]["industry_classification"] = {"model": "unknown"} if conflict else deepcopy(supplemental)
        meta = bundle["industry_data_recovery"]
        if conflict:
            meta["gaps"].append(_gap("classification_statement_type_conflict"))
        meta["classification_basis"] = "original_universe_id_bound_current_supplier_snapshot"
        meta["gaps"] = [g for g in meta["gaps"] if g.get("code") != "dated_industry_classification_unavailable"]
        meta["sources"].append({"source_id": supplemental["source_id"], "sha256": supplemental["sha256"],
                               "report_type": supplemental["report_type"], "status": "verified"})
    report = stored.get("report") if isinstance(stored.get("report"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    flags = summary.get("flags")
    if not isinstance(flags, list) or any(isinstance(f, dict) and f.get("code") in {"source_conflict", "conflicting_period"} for f in flags):
        bundle["industry_profile_input"]["industry_classification"] = {"model": "unknown"}
        bundle["industry_profile_input"]["source_conflicts"] = [{"field": key} for key in PROFIT_FIELDS]
        bundle["industry_data_recovery"]["gaps"].append(_gap("saved_source_conflict_or_flags_unresolved"))
    return build_industry_view(bundle, as_of=cutoff)


def apply_industry_policy_to_screen(screen, profile, *, _already_copied=False):
    """Retain all six factor values/formulas and risk flags, gate their use."""
    result = (screen if _already_copied else deepcopy(screen)) if isinstance(screen, dict) else {}
    permission = profile["modules"]["general_screen"]
    allowed = permission["status"] == "conditional"
    result["industry_applicability"] = {"version": INDUSTRY_GATE_VERSION, "profile_version": INDUSTRY_POLICY_VERSION,
        "model": profile["classification"]["model"], "earnings_status": profile["earnings_status"],
        "as_of": profile["as_of"], "general_ranking_allowed": allowed, **permission}
    result.setdefault("legacy_industry_model", result.get("industry_model"))
    result["industry_model"] = profile["classification"]["model"]
    if not allowed:
        prior_reason = str(result.get("reason") or "")
        result.update(quality_score=None, eligible=False, candidate=False, status="not_applicable",
            quality_label=profile["classification"]["label"] + "：普通六项排名未开放",
            reason=prior_reason if permission["reason"] in prior_reason else (prior_reason + " " + permission["reason"]).strip(),
            summary=permission["reason"], valuation_label="行业估值待专项核查")
        if isinstance(result.get("valuation"), dict):
            result["valuation"]["label"] = result["valuation_label"]
            result["valuation"]["applicability"] = deepcopy(profile["modules"]["valuation"])
    return result


def apply_industry_policy_to_report(report, profile):
    """Keep historical facts; suppress unsupported active interpretations."""
    report["industry_profile"] = deepcopy(profile)
    report["summary"] = apply_industry_policy_to_screen(report.get("summary"), profile)
    modules = profile["modules"]
    valuation = report.get("valuation")
    if isinstance(valuation, dict):
        valuation["applicability"] = deepcopy(modules["valuation"])
        if modules["general_screen"]["status"] != "conditional":
            valuation["label"] = "行业估值待专项核查"
    quality = report.get("quality")
    if isinstance(quality, dict):
        quality.update(score=report["summary"].get("quality_score"), label=report["summary"].get("quality_label"),
                       metrics=deepcopy(report["summary"].get("metrics", [])), applicability=deepcopy(modules["general_screen"]))
        if modules["cash_conversion"]["status"] != "conditional":
            quality["multi_year_cash_conversion_applicability"] = deepcopy(modules["cash_conversion"])
        long_term = quality.get("long_term")
        if isinstance(long_term, dict):
            long_term["applicability"] = deepcopy(modules["long_term"])
            long_term.setdefault("legacy_industry_model", long_term.get("industry_model"))
            long_term["industry_model"] = profile["classification"]["model"]
            if modules["long_term"]["status"] != "conditional":
                # Classification restrictions cannot clear an existing data
                # conflict. Its status/label take precedence over routing.
                if long_term.get("status") != "conflict":
                    long_term.update(status="specialist", label=profile["classification"]["label"] + "：仅保留年度事实与原始趋势")
                for window in long_term.get("windows", []):
                    window["findings"] = [{"key": "industry_applicability", "status": "specialist",
                        "label": "行业适用性待核查", "support": ["保留固定年度数字、来源与缺口。"],
                        "counter_evidence": [modules["long_term"]["reason"]], "periods": window.get("periods", []), "source_ids": []}]
                    window["applicability"] = deepcopy(modules["long_term"])
                    for metric in window.get("metrics", []):
                        if metric.get("key") == "cash_conversion":
                            metric["applicability"] = deepcopy(modules["cash_conversion"])
                            if metric.get("value") is not None:
                                metric["status"] = "context_only"
    for section_key, module_key in (("debt_governance", "debt_liquidity"), ("business_capital", "capital_allocation")):
        section = report.get(section_key)
        if isinstance(section, dict):
            section["industry_policy_applicability"] = deepcopy(modules[module_key])
            if section_key == "debt_governance" and modules[module_key]["status"] == "specialist_required":
                section.setdefault("applicability", {})["general_metrics_enabled"] = False
                section["applicability"]["policy_model"] = profile["classification"]["model"]
                for group in ("debt", "liquidity"):
                    for metric in (section.get(group) or {}).get("metrics", []):
                        metric["applicability"] = deepcopy(modules[module_key])
                        if metric.get("value") is not None:
                            metric["status"] = "context_only"
            if section_key == "business_capital":
                section["gross_margin_applicability"] = deepcopy(modules["gross_margin"])
                for row in section.get("years", []) + section.get("windows", []):
                    for metric in row.get("metrics", []):
                        policy_key = "gross_margin" if metric.get("key", "").startswith("gross_margin") else "capital_allocation"
                        metric["applicability"] = deepcopy(modules[policy_key])
                        if modules[policy_key]["status"] != "conditional" and metric.get("value") is not None:
                            metric["status"] = "context_only"
    return report
