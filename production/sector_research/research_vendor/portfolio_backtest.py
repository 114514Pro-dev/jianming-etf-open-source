"""Frozen price-volume allocation experiment; offline only, no account writes.

Only date, score and trix_long are read from feature rows for allocation.
Outcome labels and probability estimates never enter portfolio decisions.
"""
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import bisect
import json
import statistics
from . import legacy_engine as legacy

ROOT = Path(__file__).resolve().parent
MODELS = ['HOLD', 'INDEPENDENT_TRIX', 'SHARED20', 'SCORE', 'MATCH_EQUAL']
D, money, fee, fill = legacy.D, legacy.money, legacy.fee, legacy.fill
read, write, sha = legacy.read, legacy.write, legacy.sha


def allocation(rows, codes, model):
    """Return Decimal targets; ranking score is explicitly not a probability."""
    eligible = [c for c in codes if rows[c]['trix_long']]
    score_weights = {c: D('.2') * D(rows[c]['score']) / D(100)
                     if c in eligible else D(0) for c in codes}
    score_total = sum(score_weights.values(), D(0))
    if score_total > 1:
        score_weights = {c: w / score_total for c, w in score_weights.items()}
    score_total = sum(score_weights.values(), D(0))
    if model == 'SCORE':
        weights = score_weights.copy()
    elif model == 'MATCH_EQUAL':
        weights = {c: score_total / len(eligible) if c in eligible else D(0)
                   for c in codes}
    elif model == 'SHARED20':
        weights = {c: min(D(1) / len(eligible), D('.2')) if c in eligible else D(0)
                   for c in codes}
    else:
        raise ValueError(model)
    assert all(D(0) <= w <= D('.2') + D('1e-24') for w in weights.values())
    assert sum(weights.values(), D(0)) <= D(1) + D('1e-24')
    if model == 'MATCH_EQUAL':
        assert abs(sum(weights.values(), D(0)) - score_total) < D('1e-24')
    return eligible, weights, score_weights


def affordable_lots(price, budget, rate, minimum):
    qty = max(0, int((budget / (price * 100)).to_integral_value(rounding=ROUND_FLOOR)) * 100)
    while qty and money(price * qty) + fee(money(price * qty), rate, minimum) > budget:
        qty -= 100
    return qty


def allocate_buys(wants, prices, cash, rate, minimum):
    """Simultaneous proportional budgets, including fees; no leftover recycling."""
    costs = {c: money(prices[c] * q) + fee(money(prices[c] * q), rate, minimum)
             for c, q in wants.items() if q > 0}
    total = sum(costs.values(), D(0))
    budgets = {c: cash * n / total if total > cash else n for c, n in costs.items()}
    qty = {c: min(wants[c], affordable_lots(prices[c], budgets[c], rate, minimum))
           for c in costs}
    assert sum((money(prices[c] * q) + fee(money(prices[c] * q), rate, minimum)
                for c, q in qty.items() if q), D(0)) <= cash
    return qty, costs, budgets


def enrich_metrics(curve, trades, capital):
    out = legacy.metrics(curve, trades, capital)
    out.update({
        'maximum_single_security_weight': max(x['max_weight'] for x in curve),
        'average_max_security_weight': statistics.mean(x['max_weight'] for x in curve),
        'maximum_top3_security_weight': max(x['top3_weight'] for x in curve),
        'average_top3_security_weight': statistics.mean(x['top3_weight'] for x in curve),
        'average_invested_sectors': statistics.mean(x['invested_sleeves'] for x in curve),
        'all_cash_market_days': sum(x['invested_sleeves'] == 0 for x in curve),
        'rebalance_days': sum(bool(x.get('rebalanced')) for x in curve),
        'actual_single_weight_above_20pct_days': sum(x['max_weight'] > .2 + 1e-12 for x in curve),
    })
    return out


