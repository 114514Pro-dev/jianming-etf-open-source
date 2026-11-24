"""Pure mapping of explicit Eastmoney F10 consolidated statement records.

No network, file reads, implicit model calls, account writes or mutation. The
normalizer returns an isolated `fields` mapping; it MUST NOT overwrite existing
cash/scalar fields used by the original six-indicator screening engine. Use
enrich_debt_bundle only for the input of build_debt_governance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re

ADAPTER_VERSION = "debt-data-1.0"
BALANCE_MAP = {
    "SHORT_LOAN": "short_borrowings",
    "LONG_LOAN": "long_borrowings_noncurrent",
    "BOND_PAYABLE": "bonds_payable_noncurrent",
    "SHORT_BOND_PAYABLE": "short_bonds_payable",
    "NONCURRENT_LIAB_1YEAR": "current_portion_noncurrent_liabilities",
    "LEASE_LIAB": "lease_liabilities_noncurrent",
    "MONETARYFUNDS": "cash",
    "OPINION_TYPE": "audit_opinion_reported",
}
INCOME_MAP = {
    "FE_INTEREST_EXPENSE": "interest_expense_financing",
    "FE_INTEREST_INCOME": "interest_income_financing",
    "FINANCE_EXPENSE": "finance_costs_net",
    "TOTAL_PROFIT": "profit_before_tax",
    "OPINION_TYPE": "audit_opinion_reported",
}
CASHFLOW_MAP = {"OPINION_TYPE": "audit_opinion_reported"}
MAPPINGS = {"MAINFINADATA": {}}
for prefix in "GBIS":
    MAPPINGS[prefix + "BALANCE"] = BALANCE_MAP
    MAPPINGS[prefix + "CASHFLOW"] = CASHFLOW_MAP
    MAPPINGS[prefix + "INCOME"] = INCOME_MAP


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def _report_type(value):
    text = str(value or "").upper()
    return text.removeprefix("RPT_F10_FINANCE_")


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and math.isfinite(float(number)) else None
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None


def _safe_raw(value):
    # Exact raw JSON scalar is retained wherever JSON can represent it. Invalid
    # non-finite/compound inputs are represented explicitly instead of emitting NaN.
    if isinstance(value, float) and not math.isfinite(value):
        return {"unrepresentable_numeric": str(value)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"unexpected_type": type(value).__name__, "representation": str(value)[:200]}


def normalize_debt_record(raw_record, source_id, report_type, source_metadata=None):
    """Map one explicitly identified raw statement to isolated fact objects.

