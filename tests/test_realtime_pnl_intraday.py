import json
import os
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_realtime_pnl_history import raw_view, TZ
from test_realtime_paper_pnl import holding
from realtime_paper_engine import PaperLedger, TradingCalendar
from realtime_paper_pnl_history import update_and_read_history, read_history, project_account_pnl_history
from realtime_paper_pnl_intraday import LIMIT, DAYS


def at(stamp='2026-10-27T10:00:00+08:00', revision=1, cash='10000.00'):
    raw = raw_view(stamp[:10], revision, cash)
    raw['response_at'] = stamp
    return raw


class IntradayObservationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.calendar = TradingCalendar()

    def tearDown(self):
        self.db.close()

    def observe(self, raw):
        self.db.execute('BEGIN')
        raw['_pnl_history'] = update_and_read_history(self.db, raw, self.calendar)
        self.db.commit()
        return project_account_pnl_history(raw, calendar=self.calendar)

    def test_one_minute_upsert_preserves_first_actual_observation_for_fallback(self):
        self.observe(at(cash='10100.00'))
        raw = at('2026-10-27T10:00:35+08:00', 2, '10110.00')
        history = self.observe(raw)
        points = history['intraday']['points']
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]['cumulative_pnl'], '110.00')
        self.assertIsNone(points[0]['daily_pnl'])
        self.assertEqual(points[0]['since_first_observation_pnl'], '10.00')
        self.assertEqual(points[0]['first_observed_at'], '2026-10-27T10:00:00+08:00')
        later = self.observe(at('2026-10-27T10:01:05+08:00', 3, '10080.00'))
        self.assertEqual(len(later['intraday']['points']), 2)
        self.assertEqual(later['intraday']['points'][-1]['since_first_observation_pnl'], '-20.00')
        self.assertIsNone(later['intraday']['points'][-1]['daily_pnl'])
        self.assertEqual(len(later['points']), 1)
        self.assertEqual(later['points'][0]['cumulative_pnl'], '80.00')

    def test_real_daily_change_uses_prior_day_and_not_first_intraday_observation(self):
        self.observe(at('2026-10-26T14:50:00+08:00', 1, '10020.00'))
        first = self.observe(at('2026-10-27T10:00:00+08:00', 2, '10080.00'))['intraday']
        self.assertEqual(first['points'][0]['daily_pnl'], '60.00')
        self.assertEqual(first['points'][0]['since_first_observation_pnl'], '0.00')
        second = self.observe(at('2026-10-27T10:01:00+08:00', 3, '10045.00'))['intraday']
        self.assertEqual(second['points'][-1]['daily_pnl'], '25.00')
        self.assertEqual(second['points'][-1]['daily_base_date'], '2026-10-26')
        self.assertEqual(second['points'][-1]['since_first_observation_pnl'], '-35.00')

    def test_first_day_missing_day_or_capital_reset_never_fabricates_daily_zero(self):
        self.observe(at('2026-10-23T10:00:00+08:00', 1))
        raw = at('2026-10-27T10:00:00+08:00', 2, '10045.00')
        self.assertIsNone(self.observe(raw)['intraday']['points'][0]['daily_pnl'])
        raw.update(response_at='2026-10-27T10:00:30+08:00', revision='3')
        raw['account'].update(initial_capital='20000.00', cash='20000.00', equity='20000.00')
        raw['events'].append({'id': 'second-capital', 'type': 'capital_changed', 'at': raw['response_at'], 'capital': '20000.00'})
        points = self.observe(raw)['intraday']['points']
        self.assertEqual(len(points), 2)  # Separate capital segments in one minute.
        self.assertNotEqual(points[0]['segment_id'], points[1]['segment_id'])
        self.assertIsNone(points[-1]['daily_pnl'])
        self.assertEqual(points[-1]['since_first_observation_pnl'], '0.00')
        self.assertEqual(points[-1]['first_observed_at'], raw['response_at'])
        self.assertTrue(points[-1]['break_before'])

    def test_lunch_missing_minutes_and_market_close_do_not_join_or_fabricate(self):
        stamps = ('10:00:00', '10:01:00', '10:04:00', '11:29:00', '13:00:00')
        for i, stamp in enumerate(stamps, 1):
            result = self.observe(at('2026-10-27T'+stamp+'+08:00', i))
        self.assertEqual([p['break_before'] for p in result['intraday']['points']], [True, False, True, True, True])
        for i, stamp in enumerate(('12:00:00', '15:00:00'), 6):
            # Noon cannot be submitted after 13:00 (clock regression); use a fresh DB.
            if stamp.startswith('12'): continue
            result = self.observe(at('2026-10-27T'+stamp+'+08:00', i))
            self.assertEqual(len(result['intraday']['points']), 5)
            self.assertEqual(result['intraday']['points'][-1]['phase'], 'last_recorded')
            self.assertEqual(result['points'][-1]['observed_at'], '2026-10-27T15:00:00+08:00')

    def test_cash_only_lunch_and_overnight_only_change_daily_history(self):
        for i, stamp in enumerate(('08:00:00', '12:00:00', '18:00:00'), 1):
            result = self.observe(at('2026-10-27T'+stamp+'+08:00', i))
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['intraday']['points'], [])
            self.assertEqual(result['intraday']['reason'], 'no_recorded_valuations_today')

    def test_stale_quote_rejected_and_first_fresh_quote_uses_actual_current_pnl(self):
        raw = at('2026-10-23T10:00:00+08:00', 1, '8995.00')
        holding(raw, price='11.000')
        raw['quotes']['sz159915']['received_at'] = '2026-10-23T09:59:59+08:00'
        raw['fills'] = [{'id': 'buy', 'fee': '5.00', 'matched_at': '2026-10-23T09:45:00+08:00'}]
        points = self.observe(raw)['intraday']['points']
        self.assertEqual(points[0]['cumulative_pnl'], '95.00')
        raw.update(response_at='2026-10-23T10:02:00+08:00', revision='2')
        self.assertEqual(len(self.observe(raw)['intraday']['points']), 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_pnl_intraday').fetchone()[0], 1)

    def test_new_day_shows_empty_today_with_dated_previous_availability(self):
        self.observe(at('2026-10-26T10:00:00+08:00', 1))
        raw = at('2026-10-27T08:00:00+08:00', 2)
        result = self.observe(raw)['intraday']
        self.assertEqual(result['date'], '2026-10-27')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['available_dates'], ['2026-10-26'])
        self.assertEqual(result['latest_recorded_at'], '2026-10-26T10:00:00+08:00')
        self.assertIsNone(result['last_recorded_at'])
        self.assertEqual(result['points'], [])
        self.assertEqual(raw['_pnl_history']['intraday']['points'], [])

    def test_only_latest_five_dates_retained_but_only_today_returned(self):
        day = datetime(2026, 10, 19, 10, tzinfo=TZ)
        for i in range(7):
            raw = at(day.isoformat(), i+1, format(10000+i, '.2f'))
            result = self.observe(raw)
            day = datetime.combine(self.calendar.next_session(day.date()), day.time(), TZ)
        rows = self.db.execute('SELECT DISTINCT day FROM paper_pnl_intraday ORDER BY day').fetchall()
        self.assertEqual(len(rows), DAYS)
        self.assertEqual(len(result['intraday']['available_dates']), DAYS)
        self.assertEqual(len(result['intraday']['points']), 1)
        self.assertEqual(len(raw['_pnl_history']['intraday']['points']), 1)
        self.assertTrue(result['intraday']['truncated'])
        self.assertEqual(len(result['points']), 7)

    def test_global_bound_keeps_original_first_baseline_after_first_bucket_pruned(self):
        with patch('realtime_paper_pnl_intraday.LIMIT', 3):
            for i in range(5):
                result = self.observe(at('2026-10-27T10:0'+str(i)+':00+08:00', i+1, format(10000+i, '.2f')))
            points = result['intraday']['points']
            self.assertEqual(len(points), 3)
            self.assertEqual(points[0]['since_first_observation_pnl'], '2.00')
            self.assertEqual(points[-1]['since_first_observation_pnl'], '4.00')
            self.assertEqual(points[0]['first_observed_at'], '2026-10-27T10:00:00+08:00')
            self.assertTrue(result['intraday']['truncated'])
            self.assertTrue(points[0]['break_before'])

    def test_old_daily_history_is_not_backfilled_as_fake_intraday_observations(self):
        self.observe(at('2026-10-27T10:00:00+08:00', 1, '10100.00'))
        self.db.execute('DROP TABLE paper_pnl_intraday')
        self.db.execute('DROP TABLE paper_pnl_intraday_meta')
        raw = at('2026-10-27T10:15:00+08:00', 2, '10075.00')
        raw['_pnl_history'] = read_history(self.db, raw)
        self.assertEqual(project_account_pnl_history(raw)['intraday']['points'], [])
        result = self.observe(raw)['intraday']
        self.assertEqual(len(result['points']), 1)
        self.assertEqual(result['points'][0]['observed_at'], raw['response_at'])
        self.assertEqual(result['points'][0]['since_first_observation_pnl'], '0.00')
        self.assertEqual(result['points'][0]['first_observation_cumulative_pnl'], '75.00')

    def test_tampered_money_time_identity_or_baseline_is_rejected_without_mutation(self):
        raw = at(); self.observe(raw)
        original = deepcopy(raw)
        with patch('sqlite3.connect', side_effect=AssertionError('pure projection')), patch('builtins.open', side_effect=AssertionError('pure projection')):
            self.assertEqual(project_account_pnl_history(raw)['intraday']['status'], 'available')
        self.assertEqual(raw, original)
        for field, value in (('equity', '10001.00'), ('cumulative_pnl', 'NaN'), ('daily_pnl', '0.00'),
                             ('ledger_revision', '1000'), ('observed_at', '2026-10-28T10:00:00+08:00'),
                             ('segment_id', 'a'*64), ('first_base', {'observed_at': '2026-10-26T10:00:00+08:00', 'cumulative_pnl': '0.00'}),
                             ('first_base', {'observed_at': raw['response_at'], 'cumulative_pnl': '1.00'})):
            changed = deepcopy(raw)
            changed['_pnl_history']['intraday']['points'][0][field] = value
            result = project_account_pnl_history(changed)
            self.assertEqual(result['intraday']['reason'], 'invalid_history', field)
            self.assertEqual(result['status'], 'available')  # Independent existing daily view remains usable.

    def test_repeat_stability_and_revision_or_clock_rollback_fail_closed(self):
        raw = at(revision=10); first = self.observe(raw)
        self.assertEqual(self.observe(raw), first)
        before = self.db.execute('SELECT * FROM paper_pnl_intraday').fetchall()
        for stamp, revision in (('2026-10-26T10:00:00+08:00', 11), ('2026-10-28T10:00:00+08:00', 9)):
            result = self.observe(at(stamp, revision))
            self.assertEqual(result['intraday']['reason'], 'history_unavailable')
            self.assertEqual(self.db.execute('SELECT * FROM paper_pnl_intraday').fetchall(), before)


class IntradayLedgerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.now = [datetime(2026, 10, 27, 10, tzinfo=TZ)]
        self.ledger = PaperLedger(self.folder.name, now=lambda: self.now[0])

    def tearDown(self):
        self.ledger.close(); self.folder.cleanup()

    def sql(self, statement):
        with closing(sqlite3.connect(self.ledger.path)) as db:
            rows = db.execute(statement).fetchall(); db.commit(); return rows

    def test_readonly_get_and_exact_idempotent_replay_never_append_intraday(self):
        first = self.ledger.create('10000', idempotency_key='minute-created')
        original = self.ledger.path.read_bytes()
        self.now[0] += timedelta(minutes=2)
        self.ledger.snapshot(); self.ledger.snapshot()
        self.assertEqual(self.ledger.path.read_bytes(), original)
        self.ledger.tick()
        rows = self.sql('SELECT * FROM paper_pnl_intraday')
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.ledger.create('10000', idempotency_key='minute-created'), first)
        self.assertEqual(self.sql('SELECT * FROM paper_pnl_intraday'), rows)
        self.assertEqual(len(project_account_pnl_history(first)['intraday']['points']), 1)

    def test_restart_and_consistent_sqlite_backup_preserve_original_points(self):
        self.ledger.create('10000')
        self.now[0] += timedelta(minutes=1); self.ledger.tick()
        backup = Path(self.folder.name)/'intraday-backup.sqlite3'
        with closing(sqlite3.connect(self.ledger.path)) as source, closing(sqlite3.connect(backup)) as dest:
            source.backup(dest)
        original = self.sql('SELECT * FROM paper_pnl_intraday')
        self.ledger.close(); self.ledger = PaperLedger(self.folder.name, now=lambda: self.now[0])
        self.assertEqual(len(project_account_pnl_history(self.ledger.snapshot())['intraday']['points']), 2)
        self.now[0] += timedelta(minutes=1); self.ledger.tick()
        with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(self.ledger.path)) as dest:
            source.backup(dest)
        self.assertEqual(self.sql('SELECT * FROM paper_pnl_intraday'), original)

    def test_intraday_write_failure_preserves_daily_updates_and_business(self):
        self.ledger.create('10000')
        daily = self.sql('SELECT * FROM paper_pnl_daily')
        intraday = self.sql('SELECT * FROM paper_pnl_intraday')
        self.sql("CREATE TRIGGER fail_intraday BEFORE INSERT ON paper_pnl_intraday BEGIN SELECT RAISE(ABORT,'synthetic minute failure'); END")
        self.now[0] += timedelta(minutes=1)
        result = self.ledger.configure_capital('20000')
        self.assertEqual(result['account']['initial_capital'], '20000.00')
        self.assertEqual(project_account_pnl_history(result)['intraday']['reason'], 'history_unavailable')
        self.assertEqual(len(self.sql('SELECT * FROM paper_pnl_daily')), len(daily)+1)
        self.assertEqual(project_account_pnl_history(result)['status'], 'available')
        self.assertEqual(self.sql('SELECT * FROM paper_pnl_intraday'), intraday)

    def test_corrupt_intraday_rows_do_not_stop_established_daily_history(self):
        self.ledger.create('10000')
        self.sql("UPDATE paper_pnl_intraday SET data='{}'")
        broken = self.sql('SELECT * FROM paper_pnl_intraday')
        self.now[0] += timedelta(minutes=1); self.ledger.tick()
        result = project_account_pnl_history(self.ledger.snapshot())
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['points'][-1]['observed_at'], self.now[0].isoformat())
        self.assertEqual(result['intraday']['reason'], 'history_unavailable')
        self.assertEqual(self.sql('SELECT * FROM paper_pnl_intraday'), broken)

    def test_business_failure_or_sqlite_outer_abort_cannot_leave_derived_points(self):
        self.ledger.create('10000')
        for target, operation in (('ledger', 'ABORT'), ('paper_pnl_intraday', 'ROLLBACK')):
            with self.subTest(target=target):
                before = {table: self.sql('SELECT * FROM '+table) for table in ('ledger', 'paper_pnl_daily', 'paper_pnl_intraday')}
                action = 'UPDATE' if target == 'ledger' else 'INSERT'
                self.sql("CREATE TRIGGER fail_operation BEFORE "+action+" ON "+target+" BEGIN SELECT RAISE("+operation+",'synthetic failure'); END")
                self.now[0] += timedelta(minutes=1)
                with self.assertRaises(sqlite3.IntegrityError): self.ledger.configure_capital('20000')
                for table, rows in before.items(): self.assertEqual(self.sql('SELECT * FROM '+table), rows)
                self.sql('DROP TRIGGER fail_operation')

    def test_legacy_daily_only_snapshot_never_creates_intraday_tables(self):
        self.ledger.create('10000')
        self.sql('DROP TABLE paper_pnl_intraday'); self.sql('DROP TABLE paper_pnl_intraday_meta')
        before = self.ledger.path.read_bytes()
        result = project_account_pnl_history(self.ledger.snapshot())
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['intraday']['points'], [])
        self.assertEqual(self.ledger.path.read_bytes(), before)
        self.now[0] += timedelta(minutes=5); self.ledger.tick()
        intraday = project_account_pnl_history(self.ledger.snapshot())['intraday']
        self.assertEqual(len(intraday['points']), 1)
        self.assertEqual(intraday['points'][0]['first_observed_at'], self.now[0].isoformat())


if __name__ == '__main__':
    unittest.main()
