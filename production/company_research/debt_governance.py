"""Pure, conservative debt/governance research. No I/O, AI or trading effects.

Numbers are CNY; direct scalar fields belong to the company row's period/currency.
Explicit fact objects may override provenance, but cannot silently override period,
currency, consolidation scope or contradictory values. Document matches identify
source text ONLY; they do not certify numerical semantics or absence of risk.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re

VERSION = "debt-governance-1.0"
FIELDS = {
    "short_borrowings": "短期借款",
    "long_borrowings_noncurrent": "长期借款（非流动部分）",
    "bonds_payable_noncurrent": "应付债券（非流动部分）",
    "short_bonds_payable": "短期应付债券",
    "current_portion_noncurrent_liabilities": "一年内到期的非流动负债（综合项）",
    "current_interest_debt_from_noncurrent": "一年内到期非流动负债中的有息部分",
    "lease_liabilities_noncurrent": "租赁负债（非流动部分）",
    "other_interest_debt_noncurrent": "其他非流动有息债务",
    "other_interest_debt_current": "其他流动有息债务",
    "cash": "货币资金",
    "restricted_cash": "受限货币资金",
    "cash_available_within_12_months": "经期限核查的未来12个月可动用现金",
    "interest_expense_financing": "费用化融资利息支出",
    "interest_income_financing": "财务费用中的利息收入",
    "finance_costs_net": "财务费用净额（含汇兑等）",
    "profit_before_tax": "合并利润总额",
}
DEBT_COMPONENTS = (
    "short_borrowings", "short_bonds_payable", "current_interest_debt_from_noncurrent",
    "other_interest_debt_current", "long_borrowings_noncurrent",
    "bonds_payable_noncurrent", "lease_liabilities_noncurrent",
    "other_interest_debt_noncurrent",
)
CURRENT_COMPONENTS = DEBT_COMPONENTS[:4]
NONNEGATIVE = set(FIELDS) - {"finance_costs_net", "profit_before_tax"}
SPECIAL_MODELS = {"bank", "insurance", "securities", "property", "loss_making"}
BOOK_BASES = {"reported_book_value", "book_value"}
OPINIONS = {
    "标准无保留意见": "unqualified", "标准的无保留意见": "unqualified",
    "无保留意见": "unqualified", "保留意见": "qualified",
    "否定意见": "adverse", "无法表示意见": "disclaimer",
    "带强调事项段的无保留意见": "unqualified_with_emphasis",
    "带持续经营重大不确定性段落的无保留意见": "unqualified_with_going_concern",
    "unqualified": "unqualified", "qualified": "qualified",
    "adverse": "adverse", "disclaimer": "disclaimer",
}
TOPICS = {
    "restricted_cash": ("受限现金", r"受限货币资金|受限资金|所有权或使用权受限资产|所有权或使用权受到限制"),
    "debt_maturity": ("债务期限", r"一年内到期的非流动负债|一年内到期的租赁负债|一年内到期的长期借款|未折现的合同现金流量"),
    "interest": ("利息口径", r"财务费用|贷款及应付款项的利息支出|租赁负债的利息支出"),
    "guarantees": ("担保", r"是否存在提供担保事项|违规对外担保情况|对外担保情况|对外提供担保|担保总额|担保余额|重大担保事项"),
    "related_parties": ("关联交易与资金占用", r"是否存在重大关联交易事项|重大关联交易|关联方占用|非经营性占用资金"),
    "regulatory": ("定期报告中的监管披露", r"处罚及整改情况|受到处罚及整改|被调查处罚的事项|行政处罚决定|立案调查"),
    "audit": ("审计与审阅", r"一、审计意见|一、 审计意见|审计意见类型|是否审计|本.*?报告未经审计|非标准审计|关键审计事项"),
}


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    try:
        return number if number.is_finite() and math.isfinite(float(number)) else None
    except (OverflowError, ValueError):
        return None


def _plain(number):
    if number is None:
        return None
    try:
        value = float(number)
        return value if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _model(company):
    supplied = company.get("industry_model")
    if supplied in SPECIAL_MODELS:
        return supplied
    industry = str(company.get("industry") or "").lower()
    for model, terms in (("bank", ("银行", "bank")), ("insurance", ("保险", "insurance")),
                         ("securities", ("证券", "信托", "非银金融", "多元金融", "金融服务", "金融业", "securities", "capital markets")),
                         ("property", ("房地产", "地产开发", "real estate"))):
        if any(term in industry for term in terms):
            return model
    profit = _num(company.get("net_profit"))
    parent = _num(company.get("parent_profit"))
    if (profit is not None and profit <= 0) or (parent is not None and parent <= 0):
        return "loss_making"
    return "general" if industry else "unknown"


def _metadata(key, *sources, default=None):
    """Explicit unknown/invalid metadata is not replaced by another field's data."""
    return next((s[key] for s in sources if isinstance(s, dict) and key in s), default)