Known F10 amount fields have endpoint units of CNY yuan when raw UNIT is absent.
An explicit recognized Chinese amount unit is normalized with its factor recorded;
unknown units/currencies are retained but blocked. NOTICE_DATE is disclosure time;
UPDATE_DATE is separately retained and is never substituted for announcement time.
"""
    raw = deepcopy(raw_record) if isinstance(raw_record, dict) else {}
    meta = deepcopy(source_metadata) if isinstance(source_metadata, dict) else {}
    kind = _report_type(report_type)
    code = str(raw.get("SECURITY_CODE") or "")
    period, announced = _date(raw.get("REPORT_DATE")), _date(raw.get("NOTICE_DATE"))
    currency = raw.get("CURRENCY")
    problems = []
    if not re.fullmatch(r"\d{6}", code):
        problems.append("invalid_security_code")
    if not source_id or not isinstance(source_id, str):
        problems.append("source_id_missing")
    if not period:
        problems.append("report_date_missing_or_invalid")
    if not announced:
        problems.append("announcement_date_missing_or_invalid")
    if period and announced and announced < period:
        problems.append("announcement_before_report_end")
    if kind not in MAPPINGS:
        problems.append("unsupported_report_type")
    parameters = meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {}
    source_kind = _report_type(meta.get("report_type") or parameters.get("reportName"))
    if source_kind and source_kind != kind:
        problems.append("source_report_type_mismatch")
    if meta.get("id") and meta["id"] != source_id:
        problems.append("source_id_mismatch")
    if currency != "CNY":
        problems.append("currency_not_confirmed_CNY")
    raw_scope = raw.get("SCOPE") or raw.get("STATEMENT_SCOPE")
    scope = "consolidated"
    if raw_scope is not None and str(raw_scope) not in {"consolidated", "合并"}:
        scope = str(raw_scope)
        problems.append("scope_not_consolidated")
    raw_unit = raw.get("UNIT", raw.get("AMOUNT_UNIT"))
    factors = {None: Decimal(1), "": Decimal(1), "CNY": Decimal(1), "元": Decimal(1), "人民币元": Decimal(1), "万元": Decimal(10000), "人民币万元": Decimal(10000), "亿元": Decimal(100000000)}
    factor = factors.get(raw_unit) if isinstance(raw_unit, (str, type(None))) else None
    if factor is None:
        problems.append("unsupported_amount_unit")
    blocking = {"invalid_security_code", "source_id_missing", "report_date_missing_or_invalid", "source_report_type_mismatch", "source_id_mismatch", "unsupported_report_type", "scope_not_consolidated", "currency_not_confirmed_CNY", "unsupported_amount_unit", "announcement_before_report_end"}
    metadata_blocked = bool(set(problems) & blocking)
    mapped, states = {}, {}
    mapping = MAPPINGS.get(kind, {})
    for source_key, canonical in mapping.items():
        if source_key not in raw:
            states[canonical] = {"state": "not_provided", "source_key": source_key, "present": False}
            continue
        original = raw[source_key]
        opinion = canonical == "audit_opinion_reported"
        number = None if opinion else _decimal(original)
        if original is None:
            state, value = "null", None
        elif opinion:
            value = original.strip() if isinstance(original, str) else None
            state = "reported_value" if value else "invalid"
        elif number is None:
            state, value = "invalid", None
        else:
            converted = number * factor if factor is not None else None
            value = float(converted) if converted is not None and math.isfinite(float(converted)) else None
            state = "reported_zero" if value == 0 else "reported_value" if value is not None else "invalid"
        source_state = state
        if metadata_blocked:
            state, value = "metadata_invalid", None
        provenance = {"source_id": source_id, "report_type": kind, "raw_field": source_key,
                      "field": source_key, "raw_value": _safe_raw(original), "raw_presence": True,
                      "raw_state": source_state, "report_date": period, "announced_at": announced,
                      "currency": currency, "scope": scope, "raw_unit": _safe_raw(raw_unit),
                      "unit_factor": float(factor) if factor is not None else None,
                      "unit_basis": "explicit_raw_unit" if raw_unit not in (None, "") else "F10_amount_field_endpoint_contract_yuan",
                      "url": meta.get("url") or meta.get("source_url"), "sha256": meta.get("sha256"),
                      "raw_file": meta.get("raw_file")}
        # Invalid original numeric text is retained as value only for the engine to
        # distinguish invalid from null. It can never become arithmetic input.
        engine_value = value
        if state == "invalid" and original is not None and not opinion:
            engine_value = "INVALID_RAW_NUMERIC"
        if state == "metadata_invalid":
            engine_value = "INVALID_SOURCE_METADATA" if not opinion else None
        mapped[canonical] = {"value": engine_value, "state": state, "raw_state": source_state,
                             "report_date": period, "announced_at": announced,
                             "currency": currency, "unit": "CNY" if factor is not None else raw_unit,
                             "scope": scope, "basis": "audit_opinion" if opinion else "year_to_date" if "INCOME" in kind else "reported_book_value",
                             "source_refs": [provenance], "verification": "supplier_only",
                             "issues": list(problems)}
        states[canonical] = {"state": state, "source_state": source_state,
                             "source_key": source_key, "present": True}
    ignored_lookalikes = [key for key in ("FINANCE_EXPENSE", "INTEREST_EXPENSE", "INTEREST_COVERAGE_RATIO", "INTEREST_DEBT_RATIO") if key in raw and key not in mapping]
    return {"schema_version": 1, "adapter_version": ADAPTER_VERSION, "code": code,
            "name": raw.get("SECURITY_NAME_ABBR"), "financial_type": raw.get("ORG_TYPE"),
            "industry": raw.get("INDUSTRY_NAME") or raw.get("PUBLISHNAME"),
            "report_type": kind, "report_date": period, "announced_at": announced,
            "provider_updated_at": _date(raw.get("UPDATE_DATE")), "currency": currency,
            "scope": scope, "flow_basis": "year_to_date", "source_id": source_id,
            "fields": mapped, "field_states": states, "issues": problems,
            "ignored_same_name_or_unverified_fields": ignored_lookalikes,
            "completeness": "statement_mapping_only_no_debt_or_liquidity_scope_assertion"}


def _equal(left, right):
    return left.get("value") == right.get("value") and left.get("currency") == right.get("currency") and left.get("scope") == right.get("scope") and left.get("basis") == right.get("basis")


def _combine_facts(old, incoming):
    """Keep latest announcement; equal-date value conflicts remain conflicts."""
    if old is None:
        return deepcopy(incoming)
    old_date, new_date = old.get("announced_at") or "", incoming.get("announced_at") or ""
    if old_date and new_date and new_date > old_date:
        return deepcopy(incoming)
    if old_date and new_date and new_date < old_date:
        return deepcopy(old)
    old_valid = old.get("state") in {"reported_value", "reported_zero"}
    new_valid = incoming.get("state") in {"reported_value", "reported_zero"}
    if old_valid and incoming.get("state") == "null":
        retained = deepcopy(old)
        retained.setdefault("additional_missing_sources", []).extend(deepcopy(incoming.get("source_refs") or []))
        return retained
    if new_valid and old.get("state") == "null":
        retained = deepcopy(incoming)
        retained.setdefault("additional_missing_sources", []).extend(deepcopy(old.get("source_refs") or []))
        return retained
    if _equal(old, incoming) and old.get("state") == incoming.get("state"):
        retained = deepcopy(old)
        if not old_date or not new_date:
            retained["announced_at"] = None
            retained.setdefault("issues", []).append("announcement_date_unknown_in_equivalent_sources")
        for ref in incoming.get("source_refs") or []:
            if ref not in retained["source_refs"]:
                retained["source_refs"].append(deepcopy(ref))
        return retained
    candidates = deepcopy(old.get("conflicting_values") or [old]) + [deepcopy(incoming)]
    return {"value": None, "state": "conflict", "report_date": old.get("report_date"),
            "announced_at": old.get("announced_at") if old_date and new_date else None, "currency": old.get("currency"),
            "scope": old.get("scope"), "basis": old.get("basis"),
            "source_refs": deepcopy(old.get("source_refs") or []) + deepcopy(incoming.get("source_refs") or []),
            "conflicting_values": candidates, "verification": "conflict_requires_review"}


def enrich_debt_bundle(bundle, normalized_records, as_of=None):
    """Return an isolated debt-engine input; original six-indicator bundle intact.

