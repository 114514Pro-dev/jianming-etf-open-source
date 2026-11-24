"""Source-bound business/capital observations. Pure: no I/O, calls, or score.

Supplier statements are not automatically reconciled to company PDF values.
Gross-margin range is descriptive; it is not proof of durable competition.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math

VERSION = BUSINESS_CAPITAL_VERSION = "business-capital-1.0"
# Currency amounts use the same F10 yuan contract as the existing data adapter.
# Share capital is an amount, not a share count. Mainfin TOTAL_SHARE is excluded.
MAPS = {
    "GINCOME": {
        "OPERATE_INCOME": ("revenue", "营业收入", "CNY"),
        "OPERATE_COST": ("operating_cost", "营业成本", "CNY"),
        "RESEARCH_EXPENSE": ("rd_expense", "当期费用化研发费用", "CNY"),
        "PARENT_NETPROFIT": ("parent_profit", "归母净利润", "CNY"),
        "BASIC_EPS": ("basic_eps", "报告基本每股收益", "CNY/share"),
        "DILUTED_EPS": ("diluted_eps", "报告稀释每股收益", "CNY/share"),
    },
    "GBALANCE": {
        "SHARE_CAPITAL": ("share_capital_amount", "股本账面金额（不是股数）", "CNY"),
        "TREASURY_SHARES": ("treasury_shares_book", "库存股账面金额（不是本期回购金额）", "CNY"),
        "DEVELOP_EXPENSE": ("development_asset", "开发支出期末余额（不是本期资本化投入）", "CNY"),
    },
    "GCASHFLOW": {
        "NETCASH_OPERATE": ("cfo", "经营现金流量净额", "CNY"),
        "CONSTRUCT_LONG_ASSET": ("capex_cash", "购建长期资产支付现金", "CNY"),
        "ASSIGN_DIVIDEND_PORFIT": ("dividend_profit_interest_cash", "分配股利、利润或偿付利息支付现金（合计）", "CNY"),
        "ACCEPT_INVEST_CASH": ("investment_receipts_cash", "吸收投资收到现金（含合并范围）", "CNY"),
        "OBTAIN_SUBSIDIARY_OTHER": ("acquisition_net_cash", "取得子公司及其他营业单位支付现金净额", "CNY"),
        "INVEST_PAY_CASH": ("investment_paid_cash", "投资支付现金（不自动归类为收购）", "CNY"),
        "BUY_SUBSIDIARY_EQUITY": ("subsidiary_equity_cash", "购买子公司权益支付现金（筹资项目）", "CNY"),
    },
}
MAPS["BBALANCE"] = MAPS["GBALANCE"]
MAPS["BCASHFLOW"] = MAPS["GCASHFLOW"]
# Financial statements retain their raw observations, but never receive the
# industrial ratios below. Report types are explicit; no same-name guessing.
for _prefix in ("I", "S"):
    MAPS[_prefix + "BALANCE"] = MAPS["GBALANCE"]
    MAPS[_prefix + "CASHFLOW"] = MAPS["GCASHFLOW"]
ALL_FIELDS = {v[0]: v for mapping in MAPS.values() for v in mapping.values()}
USABLE = {"reported_value", "reported_zero"}


def _date(value):
    if not isinstance(value, str) or len(value) < 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        if len(value) > 10:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.fromisoformat(value[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        num = Decimal(str(value))
        return float(num) if num.is_finite() and math.isfinite(float(num)) else None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def _missing(key):
    _, label, unit = ALL_FIELDS[key]
    return {"key": key, "label": label, "value": None, "unit": unit,
            "status": "not_provided", "verification": "unavailable", "source_refs": []}


def _normalize(row, kind, source):
    period, announced = _date(row.get("REPORT_DATE")), _date(row.get("NOTICE_DATE"))
    updated = _date(row.get("UPDATE_DATE"))
    issues = []
    if not period: issues.append("report_date_unknown")
    if not announced: issues.append("announcement_date_unknown")
    if row.get("UPDATE_DATE") not in (None, "") and not updated: issues.append("provider_update_date_invalid")
    if period and announced and announced < period: issues.append("announcement_before_period_end")
    if row.get("CURRENCY") != "CNY": issues.append("currency_not_confirmed_CNY")
    parameters = source.get("parameters") if isinstance(source.get("parameters"), dict) else {}
    declared = str(parameters.get("reportName", "")).removeprefix("RPT_F10_FINANCE_")
    contracted = declared == kind and kind in MAPS
    # Absence may use this specifically declared supplier schema contract;
    # explicit null never borrows a confirmed scope/unit from another field.
    scope = row.get("SCOPE", row.get("STATEMENT_SCOPE", "consolidated" if contracted else None))
    if scope not in {"consolidated", "合并"}: issues.append("scope_not_consolidated")
    raw_unit = row.get("UNIT", row.get("AMOUNT_UNIT"))
    unit_absent = "UNIT" not in row and "AMOUNT_UNIT" not in row
    factor = 1 if unit_absent and contracted else {"元": 1, "CNY": 1, "人民币元": 1, "万元": 10000, "人民币万元": 10000, "亿元": 100000000}.get(raw_unit) if isinstance(raw_unit, (str, type(None))) else None
    if factor is None: issues.append("amount_unit_unknown")
    if not _known(source.get("id")): issues.append("source_id_missing")
    if declared and declared != kind: issues.append("source_report_type_mismatch")
    if not declared: issues.append("source_report_type_missing")
    balance = kind.endswith("BALANCE")
    flow = row.get("FLOW_BASIS", row.get("flow_basis", "year_to_date" if contracted else None))
    if not balance and flow not in {"year_to_date", "annual", "累计", "全年"}:
        issues.append("flow_not_full_year_cumulative")
    if "REPORT_TYPE" in row and row["REPORT_TYPE"] not in {"年报", "年度报告", "annual"}:
        issues.append("not_annual_statement")
    if not balance and "PERIOD_START" in row and _date(row["PERIOD_START"]) != (period[:4] + "-01-01" if period else None):
        issues.append("noncalendar_or_incomplete_annual_span")
    blocking = set(issues) - {"announcement_date_unknown"}
    cells = {}
    for raw_key, (key, label, unit) in MAPS.get(kind, {}).items():
        if raw_key not in row: continue
        original, number = row[raw_key], _number(row[raw_key])
        value = number if unit == "CNY/share" else number * factor if number is not None and factor is not None else None
        if value is not None and not math.isfinite(value): value = None
        state = "null" if original is None else "invalid" if value is None else "reported_zero" if value == 0 else "reported_value"
        if blocking: value, state = None, "metadata_invalid"
        field_issues = list(issues)
        if unit == "CNY/share" and row.get("EPS_UNIT", "CNY/share" if contracted else None) not in {"CNY/share", "元/股"}:
            value, state = None, "metadata_invalid"
            field_issues.append("per_share_unit_unknown")
        ref = {"source_id": source.get("id"), "report_type": kind, "raw_field": raw_key,
               "report_date": period, "announced_at": announced, "provider_updated_at": updated,
               "raw_value": original if isinstance(original, (int, str, bool, type(None))) or isinstance(original, float) and math.isfinite(original) else "non_json_numeric_or_type",
               "raw_unit": raw_unit if isinstance(raw_unit, (str, type(None))) else "invalid_type",
               "unit_factor": 1 if unit == "CNY/share" else factor,
               "unit_basis": "F10_per_share_field_yuan" if unit == "CNY/share" else "explicit_amount_unit" if raw_unit else "F10_amount_field_yuan",
               "currency": row.get("CURRENCY"), "scope": scope, "flow_basis": "instant" if balance else flow,
               "basis_confirmation": "supplier_schema_not_official_numeric_verification", "url": source.get("url"),
               "raw_file": source.get("raw_file"), "sha256": source.get("sha256")}
        cells[key] = {"key": key, "label": label, "value": value, "unit": unit, "status": state,
                      "report_date": period, "announced_at": announced, "verification": "supplier_only",
                      "issues": field_issues, "source_refs": [ref]}
    return period, announced, updated, cells


def _resolve(candidates):
    known = [c["announced_at"] for c in candidates if c["announced_at"]]
    latest = max(known) if known else None
    selected = [c for c in candidates if c["announced_at"] in {latest, None}]
    usable = [c for c in selected if c["status"] in USABLE]
    # Null from one table cannot erase a numeric fact on the same date, but a
    # later dated null has already displaced all older candidates above.
    invalid = [c for c in selected if c["status"] in {"invalid", "metadata_invalid", "conflict"}]
    evaluated = usable + invalid or selected
    states = {(c["status"], c["value"], c["unit"]) for c in evaluated}
    out = deepcopy(evaluated[0])
    out["source_refs"] = [r for c in selected for r in c["source_refs"]]
    out["superseded_source_refs"] = [r for c in candidates if c not in selected for r in c["source_refs"]]
    if len(states) > 1:
        out.update(value=None, status="conflict", conflicting_values=[c["value"] for c in evaluated])
    if any(c["announced_at"] is None for c in selected):
        out["announced_at"] = None
        out["issues"] = sorted(set(out.get("issues", [])) | {"announcement_date_unknown"})
    return out


def _metric(key, cells, formula, unit="percent", *, specialist=False, positive_denominator=False, nonnegative=()):
    refs = [r for c in cells for r in c["source_refs"]]
    result = {"key": key, "value": None, "unit": unit, "status": "insufficient",
              "periods": sorted({c["report_date"] for c in cells if c.get("report_date")}),
              "verification": "supplier_only", "source_refs": refs}
    if specialist:
        result["status"] = "specialist_required"
    elif any(c["status"] == "conflict" for c in cells):
        result["status"] = "conflict"
    elif all(c["status"] in USABLE for c in cells):
        values = [c["value"] for c in cells]
        if positive_denominator and values[-1] <= 0:
            result["status"] = "nonpositive_denominator"
        elif any(values[i] < 0 for i in nonnegative):
            result["status"] = "negative_component_requires_review"
        else:
            value = formula(values)
            result.update(value=value if math.isfinite(value) else None,
                          status="calculated" if math.isfinite(value) else "invalid_arithmetic")
    return result


def _json_value(value):
    """Keep supplied review text/data JSON-safe without interpreting instructions."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    return str(value)


