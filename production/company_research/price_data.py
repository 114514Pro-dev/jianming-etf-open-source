"""Read-only A-share supplier quote binding and optional arithmetic diagnostics.

Provider ratios are usable as labelled references without pretending that their
full denominators were independently certified. No fetch, AI, writes, or FX.
"""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import debt_recovery as recovery
from .business_data import recover_business_statements
from .industry_data import (build_industry_view, prepare_industry_bundle, INDUSTRY_ADAPTER_VERSION,
                            CURRENT_MAPPING_VERSION, CURRENT_SECTORS, FINANCIAL_TYPES)
from .price_quality import build_price_quality_panel, legacy_market_reference, _day, _num, _text, _obj, _rows

VERSION = "price-data-1.0"
ALLOWED = {"RPT_VALUEANALYSIS_DET", "RPT_F10_ORG_BASICINFO", "RPT_LICO_FN_CPD", "RPT_F10_FINANCE_MAINFINADATA"}
RAW_FIELDS = {"price": "CLOSE_PRICE", "pe_ttm": "PE_TTM", "pb": "PB_MRQ", "market_cap": "TOTAL_MARKET_CAP"}


def _gap(code, source_id=None, field=None):
    return {"code": code, "source_id": source_id, "field": field}


def _load_sources(sources, cache_dir, cutoff):
    root = Path(os.path.abspath(cache_dir))
    loaded, gaps, manifests = {}, [], {}
    for source in _rows(sources):
        sid = source.get("id")
        if not isinstance(sid, str):continue
        manifests.setdefault(sid, []).append(source)
    count, total_rows = [0], 0
    for sid, variants in manifests.items():
        source = variants[0]
        signatures = {json.dumps({k: s.get(k) for k in ("id", "url", "parameters", "raw_file", "sha256")}, sort_keys=True, ensure_ascii=True, default=str) for s in variants}
        try:
            if not recovery._source_id(sid) or len(signatures) != 1:raise recovery.RecoveryError("price_source_identity_conflict")
            if recovery._report(source) not in ALLOWED:continue
            visible = [s for s in variants if _day(s.get("fetched_at")) and _day(s["fetched_at"]) <= cutoff]
            if not visible:raise recovery.RecoveryError("price_source_not_visible_at_cutoff")
            # Identical payload hashes can have several real fetch observations.
            # Use a visible manifest, retaining dates; never invent a fetch time.
            source = min(visible, key=lambda s: s["fetched_at"])
            if len(loaded) >= 64:raise recovery.RecoveryError("price_source_count_limit")
            parsed = urlsplit(source.get("url") or "")
            if parsed.scheme != "https" or parsed.hostname != "datacenter-web.eastmoney.com" or parsed.path != "/api/data/v1/get" or parsed.username or parsed.password:
                raise recovery.RecoveryError("price_source_endpoint_unrecognized")
            observed = _day(source.get("fetched_at"))
            if not observed or observed > cutoff:raise recovery.RecoveryError("price_source_not_visible_at_cutoff")
            digest = source.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):raise recovery.RecoveryError("price_source_hash_missing")
            content = recovery._read_source(root, source.get("raw_file"), digest, recovery.MAX_TOTAL_BYTES - count[0], count)
            payload = json.loads(content.decode("utf-8-sig"), object_pairs_hook=recovery._unique_object, parse_constant=recovery._invalid_constant)
            rows = _obj(payload.get("result")).get("data") if isinstance(payload, dict) else None
            if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(rows, list) or not rows or len(rows) > recovery.MAX_ROWS_PER_FILE:
                raise recovery.RecoveryError("price_raw_response_invalid")
            if any(not isinstance(r, dict) or not isinstance(r.get("SECURITY_CODE"), str) for r in rows):raise recovery.RecoveryError("price_raw_subject_invalid")
            total_rows += len(rows)
            if total_rows > 30000:raise recovery.RecoveryError("price_raw_row_limit")
            indexed = {}
            for row in rows:indexed.setdefault(row["SECURITY_CODE"], []).append(row)
            loaded[sid] = {"source": source, "rows": indexed, "observed_at_candidates": sorted({s["fetched_at"] for s in visible})}
        except recovery.RecoveryError as exc:
            gaps.append(_gap(str(exc), sid))
        except (ValueError, TypeError, OSError, UnicodeError, RecursionError):
            gaps.append(_gap("price_raw_unavailable_or_invalid", sid))
    return loaded, {"adapter_version": VERSION, "raw_hashes_rechecked": bool(loaded), "verified_sources": len(loaded),
                    "read_bytes": count[0], "gaps": gaps, "sources": [{"source_id": sid, "report_type": recovery._report(x["source"]), "sha256": x["source"]["sha256"]} for sid, x in loaded.items()]}


