"""Explainable company research rules. Amounts are CNY, all ratios are decimals.

This is an unvalidated research-priority rubric, not a return forecast or trading
model. It deliberately refuses a score when material evidence is missing.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import math
from statistics import median
from .long_term import analyze_long_term
from .debt_data import ADAPTER_VERSION as DEBT_ADAPTER_VERSION, enrich_debt_bundle
from .debt_governance import build_debt_governance
from .business_data import build_business_view
from .industry_data import build_industry_view, apply_industry_policy_to_report

ENGINE_VERSION = "company-research-rules-1.2"
FINANCIAL_FIELDS = ("revenue", "parent_profit", "net_profit", "adjusted_profit",
    "op_cashflow", "roe", "gross_margin", "debt_ratio", "revenue_yoy", "profit_yoy",
    "total_assets", "total_liabilities", "cash", "interest_debt", "capex", "eps",
    "bvps", "pe_ttm", "pb")


def number(value):
    """None/NaN/booleans are missing; a legitimate zero is never missing."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _flat(row):
    if not isinstance(row, dict):
        return {}
    out = dict(row)
    for key in ("financial", "financials", "metrics"):
        if isinstance(row.get(key), dict):
            out.update(row[key])
    return out


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return ""


def _history(rows, as_of=None):
    """Latest published restatement wins; never sum repeated reporting periods."""
    cutoff = _date(as_of)
    periods, conflicts = {}, []
    for raw in rows or []:
        row = _flat(raw)
        period = _date(row.get("report_date"))
        announced = _date(row.get("announced_at"))
        if not period or (cutoff and (period > cutoff or (announced and announced > cutoff))):
            continue
        old = periods.get(period)
        if old and announced == _date(old.get("announced_at")):
            changed = [k for k in FINANCIAL_FIELDS if number(old.get(k)) != number(row.get(k))]
            if changed:
                conflicts.append(period)
                continue
        if old is None or announced > _date(old.get("announced_at")):
            periods[period] = row
    return [periods[k] for k in sorted(periods)], sorted(set(conflicts))


def _industry(company):
    industry = str(company.get("industry") or "")
    lower = industry.lower()
    for model, terms in (("bank", ("银行", "bank")),
                         ("insurance", ("保险", "insurance")),
                         ("property", ("房地产", "地产开发", "real estate")),
                         ("securities", ("证券", "多元金融", "非银金融", "信托", "金融服务", "金融业", "capital markets"))):
        if any(term in lower for term in terms):
            return model
    profit = number(company.get("net_profit"))
    if profit is None:
        profit = number(company.get("parent_profit"))
    if profit is not None and profit <= 0:
        return "loss_making"
    return "general"


def _ratio(numerator, denominator, positive=True):
    if numerator is None or denominator is None or denominator == 0:
        return None
    if positive and denominator < 0:
        return None
    return numerator / denominator


def _peer_values(company, peers, key):
    # Compare identical industries and report periods; do not mix banks with factories.
    industry = company.get("industry")
    if not industry:
        return []
    result, seen = [], set()
    for raw in peers or []:
        p = _flat(raw)
        code = p.get("code")
        if not code or code == company.get("code") or code in seen:
            continue
        if p.get("industry") != industry or _date(p.get("report_date")) != _date(company.get("report_date")):
            continue
        if _industry(p) != _industry(company):
            continue
        if key in ("pe_ttm", "pb") and p.get("valuation_as_of") != company.get("valuation_as_of"):
            continue
        value = number(p.get(key))
        if value is not None and (key not in ("pe_ttm", "pb") or value > 0):
            result.append(value)
            seen.add(code)
    return result


def _flag(code, text, level="medium", fields=()):
    return {"code": code, "message": text, "level": level, "fields": list(fields)}


