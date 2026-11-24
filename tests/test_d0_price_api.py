"""Price-chart API boundaries on synthetic ledgers and quote databases only."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_engine import PaperLedger
from realtime_paper_intraday_charts import IntradayChartReader
from realtime_paper_rationale import SYMBOLS
from realtime_paper_service import PaperService, ReadOnlyPaperSource
from server import PaperHttpAdapter

CN = timezone(timedelta(hours=8))


def saved_price_source(home, now):
    days = ['2026-10-21', '2026-10-22', '2026-10-23']
    prices = [10, 10, 9.5]
    signal = dict(id='synthetic-price-signal', strategy='D0', day=days[-1],
        confirmed_day=days[-1], execution_day='2026-10-26',
        history_hash='synthetic-history', history_cutoff=days[-1],
        market_hash='synthetic-history', spec_hash='synthetic-spec',
        signal_at='2026-10-23T16:10:00+08:00', known_at='2026-10-23T16:10:00+08:00',
        received_at='2026-10-23T16:10:01+08:00', eligible_at='2026-10-26T09:30:00+08:00',
        data_cutoff='2026-10-23T15:00:00+08:00', market_at='2026-10-23T15:00:00+08:00',
        version='D0-forward-v1', source='Synthetic saved signal', valid=True,
        waiting_reason=None, reason='Synthetic price integration fixture',
        weights={symbol: '0' for symbol in SYMBOLS},
        reference_prices={symbol: '9.500' for symbol in SYMBOLS})
    source = ReadOnlyPaperSource(home, now=now)
    source._signal = deepcopy(signal)
    source._signal_key = (days[-1], signal['history_hash'])
    source._market = SimpleNamespace(dates=days, inputs=SimpleNamespace(
        bars={symbol: [dict(date=day, close=price) for day, price in zip(days, prices)]
              for symbol in SYMBOLS}))
    source.read = Mock(side_effect=AssertionError('display must never poll the producer'))
    source._daily_data = Mock(side_effect=AssertionError('display must never load daily data'))
    return signal, source


def recorded_batch(now, *, price=9.5, previous=10):
    at = now - timedelta(seconds=2)
    return dict(received_at=(at + timedelta(seconds=1)).isoformat(), source='synthetic-public',
        quotes={symbol: dict(symbol=symbol, quote_at=at.isoformat(), price=price,
                             previous_close=previous, source='synthetic-public')
                for symbol in SYMBOLS})


class PriceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.home = Path(self.temp.name)
        self.now = datetime(2026, 10, 26, 10, tzinfo=CN)
        self.ledger = PaperLedger(self.home, now=lambda: self.now)
        self.ledger.create('100000.00', name='Synthetic chart account')
        self.signal, self.source = saved_price_source(self.home, lambda: self.now)
        self.ledger.set_signal(self.signal)
        self.service = PaperService(self.home, source=self.source, ledger=self.ledger,
                                    now=lambda: self.now, start_worker=False)

    def tearDown(self):
        self.source.read.assert_not_called()
        self.source._daily_data.assert_not_called()
        self.service.close()
        self.ledger.close()
        self.temp.cleanup()

    def durable(self):
        with closing(sqlite3.connect(self.ledger.path.resolve().as_uri() + '?mode=ro', uri=True)) as con:
            return con.execute('SELECT data FROM ledger WHERE id=1').fetchone()[0]

    def seed_recorded_quotes(self):
        path = self.home / '盘中行情.sqlite3'
        batch = recorded_batch(self.now)
        with closing(sqlite3.connect(path)) as con:
            con.execute('CREATE TABLE snapshots(id TEXT PRIMARY KEY, received_at TEXT, payload TEXT)')
            con.execute('CREATE TABLE attempts(id TEXT PRIMARY KEY, attempted_at TEXT, status TEXT)')
            con.execute('INSERT INTO snapshots VALUES(?,?,?)',
                ('synthetic-batch', batch['received_at'], json.dumps(batch)))
            con.execute('INSERT INTO attempts VALUES(?,?,?)',
                ('synthetic-attempt', batch['received_at'], '成功'))
            con.commit()
        return path

    def test_source_daily_projection_is_cache_only_and_does_not_mutate_input(self):
        before = deepcopy(self.signal)
        cached = deepcopy(self.source._market.inputs.bars)
        with patch('builtins.open', side_effect=AssertionError('no file IO')), \
             patch('sqlite3.connect', side_effect=AssertionError('no database IO')):
            histories = self.source.daily_price_history(self.signal)
        self.assertEqual(self.signal, before)
        self.assertEqual(self.source._market.inputs.bars, cached)
        self.assertEqual(set(histories), set(SYMBOLS))
        for history in histories.values():
            self.assertEqual(history['status'], 'available')
            self.assertAlmostEqual(history['points'][-1]['change_ratio'], -.05)

    def test_service_constructor_does_not_read_the_intraday_database(self):
        with patch.object(IntradayChartReader, '_read', side_effect=AssertionError('constructor IO')) as read, \
             patch('sqlite3.connect', side_effect=AssertionError('constructor database IO')), \
             patch.object(Path, 'stat', side_effect=AssertionError('constructor file IO')):
            service = PaperService(self.home, source=self.source, ledger=self.ledger,
                                   now=lambda: self.now, start_worker=False)
            self.assertIsInstance(service.intraday_charts, IntradayChartReader)
            read.assert_not_called()
            service.close()

    def test_get_reuses_service_reader_across_adapters_outside_the_service_lock(self):
        quote_path = self.seed_recorded_quotes()
        before, quote_before = self.durable(), quote_path.read_bytes()
        reader = self.service.intraday_charts
        reader._clock = lambda: 0.0
        original_read = reader._read
        lock_checks = []

        def checked_read(now):
            # A second thread must be able to take this lock during chart IO.
            import threading
            def acquire():
                free = self.service._lock.acquire(blocking=False)
                lock_checks.append(free)
                if free:
                    self.service._lock.release()
            probe = threading.Thread(target=acquire)
            probe.start(); probe.join(timeout=2)
            self.assertFalse(probe.is_alive())
            self.assertTrue(lock_checks[-1])
            return original_read(now)

        with patch.object(reader, '_read', side_effect=checked_read) as read:
            first = PaperHttpAdapter(self.service).snapshot()
            second = PaperHttpAdapter(self.service).snapshot()
            self.assertEqual(read.call_count, 1)
        self.assertIs(self.service.intraday_charts, reader)
        self.assertEqual(lock_checks, [True])
        self.assertEqual(first['price_histories'], second['price_histories'])
        self.assertEqual(first['price_histories']['contract_version'], 'd0-price-history-v1')
        assets = first['price_histories']['assets']
        self.assertEqual([row['symbol'] for row in assets], list(SYMBOLS))
        for row in assets:
            self.assertEqual(row['intraday']['status'], 'available')
            self.assertEqual(row['intraday']['coverage'], 'recorded_samples_only')
            self.assertAlmostEqual(row['intraday']['points'][-1]['change_ratio'], -.05)
            self.assertEqual(row['daily']['status'], 'available')
            self.assertAlmostEqual(row['daily']['points'][-1]['change_ratio'], -.05)
        self.assertEqual(self.durable(), before)
        self.assertEqual(quote_path.read_bytes(), quote_before)
        json.dumps(first, allow_nan=False)

    def test_service_snapshot_projects_daily_prices_without_reading_intraday_or_writing_ledger(self):
        before = self.durable()
        with patch.object(self.service.intraday_charts, 'snapshot', side_effect=AssertionError('no chart IO under snapshot lock')) as reader:
            raw = self.service.snapshot()
            reader.assert_not_called()
        self.assertTrue(all(h['status'] == 'available' for h in raw['daily_price_histories'].values()))
        raw['daily_price_histories'][SYMBOLS[0]]['points'][-1]['close'] = 999
        self.assertEqual(self.service.snapshot()['daily_price_histories'][SYMBOLS[0]]['points'][-1]['close'], 9.5)
        self.assertEqual(self.durable(), before)

    def test_commands_and_idempotent_replays_do_not_read_charts(self):
        account_id = self.ledger.snapshot()['account']['id']
        reader = Mock(side_effect=AssertionError('commands must not read charts'))
        self.service.intraday_charts.snapshot = reader
        first = PaperHttpAdapter(self.service).configure_capital(account_id, '110000.00', 'synthetic-price-capital')
        after = self.durable()
        self.now += timedelta(minutes=5)
        self.source.daily_price_history = Mock(side_effect=RuntimeError('optional cache failed later'))
        replay = PaperHttpAdapter(self.service).configure_capital(account_id, '110000.00', 'synthetic-price-capital')
        self.assertEqual(first, replay)
        self.assertEqual(first['price_histories'], {'contract_version': 'd0-price-history-v1', 'assets': []})
        self.assertEqual(first['market_quotes'], [])
        self.assertEqual(self.durable(), after)
        reader.assert_not_called()

    def test_chart_failures_preserve_account_orders_and_fills(self):
        before = self.durable()
        raw = self.ledger.snapshot()
        baseline = PaperHttpAdapter(self.service).snapshot()
        self.source.daily_price_history = Mock(side_effect=RuntimeError('synthetic daily failure'))
        self.service.intraday_charts.snapshot = Mock(side_effect=RuntimeError('synthetic intraday failure'))
        output = PaperHttpAdapter(self.service).snapshot()
        self.assertEqual(output['accounts'], baseline['accounts'])
        self.assertEqual(output['accounts'][0]['id'], raw['account']['id'])
        self.assertEqual(output['accounts'][0]['cash'], raw['account']['cash'])
        self.assertEqual(output['accounts'][0]['orders'], [])
        self.assertEqual(output['accounts'][0]['fills'], [])
        for row in output['price_histories']['assets']:
            self.assertEqual(row['intraday']['status'], 'unavailable')
            self.assertEqual(row['intraday']['points'], [])
            self.assertEqual(row['daily']['status'], 'invalid')
            self.assertEqual(row['daily']['points'], [])
        self.assertEqual(self.durable(), before)

    def test_observed_market_changes_keep_negative_zero_and_positive_ratios(self):
        adapter = PaperHttpAdapter(self.service)
        for price, expected in [(9.5, -.05), (10, 0), (10.5, .05)]:
            batch = recorded_batch(self.now, price=price)
            before = deepcopy(batch)
            rows = adapter.market_quotes(batch, self.now)
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row['display_only'] and row['fresh'] for row in rows))
            for row in rows:
                self.assertEqual(row['previous_close'], '10')
                self.assertAlmostEqual(row['change_ratio'], expected)
            self.assertEqual(batch, before)

    def test_missing_or_invalid_previous_close_never_fabricates_change(self):
        adapter = PaperHttpAdapter(self.service)
        for previous in (None, True, False, 0, -1, 'NaN', float('inf'), '1e1000', {}, []):
            with self.subTest(previous=previous):
                rows = adapter.market_quotes(recorded_batch(self.now, previous=previous), self.now)
                self.assertEqual(len(rows), 4)
                self.assertTrue(all(row['price'] == '9.5' and row['previous_close'] is None
                                    and row['change_ratio'] is None for row in rows))
                json.dumps(rows, allow_nan=False)
        for price in (None, True, False, 0, -1, 'NaN', float('inf'), {}, []):
            with self.subTest(price=price):
                self.assertEqual(adapter.market_quotes(recorded_batch(self.now, price=price), self.now), [])

    def test_missing_observation_never_substitutes_accepted_quotes(self):
        raw = self.ledger.snapshot()
        stamp = (self.now - timedelta(seconds=2)).isoformat()
        raw['quotes'] = {SYMBOLS[0]: dict(id='synthetic-accepted', price='9.5', previous_close='10',
            status='unverified', quote_at=stamp, received_at=stamp, source='synthetic-accepted',
            volume_lots=1000, amount_cny=950000)}
        self.service.intraday_charts.snapshot = Mock(return_value={})
        adapter = PaperHttpAdapter(self.service)
        for missing in (None, {}, {'quotes': None}):
            raw['market_observation'] = missing
            output = adapter.view(raw)
            self.assertEqual(len(output['quotes']), 1)
            self.assertEqual(output['market_quotes'], [])
            self.assertTrue(all(row['intraday']['points'] == [] for row in output['price_histories']['assets']))
        raw['market_observation'] = recorded_batch(self.now, price=8)
        output = adapter.view(raw)
        self.assertEqual(output['quotes'][0]['price'], '9.5')
        self.assertEqual(output['market_quotes'][0]['price'], '8')
        self.assertAlmostEqual(output['market_quotes'][0]['change_ratio'], -.2)


if __name__ == '__main__':
    unittest.main()