def _known(value):
    return value is not None and str(value).strip().lower() not in {"", "unknown", "unverified", "none", "null", "n/a", "未知", "待核查"}


def _material_basis(item, code, cutoff, *, require_period=True):
    """Metadata routing only: a matching source does not verify its assertion."""
    issues = []
    period = _date(item.get("report_date"))
    announced = _date(item.get("announced_at"))
    if str(item.get("company_code") or "") != code:
        issues.append("company_unknown_or_mismatch")
    if not _known(item.get("source_id")):
        issues.append("source_id_missing")
    # Routing labels and a document link are not reviewable source text. The
    # caller must retain an excerpt; its source match and meaning remain unverified.
    if not isinstance(item.get("text"), str) or not _known(item["text"]):
        issues.append("source_text_missing_or_invalid")
    if require_period and not period:
        issues.append("report_date_unknown")
    if not announced:
        issues.append("announcement_date_unknown")
    if cutoff and ((announced and announced > cutoff) or (period and period > cutoff)):
        issues.append("future_information")
    if require_period and period and announced and announced < period:
        issues.append("announcement_before_period_end")
    return issues, period, announced


def _evidence_records(items, code, cutoff):
    records = []
    groups = {"company_claims": [], "independent_material": [], "counterevidence": [], "unclassified": []}
    for index, raw in enumerate(items or []):
        item = raw if isinstance(raw, dict) else {"text": str(raw)}
        issues, period, announced = _material_basis(item, code, cutoff)
        origin = item.get("origin")
        # Publisher owned by the issuer cannot become independent because a
        # caller or a passage calls it authoritative or uses a stock-exchange URL.
        relationship = item.get("publisher_relationship")
        if relationship == "issuer" or origin == "issuer_disclosure":
            origin = "issuer_disclosure"
        elif origin == "independent_publication" and relationship == "independent_declared":
            origin = "independent_material"
        else:
            origin = "unclassified"
        perspective = item.get("perspective") if item.get("perspective") in {"support", "challenge", "context"} else "context"
        key = str(item.get("id") or f"review-material-{index + 1}")
        record = {"id": key, "topic": str(item.get("topic") or "unspecified"), "text": str(item.get("text") or ""),
            "origin": origin, "perspective": perspective, "report_date": period, "announced_at": announced,
            "source_ref": {k: _json_value(item.get(k)) for k in ("source_id", "document_id", "source_url", "page", "publisher", "publisher_relationship")},
            "status": "unusable_evidence" if issues else "review_material_only", "issues": issues,
            "verification": "unverified_text", "independent_corroboration": False, "proves_moat": False,
            "source_quote_match_verified": False, "numeric_semantics_verified": False}
        records.append(record)
        group = "company_claims" if origin == "issuer_disclosure" else "independent_material" if origin == "independent_material" else "unclassified"
        # Invalid/future items stay visible as rejected material but do not
        # contribute to any support, independence or counterevidence counts.
        if not issues:
            groups[group].append(key)
            if perspective == "challenge":
                groups["counterevidence"].append(key)
    return records, groups