def _reference(company, profile, loaded, cutoff):
    c, code = _obj(company), _obj(company).get("code")
    ref = legacy_market_reference(c, [x["source"] for x in loaded.values()])
    ref["industry_profile"] = deepcopy(profile)
    ref["basis"]["provider"] = "eastmoney_RPT_VALUEANALYSIS_DET"
    ref["adapter_gaps"] = []
    master = loaded.get(c.get("universe_source_id")) if isinstance(c.get("universe_source_id"), str) else None
    master_rows = master["rows"].get(code, []) if master else []
    valid_master = False
    if master and recovery._report(master["source"]) == "RPT_F10_ORG_BASICINFO" and len(master_rows) == 1:
        row = master_rows[0]
        suffix = str(row.get("SECUCODE", "")).split(".")
        listed = _day(row.get("LISTING_DATE"))
        valid_master = (len(suffix) == 2 and suffix[0] == code and suffix[1] == c.get("exchange") and suffix[1] in {"SH", "SZ", "BJ"}
                        and row.get("SECURITY_TYPE") == "A股" and row.get("LISTING_STATE") == "0"
                        and row.get("BOARD_NAME_2LEVEL") == c.get("industry") and listed and listed <= cutoff)
        if valid_master:
            ref.update(issuer_id="eastmoney_A_issuer:" + code, security_id=row["SECUCODE"], market=suffix[1],
                       quote_currency="CNY", financial_currency=c.get("currency"),
                       security_binding={"source_id": master["source"]["id"], "sha256": master["source"]["sha256"],
                                         "raw_field": "SECUCODE", "raw_value": row["SECUCODE"], "universe": "listed_mainland_A_shares",
                                         "currency_basis": "supplier_mainland_A_share_yuan_schema", "automatic_A_H_matching": False})
    if not valid_master:ref["adapter_gaps"].append(_gap("price_listed_A_identity_unresolved"))
    table = loaded.get(c.get("quote_source_id")) if isinstance(c.get("quote_source_id"), str) else None
    quote_date = _day(c.get("valuation_as_of"))
    matches = [r for r in table["rows"].get(code, []) if _day(r.get("TRADE_DATE")) == quote_date and quote_date] if table else []
    valid_quote = table and recovery._report(table["source"]) == "RPT_VALUEANALYSIS_DET" and len(matches) == 1
    if valid_quote:
        row, source = matches[0], table["source"]
        ref["observed_at"] = source["fetched_at"]
        for key, raw_field in RAW_FIELDS.items():
            bound = _obj(_obj(c.get("field_sources")).get(key))
            present = raw_field in row
            raw, canonical = _num(row.get(raw_field)), _num(c.get(key))
            match = present and raw is not None and canonical is not None and raw == canonical
            metadata = bound.get("source_id") == source["id"] and bound.get("field") == raw_field
            source_ref = {"source_id": source["id"], "raw_field": raw_field, "company_code": code,
                          "valuation_as_of": quote_date.isoformat(), "observed_at": source["fetched_at"], "sha256": source["sha256"],
                          "url": source["url"], "raw_hash_rechecked": True, "raw_value_matches": bool(match and metadata)}
            ref["sources"][key] = source_ref
            if match and metadata:ref[key] = _text(raw)
            else:
                ref["adapter_gaps"].append(_gap("price_field_unbound_or_conflicting", source["id"], key))
                # Raw observation remains visible as unverified legacy input, never
                # made into a reference by the enclosing quote's valid hash.
        ref["supplier_reference_contract"] = "eastmoney-daily-ratios-1.0" if valid_master else None
    else:ref["adapter_gaps"].append(_gap("unique_quote_row_unavailable", c.get("quote_source_id")))
    # A provided BPS is a warning cross-check, never a reconstructed denominator.
    bound = _obj(_obj(c.get("field_sources")).get("bvps"));table = loaded.get(bound.get("source_id")) if isinstance(bound.get("source_id"), str) else None
    period = _day(c.get("report_date"))
    rows = [r for r in table["rows"].get(code, []) if _day(r.get("REPORT_DATE", r.get("REPORTDATE"))) == period and period] if table else []
    visible = [r for r in rows if _day(r.get("NOTICE_DATE")) and _day(r["NOTICE_DATE"]) <= cutoff and
               (not r.get("UPDATE_DATE") or _day(r["UPDATE_DATE"]) and _day(r["UPDATE_DATE"]) <= cutoff)]
    if len(visible) == 1 and bound.get("field") == "BPS" and _num(visible[0].get("BPS")) == _num(c.get("bvps")) and _num(c.get("bvps")) is not None:
        ref["book_value_reference"] = {"value": _text(_num(c["bvps"])), "source_id": bound["source_id"], "raw_field": "BPS",
                                       "report_date": period.isoformat(), "status": "supplier_per_share_reference_only"}
    return ref


