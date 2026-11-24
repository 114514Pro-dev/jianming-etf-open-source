"""Synthetic actual-index quote packets; these tests never access the network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
import realtime_paper_comparison_indices as indices


NOW = datetime(2026, 10, 28, 10, 1, tzinfo=timezone(timedelta(hours=8)))


def packet(symbol='sh000001', stamp='20261028100059'):
    fields = [''] * 88
    fields[1] = '供应方名称不作为身份依据'
    fields[2] = symbol[2:]
    fields[3:6] = ['3050.125', '3030.5', '3040.25']
    fields[30] = stamp
    fields[33:35] = ['3060', '3020']
    fields[61] = 'ZS'
    return {'code': 0, 'data': {symbol: {'day': [], 'qt': {symbol: fields}}}}


def fields(payload, symbol='sh000001'):
    return payload['data'][symbol]['qt'][symbol]


class IndexQuoteTests(unittest.TestCase):
    def test_both_actual_indices_have_source_identity_and_unscaled_values(self):
        for symbol in indices.INDEX_NAMES:
            result = indices.parse_index_quote(packet(symbol), symbol, received_at=NOW)
            self.assertEqual(result['symbol'], symbol)
            self.assertEqual(result['name'], indices.INDEX_NAMES[symbol])
            self.assertEqual(result['instrument_type'], 'ZS')
            self.assertEqual(result['price'], 3050.125)
            self.assertEqual(result['previous_close'], 3030.5)
            self.assertEqual(result['open'], 3040.25)
            self.assertEqual(result['quote_at'], '2026-10-28T10:00:59+08:00')
            self.assertEqual(result['received_at'], NOW.isoformat())
            self.assertEqual(result['source'], '腾讯实际指数报价')

    def test_only_the_two_index_symbols_are_allowed_before_any_request(self):
        request = Mock(side_effect=AssertionError('must not fetch'))
        for symbol in ('sh510050', 'sz159915', 'sh399006', 'sz000001', None, True, ['sh000001']):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                indices.fetch_index_quote(symbol, now=NOW, request=request)
        request.assert_not_called()

    def test_wrong_response_code_missing_namespace_and_wrong_instrument_code_fail(self):
        for code in (False, '0', 1, None):
            payload = packet(); payload['code'] = code
            with self.subTest(code=code), self.assertRaises(ValueError):
                indices.parse_index_quote(payload, 'sh000001', received_at=NOW)
        for change in (lambda p: p['data'].pop('sh000001'),
                       lambda p: p['data']['sh000001']['qt'].pop('sh000001'),
                       lambda p: fields(p).__setitem__(2, '510050'),
                       lambda p: fields(p).__setitem__(2, 1)):
            payload = packet(); change(payload)
            with self.assertRaises(ValueError):
                indices.parse_index_quote(payload, 'sh000001', received_at=NOW)

    def test_etf_packets_cannot_be_relabelled_as_an_index(self):
        for tag in ('JJ', 'GP-A', 'zs', '', None, ['ZS']):
            payload = packet(); fields(payload)[61] = tag
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                indices.parse_index_quote(payload, 'sh000001', received_at=NOW)

    def test_zs_in_names_or_other_slots_cannot_substitute_for_the_security_type(self):
        for symbol in indices.INDEX_NAMES:
            for position in (0, 1, 49, 60, 62, 87):
                payload = packet(symbol)
                quote = fields(payload, symbol)
                quote[61] = 'GP-A'
                quote[position] = 'ZS'
                with self.subTest(symbol=symbol, position=position), self.assertRaises(ValueError):
                    indices.parse_index_quote(payload, symbol, received_at=NOW)
        # Original bypass: a non-index type in the assumed slot and ZS as name.
        payload = packet(); fields(payload)[61] = ''; fields(payload)[49] = 'GP-A'
        fields(payload)[1] = 'ZS'
        with self.assertRaises(ValueError):
            indices.parse_index_quote(payload, 'sh000001', received_at=NOW)

    def test_actual_day_array_and_bounded_quote_array_are_required(self):
        for day in (None, {}, 'day'):
            payload = packet(); payload['data']['sh000001']['day'] = day
            with self.subTest(day=day), self.assertRaises(ValueError):
                indices.parse_index_quote(payload, 'sh000001', received_at=NOW)
        for array in ([], ['ZS'] * 34, fields(packet())[:61], ['ZS'] * 513, {}, None):
            payload = packet(); payload['data']['sh000001']['qt']['sh000001'] = array
            with self.assertRaises(ValueError):
                indices.parse_index_quote(payload, 'sh000001', received_at=NOW)

    def test_nonfinite_nonpositive_and_boolean_prices_are_rejected(self):
        for index in (3, 4, 5, 33, 34):
            for value in ('NaN', 'Infinity', '-Infinity', float('inf'), float('nan'),
                          0, -1, True, None, '', '1e101', '1' * 65, '1e-1000'):
                payload = packet(); fields(payload)[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                    indices.parse_index_quote(payload, 'sh000001', received_at=NOW)

    def test_high_low_must_enclose_open_and_current_price(self):
        for high, low in (('3045', '3020'), ('3060', '3045'), ('3000', '3100')):
            payload = packet(); fields(payload)[33:35] = [high, low]
            with self.assertRaises(ValueError):
                indices.parse_index_quote(payload, 'sh000001', received_at=NOW)

    def test_illegal_source_stamps_and_quotes_more_than_five_seconds_ahead_fail(self):
        for stamp in ('20260230100000', '20261028100106', '202610281000',
                      '2026-10-28T10:00:59', 20261028100059, None, ' 20261028100059'):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                indices.parse_index_quote(packet(stamp=stamp), 'sh000001', received_at=NOW)
        allowed = indices.parse_index_quote(packet(stamp='20261028100105'), 'sh000001', received_at=NOW)
        self.assertEqual(allowed['quote_at'], '2026-10-28T10:01:05+08:00')

    def test_old_quotes_keep_their_real_source_timestamp(self):
        result = indices.parse_index_quote(packet(stamp='20261023150000'), 'sh000001', received_at=NOW)
        self.assertEqual(result['quote_at'], '2026-10-23T15:00:00+08:00')
        self.assertEqual(result['received_at'], NOW.isoformat())
        self.assertNotEqual(result['quote_at'], result['received_at'])

    def test_receipt_time_requires_a_timezone_and_keeps_the_same_instant(self):
        for value in (None, '2026-10-28', datetime(2026, 10, 28, 10, 1), 'bad', 0, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                indices.parse_index_quote(packet(), 'sh000001', received_at=value)
        result = indices.parse_index_quote(packet(), 'sh000001', received_at='2026-10-28T02:01:00+00:00')
        self.assertEqual(result['received_at'], NOW.isoformat())

    def test_parse_is_pure_and_performs_no_io(self):
        payload = packet(); before = deepcopy(payload)
        with (patch('builtins.open', side_effect=AssertionError('no files')),
              patch.object(indices, '_request', side_effect=AssertionError('no network'))):
            result = indices.parse_index_quote(payload, 'sh000001', received_at=NOW)
        result['price'] = 1
        self.assertEqual(payload, before)

    def test_fetch_uses_existing_https_path_with_only_the_selected_index(self):
        captured = []
        def request(url):
            captured.append(url)
            return json.dumps(packet(), ensure_ascii=False).encode()
        result = indices.fetch_index_quote('sh000001', now=NOW, request=request)
        self.assertEqual(result['price'], 3050.125)
        self.assertEqual(len(captured), 1)
        parsed = urlparse(captured[0]); query = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, 'https')
        self.assertEqual(parsed.netloc, 'proxy.finance.qq.com')
        self.assertEqual(parsed.path, '/ifzqgtimg/appstock/app/newfqkline/get')
        self.assertEqual(query['param'], ['sh000001,day,,,1,'])

    def test_fetch_accepts_the_provider_assignment_wrapper_and_utf8_bom(self):
        body = json.dumps(packet(), ensure_ascii=False).encode()
        for raw in (b'\xef\xbb\xbf' + body, b'd0_comparison_quote=' + body + b';', b'var d0_comparison_quote = ' + body + b';'):
            with self.subTest(prefix=raw[:20]):
                result = indices.fetch_index_quote('sh000001', now=NOW, request=lambda _url: raw)
                self.assertEqual(result['quote_at'], '2026-10-28T10:00:59+08:00')

    def test_fetch_rejects_duplicate_json_keys_and_nonfinite_json_constants(self):
        body = json.dumps(packet())
        variants = [body.replace('"code": 0', '"code": 0, "code": 0'),
                    body.replace('"3050.125"', 'NaN'), body.replace('"3050.125"', 'Infinity')]
        for value in variants:
            with self.assertRaises(ValueError):
                indices.fetch_index_quote('sh000001', now=NOW, request=lambda _url: value.encode())

    def test_fetch_bounds_response_before_decoding_and_rejects_malformed_types(self):
        for raw in (b'x' * (indices.MAX_RESPONSE_BYTES + 1), b'', 'text', b'\xff', b'<html>bad</html>', b'{'):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                indices.fetch_index_quote('sh000001', now=NOW, request=lambda _url: raw)

    def test_fetch_normalizes_numeric_json_values_without_overflow(self):
        payload = packet(); fields(payload)[3] = 3050.125; fields(payload)[4] = 3030.5
        fields(payload)[5] = 3040.25
        result = indices.fetch_index_quote('sh000001', now=NOW,
                                           request=lambda _url: json.dumps(payload).encode())
        self.assertIsInstance(result['price'], float)
        self.assertEqual(result['open'], 3040.25)

    def test_six_digit_numeric_code_is_checked_without_guessing_leading_zeroes(self):
        payload = packet('sz399006'); fields(payload, 'sz399006')[2] = 399006
        result = indices.parse_index_quote(payload, 'sz399006', received_at=NOW)
        self.assertEqual(result['symbol'], 'sz399006')
        payload = packet(); fields(payload)[2] = 1
        with self.assertRaises(ValueError):
            indices.parse_index_quote(payload, 'sh000001', received_at=NOW)

    def test_default_clock_captures_receipt_after_transport(self):
        class Clock(datetime):
            current = NOW
            @classmethod
            def now(cls, tz=None):
                return cls.fromtimestamp(cls.current.timestamp(), tz)
        def request(_url):
            Clock.current = NOW + timedelta(seconds=20)
            return json.dumps(packet(stamp='20261028100115')).encode()
        with patch.object(indices, 'datetime', Clock):
            result = indices.fetch_index_quote('sh000001', request=request)
        self.assertEqual(result['received_at'], '2026-10-28T10:01:20+08:00')
        self.assertEqual(result['quote_at'], '2026-10-28T10:01:15+08:00')


if __name__ == '__main__':
    unittest.main()
