"""Research endpoints inherit the application's login, CSRF and size guards."""
from fastapi import HTTPException, Request


def install_routes(app):
    def service():
        current = getattr(app.state, "research", None)
        if current is None:
            raise HTTPException(503, "公司研究模块暂不可用，现有交易功能继续运行")
        return current

    def valuation():
        from .valuation_service import ValuationService
        return ValuationService(service())

    async def valuation_body(request):
        import json
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 384000:
                raise HTTPException(413, "估值假设与原文摘录合计过长，请精简后重试。")
            chunks.append(chunk)
        try:
            return json.loads(b"".join(chunks))
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, "估值请求必须为有效JSON。") from exc

    @app.get("/api/research/valuation/{code}")
    def valuation_get(code: str):
        try:
            return valuation().get(code)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/research/valuation/{code}/preview")
    async def valuation_preview(code: str, request: Request):
        try:
            return valuation().preview(code, await valuation_body(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/research/valuation/{code}/save")
    async def valuation_save(code: str, request: Request):
        from .valuation_store import RevisionConflict
        try:
            return valuation().save(code, await valuation_body(request))
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/research/summary")
    def research_summary():
        return service().summary()

    @app.get("/api/research/companies")
    def research_companies(query: str = "", industry: str = "", candidate: str = "",
                           sort: str = "quality", offset: int = 0, limit: int = 100):
        return service().companies(query, industry, candidate, sort, offset, limit)

    @app.get("/api/research/company/{code}")
    def research_company(code: str):
        return service().company(code)

    @app.post("/api/research/scan")
    async def research_scan(request: Request):
        body = await request.json() if await request.body() else {}
        if not isinstance(body, dict) or set(body) - {"force"}:
            raise ValueError("扫描请求格式无效")
        # Clicking update means a real supplier refresh. The scheduler invokes
        # submit("scan") directly and retains its ordinary cache policy.
        return service().submit("scan", force=body.get("force", True))

    @app.post("/api/research/analyze")
    async def research_analyze(request: Request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {"code", "force"}:
            raise ValueError("分析请求格式无效")
        return service().submit("analyze", body.get("code"), body.get("force", False))

    @app.get("/api/research/deep-library")
    def research_deep_library(request: Request, query: str = "", industry: str = "", offset: str = "0", limit: str = "100"):
        if set(request.query_params) - {"query", "industry", "offset", "limit"}:
            raise ValueError("已深度研究筛选参数无效")
        if not offset.isascii() or not offset.isdecimal() or not limit.isascii() or not limit.isdecimal():
            raise ValueError("已深度研究分页参数须为整数")
        return service().deep_library(query, industry, int(offset), int(limit))

    @app.get("/api/research/deep/{code}")
    def research_deep_company(code: str):
        return service().deep_company(code)

    @app.post("/api/research/deep")
    async def research_deep_start(request: Request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {"code", "force"}:
            raise ValueError("深度研究请求格式无效")
        return service().submit("deep", body.get("code"), body.get("force", False))

    @app.get("/api/research/jobs/{job_id}")
    def research_job(job_id: str):
        return service().job(job_id)

    @app.post("/api/research/jobs/{job_id}/cancel")
    def research_cancel(job_id: str):
        return service().cancel(job_id)

    @app.get("/api/research/settings")
    def research_settings():
        return service().public_settings()

    @app.post("/api/research/settings")
    async def research_set_settings(request: Request):
        body = await request.json()
        return service().set_settings(body)
