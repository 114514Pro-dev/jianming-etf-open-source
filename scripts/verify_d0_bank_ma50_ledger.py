"""Replay a disposable real SuiteBook and compare reviewed cross50 economics.

Uses the production account, signal and execution paths without adapter hooks.
Only a temporary SQLite account is written; frozen inputs stay read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from verify_d0_bank_ma50 import ROOT, WORKSPACE, DEFAULT_DATA, DEFAULT_OUTPUT, DATA_SHA, read, write, sha

sys.path.insert(0, str(ROOT / 'production'))
import bank_model as model
import trade_book as ledger
from suite_analysis import metrics
from suite_book import SuiteBook

RESEARCH = WORKSPACE / 'outputs/d0-bank-ma50-20261113/results.json'
START, END, CAPITAL = '2018-01-02', '2026-10-30', 100000.
FILL_FIELDS = ('symbol', 'side', 'qty', 'price', 'reference', 'gross', 'fee',
               'cash_change', 'signal_day', 'realized')


def economic_event(event):
    return dict(day=event['day'], kind=event['kind'],
                data={k: event['data'][k] for k in FILL_FIELDS if k in event['data']})


def action_event(event):
    return {k: event[k] for k in ('day', 'kind', 'data')}


def main():
    assert sha(DEFAULT_DATA) == DATA_SHA
    assert ledger.RATE == .0003 and ledger.SLIP == .0002
    frozen = next(r for r in read(RESEARCH)['rows'] if r['code'] == 'cross50')['runs']['base']
    offline = RuntimeError('Ledger verification is offline')
    with patch('socket.socket.connect', side_effect=offline), patch('urllib.request.urlopen', side_effect=offline):
        market = ledger.Market(data=read(DEFAULT_DATA))
        with tempfile.TemporaryDirectory(prefix='d0_ma50_production_verify_') as folder:
            book = SuiteBook(Path(folder))
            state = book.create('Disposable native D0 verification', CAPITAL, START, market, 'D0')
            state = book.advance(state['id'], market, END)
            events = list(reversed(book.events(state['id'])))
    fills = [economic_event(e) for e in events if e['kind'] in ('策略成交', '模拟成交')]
    assert fills == [economic_event(e) for e in frozen['fills']], 'daily native fills differ'
    assert len(state['curve']) == len(frozen['curve'])
    for actual, expected in zip(state['curve'], frozen['curve']):
        assert actual == {k: expected[k] for k in actual}, ('native curve differs', actual['day'])
    actual_metrics = metrics(state['curve'], CAPITAL)
    assert actual_metrics == frozen['canonical_metrics'], 'native financial metrics differ'
    for key, value in (('cash', frozen['final_cash']), ('positions', frozen['final_positions']),
                       ('fees', frozen['fees']), ('dividends', frozen['dividends']),
                       ('receivables', frozen['receivables'])):
        assert state[key] == value, ('native final state differs', key)
    dividends = [action_event(e) for e in events if e['kind'] in ('应收分红', '分红到账')]
    actions = [action_event(e) for e in events if e['kind'] == '份额折算']
    assert dividends == frozen['dividend_events'], 'native dividend accounting differs'
    assert actions == frozen['corporate_action_events'], 'native corporate actions differ'
    output = dict(schema='d0.bank-ma50.native-ledger-parity.v1', status='passed',
        checked_at=datetime.now(timezone.utc).isoformat(), start=START, end=END,
        capital=CAPITAL, metrics=actual_metrics, daily_points=len(state['curve']), fills=len(fills),
        dividend_events=len(dividends), corporate_action_events=len(actions),
        curve_and_fills_exact=True, final_economic_state_exact=True,
        data_sha256=DATA_SHA, research_sha256=sha(RESEARCH),
        spec_hash=model.digest(model.spec('D0')), verifier_sha256=sha(__file__),
        source_hashes={p.name: sha(p) for p in sorted((ROOT/'production').glob('*.py'))},
        costs=dict(commission_rate=ledger.RATE, slippage=ledger.SLIP, minimum_fee=5),
        terminal_liquidation=False)
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    write(DEFAULT_OUTPUT / 'native_ledger_validation.json', output)
    write(DEFAULT_OUTPUT / 'native_ledger_evidence.json', dict(curve=state['curve'], fills=fills,
        dividends=dividends, corporate_actions=actions, final_positions=state['positions']))
    print(json.dumps({k: output[k] for k in ('status', 'metrics', 'daily_points', 'fills',
                                          'curve_and_fills_exact', 'final_economic_state_exact')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
