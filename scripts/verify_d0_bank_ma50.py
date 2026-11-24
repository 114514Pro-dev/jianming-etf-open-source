"""Offline production-versus-reviewed-research parity and isolation checks.

The baseline is imported in a separate subprocess so Python module caching
cannot accidentally make an old/new comparison compare the same implementation.
No user accounts or stores are opened. Only frozen public market inputs are read.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
DEFAULT_DATA = WORKSPACE / 'd0-long-comparison-20261102/research/d0_no_gold/inputs/d0-through-20261030.json'
DEFAULT_BASELINE = WORKSPACE / 'd0-bank-relax-20261113/production'
DEFAULT_RESEARCH = WORKSPACE / 'outputs/d0-bank-ma50-20261113/signals.json'
DEFAULT_OUTPUT = WORKSPACE / 'outputs/d0-bank-ma50-implementation-20261115'
DATA_SHA = '64651b4d4a7b078d5cc136af758d1f32935e4a166eec6e6c08dab4900fed575f'
CODES = ('sz159915', 'sh512800', 'sh518880', 'sh511010')
UNCHANGED = ('D5', 'DW', 'F0', 'F10', 'F20', 'L0', 'L10', 'L20')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
        separators=(',', ':')), encoding='utf-8')


def observation_hash(value):
    copied = deepcopy(value)
    copied.pop('market_hash', None)
    return digest(copied)


def truncated(pair, cutoff):
    short = deepcopy(pair)
    for part in short.values():
        part['asof'] = cutoff
        for c in part['bars']:
            part['bars'][c] = [r for r in part['bars'][c] if r['date'] <= cutoff]
        for c in part['split_adjustments']:
            part['split_adjustments'][c] = {d: v for d, v in part['split_adjustments'][c].items() if d <= cutoff}
    return short


def worker(production, data_path, output, current):
    sys.path.insert(0, str(production))
    import bank_model as model
    import d0i_bond_ww as ww
    from trade_book import Market
    pair = read(data_path)
    offline = RuntimeError('Verification is offline')
    with patch('socket.socket.connect', side_effect=offline), patch('urllib.request.urlopen', side_effect=offline):
        market = Market(data=pair)
        legacy = (lambda day: model.legacy_d0_observation(market, day)) if current else (lambda day: market.observation('D0', day))
        result = dict(data_sha256=sha(data_path), specs={}, legacy={}, unchanged={c: {} for c in UNCHANGED}, ww={}, d0={})
        result['specs']['legacy_d0'] = digest(model.legacy_d0_spec() if current else model.spec('D0'))
        result['specs']['D0'] = digest(model.spec('D0'))
        result['specs']['WW'] = digest(ww.spec())
        for code in UNCHANGED:
            result['specs'][code] = digest(model.spec(code))
        full_hashes = {}
        for day in market.dates:
            result['legacy'][day] = observation_hash(legacy(day))
            for code in UNCHANGED:
                if code.startswith('L') and day < '2017-08-03':
                    continue
                result['unchanged'][code][day] = observation_hash(market.observation(code, day))
            result['ww'][day] = observation_hash(ww.observation(market, day))
            if current:
                obs = market.observation('D0', day)
                result['d0'][day] = dict(weights=obs['weights'], bank_gate=obs['bank_gate'],
                    bank_state=obs['bank_state'], bank_long=obs['bank_long'],
                    eligible=obs['dynamic']['sh512800']['eligible'],
                    effective_score=obs['dynamic']['sh512800']['effective_score'],
                    raw_score=obs['dynamic']['sh512800']['score'])
                full_hashes[day] = observation_hash(obs)
        if current:
            # Call order and caller mutation must not alter cached signals.
            for day in reversed(market.dates):
                assert observation_hash(market.observation('D0', day)) == full_hashes[day], ('call order', day)
            last = market.dates[-1]
            altered = market.observation('D0', last)
            altered['weights']['sh512800'] = -123
            altered['bank_gate']['holding_days'] = -123
            assert observation_hash(market.observation('D0', last)) == full_hashes[last], 'cached result is mutable'
            prefix_checks = []
            for cutoff in ('2024-12-25', '2026-10-29'):
                smaller = Market(data=truncated(pair, cutoff))
                for day in smaller.dates:
                    assert observation_hash(smaller.observation('D0', day)) == full_hashes[day], ('future-data prefix', cutoff, day)
                prefix_checks.append(dict(cutoff=cutoff, days=len(smaller.dates), passed=True))
            result['prefix_checks'] = prefix_checks
            result['call_order_and_mutation_checks'] = dict(days=len(market.dates), passed=True)
    write(output, result)


def compare(current, baseline, research):
    assert current['data_sha256'] == baseline['data_sha256'] == DATA_SHA
    checks = []
    for name in ('legacy', 'unchanged', 'ww'):
        assert current[name] == baseline[name], (name, 'prechange behavior differs')
        count = sum(len(v) for v in current[name].values()) if name == 'unchanged' else len(current[name])
        checks.append(dict(test='prechange complete observations retained', component=name, observations=count, passed=True))
    for code in ('legacy_d0', 'WW', *UNCHANGED):
        assert current['specs'][code] == baseline['specs'][code], ('specification changed', code)
    assert current['specs']['D0'] != baseline['specs']['D0'], 'New D0 rule has no changed specification identity'
    checks.append(dict(test='D0 specification updated while legacy and other specifications retained', passed=True))
    targets = research['allocations']['cross50']
    evidence = research['evidence']
    assert set(current['d0']) == set(targets)
    fields = ('holding_days', 'next_eligible', 'bank_eligible', 'reference_held', 'transition')
    changed = 0
    for day, obs in current['d0'].items():
        assert obs['weights'] == targets[day], ('reviewed cross50 targets', day, obs['weights'], targets[day])
        expected = evidence[day]['variants']['cross50']
        gate = obs['bank_gate']
        assert gate['schema'] == 'd0.bank-ma50-k50.v1'
        for field in fields:
            assert gate[field] == expected[field], ('reviewed bank state', day, field, gate[field], expected[field])
        for field in ('relaxed', 'weekly_close', 'ma', 'week_end', 'available'):
            assert gate[field] == evidence[day][field], ('reviewed gate evidence', day, field)
        assert obs['bank_state']['holding_days'] == expected['holding_days'], ('displayed age', day)
        assert bool(obs['bank_state']['next_risk']) == expected['next_eligible'], ('displayed target', day)
        assert obs['eligible'] == expected['bank_eligible']
        assert obs['bank_long'] == expected['next_eligible'] or not evidence[day]['has_bank_bar']
        assert obs['effective_score'] == (obs['raw_score'] if obs['eligible'] else 0.)
        if '2018-01-02' <= day <= '2026-10-30' and targets[day] != research['allocations']['original'][day]:
            changed += 1
    assert changed == 29, ('unexpected changed signal days', changed)
    checks.append(dict(test='new production D0 equals independently audited cross50',
        days=len(targets), changed_main_window_days=changed, passed=True))
    return checks


def main(args):
    if args.worker:
        worker(args.production, args.data, args.output, args.worker == 'current')
        return
    assert sha(args.data) == DATA_SHA
    args.output.mkdir(parents=True, exist_ok=True)
    for kind, production in (('baseline', args.baseline), ('current', args.production)):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', kind,
            '--production', str(production), '--data', str(args.data), '--output', str(args.output / (kind+'.json'))], check=True)
    current, baseline = read(args.output/'current.json'), read(args.output/'baseline.json')
    result = dict(schema='d0.bank-ma50.production-parity.v1', status='passed',
        data_sha256=DATA_SHA, research_sha256=sha(args.research),
        baseline_snapshot_sha256=sha(args.output/'baseline.json'), current_snapshot_sha256=sha(args.output/'current.json'),
        checks=compare(current, baseline, read(args.research)),
        prefix_checks=current['prefix_checks'], call_order_and_mutation_checks=current['call_order_and_mutation_checks'],
        source_hashes={str(p.relative_to(args.production)): sha(p) for p in sorted(args.production.glob('*.py'))},
        verifier_sha256=sha(__file__))
    write(args.output/'parity_validation.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'checks', 'prefix_checks')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', choices=('baseline', 'current'))
    parser.add_argument('--production', type=Path, default=ROOT/'production')
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--research', type=Path, default=DEFAULT_RESEARCH)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    main(parser.parse_args())
