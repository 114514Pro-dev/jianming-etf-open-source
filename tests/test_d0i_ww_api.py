"""Strategy-scoped paper routes and backups, using only synthetic private homes."""
import asyncio
from contextlib import ExitStack, contextmanager, closing
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from server import create_app, hash_password, verify_paper_backup, Runtime
from realtime_paper_backup import (snapshot_business_for_backup, BusinessBackupError,
    PAPER_PATH, WW_PAPER_PATH, HISTORY_PATHS)
from realtime_paper_engine import PaperLedger
from test_d0_comparison_api import request, SyntheticRuntime
from test_emtl_d0 import inputs as preview_inputs, NOW as PREVIEW_NOW

WW = 'D0I-BOND-WW'


class SyntheticPaper:
    def __init__(self, strategy):
        self.strategy, self.actions = strategy, []
        self.identity = strategy + '-forward-paper'
        self.account = None

    def snapshot(self):
        return {'contract_version': 'realtime-paper-v1', 'accounts': [] if self.account is None else [dict(self.account)]}

    def account_detail(self, account_id):
        if account_id != self.identity or self.account is None:
            error = ValueError('missing'); error.code = 'ACCOUNT_NOT_FOUND'; raise error
        return {'account': dict(self.account)}

    def create_account(self, name, initial_cash, idempotency_key):
        self.actions.append(('create', name, initial_cash, idempotency_key))
        self.account = {'id': self.identity, 'strategy': self.strategy, 'name': name,
                        'cash': initial_cash, 'status': 'stopped'}
        return self.snapshot()

    def start_account(self, account_id, idempotency_key):
        self.account_detail(account_id)
        self.actions.append(('start', account_id, idempotency_key))
        self.account['status'] = 'running'
        return self.snapshot()

    def pause_account(self, account_id, idempotency_key):
        self.account_detail(account_id)
        self.actions.append(('pause', account_id, idempotency_key))
        self.account['status'] = 'paused'
        return self.snapshot()


class ScopedApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'Synthetic-only-WW-scope-2026'
        cls.encoded = hash_password(cls.password)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.home = Path(self.temp.name)
        (self.home / 'web').mkdir()
        auth = self.home / 'web/auth.json'
        auth.write_text(json.dumps({'password_hash': self.encoded}), encoding='utf8')
        auth.chmod(0o600)
        self.d0, self.ww = SyntheticPaper('D0'), SyntheticPaper(WW)
        self.stack = ExitStack()
        self.stack.enter_context(patch.dict(os.environ, {'ETF_WEB_PASSWORD_HASH': '', 'ETF_D0_WEB_PREVIEW': '0', 'ETF_EMTL_WEB_LIVE': '0',
            'ETF_WEB_SECURE_COOKIE': '1', 'ETF_WEB_TRUSTED_HOSTS': 'testserver'}))
        self.stack.enter_context(patch('server.Runtime', SyntheticRuntime))
        self.stack.enter_context(patch('server.shutdown_runtime', new_callable=AsyncMock))
        self.comparisons = {}
        def comparison_factory(folder, paper, indices, **options):
            service = Mock(spec=['snapshot', 'thread']); service.thread = None
            strategy = options.get('strategy', 'D0')
            service.snapshot.return_value = {'strategy': strategy, 'account_id': paper.identity}
            self.comparisons[strategy] = service
            return service
        self.stack.enter_context(patch('realtime_paper_comparison.D0ComparisonService', side_effect=comparison_factory))
        for target in ('account_benchmark_service.AccountBenchmarkService',
                       'market_index_service.MarketIndexBenchmarkService',
                       'company_research.service.ResearchService',
                       'sector_research.research_service.ResearchService'):
            self.stack.enter_context(patch(target, return_value=None))
        self.app = create_app(self.home, paper_factory=lambda _: self.d0, ww_paper_factory=lambda _: self.ww)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        status, headers, body = await request(self.app, '/api/login', method='POST', data={'password': self.password})
        self.assertEqual(status, 200)
        self.cookie, self.csrf = headers['set-cookie'].split(';', 1)[0], body['csrf']

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)
        self.stack.close(); self.temp.cleanup()

    async def call(self, path='/api/realtime-paper', *, strategy=None, method='GET', data=None, csrf=True):
        query = '' if strategy is None else 'strategy=' + strategy
        return await request(self.app, path, query_string=query, method=method, data=data,
                             cookie=self.cookie, csrf=self.csrf if csrf else None)

    async def test_web_control_opt_in_auth_same_origin_and_preview_only(self):
        path = '/api/d0-control'
        status, _, _ = await self.call(path + '/status')
        self.assertEqual(status, 404)
        snapshot, balances = preview_inputs()
        self.d0.order_preview_input = lambda: snapshot
        with patch.dict(os.environ, {'ETF_D0_WEB_PREVIEW': '1'}):
            app = create_app(self.home, paper_factory=lambda _: self.d0, ww_paper_factory=lambda _: self.ww)
        async with app.router.lifespan_context(app):
            status, _, _ = await request(app, path + '/status')
            self.assertEqual(status, 401)
            status, headers, body = await request(app, '/api/login', method='POST', data={'password': self.password})
            cookie, csrf = headers['set-cookie'].split(';', 1)[0], body['csrf']
            status, headers, result = await request(app, path + '/status', cookie=cookie)
            self.assertEqual((status, headers['cache-control'], result['live_orders_enabled']), (200, 'no-store', False))
            self.assertEqual(result['broker_state'], 'disabled')
            status, _, _ = await request(app, path + '/broker/connect', method='POST', data={},
                                         cookie=cookie, csrf=csrf, origin='https://testserver')
            self.assertEqual(status, 404)
            for token, origin in ((None, 'https://testserver'), (csrf, None), (csrf, 'https://other.invalid')):
                status, _, _ = await request(app, path + '/preview', method='POST', data=balances, cookie=cookie, csrf=token, origin=origin)
                self.assertEqual(status, 403)
            with patch('server.datetime', wraps=datetime) as clock:
                clock.now.return_value = PREVIEW_NOW
                status, _, result = await request(app, path + '/preview', method='POST', data=balances,
                                                  cookie=cookie, csrf=csrf, origin='https://testserver')
            self.assertEqual((status, result['mode'], result['orders'][0]['quantity']), (200, 'preview_only', 500))
            status, _, _ = await request(app, path + '/submit', method='POST', data=balances,
                                         cookie=cookie, csrf=csrf, origin='https://testserver')
            self.assertEqual(status, 404)
            self.assertFalse(self.d0.actions)

    async def test_emtl_web_requires_private_https_and_binds_to_website_session(self):
        env = {'ETF_D0_WEB_PREVIEW': '1', 'ETF_EMTL_WEB_LIVE': '1', 'ETF_EMTL_ORIGIN': 'http://testserver'}
        with patch.dict(os.environ, env), self.assertRaisesRegex(RuntimeError, 'HTTPS'):
            create_app(self.home)
        snapshot, _ = preview_inputs()
        self.d0.order_preview_input = lambda: snapshot
        desk = Mock()
        desk.connect.return_value = {'connected': True, 'account_tail': '1234'}
        peer = '198.51.100.10'
        config = {**env, 'ETF_EMTL_ORIGIN': 'https://testserver', 'ETF_EMTL_ALLOWED_IPS': peer,
                  'ETF_EMTL_ORDERS_ENABLED': '0', 'FORWARDED_ALLOW_IPS': '127.0.0.1'}
        with patch.dict(os.environ, {**config, 'FORWARDED_ALLOW_IPS': '*'}), self.assertRaisesRegex(RuntimeError, '通配符'):
            create_app(self.home)
        with patch.dict(os.environ, config):
            app = create_app(self.home, paper_factory=lambda _: self.d0, ww_paper_factory=lambda _: self.ww)
        path = '/api/d0-control/broker/connect'
        data = {'username': '000001234', 'password': 'test-password'}
        with patch('emtl_live.BrokerDesk.from_env', return_value=desk):
            async with app.router.lifespan_context(app):
                status, _, _ = await request(app, path, method='POST', data=data)
                self.assertEqual(status, 401)
                _, headers, body = await request(app, '/api/login', method='POST', data={'password': self.password})
                cookie, csrf = headers['set-cookie'].split(';', 1)[0], body['csrf']
                status, _, availability = await request(app, '/api/d0-control/status', cookie=cookie)
                self.assertEqual((status, availability['broker_state'], availability['live_orders_enabled']),
                                 (200, 'private_origin_required', False))
                _, _, availability = await request(app, '/api/d0-control/status', cookie=cookie, peer=peer)
                self.assertEqual((availability['broker_state'], availability['live_orders_enabled']), ('available', False))
                status, _, _ = await request(app, path, method='POST', data=data, cookie=cookie, csrf=csrf, peer=peer)
                self.assertEqual(status, 403)
                desk.connect.assert_not_called()
                status, _, body = await request(app, path, method='POST', data=data,
                                                cookie=cookie, csrf=csrf, origin='https://testserver', peer=peer)
                self.assertEqual((status, body['account_tail']), (200, '1234'))
                owner, name, password = desk.connect.call_args.args
                self.assertEqual(owner, hashlib.sha256(cookie.split('=', 1)[1].encode()).hexdigest())
                self.assertEqual((name, password), (data['username'], data['password']))
                options = dict(method='POST', cookie=cookie, csrf=csrf, origin='https://testserver', peer=peer)
                status, _, _ = await request(app, '/api/d0-control/broker/submit', data={}, **options)
                self.assertEqual(status, 403)
                desk.submit.assert_not_called()
                limits = {'single_cny': '800000', 'daily_cny': '5000000'}
                desk.update_limits.return_value = limits
                status, _, result = await request(app, '/api/d0-control/broker/limits', data=limits, **options)
                self.assertEqual((status, result), (200, limits))
                desk.update_limits.assert_called_once_with(owner, limits)
                desk.bound = False
                fields = {**data, 'enrollment_code': 'E' * 43, 'confirmation': '同意绑定'}
                action = '/api/d0-control/broker/enroll'
                denied = {**options, 'peer': '198.51.100.11'}
                self.assertEqual((await request(app, action, data=fields, **denied))[0], 403)
                desk.enroll.assert_not_called()
                desk.enroll.return_value = {'connected': True, 'account_bound': True, 'account_tail': '1234'}
                status, _, result = await request(app, action, data=fields, **options)
                self.assertEqual((status, result['account_bound']), (200, True))
                desk.enroll.assert_called_once_with(owner, fields)
            desk.close.assert_called_once()

    async def test_connector_status_is_session_bound_and_native_code_single_use(self):
        with patch.dict(os.environ, {'ETF_D0_WEB_PREVIEW': '1'}):
            app = create_app(self.home, paper_factory=lambda _: self.d0, ww_paper_factory=lambda _: self.ww)
        callbacks = []
        self.d0.set_signal_listener = callbacks.append
        prefix = '/api/d0-control/sync/'
        site = 'https://testserver'
        async with app.router.lifespan_context(app):
            self.assertEqual((await request(app, prefix + 'status'))[0], 401)
            _, headers, body = await request(app, '/api/login', method='POST', data={'password': self.password})
            cookie, csrf = headers['set-cookie'].split(';', 1)[0], body['csrf']
            self.assertEqual((await request(app, prefix + 'pair', method='POST', cookie=cookie, csrf=csrf))[0], 403)
            status, headers, pair = await request(app, prefix + 'pair', method='POST', cookie=cookie, csrf=csrf, origin=site)
            self.assertEqual((status, headers['cache-control']), (200, 'no-store'))
            status, headers, zipped = await request(app, prefix + 'download', cookie=cookie, as_json=False)
            self.assertEqual((status, headers['content-type'], headers['cache-control']), (200, 'application/zip', 'no-store'))
            with zipfile.ZipFile(BytesIO(zipped)) as archive:
                self.assertEqual({Path(name).name for name in archive.namelist()},
                                 {'launch.cmd', 'bootstrap.ps1', 'pilot.py', 'requirements-win.lock', 'README.txt'})
            identity = {'code': pair['code']}
            self.assertEqual((await request(app, prefix + 'claim', method='POST', data=identity, origin=site))[0], 403)
            status, _, linked = await request(app, prefix + 'claim', method='POST', data=identity)
            self.assertEqual(status, 200)
            self.assertEqual((await request(app, prefix + 'claim', method='POST', data=identity))[0], 409)
            self.assertEqual((await request(app, prefix + 'status', cookie=cookie))[2], {'state': 'linked'})
            _, other_headers, _ = await request(app, '/api/login', method='POST', data={'password': self.password})
            other = other_headers['set-cookie'].split(';', 1)[0]
            self.assertEqual((await request(app, prefix + 'status', cookie=other))[2], {'state': 'not_linked'})
            fields = {'sync_token': linked['sync_token'], 'state': 'verified'}
            self.assertEqual((await request(app, prefix + 'report', method='POST', data={**fields, 'cash': 123}))[0], 400)
            self.assertEqual((await request(app, prefix + 'report', method='POST', data=fields))[0], 200)
            self.assertEqual((await request(app, prefix + 'report', method='POST', data=fields))[0], 409)
            self.assertEqual((await request(app, prefix + 'status', cookie=cookie))[2], {'state': 'verified'})
            self.assertEqual((await request(app, prefix + 'signal', authorization='Bearer ' + linked['sync_token']))[0], 401)
            auth = 'Bearer ' + linked['signal_token']
            status, _, first = await request(app, prefix + 'signal', authorization=auth)
            self.assertEqual((status, first['signal']), (200, None))
            watcher = asyncio.create_task(request(app, prefix + 'signal', query_string='after=' + first['cursor'], authorization=auth))
            await asyncio.sleep(.02)
            self.assertFalse(watcher.done())
            signal = {'schema': 'jianming-etf.confirmed-target.v1', 'strategy': 'D0', 'signal_id': 'synthetic'}
            callbacks[0](signal)
            _, _, update = await asyncio.wait_for(watcher, 1)
            self.assertEqual(update['signal'], signal)
            self.assertNotEqual(update['cursor'], first['cursor'])
            self.assertEqual((await request(app, '/api/logout', method='POST', cookie=cookie, csrf=csrf, origin=site))[0], 200)
            self.assertEqual((await request(app, prefix + 'signal', authorization=auth))[0], 401)

    async def test_default_and_ww_empty_snapshots_are_distinct_and_stopped(self):
        for code in ('D0', WW):
            status, _, value = await self.call(strategy=code)
            self.assertEqual(status, 200)
            self.assertEqual(value['strategy'], code)
            self.assertEqual(value['accounts'], [])
            self.assertEqual({v['code'] for v in value['strategies']}, {'D0', WW})
        self.assertEqual((self.d0.actions, self.ww.actions), ([], []))
        self.assertEqual((await self.call())[2]['strategy'], 'D0')

    async def test_ww_creation_start_and_wrong_account_never_touch_d0(self):
        status, _, result = await self.call('/api/realtime-paper/accounts', strategy=WW, method='POST',
            data={'name': 'Synthetic WW', 'initial_cash': '100000.00', 'idempotency_key': 'ww-create-key-123'})
        self.assertEqual(status, 200)
        self.assertEqual(result['strategy'], WW)
        self.assertEqual(result['accounts'][0]['status'], 'stopped')
        self.assertEqual(self.d0.actions, [])
        self.assertEqual((await self.call('/api/realtime-paper/accounts/' + self.ww.identity + '/start',
            strategy=WW, method='POST', data={'idempotency_key': 'ww-start-key-123'}))[0], 200)
        status, _, _ = await self.call('/api/realtime-paper/accounts/' + self.ww.identity + '/pause',
            strategy='D0', method='POST', data={'idempotency_key': 'wrong-scope-key-123'})
        self.assertEqual(status, 404)
        self.assertEqual(self.ww.account['status'], 'running')
        self.assertEqual(self.d0.actions, [])

    async def test_misbound_service_cannot_relabel_an_original_account_as_ww(self):
        self.d0.create_account('D0', '1000.00', 'synthetic-misbound-key')
        self.app.state.ww_paper = self.d0
        self.assertEqual((await self.call(strategy=WW))[0], 503)
        before = list(self.d0.actions)
        self.assertEqual((await self.call('/api/realtime-paper/accounts/' + self.d0.identity + '/start',
            strategy=WW, method='POST', data={'idempotency_key': 'misbound-write-key'}))[0], 503)
        self.assertEqual(self.d0.actions, before)

    async def test_real_ledger_service_adapter_round_trip_keeps_strategy_on_commands(self):
        from realtime_paper_service import PaperService
        moment = datetime(2026, 11, 2, 11, 0, tzinfo=timezone(timedelta(hours=8)))
        ledger = PaperLedger(self.home / 'web/realtime-paper-ww', strategy=WW, now=lambda: moment)
        service = PaperService(self.home, ledger=ledger, strategy=WW, now=lambda: moment, start_worker=False)
        self.app.state.ww_paper = service
        try:
            status, _, value = await self.call('/api/realtime-paper/accounts', strategy=WW, method='POST',
                data={'name': 'Actual synthetic WW', 'initial_cash': '100000.00', 'idempotency_key': 'real-ww-create-key'})
            self.assertEqual((status, value['strategy']), (200, WW))
            self.assertEqual(value['accounts'][0]['strategy'], WW)
            self.assertEqual(value['accounts'][0]['status'], 'stopped')
            identity = value['accounts'][0]['id']
            for operation, expected in (('start', 'running'), ('pause', 'paused')):
                status, _, command = await self.call('/api/realtime-paper/accounts/' + identity + '/' + operation,
                    strategy=WW, method='POST', data={'idempotency_key': 'real-ww-' + operation + '-key'})
                self.assertEqual((status, command['strategy']), (200, WW))
                self.assertEqual(command['accounts'][0]['strategy'], WW)
                self.assertEqual(command['accounts'][0]['status'], expected)
            self.assertEqual(ledger.snapshot()['fills'], [])
            self.assertEqual(self.d0.actions, [])
        finally:
            service.close()

    async def test_unknown_duplicate_and_body_strategy_are_rejected(self):
        self.assertEqual((await self.call(strategy='unknown'))[0], 400)
        self.assertEqual((await self.call(strategy='D0&strategy=' + WW))[0], 400)
        self.assertEqual((await self.call('/api/realtime-paper/accounts', strategy=WW, method='POST',
            data={'name': 'X', 'initial_cash': '1000', 'strategy': 'D0', 'idempotency_key': 'bad-body-key-123'}))[0], 400)
        self.assertEqual((self.d0.actions, self.ww.actions), ([], []))

    async def test_csrf_and_comparison_scope_are_preserved(self):
        self.assertEqual((await self.call('/api/realtime-paper/accounts', strategy=WW, method='POST',
            data={'name': 'X', 'initial_cash': '1000', 'idempotency_key': 'csrf-body-key-123'}, csrf=False))[0], 403)
        status, _, result = await request(self.app, '/api/realtime-paper/comparison',
            query_string='strategy=' + WW + '&account_id=' + self.ww.identity, cookie=self.cookie)
        self.assertEqual((status, result['strategy']), (200, WW))
        self.comparisons[WW].snapshot.assert_called_once_with(self.ww.identity)
        self.comparisons['D0'].snapshot.assert_not_called()
        dependencies = self.app.state.runtime.dependencies
        self.assertIn(self.ww, [service for _, service, _ in dependencies])

    async def test_default_production_ww_factory_is_bound_to_ww_strategy(self):
        # Exercise the real lifecycle branch without background IO or user data.
        captured = []
        def construct(home, *, ledger, source=None, strategy='D0'):
            captured.append((ledger.path, ledger.strategy, strategy, source))
            ledger.close()
            return self.ww if strategy == WW else self.d0
        with patch('realtime_paper_service.PaperService', side_effect=construct):
            app = create_app(self.home)
            async with app.router.lifespan_context(app):
                self.assertIs(app.state.ww_paper, self.ww)
        ww = [row for row in captured if row[1] == WW]
        self.assertEqual(len(ww), 1)
        self.assertEqual(ww[0][:3], (self.home / WW_PAPER_PATH, WW, WW))


class DualBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'; self.home.mkdir()
        self.opened = []
        self.services = []
        now = lambda: datetime(2026, 11, 2, 11, 0, tzinfo=timezone(timedelta(hours=8)))
        for relative in (PAPER_PATH, WW_PAPER_PATH):
            ledger = PaperLedger((self.home / relative).parent, now=now)
            @contextmanager
            def guard(timeout, relative=relative):
                self.opened.append(relative)
                try: yield
                finally: self.opened.remove(relative)
            service = type('Service', (), {})(); service.ledger = ledger; service.backup_guard = guard
            self.services.append(service)
        self.d0, self.ww = self.services
        self.target = self.root / 'target'; self.target.mkdir()

    def tearDown(self):
        for service in self.services: service.ledger.close()
        self.temp.cleanup()

    def test_both_guards_cover_copy_and_two_verified_sqlite_snapshots(self):
        from realtime_paper_history import durable_json, digest
        for relative in HISTORY_PATHS.values():
            value = {'schema': 'synthetic-integrity-only.v1', 'data': {'unchanged': True}}
            durable_json(self.home / relative / 'checkpoints/synthetic.json', {**value, 'integrity': digest(value)})
        def copy(home, target):
            self.assertEqual(self.opened, [PAPER_PATH, WW_PAPER_PATH])
            (target / 'public.json').write_text('{}')
        component = snapshot_business_for_backup(self.home, self.target, copy, self.d0,
            additional_services={WW: self.ww})
        self.assertEqual(self.opened, [])
        self.assertEqual(component['path'], PAPER_PATH)
        ww = component['additional_components']['realtime_paper_ww']
        self.assertEqual((ww['path'], ww['strategy']), (WW_PAPER_PATH, WW))
        for relative in (PAPER_PATH, WW_PAPER_PATH):
            with closing(sqlite3.connect(self.target / relative)) as db:
                self.assertEqual(db.execute('pragma integrity_check').fetchone(), ('ok',))
        archive = self.root / 'backup.zip'; hashes = {}
        components = {'realtime_paper': {k: v for k, v in component.items() if k != 'additional_components'},
                      **component['additional_components']}
        with zipfile.ZipFile(archive, 'w') as out:
            for path in self.target.rglob('*'):
                if path.is_file():
                    name = path.relative_to(self.target).as_posix()
                    hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest(); out.write(path, name)
            for value in components.values():
                if 'files' not in value: value['sha256'] = hashes[value['path']]
            out.writestr('备份校验.json', json.dumps({'created': datetime.now(timezone.utc).isoformat(),
                'sha256': hashes, 'components': components}))
        self.assertIsNotNone(verify_paper_backup(archive))

    def test_existing_ww_ledger_cannot_be_silently_omitted(self):
        with self.assertRaises(BusinessBackupError):
            snapshot_business_for_backup(self.home, self.target, lambda *_: None, self.d0)
        self.assertFalse((self.target / 'web').exists())
        self.assertEqual(self.opened, [])

    def test_legacy_single_ledger_backup_and_draft_settings_remain_independent(self):
        legacy = self.root / 'legacy'; legacy.mkdir()
        ledger = PaperLedger((legacy / PAPER_PATH).parent)
        target = self.root / 'legacy-target'; target.mkdir()
        @contextmanager
        def guard(timeout): yield
        service = type('Service', (), {'ledger': ledger, 'backup_guard': staticmethod(guard)})()
        try:
            component = snapshot_business_for_backup(legacy, target, lambda *_: None, service)
            self.assertEqual(component['path'], PAPER_PATH)
            self.assertNotIn('additional_components', component)
        finally:
            ledger.close()
        runtime = Runtime.__new__(Runtime)
        runtime.settings_lock = threading.RLock(); runtime.settings = {}; runtime.private = legacy / 'web'
        def snapshot(strategy):
            return {'contract_version': 'realtime-paper-v1', 'accounts': [{
                'id': strategy + '-forward-paper', 'strategy': strategy, 'status': 'stopped',
                'created_at': '2026-11-02T11:00:00+08:00'}]}
        for strategy in ('D0', WW):
            response = runtime.email_draft(lambda strategy=strategy: snapshot(strategy),
                {'recipient': ('d0' if strategy == 'D0' else 'ww') + '@example.com',
                 'account_id': strategy + '-forward-paper'}, save=True, strategy=strategy)
            self.assertEqual(response['binding']['status'], 'available')
            self.assertFalse(response['sending_enabled'])
        self.assertEqual(runtime.email_draft(lambda: snapshot('D0'))['draft']['recipient'], 'd0@example.com')
        self.assertEqual(runtime.email_draft(lambda: snapshot(WW), strategy=WW)['draft']['recipient'], 'ww@example.com')


if __name__ == '__main__': unittest.main()
