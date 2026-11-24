"""Pure industry applicability policy, not a sector rating or data feed.

No network/AI, file writes, company-code exceptions, currency inference or risk
clearance. A source identifier establishes provenance, not numerical verification.
"""
from copy import deepcopy
from datetime import date, datetime
import math
import re

VERSION = INDUSTRY_POLICY_VERSION = "industry-policy-1.0"
CURRENCIES = {"CNY", "HKD", "USD", "EUR", "GBP", "JPY", "CHF", "SGD", "AUD", "CAD", "TWD", "KRW", "NZD"}
ALIASES = {
    "bank": {"银行", "商业银行", "bank", "banks"},
    "insurance": {"保险", "保险业", "insurance", "人寿保险", "财产保险"},
    "securities": {"证券", "证券公司", "证券业", "securities", "capital markets"},
    "property": {"房地产", "房地产开发", "地产开发", "real estate development"},
    "cyclical": {"煤炭", "煤炭开采", "钢铁", "有色金属", "石油石化", "航运", "基础化工"},
    "general": {"食品饮料", "食品制造", "调味品", "软件开发", "计算机软件"},
}
FINANCIAL_AMBIGUOUS = {"多元金融", "非银金融", "金融服务", "金融业", "综合金融", "信托", "信托公司", "金融控股公司", "其他金融", "financial services"}
NONFINANCIAL_TYPES = {"通用", "一般企业", "非金融企业", "非金融", "nonfinancial", "non-financial"}
LABELS = {"bank": "银行", "insurance": "保险", "securities": "证券公司", "property": "房地产开发",
          "cyclical": "周期行业候选", "general": "普通非金融", "financial_unresolved": "金融业务类型待核实", "unknown": "行业待核实"}


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _known(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"unknown", "not_verified", "unverified", "n/a", "none", "null", "未知", "待核查"}


def _current_classification_visible(supplied, cutoff, purpose):
    observed = supplied.get("observed_at")
    try:
        observed_date = datetime.fromisoformat(observed.replace("Z", "+00:00")).date() if isinstance(observed, str) else None
    except ValueError:
        observed_date = None
    return bool(purpose == "current_research" and cutoff is not None
        and supplied.get("temporal_basis") == "supplier_current_snapshot"
        and observed_date is not None and observed_date <= cutoff and _known(supplied.get("source_id"))
        and supplied.get("report_type") == "RPT_F10_ORG_BASICINFO"
        and supplied.get("raw_field") == "BOARD_NAME_2LEVEL" and _known(supplied.get("raw_value"))
        and supplied.get("mapping_version") == "eastmoney-current-industry-1.0"
        and isinstance(supplied.get("sha256"), str) and re.fullmatch(r"[a-fA-F0-9]{64}", supplied["sha256"]))


