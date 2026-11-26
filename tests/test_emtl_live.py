from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from test_emtl_d0 import inputs, NOW
from emtl_live import ARM_CONFIRMATION, LIVE_CONFIRMATION, BrokerDesk, CONFIRMATION, LiveError


def arm(desk, owner, username, password):
    desk.enable_live(owner, {'confirmation': LIVE_CONFIRMATION})
    desk.next_login = 0  # No wall-clock sleep in synthetic credential tests.
    return desk.arm_orders(owner, {'username': username, 'password': password, 'confirmation': ARM_CONFIRMATION})


class Broker:
    def __init__(self, **ignored):
        self.sent = []
        self.closed = False
        self.cash = '2000'
        self.orders = []
        self.response = {'Status': 0, 'Data': [{'Wtrq': '20261124', 'Wtbh': '123'}]}

    def login(self, **ignored):
        return 'synthetic-session'

    def query_asset_and_position(self):
        return {'Status': 0, 'Data': [{'Kyzj': self.cash, 'positions': [
            {'Zqdm': '512800', 'Zqsl': '100', 'Kysl': '100'}]}]}

    def query_orders(self):
        return {'Status': 0, 'Data': self.orders}

    def create_order(self, *args):
        self.sent.append(args)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self):
        self.closed = True


class ManualEmtlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'broker.sqlite3'
        self.snapshot, _ = inputs()
        self.now = NOW
        self.create()

    def create(self):
        first, self.broker = Broker(), Broker()
        brokers = iter((first, self.broker))
        self.desk = BrokerDesk(self.path, '000001234', Decimal('1000'), Decimal('8000'), lambda **_: next(brokers),
                               orders_cap=True, now=lambda: self.now)
        self.addCleanup(self.desk.close)
        info = self.desk.connect('browser-one', '000001234', 'SYNTHETIC_PASSWORD')
        self.assertFalse(info['orders_armed'])
        info = arm(self.desk, 'browser-one', '000001234', 'SYNTHETIC_PASSWORD')
        self.assertTrue(first.closed)
        self.assertEqual(info['account_tail'], '1234')
        self.assertNotIn('SYNTHETIC_PASSWORD', str(info))

    def draft(self, **overrides):
        return self.desk.draft_order('browser-one', {
            'symbol': 'sz159915', 'side': 'buy', 'price': '1.001', 'quantity': 100, **overrides}, lambda: self.snapshot)

    def submit(self, draft, owner='browser-one', confirm=CONFIRMATION):
        return self.desk.submit(owner, {'order_token': draft['order_token'], 'confirmation': confirm}, lambda: self.snapshot)

    def test_requires_explicit_confirmation_and_scope_then_sends_once(self):
        draft = self.draft()
        for owner, confirm in (('other', CONFIRMATION), ('browser-one', 'OK')):
            with self.assertRaises(LiveError):
                self.submit(draft, owner, confirm)
        self.assertFalse(self.broker.sent)
        result = self.submit(draft)
        self.assertEqual(result['state'], 'submitted')
        self.assertEqual(self.broker.sent, [('159915', 'B', 'SA', 1.001, 100)])
        with self.assertRaises(LiveError):
            self.submit(draft)
        self.assertEqual(len(self.broker.sent), 1)

    def test_ambiguous_transport_result_persists_and_blocks_followups(self):
        self.broker.response = RuntimeError('must not surface password/token')
        result = self.submit(self.draft())
        self.assertEqual(result['state'], 'unknown')
        self.assertIsNone(result['broker_receipt'])
        self.assertEqual(len(self.broker.sent), 1)
        self.desk.close()
        self.create()  # same intent database, new client/process analogue
        with self.assertRaisesRegex(LiveError, '未核对'):
            self.submit(self.draft())
        self.assertFalse(self.broker.sent)

    def test_requires_fresh_market_cash_and_sellable(self):
        draft = self.draft()
        self.now += timedelta(seconds=6)
        with self.assertRaisesRegex(LiveError, '当前不可委托'):
            self.submit(draft)
        self.now = NOW
        self.broker.cash = '99'
        with self.assertRaisesRegex(LiveError, '可用资金'):
            self.submit(self.draft())
        with self.assertRaisesRegex(LiveError, '可卖份额'):
            self.submit(self.draft(symbol='sh512800', side='sell', quantity=200))
        self.assertFalse(self.broker.sent)

    def test_existing_orders_block_until_matching_terminal(self):
        self.submit(self.draft())
        self.broker.orders = [{'Wtrq': '20261124', 'Wtbh': '123', 'Zqdm': '159915', 'Wtzt': '已报', 'Wtsl': '100'}]
        with self.assertRaisesRegex(LiveError, '终态'):
            self.submit(self.draft(symbol='sh512800', side='sell'))
        self.broker.orders[0]['Wtzt'] = '已成'
        self.broker.response['Data'][0]['Wtbh'] = '124'
        result = self.submit(self.draft(symbol='sh512800', side='sell'))
        self.assertEqual(result['state'], 'submitted')
        self.assertEqual(self.broker.sent[-1], ('512800', 'S', 'HA', 1.001, 100))

    def test_caps_block_large_drafts_and_cumulative_submissions(self):
        self.desk.single_limit = Decimal('100')
        self.desk.daily_limit = Decimal('150')
        with self.assertRaisesRegex(LiveError, '单笔'):
            self.draft(price='1.001')
        self.submit(self.draft(price='1.000'))
        self.broker.orders = [{'Wtrq': '20261124', 'Wtbh': '123', 'Zqdm': '159915', 'Wtzt': '已成', 'Wtsl': '100'}]
        with self.assertRaisesRegex(LiveError, '本日'):
            self.submit(self.draft(price='1.000'))
        self.assertEqual(len(self.broker.sent), 1)

    def test_limits_are_owner_only_bounded_persisted_and_invalidate_draft(self):
        draft = self.draft()
        fields = {'single_cny': '800000', 'daily_cny': '5000000'}
        with self.assertRaises(LiveError):
            self.desk.update_limits('other', fields)
        for invalid in ('0', '5000000.01', 'NaN', '1e3', '800000.001'):
            with self.assertRaises(LiveError):
                self.desk.update_limits('browser-one', {**fields, 'single_cny': invalid})
        self.assertEqual(self.desk.update_limits('browser-one', fields)['single_cny'], '800000')
        with self.assertRaises(LiveError):
            self.submit(draft)
        self.desk.close()
        self.create()
        self.assertEqual(self.desk.status('browser-one')['limits']['daily_cny'], '5000000')
        with self.assertRaisesRegex(RuntimeError, '另一资金账号'):
            BrokerDesk(self.path, '000006789', Decimal('1000'), Decimal('8000'), Broker)

    def test_first_enrollment_checks_broker_then_persists_single_account(self):
        ledger = self.path.with_name('enrollment.sqlite3')
        broker = Broker()
        code = 'E' * 43
        fields = {'username': '0012349876', 'password': 'SYNTHETIC-NOT-STORED',
                  'enrollment_code': code, 'confirmation': '同意绑定'}
        desk = BrokerDesk(ledger, None, Decimal('1000'), Decimal('8000'), lambda **_: broker,
                          enrollment_sha256=sha256(code.encode()).hexdigest(), orders_cap=True, now=lambda: NOW)
        self.addCleanup(desk.close)
        self.assertEqual(desk.status('owner'), {'connected': False, 'account_bound': False})
        with self.assertRaisesRegex(LiveError, '开通码无效'):
            desk.enroll('owner', {**fields, 'enrollment_code': 'X' * 43})
        with self.assertRaisesRegex(LiveError, '未获准'):
            desk.connect('owner', fields['username'], fields['password'])
        broker.cash = 'not-broker-balance'
        with self.assertRaisesRegex(LiveError, '只读核对失败'):
            desk.enroll('owner', fields)
        self.assertFalse(desk.bound)
        self.assertTrue(broker.closed)
        broker = Broker()
        desk.next_login = 0  # Synthetic retry, after the first failed verification.
        self.assertEqual(desk.enroll('owner', fields)['account_tail'], '9876')
        self.assertTrue(desk.bound)
        self.assertFalse(broker.sent)
        broker = Broker()
        arm(desk, 'owner', fields['username'], fields['password'])
        draft = desk.draft_order('owner', {'symbol': 'sz159915', 'side': 'buy', 'price': '1.001', 'quantity': 100},
                                 lambda: self.snapshot)
        result = desk.submit('owner', {'order_token': draft['order_token'], 'confirmation': CONFIRMATION},
                             lambda: self.snapshot)
        self.assertEqual(result['state'], 'submitted')
        self.assertEqual(len(broker.sent), 1)
        desk.close()
        broker = Broker()
        restarted = BrokerDesk(ledger, None, Decimal('1000'), Decimal('8000'), lambda **_: broker)
        self.addCleanup(restarted.close)
        with self.assertRaisesRegex(LiveError, '请先解绑'):
            restarted.enroll('other', {**fields, 'username': '0099999876'})
        with self.assertRaisesRegex(LiveError, '未获准'):
            restarted.connect('other', '0099999876', fields['password'])
        self.assertTrue(restarted.connect('owner', fields['username'], fields['password'])['connected'])
        for secret in (fields['password'], fields['username'], code):
            self.assertNotIn(secret.encode(), ledger.read_bytes())

    def test_unbind_reconciles_then_rebinds_after_restart_without_resetting_limits(self):
        ledger = self.path.with_name('rebind.sqlite3')
        broker = Broker()
        old_code = 'E' * 43
        fields = {'username': '000001234', 'password': 'SYNTHETIC', 'enrollment_code': old_code,
                  'confirmation': '同意绑定'}

        def start():
            desk = BrokerDesk(ledger, None, Decimal('1000'), Decimal('8000'), lambda **_: broker,
                              enrollment_sha256=sha256(old_code.encode()).hexdigest(), orders_cap=True, now=lambda: NOW)
            self.addCleanup(desk.close)
            return desk

        owner = 'browser-one'
        desk = start()
        desk.enroll(owner, fields)
        broker = Broker()
        arm(desk, owner, fields['username'], fields['password'])
        desk.update_limits(owner, {'single_cny': '100', 'daily_cny': '150'})
        confirm = {'confirmation': '确认解绑'}
        with self.assertRaisesRegex(LiveError, '请先登录'):
            desk.unbind('another-browser', confirm)
        with self.assertRaisesRegex(LiveError, '请输入'):
            desk.unbind(owner, {'confirmation': 'OK'})
        order = {'symbol': 'sz159915', 'side': 'buy', 'price': '1.000', 'quantity': 100}
        draft = desk.draft_order(owner, order, lambda: self.snapshot)
        desk.submit(owner, {'order_token': draft['order_token'], 'confirmation': CONFIRMATION}, lambda: self.snapshot)
        broker.orders = [{'Wtrq': '20261124', 'Wtbh': '123', 'Zqdm': '159915', 'Wtzt': '已报', 'Wtsl': '100'}]
        with self.assertRaisesRegex(LiveError, '终态'):
            desk.unbind(owner, confirm)
        self.assertTrue(desk.bound)
        broker.orders[0]['Wtzt'] = '已成'
        broker.orders.extend({'Wtzt': '已成'} for _ in range(99))
        with self.assertRaisesRegex(LiveError, '截断'):
            desk.unbind(owner, confirm)
        del broker.orders[1:]
        broker.orders.append({'Wtzt': '已报'})
        with self.assertRaisesRegex(LiveError, '券商有未结'):
            desk.unbind(owner, confirm)
        broker.orders.pop()
        draft = desk.draft_order(owner, order, lambda: self.snapshot)
        unbound = desk.unbind(owner, confirm)
        self.assertFalse(unbound['account_bound'])
        self.assertTrue(broker.closed)
        with self.assertRaisesRegex(LiveError, '失效'):
            desk.submit(owner, {'order_token': draft['order_token'], 'confirmation': CONFIRMATION}, lambda: self.snapshot)
        desk.close()
        new_code = unbound['rebind_code']
        self.assertNotIn(new_code.encode(), ledger.read_bytes())
        broker = Broker()
        restarted = start()
        self.assertFalse(restarted.bound)
        with self.assertRaisesRegex(LiveError, '未获准'):
            restarted.connect(owner, fields['username'], fields['password'])
        with self.assertRaisesRegex(LiveError, '开通码无效'):
            restarted.enroll(owner, fields)
        rebound = restarted.enroll(owner, {**fields, 'username': '000008765', 'enrollment_code': new_code})
        self.assertEqual(rebound['account_tail'], '8765')
        self.assertEqual(rebound['limits']['daily_cny'], '150')
        with self.assertRaisesRegex(LiveError, '请先解绑'):
            restarted.enroll(owner, {**fields, 'enrollment_code': new_code})
        broker = Broker()
        arm(restarted, owner, '000008765', fields['password'])
        draft = restarted.draft_order(owner, order, lambda: self.snapshot)
        with self.assertRaisesRegex(LiveError, '本日'):
            restarted.submit(owner, {'order_token': draft['order_token'], 'confirmation': CONFIRMATION}, lambda: self.snapshot)
        self.assertFalse(broker.sent)

    def test_web_controls_require_owner_two_confirmations_and_fresh_verification(self):
        owner, username = 'browser-one', '000001234'
        draft = self.draft()
        self.assertFalse(self.desk.stop_live(owner)['orders_armed'])
        with self.assertRaisesRegex(LiveError, '授权'):
            self.submit(draft)
        with self.assertRaisesRegex(LiveError, '授权'):
            self.draft()
        fields = {'username': username, 'password': 'FRESH_PASSWORD', 'confirmation': ARM_CONFIRMATION}
        with self.assertRaises(LiveError):
            self.desk.arm_orders(owner, fields)
        with self.assertRaises(LiveError):
            self.desk.enable_live('someone-else', {'confirmation': LIVE_CONFIRMATION})
        self.assertTrue(self.desk.enable_live(owner, {'confirmation': LIVE_CONFIRMATION})['live_active'])
        self.assertFalse(self.desk.status(owner)['orders_armed'])
        with self.assertRaisesRegex(LiveError, '绑定'):
            self.desk.arm_orders(owner, {**fields, 'username': '000009876'})
        self.desk.next_login = 0
        self.desk.factory = lambda **_: (_ for _ in ()).throw(RuntimeError('SENSITIVE_BROKER_ERROR'))
        with self.assertRaisesRegex(LiveError, '券商登录或只读核对失败'):
            self.desk.arm_orders(owner, fields)
        self.assertFalse(self.desk.status(owner)['connected'])
        self.assertFalse(self.broker.sent)

    def test_unbind_refuses_environment_pinned_account(self):
        self.assertFalse(self.desk.status('browser-one')['can_unbind'])
        with self.assertRaisesRegex(LiveError, '固定配置'):
            self.desk.unbind('browser-one', {'confirmation': '确认解绑'})
        self.assertTrue(self.desk.bound)

    def test_disconnect_discards_client_and_draft(self):
        draft = self.draft()
        self.assertFalse(self.desk.disconnect('other')['connected'])
        self.assertTrue(self.desk.status('browser-one')['connected'])
        self.desk.disconnect('browser-one')
        self.assertTrue(self.broker.closed)
        with self.assertRaises(LiveError):
            self.submit(draft)