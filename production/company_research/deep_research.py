"""Pure deep-research report assembly and strict, themed AI evidence rounds."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import re

from .ai import AIClient, AI_VERSION, _materials
from .deep_data import official_pdf_url
from .transport import ERROR_CODE_STATUSES

VERSION = "company-deep-research-1.0"
PROMPT_VERSION = "deep-evidence-rounds-1.0"
INPUT_CHARS = 90000
SUCCESS = {"evidence_only", "abstained"}
PRE_REQUEST = {"unconfigured", "invalid_configuration", "insufficient_evidence"}
ERROR_MESSAGES = {
    "deepseek_insufficient_balance": "DeepSeek账户余额不足；请核对供应商余额，不是本程序每日次数限制。",
    "insufficient_quota": "AI供应商账户额度或费用上限不足；请核对供应商账单与限制。",
    "credit_balance_exhausted": "AI供应商预付余额已耗尽；请核对供应商账单。",
    "organization_spend_limit_exceeded": "AI供应商组织已达到费用上限。",
    "project_spend_limit_exceeded": "AI供应商项目已达到费用上限。",
    "organization_usage_limit_exceeded": "AI供应商组织已达到服务用量上限。",
    "rate_limit_exceeded": "AI供应商暂时限速；本轮未自动重试。",
    "invalid_api_key": "AI供应商未接受密钥；请核对配置。",
    "model_not_found": "AI供应商模型不存在或无权访问；请核对配置。"}
TITLES = {"business": "生意模式", "competition": "竞争与护城河证据", "financial": "财务持续性与现金",
          "governance": "债务、审计与治理", "valuation": "价格与估值条件", "risk": "风险、反证与待核问题"}
ROUNDS = (
    {"key": "business_competition", "topics": ("business", "competition"), "title": "生意模式与竞争证据",
     "keywords": ("主要业务", "经营模式", "核心竞争力", "客户", "供应商", "研发", "市场地位", "竞争", "毛利")},
    {"key": "financial_governance", "topics": ("financial", "governance"), "title": "财务、债务与治理",
     "keywords": ("现金流量", "净利润", "应收", "存货", "审计", "受限", "借款", "偿债", "关联交易", "担保")},
    {"key": "valuation_risk", "topics": ("valuation", "risk"), "title": "资本使用、价格条件与反证",
     "keywords": ("风险", "回购", "发行", "募集资金", "收购", "资本", "分红", "权益分派", "诉讼", "处罚", "商誉")},
)
# Keep the original three keys, prompt and fingerprint contract intact. A
# single-topic request has a distinct key, so paid paired rounds cannot be
# relabelled as six independent model calls.
DETAILED_ROUNDS = (
    {"key": "business", "topics": ("business",), "title": "生意模式",
     "keywords": ("主要业务", "经营模式", "产品", "客户", "供应商", "收入")},
    {"key": "competition", "topics": ("competition",), "title": "竞争与护城河证据",
     "keywords": ("核心竞争力", "研发", "市场地位", "竞争", "毛利", "客户")},
    {"key": "financial", "topics": ("financial",), "title": "财务持续性与现金",
     "keywords": ("现金流量", "净利润", "应收", "存货", "营业收入", "现金")},
    {"key": "governance", "topics": ("governance",), "title": "债务、审计与治理",
     "keywords": ("审计", "受限", "借款", "偿债", "关联交易", "担保")},
    {"key": "valuation", "topics": ("valuation",), "title": "资本使用与价格条件",
     "keywords": ("回购", "发行", "募集资金", "收购", "资本", "分红", "权益分派")},
    {"key": "risk", "topics": ("risk",), "title": "风险、反证与待核问题",
     "keywords": ("风险", "诉讼", "处罚", "商誉", "减值", "不确定")},
)


def round_specs(count=3):
    if type(count) is not int or count not in (3, 6):
        raise ValueError("深度研究轮数须为3或6")
    return ROUNDS if count == 3 else DETAILED_ROUNDS


class FocusedAIClient(AIClient):
    """Inherit the existing HTTP, schema and exact source-quote validation."""
    def __init__(self, config, round_key):
        super().__init__({**config, "max_input_chars": INPUT_CHARS})
        self.round = next(r for r in (*ROUNDS, *DETAILED_ROUNDS) if r["key"] == round_key)

    def _request(self, url, body, timeout):
        body = deepcopy(body)
        instruction = ("\n本轮服务器指定研究范围：" + self.round["title"] + "。claims.section只能为"
                       + "/".join(self.round["topics"]) + "。优先跨年度核对变化、限制与反证，缺证据保留问题。"
                       "本轮仍只是原文节选研究，不形成完整公司结论；不得以公司自述证明护城河，也不输出目标价或买入建议。")
        if "instructions" in body:
            body["instructions"] += instruction
        else:
            body["messages"][0]["content"] += instruction
        return super()._request(url, body, timeout)


def admitted_bundle(bundle, code, as_of):
    """Require explicit subject, official URL, known publication and PDF hash."""
    if not isinstance(bundle, dict) or bundle.get("company", {}).get("code") != code:
        raise ValueError("deep_company_identity_mismatch")
    cutoff = date.fromisoformat(as_of)
    result = {"company": deepcopy(bundle["company"]), "documents": [], "warnings": list(bundle.get("warnings") or [])}
    seen = set()
    for original in bundle.get("documents") or []:
        if not isinstance(original, dict):
            continue
        sid = str(original.get("id") or "")
        try:
            published = date.fromisoformat(str(original.get("published_at") or ""))
        except ValueError:
            published = None
        if (not re.fullmatch(r"\d{6,25}", sid) or sid in seen or original.get("company_code") != code
                or not official_pdf_url(original.get("url")) or published is None or published > cutoff):
            result["warnings"].append("部分文档的公司、来源或公告日期未通过核对，未纳入AI阅读。")
            continue
        seen.add(sid)
        doc = {k: deepcopy(original.get(k)) for k in ("id", "company_code", "title", "url", "source_url", "published_at",
                "document_type", "sha256", "extraction_status", "extraction_note", "total_pages")}
        doc["pages"] = []
        if original.get("extraction_status") == "complete" and re.fullmatch(r"[a-f0-9]{64}", str(original.get("sha256") or "")):
            numbers = set()
            for page in original.get("pages") if isinstance(original.get("pages"), list) else []:
                if (isinstance(page, dict) and type(page.get("page")) is int and 0 < page["page"] <= 600
                        and isinstance(page.get("text"), str) and page["page"] not in numbers):
                    numbers.add(page["page"])
                    doc["pages"].append({"page": page["page"], "text": page["text"]})
        if not doc["pages"]:
            result["warnings"].append("部分官方文档未取得可核对的正文页码，链接不等于已经阅读。")
        result["documents"].append(doc)
        if len(result["documents"]) == 8:
            break
    return result


def round_bundle(bundle, spec):
    selected = {"company": deepcopy(bundle["company"]), "documents": []}
    for doc in bundle["documents"]:
        ranked = []
        for page in doc["pages"]:
            compact = "".join(page["text"].split())
            score = sum(compact.count(k) for k in spec["keywords"])
            if "目录" in compact[:300]:
                score -= 100
            if score > 0:
                ranked.append((score, page["page"], page))
        wanted = {p for _, p, _ in sorted(ranked, key=lambda x: (-x[0], x[1]))[:10]}
        # Keep the actual adjacent source page for statements split across pages.
        wanted |= {p + 1 for p in list(wanted)}
        pages = [deepcopy(p) for p in doc["pages"] if p["page"] in wanted][:20]
        if pages:
            selected["documents"].append({**deepcopy(doc), "pages": pages})
    return selected


def fingerprint(bundle, spec, config):
    materials, _, coverage = _materials(bundle, INPUT_CHARS)
    # Source-byte changes matter; observation timestamps, API keys and incidental
    # collection ordering never enter the paid input fingerprint.
    payload = {"version": VERSION, "prompt_version": PROMPT_VERSION, "adapter_version": AI_VERSION,
               "round": spec["key"], "company_code": bundle["company"]["code"],
               "company_name": bundle["company"].get("name"), "materials": materials,
               "document_hashes": sorted((d["id"], d.get("sha256")) for d in bundle["documents"]),
               "config": {k: config.get(k) for k in ("provider", "base_url", "model", "max_output_tokens", "ai_revision")},
               "max_input_chars": INPUT_CHARS}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest(), coverage


def validated_round(result, bundle, spec):
    """Revalidate cached/injected results against this round's actual page text."""
    if not isinstance(result, dict) or result.get("status") not in SUCCESS:
        state = result.get("status") if isinstance(result, dict) else "failed"
        failed = {"status": state if state in PRE_REQUEST | {"limit_reached"} else "failed", "claims": [],
                  "message": "本轮未完成有效AI证据整理；未发布未核对的模型文字。"}
        if isinstance(result, dict) and state == "error":
            code, http_status = result.get("provider_error_code"), result.get("http_status")
            if isinstance(code, str) and type(http_status) is int and http_status in ERROR_CODE_STATUSES.get(code, ()):
                failed.update(error_code=code, provider_error_code=code, http_status=http_status,
                              message=ERROR_MESSAGES[code])
        return failed
    code = bundle["company"]["code"]
    if result.get("company_code") != code:
        return {"status": "failed", "claims": [], "message": "模型结果公司身份未通过校验。"}
    _, index, coverage = _materials(bundle, INPUT_CHARS)
    claims = []
    for value in result.get("claims") or []:
        if isinstance(value, dict) and value.get("section") in spec["topics"]:
            claims.append({k: deepcopy(value.get(k)) for k in ("category", "section", "subject_code", "text", "citations")})
    if not claims:
        checked = {"status": "abstained", "claims": [], "message": "本轮没有通过校验的主题证据，保留判断。"}
    else:
        checked = AIClient._select_evidence({"company_code": code, "status": "abstain" if result["status"] == "abstained" else "completed",
                                             "claims": claims}, code, index, coverage)
    if checked.get("status") not in SUCCESS:
        return {"status": "failed", "claims": [], "message": "本轮主题、公司或引文校验未通过。"}
    checked.update(company_code=code, generated_at=result.get("generated_at"), evidence_coverage=coverage,
                   usage={k: v for k, v in (result.get("usage") or {}).items() if k in ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens")
                          and type(v) is int and v >= 0})
    return checked


