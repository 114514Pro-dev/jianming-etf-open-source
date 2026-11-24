"""Synthetic public quote databases only; no producer, ledger or network use."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
import realtime_paper_intraday_charts as charts


@contextmanager
def database(path):
    con = sqlite3.connect(path)
    try:
        with con:
            yield con
    finally:
        con.close()


def moment(value='2026-10-23T16:30:00+08:00'):
    return datetime.fromisoformat(value)


class IntradayChartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = self.home / '盘中行情.sqlite3'
        self._schema(self.path)
        self.counter = 0
        self.clock = 100.
        self.reader = charts.IntradayChartReader(self.home, clock=lambda: self.clock)

    @staticmethod
    def _schema(path):
        with database(path) as con:
            con.execute('CREATE TABLE snapshots(id TEXT PRIMARY KEY,received_at TEXT,payload TEXT)')
            con.execute('CREATE TABLE attempts(id TEXT PRIMARY KEY,attempted_at TEXT,status TEXT,note TEXT)')

    def _insert(self, at, price=2., previous=2.1, received=None, overrides=None, padding='', path=None):
        received = received or at
        quotes = {symbol: dict(symbol=symbol, quote_at=at, day=at[:10], price=price, previous_close=previous)
                  for symbol in charts.SYMBOLS}
        if overrides:
            quotes[charts.SYMBOLS[0]].update(overrides)
        batch = dict(received_at=received, source='synthetic public quote', quotes=quotes, padding=padding)
        self._raw(json.dumps(batch, ensure_ascii=False), received, path)
        return batch

    def _raw(self, payload, received='2026-10-23T10:00:00+08:00', path=None):
        self.counter += 1
        with database(path or self.path) as con:
            con.execute('INSERT INTO snapshots VALUES (?,?,?)', (f"insert-{self.counter}", received, payload))

    def _attempt(self, at, status='失败'):
        self.counter += 1
        with database(self.path) as con:
            con.execute('INSERT INTO attempts VALUES (?,?,?,?)', (str(self.counter), at, status, 'synthetic'))

    def _get(self, now=None, refresh=False):
        if refresh:
            self.clock += 31
        return self.reader.snapshot(now or moment())[charts.SYMBOLS[0]]

    def test_constructor_has_no_io_and_missing_database_is_not_created(self):
        absent = self.home / 'absent'
        with patch.object(Path, 'stat', side_effect=AssertionError('constructor IO')), \
                patch.object(charts.sqlite3, 'connect', side_effect=AssertionError('constructor SQL')):
            reader = charts.IntradayChartReader(absent)
        self.assertEqual(reader.snapshot(moment())[charts.SYMBOLS[0]]['reason'], 'quotes_missing')
        self.assertFalse(absent.exists())

    def test_negative_return_actual_source_time_and_readonly_database(self):
        self._insert('2026-10-23T10:00:00+08:00', price=1.8, previous=2.)
        before = self.path.read_bytes()
        history = self._get()
        self.assertEqual(history['status'], 'available')
        self.assertEqual(history['session_day'], '2026-10-23')
        self.assertEqual(history['source'], 'recorded_public_quotes')
        self.assertEqual(history['coverage'], 'recorded_samples_only')
        self.assertAlmostEqual(history['points'][0]['change_ratio'], -.1)
        self.assertEqual(history['points'][0]['at'], '2026-10-23T10:00:00+08:00')
        self.assertEqual(self.path.read_bytes(), before)
        json.dumps(history, allow_nan=False)

    def test_ttl_does_not_read_or_share_mutable_cache_and_incremental_append(self):
        self._insert('2026-10-23T10:00:00+08:00')
        history = self._get()
        history['points'][0]['price'] = 999
        with patch.object(charts.sqlite3, 'connect', side_effect=AssertionError('warm cache IO')):
            self.assertEqual(self._get()['points'][0]['price'], 2.)
        self._insert('2026-10-23T10:00:30+08:00', price=2.01)
        self.assertEqual(len(self._get()['points']), 1)
        updated = self._get(refresh=True)
        self.assertEqual(len(updated['points']), 2)
        self.assertFalse(updated['points'][1]['break_before'])

    def test_nonblocking_lock_does_not_serialize_parallel_account_gets(self):
        self._insert('2026-10-23T10:00:00+08:00')
        started, release = threading.Event(), threading.Event()
        original = self.reader._read
        results = []

        def delayed(now):
            started.set()
            self.assertTrue(release.wait(3))
            return original(now)

        with patch.object(self.reader, '_read', side_effect=delayed):
            worker = threading.Thread(target=lambda: results.append(self.reader.snapshot(moment())))
            worker.start()
            self.assertTrue(started.wait(3))
            try:
                self.assertEqual(self._get()['reason'], 'reader_busy')
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0][charts.SYMBOLS[0]]['status'], 'available')

    def test_refresh_error_is_unavailable_and_recovers_without_false_success(self):
        self._insert('2026-10-23T10:00:00+08:00')
        self._get()
        with patch.object(charts.sqlite3, 'connect', side_effect=sqlite3.OperationalError('synthetic busy')):
            self.assertEqual(self._get(refresh=True)['reason'], 'read_failed')
        self.assertEqual(self._get()['status'], 'unavailable')
        self.assertEqual(self._get(refresh=True)['status'], 'available')

    def test_sqlite_busy_and_wall_budget_fail_safely(self):
        self._insert('2026-10-23T10:00:00+08:00')
        con = sqlite3.connect(self.path)
        try:
            con.execute('BEGIN EXCLUSIVE')
            self.assertEqual(self._get()['reason'], 'read_failed')
        finally:
            con.rollback()
            con.close()
        with patch.object(charts, 'READ_SECONDS', -1):
            self.assertEqual(self._get(refresh=True)['reason'], 'read_failed')
        self.assertEqual(self._get(refresh=True)['status'], 'available')

    def test_mode_ro_query_only_and_progress_handler_are_enabled(self):
        self._insert('2026-10-23T10:00:00+08:00')
        connect = sqlite3.connect
        statements, progress = [], []

        class Observed(sqlite3.Connection):
            def set_progress_handler(self, handler, steps):
                progress.append((handler, steps))
                return super().set_progress_handler(handler, steps)

        def observed(path, **kwargs):
            self.assertTrue(path.endswith('?mode=ro'))
            self.assertTrue(kwargs['uri'])
            connection = connect(path, **kwargs, factory=Observed)
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(charts.sqlite3, 'connect', side_effect=observed):
            self.assertEqual(self._get()['status'], 'available')
        self.assertIn('PRAGMA query_only=ON', statements)
        self.assertTrue(progress and progress[0][1] == 1000)
        self.assertFalse(any('ORDER BY received_at' in statement for statement in statements))
        self.assertFalse(any(statement.startswith(('CREATE', 'INSERT', 'UPDATE', 'DELETE')) for statement in statements))

    def test_json_parsing_does_not_hold_read_transaction_against_quote_producer(self):
        self._insert('2026-10-23T10:00:00+08:00')
        real_loads = json.loads

        def collector_can_commit(payload, **kwargs):
            con = sqlite3.connect(self.path, timeout=.01)
            try:
                con.execute('INSERT INTO attempts VALUES (?,?,?,?)',
                            ('during-parse', '2026-10-23T10:00:01+08:00', '成功', 'synthetic'))
                con.commit()
            finally:
                con.close()
            return real_loads(payload, **kwargs)

        with patch.object(charts.json, 'loads', side_effect=collector_can_commit):
            self.assertEqual(self._get()['status'], 'available')

    def test_repeated_old_quote_on_weekend_preserves_one_point_and_original_receipt(self):
        at = '2026-10-23T14:55:54+08:00'
        self._insert(at)
        self._get()
        self._insert(at, received='2026-10-24T11:00:00+08:00')
        history = self._get(moment('2026-10-24T12:00:00+08:00'), refresh=True)
        self.assertEqual(history['session_day'], '2026-10-23')
        self.assertEqual(len(history['points']), 1)
        self.assertEqual(history['points'][0]['received_at'], at)

    def test_display_quotes_after_trading_cutoff_are_retained_with_their_own_time(self):
        self._insert('2026-10-23T14:55:54+08:00')
        self._insert('2026-10-23T16:14:27+08:00')
        history = self._get(moment('2026-10-24T12:00:00+08:00'))
        self.assertEqual(history['session_day'], '2026-10-23')
        self.assertEqual(history['points'][-1]['at'], '2026-10-23T16:14:27+08:00')
        self.assertTrue(history['points'][-1]['break_before'])

    def test_latest_quote_day_wins_over_receipt_order_and_old_day_is_not_joined(self):
        self._insert('2026-10-22T15:00:00+08:00')
        self._insert('2026-10-23T10:00:00+08:00')
        self._insert('2026-10-22T15:00:00+08:00', received='2026-10-23T10:01:00+08:00')
        history = self._get()
        self.assertEqual(history['session_day'], '2026-10-23')
        self.assertEqual(len(history['points']), 1)

    def test_gap_lunch_and_previous_close_change_break_lines_without_interpolation(self):
        for at, previous in [('10:00:00', 2.), ('10:00:30', 2.), ('10:02:01', 2.),
                             ('11:30:00', 2.), ('13:00:00', 2.), ('13:00:30', 2.1)]:
            self._insert(f'2026-10-23T{at}+08:00', previous=previous)
        points = self._get()['points']
        self.assertEqual([p['break_before'] for p in points], [False, False, True, True, True, True])
        self.assertEqual(len(points), 6)

    def test_collection_failure_breaks_recovery_and_daily_failure_is_ignored(self):
        self._insert('2026-10-23T10:00:00+08:00')
        self._attempt('2026-10-23T10:00:10+08:00')
        # A repeat of an old quote cannot cross the failure barrier.
        self._insert('2026-10-23T10:00:00+08:00', received='2026-10-23T10:00:20+08:00')
        self.assertEqual(self._get()['reason'], 'collection_failed')
        # The new snapshot is committed before a success attempt, as in production.
        self._insert('2026-10-23T10:00:30+08:00')
        self._attempt('2026-10-23T10:00:40+08:00', '日线失败')
        self._insert('2026-10-23T10:01:00+08:00')
        history = self._get(refresh=True)
        self.assertIsNone(history['reason'])
        self.assertEqual([p['break_before'] for p in history['points']], [False, True, False])

    def test_same_time_conflict_is_removed_and_cannot_be_restored_by_repetition(self):
        for at, price in [('10:00:00', 2.), ('10:00:30', 2.01), ('10:00:30', 2.02),
                          ('10:00:30', 2.01), ('10:01:00', 2.03)]:
            self._insert(f'2026-10-23T{at}+08:00', price=price)
        history = self._get()
        self.assertEqual([p['price'] for p in history['points']], [2., 2.03])
        self.assertTrue(history['points'][1]['break_before'])
        self.assertEqual(history['reason'], 'invalid_samples')

    def test_out_of_order_source_samples_sort_by_source_time(self):
        self._insert('2026-10-23T10:00:30+08:00')
        self._insert('2026-10-23T10:00:00+08:00', received='2026-10-23T10:00:40+08:00')
        self.assertEqual([p['at'][11:19] for p in self._get()['points']], ['10:00:00', '10:00:30'])

    def test_invalid_numbers_future_naive_and_wrong_day_never_become_valid_points(self):
        cases = [{'price': True}, {'price': float('nan')}, {'price': float('inf')}, {'price': '2'},
                 {'previous_close': 0}, {'previous_close': -1}, {'day': '2026-10-22'},
                 {'quote_at': '2026-10-23T10:00:00'}, {'quote_at': '2026-10-24T10:00:00+08:00'},
                 {'quote_at': '2026-10-23T10:00:01+08:00'}]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with database(self.path) as con:
                    con.execute('DELETE FROM snapshots')
                self._insert('2026-10-23T10:00:00+08:00', overrides=overrides)
                history = self._get(refresh=True)
                self.assertEqual(history['status'], 'invalid')
                self.assertEqual(history['points'], [])
                json.dumps(history, allow_nan=False)

    def test_malformed_duplicate_json_and_invalid_receipt_are_isolated_from_account_api(self):
        self._raw('{"received_at":null,"received_at":"2026-10-23T10:00:00+08:00"}')
        self._raw('{')
        self._insert('2026-10-23T10:00:00+08:00', received='2026-10-24T10:00:00+08:00')
        self.assertEqual(self._get()['status'], 'invalid')
        self._insert('2026-10-23T10:00:30+08:00')
        self.assertEqual(self._get(refresh=True)['status'], 'available')

    def test_missing_attempt_table_preserves_samples_but_never_invents_continuity(self):
        with database(self.path) as con:
            con.execute('DROP TABLE attempts')
        self._insert('2026-10-23T10:00:00+08:00')
        self._insert('2026-10-23T10:00:30+08:00')
        history = self._get()
        self.assertEqual(history['reason'], 'collection_state_unavailable')
        self.assertTrue(history['points'][1]['break_before'])

    def test_bootstrap_and_restart_are_bounded_and_honest_after_many_duplicate_receipts(self):
        at = '2026-10-23T14:55:54+08:00'
        self._insert('2026-10-23T10:00:00+08:00')
        self._insert(at)
        warm = self._get()
        self.assertEqual(len(warm['points']), 2)
        # Use a single synthetic transaction, not a production collector.
        with database(self.path) as con:
            payload = con.execute('SELECT payload FROM snapshots ORDER BY rowid DESC LIMIT 1').fetchone()[0]
            con.executemany('INSERT INTO snapshots VALUES (?,?,?)',
                [(f'duplicate-{i}', at, payload) for i in range(charts.MAX_ROWS + 2)])
        history = charts.IntradayChartReader(self.home).snapshot(moment())[charts.SYMBOLS[0]]
        self.assertEqual(len(history['points']), 1)
        self.assertTrue(history['truncated'])
        self.assertEqual(history['session_day'], '2026-10-23')

    def test_incremental_backlog_resets_to_newest_tail_and_caps_unique_points(self):
        self._insert('2026-10-22T15:00:00+08:00')
        self._get()
        with patch.object(charts, 'MAX_ROWS', 4):
            for index in range(7):
                self._insert(f'2026-10-23T10:0{index}:00+08:00')
            history = self._get(refresh=True)
        self.assertTrue(history['truncated'])
        self.assertEqual(len(history['points']), 4)
        self.assertEqual(history['points'][0]['at'], '2026-10-23T10:03:00+08:00')
        self.assertEqual(history['session_day'], '2026-10-23')
        with patch.object(charts, 'MAX_POINTS', 2):
            self._insert('2026-10-23T10:07:00+08:00')
            self.assertEqual(len(self._get(refresh=True)['points']), 2)

    def test_actual_600_point_cap_also_bounds_invalid_tombstones(self):
        start = moment('2026-10-23T09:30:00+08:00')
        with database(self.path) as con:
            rows = []
            for index in range(605):
                stamp = (start + timedelta(seconds=index * 30)).isoformat()
                batch = dict(received_at=stamp, quotes={s: dict(quote_at=stamp, price=2., previous_close=2.) for s in charts.SYMBOLS})
                rows.append((str(index), stamp, json.dumps(batch)))
            con.executemany('INSERT INTO snapshots VALUES (?,?,?)', rows)
        history = self._get()
        self.assertEqual(len(history['points']), 600)
        self.assertTrue(history['truncated'])
        with patch.object(charts, 'MAX_POINTS', 2):
            for minute in range(3):
                self._insert(f'2026-10-23T15:0{minute}:00+08:00', overrides={'price': False})
            self._get(refresh=True)
        self.assertEqual(len(self.reader._state['assets'][charts.SYMBOLS[0]]['samples']), 2)

    def test_payload_limits_apply_before_json_materialization_and_count_utf8_bytes(self):
        self._insert('2026-10-23T10:00:00+08:00', padding='中' * (charts.MAX_PAYLOAD_BYTES // 2))
        self._insert('2026-10-23T10:00:30+08:00')
        real_loads, lengths = json.loads, []

        def tracked(payload, **kwargs):
            lengths.append(len(payload.encode('utf-8')))
            return real_loads(payload, **kwargs)

        with patch.object(charts.json, 'loads', side_effect=tracked):
            history = self._get()
        self.assertEqual(len(lengths), 1)
        self.assertLessEqual(max(lengths), charts.MAX_PAYLOAD_BYTES)
        self.assertEqual(len(history['points']), 1)
        self.assertEqual(history['reason'], 'invalid_samples')

    def test_total_payload_budget_does_not_load_then_discard_unbounded_text(self):
        for minute in range(6):
            self._insert(f'2026-10-23T10:0{minute}:00+08:00', padding='x' * 1000)
        real_loads, sizes = json.loads, []

        def tracked(payload, **kwargs):
            sizes.append(len(payload.encode('utf-8')))
            return real_loads(payload, **kwargs)

        with patch.object(charts, 'MAX_READ_BYTES', 4096), patch.object(charts.json, 'loads', side_effect=tracked):
            history = self._get()
        self.assertLessEqual(sum(sizes), 4096)
        self.assertTrue(history['truncated'])
        self.assertLess(len(history['points']), 6)
        self.assertEqual(history['points'][-1]['at'], '2026-10-23T10:05:00+08:00')

    def test_database_replacement_rowid_regression_and_cursor_mutation_rebuild(self):
        self._insert('2026-10-23T10:00:00+08:00')
        self._insert('2026-10-23T10:00:30+08:00')
        self._get()
        other = self.home / 'replacement.sqlite3'
        self._schema(other)
        self._insert('2026-10-23T11:00:00+08:00', path=other)
        other.replace(self.path)
        self.assertEqual(len(self._get(refresh=True)['points']), 1)
        self._insert('2026-10-23T11:00:30+08:00')
        self._get(refresh=True)
        with database(self.path) as con:
            con.execute('DELETE FROM snapshots')
        self._insert('2026-10-23T13:00:00+08:00')
        self.assertEqual([p['at'][11:19] for p in self._get(refresh=True)['points']], ['13:00:00'])
        with database(self.path) as con:
            con.execute("UPDATE snapshots SET id='changed-anchor'")
        self._insert('2026-10-23T13:00:30+08:00')
        self.assertEqual(len(self._get(refresh=True)['points']), 2)

    def test_invalid_now_and_clock_rollback_do_not_expose_future_cache(self):
        self._insert('2026-10-23T10:00:00+08:00')
        self._get()
        self.assertEqual(self.reader.snapshot(datetime(2026, 10, 23))[charts.SYMBOLS[0]]['reason'], 'invalid_time')
        self.assertEqual(self._get(moment('2026-10-23T09:00:00+08:00'))['reason'], 'clock_regressed')


if __name__ == '__main__':
    unittest.main()