def screen_company(company, peers=None):
    """Return JSON-safe screening summary for a canonical company financial row.

    history/as_of are optional. No call mutates the caller's records. eligible means
    'priority for research', never permission to buy or a claim of company quality.
    """
    c = _flat(deepcopy(company))
    history, conflicts = _history(c.get("history"), c.get("as_of"))
    # Correct a snapshot with a newer publication of the SAME period only.
    for old in history:
        if _date(old.get("report_date")) == _date(c.get("report_date")) and _date(old.get("announced_at")) > _date(c.get("announced_at")):
            c.update({k: v for k, v in old.items() if k not in ("code", "name", "industry", "history")})
    model = _industry(c)
    f = {key: number(c.get(key)) for key in FINANCIAL_FIELDS}
    flags, missing, metrics = [], [], []
    if c.get("listing_unverified"):
        flags.append(_flag("listing_unverified", "尚未在本次核验的存续A股名单中确认该证券，不能列入候选。", "high"))
    if conflicts:
        flags.append(_flag("conflicting_period", "同一报告期和公告日的数值冲突，需核对重述版本。", "high"))
    if c.get("source_conflicts"):
        flags.append(_flag("source_conflict", "同报告期来源存在未解决的字段冲突，需核对原始披露；暂停初筛评分。", "high"))
    if not _date(c.get("report_date")):
        flags.append(_flag("missing_period", "缺少有效报告期，不能确认指标口径。", "high"))
    if not _date(c.get("announced_at")):
        missing.append("announced_at")
    if not c.get("industry"):
        missing.append("industry")
    if _date(c.get("as_of")) and _date(c.get("announced_at")) > _date(c.get("as_of")):
        flags.append(_flag("future_disclosure", "公告晚于本次研究截止时间，不能使用。", "high"))
    if any(x in str(c.get("name", "")).upper() for x in ("*ST", "ST", "退")) or c.get("special_treatment"):
        flags.append(_flag("special_treatment", "证券简称或标记提示风险警示/退市事项，必须先核实。", "high"))
    opinion = str(c.get("audit_opinion") or "")
    if opinion and opinion not in ("标准无保留意见", "无保留意见", "unqualified", "standard unqualified"):
        flags.append(_flag("audit_opinion", "审计意见不是明确的标准无保留意见，需阅读审计报告。", "high"))
    for key, label in (("going_concern", "持续经营重大不确定性"), ("default", "债务违约"), ("fraud_investigation", "涉嫌财务违规调查")):
        if c.get(key) is True:
            flags.append(_flag(key, label + "：单项财务高分不能抵消该风险。", "high"))
    if f["total_assets"] is not None and f["total_liabilities"] is not None and f["total_assets"] <= f["total_liabilities"]:
        flags.append(_flag("negative_equity", "合并总资产不高于总负债。", "high", ("total_assets", "total_liabilities")))
    if f["net_profit"] is not None and f["net_profit"] <= 0:
        flags.append(_flag("loss", "合并净利润非正，常规现金净利比和市盈率不适用。", "medium", ("net_profit",)))
    if f["parent_profit"] is not None and f["parent_profit"] <= 0:
        flags.append(_flag("parent_loss", "归母净利润非正，股东盈利和市盈率需专项研究。", "medium", ("parent_profit",)))
    # Derived ratios keep consolidated cash flow paired with consolidated net profit.
    cash_conversion = _ratio(f["op_cashflow"], f["net_profit"])
    margin = _ratio(f["net_profit"], f["revenue"])
    recurring = _ratio(f["adjusted_profit"], f["parent_profit"])
    debt_ratio = f["debt_ratio"]
    if debt_ratio is None:
        debt_ratio = _ratio(f["total_liabilities"], f["total_assets"])
    f["debt_ratio"] = debt_ratio
    if cash_conversion is not None and cash_conversion < 0.5 and model == "general":
        flags.append(_flag("weak_cash_conversion", "合并经营现金流低于合并净利润的一半，需核查季节性、应收和存货。", "medium", ("op_cashflow", "net_profit")))
    if recurring is not None and recurring < 0.7:
        flags.append(_flag("nonrecurring_profit", "扣非归母净利润占归母净利润较低，需核对非经常损益。", "medium", ("adjusted_profit", "parent_profit")))
    if f["cash"] is not None and f["interest_debt"] is not None and f["cash"] < f["interest_debt"] * 0.3 and model in ("general", "loss_making"):
        flags.append(_flag("cash_debt_gap", "货币资金对有息债务覆盖较低；该指标未区分受限现金和债务期限。", "medium", ("cash", "interest_debt")))
    if f["profit_yoy"] is not None and f["profit_yoy"] < -0.3:
        flags.append(_flag("profit_fall", "归母利润同比明显下降，应结合上年基数和本期异常项目。", "medium", ("profit_yoy",)))
    source_ids = c.get("source_ids") or [str(s.get("id")) for s in c.get("sources", []) if isinstance(s, dict) and s.get("id")]

    def metric(key, label, value, unit, explanation, weight=0, score=None, peer_count=0):
        dependencies = {"cash_conversion": ["op_cashflow", "net_profit"], "net_margin": ["net_profit", "revenue"],
            "recurring_profit": ["adjusted_profit", "parent_profit"]}.get(key, [key])
        if key == "debt_ratio" and number(c.get("debt_ratio")) is None:
            dependencies = ["total_assets", "total_liabilities"]
        field_sources = [c.get("field_sources", {}).get(k, {}) for k in dependencies]
        specific_ids = list(dict.fromkeys(str(s["source_id"]) for s in field_sources if s.get("source_id")))
        metrics.append({"key": key, "label": label, "value": value, "unit": unit,
            "explanation": explanation, "weight": weight, "score": score,
            "covered": score is not None, "peer_count": peer_count, "source_ids": specific_ids or list(source_ids),
            "fields": dependencies,
            "report_date": c.get("report_date")})
        if value is None:
            missing.append(key)

    if model == "general":
        peer_roe = _peer_values(c, peers, "roe")
        annual = str(c.get("report_date", "")).endswith("12-31")
        roe_score = None
        roe_note = "报告期ROE；季度/半年累计值不乘倍数年化。"
        if f["roe"] is not None and len(peer_roe) >= 5:
            roe_score = 100 * (sum(x < f["roe"] for x in peer_roe) + 0.5 * sum(x == f["roe"] for x in peer_roe)) / len(peer_roe)
            roe_note += "评分来自相同行业、相同报告期的同行分位。"
        elif f["roe"] is not None and annual:
            roe_score = 100 if f["roe"] >= .15 else 70 if f["roe"] >= .10 else 40 if f["roe"] >= .05 else 0
            roe_note += "无充足同行，按披露的年度ROE研究阈值评分。"
        else:
            roe_note += "缺少同报告期同行，ROE项不计分。"
        metric("roe", "资本回报", f["roe"], "ratio", roe_note, 20, roe_score, len(peer_roe))
        metric("net_margin", "合并净利率", margin, "ratio", "合并净利润/营业收入，仅用于研究筛查。", 10,
               None if margin is None else 100 if margin >= .15 else 70 if margin >= .08 else 40 if margin > 0 else 0)
        growth = f["revenue_yoy"]
        metric("revenue_yoy", "收入同比", growth, "ratio", "本期累计收入相对上年相同期间；不乘2或4。", 15,
               None if growth is None else 100 if growth >= .10 else 75 if growth >= .03 else 50 if growth >= 0 else 20 if growth > -.10 else 0)
        metric("cash_conversion", "利润现金含量", cash_conversion, "multiple", "合并经营现金流/合并净利润；不以归母净利润替代分母。单期受季节性影响。", 25,
               None if cash_conversion is None else 100 if cash_conversion >= 1 else 75 if cash_conversion >= .8 else 40 if cash_conversion >= .5 else 0)
        metric("debt_ratio", "资产负债率", debt_ratio, "ratio", "总负债/总资产；含经营负债，并非有息债务率。", 20,
               None if debt_ratio is None or debt_ratio < 0 else 100 if debt_ratio <= .35 else 75 if debt_ratio <= .55 else 40 if debt_ratio <= .70 else 0)
        metric("recurring_profit", "扣非盈利占比", recurring, "multiple", "扣非归母净利润/归母净利润；一次性损失也会使比率超过1。", 10,
               None if recurring is None else 100 if recurring >= .9 else 65 if recurring >= .7 else 30 if recurring > 0 else 0)
    else:
        # Sector checklists deliberately do not convert incomplete specialist data
        # into a generic ranking. Supplying all fields still requires peer research.
        special = {
            "bank": [("npl_ratio", "不良贷款率"), ("provision_coverage", "拨备覆盖率"), ("capital_adequacy", "资本充足率"), ("net_interest_margin", "净息差")],
            "insurance": [("core_solvency", "核心偿付能力"), ("comprehensive_solvency", "综合偿付能力"), ("nbv_growth", "新业务价值增速"), ("investment_yield", "投资收益率")],
            "property": [("restricted_cash", "受限现金"), ("short_debt", "短期有息债务"), ("contract_liabilities", "合同负债"), ("inventory_impairment", "存货减值")],
            "securities": [("net_capital", "净资本"), ("risk_coverage", "风险覆盖率"), ("liquidity_coverage", "流动性覆盖率")],
            "loss_making": [("cash", "货币资金"), ("interest_debt", "有息债务"), ("op_cashflow", "经营现金流"), ("capex", "资本开支")],
        }
        for key, label in special[model]:
            metric(key, label, number(c.get(key)), "CNY" if key in ("restricted_cash", "short_debt", "contract_liabilities", "inventory_impairment", "net_capital", "cash", "interest_debt", "op_cashflow", "capex") else "ratio", "专用行业核查项；不套用普通工业公司的评分阈值。")
        flags.append(_flag("specialist_review", "该行业或盈利阶段进入专项研究队列，暂不参与普通公司质量排名。", "info"))
    for key, label, unit in (("revenue", "营业收入", "CNY"), ("net_profit", "合并净利润", "CNY"),
            ("parent_profit", "归母净利润", "CNY"), ("op_cashflow", "合并经营现金流", "CNY"),
            ("profit_yoy", "归母利润同比", "ratio"), ("pe_ttm", "市盈率TTM", "multiple"), ("pb", "市净率", "multiple")):
        if key not in {m["key"] for m in metrics}:
            metric(key, label, f[key], unit, "来源披露值；期次和单位见资料。")
    covered = sum(m["weight"] for m in metrics if m["covered"])
    earned = sum(m["weight"] * m["score"] / 100 for m in metrics if m["covered"])
    high_risk = any(x["level"] == "high" for x in flags)
    # A partial 60/60 is not transformed into a deceptively perfect 100/100.
    quality_score = round(earned, 1) if covered >= 80 and model == "general" and c.get("industry") and not high_risk else None
    if high_risk:
        label = "重大事项待核查"
    elif model != "general":
        label = "专项研究，暂不评分"
    elif quality_score is None:
        label = "资料不足，暂不评分"
    elif quality_score >= 75:
        label = "财务初筛较强，待深度核查"
    elif quality_score >= 55:
        label = "财务表现混合，需进一步核查"
    else:
        label = "财务初筛偏弱"
    risk_level = "high" if high_risk else "medium" if any(x["level"] == "medium" for x in flags) else "unknown"
    pe = f["pe_ttm"]
    values = _peer_values(c, peers, "pe_ttm")
    # PE is not meaningful for nonpositive parent earnings, even if stale PE exists.
    if pe is None or pe <= 0 or (f["parent_profit"] is not None and f["parent_profit"] <= 0):
        valuation_label = "市盈率缺失或不适用，暂不能判断价格"
    elif len(values) >= 5 and c.get("valuation_as_of"):
        mid = median(values)
        valuation_label = "市盈率低于可比同行中位数，仍需核查增长与风险" if pe < mid * .8 else "市盈率高于可比同行中位数，需更强增长支撑" if pe > mid * 1.2 else "市盈率接近可比同行中位数"
    else:
        valuation_label = "已有估值数值，缺少足够同口径同行，暂不判断贵贱"
    eligible = quality_score is not None and quality_score >= 65 and not high_risk
    reason = "进入深度研究候选，不是买入建议。" if eligible else "先处理风险、补齐资料或采用专项行业研究。"
    return {"code": str(c.get("code", "")), "name": str(c.get("name", "")), "industry": c.get("industry"),
        "report_date": c.get("report_date"), "announced_at": c.get("announced_at"),
        "quality_score": quality_score, "quality_label": label, "valuation_label": valuation_label,
        "risk_level": risk_level, "flags": flags, "metrics": metrics, "missing": sorted(set(missing)),
        "industry_model": model, "eligible": eligible, "reason": reason,
        "coverage_weight": covered, "total_weight": 100, "earned_points": round(earned, 1),
        "history_periods": len(history), "engine_version": ENGINE_VERSION,
        "method": "公开、未做收益有效性验证的财务研究初筛；缺项不填零、不重分配权重。"}


