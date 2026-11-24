"""Continuous, current-snapshot peer references; never a quality/profit forecast.

The input contract is the canonical A-share rows after the existing industry
gate. This module does not fetch, persist, run AI, or mutate those rows. Absent
scope on that established CNY/year-to-date contract means consolidated, as in
data.normalize; an explicit unknown/conflicting scope is never defaulted away.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date
import hashlib
import json
import math
import re

VERSION = "dynamic-financial-1.0"
MIN_PEERS = 5
METHOD = ("按相同细行业、报告期、币种和财务口径，对照至少5家其他可比公司；"
          "以同业中位数及四分位间距连续换算，六项齐全才按原权重合成。"
          "50表示同业中位附近，不是合格线、百分位或胜率。"
          "ROE及增长按原报告期使用，不将季度或半年值年化。"
          "仅为当前供应商快照的研究参考，未完成官方逐值核验、严格历史时点验证或收益回测；"
          "不替代绝对风险、多年财务和价格判断。")
SPECS = (
    ("roe", "ROE", 20, 1, .01),
    ("net_margin", "净利率", 10, 1, .01),
    ("revenue_yoy", "营收同比", 15, 1, .02),
    ("cash_conversion", "经营现金/合并利润", 25, 1, .1),
    ("debt_ratio", "资产负债率", 20, -1, .05),
    ("recurring_profit", "扣非归母/归母利润", 10, 1, .05),
)
FIELDS = ("roe", "revenue", "net_profit", "parent_profit", "adjusted_profit",
          "op_cashflow", "revenue_yoy", "debt_ratio", "total_assets",
          "total_liabilities", "cash", "interest_debt", "profit_yoy")
SPECIALISTS = {"bank", "insurance", "securities", "property", "cyclical", "financial_unresolved"}
CURRENCIES = {"CNY", "HKD", "USD", "EUR", "GBP", "JPY", "CHF", "SGD", "AUD", "CAD", "TWD", "KRW", "NZD"}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return (0.0 if value == 0 else value) if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _unique(values):
    return list(dict.fromkeys(values))


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return _number(numerator / denominator)


def _basis(row):
    currency = _text(row.get("currency"))
    flow = _text(row.get("flow_basis"))
    period = _date(row.get("report_date"))
    if flow in ("annual", "全年") and period and period.endswith("12-31"):
        flow = "year_to_date"
    if flow == "累计":
        flow = "year_to_date"
    canonical = currency == "CNY" and flow == "year_to_date"
    scope = row.get("scope", row.get("statement_scope", "consolidated" if canonical else None))
    scope = {"合并": "consolidated"}.get(scope, scope) if isinstance(scope, str) else None
    standard = row.get("accounting_standard", "CAS" if canonical else None)
    standard = {"中国企业会计准则": "CAS", "Chinese GAAP": "CAS", "US GAAP": "US_GAAP"}.get(standard, standard) if isinstance(standard, str) else None
    unit = row.get("amount_unit", "currency_units" if canonical else None)
    unit = {"元": "currency_units", "人民币元": "currency_units", "CNY": "currency_units"}.get(unit, unit) if isinstance(unit, str) else None
    start = row.get("period_start", period[:4] + "-01-01" if period and flow == "year_to_date" else None)
    result = {"currency": currency, "flow_basis": flow, "scope": scope,
              "accounting_standard": standard, "amount_unit": unit, "period_start": _date(start)}
    valid = (currency in CURRENCIES and flow == "year_to_date" and scope == "consolidated"
             and standard in {"CAS", "IFRS", "US_GAAP"} and unit == "currency_units"
             and period is not None and result["period_start"] == period[:4] + "-01-01")
    return result, valid


def _field(row, key, basis, cutoff):
    sources = row.get("field_sources")
    source = sources.get(key) if isinstance(sources, dict) else None
    source = source if isinstance(source, dict) else {}
    period, published = _date(source.get("report_date")), _date(source.get("announced_at"))
    known = bool(_text(source.get("source_id")))
    # Source batch IDs, hashes, URLs and fetch timestamps are deliberately absent
    # from the financial fingerprint: re-fetching equal facts is not a change.
    meta = {"source_known": known, "field": _text(source.get("field")),
            "report_date": period, "announced_at": published,
            "status": _text(source.get("status"))}
    issues = []
    if _number(row.get(key)) is None:
        issues.append("指标原始数值缺失或无效")
    if not known:
        issues.append("指标来源未确认")
    if not period or not published:
        issues.append("指标报告期或公告日期未确认")
    elif period != _date(row.get("report_date")):
        issues.append("指标报告期与公司报告期不一致")
    elif published < period:
        issues.append("指标公告日期早于报告期")
    elif period > cutoff or published > cutoff:
        issues.append("指标报告或公告晚于评价截止日")
    if meta["status"] in {"conflict", "metadata_invalid", "missing", "unavailable"}:
        issues.append("指标来源存在冲突或无效标记")
    if "status" in source and source["status"] is not None and meta["status"] is None:
        issues.append("指标来源存在冲突或无效标记")
    # Explicit metadata has precedence over the canonical row contract.
    for name in ("currency", "flow_basis", "scope", "accounting_standard", "amount_unit", "period_start"):
        if name in source:
            meta[name] = _text(source[name])
            if source[name] != basis.get(name):
                issues.append("指标币种或财务口径不一致")
    return meta, _unique(issues)


def _risks(row, values):
    flags = []
    screen = row.get("screen") if isinstance(row.get("screen"), dict) else {}

    def add(key, label, severity="high"):
        flags.append({"key": key, "severity": severity, "label": label})

    for flag in screen.get("flags", []) if isinstance(screen.get("flags"), list) else []:
        if not isinstance(flag, dict):
            continue
        key = _text(flag.get("code")) or _text(flag.get("key"))
        if key:
            add(key, _text(flag.get("message")) or _text(flag.get("label")) or key,
                _text(flag.get("level")) or _text(flag.get("severity")) or "medium")
    if _text(screen.get("risk_level")) in {"high", "高", "高风险"}:
        add("screen_high_risk", "原财务筛查已识别高风险，需先核查")
    if row.get("listing_unverified"):
        add("listing_unverified", "存续A股身份尚未核验")
    if row.get("source_conflicts") or ("source_conflicts" in row and not isinstance(row["source_conflicts"], (list, type(None)))):
        add("source_conflict", "财务来源存在未解决冲突")
    if row.get("special_treatment") or any(x in str(row.get("name") or "").upper() for x in ("ST", "退")):
        add("special_treatment", "风险警示或退市事项需核查")
    opinion = _text(row.get("audit_opinion"))
    if opinion and opinion not in {"标准无保留意见", "无保留意见", "unqualified", "standard unqualified"}:
        add("audit_opinion", "审计意见需专项核查")
    for key, label in (("going_concern", "持续经营重大不确定性"), ("default", "债务违约"), ("fraud_investigation", "财务违规调查")):
        if row.get(key) is True:
            add(key, label)
    assets, liabilities = values["total_assets"], values["total_liabilities"]
    if assets is not None and liabilities is not None and assets <= liabilities:
        add("negative_equity", "合并总资产不高于总负债")
    for key in ("net_profit", "parent_profit"):
        if values[key] is not None and values[key] <= 0:
            add(key + "_nonpositive", "合并或归母盈利非正，不适用普通同行换算", "medium")
    if values["debt_ratio"] is not None and values["debt_ratio"] < 0:
        add("invalid_debt_ratio", "资产负债率为负，需核对数值口径")
    # Preserve existing medium flags without inventing an overall 'safe' status.
    return sorted({(f["key"], f["severity"], f["label"]): f for f in flags}.values(),
                  key=lambda x: (x["key"], x["severity"], x["label"]))


def _prepare(row, cutoff):
    code = row.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"(?:[03468]\d{5}|92\d{4})", code):
        return None
    screen = row.get("screen") if isinstance(row.get("screen"), dict) else {}
    gate = screen.get("industry_applicability")
    gate = gate if isinstance(gate, dict) else {}
    industry = _text(row.get("industry"))
    period, published = _date(row.get("report_date")), _date(row.get("announced_at"))
    basis, basis_ok = _basis(row)
    numbers = {k: _number(row.get(k)) for k in FIELDS}
    meta, field_gaps = {}, {}
    for key in FIELDS:
        meta[key], field_gaps[key] = _field(row, key, basis, cutoff)
    derived = {"roe": numbers["roe"], "net_margin": _ratio(numbers["net_profit"], numbers["revenue"]),
               "revenue_yoy": numbers["revenue_yoy"], "cash_conversion": _ratio(numbers["op_cashflow"], numbers["net_profit"]),
               "debt_ratio": numbers["debt_ratio"], "recurring_profit": _ratio(numbers["adjusted_profit"], numbers["parent_profit"])}
    dependencies = {"roe": ("roe",), "net_margin": ("net_profit", "revenue"), "revenue_yoy": ("revenue_yoy",),
                    "cash_conversion": ("op_cashflow", "net_profit"), "debt_ratio": ("debt_ratio",),
                    "recurring_profit": ("adjusted_profit", "parent_profit")}
    if derived["debt_ratio"] is None:
        derived["debt_ratio"] = _ratio(numbers["total_liabilities"], numbers["total_assets"])
        dependencies["debt_ratio"] = ("total_assets", "total_liabilities")
    flags = _risks(row, numbers)
    gaps = []
    expected_exchange = "SH" if code.startswith("6") else "SZ" if code.startswith(("0", "3")) else "BJ"
    if "exchange" in row and row["exchange"] != expected_exchange:
        gaps.append("证券代码与交易所不一致")
    if not industry or industry in {"未知", "其他", "全部行业", "unknown"}:
        gaps.append("细分行业未确认")
    if not period or not published:
        gaps.append("公司报告期或公告日期未确认")
    elif period > cutoff or published > cutoff:
        gaps.append("公司报告或公告晚于评价截止日")
    elif published < period:
        gaps.append("公司公告日期早于报告期")
    if not basis_ok:
        gaps.append("币种或财务口径未确认或不适用")
    if not (gate.get("general_ranking_allowed") is True and gate.get("model") == "general"):
        gaps.append("行业门控未明确允许普通财务排名")
    gate_date = _date(gate.get("as_of"))
    if gate_date and gate_date > cutoff:
        gaps.append("行业判定晚于评价截止日")
    if any(numbers[k] is None or numbers[k] <= 0 for k in ("net_profit", "parent_profit")):
        gaps.append("合并及归母盈利均为正的条件未满足")
    if any(field_gaps[k] for k in ("net_profit", "parent_profit")):
        gaps.append("盈利来源、日期或口径未确认")
    high = any(f["severity"] == "high" for f in flags)
    if high:
        gaps.append("存在已识别高风险，需先核查")
    metric_gaps = {}
    for key, _, _, _, _ in SPECS:
        issues = [issue for dep in dependencies[key] for issue in field_gaps[dep]]
        if derived[key] is None:
            issues.append("指标数值或正分母条件不足")
        if key == "debt_ratio" and derived[key] is not None and derived[key] < 0:
            issues.append("负债率数值无效")
        metric_gaps[key] = _unique(issues)
    state = "risk_review" if high or any(numbers[k] is not None and numbers[k] <= 0 for k in ("net_profit", "parent_profit")) else "specialist" if _text(gate.get("model")) in SPECIALISTS else "insufficient" if gaps else "ready"
    material = {"version": VERSION, "code": code, "industry": industry, "report_date": period,
                "announced_at": published, "basis": basis, "financials": numbers, "field_evidence": meta,
                "applicability": {"allowed": gate.get("general_ranking_allowed") is True, "model": _text(gate.get("model")),
                                  "earnings_status": _text(gate.get("earnings_status"))},
                "risk_flags": flags, "input_gaps": gaps, "metric_gaps": metric_gaps}
    return {"code": code, "industry": industry, "report_date": period, "announced_at": published,
            "basis": basis, "legacy_score": _number(screen.get("quality_score")), "values": derived,
            "metric_gaps": metric_gaps, "gaps": gaps, "state": state, "flags": flags, "high": high,
            "fingerprint": _digest(material), "material": material}


def _quantile(items, q, omitted=None):
    """Linear (type-7) quantile, removing self without re-sorting each issuer."""
    removed = bisect_left(items, omitted) if omitted is not None else len(items)
    if removed == len(items) or items[removed] != omitted:
        removed = len(items)
    size = len(items) - (removed < len(items))
    position = (size - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    left = items[lo + (lo >= removed)][0]
    right = items[hi + (hi >= removed)][0]
    # Weighted sum avoids overflow from (right-left) for opposite extremes.
    part = position - lo
    return left * (1 - part) + right * part


def build_market_evaluations(rows, *, as_of):
    """Return deterministic current peer references keyed by strict A-share code.

    Equal duplicate financial rows collapse to one identity. Conflicting rows
    for the same identity all leave the peer pool, with an explicit risk result.
    An invalid cutoff is an API error; malformed individual rows are isolated.
    """
    cutoff = _date(as_of)
    if not cutoff:
        raise ValueError("as_of must be a valid YYYY-MM-DD date")
    by_code = defaultdict(list)
    for row in rows:
        if isinstance(row, dict):
            prepared = _prepare(row, cutoff)
            if prepared:
                by_code[prepared["code"]].append(prepared)
    companies = {}
    for code, copies in by_code.items():
        fingerprints = sorted({c["fingerprint"] for c in copies})
        chosen = min(copies, key=lambda c: (c["fingerprint"], c["legacy_score"] if c["legacy_score"] is not None else -1))
        if len(fingerprints) > 1:
            chosen["gaps"].append("同一证券存在冲突记录，已从同行样本排除")
            chosen["flags"].append({"key": "duplicate_identity", "severity": "high", "label": "同一证券存在冲突记录"})
            chosen.update(state="risk_review", high=True,
                          fingerprint=_digest({"version": VERSION, "code": code, "conflicting_inputs": fingerprints}))
        companies[code] = chosen
    groups = defaultdict(list)
    for c in companies.values():
        c["group"] = (c["industry"], c["report_date"], tuple(sorted(c["basis"].items())))
        if c["state"] == "ready":
            groups[c["group"]].append(c)
    sorted_groups, metric_pools = {}, {}
    for group, members in groups.items():
        members.sort(key=lambda c: c["code"])
        sorted_groups[group] = members
        metric_pools[group] = {key: sorted((c["values"][key], c["code"]) for c in members
                                         if not c["metric_gaps"][key]) for key, *_ in SPECS}
    results = {}
    for code in sorted(companies):
        c = companies[code]
        peers = [p for p in sorted_groups.get(c["group"], []) if p["code"] != code]
        peer_fp = _digest({"version": VERSION, "peers": [(p["code"], p["fingerprint"]) for p in peers]})
        metrics = []
        for key, label, weight, direction, minimum in SPECS:
            value = c["values"][key]
            pool = metric_pools.get(c["group"], {}).get(key, [])
            own_in_pool = c["state"] == "ready" and not c["metric_gaps"][key]
            count = len(pool) - own_in_pool
            gaps = _unique(c["gaps"] + c["metric_gaps"][key])
            if count < MIN_PEERS:
                gaps.append("同口径可用其他公司不足5家")
            item = {"key": key, "label": label, "value": value, "unit": "decimal", "weight": weight,
                    "peer_count": count, "peer_median": None, "p25": None, "p75": None,
                    "scale": None, "score": None, "contribution": None, "gaps": gaps}
            if not gaps:
                omitted = (value, code) if own_in_pool else None
                p25, middle, p75 = (_quantile(pool, q, omitted) for q in (.25, .5, .75))
                # Inputs are finite, but IQR/difference can overflow on malicious
                # synthetic extremes. Reject arithmetic failure instead of NaN.
                scale = max(p75 - p25, abs(middle) * .1, minimum)
                if not math.isfinite(scale):
                    item["gaps"].append("同行数值尺度超出可计算范围")
                else:
                    distance = value / scale / 2 - middle / scale / 2
                    score = 50 + 50 * math.tanh(direction * distance)
                    item.update(peer_median=middle, p25=p25, p75=p75, scale=scale,
                                score=round(score, 6), contribution=round(score * weight / 100, 6))
            metrics.append(item)
        available = sum(m["score"] is not None for m in metrics)
        state = c["state"] if c["state"] != "ready" else "ready" if available == len(SPECS) else "insufficient"
        gaps = list(c["gaps"])
        if state == "insufficient" and available < len(SPECS):
            gaps.append("六项可比资料未齐全，暂不合成同行财务参考")
        results[code] = {"version": VERSION, "code": code, "status": state,
            "relative_score": round(sum(m["contribution"] for m in metrics), 4) if state == "ready" else None,
            "legacy_score": c["legacy_score"], "industry": c["industry"], "report_date": c["report_date"],
            "announced_at": c["announced_at"], "as_of": cutoff, "peer_count": min(m["peer_count"] for m in metrics),
            "coverage": {"available_metrics": available, "total_metrics": len(SPECS)}, "metrics": metrics,
            "risk": {"status": "identified_high_risk" if c["high"] else "review_required", "flags": c["flags"]},
            "evidence": {"status": "supplier_snapshot", "official_verified": False, "historical_pit_usable": False},
            "company_fingerprint": c["fingerprint"], "peer_fingerprint": peer_fp,
            "input_fingerprint": _digest({"version": VERSION, "company": c["fingerprint"], "peers": peer_fp}),
            "gaps": gaps, "method": METHOD}
    return results