EVENT_TYPES = {"bonus_issue", "capitalization_issue", "stock_split", "share_consolidation",
               "cash_equity_issue", "repurchase", "cancellation", "cash_dividend", "acquisition"}
NONCASH_SHARE_EVENTS = {"bonus_issue", "capitalization_issue", "stock_split", "share_consolidation", "cancellation"}


def _capital_events(items, code, cutoff, periods):
    """Classify explicitly supplied event metadata; never infer from share growth.

    No cash totals or EPS growth are inferred. Event dates are actual economic
    dates, distinct from proposal fiscal year, report date and publication date.
    """
    results, by_id = [], {}
    for index, raw in enumerate(items or []):
        item = raw if isinstance(raw, dict) else {}
        issues, report_period, announced = _material_basis(item, code, cutoff, require_period=False)
        kind, stage = item.get("event_type"), item.get("event_stage")
        event_date = _date(item.get("event_date"))
        identity = item.get("id")
        if not identity:
            issues.append("event_id_missing")
        if kind not in EVENT_TYPES:
            issues.append("event_type_unclassified")
        if stage not in {"proposed", "approved", "completed"}:
            issues.append("event_stage_unknown")
        if stage == "completed" and not event_date:
            issues.append("actual_event_date_unknown")
        if stage == "completed" and cutoff and event_date and event_date > cutoff:
            issues.append("future_actual_event")
        if stage == "completed" and event_date and announced and event_date > announced:
            issues.append("completed_event_after_announcement")
        before, after = _number(item.get("shares_before")), _number(item.get("shares_after"))
        if any(item.get(key) is not None and _number(item[key]) is None for key in ("shares_before", "shares_after")):
            issues.append("share_count_number_invalid")
        if (before is not None or after is not None) and (item.get("shares_unit") != "shares" or before is None or after is None or before <= 0 or after < 0):
            issues.append("share_count_basis_invalid")
        if before is not None and after is not None:
            if kind in {"share_consolidation", "cancellation"} and after > before:
                issues.append("share_direction_conflicts_with_event")
            if kind in {"bonus_issue", "capitalization_issue", "stock_split"} and after < before:
                issues.append("share_direction_conflicts_with_event")
        cash = _number(item.get("cash_amount"))
        if item.get("cash_amount") is not None and cash is None:
            issues.append("cash_number_invalid")
        if cash is not None and (item.get("cash_unit") != "currency_units" or item.get("currency") not in {"CNY", "HKD", "USD", "EUR", "GBP", "JPY"}):
            issues.append("cash_currency_or_unit_unknown")
        if cash is not None and cash < 0 and kind != "acquisition":
            issues.append("negative_cash_requires_review")
        if cash is not None and cash < 0 and kind == "acquisition" and item.get("cash_basis") != "net_acquisition_cash_paid":
            issues.append("negative_acquisition_consideration_requires_review")
        if kind in NONCASH_SHARE_EVENTS and cash not in (None, 0):
            issues.append("cash_conflicts_with_non_cash_event")
        treatment = "unclassified"
        cash_observation = None
        if not issues and stage != "completed":
            treatment = "proposal_or_authorization_not_realized"
        elif not issues and kind in NONCASH_SHARE_EVENTS:
            treatment = "reported_non_cash_share_change"
        elif not issues and kind == "cash_equity_issue":
            treatment = "reported_cash_financing"
            if item.get("cash_basis") not in {"net_issuance_proceeds", "gross_issuance_proceeds"}:
                issues.append("issuance_cash_basis_unknown")
            elif item.get("scope") != "listed_parent":
                issues.append("issuer_cash_scope_unknown")
            else:
                cash_observation = cash
        elif not issues and kind == "cash_dividend":
            treatment = "reported_common_dividend_payment"
            if item.get("cash_basis") != "ordinary_common_dividend_paid" or item.get("scope") != "listed_parent_common_shareholders":
                issues.append("dividend_not_identified_as_common_cash_paid")
            else:
                cash_observation = cash
        elif not issues and kind == "acquisition":
            treatment = "reported_acquisition_cash_or_consideration"
            if item.get("cash_basis") not in {"net_acquisition_cash_paid", "total_consideration"}:
                issues.append("acquisition_basis_unknown")
            elif item.get("scope") not in {"consolidated", "listed_parent"}:
                issues.append("acquisition_scope_unknown")
            else:
                cash_observation = cash
        elif not issues and kind == "repurchase":
            treatment = "reported_share_repurchase_not_necessarily_cancelled"
            if item.get("cash_basis") != "repurchase_cash_paid" or item.get("scope") != "listed_parent":
                issues.append("repurchase_cash_basis_unknown")
            else:
                cash_observation = cash
        if stage == "completed" and kind not in NONCASH_SHARE_EVENTS and cash is None:
            issues.append("cash_amount_missing")
        economic_period = event_date[:4] + "-12-31" if event_date and stage == "completed" else None
        result = {"id": str(identity or f"unidentified-event-{index + 1}"), "event_type": kind,
            "event_stage": stage, "event_date": event_date, "report_date": report_period, "announced_at": announced,
            "text": item.get("text") if isinstance(item.get("text"), str) else None,
            "scheme_fiscal_year": _json_value(item.get("scheme_fiscal_year")), "economic_annual_period": economic_period,
            "in_fixed_annual_window": economic_period in periods if economic_period else False,
            "subsequent_to_report_period": bool(event_date and report_period and event_date > report_period),
            "status": "unusable_event" if issues else "reported_event_only", "issues": issues,
            "treatment": treatment if not issues else "requires_review", "cash_basis": item.get("cash_basis"),
            "reported_cash_value": cash_observation if not issues else None, "currency": item.get("currency"),
            "cash_unit": item.get("cash_unit"), "scope": item.get("scope"),
            "reported_shares_before": before, "reported_shares_after": after, "shares_unit": item.get("shares_unit"),
            "reported_share_change": after - before if not issues and stage == "completed" and kind in NONCASH_SHARE_EVENTS | {"cash_equity_issue"} and before is not None and after is not None else None,
            "share_change_formula": "shares_after - shares_before; no financing or EPS inference",
            "financing_inferred_from_share_change": False, "dilution_or_per_share_value_effect": "not_assessed",
            "verification": "source_metadata_only_unverified_semantics", "numeric_semantics_verified": False,
            "source_quote_match_verified": False,
            "source_ref": {k: _json_value(item.get(k)) for k in ("source_id", "source_url", "document_id", "page")}}
        results.append(result)
        if identity:
            by_id.setdefault(str(identity), []).append(result)
    for group in by_id.values():
        if len(group) > 1:
            # Conservative duplicate handling: no repeated cash totals, and
            # unresolved revised/duplicate events cannot be treated as payments.
            for result in group:
                result.update(status="duplicate_event_requires_review", treatment="requires_review", reported_cash_value=None,
                              reported_share_change=None)
                result["issues"].append("duplicate_event_id")
    return results


