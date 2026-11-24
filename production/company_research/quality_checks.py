"""Experimental, field-scoped financial checks over an existing research report.

No I/O, scoring, return forecasts, report mutation or new financial data recovery.
The current supplier records are not audited or strict point-in-time evidence.
"""
from datetime import date
import math
from statistics import median

VERSION = RULES_VERSION = "quality-checks-1.0"
LONG_TERM_VERSION = "long-term-quality-1.0"
VALID_FIELD_STATES = {"available", "zero", "negative"}
STATUSES = ("pass", "watch", "fail", "insufficient", "not_applicable")


def _obj(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _unique(values):
    return list(dict.fromkeys(v for v in values if isinstance(v, str) and v))


def _valid_state(value, allowed):
    return isinstance(value, str) and value in allowed


def _pair(zh, en):
    return [zh, en]


def _check(key, title, rule, review, periods):
    return {"key": key, "title": title, "status": "insufficient", "rule": rule,
            "value_text": _pair("资料不足", "Insufficient evidence"),
            "reason": _pair("所需同口径资料尚未齐备。", "Required comparable evidence is incomplete."),
            "periods": list(periods), "source_ids": [], "missing": [], "review_trigger": review}


def _context(report, expected):
    company = _obj(report.get("company"))
    summary = _obj(report.get("summary"))
    long_term = _obj(_obj(report.get("quality")).get("long_term"))
    profile = _obj(report.get("industry_profile"))
    code = str(company.get("code") or "")
    cutoff = _day(company.get("as_of")) or _day(long_term.get("as_of"))
    period = _day(company.get("report_date"))
    errors = []
    if not code or (expected is not None and str(expected) != code):
        errors.append("company_code_missing_or_mismatch")
    for name, obj, key in (("summary", summary, "code"), ("industry_profile", profile, "code")):
        if str(obj.get(key) or "") != code:
            errors.append(name + ":company_code_missing_or_mismatch")
    for key in ("company_code", "code"):
        if key in long_term and str(long_term[key]) != code:
            errors.append("long_term:company_code_mismatch")
    if not cutoff or not period or period > cutoff:
        errors.append("report_date_or_cutoff_invalid")
    if company.get("as_of") is not None and _day(company.get("as_of")) != cutoff:
        errors.append("company:invalid_as_of")
    for name, obj in (("report", report), ("summary", summary)):
        if "as_of" in obj and _day(obj["as_of"]) != cutoff:
            errors.append(name + ":cutoff_mismatch")
    if long_term.get("version") != LONG_TERM_VERSION or _day(long_term.get("as_of")) != cutoff:
        errors.append("long_term:version_or_cutoff_mismatch")
    for name, obj in (("summary", summary), ("industry_profile", profile)):
        if _day(obj.get("report_date")) != period:
            errors.append(name + ":report_date_mismatch")
    if profile.get("version") != "industry-policy-1.0" or _day(profile.get("as_of")) != cutoff:
        errors.append("industry_profile:version_or_cutoff_mismatch")
    anchor = int(cutoff[:4]) - 1 if cutoff else None
    if anchor is not None and long_term.get("anchor_year") != anchor:
        errors.append("long_term:fixed_annual_anchor_mismatch")
    classification = _obj(profile.get("classification"))
    model = classification.get("model")
    evidence = _rows(classification.get("evidence"))
    if not evidence:
        errors.append("industry_profile:classification_evidence_missing")
    for item in evidence:
        current = item.get("temporal_basis") == "supplier_current_snapshot"
        published = _day(str(item.get("observed_at") or "")[:10]) if current else _day(item.get("announced_at"))
        if not item.get("source_id") or not published or not cutoff or published > cutoff:
            errors.append("industry_profile:classification_evidence_unbound_or_future")
        if item.get("company_code") is not None and str(item["company_code"]) != code:
            errors.append("industry_profile:classification_company_mismatch")
        if current and profile.get("research_purpose") != "current_research":
            errors.append("industry_profile:current_label_not_historical_evidence")
    specialist = model != "general"
    modules = _obj(profile.get("modules"))
    if not specialist and _obj(modules.get("long_term")).get("status") != "conditional":
        specialist = True
    if model in (None, "unknown", "financial_unresolved"):
        errors.append("industry_classification_unresolved")
    return company, long_term, profile, code, cutoff, period, anchor, _unique(errors), specialist


def _annual(long_term, periods, keys, cutoff):
    rows = _rows(long_term.get("years"))
    values, missing, sources = [], [], []
    for period in periods:
        candidates = [r for r in rows if r.get("report_date") == period]
        row = candidates[0] if len(candidates) == 1 else {}
        matrix = []
        for key in keys:
            item = _obj(_obj(row.get("fields")).get(key))
            value = _num(item.get("value"))
            publication = _day(item.get("announced_at"))
            refs = _unique(item.get("source_ids") if isinstance(item.get("source_ids"), list) else [])
            problem = None
            if len(candidates) > 1:
                problem = "duplicate_annual_slot"
            elif not row or row.get("year") != int(period[:4]):
                problem = "missing_or_invalid_annual_slot"
            elif item.get("key") != key or item.get("periods") != [period]:
                problem = "field_period_or_key_mismatch"
            elif not _valid_state(item.get("status"), VALID_FIELD_STATES) or value is None or item.get("missing"):
                problem = str(item.get("status") or "missing")
            elif item.get("unit") != ("ratio" if key == "roe" else "CNY"):
                problem = "invalid_unit"
            elif not publication or publication < period or publication > cutoff:
                problem = "publication_unknown_invalid_or_future"
            elif not refs:
                problem = "source_missing"
            elif key in ("receivables", "inventory") and value < 0:
                problem = "negative_balance_requires_review"
            if problem:
                missing.append(f"{period}:{key}:{problem}")
                value = None
            else:
                sources.extend(refs)
            matrix.append(value)
        values.append(matrix)
    return values, _unique(missing), _unique(sources)


def _set_evidence(check, result):
    matrix, check["missing"], check["source_ids"] = result
    return matrix


def _incomplete(check, known_bad, zh, en):
    check["status"] = "watch" if known_bad else "insufficient"
    check["reason"] = _pair(zh + "；资料缺口保留，未作完整通过判断。", en + "; gaps remain and no complete pass is issued.")


def _debt(check, report, code, cutoff, period):
    debt = _obj(report.get("debt_governance"))
    # Version 1.0 intentionally has no EBITDA or net-debt/EBITDA contract.
    # Do not accept an injected similarly named metric or a gross-debt proxy.
    check["missing"] = ["debt:validated_net_debt_to_ebitda_unavailable"]
    check["reason"] = _pair("现有资料尚缺完整净债务／EBITDA口径；资产负债率、已识别债务小计均不能替代。", "Available evidence lacks a complete net-debt/EBITDA basis; a balance-sheet debt ratio or identified subtotal is not a substitute.")
    bound = (debt.get("engine_version") == "debt-governance-1.0" and debt.get("company_code") == code
             and _day(debt.get("as_of")) == cutoff and _day(debt.get("report_date")) == period
             and _obj(debt.get("applicability")).get("general_metrics_enabled") is True)
    if not bound:
        check["missing"].append("debt:version_subject_period_or_applicability_unbound")
        return
    facts = {r.get("key"): r for r in _rows(debt.get("facts"))}
    relevant = [facts.get(k, {}) for k in ("profit_before_tax", "interest_expense_financing")]
    covers = [r for r in _rows(_obj(debt.get("debt")).get("metrics")) if r.get("key") == "expensed_interest_coverage"]
    cover = covers[0] if len(covers) == 1 else {}
    values = [_num(f.get("value")) for f in relevant]
    valid = all(f.get("state") in ("reported_zero", "reported_value")
                and f.get("report_date") == period and f.get("currency") == "CNY" and f.get("unit") == "CNY"
                and f.get("scope") == "consolidated" and f.get("basis") in ("annual", "year_to_date", "full_year")
                and _day(f.get("announced_at")) and period <= f["announced_at"] <= cutoff
                and any(s.get("source_id") or s.get("id") for s in _rows(f.get("source_refs"))) for f in relevant)
    valid = valid and relevant[0].get("basis") == relevant[1].get("basis") and all(v is not None for v in values)
    n = _num(cover.get("value"))
    valid = valid and cover.get("status") == "calculated" and n is not None and values[1] > 0
    if valid and not math.isclose(n, (values[0] + values[1]) / values[1], rel_tol=1e-10, abs_tol=1e-10):
        valid = False
    if not valid:
        check["missing"].append("debt:validated_expensed_interest_coverage_unavailable")
        return
    check["source_ids"] = _unique(str(s.get("source_id") or s.get("id") or "") for f in relevant for s in _rows(f.get("source_refs")))
    if not check["source_ids"]:
        check["missing"].append("debt:interest_coverage_source_missing")
        return
    check["value_text"] = _pair(f"费用化利息简化覆盖 {n:.2f} 倍；净债务／EBITDA缺失", f"Expensed-interest coverage {n:.2f}x; net-debt/EBITDA missing")
    check["reason"] = _pair("仅沿用已核对期间与口径的简化利息覆盖；不含资本化利息，债务整项仍不完整。", "Only the period- and basis-aligned simplified interest coverage is shown; capitalized interest is excluded and the debt check remains incomplete.")
    if n < 5:
        check["status"] = "watch"
        check["reason"] = _pair("已知费用化利息简化覆盖低于5倍，需要核查；净债务／EBITDA缺失，不能判断整体偿债能力。", "Known simplified expensed-interest coverage is below 5x and needs review; missing net-debt/EBITDA prevents an overall debt conclusion.")


def _current(check, long_term, cutoff, period):
    current = _obj(long_term.get("current_period"))
    previous = str(int(period[:4]) - 1) + period[4:]
    metrics = _rows(current.get("metrics"))
    values = []
    errors = []
    if (current.get("report_date") != period or current.get("comparison_date") != previous
            or not _day(current.get("announced_at")) or not period <= current["announced_at"] <= cutoff):
        errors.append("current:period_or_publication_invalid")
    # V1 does not carry per-current-field announcement dates. Requiring the
    # existing date-completeness flag avoids borrowing another field's date.
    if current.get("pit_status") != "publication_dates_known":
        errors.append("current:field_publication_dates_incomplete")
    shared_errors = list(errors)
    for key in ("net_profit", "op_cashflow"):
        items = [m for m in metrics if m.get("key") == key + "_yoy"]
        item = items[0] if len(items) == 1 else {}
        number = _num(item.get("current_value"))
        raw_missing = item.get("missing") if isinstance(item.get("missing"), list) else []
        relevant_missing = [m for m in raw_missing if isinstance(m, str) and m.startswith(period + ":")]
        sources = _unique(item.get("source_ids") if isinstance(item.get("source_ids"), list) else [])
        if (shared_errors or item.get("periods") != [previous, period] or number is None or relevant_missing or not sources
                or item.get("unit") != "ratio" or not _valid_state(item.get("status"), VALID_FIELD_STATES | {"missing", "not_applicable"})):
            errors.append(f"{period}:{key}:unavailable_or_unbound")
            number = None
        else:
            check["source_ids"].extend(sources)
        values.append(number)
    check["source_ids"] = _unique(check["source_ids"])
    check["missing"] = _unique(errors)
    if errors:
        # Preserve usable adverse evidence even if the other same-period field
        # is missing. Unsafe publication/period metadata invalidates both.
        profit, cash = values
        bad = profit is not None and profit <= 0 or cash is not None and cash <= 0
        if bad:
            _incomplete(check, True, "已知本期利润或经营现金流非正", "Known current profit or operating cash flow is nonpositive")
        check["value_text"] = _pair(
            "本期合并利润 " + ("缺失" if profit is None else f"{profit:,.2f} 元") + "；经营现金 " + ("缺失" if cash is None else f"{cash:,.2f} 元"),
            "Current consolidated profit " + ("missing" if profit is None else f"CNY {profit:,.2f}") + "; operating cash " + ("missing" if cash is None else f"CNY {cash:,.2f}"))
        return
    profit, cash = values
    check["value_text"] = _pair(f"同期期末累计合并净利润 {profit:,.2f} 元；经营现金流 {cash:,.2f} 元", f"Same-period cumulative consolidated profit CNY {profit:,.2f}; operating cash flow CNY {cash:,.2f}")
    ratio = cash / profit if profit > 0 else None
    check["status"] = "fail" if profit > 0 and cash <= 0 else "watch" if profit <= 0 or ratio < .8 else "pass"
    check["reason"] = _pair("合并利润非正，不计算现金／利润比例，须检查盈利及现金来源。", "Consolidated profit is nonpositive; no cash/profit ratio is computed and earnings and cash sources need review.") if profit <= 0 else _pair(
        f"本期经营现金流／合并净利润 {ratio:.2f} 倍；只比较同一累计期间，不年化，不代表未来回款。",
        f"Current operating cash flow/consolidated profit is {ratio:.2f}x for the same cumulative period; no annualization or future-collection inference.")


def build_quality_checks(report, *, company_code=None):
    """Seven transparent checks; pass means only this experimental rule is met."""
    report = _obj(report)
    company, lt, profile, code, cutoff, period, anchor, errors, specialist = _context(report, company_code)
    periods5 = [f"{year}-12-31" for year in range(anchor - 4, anchor + 1)] if anchor else []
    periods3 = periods5[-3:]
    specs = [
        ("adjusted_profit_persistence", _pair("扣非盈利持续性", "Recurring profit persistence"),
         _pair("固定最近5年扣非归母利润至少4年为正，且最近1年为正。", "At least 4 of the fixed latest 5 annual adjusted parent profits must be positive, including the latest year."),
         _pair("任一年非正、重述或资料缺失时核对主业与一次性事项。", "Review operations and one-off items after nonpositive earnings, restatements or gaps."), periods5),
        ("roe_consistency", _pair("ROE水平与稳定性", "ROE level and consistency"),
         _pair("固定最近3年披露ROE中位数≥12%，每一年≥8%。", "The fixed latest 3 annual reported ROEs need a median of at least 12% and a minimum of at least 8%."),
         _pair("低于阈值或权益收缩时核对杠杆、回购和资本结构；ROE不等于ROIC。", "Review leverage, repurchases and capital structure when thresholds fail or equity shrinks; ROE is not ROIC."), periods3),
        ("cash_conversion", _pair("三年利润现金覆盖", "Three-year cash conversion"),
         _pair("固定3年累计经营现金流／累计合并净利润≥0.80，3年现金流均为正，利润逐年非负且累计为正。", "For the fixed 3 years, total operating cash flow/total consolidated profit must be at least 0.80, every cash flow positive, and each profit nonnegative with a positive total."),
         _pair("现金覆盖走弱或单年现金／利润非正时检查回款、预收、应付款和一次性项目。", "Review collections, advances, payables and one-off items when coverage weakens or annual cash/profit is nonpositive."), periods3),
        ("debt_resilience", _pair("债务与利息覆盖", "Debt and interest coverage"),
         _pair("完整同口径净债务／EBITDA≤2且利息覆盖≥5；需同时核实债务、现金与利息范围。", "Complete comparable net-debt/EBITDA must be at most 2 and interest coverage at least 5; debt, cash and interest scope must all be checked."),
         _pair("补齐EBITDA、净债务范围、受限现金、资本化利息和到期安排。", "Complete EBITDA, net-debt scope, restricted cash, capitalized interest and maturity evidence."), [period] if period else []),
        ("cash_profit_divergence", _pair("最新期间利润与现金背离", "Latest-period earnings/cash divergence"),
         _pair("同一期累计合并利润与经营现金比较；利润正而现金≤0为未通过，现金／利润<0.80提示复核。", "Compare consolidated profit and cash for the same cumulative period; positive profit with cash at or below zero fails, and cash/profit below 0.80 prompts review."),
         _pair("结合季节性、回款和一次性支出复核；不把中期数乘倍数当全年。", "Review seasonality, collections and one-off payments; never multiply interim results into full-year values."), [period] if period else []),
    ]
    for field, zh, en in (("receivables", "应收账款", "Receivables"), ("inventory", "存货", "Inventory")):
        specs.append((field + "_pressure", _pair(zh + "资金占用", en + " intensity"),
                      _pair(f"固定最近3年逐年计算期末{zh}／全年收入；任一相邻年度比例上升即提示复核。", f"For each of the fixed latest 3 years, compare year-end {en.lower()}/annual revenue; any adjacent-year rise prompts review."),
                      _pair("核对账龄、减值和业务结构；余额／收入不是周转天数，也不能证明造假。", "Review aging, impairment and business mix; balance/revenue is not turnover days or proof of fraud."), periods3))
    checks = [_check(*spec) for spec in specs]
    if errors or specialist:
        for check in checks:
            check["status"] = "insufficient" if errors else "not_applicable"
            check["missing"] = list(errors) if errors else ["specialist_industry_or_earnings_model_required"]
            check["reason"] = _pair("主体、期间、版本或行业证据尚未通过核对，未运行普通企业阈值。", "Subject, period, version or industry evidence is not validated; ordinary-company thresholds were not run.") if errors else _pair("本行业或盈利阶段需要专项方法，未套用普通企业阈值。", "This industry or earnings stage needs a specialist method; ordinary-company thresholds were not applied.")
    else:
        c = checks[0]
        matrix = _set_evidence(c, _annual(lt, periods5, ("adjusted_profit",), cutoff))
        vals = [r[0] for r in matrix]
        known = [v for v in vals if v is not None]
        positives = sum(v > 0 for v in known)
        c["value_text"] = _pair(f"已知正值 {positives}/5 年；有值 {len(known)}/5 年", f"Known positive years {positives}/5; available years {len(known)}/5")
        if c["missing"]:
            _incomplete(c, any(v <= 0 for v in known), "已知非正年度需复核" if any(v <= 0 for v in known) else "五年固定窗口未齐", "Known nonpositive years need review" if any(v <= 0 for v in known) else "The fixed five-year window is incomplete")
        else:
            c["status"] = "pass" if positives >= 4 and vals[-1] > 0 else "fail"
            c["reason"] = _pair("完整固定窗口按扣非归母口径判断；通过不代表未来盈利稳定。", "The complete fixed window uses adjusted parent profit; a pass does not establish future earnings stability.")
        c = checks[1]
        vals = [r[0] for r in _set_evidence(c, _annual(lt, periods3, ("roe",), cutoff))]
        known = [v for v in vals if v is not None]
        if c["missing"]:
            c["value_text"] = _pair(f"已知ROE {len(known)}/3 年", f"Available ROE {len(known)}/3 years")
            bad = any(v < .08 for v in known) or sum(v < .12 for v in known) >= 2
            _incomplete(c, bad, "三年ROE未齐，已知低值仍保留关注" if bad else "三年ROE未齐", "Three-year ROE is incomplete; known low values remain a concern" if bad else "Three-year ROE is incomplete")
        else:
            med, low = median(vals), min(vals)
            c["value_text"] = _pair(f"中位数 {med:.2%}；最低 {low:.2%}", f"Median {med:.2%}; minimum {low:.2%}")
            c["status"] = "pass" if med >= .12 and low >= .08 else "fail"
            c["reason"] = _pair("仅比较披露年度ROE；未消除杠杆、权益缩小或会计差异。", "Only reported annual ROE is compared; leverage, shrinking equity and accounting differences remain unadjusted.")
        c = checks[2]
        matrix = _set_evidence(c, _annual(lt, periods3, ("op_cashflow", "net_profit"), cutoff))
        bad = any(cash is not None and cash <= 0 or profit is not None and profit < 0 for cash, profit in matrix)
        if c["missing"]:
            _incomplete(c, bad, "已知年度存在非正现金流或亏损" if bad else "现金流与合并利润未齐", "A known year has nonpositive cash flow or a loss" if bad else "Operating cash flow and consolidated profit are incomplete")
        else:
            cash, profits = sum(r[0] for r in matrix), sum(r[1] for r in matrix)
            ratio = cash / profits if profits > 0 and not any(r[1] < 0 for r in matrix) else None
            c["status"] = "pass" if not bad and ratio is not None and ratio >= .8 else "fail"
            c["value_text"] = _pair(f"累计经营现金 {cash:,.2f} 元；累计合并利润 {profits:,.2f} 元；覆盖 " + (f"{ratio:.2f} 倍" if ratio is not None else "不适用"), f"Total operating cash CNY {cash:,.2f}; total consolidated profit CNY {profits:,.2f}; coverage " + (f"{ratio:.2f}x" if ratio is not None else "not applicable"))
            c["reason"] = _pair("使用累计金额之比，不平均年度比率；单年亏损或非正现金不被累计值抵消。", "Uses the ratio of totals, not the average of annual ratios; a loss year or nonpositive cash flow is not hidden by totals.")
        _debt(checks[3], report, code, cutoff, period)
        _current(checks[4], lt, cutoff, period)
        for c, field in zip(checks[5:], ("receivables", "inventory")):
            matrix = _set_evidence(c, _annual(lt, periods3, (field, "revenue"), cutoff))
            ratios = []
            for p, (balance, revenue) in zip(periods3, matrix):
                if revenue is not None and revenue <= 0:
                    c["missing"].append(f"{p}:revenue:nonpositive_denominator")
                ratios.append(balance / revenue if balance is not None and revenue is not None and revenue > 0 else None)
            rising = any(a is not None and b is not None and b > a + 1e-12 for a, b in zip(ratios, ratios[1:]))
            text = " → ".join("—" if n is None else f"{n:.2%}" for n in ratios)
            c["value_text"] = _pair(text, text)
            if c["missing"]:
                _incomplete(c, rising, "已知相邻年度占用比例上升" if rising else "固定年度占用比例未齐", "A known adjacent-year intensity increased" if rising else "Fixed annual intensity evidence is incomplete")
            else:
                c["status"] = "watch" if rising else "pass"
                c["reason"] = _pair("存在相邻年度比例上升，需结合业务核查；不是周转率或造假判断。" if rising else "固定窗口未见相邻年度比例上升；仍需账龄、减值及业务结构核查。", "An adjacent-year intensity increased and needs business review; this is neither turnover analysis nor a fraud finding." if rising else "No adjacent-year intensity increase in the fixed window; aging, impairment and business mix remain unverified.")
    counts = {s: sum(c["status"] == s for c in checks) for s in STATUSES}
    counts["total"] = len(checks)
    status = "unavailable" if errors else "specialist" if specialist else "partial" if any(c["missing"] for c in checks) else "ready"
    summary = _pair("主体、版本、期间或行业证据不足，尚不能形成规则判断。", "Subject, version, period or industry evidence is insufficient for rule checks.") if errors else _pair("需要专项行业或盈利阶段模型，普通阈值未运行。", "A specialist industry or earnings-stage model is required; ordinary thresholds were not run.") if specialist else _pair(
        f"{counts['pass']}项满足试验规则，{counts['watch'] + counts['fail']}项需关注，{counts['insufficient']}项资料不足；这不是综合评分。",
        f"{counts['pass']} checks meet experimental rules, {counts['watch'] + counts['fail']} need attention, and {counts['insufficient']} lack evidence; this is not a composite rating.")
    notes = [
        _pair("规则为公开的试验性研究阈值，未验证收益预测能力；通过只代表该条规则满足，不代表可以买入或未来回报。", "These transparent experimental thresholds have no validated return-prediction ability; a pass applies only to that rule, not suitability to buy or future returns."),
        _pair("使用当前供应商财务版本，尚未完成官方原文逐值审计；已知公告日也不等于严格历史时点可得。", "Uses current supplier financial versions without official-document numerical audit; known publication dates do not establish strict point-in-time availability."),
        _pair("固定年度窗口不向更早年份回退；逐条只要求其所需字段，缺口不补零，已知不利证据不因其他缺项被清除。", "Fixed annual windows never roll back to older years; each check uses only required fields, gaps are not zero-filled, and known adverse evidence is retained."),
        _pair("ROIC、维持性资本开支、竞争优势与护城河尚未核实；ROE和现金流不能替代这些结论。", "ROIC, maintenance capital expenditure, competitive advantage and moat remain unverified; ROE and cash flow cannot substitute for those conclusions."),
        _pair("现有资料尚缺完整净债务／EBITDA口径，因此本项不能确认满足条件。", "Available evidence lacks a complete net-debt/EBITDA basis, so this check cannot confirm that the conditions are met."),
    ]
    if profile.get("temporal_visibility") == "current_snapshot_only_not_historical_pit":
        notes.append(_pair("行业采用当前供应商分类，仅用于当前研究路由，不能用于证明历史行业归属。", "Industry uses the current supplier classification for current research routing, not proof of historical classification."))
    return {"schema_version": VERSION, "version": VERSION, "rules_version": RULES_VERSION,
            "code": code, "as_of": cutoff, "report_date": period, "status": status,
            "summary": summary, "experimental": True, "checks": checks, "data_notes": notes, "counts": counts}