def _fact(company, key, period, as_of):
    present = key in company
    raw = company.get(key)
    obj = raw if isinstance(raw, dict) else {"value": raw}
    value = _num(obj.get("value"))
    field_sources = company.get("field_sources") if isinstance(company.get("field_sources"), dict) else {}
    field_source = field_sources.get(key) if isinstance(field_sources.get(key), dict) else {}
    refs = deepcopy(obj.get("source_refs") or ([field_source] if field_source else []))
    if not isinstance(refs, list):
        refs = [refs] if isinstance(refs, dict) else []
    fact_period = _date(_metadata("report_date", obj, field_source, company))
    announced = _date(_metadata("announced_at", obj, field_source, company))
    currency = _metadata("currency", obj, field_source, company)
    scope = _metadata("scope", obj, field_source, company, default="consolidated")
    state = "not_provided" if not present else "null" if obj.get("value") is None else "invalid" if value is None else "reported_zero" if value == 0 else "reported_value"
    issues = deepcopy(obj.get("issues")) if isinstance(obj.get("issues"), list) else []
    if obj.get("state") in {"conflict", "metadata_invalid", "invalid", "publication_unverified", "future_disclosure", "scope_mismatch", "currency_unverified", "unit_unverified", "period_mismatch"}:
        state, value = obj["state"], None
    if obj.get("value") is not None and value is not None and key in NONNEGATIVE and value < 0:
        state, value = "invalid", None
        issues.append("negative_amount_requires_review")
    if value is not None and (not fact_period or fact_period != period):
        state, value = "period_mismatch", None
    if value is not None and currency != "CNY":
        state, value = "currency_unverified", None
    if value is not None and _metadata("unit", obj, field_source, default=company.get("amount_unit", "CNY")) not in ("CNY", "元", "人民币元"):
        state, value = "unit_unverified", None
    if value is not None and scope != "consolidated":
        state, value = "scope_mismatch", None
    supplied_code = _metadata("company_code", obj, field_source) or _metadata("code", obj, field_source)
    if value is not None and supplied_code and company.get("code") and str(supplied_code) != str(company["code"]):
        state, value = "company_code_mismatch", None
    if value is not None and announced and fact_period and announced < fact_period:
        state, value = "publication_invalid", None
    if value is not None and as_of and not announced:
        state, value = "publication_unverified", None
    if value is not None and as_of and (fact_period > as_of or (announced and announced > as_of)):
        state, value = "future_disclosure", None
    verification = "supplier_only" if refs else "source_missing"
    # Do not promote a claimed verification flag to certified financial semantics.
    if obj.get("verification") == "official_verified":
        verification = "supplied_as_verified_not_independently_checked"
    default_basis = (company.get("flow_basis") or "year_to_date") if key in {"interest_expense_financing", "interest_income_financing", "finance_costs_net", "profit_before_tax"} else "reported_book_value"
    return {"key": key, "label": FIELDS[key], "value": _plain(value), "state": state,
            "unit": "CNY", "currency": currency, "report_date": fact_period,
            "announced_at": announced, "scope": scope, "basis": _metadata("basis", obj, field_source, default=default_basis),
            "source_refs": refs, "verification": verification, "issues": issues}


