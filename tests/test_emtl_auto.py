from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_emtl_d0 import NOW, inputs
from test_emtl_live import Broker, arm
from emtl_auto import AUTO_CONFIRMATION
from emtl_live import AUTO_ARM_CONFIRMATION, FIELD_CONFIRMATION, BrokerDesk, LiveError


class Account(Broker):
    def __init__(self):
        super().__init__()
        self.cash = '1900'
        self.holdings = {'512800': 100}
        self.equity = '2000'

    def query_asset_and_position(self):
        return {'Status': 0, 'Data': [{'Kyzj': self.cash, 'VERIFIED_FIXTURE_EQUITY': self.equity, 'positions': [
            {'Zqdm': code, 'Zqsl': str(held), 'Kysl': str(held)} for code, held in self.holdings.items()]}]}


class AutoTests(unittest.TestCase):
    owner = 'browser-one'
    account = '0012345678'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'desk.sqlite3'
        self.broker = None
        self.allowed = self.website = True
        self.d0, _ = inputs()
        self.d0['signal']['weights'] = {'sz159915': '0.16'}
        self.f0 = deepcopy(self.d0)
        self.f0.update(contract_version='f0-order-preview-input-v1', strategy='F0')
        self.f0['signal'].update(strategy='F0', id='f' * 64)
        self.sources = {'D0': self.d0, 'F0': self.f0}
        self.create()

    def create(self, auto_cap=True):
        def new(**_):
            self.broker = Account()
            return self.broker
        self.desk = BrokerDesk(self.path, self.account, Decimal(5000), Decimal(5000), new, orders_cap=True,
                               auto_cap=auto_cap, equity_field='VERIFIED_FIXTURE_EQUITY', now=lambda: NOW)
        self.addCleanup(self.desk.close)
        self.desk.connect(self.owner, self.account, 'test', valid_session=lambda: self.website)
        if auto_cap:
            self.verify_fields()
            self.arm_auto()

    def verify_fields(self):
        self.fill('512800', '209', 100)
        data = self.desk.diagnose(self.owner, '209', lambda: self.allowed)
        self.broker.orders.clear()
        return self.desk.verify_diagnostics(self.owner, {
            'token': data['verification_token'], 'field': 'VERIFIED_FIXTURE_EQUITY', 'total_cny': '2000.00',
            'filled_shares': '100', 'confirmation': FIELD_CONFIRMATION,
        }, lambda: self.allowed)

    def arm_auto(self):
        self.desk.next_login = 0
        return self.desk.arm_auto(self.owner, {'username': self.account, 'password': 'test',
                                               'confirmation': AUTO_ARM_CONFIRMATION}, lambda: self.allowed)

    def preview(self, strategy='D0'):
        return self.desk.auto.preview(self.owner, strategy, self.sources.__getitem__)

    def start(self, strategy='D0'):
        p = self.preview(strategy)
        self.desk.auto.start(self.owner, {'token': p['token'], 'confirmation': AUTO_CONFIRMATION},
                             self.sources.__getitem__, lambda: self.allowed)
        return p

    def tick(self):
        self.desk.auto.next_tick = 0
        self.desk.tick()

    def fill(self, code, receipt, quantity, state='已成'):
        self.broker.orders.append({'Wtrq': '20261124', 'Wtbh': receipt, 'Zqdm': code,
                                   'Wtzt': state, 'Wtsl': str(quantity), 'Cjsl': str(quantity) if state == '已成' else '0'})

    def test_f0_sells_waits_for_verified_fill_then_buys_and_never_repeats_day(self):
        plan = self.start('F0')
        self.assertEqual([o['side'] for o in plan['orders']], ['sell', 'buy'])
        self.assertFalse(self.broker.sent)
        with self.assertRaisesRegex(LiveError, '手动或自动模式'):
            self.desk.draft_order(self.owner, {'symbol': 'sz159915', 'side': 'buy', 'price': '1.001', 'quantity': 100},
                                  lambda: self.d0)
        self.tick()
        self.assertEqual([o[:2] for o in self.broker.sent], [('512800', 'S')])
        self.fill('512800', '123', 100, '已报')
        self.tick()
        self.assertEqual(len(self.broker.sent), 1)
        self.broker.orders[0].update(Wtzt='已成', Cjsl='100')
        self.broker.cash, self.broker.holdings = '1998', {}
        self.broker.response['Data'][0]['Wtbh'] = '124'
        self.tick()
        self.assertEqual([o[:2] for o in self.broker.sent], [('512800', 'S'), ('159915', 'B')])
        self.fill('159915', '124', 300)
        self.broker.cash, self.broker.holdings = '1690', {'159915': 300}
        self.tick()
        self.assertFalse(self.desk.auto.active)
        self.assertIn('本轮目标已达到', self.desk.auto.note)
        self.desk.close()
        self.create()
        with self.assertRaisesRegex(LiveError, '今日已启动'):
            self.start('D0')
        self.assertFalse(self.broker.sent)

    def test_revocation_and_broker_errors_fail_closed_without_retries(self):
        self.start()
        self.allowed = False
        self.tick()
        self.assertFalse(self.broker.sent)
        self.assertFalse(self.desk.auto.active)
        self.allowed = True
        self.arm_auto()
        self.start()
        self.broker.response = RuntimeError('BROKER_ERROR_NOT_FOR_BROWSER')
        self.tick()
        self.tick()
        self.assertEqual(len(self.broker.sent), 1)
        self.assertFalse(self.desk.auto.active)
        self.assertIn('结果不明', self.desk.auto.note)

    def test_second_device_sees_execution_and_cannot_take_over_running_cycle(self):
        self.start('F0')
        state = self.desk.monitor('browser-two', lambda: True)
        self.assertFalse(state['connected'])
        self.assertEqual(state['monitor_auto']['strategy'], 'F0')
        self.assertEqual(state['monitor_auto']['phase'], 'executing')
        with self.assertRaisesRegex(LiveError, '仍在运行'):
            self.desk.take_over('browser-two', {'username': self.account, 'password': 'test',
                                                 'confirmation': '确认接管只读连接'},
                                valid_session=lambda: True, access=lambda: True)
        self.assertFalse(self.broker.sent)
        self.tick()
        self.assertEqual(self.desk.monitor('browser-two', lambda: True)['monitor_auto']['phase'], 'reconciling')
        self.assertEqual(len(self.broker.sent), 1)

    def test_stopping_is_owner_only_and_blocks_the_first_send(self):
        self.start()
        self.desk.request_auto_stop('another-browser')
        self.assertFalse(self.desk.auto.stop_requested.is_set())
        self.desk.request_auto_stop(self.owner)
        self.tick()
        self.assertFalse(self.desk.auto.active)
        self.assertFalse(self.broker.sent)

    def test_automatic_deadline_independent_of_connection(self):
        self.start()
        self.desk.auto.deadline = 0
        self.tick()
        self.assertFalse(self.desk.auto.active)
        self.assertTrue(self.desk.status(self.owner)['connected'])
        self.assertFalse(self.broker.sent)

    def test_partial_or_unverified_fill_stops_and_never_buys(self):
        self.start()
        self.tick()
        self.fill('512800', '123', 100, '已报')
        self.broker.orders[0]['Cjsl'] = '50'
        self.tick()
        self.assertEqual(len(self.broker.sent), 1)
        self.assertFalse(self.desk.auto.active)
        self.assertIn('未确认整笔成交', self.desk.auto.note)

    def test_read_only_preview_works_but_cannot_arm_without_capability(self):
        self.desk.close()
        self.create(auto_cap=False)
        self.assertFalse(self.preview()['auto_enabled'])
        with self.assertRaisesRegex(LiveError, '尚未开放'):
            self.start()
        self.assertFalse(self.broker.sent)
        with self.assertRaisesRegex(LiveError, '有效执行信号'):
            self.sources['F0'] = self.d0
            self.preview('F0')

    def test_proof_needs_matching_values_and_exact_pairing_lease(self):
        self.desk.auto.stop()
        self.fill('512800', '209', 100)
        access = [True]
        result = self.desk.diagnose(self.owner, '209', lambda: access[0])
        fields = {'token': result['verification_token'], 'field': 'VERIFIED_FIXTURE_EQUITY', 'total_cny': '2000',
                  'filled_shares': '100', 'confirmation': FIELD_CONFIRMATION}
        for change in ({'total_cny': '1900'}, {'filled_shares': '99'}, {'field': 'Kyzj'}, {'confirmation': 'OK'}):
            with self.assertRaisesRegex(LiveError, '不一致'):
                self.desk.verify_diagnostics(self.owner, {**fields, **change}, lambda: True)
        access[0] = False
        with self.assertRaisesRegex(LiveError, '样本已失效'):
            self.desk.verify_diagnostics(self.owner, fields, lambda: True)
        access[0] = True
        self.assertTrue(self.desk.verify_diagnostics(self.owner, fields, lambda: True)['auto']['verified'])
        with self.assertRaisesRegex(LiveError, '样本已失效'):
            self.desk.verify_diagnostics(self.owner, fields, lambda: True)
        self.desk.close()
        self.create(auto_cap=False)
        state = self.desk.status(self.owner)['auto']
        self.assertTrue(state['verified'])
        self.assertFalse(state['armed'])

    def test_manual_authorization_does_not_authorize_auto_and_auto_does_not_enable_manual(self):
        self.assertTrue(self.desk.status(self.owner)['auto']['armed'])
        self.assertFalse(self.desk.status(self.owner)['orders_armed'])
        self.desk.auto.stop()
        arm(self.desk, self.owner, self.account, 'test')
        self.assertFalse(self.preview()['auto_enabled'])
        with self.assertRaisesRegex(LiveError, '授权对应的手动或自动模式'):
            self.start()
        self.assertTrue(self.arm_auto()['auto']['armed'])
        self.assertFalse(self.desk.status(self.owner)['orders_armed'])
        self.assertFalse(self.desk.auto.active)
        self.assertFalse(self.broker.sent)

    def test_no_site_timer_does_not_bypass_website_revocation(self):
        with patch('emtl_live.time.monotonic', return_value=2**40):
            self.assertTrue(self.desk.status(self.owner)['connected'])
            self.website = False
            self.assertFalse(self.desk.status(self.owner)['connected'])
            self.assertTrue(self.broker.closed)