def make_report(bundle, rounds, financial_report, generated_at, planned_rounds=3):
    specs = round_specs(planned_rounds)
    if len(rounds) != len(specs) or any(row.get("key") != spec["key"] for spec, row in zip(specs, rounds)):
        raise ValueError("deep_round_plan_mismatch")
    completed = sum(r["status"] in SUCCESS for r in rounds)
    sections = []
    for spec, row in zip(specs, rounds):
        for key in spec["topics"]:
            claims = [deepcopy(c) for c in row.get("claims", []) if c.get("section") == key]
            questions = [c["text"] for c in claims if c.get("category") == "missing"]
            evidence_count = sum(c.get("category") != "missing" for c in claims)
            if not claims and row["status"] in SUCCESS | {"insufficient_evidence"}:
                questions.append("现有主题节选未形成可核对的材料，仍需补充正文与独立证据。")
            section_status = "insufficient_evidence" if row["status"] in SUCCESS and not evidence_count else row["status"]
            unavailable = {
                "limit_reached": "本程序每日AI调用次数不足，本主题未发起新请求；不代表原文证据不足。",
                "unconfigured": "尚未配置AI，本主题未请求模型；已取得的公开资料仍可查看。",
                "not_requested": "前一轮未完成，本主题尚未请求AI；不代表原文证据不足。",
                "failed": row.get("message") or "本主题请求或校验失败，未发布AI结论。",
                "invalid_configuration": "AI配置未通过检查，本主题未请求模型。"}
            sections.append({"key": key, "title": TITLES[key], "status": section_status,
                             "summary": f"保留{evidence_count}条通过公司、页码与引文校验的材料及{len(questions)}项待核问题；不代表完整审阅。" if evidence_count else unavailable.get(section_status, "本主题尚未形成有效证据整理，保留待核问题。"),
                             "claims": claims, "questions": questions,
                             **{k: row[k] for k in ("error_code", "provider_error_code", "http_status") if k in row}})
    sources = [{k: deepcopy(d.get(k)) for k in ("id", "title", "url", "published_at", "company_code", "document_type", "sha256", "extraction_status", "total_pages")}
               | {"pages": [p["page"] for p in d["pages"]]} for d in bundle["documents"]]
    limits = list(dict.fromkeys([*bundle.get("warnings", []),
        "每轮只读长度受限的主题页节选；已提取页数不等于AI逐页阅读，全部轮次完成也不是完整尽调。",
        "企业披露属于公司自述，不是独立护城河证明；官方数值与会计口径尚未逐项核验。",
        "下方五类财务结果保留其原始研究截止；新增深研不会改写普通报告、旧AI或交易账户。",
        "公司质量和价格分开，不合成好股分数，不给目标价、买入指令或收益保证。 "]))
    status = "completed" if len(sections) == 6 and all(s["status"] == "evidence_only" for s in sections) else "partial"
    return {"version": VERSION, "company_code": bundle["company"]["code"], "company_name": bundle["company"].get("name"),
            "generated_at": generated_at, "status": status, "title": "公司深度研究：原文证据与待核问题",
            "summary": f"本次计划{planned_rounds}轮主题研究，已完成{completed}轮（含明确保留判断的轮次）；请结合资料范围、反证与缺口阅读。",
            "sections": sections, "sources": sources,
            "scope": {"documents": len(sources), "extracted_documents": sum(bool(d["pages"]) for d in bundle["documents"]),
                      "pages": sum(len(d["pages"]) for d in bundle["documents"]), "ai_rounds_completed": completed,
                      "ai_rounds_planned": planned_rounds, "limitations": limits},
            "financial_report": deepcopy(financial_report),
            "ai_rounds": [{k: deepcopy(r.get(k)) for k in ("key", "status", "cached", "fingerprint", "generated_at", "evidence_coverage", "usage", "message", "error_code", "provider_error_code", "http_status")} for r in rounds]}