class PortfolioStudy:
    def __init__(self, root=ROOT, market=None, features=None, protocol=None):
        self.root = Path(root)
        self.protocol = protocol if protocol is not None else read(self.root / 'protocol.json')
        self.market = market if market is not None else read(self.root / 'data/market.json')
        self.features = features if features is not None else read(self.root / 'output/features.json')
        self.calendar = self.market['calendar']
        self.codes = self.protocol['codes']
        self.assets = self.market['assets']
        self.bars = {c: {b['date']: b for b in self.assets[c]['bars']} for c in self.codes}
        self.rows = {c: {r['date']: {'date': r['date'], 'score': r['score'],
                                  'trix_long': r['trix_long']} for r in self.features['assets'][c]['rows']}
                     for c in self.codes}
        self.old = legacy.Study.__new__(legacy.Study)
        self.old.root = self.root
        self.old.protocol = read(self.root / 'legacy_protocol.json')
        self.old.market = self.market
        self.old.calendar = self.calendar
        self.old.assets = self.assets
        self.old.cache = {}

    def run(self, model, start=None, end=None, commission_rate=.0003,
            minimum_commission=5, slippage_rate=.0002,
            minimum_slippage_ticks=1, delay=1, capital=None):
        start = start or self.protocol['period']['start']
        end = end or self.protocol['period']['end']
        capital = self.protocol['total_capital'] if capital is None else capital
        params = dict(start=start, end=end, commission_rate=commission_rate,
                      minimum_commission=minimum_commission, slippage_rate=slippage_rate,
                      minimum_slippage_ticks=minimum_slippage_ticks, delay=delay)
        if model in ['HOLD', 'INDEPENDENT_TRIX']:
            return self.run_independent(model, capital=capital, **params)
        return self.run_shared(model, capital=capital, **params)

    def run_independent(self, model, capital, **params):
        old_model = 'TRIX' if model == 'INDEPENDENT_TRIX' else 'HOLD'
        sleeves = [self.old.run(c, old_model, capital=capital / len(self.codes), **params)
                   for c in self.codes]
        p = legacy.portfolio(sleeves, capital)
        p['model'] = model
        for i, r in enumerate(p['curve']):
            r['positions'] = {}
            for c, account in zip(self.codes, sleeves):
                q = account['curve'][i]
                r['positions'][c] = {k: q[k] for k in ['shares', 'security_value',
                    'dividend_receivable', 'mark_close', 'mark_source_date', 'stale_mark']}
                r['positions'][c]['weight'] = q['security_value'] / r['equity']
                r['positions'][c]['sleeve_cash'] = q['cash']
            weights = sorted([x['weight'] for x in r['positions'].values()], reverse=True)
            r['max_weight'] = weights[0]
            r['top3_weight'] = sum(weights[:3])
            r['rebalanced'] = False
        p['metrics'] = enrich_metrics(p['curve'], p['trades'], capital)
        p['metrics']['blocked_orders'] = sum(a['metrics']['blocked_orders'] for a in sleeves)
        p['metrics']['dividend_received'] = sum(a['metrics']['dividend_received'] for a in sleeves)
        p['corporate_events'] = sorted([{**e, 'code': a['code']} for a in sleeves
                                       for e in a['corporate_events']],
                                      key=lambda x: (x['date'], self.codes.index(x['code'])))
        p['decisions'] = []
        p['parameters'] = {**params, 'capital': capital}
        p['shared_capital'] = False
        return {'portfolio': p, 'sleeves': sleeves}

    def run_shared(self, model, start, end, capital, commission_rate,
                   minimum_commission, slippage_rate, minimum_slippage_ticks, delay):
        cal, codes = self.calendar, self.codes
        lo, hi = bisect.bisect_left(cal, start), bisect.bisect_right(cal, end)
        assert cal[lo] == start and cal[hi - 1] == end and delay in [1, 2]
        assert lo >= delay + 1
        initial, cash = D(capital), D(capital)
        shares = {c: 0 for c in codes}
        marks, mark_dates = {}, {}
        for c in codes:
            prior_bars = [b for b in self.assets[c]['bars'] if b['date'] < start]
            assert prior_bars
            marks[c], mark_dates[c] = D(prior_bars[-1]['close']), prior_bars[-1]['date']
        entitlements, receivables = {c: {} for c in codes}, {c: {} for c in codes}
        asset_cashflow = {c: D(0) for c in codes}
        curve, trades, events, decisions = [], [], [], []
        nav_history, blocked, initialized = {}, 0, False
        last_targets = {c: D(0) for c in codes}

        def event(c, day, e, kind, **kw):
            events.append({'date': day, 'event_date': e['pay_date'] if kind == 'dividend_payment'
                           else e['record_date'] if kind == 'dividend_registration' else e['ex_date'],
                           'code': c, 'event_id': e['event_id'], 'type': kind, **kw})

        def trade(c, day, b, side, qty, decision, trigger, target):
            nonlocal cash
            price = fill(b['open'], side, slippage_rate, minimum_slippage_ticks)
            assert price > 0 and qty > 0 and qty % 100 == 0
            amount = money(price * qty)
            commission = fee(amount, commission_rate, minimum_commission)
            before, old = cash, shares[c]
            change = -(amount + commission) if side == 'BUY' else amount - commission
            cash = money(cash + change)
            asset_cashflow[c] = money(asset_cashflow[c] + change)
            shares[c] += qty if side == 'BUY' else -qty
            assert cash >= 0 and shares[c] >= 0
            trades.append({'date': day, 'code': c, 'side': side, 'shares': qty,
                'raw_open': b['open'], 'fill': float(price), 'notional': float(amount),
                'commission': float(commission),
                'slippage_cost': float(D(qty) * abs(price - D(b['open']))),
                'cash_before': float(before), 'cash_after': float(cash),
                'shares_before': old, 'shares_after': shares[c],
                'decision_date': decision, 'signal_observation_date': decision,
                'trigger_reason': trigger, 'target_weight': float(target),
                'source_day_amount': b['amount_cny'],
                'participation_day_amount': float(amount / D(b['amount_cny'])),
                'fill_outside_recorded_range': price < D(b['low']) or price > D(b['high'])})

        for i in range(lo, hi):
            day, prior, decision = cal[i], cal[i - 1], cal[i - delay]
            rows = {c: self.rows[c][decision] for c in codes}
            prior_rows = {c: self.rows[c][cal[i - delay - 1]] for c in codes}
            eligible, weights, score_weights = allocation(rows, codes, model)
            prior_eligible = [c for c in codes if prior_rows[c]['trix_long']]
            reasons = []
            allowed = i - lo >= delay - 1
            if allowed:
                if not initialized:
                    reasons.append('initialization')
                if eligible != prior_eligible:
                    reasons.append('eligible_set_changed')
                if date.fromisoformat(decision).weekday() == 4:
                    reasons.append('friday_close_review')
            rebalance = bool(reasons)
            for c in codes:
                for e in self.assets[c]['dividends']:
                    eid = e['event_id']
                    if prior < e['ex_date'] <= day:
                        qty = entitlements[c].get(eid, 0)
                        amount = money(D(qty) * D(e['cash_per_share']))
                        if amount:
                            receivables[c][eid] = amount
                            event(c, day, e, 'dividend_receivable', eligible_shares=qty,
                                  cash_per_share=e['cash_per_share'], amount=float(amount))
                        marks[c] -= D(e['cash_per_share'])
                        assert marks[c] > 0
                for e in self.assets[c]['splits']:
                    if prior < e['ex_date'] <= day:
                        old = shares[c]
                        new = D(old) * D(e['ratio'])
                        assert new == new.to_integral_value()
                        shares[c] = int(new)
                        marks[c] /= D(e['ratio'])
                        if old:
                            event(c, day, e, 'split', before=old, after=shares[c], ratio=e['ratio'])
                for e in self.assets[c]['dividends']:
                    eid = e['event_id']
                    if prior < e['pay_date'] < day and eid in receivables[c]:
                        amount = receivables[c].pop(eid)
                        cash = money(cash + amount)
                        asset_cashflow[c] = money(asset_cashflow[c] + amount)
                        event(c, day, e, 'dividend_payment', amount=float(amount))
            if rebalance:
                known_nav = nav_history.get(decision, initial)
                assert known_nav > 0
                target_shares, buy_prices, missing = {}, {}, []
                for c in codes:
                    b = self.bars[c].get(day)
                    if b is None or b['open'] <= 0 or b['amount_cny'] <= 0:
                        missing.append(c)
                        target_shares[c] = shares[c]
                        blocked += 1
                        continue
                    buy_prices[c] = fill(b['open'], 'BUY', slippage_rate, minimum_slippage_ticks)
                    target_shares[c] = int((known_nav * weights[c] / (buy_prices[c] * 100))
                                           .to_integral_value(rounding=ROUND_FLOOR)) * 100
                before_cash = cash
                for c in codes:
                    if c not in missing and shares[c] > target_shares[c]:
                        trade(c, day, self.bars[c][day], 'SELL', shares[c] - target_shares[c],
                              decision, reasons, weights[c])
                after_sells_cash = cash
                wants = {c: target_shares[c] - shares[c] for c in codes
                         if c not in missing and target_shares[c] > shares[c]}
                quantities, needs, budgets = allocate_buys(wants, buy_prices, cash,
                                                          commission_rate, minimum_commission)
                for c in codes:
                    if quantities.get(c, 0):
                        trade(c, day, self.bars[c][day], 'BUY', quantities[c],
                              decision, reasons, weights[c])
                decisions.append({'execution_date': day, 'decision_date': decision,
                    'trigger_reason': reasons, 'nav_known_at_decision': float(known_nav),
                    'eligible': eligible, 'scores': {c: rows[c]['score'] for c in codes},
                    'target_weights': {c: float(w) for c, w in weights.items()},
                    'score_targets': {c: float(w) for c, w in score_weights.items()},
                    'target_total_weight': float(sum(weights.values(), D(0))),
                    'score_total_weight': float(sum(score_weights.values(), D(0))),
                    'target_shares': target_shares, 'missing_execution_quotes': missing,
                    'cash_before_sells': float(before_cash), 'cash_after_sells': float(after_sells_cash),
                    'cash_after_buys': float(cash),
                    'buy_allocations': {c: {'desired_qty': wants[c], 'desired_cost': float(needs[c]),
                        'allocated_budget': float(budgets[c]), 'qty': quantities[c],
                        'price': float(buy_prices[c])} for c in wants}})
                last_targets = weights.copy()
                initialized = True
            for c in codes:
                for e in self.assets[c]['dividends']:
                    eid = e['event_id']
                    if e['record_date'] == day:
                        entitlements[c][eid] = shares[c]
                        if shares[c]:
                            event(c, day, e, 'dividend_registration', eligible_shares=shares[c])
                    if e['pay_date'] == day and eid in receivables[c]:
                        amount = receivables[c].pop(eid)
                        cash = money(cash + amount)
                        asset_cashflow[c] = money(asset_cashflow[c] + amount)
                        event(c, day, e, 'dividend_payment', amount=float(amount))
                b = self.bars[c].get(day)
                if b:
                    marks[c], mark_dates[c] = D(b['close']), day
            assert cash >= 0 and all(q >= 0 and q % 100 == 0 for q in shares.values())
            values = {c: money(D(shares[c]) * marks[c]) for c in codes}
            recv = {c: sum(receivables[c].values(), D(0)) for c in codes}
            mv, rv = sum(values.values(), D(0)), sum(recv.values(), D(0))
            equity = money(cash + mv + rv)
            nav_history[day] = equity
            position_weights = sorted([float(values[c] / equity) for c in codes], reverse=True)
            curve.append({'date': day, 'equity': float(equity), 'cash': float(cash),
                'security_value': float(mv), 'dividend_receivable': float(rv),
                'exposure': float(mv / equity), 'invested_sleeves': sum(q > 0 for q in shares.values()),
                'max_weight': position_weights[0], 'top3_weight': sum(position_weights[:3]),
                'stale_mark': any(mark_dates[c] != day for c in codes),
                'decision_date': decision, 'rebalanced': rebalance,
                'target_weights': {c: float(w) for c, w in last_targets.items()},
                'positions': {c: {'shares': shares[c], 'security_value': float(values[c]),
                    'dividend_receivable': float(recv[c]), 'mark_close': float(marks[c]),
                    'mark_source_date': mark_dates[c], 'stale_mark': mark_dates[c] != day,
                    'weight': float(values[c] / equity), 'net_cashflow': float(asset_cashflow[c]),
                    'profit': float(money(asset_cashflow[c] + values[c] + recv[c]))} for c in codes}})
        metrics = enrich_metrics(curve, trades, capital)
        metrics['blocked_orders'] = blocked
        metrics['dividend_received'] = sum(e['amount'] for e in events if e['type'] == 'dividend_payment')
        contribution = [{'code': c, 'sector': self.assets[c]['identity']['sector'],
            'profit': curve[-1]['positions'][c]['profit'],
            'contribution_to_initial_total': curve[-1]['positions'][c]['profit'] / capital,
            'final_security_weight': curve[-1]['positions'][c]['weight']} for c in codes]
        assert abs(sum(D(x['profit']) for x in contribution) - (D(curve[-1]['equity']) - initial)) < D('.005')
        p = {'model': model, 'start': start, 'end': end, 'shared_capital': True,
             'parameters': {'start': start, 'end': end, 'capital': capital,
                 'commission_rate': commission_rate, 'minimum_commission': minimum_commission,
                 'slippage_rate': slippage_rate, 'minimum_slippage_ticks': minimum_slippage_ticks,
                 'delay': delay}, 'metrics': metrics, 'curve': curve, 'trades': trades,
             'corporate_events': events, 'decisions': decisions, 'contributions': contribution,
             'years': legacy.yearly(curve, capital)}
        return {'portfolio': p}


