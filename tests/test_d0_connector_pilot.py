from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop' / 'd0_connector'))
from pilot import CheckError, check_account


class Broker:
    def __init__(self, *, fail=None):
        self.fail = fail
        self.calls = []

    def login(self, duration):
        self.calls.append(('login', duration))
        return '' if self.fail == 'login' else 'TEST_TOKEN_DO_NOT_DISPLAY'

    def query_asset_and_position(self):
        self.calls.append('assets')
        if self.fail == 'assets':
            return {'Status': 0, 'Data': [{'positionList': [], 'unknown': 'TEST_SECRET_DO_NOT_DISPLAY'}]}
        return {'Status': 0, 'Data': [{'Kyzj': '123.45', 'positions': [
            {'Zqdm': '159915', 'Zqsl': '100', 'Kysl': '100'}]}]}

    def query_orders(self):
        self.calls.append('orders')
        if self.fail == 'orders':
            raise RuntimeError('TEST_SECRET_DO_NOT_DISPLAY')
        return {'Status': 0, 'Data': []}

    def close(self):
        self.calls.append('close')


class PilotTests(unittest.TestCase):
    def test_only_login_read_and_close(self):
        broker = Broker()
        result = check_account('0000001234', 'TEST_PASSWORD_DO_NOT_DISPLAY', lambda **kw: broker)
        self.assertEqual(broker.calls, [('login', 5), 'assets', 'orders', 'close'])
        self.assertEqual((result.account_tail, result.available_cash, result.position_count), ('1234', Decimal('123.45'), 1))
        self.assertNotIn('TEST_', repr(result))

    def test_each_failure_ends_session_without_leaking(self):
        for phase, message in [('login', '登录未成功'), ('assets', '资金／持仓'), ('orders', '当日委托')]:
            with self.subTest(phase=phase):
                broker = Broker(fail=phase)
                with self.assertRaisesRegex(CheckError, message) as error:
                    check_account('0000001234', 'TEST_PASSWORD_DO_NOT_DISPLAY', lambda **kw: broker)
                self.assertNotIn('TEST_', str(error.exception))
                self.assertEqual(broker.calls[-1], 'close')

    def test_bad_input_never_calls_broker(self):
        def fail(**kwargs):
            self.fail('Broker must not be created')
        with self.assertRaises(CheckError):
            check_account('not an account', 'pw', fail)
