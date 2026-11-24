"""Synthetic account observations only; never a live ledger or price backfill."""
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_engine import PaperLedger, TradingCalendar, PaperError
from realtime_paper_pnl_history import update_and_read_history, read_history, project_account_pnl_history, LIMIT
from realtime_paper_pnl import project_account_pnl
from test_realtime_paper_pnl import fixture, holding

TZ = timezone(timedelta(hours=8))


def raw_view(day='2026-10-23', revision=1, cash='10000.00', capital='10000.00'):
    raw = fixture(cash, capital)
    raw.update(response_at=day+'T10:00:00+08:00', revision=str(revision), events=[
        {'type': 'created', 'id': 'synthetic-created', 'at': '2026-07-06T09:30:00+08:00', 'capital': capital}])
    raw['account'].update(id='D0-forward-paper', created_at='2026-07-06T09:30:00+08:00', running=False)
    if cash != capital:
        raw['fills'] = [{'id': 'synthetic-closed-trade', 'fee': '0.00', 'matched_at': day+'T09:30:00+08:00'}]
    return raw


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:', isolation_level=None)
        self.calendar = TradingCalendar()

    def tearDown(self):
        self.con.close()

    def observe(self, raw, calendar=None):
        self.con.execute('BEGIN')
        raw['_pnl_history'] = update_and_read_history(self.con, raw, calendar or self.calendar)
        self.con.commit()
        return project_account_pnl_history(raw, calendar=calendar or self.calendar)

    def test_first_real_observation_has_no_fabricated_daily_profit(self):
        raw = raw_view(cash='10125.50')
        result = self.observe(raw)
        self.assertEqual(result['status'], 'available')
        point = result['points'][0]
        self.assertEqual(point['cumulative_pnl'], project_account_pnl(raw)['total_pnl'])
        self.assertEqual(point['cumulative_pnl'], '125.50')
        self.assertIsNone(point['daily_pnl'])
        self.assertIsNone(point['daily_base_date'])
        self.assertTrue(point['break_before'])
        self.assertEqual(point['phase'], 'intraday_estimate')
        self.assertEqual(point['record_type'], 'daily_last_observation')

    def test_day_replacement_uses_prior_day_not_previous_intraday_observation(self):
        self.observe(raw_view('2026-10-22', 1, '10100.00'))
        result = self.observe(raw_view('2026-10-23', 2, '10140.00'))
        self.assertEqual(result['points'][-1]['daily_pnl'], '40.00')
        raw = raw_view('2026-10-23', 3, '10080.00')
        raw['response_at'] = '2026-10-23T10:01:00+08:00'
        result = self.observe(raw)
        self.assertEqual(len(result['points']), 2)
        self.assertEqual(result['points'][-1]['daily_pnl'], '-20.00')
        self.assertEqual(result['points'][-1]['daily_base_date'], '2026-10-22')
        self.assertFalse(result['points'][-1]['break_before'])
        self.assertEqual(result['points'][0]['phase'], 'last_recorded')

    def test_phase_uses_server_time_and_never_claims_a_closing_valuation(self):
        raw = raw_view(); self.observe(raw)
        for at, expected in (('14:59:59', 'intraday_estimate'), ('15:00:00', 'last_recorded')):
            raw['response_at'] = '2026-10-23T'+at+'+08:00'
            point = project_account_pnl_history(raw)['points'][0]
            self.assertEqual(point['phase'], expected)
            self.assertEqual(point['observed_at'], '2026-10-23T10:00:00+08:00')
            self.assertEqual(point['record_type'], 'daily_last_observation')

    def test_weekends_and_known_holidays_are_not_missing_trading_days(self):
        self.observe(raw_view('2026-09-30', 1))
        result = self.observe(raw_view('2026-10-08', 2, '10005.00'))
        self.assertEqual(result['points'][-1]['daily_pnl'], '5.00')
        self.observe(raw_view('2026-10-23', 3, '10015.00'))
        result = self.observe(raw_view('2026-10-26', 4, '10010.00'))
        self.assertEqual(result['points'][-1]['daily_pnl'], '-5.00')

    def test_missing_trading_day_breaks_both_curves_and_does_not_claim_daily_change(self):
        self.observe(raw_view('2026-10-21', 1))
        result = self.observe(raw_view('2026-10-23', 2, '10200.00'))
        self.assertIsNone(result['points'][-1]['daily_pnl'])
        self.assertTrue(result['points'][-1]['break_before'])
        self.assertEqual(result['points'][-1]['cumulative_pnl'], '200.00')

    def test_fresh_held_prices_match_current_pnl_and_saved_fees(self):
        raw = raw_view(cash='8995.00')
        holding(raw, price='11.000')
        raw['quotes']['sz159915']['received_at'] = '2026-10-23T09:59:59+08:00'
        raw['fills'] = [{'id': 'buy', 'fee': '5.00', 'matched_at': '2026-10-23T09:45:00+08:00'}]
        result = self.observe(raw)
        self.assertEqual(result['points'][0]['cumulative_pnl'], '95.00')
        self.assertEqual(result['points'][0]['valuation_at'], '2026-10-23T09:59:58+08:00')
        self.assertFalse(result['points'][0]['cash_only'])

    def test_old_missing_future_or_delayed_quotes_do_not_replace_valid_point(self):
        original = raw_view(); self.observe(original)
        for change in ('stale', 'unknown', 'yesterday', 'future', 'queue', 'after_session'):
            with self.subTest(change=change):
                raw = raw_view(revision=2, cash='8995.00')
                holding(raw, price=None if change == 'unknown' else '11.000',
                        status=change if change in ('stale', 'unknown') else 'current')
                if change != 'unknown':
                    quote = raw['quotes']['sz159915']
                    quote['received_at'] = '2026-10-23T09:59:59+08:00'
                    if change == 'yesterday': quote['quote_at'] = '2026-10-22T09:59:58+08:00'
                    if change == 'future': quote['quote_at'] = '2026-10-23T10:00:01+08:00'
                    if change == 'queue': quote['received_at'] = '2026-10-23T09:59:50+08:00'
                    if change == 'after_session': raw['response_at'] = '2026-10-23T15:00:00+08:00'
                result = self.observe(raw)
                self.assertEqual(result['points'][0]['cumulative_pnl'], '0.00')
                self.assertEqual(result['points'][0]['ledger_revision'], '1')

    def test_cash_only_paused_account_records_but_weekend_and_unknown_calendar_do_not(self):
        self.observe(raw_view('2026-10-23', 1))
        for day in ('2026-10-24', '2027-01-04'):
            raw = raw_view(day, 2)
            result = self.observe(raw)
            self.assertEqual(len(result['points']), 1)
            self.assertEqual(result['points'][0]['date'], '2026-10-23')
        result = self.observe(raw_view('2026-10-26', 3))
        self.assertEqual(len(result['points']), 2)

    def test_capital_a_b_a_is_three_segments_and_pause_resume_is_not(self):
        raw = raw_view(); a = self.observe(raw)
        raw['revision'] = '2'; raw['response_at'] = '2026-10-23T10:01:00+08:00'
        raw['account'].update(running=True, activation_generation=99)
        resumed = self.observe(raw)
        self.assertEqual(a['current_segment'], resumed['current_segment'])
        segments = [a['current_segment']]
        for index, capital in enumerate(('20000.00', '10000.00'), 3):
            raw['revision'] = str(index)
            raw['response_at'] = '2026-10-23T10:0'+str(index)+':00+08:00'
            raw['account'].update(initial_capital=capital, cash=capital, equity=capital)
            raw['events'].append({'id': 'capital-'+str(index), 'type': 'capital_changed',
                                  'at': raw['response_at'], 'capital': capital})
            result = self.observe(raw); segments.append(result['current_segment'])
            self.assertEqual(result['points'][-1]['cumulative_pnl'], '0.00')
            self.assertIsNone(result['points'][-1]['daily_pnl'])
            self.assertTrue(result['points'][-1]['break_before'])
        self.assertEqual(len(set(segments)), 3)
        self.assertEqual(len(result['points']), 3)

    def test_time_and_revision_regressions_never_change_history(self):
        self.observe(raw_view('2026-10-23', 10))
        before = self.con.execute('SELECT data FROM paper_pnl_daily').fetchall()
        for day, revision in (('2026-10-22', 11), ('2026-10-26', 9)):
            result = self.observe(raw_view(day, revision))
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(self.con.execute('SELECT data FROM paper_pnl_daily').fetchall(), before)

    def test_future_account_capital_or_trade_evidence_does_not_backdate_cash(self):
        for field in ('created', 'capital', 'fill'):
            raw = raw_view()
            if field == 'created': raw['account']['created_at'] = '2026-10-26T10:00:00+08:00'
            elif field == 'capital': raw['events'][0]['at'] = '2026-10-26T10:00:00+08:00'
            else: raw['fills'] = [{'id': 'future', 'fee': '0.00', 'matched_at': '2026-10-26T10:00:00+08:00'}]
            result = self.observe(raw)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='paper_pnl_daily'").fetchone()[0], 0)

    def test_exact_repeated_observation_is_stable_and_conflict_is_rejected(self):
        raw = raw_view(); first = self.observe(raw)
        self.assertEqual(self.observe(raw), first)
        conflict = raw_view(cash='10010.00')
        self.assertEqual(self.observe(conflict)['reason'], 'history_unavailable')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_pnl_daily').fetchone()[0], 1)

    def test_retention_is_global_and_keeps_first_remaining_daily_baseline(self):
        class LongCalendar(TradingCalendar):
            first, last = date(2020, 1, 1), date(2030, 12, 31)
            def is_session(self, day):
                return day.weekday() < 5
        calendar = LongCalendar()
        day = date(2026, 7, 6)
        for index in range(LIMIT+3):
            raw = raw_view(day.isoformat(), index+1, format(10000+index, '.2f'))
            result = self.observe(raw, calendar)
            day = calendar.next_session(day)
        self.assertEqual(len(result['points']), LIMIT)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['points'][0]['daily_pnl'], '1.00')
        self.assertIsNotNone(result['points'][0]['daily_base_date'])
        self.assertTrue(result['points'][0]['break_before'])
        self.assertEqual(result['points'][-1]['cumulative_pnl'], '368.00')

    def test_repeated_capital_segments_share_the_same_global_limit(self):
        raw = raw_view()
        with patch('realtime_paper_pnl_history.LIMIT', 3):
            self.observe(raw)
            for index in range(1, 5):
                capital = format(10000+index, '.2f')
                raw['revision'] = str(index+1)
                raw['response_at'] = '2026-10-23T10:0'+str(index)+':00+08:00'
                raw['account'].update(initial_capital=capital, cash=capital, equity=capital)
                raw['events'].append({'type': 'capital_changed', 'id': 'change-'+str(index),
                                      'at': raw['response_at'], 'capital': capital})
                result = self.observe(raw)
            self.assertEqual(len(result['points']), 3)
            self.assertTrue(result['truncated'])
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM paper_pnl_daily').fetchone()[0], 3)

    def test_projection_is_pure_and_rejects_tampered_numeric_time_or_identity_data(self):
        raw = raw_view(); self.observe(raw)
        before = deepcopy(raw)
        with patch('builtins.open', side_effect=AssertionError('no files')), patch('sqlite3.connect', side_effect=AssertionError('no storage')):
            self.assertEqual(project_account_pnl_history(raw)['status'], 'available')
        self.assertEqual(raw, before)
        for key, value in (('cumulative_pnl', 'NaN'), ('equity', '999.00'),
                           ('return_ratio', '1.00000000'), ('ledger_revision', '999'),
                           ('observed_at', '2026-10-26T10:00:00+08:00'), ('daily_pnl', '1.00'),
                           ('segment_id', 'f'*64)):
            changed = deepcopy(raw); changed['_pnl_history']['points'][0][key] = value
            self.assertEqual(project_account_pnl_history(changed)['reason'], 'invalid_history')
        changed = deepcopy(raw); changed['account']['created_at'] = '2026-07-06T09:31:00+08:00'
        self.assertEqual(project_account_pnl_history(changed)['reason'], 'invalid_history')
        self.assertEqual(project_account_pnl_history({})['reason'], 'no_recorded_valuations')
        json.dumps(project_account_pnl_history(raw), allow_nan=False)


class LedgerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.now = [datetime(2026, 10, 23, 10, tzinfo=TZ)]
        self.ledger = PaperLedger(self.folder.name, now=lambda: self.now[0])

    def tearDown(self):
        self.ledger.close(); self.folder.cleanup()

    def sql(self, sql, args=()):
        with closing(sqlite3.connect(self.ledger.path)) as con:
            result = con.execute(sql, args).fetchall(); con.commit(); return result

    def test_get_does_not_write_and_idempotent_command_replays_its_original_history(self):
        first = self.ledger.create('10000', idempotency_key='history-create')
        before = self.ledger.path.read_bytes()
        self.ledger.snapshot(); self.ledger.snapshot()
        self.assertEqual(self.ledger.path.read_bytes(), before)
        self.now[0] += timedelta(days=3)
        self.ledger.tick()
        later = self.sql('SELECT data FROM paper_pnl_daily')
        replay = self.ledger.create('10000', idempotency_key='history-create')
        self.assertEqual(replay, first)
        self.assertEqual(self.sql('SELECT data FROM paper_pnl_daily'), later)
        with self.assertRaises(PaperError): self.ledger.create('20000', idempotency_key='history-create')
        self.assertEqual(self.sql('SELECT data FROM paper_pnl_daily'), later)
        self.assertEqual(len(project_account_pnl_history(replay)['points']), 1)
        self.assertEqual(len(project_account_pnl_history(self.ledger.snapshot())['points']), 2)

    def test_optional_history_failure_does_not_rollback_capital_or_leave_partial_rows(self):
        self.ledger.create('10000')
        before = self.sql('SELECT * FROM paper_pnl_daily')
        self.sql("CREATE TRIGGER reject_history BEFORE INSERT ON paper_pnl_daily BEGIN SELECT RAISE(ABORT,'synthetic derived failure'); END")
        result = self.ledger.configure_capital('20000', 'history-capital')
        self.assertEqual(result['account']['initial_capital'], '20000.00')
        self.assertEqual(project_account_pnl_history(result)['reason'], 'history_unavailable')
        self.assertEqual(self.sql('SELECT * FROM paper_pnl_daily'), before)
        self.assertEqual(self.ledger.snapshot()['account']['cash'], '20000.00')

    def test_business_commit_failure_rolls_back_derived_rows_too(self):
        self.ledger.create('10000')
        business = self.sql('SELECT data FROM ledger')
        history = self.sql('SELECT * FROM paper_pnl_daily')
        self.sql("CREATE TRIGGER reject_ledger BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT,'synthetic business failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.ledger.configure_capital('20000')
        self.assertEqual(self.sql('SELECT data FROM ledger'), business)
        self.assertEqual(self.sql('SELECT * FROM paper_pnl_daily'), history)

    def test_sqlite_aborting_outer_transaction_cannot_be_reported_as_business_success(self):
        self.ledger.create('10000')
        business = self.sql('SELECT data FROM ledger')
        history = self.sql('SELECT * FROM paper_pnl_daily')
        self.sql("CREATE TRIGGER abort_outer BEFORE INSERT ON paper_pnl_daily BEGIN SELECT RAISE(ROLLBACK,'synthetic outer abort'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.ledger.configure_capital('20000')
        self.assertEqual(self.sql('SELECT data FROM ledger'), business)
        self.assertEqual(self.sql('SELECT * FROM paper_pnl_daily'), history)

    def test_old_schema_get_and_old_idempotent_replay_do_not_create_history_tables(self):
        original = self.ledger.create('10000', idempotency_key='legacy-created')
        original.pop('_pnl_history')
        state = json.loads(self.sql('SELECT data FROM ledger')[0][0])
        state['commands']['legacy-created']['result'] = deepcopy(original)
        self.sql('UPDATE ledger SET data=?', (json.dumps(state),))
        self.sql('DROP TABLE paper_pnl_daily'); self.sql('DROP TABLE paper_pnl_history_meta')
        self.sql('DROP TABLE paper_pnl_intraday'); self.sql('DROP TABLE paper_pnl_intraday_meta')
        self.assertEqual(project_account_pnl_history(self.ledger.snapshot())['reason'], 'no_recorded_valuations')
        replay = self.ledger.create('10000', idempotency_key='legacy-created')
        self.assertEqual(replay, original)
        self.assertEqual(project_account_pnl_history(replay)['reason'], 'no_recorded_valuations')
        self.assertEqual(self.sql("SELECT name FROM sqlite_master WHERE name LIKE 'paper_pnl_%'"), [])
        self.ledger.tick()
        self.assertEqual(project_account_pnl_history(self.ledger.snapshot())['status'], 'available')

    def test_sqlite_backup_and_restore_keep_the_matching_history_snapshot(self):
        self.ledger.create('10000')
        backup = Path(self.folder.name)/'synthetic-backup.sqlite3'
        with closing(sqlite3.connect(self.ledger.path)) as source, closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
        self.now[0] += timedelta(days=3); self.ledger.tick()
        self.assertEqual(len(project_account_pnl_history(self.ledger.snapshot())['points']), 2)
        with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(self.ledger.path)) as destination:
            source.backup(destination)
        restored = self.ledger.snapshot()
        self.assertEqual(len(project_account_pnl_history(restored)['points']), 1)
        self.assertEqual(project_account_pnl_history(restored)['points'][0]['date'], '2026-10-23')

    def test_read_transaction_cannot_mix_new_history_with_old_ledger_revision(self):
        self.ledger.create('10000')
        self.sql('PRAGMA journal_mode=WAL')
        original_reader = read_history
        errors = []
        def write():
            try: self.ledger.configure_capital('20000')
            except Exception as error: errors.append(error)
        def during_read(db, raw):
            thread = threading.Thread(target=write); thread.start(); thread.join(5)
            self.assertFalse(thread.is_alive()); self.assertFalse(errors)
            return original_reader(db, raw)
        with patch('realtime_paper_engine.read_history', side_effect=during_read):
            result = self.ledger.snapshot()
        self.assertEqual(result['account']['initial_capital'], '10000.00')
        self.assertEqual(len(project_account_pnl_history(result)['points']), 1)
        current = self.ledger.snapshot()
        self.assertEqual(current['account']['initial_capital'], '20000.00')
        self.assertEqual(len(project_account_pnl_history(current)['points']), 2)


if __name__ == '__main__':
    unittest.main()
