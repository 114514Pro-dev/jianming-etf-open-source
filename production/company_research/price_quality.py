"""Isolated repeatable price references and evidence checklist; no score or DCF.

The existing six-factor screen is copied verbatim. This module never calls a
model/network, changes a saved report, or promotes source metadata to verification.
All temporal decisions use the caller's explicit cutoff; no wall clock is read.
"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

VERSION = "price-quality-1.0"
DEFAULT_POLICY = {"max_quote_age_calendar_days": 7, "max_financial_period_age_calendar_days": 550, "minimum_comparable_peers": 5}
ACCOUNTING_STANDARDS = {"CAS", "ASBE", "IFRS", "HKFRS", "US_GAAP"}
CURRENCIES = {"CNY", "HKD", "USD"}
COMPARABILITY_KEYS = ("market", "industry_key", "quote_currency", "financial_currency", "valuation_basis")
BASIS_KEYS = ("provider", "accounting_standard", "scope", "share_basis")
METRIC_BASIS = {"pe_ttm": ("pe_definition", "TTM_parent_earnings", "earnings_period_start", "earnings_period_end"),
                "pb": ("pb_definition", "MRQ_parent_common_equity", None, "book_period_end")}
_MISSING = object()


def _obj(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _known(value):
    return isinstance(value, str) and value == value.strip() and bool(value) and value.lower() not in {"unknown", "n/a", "null", "none", "unspecified"}


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?", value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if len(value) > 10 else date.fromisoformat(value)
    except ValueError:
        return None


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def _text(number):
    return format(number, "f") if number is not None else None


def _raw(record, key):
    value = record.get(key, _MISSING)
    number = _num(value) if value is not _MISSING else None
    state = "absent" if value is _MISSING else "null" if value is None else "invalid" if number is None else "zero" if number == 0 else "reported_value"
    return {"value": _text(number), "state": state, "source_ref": deepcopy(_obj(_obj(record.get("sources")).get(key))),
            "verification": "supplier_reference_not_official_numeric_verification"}


def _profile_issues(profile, cutoff, purpose="historical_as_of"):
    p = _obj(profile)
    if p.get("version") != "industry-policy-1.0":
        return ["industry_profile_missing_or_unsupported"]
    issues = []
    model = _obj(p.get("classification")).get("model")
    if model != "general":
        issues.append("industry_specialist_required" if model and model != "unknown" else "industry_unknown")
    if p.get("earnings_status") != "positive":
        issues.append("nonpositive_earnings" if p.get("earnings_status") == "loss_making" else "earnings_unknown")
    if _obj(_obj(p.get("modules")).get("general_screen")).get("status") != "conditional":
        issues.append("general_industry_gate_closed")
    classified = _day(p.get("as_of"))
    if classified is None or classified > cutoff:
        issues.append("industry_cutoff_unknown_or_future")
    current_only = p.get("research_purpose") == "current_research" or p.get("temporal_visibility") == "current_snapshot_only_not_historical_pit"
    current_evidence = [e for e in _rows(_obj(p.get("classification")).get("evidence")) if e.get("temporal_basis") == "supplier_current_snapshot"]
    if current_only or current_evidence:
        if purpose != "current_research":
            issues.append("current_industry_label_not_historical_evidence")
        if not current_evidence or any(_day(e.get("observed_at")) is None or _day(e.get("observed_at")) > cutoff for e in current_evidence):
            issues.append("current_industry_observation_unknown_or_future")
    return issues


def _source_issues(record, key):
    source = _obj(_obj(record.get("sources")).get(key))
    issues = []
    if not _known(source.get("source_id")) or not _known(source.get("raw_field")):
        issues.append(key + "_source_missing")
    if source.get("company_code") != record.get("company_code") or not _known(record.get("company_code")):
        issues.append(key + "_source_subject_unbound")
    if _day(source.get("valuation_as_of")) != _day(record.get("valuation_as_of")) or _day(record.get("valuation_as_of")) is None:
        issues.append(key + "_source_quote_date_unbound")
    if source.get("raw_field") != {"price": "CLOSE_PRICE", "pe_ttm": "PE_TTM", "pb": "PB_MRQ"}[key]:
        issues.append(key + "_source_field_unsupported")
    return issues


def _quote_state(record, cutoff, policy):
    quote_date = _day(record.get("valuation_as_of"))
    observed = _day(record.get("observed_at"))
    issues = []
    if quote_date is None:
        issues.append("quote_date_unknown")
    elif quote_date > cutoff:
        issues.append("quote_after_cutoff")
    if observed is None:
        issues.append("quote_observation_date_unknown")
    elif observed > cutoff:
        issues.append("quote_observed_after_cutoff")
    if quote_date and observed and observed < quote_date:
        issues.append("quote_observed_before_price_date")
    age = (cutoff - quote_date).days if quote_date else None
    if age is not None and age > policy["max_quote_age_calendar_days"]:
        issues.append("quote_stale")
    price = _num(record.get("price"))
    if price is None or price <= 0:
        issues.append("positive_price_unavailable")
    issues.extend(_source_issues(record, "price"))
    if record.get("valuation_basis") != "daily_close":
        issues.append("price_basis_not_supported")
    return {"status": "unavailable" if issues else "recent_by_calendar_policy",
            "quote_date": quote_date.isoformat() if quote_date else None,
            "observed_at": record.get("observed_at"), "calendar_age_days": age,
            "trading_calendar_verified": False, "issues": sorted(set(issues))}


def _metric_issues(record, key, cutoff, policy):
    issues = []
    value = _num(record.get(key))
    if value is None or value <= 0:
        issues.append(key + "_nonpositive_or_missing")
    for field in COMPARABILITY_KEYS:
        if not _known(record.get(field)):
            issues.append(field + "_unknown")
    if record.get("quote_currency") != record.get("financial_currency"):
        issues.append("quote_financial_currency_mismatch_no_fx")
    if any(not isinstance(record.get(k), str) or record[k] not in CURRENCIES for k in ("quote_currency", "financial_currency")):
        issues.append("currency_unrecognized")
    basis = _obj(record.get("basis"))
    for field in BASIS_KEYS:
        if not _known(basis.get(field)):
            issues.append(field + "_unknown")
    if not isinstance(basis.get("accounting_standard"), str) or basis["accounting_standard"] not in ACCOUNTING_STANDARDS:
        issues.append("accounting_standard_unrecognized")
    definition_key, required_definition, start_key, end_key = METRIC_BASIS[key]
    if basis.get(definition_key) != required_definition:
        issues.append(key + "_definition_unconfirmed")
    end = _day(basis.get(end_key))
    start = _day(basis.get(start_key)) if start_key else end
    if end is None or start is None or start > end:
        issues.append(key + "_denominator_period_unknown")
    elif key == "pe_ttm" and not 364 <= (end - start).days <= 366:
        issues.append("pe_denominator_not_twelve_months")
    latest = _day(record.get("latest_report_date"))
    if latest is None or latest != end:
        issues.append("denominator_not_latest_known_report_period")
    if end and (cutoff - end).days > policy["max_financial_period_age_calendar_days"]:
        issues.append("financial_denominator_stale")
    quote_day = _day(record.get("valuation_as_of"))
    announced = _day(basis.get("financial_announced_at"))
    if announced is None or announced > cutoff or (quote_day and announced > quote_day) or (end and announced < end):
        issues.append("denominator_not_published_by_quote_date")
    denominator = _obj(_obj(record.get("denominators")).get(key))
    amount = _num(denominator.get("value"))
    if amount is None or amount <= 0:
        issues.append(key + "_positive_denominator_unconfirmed")
    if denominator.get("issuer_id") != record.get("issuer_id") or not _known(record.get("issuer_id")):
        issues.append("denominator_issuer_unconfirmed")
    if denominator.get("scope") != basis.get("scope") or not _known(basis.get("scope")):
        issues.append("denominator_scope_unconfirmed")
    if denominator.get("currency") != record.get("financial_currency") or not _known(record.get("financial_currency")):
        issues.append("denominator_currency_unconfirmed")
    if _day(denominator.get("period_end")) != end or end is None:
        issues.append("denominator_period_mismatch")
    if start_key and _day(denominator.get("period_start")) != start:
        issues.append("denominator_period_mismatch")
    if not _known(denominator.get("source_id")):
        issues.append("denominator_source_missing")
    if basis.get("scope") != "consolidated" or basis.get("share_basis") != "parent_common_equity":
        issues.append("scope_or_share_basis_not_supported")
    issues.extend(_source_issues(record, key))
    return sorted(set(issues))


def _signature(record, key):
    basis = _obj(record.get("basis"))
    definition, _, start, end = METRIC_BASIS[key]
    fields = BASIS_KEYS + (definition, end) + ((start,) if start else ())
    return tuple(record.get(k) for k in COMPARABILITY_KEYS) + (record.get("valuation_as_of"),) + tuple(basis.get(k) for k in fields)


def _comparison(record, peers, key, profile, cutoff, policy, company_code, financial_period, purpose):
    gaps = _profile_issues(profile, cutoff, purpose) + _quote_state(record, cutoff, policy)["issues"] + _metric_issues(record, key, cutoff, policy)
    if record.get("company_code") != company_code or not _known(company_code):
        gaps.append("price_company_mismatch")
    if not _known(record.get("security_id")):
        gaps.append("security_identity_missing")
    if _day(financial_period) is None or _day(record.get("latest_report_date")) != _day(financial_period):
        gaps.append("latest_financial_snapshot_unbound")
    accepted, excluded, seen_issuers = [], [], set()
    counts, security_counts, code_counts = {}, {}, {}
    for peer in _rows(peers):
        identity = peer.get("issuer_id")
        if _known(identity):
            counts[identity] = counts.get(identity, 0) + 1
        for values, identity_key in ((security_counts, "security_id"), (code_counts, "company_code")):
            if _known(peer.get(identity_key)):
                values[peer[identity_key]] = values.get(peer[identity_key], 0) + 1
    for peer in _rows(peers):
        identity = peer.get("issuer_id")
        reasons = []
        if not _known(identity) or not _known(peer.get("security_id")):
            reasons.append("peer_identity_missing")
        elif identity == record.get("issuer_id") or peer.get("company_code") == company_code or peer.get("security_id") == record.get("security_id"):
            reasons.append("same_issuer_excluded")
        elif counts[identity] > 1:
            reasons.append("duplicate_issuer_ambiguous")
        if any(_known(peer.get(k)) and values.get(peer[k], 0) > 1 for values, k in ((security_counts, "security_id"), (code_counts, "company_code"))):
            reasons.append("duplicate_security_or_company_ambiguous")
        reasons += _profile_issues(peer.get("industry_profile"), cutoff, purpose)
        if _obj(peer.get("industry_profile")).get("code") != peer.get("company_code"):
            reasons.append("peer_industry_subject_mismatch")
        reasons += _quote_state(peer, cutoff, policy)["issues"] + _metric_issues(peer, key, cutoff, policy)
        if _signature(peer, key) != _signature(record, key):
            reasons.append("peer_basis_mismatch")
        if reasons:
            excluded.append({"issuer_id": identity, "company_code": peer.get("company_code"), "reasons": sorted(set(reasons))})
        elif identity not in seen_issuers:
            seen_issuers.add(identity)
            accepted.append({"issuer_id": identity, "company_code": peer.get("company_code"), "value": _text(_num(peer.get(key))),
                             "source_ref": deepcopy(_obj(_obj(peer.get("sources")).get(key)))})
    if len(accepted) < policy["minimum_comparable_peers"]:
        gaps.append("insufficient_same_basis_peers")
    median, relation, relative = None, None, None
    if not gaps:
        ordered = sorted(Decimal(row["value"]) for row in accepted)
        size = len(ordered)
        median = ordered[size // 2] if size % 2 else (ordered[size // 2 - 1] + ordered[size // 2]) / 2
        number = _num(record.get(key))
        relation = "below_peer_median" if number < median else "above_peer_median" if number > median else "equal_peer_median"
        relative = number / median - 1
    return {"key": key, "status": "conditional_peer_reference" if not gaps else "not_assessed",
            "observed": _raw(record, key), "peer_median": _text(median), "relative_to_median": _text(relative),
            "relation": relation, "included_peers": accepted, "excluded_peers": excluded,
            "comparable_peers": len(accepted), "issues": sorted(set(gaps)),
            "verification": "supplier_same_metadata_only", "intrinsic_value": None, "target_price": None,
            "interpretation": "同口径供应商倍数的相对位置；不证明低估，也不构成买入条件。"}


def _section(report, name, code, cutoff):
    source = _obj(report.get(name))
    if not source:
        return {}, [name + "_not_provided"]
    explicit_code = source.get("company_code", source.get("code", code))
    section_date = _day(source.get("as_of"))
    gaps = []
    if explicit_code != code:
        gaps.append(name + "_company_mismatch")
    if section_date is None or section_date > cutoff:
        gaps.append(name + "_cutoff_unknown_or_future")
    return ({} if gaps else source), gaps


def _dimensions(report, code, cutoff, purpose):
    quality = _obj(report.get("quality"))
    long_term, long_term_gaps = _section({"long_term": quality.get("long_term")}, "long_term", code, cutoff)
    debt, debt_gaps = _section(report, "debt_governance", code, cutoff)
    business, business_gaps = _section(report, "business_capital", code, cutoff)
    industry, industry_gaps = _section(report, "industry_profile", code, cutoff)
    def dimension(key, section, covered, gaps, required):
        return {"key": key, "implementation_status": "module_output_present" if section else "module_missing_or_unusable",
                "completion_status": "partial" if section else "not_assessed", "covered": covered,
                "gaps": gaps, "next_evidence": required, "quality_score": None}
    windows = [{"years": w.get("years"), "complete": w.get("complete") is True,
                "complete_years": w.get("complete_years"), "periods": deepcopy(w.get("periods", []))}
               for w in _rows(long_term.get("windows")) if w.get("years") in (3, 5)]
    groups = _obj(business.get("evidence_groups"))
    group_counts = {key: len(value) if isinstance(value, list) else 0 for key, value in groups.items()
                    if key in {"company_claims", "independent_material", "counterevidence"}}
    for key in ("company_claims", "independent_material", "counterevidence"):
        group_counts.setdefault(key, 0)
    debt_cov = _obj(debt.get("coverage"))
    audit = _obj(debt.get("audit"))
    dimensions = [
        dimension("financial_persistence", long_term, {"windows": windows, "coverage": deepcopy(_obj(long_term.get("coverage")))},
                  long_term_gaps + ([] if windows else ["fixed_three_five_year_windows_missing"]), ["逐期核对盈利与现金、重述和周期，不把固定五年视为完整周期"]),
        dimension("debt_liquidity", debt, {"provided_numeric_fields": debt_cov.get("provided_numeric_fields"),
                  "numeric_field_count": debt_cov.get("numeric_field_count"), "debt_scope_complete": _obj(debt.get("debt")).get("complete") is True,
                  "liquidity_scope_complete": _obj(debt.get("liquidity")).get("complete") is True}, debt_gaps + ["maturity_and_restricted_cash_review_required"],
                  ["有息负债全口径、受限及到期可用现金、到期分布与担保"]),
        dimension("governance", debt, {"latest_audit_status": _obj(audit.get("latest_report")).get("status"),
                  "annual_audit_status": _obj(audit.get("latest_annual")).get("status"),
                  "authority_announcements": _obj(debt.get("governance")).get("authority_announcements", "not_reviewed")},
                  debt_gaps + ["no_risk_clearance_from_periodic_report_silence"], ["分期次审计原文、监管独立公告和关联交易实质"]),
        dimension("competitive_position", business, group_counts, business_gaps + ["independent_semantic_evidence_not_verified"],
                  ["独立市场份额、客户留存、定价与反证；毛利、研发和EPS不是优势证明"]),
        dimension("capital_use", business, {"reported_events": _obj(business.get("coverage")).get("reported_events"),
                  "window_count": len(_rows(business.get("windows")))}, business_gaps + ["capital_outcome_attribution_missing"],
                  ["分红实际支付、送转与融资区别、收购现金口径、资本投入后续回报"]),
        dimension("industry_applicability", industry, {"model": _obj(industry.get("classification")).get("model"),
                  "earnings_status": industry.get("earnings_status")}, industry_gaps + _profile_issues(industry, cutoff, purpose),
                  ["保留行业来源及适用日期；金融、地产、周期或未知使用专项口径"]),
    ]
    return dimensions, debt, business, industry


def _current_context_profile(context, report, reference, cutoff, purpose):
    """Bind today's classification without replacing yesterday's report evidence."""
    value = deepcopy(_obj(context))
    company = _obj(report.get("company"))
    old = _obj(report.get("industry_profile"))
    profile = _obj(value.get("profile"))
    source = _obj(value.get("source_ref"))
    binding = _obj(reference.get("security_binding"))
    issues = []
    if purpose != "current_research":issues.append("current_context_not_historical_evidence")
    if value.get("version") != "price-industry-context-1.0" or value.get("status") != "available":issues.append("current_industry_context_unavailable")
    if value.get("company_code") != company.get("code") or profile.get("code") != company.get("code"):issues.append("current_context_subject_mismatch")
    if value.get("financial_as_of") != company.get("as_of") or value.get("previous_report") != {"model": _obj(old.get("classification")).get("model"), "as_of": old.get("as_of")}:
        issues.append("current_context_old_cutoff_mismatch")
    if (_day(value.get("classification_as_of")) != cutoff or _day(profile.get("as_of")) != cutoff
        or _day(value.get("observed_at")) is None or _day(value.get("observed_at")) > cutoff):issues.append("current_context_date_unknown_or_future")
    if value.get("historical_pit_usable") is not False or value.get("modifies_saved_report") is not False or value.get("use") != "current_price_applicability_only":
        issues.append("current_context_use_unbound")
    if (profile.get("version") != "industry-policy-1.0" or profile.get("research_purpose") != "current_research"
        or profile.get("historical_pit_usable") is not False or profile.get("report_date") != company.get("report_date")
        or profile.get("earnings_basis") != old.get("earnings_basis")):
        issues.append("current_context_saved_earnings_changed")
    if (not _known(source.get("source_id")) or not re.fullmatch(r"[a-f0-9]{64}", str(source.get("sha256", "")))
        or source.get("source_id") != binding.get("source_id") or source.get("sha256") != binding.get("sha256")
        or source.get("raw_field") != "BOARD_NAME_2LEVEL" or source.get("raw_value") != reference.get("industry_key")
        or source.get("observed_at") != value.get("observed_at")):
        issues.append("current_context_master_source_unbound")
    evidence = _rows(_obj(profile.get("classification")).get("evidence"))
    if not any(e.get("temporal_basis") == "supplier_current_snapshot" and all(e.get(k) == source.get(k)
               for k in ("source_id", "sha256", "raw_field", "raw_value", "observed_at")) for e in evidence):
        issues.append("current_context_classification_evidence_unbound")
    if issues:
        value["status"] = "unavailable"
        value["gaps"] = _rows(value.get("gaps")) + [{"code": code} for code in sorted(set(issues))]
    return ({} if issues else profile), value


def build_price_quality_panel(report, market_reference=None, peers=None, *, as_of, policy=None, research_purpose="historical_as_of", current_industry_context=None):
    """Pure deterministic panel; `as_of` is required and date based (not strict PIT)."""
    cutoff = _day(as_of)
    if cutoff is None:
        raise ValueError("as_of must be an explicit valid ISO date or timestamp")
    if not isinstance(research_purpose, str) or research_purpose not in {"historical_as_of", "current_research"}:
        raise ValueError("research_purpose must explicitly select current_research or historical_as_of")
    settings = dict(DEFAULT_POLICY)
    if policy is not None:
        if not isinstance(policy, dict) or set(policy) - set(DEFAULT_POLICY):
            raise ValueError("unknown policy option")
        settings.update(policy)
    if type(settings["max_quote_age_calendar_days"]) is not int or not 0 <= settings["max_quote_age_calendar_days"] <= 31:
        raise ValueError("quote age must be integer 0..31 calendar days")
    if type(settings["minimum_comparable_peers"]) is not int or settings["minimum_comparable_peers"] < 5:
        raise ValueError("at least five comparable peers required")
    if type(settings["max_financial_period_age_calendar_days"]) is not int or not 1 <= settings["max_financial_period_age_calendar_days"] <= 730:
        raise ValueError("financial period age must be integer 1..730 calendar days")
    report = _obj(report)
    company = _obj(report.get("company"))
    code = company.get("code") or _obj(report.get("summary")).get("code")
    reference = _obj(market_reference)
    context = None
    dimension_report = report
    if current_industry_context is not None:
        effective, context = _current_context_profile(current_industry_context, report, reference, cutoff, research_purpose)
        dimension_report = {**report, "industry_profile": effective}
    dimensions, debt, business, industry = _dimensions(dimension_report, code, cutoff, research_purpose)
    if context is not None:
        dimensions[-1]["covered"].update(temporal_use="current_price_applicability_only", financial_as_of=company.get("as_of"),
            classification_as_of=context.get("classification_as_of"), observed_at=context.get("observed_at"))
    price = {"reference_price": _raw(reference, "price"),
             "reference_basis": {k: deepcopy(reference.get(k)) for k in ("market", "industry_key", "quote_currency", "financial_currency", "valuation_basis")},
             "freshness": _quote_state(reference, cutoff, settings),
             "comparisons": [_comparison(reference, peers, key, industry, cutoff, settings, code, company.get("report_date"), research_purpose) for key in ("pe_ttm", "pb")]}
    price["supplier_comparisons"] = [_supplier_comparison(reference, peers, key, industry, cutoff, settings, code, research_purpose) for key in ("pe_ttm", "pb")]
    price["recalculation_diagnostics"] = deepcopy(_obj(reference.get("recalculation_diagnostics")))
    risk_items = []
    for origin, rows in (("legacy_screen", _obj(report.get("summary")).get("flags")), ("debt_governance", debt.get("priority_risks"))):
        for item in _rows(rows):
            risk_items.append({"origin": origin, "code": item.get("code"), "level": item.get("level"),
                               "message": item.get("message"), "confirmed_adverse_fact": False})
    has_high = any(x["level"] == "high" for x in risk_items)
    profile_blocked = bool(_profile_issues(industry, cutoff, research_purpose))
    status = "risk_review_required" if has_high else "specialist_or_identity_review_required" if profile_blocked else "evidence_incomplete"
    for item in price["comparisons"] + price["supplier_comparisons"]:
        if has_high:
            item["quality_risk_context"] = "high_priority_risk_requires_review_even_if_multiple_is_lower"
    checklist = [{"id": "review_" + d["key"], "state": "pending", "trigger": "new_disclosure_or_verified_material",
                  "requirements": deepcopy(d["next_evidence"])} for d in dimensions]
    checklist += [{"id": "refresh_price", "state": "pending" if price["freshness"]["issues"] else "observed_under_calendar_policy",
                   "trigger": "new_quote_or_age_limit", "requirements": ["核对实际报价日，不以抓取时间替代；交易日历尚未确认"]},
                  {"id": "review_comparable_peers", "state": ("conditional_reference_available" if all(not c["issues"] for c in price["comparisons"]) else
                                                             "supplier_reference_available_rebuild_pending" if any(c["status"] == "supplier_peer_reference" for c in price["supplier_comparisons"]) else "pending"),
                   "trigger": "new_earnings_equity_or_peer_basis", "requirements": ["同行必须独立发行人、同日期/定义/准则/范围/币种，重核异常与分母"]}]
    return {"version": VERSION, "company_code": code, "as_of": cutoff.isoformat(), "status": "evidence_panel_only",
            **({"current_industry_context": context} if context is not None else {}),
            "research_purpose": research_purpose, "historical_pit_usable": False,
            "company_quality": {"status": status, "verdict": None, "score": None, "weights": None,
                                "reason": "未授权综合权重；覆盖和风险单列，保留原初筛，不从缺资料推出高质量。"},
            "legacy_screen": deepcopy(_obj(report.get("summary"))), "legacy_screen_recomputed": False,
            "legacy_screen_usage": "original_reference_only_not_permission_for_current_ranking",
            "ordinary_ranking_allowed_by_industry_profile": not profile_blocked,
            "quality_dimensions": dimensions, "price_condition": price,
            "risk_state": {"status": "high_priority_review" if has_high else "review_pending" if risk_items else "not_cleared",
                           "items": risk_items, "absence_means_no_risk": False},
            "evidence_panel": {"module_dimensions_present": sum(d["implementation_status"] == "module_output_present" for d in dimensions),
                               "dimension_count": len(dimensions), "verified_company_quality_dimensions": 0,
                               "official_numbers_verified_by_this_module": 0, "source_metadata_is_numeric_verification": False},
            "observation_checklist": checklist, "policy": settings,
            "assumptions": [f"本次最多{settings['max_quote_age_calendar_days']}个自然日为报价参考窗口；不是交易日历认证。",
                            f"分母必须对应已知最新财报，且期末距截止不超过{settings['max_financial_period_age_calendar_days']}自然日；这是可配置陈旧门槛，不是及时披露认证。",
                            "同行至少5家沿用现有最低样本数量；只比较中位数位置，不采用折溢价买入阈值。",
                            "供应商倍数需明确分母、准则、日期、范围与币种；字段名本身不能补齐所有口径。"],
            "limits": ["没有DCF、内在价值、目标价、买卖指令或公司质量总分。", "日期过滤不是严格历史PIT证明。",
                       "企业自述、独立材料和反证的数量不证明语义正确或风险不存在。"],
            "intrinsic_value": None, "target_price": None, "investment_recommendation": None,
            "network_calls": 0, "model_calls": 0, "integrated": False}


def legacy_market_reference(company, sources=None):
    """Lossless public scalar reference, leaving unavailable valuation basis null.

    Existing canonical statement currency is not assumed to be quote currency.
    Raw quote cache verification belongs in a separate read-only adapter.
    """
    c = _obj(company)
    available = {s.get("id"): s for s in _rows(sources) if _known(s.get("id"))}
    refs = {}
    for key in ("price", "pe_ttm", "pb"):
        f = _obj(_obj(c.get("field_sources")).get(key))
        source = _obj(available.get(f.get("source_id")))
        refs[key] = {"source_id": f.get("source_id"), "raw_field": f.get("field"),
                     "url": source.get("url"), "sha256": source.get("sha256"), "raw_hash_rechecked": False}
    out = {"company_code": c.get("code"), "issuer_id": None, "security_id": None,
           "market": c.get("exchange"), "industry_key": c.get("industry"),
           "quote_currency": None, "financial_currency": c.get("currency"),
           "valuation_as_of": c.get("valuation_as_of"), "observed_at": c.get("quote_fetched_at"),
           "latest_report_date": c.get("report_date"),
           "valuation_basis": c.get("valuation_basis"), "basis": {}, "denominators": {}, "sources": refs}
    for key in ("price", "pe_ttm", "pb"):
        if key in c:
            out[key] = deepcopy(c[key])
    return out


def _supplier_issues(record, key, profile, cutoff, policy, purpose):
    """Provider-defined ratio reference, separate from independently rebuilt ratios."""
    issues = _profile_issues(profile, cutoff, purpose) + _quote_state(record, cutoff, policy)["issues"] + _source_issues(record, key)
    if record.get("supplier_reference_contract") != "eastmoney-daily-ratios-1.0":
        issues.append("supplier_ratio_contract_unavailable")
    value = _num(record.get(key))
    if value is None or value <= 0:
        issues.append(key + "_nonpositive_or_missing")
    for field in ("issuer_id", "security_id", "company_code", "industry_key", "market"):
        if not _known(record.get(field)):
            issues.append(field + "_unresolved")
    source = _obj(_obj(record.get("sources")).get(key))
    if source.get("raw_hash_rechecked") is not True or source.get("raw_value_matches") is not True:
        issues.append("supplier_original_not_matched")
    price_source = _obj(_obj(record.get("sources")).get("price"))
    if price_source.get("raw_hash_rechecked") is not True or price_source.get("raw_value_matches") is not True:
        issues.append("supplier_price_original_not_matched")
    if record.get("quote_currency") != "CNY" or record.get("financial_currency") != "CNY":
        issues.append("supplier_A_share_currency_unconfirmed")
    if _obj(record.get("basis")).get("provider") != "eastmoney_RPT_VALUEANALYSIS_DET":
        issues.append("supplier_metric_definition_unconfirmed")
    quote_day = _day(record.get("valuation_as_of"))
    profile = _obj(profile)
    period = _day(record.get("latest_report_date"))
    if not period or period != _day(profile.get("report_date")):
        issues.append("supplier_financial_period_unbound")
    elif (cutoff - period).days > policy["max_financial_period_age_calendar_days"]:
        issues.append("financial_denominator_stale")
    for field in ("net_profit", "parent_profit"):
        earning = _obj(_obj(profile.get("earnings_basis")).get(field))
        announced = _day(earning.get("announced_at"))
        if not announced or not quote_day or announced > quote_day:
            issues.append("known_earnings_not_published_by_quote_date")
        if _day(earning.get("report_date")) != period or period is None:
            issues.append("known_earnings_period_mismatch")
    book = _num(_obj(record.get("book_value_reference")).get("value"))
    if key == "pb" and book is not None and book <= 0:
        issues.append("known_book_value_nonpositive")
    diagnostics = _obj(record.get("recalculation_diagnostics"))
    if diagnostics.get("status") == "numeric_consistency_only":
        profit = _obj(diagnostics.get("ttm_profit"))
        profit_value = _num(profit.get("value"))
        if key == "pe_ttm" and profit.get("status") == "calculated" and profit_value is not None and profit_value <= 0:
            issues.append("known_recalculated_ttm_nonpositive")
        if key == "pb" and any(_num(candidate.get("value")) is not None and _num(candidate["value"]) <= 0 for candidate in _rows(diagnostics.get("pb_candidates"))):
            issues.append("known_equity_candidate_nonpositive")
    return sorted(set(issues))


def _supplier_comparison(record, peers, key, profile, cutoff, policy, code, purpose):
    gaps = _supplier_issues(record, key, profile, cutoff, policy, purpose)
    if record.get("company_code") != code:
        gaps.append("price_company_mismatch")
    candidates = _rows(peers)
    counts = {field: {} for field in ("issuer_id", "security_id", "company_code")}
    for p in candidates:
        for field, values in counts.items():
            if _known(p.get(field)):values[p[field]] = values.get(p[field], 0) + 1
    included, excluded = [], []
    keys = ("market", "industry_key", "quote_currency", "financial_currency", "valuation_basis", "valuation_as_of", "latest_report_date", "supplier_reference_contract")
    for p in candidates:
        reasons = _supplier_issues(p, key, p.get("industry_profile"), cutoff, policy, purpose)
        if any(_known(p.get(field)) and p[field] == record.get(field) for field in counts):
            reasons.append("same_issuer_or_security_excluded")
        if any(_known(p.get(field)) and values[p[field]] > 1 for field, values in counts.items()):
            reasons.append("duplicate_identity_excluded")
        if any(p.get(field) != record.get(field) for field in keys):
            reasons.append("supplier_peer_basis_mismatch")
        if _obj(p.get("industry_profile")).get("code") != p.get("company_code"):
            reasons.append("peer_industry_subject_mismatch")
        item = {"company_code": p.get("company_code"), "issuer_id": p.get("issuer_id"), "value": _text(_num(p.get(key)))}
        if reasons:
            item["reasons"] = sorted(set(reasons));excluded.append(item)
        else:
            item["source_ref"] = deepcopy(_obj(_obj(p.get("sources")).get(key)));included.append(item)
    if len(included) < policy["minimum_comparable_peers"]:gaps.append("insufficient_same_supplier_peers")
    median = ratio = relation = None
    if not gaps:
        values = sorted(Decimal(p["value"]) for p in included);n = len(values)
        median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
        own = _num(record[key]);ratio = own / median - 1
        relation = "below_peer_median" if own < median else "above_peer_median" if own > median else "equal_peer_median"
    return {"key": key, "status": "supplier_peer_reference" if not gaps else "not_assessed", "observed": _raw(record, key),
            "peer_median": _text(median), "relative_to_median": _text(ratio), "relation": relation,
            "included_peers": included, "excluded_peers": excluded, "comparable_peers": len(included), "issues": sorted(set(gaps)),
            "verification": "supplier_raw_matching_not_official", "target_price": None,
            "limits": ["同供应商明确命名的比率字段参考；不要求每家先独立重算，但不声称会计政策和分母已逐项复核。",
                       "同细行业、交易所和时期仍不能排除业务与周期差异；中位数不是内在价值或买入阈值。"]}