Only same-code/same-period fields overlay company/history. No source can set a
debt_scope or liquidity_scope. Unknown-publication records are retained only when
no historical cutoff is requested, with issues preserved. Records after cutoff
are excluded. A later raw null is kept as null rather than reviving old amounts.
"""
    output = deepcopy(bundle if isinstance(bundle, dict) else {})
    company = output.setdefault("company", {})
    cutoff = _date(as_of or output.get("as_of") or company.get("as_of"))
    code = str(company.get("code") or "")
    periods, excluded, used = {}, [], []
    for raw in normalized_records or []:
        if not isinstance(raw, dict):
            continue
        record = deepcopy(raw)
        period, announced = _date(record.get("report_date")), _date(record.get("announced_at"))
        if str(record.get("code") or "") != code:
            excluded.append({"source_id": record.get("source_id"), "report_date": period, "reason": "company_code_mismatch"})
            continue
        if not period or (cutoff and (period > cutoff or not announced or announced > cutoff)):
            excluded.append({"source_id": record.get("source_id"), "report_date": period, "reason": "period_or_publication_unverified_or_future"})
            continue
        fields = periods.setdefault(period, {})
        for key, fact in (record.get("fields") or {}).items():
            fields[key] = _combine_facts(fields.get(key), fact)
        used.append({"source_id": record.get("source_id"), "report_type": record.get("report_type"), "report_date": period, "announced_at": announced, "issues": record.get("issues") or []})
    company.update(deepcopy(periods.get(_date(company.get("report_date")), {})))
    for row in output.get("history") or []:
        if isinstance(row, dict) and (not row.get("code") or str(row["code"]) == code):
            row.update(deepcopy(periods.get(_date(row.get("report_date")), {})))
    # Preserve annual audit records even if the base normalized-history cache omitted
    # a period: sparse supplemental rows remain explicit, not fabricated full rows.
    existing_periods = {_date(row.get("report_date")) for row in output.get("history") or [] if isinstance(row, dict)}
    for period, fields in periods.items():
        if period not in existing_periods and "audit_opinion_reported" in fields:
            output.setdefault("history", []).append({"code": code, "report_date": period,
                "announced_at": fields["audit_opinion_reported"].get("announced_at"),
                "currency": company.get("currency"), "audit_opinion_reported": deepcopy(fields["audit_opinion_reported"]),
                "sparse_debt_supplement_only": True})
    output["debt_adapter"] = {"adapter_version": ADAPTER_VERSION, "used_records": used,
                              "excluded_records": excluded, "provider_history_basis": "current_vendor_versions_not_point_in_time_verified",
                              "complete_debt_scope_inferred": False, "complete_liquidity_scope_inferred": False}
    return output
