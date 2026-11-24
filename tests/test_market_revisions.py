"""Fail-closed source-revision policy using synthetic rows; no network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from web_market_revisions import RevisionGuard, JOURNAL

CN = timezone(timedelta(hours=8))
FIELDS = ['open', 'high', 'low', 'close', 'volume']


def source(moment, symbol='sz159915', key='datetime'):
    if key == 'date':
        url = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?' + urlencode(
            {'param': symbol + ',day,,2026-10-22,640,'})
    else:
        url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?' + urlencode(
            {'symbol': symbol, 'scale': 60, 'ma': 'no', 'datalen': 50000})
    return dict(source='腾讯未复权日线' if key == 'date' else '新浪未复权60分钟',
                url=url, sha256='a'*64, fetched_at=moment.isoformat())


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.now = datetime(2026, 10, 22, 17, tzinfo=CN)
        self.old = [dict(datetime='2026-10-13 10:30:00', open=3., high=3.1,
                         low=2.9, close=3., volume=100., amount=None)]
        self.new = [dict(self.old[0], high=3.2, close=3.05, volume=120.),
                    dict(self.old[0], datetime='2026-10-13 11:30:00')]

    def prepare(self, now=None, rows=None, evidence=None):
        now = now or self.now
        guard = RevisionGuard(self.home, now, 'synthetic-snapshot')
        rows = guard.retain(self.old, rows or self.new, 'datetime', FIELDS, 'sz159915',
                            [evidence or source(now)])
        return guard, rows

    def pending(self):
        guard, _ = self.prepare()
        with self.assertRaisesRegex(ValueError, '60秒'):
            guard.finish()

    def test_second_independent_observation_retains_whole_old_row(self):
        original = deepcopy(self.old)
        self.pending()
        guard, rows = self.prepare(self.now + timedelta(seconds=61))
        meta = guard.finish()
        self.assertEqual(rows, original + [self.new[-1]])
        self.assertEqual(self.old, original)
        self.assertEqual(len(meta['retained']), 1)
        record = next(iter(guard.data['records'].values()))
        self.assertEqual(record['accepted_row'], original[0])
        self.assertEqual(record['active']['observed_row'], self.new[0])

    def test_replayed_response_does_not_confirm_even_after_wall_time_passes(self):
        self.pending()
        guard, _ = self.prepare(self.now + timedelta(seconds=61), evidence=source(self.now))
        with self.assertRaisesRegex(ValueError, '60秒'):
            guard.finish()

    def test_changed_candidate_requires_two_new_observations(self):
        self.pending()
        rows = deepcopy(self.new); rows[0]['high'] += .1
        guard, _ = self.prepare(self.now + timedelta(seconds=61), rows=rows)
        with self.assertRaisesRegex(ValueError, '60秒'):
            guard.finish()
        guard, _ = self.prepare(self.now + timedelta(seconds=122), rows=rows)
        self.assertEqual(len(guard.finish()['retained']), 1)
        self.assertEqual(len(next(iter(guard.data['records'].values()))['observations']), 2)

    def test_return_to_accepted_values_resets_confirmation(self):
        self.pending()
        guard, _ = self.prepare(self.now + timedelta(seconds=61)); guard.finish()
        guard, _ = self.prepare(self.now + timedelta(seconds=122), rows=self.old); guard.finish()
        guard, _ = self.prepare(self.now + timedelta(seconds=183))
        with self.assertRaisesRegex(ValueError, '60秒'):
            guard.finish()

    def test_future_stale_wrong_symbol_adjusted_or_missing_evidence_rejected(self):
        variants = [source(self.now + timedelta(seconds=1)), source(self.now - timedelta(minutes=16)),
                    source(self.now, 'sh513100'), dict(source(self.now), adjustment='qfq'),
                    dict(source(self.now), sha256=''), dict(source(self.now), source='untrusted')]
        for evidence in variants:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.prepare(evidence=evidence)
        self.assertFalse((self.home / JOURNAL).exists())

    def test_duplicate_conflicts_bad_ohlc_and_no_overlap_rejected(self):
        variants = [self.new + [dict(self.new[0], volume=999)],
                    [dict(self.new[0], close=99)], [self.new[-1]]]
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.prepare(rows=rows)

    def test_history_insertion_and_missing_overlap_are_rejected(self):
        self.old += [dict(self.old[0], datetime='2026-10-13 14:00:00'),
                     dict(self.old[0], datetime='2026-10-13 15:00:00')]
        with self.assertRaisesRegex(ValueError, '插入'):
            self.prepare(rows=[self.old[0], self.new[-1]])
        with self.assertRaisesRegex(ValueError, '缺失'):
            self.prepare(rows=[self.old[0], self.old[-1]])

    def test_durable_audit_required_before_publication(self):
        guard, _ = self.prepare()
        with patch('web_market_revisions.write_json', side_effect=OSError('synthetic full disk')):
            with self.assertRaisesRegex(ValueError, '持久保存'):
                guard.finish()
        self.assertFalse((self.home / JOURNAL).exists())

    def test_corrupted_audit_is_not_reset(self):
        self.pending()
        path = self.home / JOURNAL
        payload = json.loads(path.read_text('utf-8')); payload['policy'] = 'tampered'
        path.write_text(json.dumps(payload), encoding='utf-8')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.prepare()
        self.assertEqual(path.read_bytes(), before)

    def test_backwards_observation_rejected_after_confirmation(self):
        self.pending()
        guard, _ = self.prepare(self.now + timedelta(seconds=61)); guard.finish()
        with self.assertRaisesRegex(ValueError, '倒退'):
            self.prepare(self.now + timedelta(seconds=120), evidence=source(self.now))


if __name__ == '__main__':
    unittest.main()
