"""Pure, source-aware annual financial analysis; no AI, network or accounting writes.

Inputs follow data.normalize: CNY yuan, decimal ratios, calendar year-end and
year-to-date flows. This module never upgrades a PDF link into verified numbers.
It retains fixed calendar windows, including holes, and refuses incompatible
or ambiguous values instead of finding a more flattering stretch of history.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import math

VERSION = "long-term-quality-1.0"
LONG_TERM_VERSION = VERSION
FIELDS = {
    "revenue": "营业收入", "net_profit": "合并净利润", "parent_profit": "归母净利润",
    "adjusted_profit": "扣非归母净利润", "op_cashflow": "合并经营现金流",
    "capex": "购建长期资产支付的现金", "receivables": "应收账款",
    "inventory": "存货", "roe": "披露ROE", "total_assets": "总资产",
    "total_liabilities": "总负债",
}
CORE = ("revenue", "net_profit", "parent_profit", "adjusted_profit", "op_cashflow", "roe")
BALANCE = {"receivables", "inventory", "total_assets", "total_liabilities"}
SPECIAL = {"bank": "银行", "insurance": "保险", "securities": "券商及其他金融", "property": "房地产", "loss_making": "亏损或非正盈利"}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return ""


def _flat(row):
    result = dict(row) if isinstance(row, dict) else {}
    for key in ("financial", "financials", "metrics"):
        if isinstance(result.get(key), dict):
            result.update(result[key])
    return result


def _unique(values):
    return list(dict.fromkeys(v for v in values if v))


def _sources(row, key=None):
    fs = row.get("field_sources") or {}
    f = fs.get(key, {}) if isinstance(fs, dict) else {}
    if isinstance(f, dict) and f.get("source_id"):
        return [str(f["source_id"])]
    return _unique(str(s) for s in (row.get("source_ids") or []) if s)


def _publication(row, key):
    field = (row.get("field_sources") or {}).get(key) or {}
    # Explicitly unknown field dates cannot borrow the latest date of a
    # different statement in a merged row.
    raw = field["announced_at"] if isinstance(field, dict) and "announced_at" in field else row.get("announced_at")
    return _date(raw) or None


def _metric(key, label, value, unit="CNY", *, status=None, note="", periods=(), source_ids=(), missing=()):
    value = _number(value)
    status = status or ("missing" if value is None else "zero" if value == 0 else "negative" if value < 0 else "available")
    return {"key": key, "label": label, "value": value, "unit": unit, "status": status,
            "note": note, "periods": list(periods), "source_ids": _unique(source_ids),
            "missing": list(missing), "verification": "supplier_only" if value is not None else "unavailable"}


def _model(company):
    text = str(company.get("industry") or "").lower()
    for key, names in (("bank", ("银行", "bank")), ("insurance", ("保险", "insurance")),
                       ("property", ("房地产", "地产开发", "real estate")),
                       ("securities", ("证券", "多元金融", "非银金融", "信托", "金融服务", "金融业", "capital markets"))):
        if any(name in text for name in names):
            return key
    profit = _number(company.get("net_profit"))
    parent = _number(company.get("parent_profit"))
    if (profit is not None and profit <= 0) or (parent is not None and parent <= 0):
        return "loss_making"
    return "general" if text else "unknown"


def _select_rows(company, history, cutoff, conflicts):
    raw_rows = [_flat(x) for x in (history or []) if isinstance(x, dict)]
    snapshot = _flat(company)
    sp = _date(snapshot.get("report_date"))
    peers = [r for r in raw_rows if _date(r.get("report_date")) == sp]
    if sp and (not peers or _date(snapshot.get("announced_at")) > max(_date(r.get("announced_at")) for r in peers)):
        raw_rows.append(snapshot)
    groups, excluded = {}, []
    for row in raw_rows:
        period, announced = _date(row.get("report_date")), _date(row.get("announced_at"))
        reason = "invalid_period" if not period else "future_period" if cutoff and period > cutoff else "future_disclosure" if cutoff and announced and announced > cutoff else None
        if reason:
            excluded.append({"report_date": period or row.get("report_date"), "announced_at": announced or None, "reason": reason, "source_ids": _sources(row)})
        else:
            groups.setdefault(period, []).append(row)
    selected = {}
    conflict_periods = {_date(c.get("report_date")) if isinstance(c, dict) else _date(c) for c in (conflicts or [])}
    for period, versions in groups.items():
        latest = max(_date(r.get("announced_at")) for r in versions)
        candidates = [r for r in versions if _date(r.get("announced_at")) == latest]
        chosen = deepcopy(candidates[0])
        bad = set(FIELDS) if period in conflict_periods else set()
        for row in candidates:
            for conflict in row.get("source_conflicts") or []:
                if isinstance(conflict, dict):
                    key = conflict.get("field") or conflict.get("key")
                    bad.update([key] if key in FIELDS else FIELDS)
                elif conflict in FIELDS:
                    bad.add(conflict)
                else:
                    bad.update(FIELDS)
        # Complementary fields in an identical version can coexist; different
        # nonmissing numbers or incompatible units at that version cannot.
        for key in FIELDS:
            vals = {_number(r.get(key)) for r in candidates if _number(r.get(key)) is not None}
            if len(vals) > 1:
                bad.add(key)
            elif vals and _number(chosen.get(key)) is None:
                source = next(r for r in candidates if _number(r.get(key)) is not None)
                chosen[key] = source[key]
                chosen.setdefault("field_sources", {})[key] = deepcopy((source.get("field_sources") or {}).get(key, {}))
            unknown = [r for r in versions if not _date(r.get("announced_at"))]
            if latest and any(_number(r.get(key)) is not None and _number(r.get(key)) != _number(chosen.get(key)) for r in unknown):
                bad.add(key)
        basis_keys = ("currency", "unit", "amount_unit", "flow_basis", "scope", "financial_scope")
        for key in basis_keys:
            values = {str(r.get(key)) for r in candidates if r.get(key) is not None}
            if len(values) > 1:
                bad.update(FIELDS)
        chosen["_conflict_fields"] = sorted(bad)
        chosen["_restatement"] = "conflict" if bad else "latest_known_publication" if len({_date(r.get("announced_at")) for r in versions}) > 1 or chosen.get("source_revisions") else "none"
        chosen["_version_count"] = len(versions)
        chosen["source_ids"] = _unique(s for r in candidates for s in _sources(r))
        selected[period] = chosen
    return selected, excluded


def _basis_issue(row, key, cutoff):
    fs = (row.get("field_sources") or {}).get(key) or {}
    if not isinstance(fs, dict):
        fs = {}
    currency = str(fs.get("currency") or row.get("currency") or "CNY").upper()
    unit = fs.get("unit", row.get("amount_unit", row.get("unit")))
    if key != "roe" and (currency not in ("CNY", "RMB", "人民币") or unit not in (None, "", "CNY", "元", "人民币元", "yuan", 1, "1")):
        return "invalid_basis", "币种或金额单位不是已标准化人民币元，未混算。"
    if key == "roe" and unit not in (None, "", "ratio", "decimal", "fraction", "CNY", "元", 1, "1"):
        return "invalid_basis", "ROE单位尚未确认是小数比例，未混算。"
    scope = fs.get("scope") or row.get("financial_scope") or row.get("scope")
    if scope not in (None, "", "consolidated", "合并"):
        return "invalid_basis", "该行并非已确认的合并报表口径。"
    basis = fs.get("flow_basis") or row.get("flow_basis")
    if key not in BALANCE and basis not in (None, "", "year_to_date", "annual", "累计", "全年"):
        return "invalid_basis", "现金及利润不是相同累计期间，未乘倍数年化或混算。"
    field_period = _date(fs.get("report_date"))
    if field_period and field_period != _date(row.get("report_date")):
        return "invalid_basis", "字段来源报告期与本行不一致。"
    if cutoff and _date(fs.get("announced_at")) > cutoff:
        return "future_disclosure", "字段来源公告晚于研究截止，未使用。"
    return None, ""


def _annual_slot(year, row, cutoff, excluded):
    period = f"{year}-12-31"
    fields, issues = {}, []
    for key, label in FIELDS.items():
        unit = "ratio" if key == "roe" else "CNY"
        value = _number(row.get(key)) if row else None
        status, note = (None, "供应商标准化值；尚未完成官方正文逐值核验。") if row else ("missing", "该固定年度无可用记录，不用更旧年度补足。")
        if row:
            if key in row.get("_conflict_fields", []):
                status, note, value = "conflict", "同报告期版本数值或口径冲突，原始值保留待核对，本项不参与计算。", None
            else:
                issue, why = _basis_issue(row, key, cutoff)
                if issue:
                    status, note, value = issue, why, None
                elif value is None:
                    status, note = "missing" if row.get(key) is None else "invalid_value", "来源未提供该项。" if row.get(key) is None else "来源不是有限有效数值，不当作零。"
                elif key == "capex" and value < 0:
                    status, note, value = "invalid_basis", "购建长期资产现金支出为负，符号定义待核对，不计算简化现金差额。", None
            if status not in (None, "missing"):
                issues.append(f"{label}：{note}")
        fields[key] = _metric(key, label, value, unit, status=status, note=note, periods=[period], source_ids=_sources(row, key) if row else [], missing=[f"{period}:{key}"] if value is None else [])
        fields[key]["announced_at"] = _publication(row, key) if row else None
    def derived(key, label, deps, calculation, unit="CNY", note=""):
        items = [fields[d] for d in deps]
        missing = [m for item in items for m in item["missing"]]
        values = [item["value"] for item in items]
        value = calculation(values) if not missing else None
        fields[key] = _metric(key, label, value, unit, status="missing" if missing else "not_applicable" if value is None else None, note=note, periods=[period], source_ids=[s for i in items for s in i["source_ids"]], missing=missing)
        fields[key]["announced_at"] = max(i["announced_at"] for i in items) if all(i.get("announced_at") for i in items) else None
    derived("simple_free_cashflow", "简化自由现金流", ("op_cashflow", "capex"), lambda v: v[0] - v[1], note="经营现金流减购建长期资产支付现金；未区分维持与扩张资本开支，不等于股东可分配现金。")
    derived("net_margin", "合并净利率", ("net_profit", "revenue"), lambda v: v[0] / v[1] if v[1] > 0 else None, "ratio", "合并净利润／营业收入；收入非正时不计算。")
    derived("debt_ratio", "资产负债率", ("total_liabilities", "total_assets"), lambda v: v[0] / v[1] if v[1] > 0 else None, "ratio", "合并总负债／合并总资产；不能替代有息债务率或可用现金覆盖。")
    missing = [key for key in FIELDS if fields[key]["value"] is None]
    complete = all(fields[key]["value"] is not None for key in CORE) and not (row and row.get("_conflict_fields"))
    status = "missing" if not row else "conflict" if row.get("_conflict_fields") else "invalid_basis" if any(x["status"] in ("invalid_basis", "future_disclosure") for x in fields.values()) else "available" if complete else "partial"
    if not row:
        issues.extend("存在尚不能使用的记录：" + x["reason"] for x in excluded if x.get("report_date") == period)
    announced = _date(row.get("announced_at")) if row else ""
    dates_known = bool(announced) and all(fields[k]["announced_at"] for k in FIELDS if fields[k]["value"] is not None)
    return {"year": year, "report_date": period, "announced_at": announced or None, "status": status,
            "complete": complete, "pit_status": "publication_date_known" if dates_known else "unknown_publication" if row else "missing",
            "restatement": row.get("_restatement", "none") if row else "none", "source_ids": _sources(row) if row else [],
            "missing": missing, "issues": _unique(issues), "fields": fields}


def _window(slots, width, model):
    rows = slots[-width:]
    periods = [r["report_date"] for r in rows]
    missing_core = [f"{r['report_date']}:{k}" for r in rows for k in CORE if r["fields"][k]["value"] is None]
    missing_core.extend(f"{r['report_date']}:unresolved_conflict" for r in rows if r["status"] == "conflict")
    metrics = []
    def compute(key, label, dependencies, formula, unit="CNY", note="", check=None):
        items = [r["fields"][d] for r in rows for d in dependencies]
        missing = _unique(m for i in items for m in i["missing"])
        matrix = [[r["fields"][d]["value"] for d in dependencies] for r in rows]
        status = "missing" if missing else None
        value = None
        if not missing:
            if check and not check(matrix):
                status = "not_applicable"
            else:
                value = formula(matrix)
                if value is None:
                    status = "not_applicable"
        item = _metric(key, label, value, unit, status=status, note=note, periods=periods, source_ids=[s for i in items for s in i["source_ids"]], missing=missing)
        metrics.append(item)
        return item
    for key in ("revenue", "net_profit", "parent_profit", "adjusted_profit", "op_cashflow", "capex", "simple_free_cashflow"):
        label = FIELDS.get(key, "简化自由现金流")
        compute(key + "_sum", f"{width}年累计{label}", [key], lambda m: sum(v[0] for v in m), note="按固定年度窗口相加；任何一年该项缺失则不报告累计。" + ("未区分维持性与扩张性开支。" if key == "simple_free_cashflow" else ""))
    compute("cash_conversion", "累计经营现金流／合并净利润", ["op_cashflow", "net_profit"], lambda m: sum(v[0] for v in m) / sum(v[1] for v in m), "multiple", "同窗累计合并经营现金流除以累计合并净利润；不使用归母利润替代，分母非正时不适用。单年亏损仍须独立核查。", lambda m: sum(v[1] for v in m) > 0)
    compute("recurring_profit", "累计扣非归母／归母净利润", ["adjusted_profit", "parent_profit"], lambda m: sum(v[0] for v in m) / sum(v[1] for v in m), "multiple", "扣非归母与归母利润配对；累计分母非正不适用；一次性损失也可能使比率超过1。", lambda m: sum(v[1] for v in m) > 0)
    compute("positive_profit_years", "合并净利润为正年度数", ["net_profit"], lambda m: sum(v[0] > 0 for v in m), "years", "严格大于零才计入；零、负和缺失分别处理，不能用已知年数冒充完整窗口。")
    compute("positive_cashflow_years", "经营现金流为正年度数", ["op_cashflow"], lambda m: sum(v[0] > 0 for v in m), "years", "严格大于零才计入。")
    compute("roe_average", "披露年度ROE算术平均", ["roe"], lambda m: sum(v[0] for v in m) / width, "ratio", "各年度披露ROE的简单平均；不是累计投入资本回报，不对季报乘倍数。")
    for key in ("revenue", "net_profit"):
        compute(key + "_cagr", FIELDS[key] + "复合年增长率", [key], lambda m: (m[-1][0] / m[0][0]) ** (1 / (width - 1)) - 1, "ratio", f"首末完整年度相隔{width - 1}年；存在非正基数或跨亏损年度时不报告CAGR。", lambda m: all(v[0] > 0 for v in m))
    for key in ("revenue", "net_profit", "receivables", "inventory"):
        item = compute(key + "_change", FIELDS[key] + "首末年度变化", [key], lambda m: m[-1][0] / m[0][0] - 1, "ratio", "首末年度相对变化；基期非正不报告百分比；期末资产与累计收入的比较仅提示核查方向。", lambda m: m[0][0] > 0)
        first, last = rows[0]["fields"][key]["value"], rows[-1]["fields"][key]["value"]
        if first is not None and last is not None and not item["missing"]:
            item["absolute_change"] = last - first
            if first <= 0:
                item["note"] += f" 首末金额差为{last - first:g}元，不能用此直接认定持续增长。"
    for key in ("receivables", "inventory"):
        compute(key + "_vs_revenue", FIELDS[key] + "变化减收入变化", [key, "revenue"], lambda m: (m[-1][0] / m[0][0] - 1) - (m[-1][1] / m[0][1] - 1), "ratio", "首末年资产增幅减同期收入增幅；正值提示资金占用可能增快，未证实回款或减值风险。基期非正不比较。", lambda m: m[0][0] > 0 and m[0][1] > 0)
    by_key = {m["key"]: m for m in metrics}
    complete = not missing_core
    findings = []
    def finding(key, label, status, support, counter, dependencies):
        items = [by_key[d] for d in dependencies]
        findings.append({"key": key, "label": label, "status": status, "support": list(support), "counter_evidence": list(counter), "periods": periods, "source_ids": _unique(s for i in items for s in i["source_ids"])})
    if model != "general":
        finding("specialist", f"{SPECIAL.get(model, '行业未确认')}：仅列可复算数值", "specialist", ["保留固定年度数字及缺口。"], ["普通工业企业的现金含量与增长阈值不用于该类公司；专项行业模型尚未完成。"], list(by_key))
    elif not complete:
        finding("coverage", f"最近{width}年核心数据未齐", "insufficient", [f"固定窗口有{sum(r['complete'] for r in rows)}/{width}个核心字段齐全年份。"], ["不能选更早年度补足，也不能从已知年度推断缺失年度。"], list(by_key))
    else:
        p, cf = by_key["positive_profit_years"]["value"], by_key["positive_cashflow_years"]["value"]
        cash, recur = by_key["cash_conversion"]["value"], by_key["recurring_profit"]["value"]
        finding("persistence", "盈利与现金持续性", "support" if p == cf == width else "mixed", [f"合并净利润为正{p:g}/{width}年，经营现金流为正{cf:g}/{width}年。"], ["连续正数不证明未来盈利稳定；须核对价格周期、客户集中与一次性事项。"], ["positive_profit_years", "positive_cashflow_years"])
        finding("cash_quality", "累计利润现金覆盖", "insufficient" if cash is None else "support" if cash >= 1 else "concern" if cash < .8 else "mixed", ["累计利润非正，比率不适用。" if cash is None else f"累计经营现金流／合并净利润为{cash:.3f}。"], ["累计值可能掩盖单年现金流背离；应收账款、存货、票据及保理口径仍需正文核查。"], ["cash_conversion"])
        finding("recurring", "扣非与归母盈利差异", "insufficient" if recur is None else "concern" if recur < .7 else "support" if recur >= .9 else "mixed", ["累计归母利润非正，比率不适用。" if recur is None else f"累计扣非归母／归母净利润为{recur:.3f}。"], ["高比率也可能来自一次性损失，不能等同主业增长；需逐项核对非经常损益。"], ["recurring_profit"])
        growth = by_key["revenue_cagr"]["value"]
        roe = by_key["roe_average"]["value"]
        finding("growth_return", "收入增长与资本回报", "insufficient" if growth is None else "support" if growth >= 0 and roe > 0 else "mixed", ["收入存在非正年度，CAGR不适用。" if growth is None else f"收入复合年增长{growth:.2%}；年度披露ROE算术平均{roe:.2%}。"], ["未做行业或周期校正，ROE可能受杠杆、回购及权益缩小影响；不等于ROIC或竞争优势。"], ["revenue_cagr", "roe_average"])
        occupied = [by_key[k + "_vs_revenue"] for k in ("receivables", "inventory")]
        finding("working_capital", "应收与存货对收入的变化", "insufficient" if any(m["value"] is None for m in occupied) else "concern" if any(m["value"] > 0 for m in occupied) else "support", [f"{m['label']}：" + ("资料不足或基数不适用。" if m["value"] is None else f"{m['value']:.2%}。") for m in occupied], ["资产时点余额与累计收入变化只用于筛查；账龄、坏账、存货跌价与收入确认尚未核实。"], ["receivables_vs_revenue", "inventory_vs_revenue"])
    return {"years": width, "periods": periods, "complete": complete,
            "available_years": sum(r["status"] != "missing" for r in rows), "complete_years": sum(r["complete"] for r in rows),
            "missing": missing_core, "metrics": metrics, "findings": findings}


def _current(selected, cutoff):
    period = max(selected, default="")
    if not period:
        return {"status": "missing", "label": "暂无最新可比期间", "report_date": None, "comparison_date": None, "seasonality_note": "缺少有效报告期。", "metrics": [], "source_ids": []}
    prior = str(int(period[:4]) - 1) + period[4:]
    current_row, previous_row = selected[period], selected.get(prior)
    slots = [_annual_slot(int(p[:4]), row, cutoff, []) for p, row in ((prior, previous_row), (period, current_row))]
    # Reuse per-field checks while retaining the actual nonannual report dates.
    for slot, actual in zip(slots, (prior, period)):
        slot["report_date"] = actual
        for field in slot["fields"].values():
            field["periods"] = [actual]
            field["missing"] = [actual + ":" + m.split(":", 1)[-1] for m in field["missing"]]
    metrics = []
    for key in ("revenue", "net_profit", "parent_profit", "adjusted_profit", "op_cashflow"):
        a, b = slots[0]["fields"][key], slots[1]["fields"][key]
        missing = a["missing"] + b["missing"]
        value = None if missing or a["value"] <= 0 else b["value"] / a["value"] - 1
        note = "本期累计值与上年同一截止期间比较，不乘倍数年化。"
        status = "missing" if missing else "not_applicable" if a["value"] <= 0 else None
        if not missing and a["value"] <= 0:
            note += "上年同期为零或负，百分比不适用；单列金额差，不能称为正常增速。"
        item = _metric(key + "_yoy", FIELDS[key] + "可比同比", value, "ratio", status=status, note=note, periods=[prior, period], source_ids=a["source_ids"] + b["source_ids"], missing=missing)
        item.update(current_value=b["value"], previous_value=a["value"], absolute_change=b["value"] - a["value"] if not missing else None)
        metrics.append(item)
    note = "仅同季累计同比，不乘2或4年化；季节性与基期异常仍需核对，不用中期结果替代全年判断。"
    known = all(s["pit_status"] == "publication_date_known" for s in slots)
    if not known:
        note += "可比期或字段公告日期不齐，不能声称通过严格历史时点核验。"
    return {"status": "available" if all(m["value"] is not None for m in metrics) else "partial" if previous_row else "missing",
            "label": "最新同年度期间比较" if period.endswith("12-31") else "最新同季累计期间比较",
            "report_date": period, "comparison_date": prior, "metrics": metrics,
            "announced_at": _date(current_row.get("announced_at")) or None,
            "comparison_announced_at": _date(previous_row.get("announced_at")) or None if previous_row else None,
            "pit_status": "publication_dates_known" if known else "unknown_publication",
            "seasonality_note": note,
            "source_ids": _unique(s for m in metrics for s in m["source_ids"])}


def analyze_long_term(company, history, *, as_of=None, documents=None, conflicts=None, industry_model=None):
    """Return the phase-one contract without modifying records or claiming audit.

    Missing ``as_of`` is inferred from the snapshot's reporting period, not the
    wall clock. Unknown announcement dates remain visible but never imply PIT.
    ``documents`` is accepted for compatibility: text/links alone do not supply
    a independently verified field, unit, currency and entity match.
    """
    company = _flat(deepcopy(company))
    cutoff = _date(as_of or company.get("as_of"))
    selected, excluded = _select_rows(company, history, cutoff, conflicts)
    if cutoff:
        anchor = int(cutoff[:4]) - 1
        anchor_reason = f"按研究截止{cutoff}固定最近已结束自然年度{anchor}；年报可能尚未披露，缺年不向旧年回退。"
    else:
        latest = max(selected, default="")
        anchor = int(latest[:4]) - (0 if latest.endswith("12-31") else 1) if latest else None
        anchor_reason = "研究截止缺失，按最新有效报告期推断年度窗口；不能声称严格历史时点可用。"
    # Stage classification must not use a future snapshot's profit signs when
    # analyzing an earlier cutoff. Industry identity remains metadata; earnings
    # come from the latest report that survived the same visibility checks.
    classification = dict(company)
    visible = selected[max(selected)] if selected else {}
    for key in ("net_profit", "parent_profit"):
        classification[key] = visible.get(key) if key not in visible.get("_conflict_fields", []) and not _basis_issue(visible, key, cutoff)[0] else None
    model = industry_model if industry_model not in (None, "general", "loss_making") else _model(classification)
    slots = [_annual_slot(y, selected.get(f"{y}-12-31"), cutoff, excluded) for y in range(anchor - 4, anchor + 1)] if anchor else []
    windows = [_window(slots, width, model) for width in (3, 5)] if slots else []
    consecutive = 0
    for row in reversed(slots):
        if not row["complete"]:
            break
        consecutive += 1
    unknown_publication = any(r["pit_status"] == "unknown_publication" for r in slots if r["status"] != "missing")
    coverage = {"target_years": 5, "available_years": sum(r["status"] != "missing" for r in slots),
                "complete_years": sum(r["complete"] for r in slots), "consecutive_years": consecutive,
                "missing_years": [r["year"] for r in slots if r["status"] == "missing"],
                "official_verified_values": 0, "available_values": sum(r["fields"][k]["value"] is not None for r in slots for k in FIELDS),
                "pit_status": "unknown_publication" if unknown_publication or not cutoff else "publication_dates_known"}
    has_conflict = any(r["status"] == "conflict" for r in slots)
    status = "specialist" if model != "general" else "conflict" if has_conflict else "insufficient" if consecutive < 3 else "conditional"
    if status == "specialist":
        label = f"{SPECIAL.get(model, '行业未确认')}：多年数字可查，专项评价待完成"
    elif status == "conflict":
        label = "固定年度存在冲突，暂不形成多年判断"
    elif status == "insufficient":
        label = "最近连续完整年度不足3年，暂不形成多年判断"
    else:
        usable = windows[-1] if windows[-1]["complete"] else windows[0]
        evidence = [f["status"] for f in usable["findings"]]
        adjective = "偏弱或存在背离" if evidence.count("concern") >= 2 else "混合，仍有核查事项" if "concern" in evidence or "mixed" in evidence else "较稳，仍需核验"
        label = f"近{usable['years']}年财务表现{adjective}（供应商数据条件下）"
    limitations = [
        "第一阶段仅形成多年财务质量；治理、竞争优势、债务期限和完整估值尚未核清，不能形成完整公司好坏或买入结论。",
        "所有逐年数值当前为供应商数据，尚未完成官方原文逐值核验；财报PDF链接、正文可读取或页码存在均不等于数值已核实。",
        "数值按现有适配器的人民币元、比例小数、合并累计口径计算；未提供单位元数据不等于从官方正文核验了单位。",
        "最近3年与5年固定窗口不向旧年回退；核心完整性要求收入、合并利润、归母利润、扣非归母、经营现金及ROE均有可用值，其他缺口逐项显示。",
        "历史为供应商当前版本，可能有追溯调整；已知公告日期也不代表已证明供应商数据在当时可获取，不能用作严格PIT回测结论。",
        "简化自由现金流仅为经营现金流减购建长期资产现金支出，未识别维持性资本开支或股东可分配现金。",
        "普通公司阈值属于解释性研究规则，未验证为股票收益预测能力。",
    ]
    if unknown_publication or not cutoff:
        limitations.append("部分公告日期或研究截止未知；允许展示供应商现版数值，但不能声称通过严格历史时点验证。")
    if consecutive < 5:
        limitations.append(f"最近连续核心数据齐全年份为{consecutive}/5；完整5年目标尚未满足。")
    if excluded:
        limitations.append(f"排除{len(excluded)}条未来报告期、未来公告或无效期间记录；详见排除记录。")
    return {"version": VERSION, "status": status, "label": label, "industry_model": model,
            "anchor_year": anchor, "anchor_reason": anchor_reason, "as_of": cutoff or None,
            "coverage": coverage, "years": slots, "windows": windows,
            "current_period": _current(selected, cutoff), "limitations": limitations, "excluded": excluded}
