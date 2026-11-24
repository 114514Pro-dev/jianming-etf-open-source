"""Host adapter. All /api/ routes inherit the existing session/CSRF guard."""
from pathlib import Path
import re
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parent
API_PREFIX = '/api/sector-research/'
PAGE_PREFIX = '/sector-research/'


def html_for_host(text, version):
    def replace_url(match):
        attribute, quote, url = match.groups()
        if url.startswith('//') or url.startswith('/api/'):
            return match.group(0)
        path = url.lstrip('/')
        return attribute + '=' + quote + PAGE_PREFIX + path + quote
    text = re.sub(r'''\b(src|href)=(["'])(/[^"']*)\2''', replace_url, text)
    bridge = '<script src="/static/sector-research-host.js?v=' + version + '"></script>'
    if not re.search(r'<head\b[^>]*>', text, flags=re.I) or not re.search(r'<body\b[^>]*>', text, flags=re.I):
        raise ValueError('研究页面结构不完整。')
    text = re.sub(r'<head\b[^>]*>', lambda m: m.group(0) + bridge, text, count=1, flags=re.I)
    back = ('<a href="/" id="sector-research-back" style="display:inline-block;margin:12px 20px;'
            'font:14px sans-serif;color:inherit">← 返回简明ETF / Back to ETF</a>')
    return re.sub(r'<body\b[^>]*>', lambda m: m.group(0) + back, text, count=1, flags=re.I)


def install_routes(app, session_getter):
    def service():
        value = getattr(app.state, 'sector_research', None)
        if value is None:
            raise HTTPException(503, '板块研究模块暂不可用，原交易与账户功能继续运行。')
        return value

    @app.get('/api/sector-research/{path:path}')
    def get_module(path: str, request: Request):
        # Use parse_qs-compatible lists so standalone and host adapters agree.
        query = {k: request.query_params.getlist(k) for k in request.query_params}
        result = service().dispatch_get('/api/' + path, query)
        if result is None:
            raise HTTPException(404, '没有此板块研究接口。')
        if path == 'runtime':
            result = dict(result)
            result['csrf_token'] = session_getter(request)['csrf']
            result['hosting'] = {'mode': 'simple-etf', 'api_prefix': API_PREFIX,
                                 'page_prefix': PAGE_PREFIX, 'account_engine_connected': False}
        return result

    @app.post('/api/sector-research/{path:path}')
    async def post_module(path: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('研究请求必须是JSON对象。')
        # Validation/cache preparation can take time; never block the host event
        # loop or use its single account Bridge queue for research work.
        return await run_in_threadpool(service().dispatch_post, '/api/' + path, body)

    @app.get('/sector-research')
    def page_redirect():
        return RedirectResponse(PAGE_PREFIX, status_code=307)

    @app.get('/sector-research/{path:path}')
    def page(path: str, request: Request):
        if not session_getter(request, False):
            return RedirectResponse('/?sector_research=1', status_code=303)
        pages = {'market': 'index.html', 'opportunities': 'opportunities.html', 'capital': 'capital.html'}
        if not path:
            path = 'capital.html' if (ROOT / 'web/capital.html').is_file() else 'opportunities.html'
        path = pages.get(path, path)
        root = (ROOT / 'web').resolve()
        selected = (root / path).resolve()
        if not selected.is_relative_to(root) or not selected.is_file() or selected.suffix not in {'.html', '.css', '.js', '.svg', '.ico', '.png'}:
            raise HTTPException(404, '没有此研究页面或资源。')
        headers = {'Cache-Control': 'no-store'}
        if selected.suffix == '.html':
            version = app.state.sector_host_ui_version
            return HTMLResponse(html_for_host(selected.read_text('utf8'), version), headers=headers)
        return FileResponse(selected, headers=headers)