def _classify(company, cutoff, purpose="historical_as_of"):
    candidates, evidence, issues = set(), [], []
    explicit_block = None
    supplied = company.get("industry_classification")
    if isinstance(supplied, dict):
        model = supplied.get("model")
        if model in ("unknown", "financial_unresolved"):
            published = _date(supplied.get("announced_at"))
            if not cutoff or not published or published <= cutoff:
                explicit_block = model
                issues.append("explicit_classification_unresolved")
                if _current_classification_visible(supplied, cutoff, purpose):
                    evidence.append(deepcopy(supplied))
                    issues.append("current_supplier_classification_not_historical_pit")
        elif model in ALIASES and _known(supplied.get("source_id")):
            published = _date(supplied.get("announced_at"))
            current = _current_classification_visible(supplied, cutoff, purpose)
            if current:
                candidates.add(model)
                evidence.append(deepcopy(supplied))
                issues.append("current_supplier_classification_not_historical_pit")
            elif not published or (cutoff and published > cutoff):
                issues.append("classification_not_visible_at_cutoff")
                explicit_block = "unknown"
            else:
                candidates.add(model)
                evidence.append(deepcopy(supplied))
        else:
            issues.append("invalid_explicit_classification")
            explicit_block = "unknown"
    elif "industry_classification" in company:
        explicit_block = "unknown"
        issues.append("explicit_classification_unresolved")
    metadata = company.get("classification_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for key in ("financial_type", "industry"):
        raw = str(company.get(key) or "").strip().lower()
        if not raw:
            continue
        matching = {model for model, labels in ALIASES.items() if raw in labels}
        if raw in FINANCIAL_AMBIGUOUS:
            issues.append("financial_subsector_unresolved")
        elif key == "financial_type" and not matching and raw not in NONFINANCIAL_TYPES:
            issues.append("financial_type_unrecognized")
            explicit_block = "unknown"
        if matching:
            published = _date(metadata.get("announced_at"))
            if not _known(metadata.get("source_id")):
                issues.append("classification_source_unknown")
            elif not published or (cutoff and published > cutoff):
                issues.append("classification_not_visible_at_cutoff")
            else:
                candidates.update(matching)
                evidence.append({"field": key, "raw_value": raw, "source_id": metadata.get("source_id"),
                                 "announced_at": metadata.get("announced_at"), "verification": "label_mapping_only"})
    if explicit_block:
        model = explicit_block
    elif len(candidates) > 1:
        model = "unknown"
        issues.append("classification_conflict")
    elif "financial_subsector_unresolved" in issues and not candidates.intersection({"bank", "insurance", "securities"}):
        model = "financial_unresolved"
    elif candidates:
        model = next(iter(candidates))
        # A broad label cannot disprove a specifically identified licensed entity.
    else:
        model = "financial_unresolved" if "financial_subsector_unresolved" in issues else "unknown"
    return {"model": model, "label": LABELS[model], "candidates": sorted(candidates),
            "evidence": evidence, "issues": sorted(set(issues)),
            "verification": "classification_provenance_only"}


def _spec(label, unit="decimal", scopes=("consolidated",), regulatory=False, subtype=None):
    return {"label": label, "unit": unit, "scopes": list(scopes), "regulatory": regulatory, "subtype": subtype}


REGULATORY_BANK = ("regulatory_consolidated", "regulated_bank_solo")
SPECS = {
    "bank": {
        "npl_ratio": _spec("不良贷款率"), "provision_coverage": _spec("拨备覆盖率"),
        "capital_adequacy": _spec("资本充足率", scopes=REGULATORY_BANK, regulatory=True),
        "cet1_ratio": _spec("核心一级资本充足率", scopes=REGULATORY_BANK, regulatory=True),
        "net_interest_margin": _spec("净息差"),
    },
    "insurance": {
        "core_solvency": _spec("核心偿付能力充足率", scopes=("regulated_insurer",), regulatory=True),
        "comprehensive_solvency": _spec("综合偿付能力充足率", scopes=("regulated_insurer",), regulatory=True),
        "nbv_growth": _spec("新业务价值增速", subtype="life"),
        "combined_ratio": _spec("综合成本率", subtype="pnc"),
        "investment_yield": _spec("投资收益率（须指明净/总/综合口径）"),
    },
    "securities": {
        "net_capital": _spec("净资本", "money", ("regulated_securities_solo",), True),
        "risk_coverage": _spec("风险覆盖率", scopes=("regulated_securities_solo",), regulatory=True),
        "liquidity_coverage": _spec("流动性覆盖率", scopes=("regulated_securities_solo",), regulatory=True),
        "net_stable_funding": _spec("净稳定资金率", scopes=("regulated_securities_solo",), regulatory=True),
    },
    "property": {
        "restricted_cash": _spec("受限货币资金", "money"),
        "contract_liabilities": _spec("合同负债（不能替代有息债务或已确认收入）", "money"),
        "inventory_impairment": _spec("存货减值（须区分余额与本期计提）", "money"),
        "sales_collections": _spec("销售回款（不能替代营业收入）", "money"),
        "project_guarantees": _spec("项目担保披露额（不等于完整风险敞口）", "money"),
    },
    "cyclical": {
        "capacity_utilization": _spec("产能利用率"),
        "unit_selling_price": _spec("产品单位售价", "explicit"),
        "unit_cash_cost": _spec("产品单位现金成本", "explicit"),
        "maintenance_capex": _spec("已明确区分的维持性资本开支", "money"),
    },
}


def _fact(key, spec, facts, company, cutoff, subtype):
    base = {"key": key, **deepcopy(spec), "value": None, "status": "missing_field", "issues": [],
            "verification": "numerical_semantics_not_verified", "provenance": None}
    if spec["subtype"] and subtype not in (spec["subtype"], "mixed"):
        base["status"] = "not_applicable" if subtype in ("life", "pnc") else "subtype_required"
        return base
    if key not in facts:
        return base
    raw = facts[key]
    if not isinstance(raw, dict):
        base["status"] = "missing_metadata"
        return base
    base["provenance"] = deepcopy(raw)
    if subtype == "mixed" and spec["subtype"] and raw.get("segment_type") != spec["subtype"]:
        base["status"] = "segment_required"
        return base
    if "value" not in raw:
        base["status"] = "missing_value_key"
        return base
    if raw["value"] is None:
        base["status"] = "disclosed_null"
        return base
    value = _num(raw["value"])
    if value is None:
        if isinstance(raw["value"], float) and not math.isfinite(raw["value"]):
            base["provenance"]["value"] = None
            base["provenance"]["invalid_value_repr"] = repr(raw["value"])
        base["status"] = "invalid_number"
        return base
    problems = []
    if not _known(raw.get("source_id")):
        problems.append("missing_source")
    if not _known(raw.get("definition_id")):
        problems.append("missing_definition")
    if not _known(company.get("issuer_id")) or raw.get("subject_id") != company["issuer_id"]:
        problems.append("subject_unknown_or_mismatch")
    if raw.get("scope") not in spec["scopes"]:
        problems.append("scope_mismatch")
    period, published = _date(raw.get("report_date")), _date(raw.get("announced_at"))
    if not period:
        problems.append("invalid_period")
    if not published:
        problems.append("unknown_publication")
    if period and published and published < period:
        problems.append("publication_before_period_end")
    if cutoff and ((period and period > cutoff) or (published and published > cutoff)):
        problems.append("future_information")
    if company.get("report_date") and raw.get("report_date") != company["report_date"]:
        problems.append("different_period")
    if spec["regulatory"] and not _known(raw.get("regime_id")):
        problems.append("regulatory_regime_unknown")
    unit = raw.get("unit")
    if spec["unit"] == "decimal" and unit != "decimal":
        problems.append("ratio_unit_not_decimal")
    if spec["unit"] == "money":
        if unit != "currency_units" or raw.get("currency") not in CURRENCIES:
            problems.append("money_basis_unknown")
    if spec["unit"] == "explicit" and (not _known(unit) or unit in ("money", "explicit")):
        problems.append("physical_unit_unknown")
    if problems:
        base.update(status="unusable_basis", issues=problems)
    else:
        base.update(value=value, status="zero" if value == 0 else "observed")
    return base


def _modules(model, earnings):
    general = model == "general"
    positive = earnings == "positive"
    loss = earnings == "loss_making"
    finance = model in ("bank", "insurance", "securities", "financial_unresolved")
    def item(status, reason):
        return {"status": status, "reason": reason}
    result = {
        "governance": item("applicable_with_evidence", "逐主体、期次与状态核查；未检索监管公告不能判定无风险。"),
        "general_screen": item("conditional" if general and positive else "not_applicable", "普通六指标阈值仅适用于已明确普通非金融且正盈利的公司；本模块不评分。"),
        "long_term": item("conditional" if general and positive else "raw_trends_only", "保留年度事实；专项业务、亏损或周期未校正时不套持续性评分。"),
        "debt_liquidity": item("specialist_required" if finance or model == "unknown" else "conditional", "金融负债和客户资金需专用口径；非金融复用阶段2完整债务/受限现金/期限契约。"),
        "cash_conversion": item("not_applicable" if finance or not positive or model == "unknown" else "context_only" if model in ("property", "cyclical") else "conditional", "金融经营现金流包含核心资产负债扩张；地产受预售和交付影响；周期须跨周期观察。"),
        "gross_margin": item("not_applicable" if finance or model == "unknown" else "context_only" if model in ("property", "cyclical") else "conditional", "保险/银行不能套工业毛利率；地产看结算与减值，周期看产品价格和成本。"),
        "capital_allocation": item("specialist_required" if finance or model == "unknown" else "conditional", "金融应检查监管资本和分配限制；普通资本开支/经营现金比不通用。"),
        "valuation": item("specialist_required", "留待阶段5；周期峰值PE、账面折价或监管资本达标均不构成买入建议。"),
    }
    if loss:
        result["pe"] = item("not_applicable", "归母/合并利润已知非正，旧正PE不能替代可用盈利。")
    return result


def _earnings(company, cutoff):
    """A merged statement date cannot make an explicitly undated field visible."""
    result = {}
    raw_sources = company.get("field_sources")
    sources = raw_sources
    sources = sources if isinstance(sources, dict) else {}
    source_ids = company.get("source_ids")
    source_ids = source_ids if isinstance(source_ids, list) else []
    raw_conflicts = company.get("source_conflicts")
    conflicts = raw_conflicts if isinstance(raw_conflicts, list) else []
    for key in ("net_profit", "parent_profit"):
        field = sources.get(key)
        field = field if isinstance(field, dict) else {}
        raw_period = field["report_date"] if "report_date" in field else company.get("report_date")
        raw_publication = field["announced_at"] if "announced_at" in field else company.get("announced_at")
        period, published = _date(raw_period), _date(raw_publication)
        if "source_id" in field:
            source_known = _known(field["source_id"])
        else:
            source_known = any(_known(x) for x in source_ids)
        value, issues = _num(company.get(key)), []
        if cutoff is None:
            issues.append("profit_cutoff_unknown")
        if (("field_sources" in company and not isinstance(raw_sources, dict)) or
            (key in sources and not isinstance(sources[key], dict)) or
            (raw_conflicts is not None and not isinstance(raw_conflicts, list))):
            issues.append("profit_metadata_invalid")
        if value is None:
            issues.append("profit_unknown")
        if not source_known:
            issues.append("profit_source_unknown")
        if not period or not published:
            issues.append("profit_dates_unknown")
        elif published < period:
            issues.append("profit_publication_before_period")
        if period and raw_period != company.get("report_date"):
            issues.append("profit_period_mismatch")
        if cutoff and ((period and period > cutoff) or (published and published > cutoff)):
            issues.append("profit_not_visible_at_cutoff")
        if (field.get("status") in {"conflict", "metadata_invalid"} or any(
            (c.get("field") or c.get("key")) == key if isinstance(c, dict) else c == key for c in conflicts)):
            issues.append("profit_conflict")
        result[key] = {"value": None if issues else value, "issues": issues, "report_date": raw_period,
                       "announced_at": raw_publication, "verification": "source_metadata_only"}
    values = [x["value"] for x in result.values()]
    state = "loss_making" if any(v is not None and v <= 0 for v in values) else "positive" if all(v is not None and v > 0 for v in values) else "unknown"
    return state, result


def build_industry_profile(company, *, as_of=None, purpose="historical_as_of"):
    """Route modules and preserve source-bound specialist observations.

    company.industry_classification can supply a model+source_id+announced_at;
    vendor labels use exact matches only. Historical routing requires dated
    classification_metadata. 'loss_making' is an overlay, never a bank subtype.
    Specialist values must be explicit fact objects; no generic scalar aliases.
    """
    from .dynamic_data import _copy_view_data
    company = _copy_view_data(company)
    cutoff = _date(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        raise ValueError("as_of must be a valid YYYY-MM-DD date")
    if purpose not in {"historical_as_of", "current_research"}:
        raise ValueError("purpose must be current_research or historical_as_of")
    classification = _classify(company, cutoff, purpose)
    model = classification["model"]
    earnings, earnings_basis = _earnings(company, cutoff)
    loss = earnings == "loss_making"
    subtype = next((e.get("insurance_business") for e in classification["evidence"]
                    if e.get("model") == "insurance"), None)
    facts = company.get("specialist_facts")
    facts = facts if isinstance(facts, dict) else {}
    observations = [_fact(k, s, facts, company, cutoff, subtype) for k, s in SPECS.get(model, {}).items()]
    current = "current_supplier_classification_not_historical_pit" in classification["issues"]
    return {"version": VERSION, "status": "applicability_only", "as_of": as_of,
            "research_purpose": purpose, "historical_pit_usable": False,
            "temporal_visibility": "current_snapshot_only_not_historical_pit" if current else "checked_against_cutoff" if cutoff else "cutoff_not_supplied",
            "classification": classification,
            "overlays": ["loss_making"] if loss else [], "earnings_status": earnings, "earnings_basis": earnings_basis, "modules": _modules(model, earnings),
            "specialist_observations": observations, "rating": None, "investment_recommendation": None,
            "coverage": {"observed_fields": sum(x["value"] is not None for x in observations), "required_fields": len(observations),
                         "officially_verified_numbers": 0, "regulatory_compliance": "not_assessed"},
            "limitations": ["行业路由通过不代表该行业已开放上线；指标齐全也不自动给综合分。",
                "监管实体、并表范围、规则版本必须保留，禁止合并集团数据顶替子公司偿付/净资本口径。",
                "周期候选需行业与产品证据确认完整周期，固定5年不等于覆盖完整周期。",
                "来源匹配未完成数值、表头、单位和期间的语义复核。"]}


def compare_reporting_basis(left, right, *, monetary=True, same_issuer=False, as_of=None):
    """Conservative A/H or peer comparison gate, not FX conversion or period resampling.

    Explicit fiscal spans permit March/June year ends. Ratios still require the
    same metric definition, accounting standard and consolidation scope. Explicit
    measurement_kind/measurement_basis prevent a caller flag bypassing money or
    unit checks. Comparability is metadata-only, distinct from PIT visibility.
    """
    problems, visibility_issues = [], []
    cutoff = _date(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        raise ValueError("as_of must be a valid YYYY-MM-DD date")
    for side, row in (("left", left), ("right", right)):
        start, end = _date(row.get("period_start")), _date(row.get("period_end"))
        period_type = row.get("period_type")
        if not start or not end or start > end:
            problems.append(side + ":invalid_period_span")
        else:
            days = (end-start).days+1
            if period_type == "annual" and not 350 <= days <= 380:
                problems.append(side + ":nonstandard_annual_duration")
            elif period_type == "half_year" and not 170 <= days <= 196:
                problems.append(side + ":nonstandard_half_year_duration")
            elif period_type == "quarter" and not 80 <= days <= 100:
                problems.append(side + ":nonstandard_quarter_duration")
            elif period_type == "instant" and days != 1:
                problems.append(side + ":instant_has_duration")
            elif period_type == "year_to_date":
                if not 1 <= days <= 380:
                    problems.append(side + ":nonstandard_ytd_duration")
                if _date(row.get("fiscal_year_start")) != start:
                    problems.append(side + ":ytd_fiscal_start_unknown_or_mismatch")
        for key in ("accounting_standard", "scope", "definition_id", "period_type"):
            if not _known(row.get(key)):
                problems.append(side + ":missing_" + key)
        if period_type not in {"annual", "half_year", "quarter", "year_to_date", "instant"}:
            problems.append(side + ":unsupported_period_type")
        if row.get("accounting_standard") not in {"IFRS", "HKFRS", "ASBE", "CAS", "US_GAAP"}:
            problems.append(side + ":unsupported_accounting_standard")
        if row.get("scope") not in {"consolidated", "parent_only", "regulatory_consolidated", "regulated_bank_solo", "regulated_insurer", "regulated_securities_solo"}:
            problems.append(side + ":unsupported_scope")
        if str(row.get("scope", "")).startswith(("regulatory_", "regulated_")) and not _known(row.get("regime_id")):
            problems.append(side + ":regulatory_regime_unknown")
        kind, basis = row.get("measurement_kind"), row.get("measurement_basis")
        if kind not in {"money", "ratio"}:
            problems.append(side + ":unsupported_measurement_kind")
        if basis not in {"instant", "duration"}:
            problems.append(side + ":unsupported_measurement_basis")
        elif (period_type == "instant") != (basis == "instant"):
            problems.append(side + ":period_measurement_basis_mismatch")
        if (kind == "money") != bool(monetary):
            problems.append(side + ":monetary_argument_conflicts_with_kind")
        if kind == "money":
            if row.get("reporting_currency") not in CURRENCIES:
                problems.append(side + ":unsupported_reporting_currency")
            if row.get("amount_unit") not in {"units", "thousands", "millions", "billions"}:
                problems.append(side + ":unsupported_amount_unit")
        elif kind == "ratio" and row.get("unit") not in {"decimal", "percent", "multiple"}:
            problems.append(side + ":unsupported_ratio_unit")
        if cutoff:
            published = _date(row.get("announced_at"))
            if not published:
                visibility_issues.append(side + ":publication_unknown")
            if end and published and published < end:
                visibility_issues.append(side + ":publication_before_period_end")
            if (end and end > cutoff) or (published and published > cutoff):
                visibility_issues.append(side + ":future_information")
    for key in ("accounting_standard", "scope", "definition_id", "period_type", "measurement_kind", "measurement_basis"):
        if left.get(key) != right.get(key):
            problems.append(key + "_mismatch")
    if any(str(row.get("scope", "")).startswith(("regulatory_", "regulated_")) for row in (left, right)):
        if left.get("regime_id") != right.get("regime_id"):
            problems.append("regulatory_regime_mismatch")
    if (left.get("period_start"), left.get("period_end")) != (right.get("period_start"), right.get("period_end")):
        problems.append("different_reporting_spans")
    if left.get("measurement_kind") == "money" or right.get("measurement_kind") == "money":
        for key in ("reporting_currency", "amount_unit"):
            if left.get(key) != right.get(key):
                problems.append(key + "_mismatch_requires_explicit_conversion")
    if left.get("measurement_kind") == "ratio" or right.get("measurement_kind") == "ratio":
        if left.get("unit") != right.get("unit"):
            problems.append("ratio_unit_mismatch_requires_explicit_conversion")
    if same_issuer and (not _known(left.get("issuer_id")) or not _known(right.get("issuer_id")) or left.get("issuer_id") != right.get("issuer_id")):
        problems.append("issuer_identity_unresolved")
    return {"comparable": not problems, "issues": problems, "fx_performed": False,
            "annualized": False, "listing_currency_used": False, "as_of": as_of,
            "temporal_visibility": "not_assessed" if cutoff is None else "not_visible" if visibility_issues else "visible_at_cutoff",
            "visibility_issues": visibility_issues,
            "usable_at_cutoff": None if cutoff is None else not problems and not visibility_issues,
            "verification": "metadata_comparison_only", "officially_verified_numbers": 0}