def library_summary(report, code):
    """Validate saved report metadata; never reopen PDF bodies or trust a score."""
    if (not isinstance(report, dict) or report.get("version") != VERSION or report.get("company_code") != code
            or report.get("status") not in {"completed", "partial"}
            or not isinstance(report.get("company_name"), str) or not 1 <= len(report["company_name"].strip()) <= 200):
        return None
    try:
        generated = datetime.fromisoformat(report["generated_at"])
        if generated.tzinfo is None:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    rounds, sections, sources, scope = (report.get(k) for k in ("ai_rounds", "sections", "sources", "scope"))
    if not all(isinstance(value, list) for value in (rounds, sections, sources)) or not isinstance(scope, dict):
        return None
    states = SUCCESS | PRE_REQUEST | {"limit_reached", "failed", "not_requested"}
    planned = scope.get("ai_rounds_planned", 3)
    try:
        specs = round_specs(planned)
    except ValueError:
        return None
    expected_rounds = {r["key"] for r in specs}
    if (len(rounds) != planned or any(not isinstance(r, dict) or not isinstance(r.get("key"), str)
                              or r.get("status") not in states for r in rounds)
            or {r["key"] for r in rounds} != expected_rounds):
        return None
    completed = sum(r["status"] in SUCCESS for r in rounds)
    if not completed or scope.get("ai_rounds_completed") != completed:
        return None
    source_pages = {}
    for source in sources:
        if (not isinstance(source, dict) or source.get("company_code") != code
                or not isinstance(source.get("id"), str) or not re.fullmatch(r"\d{6,25}", source["id"])
                or source["id"] in source_pages or not official_pdf_url(source.get("url"))
                or not isinstance(source.get("pages"), list)
                or any(type(p) is not int or not 1 <= p <= 600 for p in source["pages"])):
            return None
        source_pages[source["id"]] = set(source["pages"])
    if len(sources) > 8 or len(sections) != 6:
        return None
    seen, evidence_topics = set(), 0
    for section in sections:
        if (not isinstance(section, dict) or not isinstance(section.get("key"), str)
                or section["key"] not in TITLES or section["key"] in seen
                or section.get("status") not in states or not isinstance(section.get("claims"), list)):
            return None
        seen.add(section["key"])
        has_evidence = False
        for claim in section["claims"]:
            if (not isinstance(claim, dict) or claim.get("subject_code") != code or claim.get("section") != section["key"]
                    or claim.get("category") not in {"fact", "inference", "counterevidence", "missing"}
                    or not isinstance(claim.get("text"), str) or not isinstance(claim.get("citations"), list)):
                return None
            if claim["category"] != "missing":
                if not claim["citations"]:
                    return None
                for citation in claim["citations"]:
                    if (not isinstance(citation, dict) or not isinstance(citation.get("source_id"), str)
                            or type(citation.get("page")) is not int
                            or citation["page"] not in source_pages.get(citation["source_id"], ())
                            or not isinstance(citation.get("quote"), str) or not citation["quote"].strip()):
                        return None
                has_evidence = True
        if has_evidence and section["status"] == "evidence_only":
            evidence_topics += 1
    financial = report.get("financial_report")
    if not isinstance(financial, dict):
        return None
    subject = financial.get("company")
    if isinstance(subject, dict) and subject.get("code") not in (None, code):
        return None
    deep_status = "completed" if evidence_topics == 6 and all(r["status"] == "evidence_only" for r in rounds) else "partial"
    return {"code": code, "name": report["company_name"], "deep_status": deep_status,
            "generated_at": report["generated_at"], "ai_rounds_completed": completed,
            "ai_rounds_planned": planned, "evidence_topics": evidence_topics, "documents": len(sources)}


def preserves_topic_coverage(previous, current):
    """Compare covered topics, never the incomparable 3-versus-6 call counts."""
    def coverage(report):
        rows = report.get("ai_rounds") or []
        definitions = {r["key"]: r for r in (*ROUNDS, *DETAILED_ROUNDS)}
        read_topics = {topic for row in rows if isinstance(row, dict) and row.get("status") in SUCCESS
                       for topic in definitions.get(row.get("key"), {}).get("topics", ())}
        evidence_topics = {s.get("key") for s in report.get("sections", []) if isinstance(s, dict)
                           and s.get("key") in TITLES and s.get("status") == "evidence_only"}
        return read_topics, evidence_topics
    before, after = coverage(previous), coverage(current)
    return before[0] <= after[0] and before[1] <= after[1]