def _statement_metadata_issues(row, period, report_type):
    """Supplier defaults never override an explicit conflicting raw qualifier."""
    issues = []
    if row.get("CURRENCY") != "CNY":issues.append("currency_not_CNY")
    if any(key in row and row[key] not in ("consolidated", "合并") for key in ("SCOPE", "STATEMENT_SCOPE")):
        issues.append("statement_scope_not_consolidated")
    if any(key in row and row[key] not in ("元", "人民币元", "CNY") for key in ("UNIT", "AMOUNT_UNIT")):
        issues.append("amount_unit_not_yuan")
    if report_type == "RPT_F10_FINANCE_GINCOME":
        allowed = ("year_to_date", "累计") + (("annual", "全年") if (period.month, period.day) == (12, 31) else ())
        if any(key in row and row[key] not in allowed for key in ("FLOW_BASIS", "flow_basis")):
            issues.append("profit_flow_not_year_to_date")
        if "PERIOD_START" in row and _day(row["PERIOD_START"]) != date(period.year, 1, 1):
            issues.append("profit_period_start_not_year_start")
    return issues


def _statement_fact(statements, period, field, kinds, cutoff, quote_date):
    choices = []
    for statement in statements:
        if statement.get("report_type") not in kinds:continue
        source = statement["source"]
        if not _day(source.get("fetched_at")) or _day(source["fetched_at"]) > cutoff:continue
        for row in statement.get("rows", []):
            if _day(row.get("REPORT_DATE")) != period:continue
            announced, updated = _day(row.get("NOTICE_DATE")), _day(row.get("UPDATE_DATE"))
            if not announced or announced > quote_date or announced < period or (row.get("UPDATE_DATE") and (not updated or updated > cutoff)):continue
            metadata_issues = _statement_metadata_issues(row, period, statement["report_type"])
            value = None if metadata_issues else _num(row.get(field))
            choices.append({"value": value, "raw_state": "raw_metadata_invalid" if metadata_issues else "absent" if field not in row else "null" if row[field] is None else "invalid" if value is None else "zero" if value == 0 else "reported_value",
                            "source_id": source["id"], "sha256": source["sha256"], "report_type": statement["report_type"], "raw_field": field,
                            "report_date": period.isoformat(), "announced_at": announced.isoformat(), "provider_updated_at": updated.isoformat() if updated else None,
                            "unit_basis": None if metadata_issues else "supplier_F10_CNY_yuan_YTD_or_book_value", "metadata_issues": metadata_issues,
                            "source_url": source.get("url")})
    if not choices:return {"value": None, "status": "not_provided", "source_refs": []}
    newest = max(x["announced_at"] for x in choices)
    choices = [x for x in choices if x["announced_at"] == newest]
    values = {(x["value"], x["raw_state"]) for x in choices}
    if len(values) != 1:return {"value": None, "status": "conflict", "source_refs": [{k: (_text(v) if k == "value" else v) for k, v in x.items()} for x in choices]}
    return {"value": _text(choices[0]["value"]), "status": choices[0]["raw_state"],
            "source_refs": [{k: (_text(v) if k == "value" else v) for k, v in x.items()} for x in choices]}