def experiment(root=ROOT):
    root = Path(root)
    receipt = read(root / 'freeze_receipt.json')
    for rel, h in receipt['inputs'].items():
        assert sha(root / rel) == h, f'Frozen source changed: {rel}'
    output = root / 'output/portfolio_results.json'
    assert not output.exists(), 'Preserve existing result before rerunning.'
    s = PortfolioStudy(root)
    started = datetime.now(timezone.utc).isoformat()
    setups = [('primary', {}), ('double_cost', s.protocol['experiments']['double_cost_parameters']),
              ('extra_execution_day', {'delay': 2})]
    setups += [('period/' + a, {'start': a, 'end': b}) for a, b in s.protocol['fixed_periods']]
    groups = []
    for group, params in setups:
        for model in MODELS:
            result = s.run(model, **params)
            groups.append({'case_id': group + '/' + model, 'group': group, 'model': model,
                           'parameters': result['portfolio']['parameters'], **result})
    for group, _ in setups:
        score = next(g['portfolio']['decisions'] for g in groups if g['case_id'] == group + '/SCORE')
        equal = next(g['portfolio']['decisions'] for g in groups if g['case_id'] == group + '/MATCH_EQUAL')
        assert len(score) == len(equal)
        for a, b in zip(score, equal):
            assert a['execution_date'] == b['execution_date'] and a['decision_date'] == b['decision_date']
            assert abs(a['target_total_weight'] - b['target_total_weight']) < 1e-14
            assert a['eligible'] == b['eligible']
    assert len(groups) == 25
    result = {'schema': 'ten-sector-score-portfolios-v1', 'study': s.protocol['study'],
              'started_utc': started, 'finished_utc': datetime.now(timezone.utc).isoformat(),
              'input_hashes': {**receipt['inputs'], 'output/features.json': sha(root / 'output/features.json')},
              'portfolio_cases': len(groups),
              'independent_sleeve_cases': sum(len(g.get('sleeves', [])) for g in groups),
              'shared_account_cases': sum(g['portfolio']['shared_capital'] for g in groups),
              'groups': groups}
    write(output, result)
    print(json.dumps({'output': str(output), 'portfolio_cases': len(groups),
                      'primary': {g['model']: g['portfolio']['metrics'] for g in groups
                                  if g['group'] == 'primary'}}, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    experiment()
