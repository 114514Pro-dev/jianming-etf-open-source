"""Independent real-ledger HTTP checks, confined to disposable synthetic homes."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from server import create_app, hash_password
from realtime_paper_engine import PaperLedger
from realtime_paper_service import PaperService
from test_d0_comparison_api import request, SyntheticRuntime

WW = 'D0I-BOND-WW'


class RealLedgerScopedHttpTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = 'Synthetic-independent-WW-review-2026'
        cls.password_hash = hash_password(cls.password)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.home = Path(self.temp.name)
        (self.home / 'web').mkdir()
        auth = self.home / 'web/auth.json'
        auth.write_text(json.dumps({'password_hash': self.password_hash}), encoding='utf8')
        auth.chmod(0o600)
        moment = datetime(2026, 11, 2, 11, 0, tzinfo=timezone(timedelta(hours=8)))
        self.services = {}
        for code, folder in [('D0', 'realtime-paper'), (WW, 'realtime-paper-ww')]:
            ledger = PaperLedger(self.home / 'web' / folder, now=lambda: moment, strategy=code)
            self.services[code] = PaperService(self.home, ledger=ledger, now=lambda: moment,
                source=SimpleNamespace(strategy=code), strategy=code, start_worker=False)
        self.stack = ExitStack()
        self.stack.enter_context(patch.dict(os.environ, {'ETF_WEB_PASSWORD_HASH': '',
            'ETF_WEB_SECURE_COOKIE': '1', 'ETF_WEB_TRUSTED_HOSTS': 'testserver'}))
        self.stack.enter_context(patch('server.Runtime', SyntheticRuntime))
        self.stack.enter_context(patch('server.shutdown_runtime', new_callable=AsyncMock))
        self.stack.enter_context(patch('realtime_paper_comparison.D0ComparisonService', return_value=None))
        for target in ('account_benchmark_service.AccountBenchmarkService',
                       'market_index_service.MarketIndexBenchmarkService',
                       'company_research.service.ResearchService',
                       'sector_research.research_service.ResearchService'):
            self.stack.enter_context(patch(target, return_value=None))
        self.stack.enter_context(patch('socket.create_connection', side_effect=AssertionError('No test network')))
        self.app = create_app(self.home, paper_factory=lambda _: self.services['D0'],
                              ww_paper_factory=lambda _: self.services[WW])
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        status, headers, body = await request(self.app, '/api/login', method='POST',
                                              data={'password': self.password})
        self.assertEqual(status, 200)
        self.cookie = headers['set-cookie'].split(';', 1)[0]
        self.csrf = body['csrf']

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)
        self.stack.close()
        for service in self.services.values():
            service.close()
        self.temp.cleanup()

    async def call(self, strategy, path='/api/realtime-paper', *, method='GET', body=None):
        return await request(self.app, path, query_string='strategy=' + strategy,
            method=method, data=body, cookie=self.cookie, csrf=self.csrf)

    async def create(self, strategy, amount='100000.00'):
        # Equal operation keys across the two ledgers must remain independent.
        return await self.call(strategy, '/api/realtime-paper/accounts', method='POST',
            body={'name': 'Synthetic ' + strategy, 'initial_cash': amount,
                  'idempotency_key': 'independent-create-key'})

    async def test_real_ww_command_responses_keep_identity_and_default_stop(self):
        status, _, result = await self.create(WW)
        self.assertEqual(status, 200)
        self.assertEqual(result.get('strategy'), WW)
        account = result['accounts'][0]
        self.assertEqual(account['strategy'], WW)
        self.assertEqual(account['status'], 'stopped')
        self.assertEqual(account['fills'], [])
        self.assertEqual(account['orders'], [])
        self.assertIsNone(self.services['D0'].ledger.snapshot()['account'])
        identity = account['id']
        for action, expected in [('start', 'running'), ('pause', 'paused')]:
            status, _, result = await self.call(WW, '/api/realtime-paper/accounts/' + identity + '/' + action,
                method='POST', body={'idempotency_key': 'independent-' + action + '-key'})
            self.assertEqual(status, 200)
            self.assertEqual(result.get('strategy'), WW)
            self.assertEqual(result['accounts'][0]['status'], expected)
        status, _, result = await self.call(WW, '/api/realtime-paper/accounts/' + identity + '/capital',
            method='POST', body={'initial_cash': '120000.00', 'idempotency_key': 'independent-capital-key'})
        self.assertEqual(status, 200)
        self.assertEqual(result.get('strategy'), WW)
        self.assertEqual(result['accounts'][0]['initial_cash'], '120000.00')
        self.assertIsNone(self.services['D0'].ledger.snapshot()['account'])

    async def test_same_command_key_and_cross_ids_cannot_mutate_other_ledger(self):
        old = (await self.create('D0', '50000.00'))[2]
        new = (await self.create(WW, '150000.00'))[2]
        old_id, new_id = old['accounts'][0]['id'], new['accounts'][0]['id']
        self.assertNotEqual(old_id, new_id)
        before = {code: service.ledger.snapshot() for code, service in self.services.items()}
        for selected, wrong_id in [('D0', new_id), (WW, old_id)]:
            status, _, _ = await self.call(selected, '/api/realtime-paper/accounts/' + wrong_id + '/start',
                method='POST', body={'idempotency_key': 'wrong-id-start-key'})
            self.assertEqual(status, 404)
        for code, service in self.services.items():
            self.assertEqual(service.ledger.snapshot(), before[code])
        self.assertEqual((await self.call('D0'))[2]['accounts'][0]['initial_cash'], '50000.00')
        self.assertEqual((await self.call(WW))[2]['accounts'][0]['initial_cash'], '150000.00')


if __name__ == '__main__':
    unittest.main()