def _matches_calculation(numerator, denominator, supplier):
    a, b, expected = _num(numerator), _num(denominator), _num(supplier)
    ratio = a / b if a is not None and a > 0 and b is not None and b > 0 else None
    return _text(ratio), (abs(ratio - expected) <= Decimal("0.00000001") if ratio is not None and expected is not None else None)


def diagnostics(company, sources, cache_dir, reference, *, as_of):
    cutoff, quote = _day(as_of), _day(reference.get("valuation_as_of"))
    period = _day(company.get("report_date"))
    if not cutoff or not quote or not period:return {"status": "unavailable", "gaps": ["period_or_quote_date_missing"]}
    if (period.month, period.day) not in {(3, 31), (6, 30), (9, 30), (12, 31)}:
        return {"status": "unavailable", "gaps": ["unsupported_fiscal_period_no_resampling"]}
    recovered = recover_business_statements({"company": company, "sources": sources}, cache_dir)
    statements = recovered.pop("statements")
    income = {"RPT_F10_FINANCE_GINCOME"}
    balance = {"RPT_F10_FINANCE_GBALANCE", "RPT_F10_FINANCE_BBALANCE"}
    current = _statement_fact(statements, period, "PARENT_NETPROFIT", income, cutoff, quote)
    components = [{"operation": "+", "fact": current}]
    start = date(period.year, 1, 1)
    if (period.month, period.day) != (12, 31):
        prior_same = date(period.year - 1, period.month, period.day)
        annual = _statement_fact(statements, date(period.year - 1, 12, 31), "PARENT_NETPROFIT", income, cutoff, quote)
        previous = _statement_fact(statements, prior_same, "PARENT_NETPROFIT", income, cutoff, quote)
        components = [{"operation": "+", "fact": annual}, {"operation": "+", "fact": current}, {"operation": "-", "fact": previous}]
        start = prior_same + timedelta(days=1)
    values = [_num(x["fact"]["value"]) for x in components]
    ttm = sum((v if x["operation"] == "+" else -v for x, v in zip(components, values)), Decimal(0)) if all(v is not None for v in values) else None
    cap_source = _obj(_obj(reference.get("sources")).get("market_cap"))
    cap = reference.get("market_cap") if cap_source.get("raw_value_matches") is True else None
    pe_source = _obj(_obj(reference.get("sources")).get("pe_ttm"))
    pb_source = _obj(_obj(reference.get("sources")).get("pb"))
    pe_reference = reference.get("pe_ttm") if pe_source.get("raw_value_matches") is True else None
    pb_reference = reference.get("pb") if pb_source.get("raw_value_matches") is True else None
    pe, pe_match = _matches_calculation(cap, ttm, pe_reference)
    parent = _statement_fact(statements, period, "TOTAL_PARENT_EQUITY", balance, cutoff, quote)
    other = _statement_fact(statements, period, "OTHER_EQUITY_TOOL", balance, cutoff, quote)
    pref = _statement_fact(statements, period, "PREFERRED_SHARES", balance, cutoff, quote)
    perp = _statement_fact(statements, period, "PERPETUAL_BOND", balance, cutoff, quote)
    raw_ratio, raw_match = _matches_calculation(cap, parent["value"], pb_reference)
    candidates = [{"basis": "reported_parent_equity", "value": parent["value"], "ratio": raw_ratio, "matches_supplier": raw_match,
                   "ordinary_common_equity_certified": False, "source_refs": parent["source_refs"]}]
    if _num(parent["value"]) is not None and _num(other["value"]) is not None:
        adjusted = _num(parent["value"]) - _num(other["value"])
        adjusted_ratio, matched = _matches_calculation(cap, adjusted, pb_reference)
        candidates.append({"basis": "parent_equity_less_reported_other_equity_total_once", "value": _text(adjusted), "ratio": adjusted_ratio,
                           "matches_supplier": matched, "ordinary_common_equity_certified": False, "source_refs": parent["source_refs"] + other["source_refs"]})
    return {"status": "numeric_consistency_only", "company_code": company.get("code"), "report_date": period.isoformat(), "as_of": cutoff.isoformat(),
            "ttm_profit": {"value": _text(ttm), "status": "calculated" if ttm is not None else "insufficient",
             "period_start": start.isoformat(), "period_end": period.isoformat(), "components": components, "ratio": pe, "matches_supplier": pe_match},
            "pb_candidates": candidates, "equity_components": {"parent_equity": parent, "other_equity_total": other, "preferred_shares": pref, "perpetual_bonds": perp},
            "market_cap": cap, "market_cap_source": deepcopy(cap_source), "recovery_status": recovered["status"],
            "limits": ["供应商当前缓存版本的数值一致性，不是官方语义或历史PIT核验。",
                       "OTHER_EQUITY_TOOL为总项，优先股和永续债可能是组成，不重复扣除；null和缺字段不填0。",
                       "原归母权益或扣其他权益后与PB吻合，也不自动认证普通股权益附注完整；银行仍走专项。"]}


