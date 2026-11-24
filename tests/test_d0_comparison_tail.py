"""Recorded intraday observations remain records, never new price evidence."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_comparison_tail import retain_intraday

NOW = datetime.fromisoformat('2026-10-29T10:05:00+08:00')
AT = '2026-10-29T10:00:00+08:00'
SOURCE = '2026-10-29T09:59:58+08:00'


def fixture(live=False):
    segment = dict(id='capital-1', starts_at='2026-10-21T09:30:00+08:00', ends_at=None,
                   baseline_at='2026-10-21T15:00:00+08:00', baseline_equity='10000.00',
                   capital='10000.00')
    historical = dict(key='capital-1:close:2026-10-28', phase='reconstructed_close',
                      at='2026-10-28T15:00:00+08:00', date='2026-10-28',
                      segment_id='capital-1', equity='10100.00', return_ratio=.01,
                      source_at='2026-10-28T15:00:00+08:00', observed_at=None,
                      cash_only=False, break_before=False)
    point = dict(key='capital-1:intraday_estimate:' + AT, phase='intraday_estimate', at=AT,
                 date='2026-10-29', segment_id='capital-1', equity='10200.00', return_ratio=.02,
                 source_at=SOURCE, observed_at=AT, cash_only=False, break_before=False)
    lines = []
    for name in ('account', 'd0', 'market', 'chinext'):
        points = [deepcopy(historical)] + ([deepcopy(point)] if live else [])
        lines.append(dict(id=name, method='test-' + name, status='available', reason=None,
                          as_of=SOURCE if live else historical['at'], points=points))
    return dict(contract_version='d0-performance-comparison-v1', account_id='account-1',
                normalization='first_shared_confirmed_close', status='available',
                generated_at=NOW.isoformat(), segments=[segment], series=lines)


def lines(value):
    return {row['id']: row for row in value['series']}


class RetainedComparisonTailTests(unittest.TestCase):
    def setUp(self):
        self.current, self.previous = fixture(), fixture(True)

    def retain(self, **kwargs):
        return retain_intraday(self.current, self.previous, now=kwargs.get('now', NOW),
                               same_identity=kwargs.get('same_identity', True))

    def assertNotRetained(self, result):
        for name in ('account', 'd0'):
            self.assertEqual(len(lines(result)[name]['points']), 1)

    def test_expired_record_retains_exact_times_and_value_without_input_mutation(self):
        original = deepcopy((self.current, self.previous))
        result = self.retain()
        for name in ('account', 'd0'):
            prior = lines(self.previous)[name]['points'][-1]
            kept = lines(result)[name]['points'][-1]
            self.assertEqual({k: v for k, v in kept.items() if k not in ('retained', 'retained_reason')}, prior)
            self.assertIs(kept['retained'], True)
            self.assertEqual(kept['retained_reason'], 'waiting_verified_quote')
            self.assertEqual(lines(result)[name]['as_of'], SOURCE)
        self.assertEqual((self.current, self.previous), original)
        self.assertEqual(len(lines(result)['market']['points']), 1)
        self.assertEqual(len(lines(result)['chinext']['points']), 1)

    def test_business_signal_or_model_identity_change_never_retains(self):
        for identity in (False, None, 1):
            with self.subTest(identity=identity):
                self.assertNotRetained(self.retain(same_identity=identity))

    def test_account_contract_normalization_or_segment_change_never_retains(self):
        for field, value in (('account_id', 'other'), ('contract_version', 'new'),
                             ('normalization', 'other'), ('status', 'waiting')):
            with self.subTest(field=field):
                self.current = fixture()
                self.current[field] = value
                self.assertNotRetained(self.retain())
        for field, value in (('id', 'new'), ('capital', '20000.00'), ('baseline_equity', '10001.00'),
                             ('baseline_at', '2026-10-22T15:00:00+08:00'),
                             ('starts_at', '2026-10-21T10:30:00+08:00'),
                             ('ends_at', '2026-10-29T10:00:30+08:00')):
            with self.subTest(field=field):
                self.current = fixture()
                self.current['segments'][-1][field] = value
                self.assertNotRetained(self.retain())

    def test_cross_day_never_carries_a_record_into_today(self):
        self.assertNotRetained(self.retain(now=NOW + timedelta(days=1)))

    def test_session_boundaries_keep_historical_record_with_unchanged_timestamp(self):
        for clock in ('2026-10-29T12:00:00+08:00', '2026-10-29T15:00:00+08:00'):
            with self.subTest(clock=clock):
                result = self.retain(now=datetime.fromisoformat(clock))
                self.assertEqual(lines(result)['account']['points'][-1]['at'], AT)
                self.assertTrue(lines(result)['account']['points'][-1]['retained'])

    def test_new_current_estimate_replaces_old_without_retained_flag(self):
        self.current = fixture(True)
        for row in self.current['series']:
            row['points'][-1].update(at='2026-10-29T10:04:55+08:00',
                                      observed_at='2026-10-29T10:04:55+08:00',
                                      source_at='2026-10-29T10:04:52+08:00')
        result = self.retain()
        self.assertEqual(result, self.current)
        self.assertNotIn('retained', lines(result)['account']['points'][-1])

    def test_retained_record_survives_repeated_refresh_without_duplicates_or_new_time(self):
        first = self.retain()
        result = retain_intraday(self.current, first, now=NOW + timedelta(minutes=10), same_identity=True)
        for name in ('account', 'd0'):
            self.assertEqual(len(lines(result)[name]['points']), 2)
            self.assertEqual(lines(result)[name]['points'][-1], lines(first)[name]['points'][-1])

    def test_cash_only_record_requires_explicit_cash_status_and_original_observation(self):
        for name in ('account', 'd0'):
            lines(self.previous)[name]['points'][-1].update(source_at=None, cash_only=True)
        result = self.retain()
        self.assertEqual(lines(result)['account']['as_of'], AT)
        self.assertIsNone(lines(result)['account']['points'][-1]['source_at'])
        for row in self.previous['series']:
            row['points'][-1]['cash_only'] = False
        self.assertNotRetained(self.retain())

    def test_changed_history_missing_close_and_line_failure_do_not_restore_old_tail(self):
        for field, value in (('equity', None), ('equity', '10101.00'),
                             ('at', '2026-10-29T15:00:00+08:00'),
                             ('break_before', True), ('phase', 'model_close')):
            with self.subTest(field=field, value=value):
                self.current = fixture()
                for row in self.current['series']:
                    row['points'][-1][field] = value
                self.assertNotRetained(self.retain())
        for field, value in (('method', 'other'), ('status', 'unavailable')):
            with self.subTest(field=field):
                self.current = fixture()
                for row in self.current['series']:
                    row[field] = value
                self.assertNotRetained(self.retain())

    def test_existing_history_gap_and_original_break_are_preserved(self):
        for value in (self.current, self.previous):
            for row in value['series']:
                row['points'][0]['equity'] = None
                row['points'][0]['return_ratio'] = None
        for row in self.previous['series']:
            row['points'][-1]['break_before'] = True
        result = self.retain()
        for name in ('account', 'd0'):
            self.assertIsNone(lines(result)[name]['points'][0]['equity'])
            self.assertIs(lines(result)[name]['points'][-1]['break_before'], True)

    def test_future_malformed_or_inconsistent_record_is_not_carried(self):
        changes = [dict(at='2026-10-29T10:06:00+08:00'),
                   dict(source_at='2026-10-29T10:06:00+08:00'),
                   dict(observed_at='2026-10-29T10:06:00+08:00'),
                   dict(observed_at=None), dict(at='2026-10-29T10:00:00'),
                   dict(date='2026-10-28'), dict(equity='NaN'), dict(equity='-1'),
                   dict(return_ratio=float('inf')), dict(return_ratio=True),
                   dict(return_ratio=.03), dict(segment_id='old'),
                   dict(source_at='2026-10-28T15:00:00+08:00')]
        for change in changes:
            with self.subTest(change=change):
                self.previous = fixture(True)
                for row in self.previous['series']:
                    row['points'][-1].update(change)
                self.assertNotRetained(self.retain())

    def test_no_prior_history_or_ambiguous_series_is_not_retained(self):
        for value in (None, {}, {'status': 'waiting'}):
            with self.subTest(value=value):
                self.assertNotRetained(retain_intraday(self.current, value, now=NOW, same_identity=True))
        self.previous = fixture(True)
        self.previous['series'].append(deepcopy(self.previous['series'][0]))
        self.assertNotRetained(self.retain())


if __name__ == '__main__':
    unittest.main()