def _metric(key, label, value, formula, components, status="calculated", note=""):
    parsed = _plain(value)
    return {"key": key, "label": label, "value": parsed, "status": status if parsed is not None or status.startswith("not_applicable") else "insufficient",
            "formula": formula, "components": list(components), "note": note,
            "verification": "arithmetic_only_not_source_semantics"}


def _document_period(doc):
    explicit = _date(doc.get("report_date"))
    if explicit:
        return explicit
    title = str(doc.get("title") or "")
    year = re.search(r"(20\d{2})年?", title)
    if not year:
        return None
    suffix = "06-30" if "半年度" in title else "03-31" if ("第一季度" in title or "一季度" in title) else "09-30" if ("第三季度" in title or "三季度" in title) else "12-31" if "年度报告" in title else None
    return f"{year.group(1)}-{suffix}" if suffix else None


def _source_excerpt(doc, page, start, length=620):
    text = page["text"]
    start = max(0, start - 100)
    return {"document_id": str(doc.get("id") or ""), "source_id": str(doc.get("id") or ""),
            "title": doc.get("title"), "url": doc.get("url") or doc.get("source_url"),
            "page": page["page"], "quote": text[start:start + length],
            "published_at": _date(doc.get("published_at")), "report_date": _document_period(doc),
            "sha256": doc.get("sha256"), "verification": "source_text_matched_only",
            "numeric_semantics_verified": False}


def _documents(bundle, as_of):
    docs, excluded, seen = [], [], set()
    for raw in bundle.get("documents") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        identity = str(raw["id"])
        expected_code = str((bundle.get("company") or {}).get("code") or "")
        supplied_code = str(raw.get("company_code") or raw.get("security_code") or "")
        if supplied_code and expected_code and supplied_code != expected_code:
            excluded.append({"document_id": identity, "reason": "company_code_mismatch"})
            continue
        if identity in seen:
            excluded.append({"document_id": identity, "reason": "duplicate_document_id"})
            continue
        seen.add(identity)
        period, published = _document_period(raw), _date(raw.get("published_at"))
        if period and published and published < period:
            excluded.append({"document_id": identity, "reason": "publication_before_report_end"})
            continue
        if as_of and (not published or published > as_of or (period and period > as_of)):
            excluded.append({"document_id": identity, "reason": "publication_unverified_or_future"})
            continue
        doc = deepcopy(raw)
        pages, page_ids = [], set()
        raw_pages = doc.get("pages")
        if raw_pages is not None and not isinstance(raw_pages, list):
            excluded.append({"document_id": identity, "reason": "document_pages_invalid"})
            continue
        for page in raw_pages or []:
            if not isinstance(page, dict) or isinstance(page.get("page"), bool) or not isinstance(page.get("page"), int) or page["page"] <= 0 or not isinstance(page.get("text"), str) or not page["text"].strip() or page["page"] in page_ids:
                continue
            page_ids.add(page["page"])
            pages.append(page)
        doc["pages"] = sorted(pages, key=lambda p: p["page"])
        if pages:
            docs.append(doc)
    return docs, excluded