def analyze_business_capital(company, statements, *, as_of=None, qualitative_evidence=None, capital_events=None, industry_model=None):
    """Return fixed 3/5-year financial observations without moat/allocation rating.

    statements: [{report_type, source:{id, parameters, url, raw_file, sha256}, rows}].
    as_of filters unknown/future announcements and later provider updates. Even
    then this is disclosure-metadata filtering, not a certified PIT archive.
    qualitative_evidence distinguishes company claims, independent material and
    challenges, always pending semantic verification. capital_events requires
    explicit source/entity/type/stage/economic-date metadata; share growth never
    proves financing. No investment/capital-allocation quality score is produced.
    """
    company, statements = deepcopy(company), deepcopy(statements)
    cutoff = _date(as_of)
    if as_of is not None and (cutoff is None or as_of != cutoff): raise ValueError("as_of must be YYYY-MM-DD")
    latest_period = _date(company.get("report_date"))
    if cutoff:
        anchor = int(cutoff[:4]) - 1
    elif latest_period:
        anchor = int(latest_period[:4]) - (not latest_period.endswith("12-31"))
    else:
        raise ValueError("company.report_date or as_of is required for a fixed annual window")
    code = str(company.get("code") or company.get("security_code") or "")
    if not code: raise ValueError("company code is required")
    labels = [str(company.get(k) or "").lower() for k in ("industry", "financial_type", "industry_model")]
    labels.append(str(industry_model or "").lower())
    for statement in statements:
        kind = str(statement.get("report_type", "")).removeprefix("RPT_F10_FINANCE_")
        own_rows = [r for r in statement.get("rows", []) if str(r.get("SECURITY_CODE") or "") == code]
        if cutoff:
            own_rows = [r for r in own_rows if _date(r.get("NOTICE_DATE")) and _date(r["NOTICE_DATE"]) <= cutoff]
        if own_rows and kind in {"BBALANCE", "BCASHFLOW", "IBALANCE", "ICASHFLOW", "SBALANCE", "SCASHFLOW"}:
            labels.append("finance")
        labels.extend(str(r.get("ORG_TYPE") or "").lower() for r in own_rows)
    specialist_terms = {"银行", "商业银行", "银行业", "保险", "证券", "证券公司", "金融", "金融业", "多元金融", "非银金融", "信托", "金融服务",
                        "房地产", "房地产开发", "地产开发", "bank", "banks", "insurance", "securities", "finance", "financial_unresolved", "property", "real estate"}
    specialist = bool(set(labels) & specialist_terms)
    periods = [f"{year}-12-31" for year in range(anchor - 4, anchor + 1)]
    candidates, excluded, observed_types, raw_count = {}, [], set(), 0
    for statement in statements:
        kind = str(statement.get("report_type", "")).removeprefix("RPT_F10_FINANCE_")
        observed_types.add(kind)
        raw_count += len(statement.get("rows", []))
        if kind not in MAPS:
            excluded.append({"reason": "unsupported_statement_type", "report_type": kind, "source_id": statement.get("source", {}).get("id")})
            continue
        for row in statement.get("rows", []):
            if str(row.get("SECURITY_CODE") or "") != code:
                excluded.append({"reason": "other_company", "code": row.get("SECURITY_CODE")})
                continue
            period, announced, updated, cells = _normalize(row, kind, statement.get("source", {}))
            if period not in periods:
                continue
            reason = "announcement_unknown_at_cutoff" if cutoff and not announced else "future_announcement" if cutoff and announced > cutoff else "provider_revision_after_cutoff" if cutoff and updated and updated > cutoff else None
            if reason:
                excluded.append({"reason": reason, "report_date": period, "source_id": statement.get("source", {}).get("id")})
                continue
            for key, cell in cells.items(): candidates.setdefault((period, key), []).append(cell)
    years = []
    for period in periods:
        fields = {key: _resolve(candidates[period, key]) if (period, key) in candidates else _missing(key) for key in ALL_FIELDS}
        metric = lambda key, names, fn, **kw: _metric(key, [fields[name] for name in names], fn, **kw)
        metrics = [metric("gross_margin", ["operating_cost", "revenue"], lambda v: (v[1]-v[0])/v[1]*100, specialist=specialist, positive_denominator=True, nonnegative=(0,)),
                   metric("rd_expense_to_revenue", ["rd_expense", "revenue"], lambda v: v[0]/v[1]*100, specialist=specialist, positive_denominator=True, nonnegative=(0,)),
                   metric("capex_to_cfo", ["capex_cash", "cfo"], lambda v: v[0]/v[1]*100, specialist=specialist, positive_denominator=True, nonnegative=(0,)),
                   metric("simplified_cash_surplus", ["cfo", "capex_cash"], lambda v: v[0]-v[1], unit="CNY", specialist=specialist, nonnegative=(1,))]
        for item in metrics:
            item["formula"] = {"gross_margin": "(revenue - operating_cost) / revenue * 100",
                               "rd_expense_to_revenue": "rd_expense / revenue * 100",
                               "capex_to_cfo": "capex_cash / cfo * 100",
                               "simplified_cash_surplus": "cfo - capex_cash"}[item["key"]]
        years.append({"report_date": period, "fields": fields, "metrics": metrics,
                      "coverage": {"reported_fields": sum(c["status"] in USABLE for c in fields.values()), "total_fields": len(fields)}})
    windows = []
    for width in (3, 5):
        rows = years[-width:]
        margins = [next(m for m in r["metrics"] if m["key"] == "gross_margin") for r in rows]
        valid = [m for m in margins if m["status"] == "calculated"]
        metrics = [{"key": "gross_margin_range", "unit": "percentage_points", "value": max(m["value"] for m in valid)-min(m["value"] for m in valid) if len(valid) == width else None,
                    "status": "calculated" if len(valid) == width else "specialist_required" if specialist else "insufficient",
                    "formula": "max(annual gross margins) - min(annual gross margins)", "periods": [r["report_date"] for r in rows],
                    "source_refs": [ref for m in margins for ref in m["source_refs"]], "verification": "supplier_only"}]
        for field in ("rd_expense", "capex_cash", "parent_profit"):
            cells = [r["fields"][field] for r in rows]
            item = _metric("sum_"+field, cells, sum, "CNY", nonnegative=range(len(cells)) if field in {"rd_expense", "capex_cash"} else ())
            item["formula"] = "sum(" + field + " for every fixed-window annual period)"
            metrics.append(item)
        windows.append({"years": width, "periods": [r["report_date"] for r in rows], "metrics": metrics,
                        "complete_gross_margin_years": len(valid), "interpretation": "仅描述观测区间；毛利率范围小不等于优势可持续，支出规模不等于投资回报。"})
    evidence, evidence_groups = _evidence_records(qualitative_evidence, code, cutoff)
    events = _capital_events(capital_events, code, cutoff, periods)
    gaps = [
        {"key": "competitive_advantage", "reason": "未有经主体、期间、口径核验的独立份额、留存、定价或同行证据；不形成护城河判断。"},
        {"key": "rd_outcomes", "reason": "研发费用不是研发总投入；缺资本化当期流量、成果收入及投入产出归因。"},
        {"key": "capex_outcomes", "reason": "购建现金不区分维持与扩张；缺投产进度、产能利用率和增量回报归因。"},
        {"key": "dividend_payout", "reason": "供应商现金流项目合并股利、利润和利息；不能计算普通股现金分红或分红率。"},
        {"key": "repurchase_issuance", "reason": "库存股是账面存量、吸收投资是合并现金；缺普通股回购、注销、发行日期与实际股数。"},
        {"key": "per_share_results", "reason": "并列报告基本/稀释EPS与归母利润；拆并股、送转及追溯调整基准未核实，不计算跨年EPS增速。MAINFINADATA总股数不作历史股数。"},
        {"key": "acquisition_outcomes", "reason": "收购现金不证明整合成功；缺对价、商誉、被购方后续利润和承诺兑现证据。"},
        {"key": "customer_supplier_concentration", "reason": "12张结构化报表没有客户或供应商集中度及留存字段，正文需核对适用勾选和表格语境。"},
    ]
    return {"version": VERSION, "status": "specialist_required" if specialist else "observations_only",
            "label": "生意与资金使用：财务观测及待核查证据", "code": code, "anchor_year": anchor,
            "years": years, "windows": windows, "evidence": evidence, "evidence_groups": evidence_groups,
            "capital_events": events, "gaps": gaps,
            "competitive_advantage": {"status": "insufficient", "rating": None, "proven": False},
            "capital_allocation_quality": {"status": "insufficient", "rating": None},
            "coverage": {"raw_statement_rows": raw_count, "statement_types": sorted(observed_types), "official_values_verified": 0,
                         "reviewable_evidence": sum(e["status"] == "review_material_only" for e in evidence),
                         "rejected_evidence": sum(e["status"] != "review_material_only" for e in evidence),
                         "reported_events": sum(e["status"] == "reported_event_only" for e in events)},
            "excluded_records": excluded, "as_of": cutoff,
            "temporal_validation": "disclosure_metadata_filter_only_not_certified_PIT",
            "limitations": ["公司自述、独立来源待核查材料和反证分别保留；来源关系标签没有经过本函数外部核验。",
                "关键词、PDF链接和元数据匹配不构成原文/数字语义核验。", "毛利率、研发费用、EPS和支出规模不证明护城河或良好资本配置。",
                "缺少元数据时不自动给高分；无同行基准、无总分、无买卖判断。",
                "供应商历史值可能后续修订；公告日过滤不等于拥有当时冻结原件。",
                "资本事件按明确实际发生日归属；送转/拆并股不推断现金融资，方案年度不等于现金支付年度。"]}
