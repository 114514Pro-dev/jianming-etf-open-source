"""Isolated browser fixture for the comparison UI; all returns are synthetic.

Uses the existing guarded, outbound-blocked fixture and real app/ledger/HTTP
integration. Only this optional comparison service is replaced. No market data
is downloaded and no trading commands are created by the comparison.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from unittest.mock import patch

import d0_browser_fixture as fixture

sys.path.insert(0, str(fixture.REPOSITORY / 'production'))
CN = timezone(timedelta(hours=8))


class SyntheticComparisonService:
    def __init__(self, folder, paper, indices):
        self.paper = paper
        self.case = Path(folder).parents[2] / 'comparison-case.json'
        self.thread = None

    def close(self):
        pass

    def snapshot(self, account_id):
        with self.paper._lock:
            raw = deepcopy(self.paper.ledger.snapshot())
        account = raw.get('account') or {}
        now = datetime.now(CN)
        case = json.loads(self.case.read_text('utf8')) if self.case.exists() else {}
        generated = now.isoformat()
        start = account.get('created_at', '2026-10-21T10:00:00+08:00')
        capital = account.get('initial_capital', '100000.00')
        days = ['2026-10-21', '2026-10-22', '2026-10-23', '2026-10-26', '2026-10-27']
        if case.get('single'):
            days = days[:1]
        segment = dict(id='synthetic-initial', capital=capital, starts_at=start,
                       ends_at=None, baseline_at=days[0] + 'T15:00:00+08:00',
                       baseline_equity=capital)
        result = dict(contract_version='d0-performance-comparison-v1', status='available',
                      reason=None, account_id=account_id, account_created_at=start,
                      generated_at=generated, requested_start_at=start,
                      normalization='first_shared_confirmed_close', segments=[segment],
                      notes=['account_reconstructed_from_fills', 'model_native_fees',
                             'index_price_excludes_dividends', 'gaps_not_filled',
                             'independent_live_times'], series=[])
        phases = dict(account='reconstructed_close', market='index_close',
                      chinext='index_close', d0='model_close')
        values = dict(account=[0, .004, -.003, .012, .018, .020],
                      market=[0, -.003, -.007, -.002, .004, .006],
                      chinext=[0, .009, -.009, .019, .028, .031],
                      d0=[0, .006, .001, .016, .024, .026])
        for name in phases:
            points = []
            for index, day in enumerate(days):
                missing = case.get('gap') and name == 'account' and index == 2
                at = day + 'T15:00:00+08:00'
                ratio = None if missing else values[name][index]
                points.append(dict(key=name + ':' + day, at=at, date=day,
                    segment_id=segment['id'], equity=None if missing else format(float(capital) * (1 + ratio), '.2f'),
                    return_ratio=ratio, phase=phases[name], source_at=None if missing else at,
                    observed_at=None, break_before=index == 0 or bool(missing)))
            if not case.get('single'):
                moment = now - timedelta(seconds=180 if case.get('stale') else 5)
                at = moment.isoformat()
                points.append(dict(key=name + ':live', at=at, date=moment.date().isoformat(),
                    segment_id=segment['id'], equity=format(float(capital) * (1 + values[name][-1]), '.2f'),
                    return_ratio=values[name][-1], phase='intraday_estimate',
                    source_at=(moment - timedelta(seconds=2)).isoformat(), observed_at=at,
                    break_before=False))
            if case.get('missing_index') and name == 'market':
                points = []
            result['series'].append(dict(id=name, status='available' if points else 'unavailable',
                reason=None if points else 'index_anchor_missing', method='synthetic_browser_fixture',
                as_of=points[-1]['source_at'] if points else None, points=points))
        if case.get('invalid'):
            result['series'][0]['points'][-1]['return_ratio'] = 999
        return result


if __name__ == '__main__':
    with patch('realtime_paper_comparison.D0ComparisonService', SyntheticComparisonService):
        fixture.main()
