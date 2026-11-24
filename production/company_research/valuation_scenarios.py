"""Source-linked, user-supplied three-year equity valuation scenarios.

Pure arithmetic: no provider calls, AI, persistence, defaults for assumptions,
or claim that a cited passage proves an input. Eligibility and verification of
evidence belong to the caller. Amounts and current shares are both in yi (1e8),
so their ratio is CNY per share. Equity earnings never receive a second debt
deduction or net-cash addition in this model.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import math
import re


VERSION = "valuation-scenarios-1.0"
SCENARIO_KEYS = ("conservative", "base", "optimistic")
METHODS = {"discounted_dividends", "book_simplified"}
TOP_FIELDS = {"as_of", "share_count_yi", "share_count_basis", "reference_price", "reference_date",
              "reference_basis", "method", "scenarios", "thesis", "invalidation", "evidence_refs"}
SCENARIO_FIELDS = {"key", "profits_yi", "terminal_pe", "discount_rate_pct",
                   "payout_pct", "dilution_pct", "basis"}
BASIS_FIELDS = {"earnings", "multiple", "discount", "payout", "dilution"}
EVIDENCE_FIELDS = {"source_id", "page", "quote"}


def _object(value, fields, path):
    if not isinstance(value, dict):
        raise ValueError(f"{path}: 必须是对象")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise ValueError(f"{path}: 未知字段 {', '.join(sorted(str(x) for x in unknown))}")
    if missing:
        raise ValueError(f"{path}: 缺少字段 {', '.join(sorted(missing))}")
    return value


def _text(value, path, maximum, *, empty=False):
    if not isinstance(value, str):
        raise ValueError(f"{path}: 必须是文本")
    if len(value) > maximum:
        raise ValueError(f"{path}: 文本不得超过 {maximum} 个字符")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError(f"{path}: 文本包含无效控制字符")
    value = value.strip()
    if not value and not empty:
        raise ValueError(f"{path}: 必须填写依据，不能留空")
    return value


def _number(value, path, *, low=None, high=None, positive=False):
    # JSON strings, bools and nonfinite floating-point values are not numbers.
    if type(value) not in (int, float):
        raise ValueError(f"{path}: 必须是有限数值，不能是布尔值或数字字符串")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{path}: 数值超出可计算范围") from None
    if not math.isfinite(value):
        raise ValueError(f"{path}: 必须是有限数值")
    if positive and value <= 0:
        raise ValueError(f"{path}: 必须大于零")
    if low is not None and value < low:
        raise ValueError(f"{path}: 不得小于 {low}")
    if high is not None and value > high:
        raise ValueError(f"{path}: 不得大于 {high}")
    return 0.0 if value == 0 else value


def _day(value, path):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{path}: 必须为 YYYY-MM-DD 日期")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{path}: 日期无效") from None


def _normalize(payload, today):
    raw = _object(payload, TOP_FIELDS, "payload")
    as_of = _day(raw["as_of"], "as_of")
    if as_of > today:
        raise ValueError("as_of: 研究截止日不能晚于今天")
    method = raw["method"]
    if not isinstance(method, str) or method not in METHODS:
        raise ValueError("method: 仅支持 discounted_dividends 或 book_simplified")
    result = {"as_of": as_of.isoformat(), "method": method,
              "share_count_yi": _number(raw["share_count_yi"], "share_count_yi", positive=True),
              "share_count_basis": _text(raw["share_count_basis"], "share_count_basis", 2000),
              "reference_price": None, "reference_date": None,
              "reference_basis": _text(raw["reference_basis"], "reference_basis", 2000, empty=True),
              "thesis": _text(raw["thesis"], "thesis", 4000),
              "invalidation": _text(raw["invalidation"], "invalidation", 4000)}
    price_present, date_present = raw["reference_price"] is not None, raw["reference_date"] is not None
    if price_present != date_present:
        raise ValueError("reference_price/reference_date: 报价和报价日须同时填写或同时为 null")
    if price_present:
        result["reference_price"] = _number(raw["reference_price"], "reference_price", positive=True)
        quoted = _day(raw["reference_date"], "reference_date")
        if quoted > as_of:
            raise ValueError("reference_date: 报价日不能晚于研究截止日")
        if not result["reference_basis"]:
            raise ValueError("reference_basis: 有报价时必须说明来源及价格口径")
        result["reference_date"] = quoted.isoformat()
    scenarios = raw["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) != 3:
        raise ValueError("scenarios: 必须恰好填写 conservative、base、optimistic 三个情景")
    normalized = {}
    for i, candidate in enumerate(scenarios):
        path = f"scenarios[{i}]"
        s = _object(candidate, SCENARIO_FIELDS, path)
        key = s["key"]
        if not isinstance(key, str) or key not in SCENARIO_KEYS:
            raise ValueError(f"{path}.key: 情景名称无效")
        if key in normalized:
            raise ValueError(f"{path}.key: 情景重复")
        profits = s["profits_yi"]
        if not isinstance(profits, list) or len(profits) != 3:
            raise ValueError(f"{path}.profits_yi: 必须提供未来三个连续 12 个月期间的三个归母净利润数值")
        basis = _object(s["basis"], BASIS_FIELDS, path + ".basis")
        normalized[key] = {"key": key,
            "profits_yi": [_number(x, f"{path}.profits_yi[{j}]", positive=True) for j, x in enumerate(profits)],
            "terminal_pe": _number(s["terminal_pe"], path + ".terminal_pe", positive=True),
            "discount_rate_pct": _number(s["discount_rate_pct"], path + ".discount_rate_pct", low=1, high=50),
            "payout_pct": _number(s["payout_pct"], path + ".payout_pct", low=0, high=100),
            "dilution_pct": _number(s["dilution_pct"], path + ".dilution_pct", low=0, high=100),
            "basis": {k: _text(basis[k], path + ".basis." + k, 2000) for k in sorted(BASIS_FIELDS)}}
    result["scenarios"] = [normalized[k] for k in SCENARIO_KEYS]
    refs = raw["evidence_refs"]
    if not isinstance(refs, list) or len(refs) > 30:
        raise ValueError("evidence_refs: 必须是列表，最多 30 条引用")
    result["evidence_refs"] = []
    for i, candidate in enumerate(refs):
        path = f"evidence_refs[{i}]"
        ref = _object(candidate, EVIDENCE_FIELDS, path)
        page = ref["page"]
        if type(page) is not int or not 1 <= page <= 100000:
            raise ValueError(f"{path}.page: 页码须为 1 至 100000 的整数")
        result["evidence_refs"].append({"source_id": _text(ref["source_id"], path + ".source_id", 200),
            "page": page, "quote": _text(ref["quote"], path + ".quote", 2000)})
    return result


def _finite(value, path, *, positive=False):
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{path}: 计算结果溢出或下溢，请检查数值范围")
    return value


def _calculate(scenario, current_shares, method, reference_price):
    rate = scenario["discount_rate_pct"] / 100
    dilution = scenario["dilution_pct"] / 100
    payout = scenario["payout_pct"] / 100
    yearly, dividends_pv = [], 0.0
    for year, profit in enumerate(scenario["profits_yi"], 1):
        shares = _finite(current_shares * (1 + dilution) ** year, "shares_yi", positive=True)
        dividend = _finite(profit / shares * payout, "dividend_per_share")
        dividends_pv += dividend if method == "book_simplified" else dividend / (1 + rate) ** year
        yearly.append({"year": year, "profit_yi": profit, "shares_yi": shares, "dividend_per_share": dividend})
    terminal = _finite(scenario["profits_yi"][2] / yearly[-1]["shares_yi"] * scenario["terminal_pe"] / (1 + rate) ** 3,
                       "terminal_pv_per_share", positive=True)
    dividends_pv = _finite(dividends_pv, "dividends_pv_per_share")
    value = _finite(terminal + dividends_pv, "fair_value_per_share", positive=True)
    ratio = _finite(reference_price / value, "price_to_value") if reference_price is not None else None
    return {"key": scenario["key"], "fair_value_per_share": value,
            "equity_value_yi": _finite(value * current_shares, "equity_value_yi", positive=True),
            "terminal_pv_per_share": terminal, "dividends_pv_per_share": dividends_pv,
            "margin_of_safety_pct": _finite((1 - ratio) * 100, "margin_of_safety_pct") if ratio is not None else None,
            "price_to_value": ratio, "yearly": yearly}


def evaluate(payload, *, company_code, as_of_today=None):
    """Validate all explicit assumptions and return independently auditable values.

    ``margin_of_safety_pct`` is a percentage, e.g. 25 means 25%, and may be
    negative. Both price comparisons are absent when a quote is over 7 calendar
    days old at the requested cutoff. ``as_of_today`` supports deterministic tests.
    Invalid inputs or nonfinite/underflowed arithmetic raise ``ValueError``.
    """
    if not isinstance(company_code, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", company_code):
        raise ValueError("company_code: 必须是非空且不超过 32 字符的证券标识")
    today = date.today() if as_of_today is None else as_of_today if type(as_of_today) is date else _day(as_of_today, "as_of_today")
    inputs = _normalize(payload, today)
    as_of = _day(inputs["as_of"], "as_of")
    reference = {"status": "not_provided", "price": inputs["reference_price"],
                 "date": inputs["reference_date"], "basis": inputs["reference_basis"],
                 "age_days": None, "reasons": []}
    if reference["price"] is None:
        reference["reasons"].append("未填写参考报价，不计算价格比较或安全边际。")
    else:
        reference["age_days"] = (as_of - _day(reference["date"], "reference_date")).days
        reference["status"] = "available" if reference["age_days"] <= 7 else "stale"
        if reference["status"] == "stale":
            reference["reasons"].append("参考报价距研究截止日超过 7 个自然日，保留原价但不计算价格比较或安全边际。")
    comparison_price = reference["price"] if reference["status"] == "available" else None
    scenarios = [_calculate(s, inputs["share_count_yi"], inputs["method"], comparison_price) for s in inputs["scenarios"]]
    low, base, high = [s["fair_value_per_share"] for s in scenarios]
    ordered = low <= base <= high
    warnings = ["本结果仅计算所填假设，不代表利润预测已获认证、公司质量评级、收益保证或交易指令。",
                "三个利润分别对应研究截止日起未来连续三个 12 个月期间；第 3 年末终值与年度分红使用同一归母权益口径。",
                "引用只建立材料关联，计算模块不认证引文、数字或预测假设真实性；公司资格与行业适用性由上层核查。",
                "以第 3 年归母利润乘终值 PE 估计权益价值；未再加净现金或扣债，避免重复计量。",
                "逐年摊薄按输入比例增加股数；未自动预测新增融资用途、发行现金或未来利润，相关影响须体现在假设中。"]
    if not ordered:
        warnings.append("保守、基准、乐观情景价值未依次递增；保留原标签，不以重新排序掩盖假设冲突。")
    if inputs["method"] == "book_simplified":
        warnings.append("原书简化模式仅贴现第 3 年末终值，前三年分红不贴现；与逐年贴现模式分开比较。")
    if not inputs["evidence_refs"]:
        warnings.append("尚未关联原文引用；假设依据为用户填写的文字，不能标记为已核实。")
    sensitivity = []
    base_scenario = inputs["scenarios"][1]
    for multiplier in (.8, 1.0, 1.2):
        for shift in (-2, 0, 2):
            s = deepcopy(base_scenario)
            s["terminal_pe"] = _finite(s["terminal_pe"] * multiplier, "sensitivity.terminal_pe", positive=True)
            s["discount_rate_pct"] = max(1.0, s["discount_rate_pct"] + shift)
            result = _calculate(s, inputs["share_count_yi"], inputs["method"], comparison_price)
            sensitivity.append({"pe_multiplier": multiplier, "rate_shift_pp": shift,
                "terminal_pe": s["terminal_pe"], "discount_rate_pct": s["discount_rate_pct"],
                **{k: result[k] for k in ("fair_value_per_share", "equity_value_yi", "margin_of_safety_pct", "price_to_value")}})
    return {"version": VERSION, "method": inputs["method"], "company_code": company_code,
            "as_of": inputs["as_of"], "inputs": deepcopy(inputs), "scenarios": scenarios,
            "reference": reference, "range": {"low": low, "base": base, "high": high, "ordered": ordered},
            "sensitivity": sensitivity, "warnings": warnings}