def _current_industry_context(report, company, current, supplied, master_loaded, cache_dir, original_sources, cutoff):
    """Current classification plus original dated earnings, never a saved-report edit."""
    old = _obj(report.get("industry_profile"))
    financial_day = _day(company.get("as_of"))
    context = {"version": "price-industry-context-1.0", "status": "unavailable", "company_code": company.get("code"),
        "classification_as_of": cutoff.isoformat(), "observed_at": None, "financial_as_of": company.get("as_of"),
        "previous_report": {"model": _obj(old.get("classification")).get("model"), "as_of": old.get("as_of")},
        "profile": {}, "source_ref": {}, "historical_pit_usable": False, "modifies_saved_report": False,
        "use": "current_price_applicability_only", "gaps": []}
    gaps = context["gaps"]
    if not financial_day or financial_day > cutoff:
        gaps.append(_gap("saved_financial_cutoff_missing_or_future"))
    # Original statements are the only earnings inputs. Today's market profits
    # and its report period cannot repair or replace saved research evidence.
    visible_sources = []
    for source in _rows(original_sources):
        fetched = _day(source.get("fetched_at"))
        if recovery._report(source) in recovery.SUPPORTED_REPORTS and (not financial_day or not fetched or fetched > financial_day):
            gaps.append(_gap("saved_financial_source_not_visible", source.get("id")))
        else:
            visible_sources.append(source)
    bundle = {"company": deepcopy(company), "sources": visible_sources}
    bundle.update(prepare_industry_bundle(bundle, cache_dir, as_of=financial_day.isoformat() if financial_day else None))
    policy = bundle["industry_profile_input"]
    original_profile = build_industry_view(bundle, as_of=financial_day.isoformat() if financial_day else None)
    if original_profile.get("earnings_basis") != old.get("earnings_basis"):
        gaps.append(_gap("saved_earnings_recovery_mismatch"))
    if any(g.get("code") in {"classification_conflict_or_publication_unknown", "classification_statement_type_conflict"}
           for g in _rows(_obj(bundle.get("industry_data_recovery")).get("gaps"))):
        gaps.append(_gap("saved_statement_classification_conflict_unresolved"))
    flags = _obj(report.get("summary")).get("flags")
    if not isinstance(flags, list) or any(f.get("code") in {"source_conflict", "conflicting_period"} for f in _rows(flags)):
        gaps.append(_gap("saved_source_conflict_or_flags_unresolved"))
    # Missing historical master evidence remains a disclosed coverage gap, but
    # retained evidence must not contradict the saved security's identity.
    old_sid = company.get("universe_source_id")
    old_manifests = [s for s in _rows(original_sources) if s.get("id") == old_sid] if isinstance(old_sid, str) else []
    if old_manifests:
        old_loaded, _ = _load_sources(old_manifests, cache_dir, financial_day or cutoff)
        old_master = old_loaded.get(old_sid)
        old_matches = old_master["rows"].get(company.get("code"), []) if old_master else []
        old_row = old_matches[0] if len(old_matches) == 1 else {}
        if not (old_master and recovery._report(old_master["source"]) == "RPT_F10_ORG_BASICINFO"
                and company.get("exchange") in {"SH", "SZ", "BJ"}
                and old_row.get("SECUCODE") == str(company.get("code")) + "." + company["exchange"]
                and old_row.get("SECURITY_TYPE") == "A股"):
            gaps.append(_gap("saved_retained_master_identity_conflict", old_sid))
    current, supplied = _obj(current), _obj(supplied)
    current_policy = _obj(supplied.get("industry_profile_input"))
    classification = _obj(current_policy.get("industry_classification"))
    sid = classification.get("source_id")
    master = master_loaded.get(sid) if isinstance(sid, str) else None
    matches = master["rows"].get(company.get("code"), []) if master else []
    row = matches[0] if len(matches) == 1 else {}
    observed = _day(classification.get("observed_at"))
    current_day = _day(current.get("as_of"))
    source = master["source"] if master else {}
    label = row.get("BOARD_NAME_2LEVEL")
    mapped = next((model for model, labels in CURRENT_SECTORS.items() if isinstance(label, str) and label in labels), "unknown")
    org = row.get("ORG_TYPE")
    org_conflict = isinstance(org, str) and org in FINANCIAL_TYPES and mapped not in {FINANCIAL_TYPES[org], "financial_unresolved"}
    listed = _day(row.get("LISTING_DATE"))
    recovery_meta = _obj(supplied.get("industry_data_recovery"))
    identity_ok = (current.get("code") == company.get("code") and current.get("exchange") == company.get("exchange")
        and company.get("exchange") in {"SH", "SZ", "BJ"}
        and row.get("SECUCODE") == str(company.get("code")) + "." + str(company.get("exchange"))
        and row.get("SECURITY_TYPE") == "A股" and row.get("LISTING_STATE") == "0"
        and current.get("universe_source_id") == sid and current.get("industry") == label)
    binding_ok = (supplied.get("industry_adapter_version") == INDUSTRY_ADAPTER_VERSION
        and current_policy.get("code") == company.get("code")
        and _day(current_policy.get("as_of")) == current_day and current_day is not None and current_day <= cutoff
        and current_policy.get("report_date") == current.get("report_date")
        and classification.get("temporal_basis") == "supplier_current_snapshot"
        and classification.get("mapping_version") == CURRENT_MAPPING_VERSION
        and classification.get("report_type") == "RPT_F10_ORG_BASICINFO"
        and recovery._report(source) == "RPT_F10_ORG_BASICINFO"
        and classification.get("raw_field") == "BOARD_NAME_2LEVEL" and classification.get("raw_value") == label
        and classification.get("sha256") == source.get("sha256") and classification.get("source_url") == source.get("url")
        and classification.get("supplier_org_type") == org and classification.get("model") == mapped and mapped != "unknown"
        and not org_conflict and (mapped != "general" or org == "通用")
        and _obj(recovery_meta.get("coverage")).get("raw_hashes_rechecked") is True
        and any(r.get("source_id") == sid and r.get("sha256") == source.get("sha256")
                and r.get("report_type") == "RPT_F10_ORG_BASICINFO" and r.get("status") == "verified"
                for r in _rows(recovery_meta.get("sources"))))
    time_ok = (observed is not None and current_day is not None and observed <= current_day <= cutoff
        and classification.get("observed_at") in (master["observed_at_candidates"] if master else [])
        and listed is not None and listed <= observed)
    if not identity_ok:gaps.append(_gap("current_industry_security_unbound", sid))
    if not binding_ok:gaps.append(_gap("current_industry_original_unbound", sid))
    if not time_ok:gaps.append(_gap("current_industry_observation_unknown_or_future", sid))
    original_model = _obj(policy.get("industry_classification")).get("model")
    if original_model in {"bank", "insurance", "securities"} and original_model != mapped:
        gaps.append(_gap("current_industry_saved_statement_type_conflict", sid))
    if identity_ok and binding_ok and time_ok:
        context["observed_at"] = classification["observed_at"]
        context["source_ref"] = {"source_id": sid, "sha256": source["sha256"], "url": source["url"],
            "raw_field": "BOARD_NAME_2LEVEL", "raw_value": label, "observed_at": classification["observed_at"]}
    policy["as_of"] = cutoff.isoformat()
    policy["industry_classification"] = deepcopy(classification) if not gaps else {"model": "unknown"}
    if not gaps:
        bundle["industry_data_recovery"].update(classification_basis="current_supplier_classification_saved_financial_cutoff",
            classification_as_of=cutoff.isoformat(), financial_as_of=company.get("as_of"),
            current_classification_source_ref=deepcopy(context["source_ref"]))
        bundle["industry_data_recovery"]["gaps"] = [g for g in bundle["industry_data_recovery"]["gaps"]
            if g.get("code") != "dated_industry_classification_unavailable"]
    profile = build_industry_view(bundle, as_of=cutoff.isoformat(), purpose="current_research")
    if context["source_ref"]:
        profile["classification"]["observed_supplier_label"] = {"industry": label, "financial_type": org,
            "observed_at": context["observed_at"], "announcement_date": None,
            "use": "current_label_only_not_historical_classification"}
    context["profile"] = profile
    context["status"] = "available" if not gaps else "unavailable"
    return context