def analyze_company(bundle, peers=None):
    """Build a deterministic report. A separate AI result must be labelled as AI."""
    bundle = deepcopy(bundle)
    company = _flat(bundle.get("company") or bundle)
    if isinstance(bundle.get("financial"), dict):
        company.update(bundle["financial"])
    raw_history = bundle.get("history") or company.get("history") or []
    history, conflicts = _history(raw_history, bundle.get("as_of"))
    company["history"] = history
    if bundle.get("as_of"):
        company["as_of"] = bundle["as_of"]
    if not company.get("report_date") and history:
        company.update({k: v for k, v in history[-1].items() if k not in ("code", "name", "industry")})
    summary = screen_company(company, peers)
    if conflicts and not any(f["code"] == "conflicting_period" for f in summary["flags"]):
        summary["flags"].append(_flag("conflicting_period", "历史同一期同公告日数据冲突，需核查。", "high"))
        summary.update(quality_score=None, eligible=False, risk_level="high", quality_label="重大事项待核查")
    sources = []
    seen = set()
    for s in bundle.get("sources", []) + bundle.get("documents", []):
        if not isinstance(s, dict) or not s.get("id") or str(s["id"]) in seen:
            continue
        seen.add(str(s["id"]))
        sources.append({"id": str(s["id"]), "title": s.get("title", "财务数据来源"),
            "url": s.get("url"), "published_at": s.get("published_at"),
            "pages": [p.get("page") for p in s.get("pages", []) if isinstance(p, dict) and p.get("text")]})
    annual = [x for x in history if str(x.get("report_date", "")).endswith("12-31")]
    cash_rows = [x for x in annual if number(x.get("op_cashflow")) is not None and number(x.get("net_profit")) is not None]
    # Only contiguous complete fiscal years are eligible for multi-year cash conversion.
    years = [int(x["report_date"][:4]) for x in cash_rows]
    multi_cash = None
    if len(cash_rows) >= 3 and years == list(range(years[0], years[-1] + 1)):
        multi_cash = _ratio(sum(number(x["op_cashflow"]) for x in cash_rows), sum(number(x["net_profit"]) for x in cash_rows))
    limitations = ["质量分是财务研究优先级，不是好坏公司的最终判决，未通过样本外收益检验。",
        "估值与质量分别判断；未预测股票回报、给出交易指令或目标价。",
        "供应商财务字段需与原始财报核对；本报告不是审计意见。",
        "未确认治理、护城河、关联交易和审计附注时，不能自动认定这些方面良好。",
        "经营现金流与合并净利润配对；扣非利润与归母净利润配对。"]
    limitations.extend(str(w) for w in bundle.get("warnings", []) if w and str(w) not in limitations)
    if len(annual) < 3:
        limitations.append("不足三份完整年度记录，不能判断长期稳定性。")
    if not any(s["pages"] for s in sources):
        limitations.append("尚无可逐页核对的财报正文；AI不得补造页码或声称已精读。")
    debt_as_of = _date(bundle.get("as_of") or company.get("as_of")) or date.today().isoformat()
    debt_records = bundle.get("debt_financial_records") or []
    debt_records_current = (bundle.get("debt_adapter_version") == DEBT_ADAPTER_VERSION
        and isinstance(debt_records, list)
        and all(isinstance(row, dict) and row.get("adapter_version") == DEBT_ADAPTER_VERSION for row in debt_records))
    debt_input = {**bundle, "company": deepcopy(company)}
    debt_section = build_debt_governance(enrich_debt_bundle(debt_input,
        debt_records if debt_records_current else [], as_of=debt_as_of), as_of=debt_as_of)
    debt_section["data_recovery"] = {"mode": "normalized_bundle",
        "adapter_version": DEBT_ADAPTER_VERSION,
        "status": "provided" if debt_records_current and debt_records else "unavailable",
        "sources": [], "gaps": [] if debt_records_current and debt_records else [{"code": "normalized_records_unavailable_or_outdated"}],
        "coverage": {"normalized_records": len(debt_records) if debt_records_current else 0,
                     "raw_hashes_rechecked": False, "debt_scope_complete": False}}
    report = {"schema_version": 1, "engine_version": ENGINE_VERSION,
        "company": {k: v for k, v in company.items() if k not in ("history", "documents")},
        "summary": summary,
        "debt_governance": debt_section,
        "business_capital": build_business_view(debt_input, as_of=debt_as_of, industry_model=summary["industry_model"]),
        "quality": {"score": summary["quality_score"], "label": summary["quality_label"],
            "coverage_weight": summary["coverage_weight"], "total_weight": 100,
            "metrics": summary["metrics"], "annual_periods": len(annual),
            "multi_year_cash_conversion": multi_cash, "multi_year_cash_periods": [x["report_date"] for x in cash_rows] if multi_cash is not None else [],
            "history": history,
            "long_term": analyze_long_term(company, raw_history, as_of=bundle.get("as_of") or company.get("as_of"),
                documents=bundle.get("documents"), industry_model=summary["industry_model"])},
        "valuation": {"label": summary["valuation_label"], "pe_ttm": number(company.get("pe_ttm")),
            "pb": number(company.get("pb")), "as_of": company.get("valuation_as_of"),
            "note": "同行相对估值不是内在价值；盈利周期、成长和会计政策仍需分析。"},
        "risks": summary["flags"], "evidence": sources, "limitations": limitations,
        "ai": {"status": "not_requested", "message": "以上为确定性财务计算，尚未调用AI。"}}

    return apply_industry_policy_to_report(report, build_industry_view(bundle, as_of=bundle.get("as_of") or company.get("as_of")))