def _evidence_topics(docs):
    topics = []
    for key, (label, pattern) in TOPICS.items():
        candidates = []
        for doc in docs:
            per_document = 0
            for page in doc["pages"]:
                text = page["text"]
                match = re.search(pattern, text)
                if not match:
                    continue
                # Suppress contents pages; a heading alone does not establish fact.
                if "目录" in text[:80] or re.search(r"\.{5,}|…{3,}", text[match.start():match.start()+100]):
                    continue
                evidence = _source_excerpt(doc, page, match.start())
                evidence["matched_text"] = match.group(0)
                evidence["status"] = "pending_review"
                if key == "regulatory":
                    evidence["scope"] = "periodic_report_disclosure_only"
                candidates.append(evidence)
                per_document += 1
                if per_document == 3:
                    break
        topics.append({"topic": key, "label": label, "status": "evidence_candidates" if candidates else "not_reviewed",
                       "evidence": candidates, "conclusion": None,
                       "note": "已定位原文，需核查主体、期间、适用范围和上下文；未把关键词命中当作风险事实。"})
    return topics


def _audit(company, history, docs, as_of):
    records, excluded = [], []
    for row in [company] + list(history or []):
        if not isinstance(row, dict):
            continue
        if row.get("code") and company.get("code") and str(row["code"]) != str(company["code"]):
            excluded.append({"report_date": _date(row.get("report_date")), "reason": "company_code_mismatch"})
            continue
        field_sources = row.get("field_sources") if isinstance(row.get("field_sources"), dict) else {}
        opinion_source = field_sources.get("audit_opinion_reported") or field_sources.get("audit_opinion")
        opinion_source = opinion_source if isinstance(opinion_source, dict) else {}
        opinion = row.get("audit_opinion_reported", row.get("audit_opinion"))
        opinion_object = opinion if isinstance(opinion, dict) else {}
        period = _date(_metadata("report_date", opinion_object, opinion_source, row))
        announced = _date(_metadata("announced_at", opinion_object, opinion_source, row))
        source_code = _metadata("company_code", opinion_object, opinion_source) or _metadata("code", opinion_object, opinion_source)
        if source_code and company.get("code") and str(source_code) != str(company["code"]):
            excluded.append({"report_date": period, "reason": "opinion_company_code_mismatch"})
            continue
        audit_type = _metadata("audit_type", opinion_object, opinion_source, row, default="financial_statements")
        audit_scope = _metadata("scope", opinion_object, opinion_source, default="consolidated")
        if audit_type not in {"financial", "financial_statement", "financial_statements", "financial_report", "财务报表"} or audit_scope in {"internal_control", "内部控制"}:
            if opinion is not None:
                excluded.append({"report_date": period, "reason": "not_financial_statement_audit"})
            continue
        forced_status, object_sources, conflicting_opinions = None, None, None
        if isinstance(opinion, dict):
            object_sources = opinion.get("source_refs")
            if opinion.get("state") == "conflict":
                forced_status = "conflict"
                conflicting_opinions = [item.get("value") for item in opinion.get("conflicting_values") or [] if isinstance(item, dict)]
                opinion = "来源意见冲突"
            elif opinion.get("state") not in (None, "reported_value"):
                excluded.append({"report_date": period, "reason": "opinion_source_" + str(opinion.get("state"))})
                continue
            else:
                opinion = opinion.get("value")
        if not period or (announced and announced < period) or (as_of and (period > as_of or not announced or announced > as_of)):
            if opinion is not None:
                excluded.append({"report_date": period, "reason": "period_or_publication_unverified_or_future"})
            continue
        if not isinstance(opinion, str) or not opinion.strip():
            continue
        normalized = re.sub(r"\s+", "", opinion).lower()
        records.append({"report_date": period, "announced_at": announced,
                        "raw_opinion": opinion, "status": forced_status or OPINIONS.get(normalized, "unrecognized_requires_review"),
                        "source": "supplied_structured_opinion", "source_refs": deepcopy(object_sources) if isinstance(object_sources, list) else [deepcopy(opinion_source)] if isinstance(opinion_source, dict) else [],
                        "conflicting_opinions": conflicting_opinions,
                        "verification": "supplier_only"})
    # Latest announcement may legitimately restate an earlier opinion, equal-date
    # disagreement is retained as a conflict instead of selecting the better one.
    grouped = {}
    for item in records:
        grouped.setdefault(item["report_date"], []).append(item)
    periods = {}
    for period, versions in grouped.items():
        latest = max((item["announced_at"] or "") for item in versions)
        candidates = [item for item in versions if not item["announced_at"] or item["announced_at"] == latest]
        chosen = deepcopy(next((item for item in candidates if item["announced_at"] == latest), candidates[0]))
        signatures = {(item["status"], item["raw_opinion"] if item["status"] == "unrecognized_requires_review" else "") for item in candidates}
        if len(signatures) > 1:
            chosen.update(status="conflict", conflicting_opinions=list(dict.fromkeys(
                opinion for item in candidates for opinion in (item.get("conflicting_opinions") or [item["raw_opinion"]]))))
            if any(not item["announced_at"] for item in candidates):
                chosen["note"] = "存在未知公告日期的不同意见，不能用已知日期为其排序并消除冲突。"
        chosen["source_refs"] = []
        for item in candidates:
            for ref in item.get("source_refs") or []:
                if ref not in chosen["source_refs"]:
                    chosen["source_refs"].append(deepcopy(ref))
        periods[period] = chosen
    current_period = _date(company.get("report_date"))
    current = deepcopy(periods.get(current_period)) or {"report_date": current_period, "status": "not_reported", "source": None}
    disclosures = []
    for doc in docs:
        if _document_period(doc) != current_period:
            continue
        for page in doc["pages"]:
            compact = re.sub(r"\s+", "", page["text"])
            def matching_disclosure(pattern):
                for match in re.finditer(pattern, compact):
                    prefix = compact[max(0, match.start() - 16):match.start()]
                    if re.search(r"(?:如果|假如|假设|假定|若|如)[^。；;]{0,8}$", prefix):
                        continue
                    text = match.group(0)
                    year = re.search(r"20\d{2}", text)
                    if year and year.group(0) != str(current_period)[:4]:
                        continue
                    suffix = "06-30" if "半年度" in text else "03-31" if "第一季度" in text else "09-30" if "第三季度" in text else None
                    if suffix and not str(current_period).endswith(suffix):
                        continue
                    return match
                return None
            unaudited = matching_disclosure(r"(?:本公司|本行|本集团|公司|本)?20\d{2}年(?:半年度|第一季度|第三季度)?(?:财务)?报告未经审计|本(?:公司|行|集团)?(?:半年度|季度|财务)?报告未经审计|本半年度报告未经审计")
            unaudited_checkbox = re.search(r"(?:^|[\r\n])\s*(?:半年度财务报告)?是否(?:已经)?审计\s*(?:□是\s*√否|否)\s*(?:[\r\n]|$)", page["text"])
            reviewed = matching_disclosure(r"对本(?:公司|行|集团)?20\d{2}年半年度财务报告进行了审阅|对本(?:公司|行|集团)?(?:半年度)?财务报告进行了审阅")
            if not unaudited and not reviewed and not unaudited_checkbox:
                continue
            match = re.search(r"未经审计|进行了审阅|是否(?:已经)?审计", page["text"])
            if match:
                disclosures.append(_source_excerpt(doc, page, match.start()))
            inferred = "reviewed_not_audited" if reviewed else "unaudited"
            if current.get("status") in set(OPINIONS.values()) | {"conflict"}:
                current["status"] = "conflict"
                current["note"] = "结构化意见与同报告期原文未经审计/审阅声明不一致。"
            elif current.get("status") != "reviewed_not_audited":
                current.update(status=inferred, source="explicit_document_disclosure")
    current["evidence"] = disclosures
    annuals = [item for period, item in periods.items() if period.endswith("12-31")]
    if current_period and current_period.endswith("12-31") and current.get("status") != "not_reported":
        annuals = [item for item in annuals if item["report_date"] != current_period] + [current]
    annual = deepcopy(max(annuals, key=lambda x: x["report_date"])) if annuals else None
    return {"latest_report": current, "latest_annual": annual,
            "history": sorted(periods.values(), key=lambda x: x["report_date"]), "excluded_records": excluded,
            "note": "标准审计意见不等于无风险；审阅、未经审计及财务/内部控制意见分别理解。原文关键词不能自动判为非标。"}


