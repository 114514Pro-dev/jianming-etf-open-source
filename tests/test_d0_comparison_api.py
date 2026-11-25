"""Authenticated comparison routes use only synthetic services and private homes."""
import asyncio
from contextlib import asynccontextmanager, ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from server import create_app, hash_password


PATH = '/api/realtime-paper/comparison'
IDENTITY = 'synthetic_D0-account_2026'


async def request(app, path, *, query_string=b'', method='GET', data=None, cookie=None, csrf=None, origin=None,
                  peer='127.0.0.1', as_json=True):
    """Small ASGI client that keeps the path separate from the query bytes."""
    body = b'' if data is None else json.dumps(data).encode()
    headers = [(b'host', b'testserver'), (b'content-length', str(len(body)).encode())]
    if data is not None:
        headers.append((b'content-type', b'application/json'))
    for name, value in (('cookie', cookie), ('x-csrf-token', csrf), ('origin', origin)):
        if value:
            headers.append((name.encode(), value.encode()))
    query = query_string.encode('ascii') if isinstance(query_string, str) else query_string
    scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method=method,
                 scheme='https', path=path, raw_path=path.encode(), query_string=query,
                 root_path='', headers=headers, client=(peer, 52000), server=('testserver', 443))
    sent, output = False, []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return dict(type='http.request', body=body, more_body=False)
        await asyncio.Future()

    async def send(message):
        output.append(message)

    await app(scope, receive, send)
    response = next(row for row in output if row['type'] == 'http.response.start')
    payload = b''.join(row.get('body', b'') for row in output if row['type'] == 'http.response.body')
    return (response['status'], {key.decode().lower(): value.decode() for key, value in response['headers']},
            json.loads(payload) if as_json else payload)


class SyntheticRuntime:
    def __init__(self, home):
        self.home, self.dependencies = home, []

    def status(self):
        return {'ready': True}

    def register_shutdown_dependency(self, service, *, name='dependency', stopped=None):
        self.dependencies.append((name, service, stopped))


class ComparisonApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'Synthetic-comparison-only-2026'
        cls.encoded = hash_password(cls.password)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.home = Path(self.temp.name)
        self.home.joinpath('web').mkdir(mode=0o700)
        self.auth = self.home / 'web' / 'auth.json'
        self.auth.write_text(json.dumps({'password_hash': self.encoded}), encoding='utf8')
        self.auth.chmod(0o600)
        self.sentinel = self.home / 'synthetic-production-ledger.json'
        self.sentinel.write_bytes(b'{"never":"edit this ledger","fills":[]}')
        self.before = {path: path.read_bytes() for path in (self.auth, self.sentinel)}
        self.payload = {'schema': 'synthetic-comparison.v1', 'account_id': IDENTITY,
                        'status': 'waiting', 'series': [{'id': 'account', 'points': []}]}
        self.service = Mock(spec=['snapshot', 'thread'])
        self.service.thread = None
        self.service.snapshot.return_value = self.payload
        self.paper = object()
        self.stack = ExitStack()
        self.stack.enter_context(patch.dict(os.environ, {'ETF_WEB_PASSWORD_HASH': '',
            'ETF_WEB_SECURE_COOKIE': '1', 'ETF_WEB_TRUSTED_HOSTS': 'testserver'}))
        self.stack.enter_context(patch('server.Runtime', SyntheticRuntime))
        self.shutdown = self.stack.enter_context(patch('server.shutdown_runtime', new_callable=AsyncMock))
        self.factory = self.stack.enter_context(patch('realtime_paper_comparison.D0ComparisonService',
                                                     return_value=self.service))
        for target in ('account_benchmark_service.AccountBenchmarkService',
                       'market_index_service.MarketIndexBenchmarkService',
                       'company_research.service.ResearchService',
                       'sector_research.research_service.ResearchService'):
            self.stack.enter_context(patch(target, return_value=None))
        self.stack.enter_context(patch('socket.create_connection', side_effect=AssertionError('No test network')))

    async def asyncTearDown(self):
        self.stack.close()
        try:
            for path, body in self.before.items():
                self.assertEqual(path.read_bytes(), body)
        finally:
            self.temp.cleanup()

    @asynccontextmanager
    async def app(self):
        app = create_app(self.home, paper_factory=lambda _: self.paper)
        async with app.router.lifespan_context(app):
            yield app

    async def login(self, app):
        status, headers, body = await request(app, '/api/login', method='POST',
                                              data={'password': self.password})
        self.assertEqual(status, 200)
        return headers['set-cookie'].split(';', 1)[0], body['csrf']

    async def comparison(self, app, identity=IDENTITY, **kwargs):
        return await request(app, PATH, query_string=urlencode({'account_id': identity}), **kwargs)

    async def test_anonymous_request_is_unauthorized_before_reading_the_service(self):
        async with self.app() as app:
            status, headers, _ = await self.comparison(app)
        self.assertEqual(status, 401)
        self.assertEqual(headers['cache-control'], 'no-store')
        self.service.snapshot.assert_not_called()

    async def test_authenticated_get_passes_identity_and_payload_without_requiring_csrf(self):
        async with self.app() as app:
            cookie, _ = await self.login(app)
            status, headers, body = await self.comparison(app, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(headers['cache-control'], 'no-store')
        self.assertEqual(body, self.payload)
        self.service.snapshot.assert_called_once_with(IDENTITY)

    async def test_live_signal_export_is_authenticated_and_read_only(self):
        from datetime import datetime
        from live_signal import project_live_signal
        from realtime_paper_engine import TradingCalendar, TZ

        now = datetime(2026, 10, 28, 10, tzinfo=TZ)
        signal = dict(id='test-D0', valid=True, strategy='D0', confirmed_day='2026-10-27',
                      execution_day='2026-10-28', data_cutoff='2026-10-27T15:00:00+08:00',
                      known_at='2026-10-27T16:10:00+08:00', eligible_at='2026-10-28T09:30:00+08:00',
                      weights={'sz159915': '0.6', 'sh511010': '0.25'})
        self.paper = Mock(spec=['export_live_signal'])
        self.paper.export_live_signal.side_effect = lambda: project_live_signal(
            signal=signal, strategy='D0', calendar=TradingCalendar(), now=now,
            observed_at=now, source_status='ready')
        endpoint = '/api/live-trading/signal'
        async with self.app() as app:
            self.assertEqual((await request(app, endpoint))[0], 401)
            self.paper.export_live_signal.assert_not_called()
            cookie, csrf = await self.login(app)
            status, headers, body = await request(app, endpoint, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertEqual(headers['cache-control'], 'no-store')
            self.assertEqual(body['targets'], {'SZSE.159915': '0.6', 'SHSE.511010': '0.25',
                                               'SHSE.518880': '0', 'SHSE.512800': '0'})
            self.assertEqual(body['cash_weight'], '0.15')
            self.assertNotIn('orders', body)
            self.assertEqual((await request(app, endpoint, method='POST', cookie=cookie, csrf=csrf))[0], 405)
            signal['confirmed_day'] = '2026-10-26'
            self.assertEqual((await request(app, endpoint, cookie=cookie))[0], 409)

    async def test_invalid_account_ids_are_rejected_before_the_service(self):
        async with self.app() as app:
            cookie, _ = await self.login(app)
            for identity in ('', '../ledger', 'x' * 101, '中文账户', 'bad\x00id', 'with space'):
                with self.subTest(identity=repr(identity)):
                    status, headers, body = await self.comparison(app, identity, cookie=cookie)
                    self.assertEqual(status, 400)
                    self.assertEqual(body['code'], 'INVALID_REQUEST')
                    self.assertEqual(headers['cache-control'], 'no-store')
        self.service.snapshot.assert_not_called()

    async def test_write_methods_keep_csrf_guard_and_never_reach_a_write_route(self):
        async with self.app() as app:
            cookie, csrf = await self.login(app)
            for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                with self.subTest(method=method):
                    self.assertEqual((await self.comparison(app, method=method, cookie=cookie))[0], 403)
                    status, headers, _ = await self.comparison(app, method=method, cookie=cookie, csrf=csrf)
                    self.assertEqual(status, 405)
                    self.assertIn('GET', headers['allow'])
        self.service.snapshot.assert_not_called()

    async def test_unavailable_service_and_failed_startup_return_public_503(self):
        for failed_startup in (False, True):
            with self.subTest(failed_startup=failed_startup):
                self.factory.side_effect = RuntimeError('private startup path /private/secret') if failed_startup else None
                self.factory.return_value = None
                with self.assertLogs('etfweb', level='ERROR') if failed_startup else ExitStack():
                    async with self.app() as app:
                        cookie, _ = await self.login(app)
                        status, headers, body = await self.comparison(app, cookie=cookie)
                self.assertEqual(status, 503)
                self.assertEqual(body['code'], 'COMPARISON_UNAVAILABLE')
                self.assertEqual(headers['cache-control'], 'no-store')
                self.assertNotIn('private', json.dumps(body))
        self.service.snapshot.assert_not_called()

    async def test_service_errors_are_503_and_do_not_expose_exception_details(self):
        async with self.app() as app:
            cookie, _ = await self.login(app)
            for error in (ValueError('private-state-token'), RuntimeError('private-state-token')):
                with self.subTest(error=type(error).__name__), self.assertLogs('etfweb', level='ERROR') as log:
                    self.service.snapshot.side_effect = error
                    status, headers, body = await self.comparison(app, cookie=cookie)
                    self.assertEqual(status, 503)
                    self.assertEqual(body['code'], 'COMPARISON_UNAVAILABLE')
                    self.assertEqual(headers['cache-control'], 'no-store')
                    self.assertNotIn('private-state-token', json.dumps(body))
                    self.assertNotIn('private-state-token', '\n'.join(log.output))

    async def test_slow_snapshot_runs_in_a_worker_without_blocking_the_event_loop(self):
        started, release, worker_ids = threading.Event(), threading.Event(), []

        def delayed(identity):
            worker_ids.append(threading.get_ident())
            started.set()
            if not release.wait(3):
                raise AssertionError('comparison worker was not released')
            return self.payload

        self.service.snapshot.side_effect = delayed
        async with self.app() as app:
            cookie, _ = await self.login(app)
            pending = asyncio.create_task(self.comparison(app, cookie=cookie))
            try:
                self.assertTrue(await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 1.5))
                self.assertFalse(pending.done())
                self.assertNotEqual(worker_ids, [threading.get_ident()])
                self.assertEqual((await asyncio.wait_for(request(app, '/healthz'), .5))[0], 200)
            finally:
                release.set()
                result = await pending
            self.assertEqual(result[0], 200)

    async def test_lifespan_registers_the_owned_thread_and_awaits_runtime_shutdown(self):
        release = threading.Event()
        thread = threading.Thread(target=release.wait, name='synthetic-comparison-worker', daemon=True)
        self.service.thread = thread
        thread.start()
        try:
            async with self.app() as app:
                runtime = app.state.runtime
                self.factory.assert_called_once_with(self.home / 'web' / 'd0-performance-comparison', self.paper, None)
                dependencies = {name: (service, stopped) for name, service, stopped in runtime.dependencies}
                self.assertIs(dependencies['paper'][0], self.paper)
                service, stopped = dependencies['D0 comparison']
                self.assertIs(service, self.service)
                self.assertFalse(stopped())
                release.set()
                await asyncio.to_thread(thread.join, 1)
                self.assertFalse(thread.is_alive())
                self.assertTrue(stopped())
            self.shutdown.assert_awaited_once_with(runtime, interrupted=False)
        finally:
            release.set()
            await asyncio.to_thread(thread.join, 1)


if __name__ == '__main__':
    unittest.main()
