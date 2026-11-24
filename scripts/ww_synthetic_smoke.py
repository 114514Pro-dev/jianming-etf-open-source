"""Actual application startup/HTTP smoke on a fresh synthetic home, without network.

Run in the resource-limited Linux container created by verify_ww_candidate.py.
The script never accepts an application-data path; every ledger is temporary.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from unittest.mock import patch

WW = 'D0I-BOND-WW'
CHECKS = []


def check(name, condition, **details):
    value = dict(check=name, passed=bool(condition), **details)
    CHECKS.append(value)
    print(json.dumps(value, ensure_ascii=True), flush=True)
    if not condition:
        raise AssertionError(name)


async def request(app, path, *, query='', method='GET', data=None, cookie=None, csrf=None, origin=None):
    """In-process ASGI client; it cannot open a network connection."""
    body = b'' if data is None else json.dumps(data).encode()
    headers = [(b'host', b'testserver'), (b'content-length', str(len(body)).encode())]
    if data is not None:
        headers.append((b'content-type', b'application/json'))
    for key, value in (('cookie', cookie), ('x-csrf-token', csrf), ('origin', origin)):
        if value is not None:
            headers.append((key.encode(), value.encode()))
    scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method=method,
                 scheme='https', path=path, raw_path=path.encode(), query_string=query.encode(),
                 root_path='', headers=headers, client=('127.0.0.1', 52000), server=('testserver', 443))
    output, sent = [], False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return dict(type='http.request', body=body, more_body=False)
        await asyncio.Future()

    async def send(value):
        output.append(value)

    await app(scope, receive, send)
    response = next(row for row in output if row['type'] == 'http.response.start')
    payload = b''.join(row.get('body', b'') for row in output if row['type'] == 'http.response.body')
    return response['status'], {k.decode().lower(): v.decode() for k, v in response['headers']}, json.loads(payload)


async def exercise_ww(app, cookie, csrf):
    base, query = '/api/realtime-paper', 'strategy=' + WW
    for strategy in ('D0', WW):
        status, _, value = await request(app, base, query='strategy=' + strategy, cookie=cookie)
        check(strategy + '_fresh_empty_account', status == 200 and value.get('strategy') == strategy
              and value.get('accounts') == [])
    check('actual_ww_service_bound', app.state.ww_paper.strategy == WW
          and app.state.ww_paper.ledger.strategy == WW)
    create = {'name': 'Synthetic verification WW', 'initial_cash': '100000.00',
              'idempotency_key': 'synthetic-ww-smoke-create'}
    status, _, value = await request(app, base + '/accounts', query=query, method='POST',
                                     data=create, cookie=cookie, csrf=csrf)
    accounts = value.get('accounts', [])
    account = accounts[0] if len(accounts) == 1 else {}
    check('ww_create_default_stopped', status == 200 and value.get('strategy') == WW
          and account.get('strategy') == WW and account.get('status') == 'stopped'
          and account.get('cash') == '100000.00' and account.get('orders') == [] and account.get('fills') == [])
    identity = account['id']
    route = base + '/accounts/' + identity
    try:
        status, _, repeated = await request(app, base + '/accounts', query=query, method='POST',
                                             data=create, cookie=cookie, csrf=csrf)
        check('ww_create_idempotent', status == 200 and repeated == value)
        status, _, _ = await request(app, route + '/start', query=query, method='POST',
            data={'idempotency_key': 'synthetic-ww-smoke-no-csrf'}, cookie=cookie)
        check('ww_write_requires_csrf', status == 403)
        status, _, _ = await request(app, route + '/start', query='strategy=D0', method='POST',
            data={'idempotency_key': 'synthetic-ww-smoke-wrong-scope'}, cookie=cookie, csrf=csrf)
        check('ww_account_rejected_in_d0_scope', status == 404)
        status, _, started = await request(app, route + '/start', query=query, method='POST',
            data={'idempotency_key': 'synthetic-ww-smoke-start'}, cookie=cookie, csrf=csrf)
        check('ww_start_synthetic_only', status == 200 and started.get('strategy') == WW
              and started.get('accounts', [{}])[0].get('status') == 'running')
        status, _, paused = await request(app, route + '/pause', query=query, method='POST',
            data={'idempotency_key': 'synthetic-ww-smoke-pause'}, cookie=cookie, csrf=csrf)
        check('ww_pause_synthetic_only', status == 200 and paused.get('strategy') == WW
              and paused.get('accounts', [{}])[0].get('status') == 'paused')
        status, _, original = await request(app, base, query='strategy=D0', cookie=cookie)
        check('original_d0_still_has_no_account', status == 200 and original.get('accounts') == []
              and app.state.realtime_paper.ledger.snapshot().get('account') is None)
        raw = app.state.ww_paper.ledger.snapshot()
        check('ww_no_backfilled_fills_or_orders', raw.get('fills') == [] and raw.get('orders') == [])
    finally:
        raw = await asyncio.to_thread(app.state.ww_paper.snapshot)
        if raw.get('account') is not None:
            await asyncio.to_thread(app.state.ww_paper.set_running, False,
                                    idempotency_key='synthetic-ww-smoke-final-pause')


async def exercise(repo, timeout):
    print(json.dumps({'phase': 'synthetic_app_import', 'network': 'blocked'}), flush=True)
    sys.path.insert(0, str(repo / 'production'))
    from server import create_app, hash_password, FolderLock
    password = secrets.token_urlsafe(28)
    os.environ['ETF_WEB_PASSWORD_HASH'] = hash_password(password)
    parent = Path(os.environ.get('ETF_TEST_TMPDIR', tempfile.gettempdir())).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ww-actual-app-smoke-', dir=parent) as home:
        # The only data home comes from TemporaryDirectory, never from a CLI arg.
        os.environ['SIMPLE_ETF_HOME'] = home
        os.environ['ETF_SUITE_HOME'] = home
        app = create_app(home)
        began = time.monotonic()
        print(json.dumps({'phase': 'synthetic_app_startup', 'runtime_data': 'temporary_only'}), flush=True)
        async with app.router.lifespan_context(app):
            ready = await asyncio.to_thread(app.state.runtime.ready.wait, min(120, timeout - 30))
            elapsed = time.monotonic() - began
            check('actual_app_startup', ready and not app.state.runtime.init_error and elapsed <= 120,
                  seconds=round(elapsed, 3), maximum_seconds=120)
            names = ('realtime_paper', 'ww_paper', 'd0_comparison', 'ww_comparison',
                     'benchmark', 'market_indices', 'research', 'sector_research')
            check('all_services_initialized', all(getattr(app.state, name, None) is not None for name in names))
            check('financial_automation_disabled', app.state.runtime.settings.get('auto_refresh') is False
                  and app.state.runtime.settings.get('auto_simulate') is False)
            status, _, value = await request(app, '/healthz')
            check('health_ready', status == 200 and value.get('status') == 'ok')
            check('unauthenticated_catalog_rejected', (await request(app, '/api/catalog'))[0] == 401)
            status, _, _ = await request(app, '/api/login', method='POST', data={'password': 'synthetic-wrong-password'})
            check('incorrect_login_rejected', status == 401)
            status, headers, login = await request(app, '/api/login', method='POST', data={'password': password})
            check('synthetic_login', status == 200 and login.get('authenticated') is True)
            cookie, csrf = headers['set-cookie'].split(';', 1)[0], login['csrf']
            check('secure_cookie', all(flag in headers['set-cookie'].lower()
                                      for flag in ('httponly', 'secure', 'samesite=strict')))
            for path in ('/api/catalog', '/api/overview'):
                status, _, value = await request(app, path, cookie=cookie)
                check('authenticated_' + path, status == 200 and bool(value))
            status, _, value = await request(app, '/api/accounts', cookie=cookie)
            check('fresh_historical_accounts', status == 200 and value == [])
            for supplied in (None, 'synthetic-invalid-csrf'):
                status, _, _ = await request(app, '/api/settings', method='POST',
                    data={'auto_refresh': False}, cookie=cookie, csrf=supplied)
                check('missing_csrf_rejected' if supplied is None else 'invalid_csrf_rejected', status == 403)
            status, _, settings = await request(app, '/api/settings', method='POST',
                data={'auto_refresh': False}, cookie=cookie, csrf=csrf)
            check('valid_csrf_synthetic_settings', status == 200 and settings.get('auto_refresh') is False)
            status, _, _ = await request(app, '/api/settings', method='POST', data={'auto_refresh': False},
                cookie=cookie, csrf=csrf, origin='https://synthetic-outside.invalid')
            check('cross_origin_write_rejected', status == 403)
            await exercise_ww(app, cookie, csrf)
            status, _, _ = await request(app, '/api/logout', method='POST', cookie=cookie, csrf=csrf)
            check('logout', status == 200)
            check('logged_out_cookie_rejected', (await request(app, '/api/catalog', cookie=cookie))[0] == 401)
        check('runtime_shutdown_confirmed', app.state.runtime.shutdown_verified is True
              and not app.state.runtime.thread.is_alive() and not app.state.runtime.scheduler.is_alive()
              and app.state.runtime.signals.shutdown_complete is True)
        check('both_paper_services_closed', app.state.realtime_paper.closed is True and app.state.ww_paper.closed is True)
        lock = FolderLock(Path(home) / 'web/server.lock')
        lock.close()
        check('exclusive_runtime_lock_released', True)
    peak_file = Path('/sys/fs/cgroup/memory.peak')
    print(json.dumps(dict(status='passed', checks=len(CHECKS), passed=sum(row['passed'] for row in CHECKS),
        platform=sys.platform, linux=sys.platform.startswith('linux'), network='blocked',
        runtime_data='fresh temporary synthetic home only',
        cgroup_memory_peak_bytes=int(peak_file.read_text()) if peak_file.is_file() else None)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if args.timeout < 60 or args.timeout > 900:
        parser.error('timeout must be 60..900 seconds')
    repo = args.repo.resolve()
    if not (repo / 'production/server.py').is_file():
        parser.error('repo does not contain the maintained application')
    def expired():
        print(json.dumps({'status': 'failed', 'reason': 'synthetic_smoke_timeout'}), flush=True)
        os._exit(124)
    timer = threading.Timer(args.timeout, expired)
    timer.daemon = True
    timer.start()
    safe = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR',
        'ETF_TEST_TMPDIR', 'PATH', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH',
        'RELEASE_REVISION') if key in os.environ}
    safe.update(ETF_WEB_AUTO_REFRESH='0', ETF_WEB_BENCHMARK_REFRESH='0', ETF_WEB_INDEX_BENCHMARK_REFRESH='0',
        ETF_SECTOR_RESEARCH_AUTO_UPDATE='0', ETF_WEB_SECURE_COOKIE='1', ETF_WEB_TRUSTED_HOSTS='testserver',
        PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2')
    logging.basicConfig(level=logging.ERROR)
    try:
        # On Windows, initialize the event-loop socket pair before blocking IO.
        with asyncio.Runner() as runner:
            runner.get_loop()
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, safe, clear=True))
                for target in ('socket.create_connection', 'socket.getaddrinfo',
                               'socket.socket.connect', 'socket.socket.connect_ex'):
                    stack.enter_context(patch(target, side_effect=RuntimeError('network disabled in synthetic smoke')))
                runner.run(exercise(repo, args.timeout))
    finally:
        timer.cancel()


if __name__ == '__main__':
    main()
