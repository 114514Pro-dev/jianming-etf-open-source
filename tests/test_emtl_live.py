from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from test_emtl_d0 import inputs, NOW
from emtl_live import BrokerDesk, CONFIRMATION, LiveError


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
        self.broker = Broker()
        self.desk = BrokerDesk(self.path, '000001234', Decimal('1000'), Decimal('8000'), lambda **_: self.broker, now=lambda: self.now)
        self.addCleanup(self.desk.close)
        info = self.desk.connect('browser-one', '000001234', 'SYNTHETIC_PASSWORD')
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

    def test_disconnect_discards_client_and_draft(self):
        draft = self.draft()
        self.assertFalse(self.desk.disconnect('other')['connected'])
        self.assertTrue(self.desk.status('browser-one')['connected'])
        self.desk.disconnect('browser-one')
        self.assertTrue(self.broker.closed)
        with self.assertRaises(LiveError):
            self.submit(draft)