def build_debt_governance(bundle, as_of=None):
    """Return JSON-safe research data without mutating any input.

Required for complete debt metrics: all DEBT_COMPONENTS present (explicit zeros
allowed), matching CNY consolidated book values, and debt_scope declaration with
complete, includes_leases, all_interest_bearing_categories_reviewed, components
equal to DEBT_COMPONENTS, report_date matching the current company row. This is a
declared completeness contract, not an audit certification. Liquidity calculations
add liquidity_scope.complete/period and explicit within-12-month available cash.
"""
    bundle = deepcopy(bundle if isinstance(bundle, dict) else {})
    company = bundle.get("company") or {}
    if not isinstance(company, dict):
        company = {}
    period = _date(company.get("report_date"))
    cutoff = _date(as_of or bundle.get("as_of") or company.get("as_of"))
    model = _model(company)
    applicable = model == "general"
    facts = {key: _fact(company, key, period, cutoff) for key in FIELDS}
    risks, gaps = [], []
    for key, fact in facts.items():
        if fact["value"] is None:
            gaps.append({"key": key, "label": fact["label"], "state": fact["state"]})
    def issue(code, message, level="needs_review", evidence=None):
        risks.append({"code": code, "level": level, "message": message, "evidence_refs": evidence or []})
    values = {key: _num(fact["value"]) for key, fact in facts.items()}
    current_total = values["current_portion_noncurrent_liabilities"]
    current_interest = values["current_interest_debt_from_noncurrent"]
    composition_conflict = current_total is not None and current_interest is not None and current_interest > current_total
    if composition_conflict:
        issue("current_portion_conflict", "到期非流动负债中的有息部分超过该综合项，需核对范围或重复项目。", "high")
    known_components = [key for key in DEBT_COMPONENTS if values[key] is not None and facts[key]["basis"] in ("reported_book_value", "book_value")]
    known = sum((values[key] for key in known_components), Decimal(0)) if known_components and not composition_conflict else None
    scope = company.get("debt_scope") or bundle.get("debt_scope") or {}
    if not isinstance(scope, dict):
        scope = {}
    scope_components = scope.get("components")
    valid_components = isinstance(scope_components, list) and all(isinstance(k, str) for k in scope_components) and len(scope_components) == len(DEBT_COMPONENTS) and set(scope_components) == set(DEBT_COMPONENTS)
    def declaration_visible(declaration, key):
        announced = _date(declaration.get("announced_at"))
        reason = "period_mismatch" if _date(declaration.get("report_date")) != period else "publication_invalid" if announced and period and announced < period else "publication_unverified" if cutoff and not announced else "future_disclosure" if cutoff and announced and announced > cutoff else None
        if declaration and reason:
            gaps.append({"key": key, "label": "完整性声明的报告期或披露时间未通过核对", "state": reason})
        return reason is None
    declared = all(scope.get(key) is True for key in ("complete", "includes_leases", "all_interest_bearing_categories_reviewed")) and declaration_visible(scope, "debt_scope_publication") and valid_components
    consistent_basis = all(facts[key]["basis"] in ("reported_book_value", "book_value") for key in DEBT_COMPONENTS if values[key] is not None)
    complete = applicable and declared and len(known_components) == len(DEBT_COMPONENTS) and not composition_conflict and consistent_basis
    total = known if complete else None
    current_debt = sum((values[key] for key in CURRENT_COMPONENTS), Decimal(0)) if complete else None
    if not complete:
        gaps.append({"key": "debt_completeness", "label": "有息债务的全部类别、期限与重复项尚未完整核查", "state": "incomplete"})
    debt_metrics = [
        _metric("known_interest_debt_subtotal", "已识别有息债务部分合计", known if applicable else None, "所列互斥组件相加", known_components,
                note="不是有息债务总额；未识别的其他有息负债仍可能存在。综合到期项未经拆分不加入。"),
        _metric("total_interest_debt", "有息债务总额（含租赁）", total, "所有完整性契约组件相加", DEBT_COMPONENTS,
                note="根据上游声明的完整口径计算，不代表本函数完成原文审计。"),
        _metric("interest_debt_due_within_12_months", "未来12个月到期有息债务账面额", current_debt, "短借+短债+到期非流动有息部分+其他流动有息债务", CURRENT_COMPONENTS,
                note="账面金额，不是含未来利息的合同现金支付额。"),
    ]
    interest, pbt = values["interest_expense_financing"], values["profit_before_tax"]
    interest_basis_aligned = facts["interest_expense_financing"]["basis"] == facts["profit_before_tax"]["basis"] and facts["interest_expense_financing"]["basis"] in {"year_to_date", "annual", "full_year"}
    interest_cover = (pbt + interest) / interest if applicable and interest_basis_aligned and interest is not None and interest > 0 and pbt is not None else None
    debt_metrics.append(_metric("expensed_interest_coverage", "利润对费用化融资利息的覆盖", interest_cover,
        "(合并利润总额+费用化融资利息支出)/费用化融资利息支出", ["profit_before_tax", "interest_expense_financing"],
        status="not_applicable_zero_interest" if applicable and interest_basis_aligned and interest == 0 and pbt is not None else "calculated",
        note="简化会计口径，不含未进入本期损益的资本化借款利息；不是现金偿债覆盖。"))
    if interest_cover is not None and interest_cover < 1:
        issue("weak_expensed_interest_coverage", "本期利润对费用化融资利息的简化覆盖低于1；需核查现金、资本化利息和到期安排。")
    cash, restricted = values["cash"], values["restricted_cash"]
    cash_less = None
    cash_basis_aligned = all(facts[k]["basis"] in BOOK_BASES for k in ("cash", "restricted_cash"))
    if applicable and cash is not None and restricted is not None and cash_basis_aligned:
        if restricted > cash:
            issue("restricted_cash_conflict", "受限货币资金大于货币资金，需核对项目和范围。", "high")
        else:
            cash_less = cash - restricted
    liquid = values["cash_available_within_12_months"]
    liquidity_scope = company.get("liquidity_scope") or bundle.get("liquidity_scope") or {}
    if not isinstance(liquidity_scope, dict):
        liquidity_scope = {}
    liquidity_complete = applicable and liquidity_scope.get("complete") is True and declaration_visible(liquidity_scope, "liquidity_scope_publication") and liquidity_scope.get("restricted_and_term_deposits_reviewed") is True and liquid is not None and cash_less is not None and facts["cash_available_within_12_months"]["basis"] in BOOK_BASES
    if not cash_basis_aligned or (liquid is not None and facts["cash_available_within_12_months"]["basis"] not in BOOK_BASES):
        gaps.append({"key": "cash_basis", "label": "货币资金、受限与可动用现金必须为同口径账面额，不能混入预测或合同现金流", "state": "basis_mismatch"})
    if liquid is not None and cash_less is not None and liquid > cash_less:
        liquidity_complete = False
        issue("liquidity_scope_conflict", "12个月可动用现金超过已披露货币资金扣受限部分，需核查是否混入其他资产。", "high")
    net_cash = liquid - total if complete and liquidity_complete else None
    cash_cover = liquid / current_debt if complete and liquidity_complete and current_debt > 0 else None
    liquidity_metrics = [
        _metric("cash_less_disclosed_restrictions", "货币资金扣已披露受限部分", cash_less, "货币资金-受限货币资金", ["cash", "restricted_cash"], note="仍可能包含不能及时动用的定期存款；不是可用现金。"),
        _metric("net_cash_after_interest_debt", "经期限核查现金减有息债务", net_cash, "12个月可动用现金-完整有息债务总额", ["cash_available_within_12_months", "total_interest_debt"], note="只在债务与现金两个完整性契约都满足时计算。"),
        _metric("cash_to_12month_interest_debt", "经期限核查现金/12个月到期有息债务", cash_cover, "12个月可动用现金/12个月到期有息债务账面额", ["cash_available_within_12_months", "interest_debt_due_within_12_months"], status="not_applicable_zero_debt" if complete and liquidity_complete and current_debt == 0 else "calculated", note="分母明确为0时比例不适用；未预测经营现金流，不是未来违约概率。"),
    ]
    if not liquidity_complete:
        gaps.append({"key": "cash_availability", "label": "受限资金、定期存款与可动用期限尚未完整核查", "state": "incomplete"})
    if cash_cover is not None and cash_cover < 1:
        issue("cash_maturity_gap", "经期限核查现金低于12个月到期有息债务账面额，需继续核查经营现金和融资安排。")
    docs, excluded_docs = _documents(bundle, cutoff)
    topics = _evidence_topics(docs)
    audit = _audit(company, bundle.get("history"), docs, cutoff)
    for record in [audit["latest_report"], audit["latest_annual"]]:
        if record and record.get("status") in {"qualified", "adverse", "disclaimer", "unqualified_with_going_concern", "conflict"}:
            code = "audit_" + record["status"] + "_" + str(record["report_date"])
            if not any(r["code"] == code for r in risks):
                issue(code, str(record["report_date"]) + "审计信息存在需优先核查的意见或冲突；核对原始审计报告。", "high", deepcopy(record.get("source_refs") or []) + deepcopy(record.get("evidence") or []))
        elif record and record.get("status") in {"unrecognized_requires_review", "unqualified_with_emphasis"}:
            code = "audit_review_" + str(record["report_date"])
            if not any(r["code"] == code for r in risks):
                issue(code, str(record["report_date"]) + "审计意见包含强调事项或暂未识别的意见类型，需要阅读原始报告。")
    if not applicable:
        issue("specialist_required", "该行业、盈利阶段或行业资料状态需要专项判断；一般企业债务合成与覆盖指标暂不计算。", "information")
    # A found periodic report never establishes complete governance/regulatory coverage.
    gaps.extend([
        {"key": "authority_announcements", "label": "尚未检索监管机关及交易所独立公告", "state": "not_reviewed"},
        {"key": "guarantee_scope", "label": "需分别核对担保余额、对象、违规性与业务担保范围", "state": "not_reviewed"},
    ])
    return {"schema_version": 1, "engine_version": VERSION, "report_date": period, "as_of": cutoff,
            "company_code": str(company.get("code") or ""),
            "applicability": {"industry_model": model, "general_metrics_enabled": applicable},
            "facts": list(facts.values()), "debt": {"complete": complete, "metrics": debt_metrics},
            "liquidity": {"complete": liquidity_complete, "metrics": liquidity_metrics},
            "audit": audit, "governance": {"scope": "periodic_report_disclosures_only", "authority_announcements": "not_reviewed", "topics": topics, "risk_cleared": False},
            "priority_risks": risks, "gaps": gaps,
            "coverage": {"provided_numeric_fields": sum(f["value"] is not None for f in facts.values()),
                         "numeric_field_count": len(facts), "documents_with_text": len(docs), "excluded_documents": excluded_docs,
                         "source_verification": "numeric_semantics_not_independently_verified"},
            "limitations": ["财报没有披露不代表没有风险；合计完整性依赖上游明确提供并核对的口径。",
                            "原文匹配只证明片段来自输入资料，没有自动核验金额语义、主体、币种或表格列。",
                            "监管机关与交易所独立事实尚未检索，不能据此清除治理风险。",
                            "本模块是研究核查，不构成公司完整结论或买入建议。"]}