def prepare_price_panel(report, company, snapshot, sources, cache_dir, industry_inputs, *, as_of, original_sources=None):
    """Return panel only; every caller-owned report/snapshot remains unchanged."""
    cutoff = _day(as_of)
    if cutoff is None:raise ValueError("explicit as_of required")
    code = company.get("code")
    current_rows = [c for c in _rows(snapshot.get("companies")) if c.get("code") == code]
    current = current_rows[0] if len(current_rows) == 1 else {}
    original_sources = original_sources if isinstance(original_sources, list) else sources
    current_sid = current.get("universe_source_id")
    master_loaded, _ = _load_sources([s for s in _rows(snapshot.get("sources")) if s.get("id") == current_sid], cache_dir, cutoff)
    context = _current_industry_context(report, company, current, _obj(industry_inputs).get(code), master_loaded,
                                        cache_dir, original_sources, cutoff)
    own_company = deepcopy(company)
    if context["status"] == "available":
        own_company.update(industry=current["industry"], universe_source_id=current_sid)
    peers = [deepcopy(c) for c in _rows(snapshot.get("companies")) if c.get("code") != code and c.get("industry") == own_company.get("industry")
             and c.get("exchange") == company.get("exchange") and c.get("report_date") == company.get("report_date")]
    needed = set()
    master_ids = {c.get("universe_source_id") for c in [own_company] + peers if isinstance(c.get("universe_source_id"), str)}
    for c in [own_company] + peers:
        needed.update(x for x in (c.get("quote_source_id"), c.get("universe_source_id")) if isinstance(x, str))
        b = _obj(_obj(c.get("field_sources")).get("bvps"))
        if isinstance(b.get("source_id"), str):needed.add(b["source_id"])
    # Master identity belongs to the explicitly current snapshot. A request ID
    # may recur across days with different bytes; do not mix its old manifest.
    manifests = [s for s in _rows(sources) if s.get("id") in needed and s.get("id") not in master_ids]
    manifests += [s for s in _rows(snapshot.get("sources")) if s.get("id") in needed]
    loaded, audit = _load_sources(manifests, cache_dir, cutoff)
    own = _reference(own_company, context["profile"], loaded, cutoff)
    adapted = []
    for peer in peers:
        if peer.get("code") in industry_inputs:peer.update(deepcopy(industry_inputs[peer["code"]]))
        bundle = {"company": peer, **{k: peer[k] for k in ("industry_adapter_version", "industry_profile_input", "industry_data_recovery") if k in peer}}
        p = build_industry_view(bundle, as_of=peer.get("as_of"), purpose="current_research")
        adapted.append(_reference(peer, p, loaded, cutoff))
    own["recalculation_diagnostics"] = diagnostics(company, original_sources, cache_dir, own, as_of=as_of)
    result = build_price_quality_panel(report, own, adapted, as_of=as_of, research_purpose="current_research", current_industry_context=context)
    result["data_recovery"] = {**audit, "mode": "read_only_supplier_raw", "candidate_peers": len(peers), "original_quote_gaps": own["adapter_gaps"],
                               "missing_originals_fetched": False, "official_numbers_verified": 0}
    result["price_condition"]["supplier_definition"] = {"pe_ttm": "RPT_VALUEANALYSIS_DET.PE_TTM", "pb": "RPT_VALUEANALYSIS_DET.PB_MRQ",
                                                       "level": "explicit_supplier_metric_not_independent_methodology_certification"}
    return result
