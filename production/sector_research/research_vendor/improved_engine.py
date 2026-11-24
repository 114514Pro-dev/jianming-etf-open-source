"""Fixed A/B execution experiment. Scores and corporate actions remain frozen.

No labels or probability fields enter the inherited date/score/TRIX projection.
Decision-date values are retained as Decimal, including for the B weight band.
"""
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_FLOOR
import bisect
import sys

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / 'frozen'
from . import portfolio_backtest as original

D, money, fee, fill = original.D, original.money, original.fee, original.fill
read, write, sha = original.read, original.write, original.sha
NEW_MODELS = ['A_SCORE', 'A_EQUAL', 'B_SCORE', 'B_EQUAL']
CONTROLS = ['HOLD', 'INDEPENDENT_TRIX', 'SCORE', 'MATCH_EQUAL']


def weight_band_passes(current_weight, target_weight, band):
    return abs(D(current_weight) - D(target_weight)) >= D(band)


def optional_amount_passes(amount, minimum):
    return D(amount) >= D(minimum)


class ImprovedStudy(original.PortfolioStudy):
    def __init__(self, root=ROOT, market=None, features=None, protocol=None):
        self.experiment_root = Path(root)
        self.improvement_protocol = protocol if protocol is not None else read(self.experiment_root / 'protocol.json')
        inherited_protocol = read(self.experiment_root / 'frozen/protocol.json')
        for key in ['codes', 'period', 'total_capital']:
            inherited_protocol[key] = self.improvement_protocol[key]
        super().__init__(self.experiment_root / 'frozen', market=market, features=features,
                         protocol=inherited_protocol)

    def run(self, model, start=None, end=None, commission_rate=.0003,
            minimum_commission=5, slippage_rate=.0002,
            minimum_slippage_ticks=1, delay=1, capital=None):
        if model in CONTROLS:
            return super().run(model, start=start, end=end, commission_rate=commission_rate,
                               minimum_commission=minimum_commission, slippage_rate=slippage_rate,
                               minimum_slippage_ticks=minimum_slippage_ticks, delay=delay, capital=capital)
        assert model in NEW_MODELS, model
        return self.run_improved(model,
            start=start or self.improvement_protocol['period']['start'],
            end=end or self.improvement_protocol['period']['end'],
            commission_rate=commission_rate, minimum_commission=minimum_commission,
            slippage_rate=slippage_rate, minimum_slippage_ticks=minimum_slippage_ticks,
            delay=delay, capital=self.improvement_protocol['total_capital'] if capital is None else capital)

    def run_improved(self, model, start, end, commission_rate, minimum_commission,
                     slippage_rate, minimum_slippage_ticks, delay, capital):
        cal, codes = self.calendar, self.codes
        lo, hi = bisect.bisect_left(cal, start), bisect.bisect_right(cal, end)
        assert cal[lo] == start and cal[hi - 1] == end and delay in [1, 2]
        assert lo >= delay + 1
        use_band = model.startswith('B_')
        weight_model = 'SCORE' if model.endswith('_SCORE') else 'MATCH_EQUAL'
        band = D(self.improvement_protocol['execution_B']['weight_band'])
        minimum_optional = D(self.improvement_protocol['execution_B']['minimum_optional_notional'])
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
        # Retain exact values, not float exports converted back into Decimal.
        history, blocked, initialized = {}, 0, False
        last_targets = {c: D(0) for c in codes}

        def event(c, day, e, kind, **kw):
            events.append({'date': day, 'event_date': e['pay_date'] if kind == 'dividend_payment'
                           else e['record_date'] if kind == 'dividend_registration' else e['ex_date'],
                           'code': c, 'event_id': e['event_id'], 'type': kind, **kw})

        def trade(c, day, b, side, qty, decision, trigger, target, action, optional, known_weight):
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
            record = {'date': day, 'code': c, 'side': side, 'shares': qty,
                'raw_open': b['open'], 'fill': float(price), 'notional': float(amount),
                'commission': float(commission),
                'slippage_cost': float(D(qty) * abs(price - D(b['open']))),
                'cash_before': float(before), 'cash_after': float(cash),
                'shares_before': old, 'shares_after': shares[c],
                'decision_date': decision, 'signal_observation_date': decision,
                'trigger_reason': trigger, 'target_weight': float(target),
                'source_day_amount': b['amount_cny'],
                'participation_day_amount': float(amount / D(b['amount_cny'])),
                'fill_outside_recorded_range': price < D(b['low']) or price > D(b['high']),
                'action_type': action, 'optional_existing_resize': optional,
                'known_decision_weight': float(known_weight)}
            trades.append(record)
            return record

        for i in range(lo, hi):
            day, prior, decision = cal[i], cal[i - 1], cal[i - delay]
            rows = {c: self.rows[c][decision] for c in codes}
            previous_rows = {c: self.rows[c][cal[i - delay - 1]] for c in codes}
            eligible, weights, score_weights = original.allocation(rows, codes, weight_model)
            previous_eligible = [c for c in codes if previous_rows[c]['trix_long']]
            entrants = [c for c in eligible if c not in previous_eligible]
            allowed = i - lo >= delay - 1
            initialization = allowed and not initialized
            friday = date.fromisoformat(decision).weekday() == 4
            full_review = allowed and (initialization or friday)
            reasons = []
            if initialization:
                reasons.append('initialization')
            if allowed and friday:
                reasons.append('friday_close_review')
            if allowed and entrants:
                reasons.append('new_eligibility')

            # Rights, splits, and prior payments follow the original engine exactly.
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

            known = history.get(decision)
            known_nav = known['equity'] if known else initial
            known_values = known['values'] if known else {c: D(0) for c in codes}
            known_shares = known['shares'] if known else {c: 0 for c in codes}
            known_weights = {c: known_values[c] / known_nav for c in codes}
            assert known_nav > 0
            before_shares = shares.copy()
            mandatory_exits = [c for c in codes if allowed and c not in eligible and shares[c] > 0]
            if mandatory_exits:
                reasons.append('mandatory_ineligible_exit')
            plans, target_shares, missing = {}, shares.copy(), []
            buy_prices, sell_orders, wants = {}, {}, {}
            before_cash = cash

            for c in codes:
                target = weights[c]
                active = False
                optional = False
                if not allowed:
                    action = 'waiting_for_execution_delay'
                elif c not in eligible:
                    action = 'mandatory_ineligible_exit' if shares[c] else 'empty_ineligible'
                    active = shares[c] > 0
                elif full_review:
                    if not shares[c]:
                        action = 'initial_entry' if initialization else 'scheduled_zero_position_entry'
                    elif initialization:
                        action = 'initial_existing_review'
                    else:
                        action = 'scheduled_existing_resize'
                        optional = True
                    active = True
                elif c in entrants and shares[c] == 0:
                    action = 'new_eligible_entry'
                    active = True
                else:
                    action = 'keep_eligible_incumbent' if shares[c] else 'wait_for_next_entry_review'
                plan = {'action_type': action, 'active_review': active,
                    'optional_existing_resize': optional, 'gate_applies': optional and use_band,
                    'shares_before_execution': before_shares[c],
                    'known_decision_shares': known_shares[c],
                    'known_decision_weight': float(known_weights[c]),
                    'known_decision_weight_decimal': str(known_weights[c]),
                    'target_weight': float(target), 'target_weight_decimal': str(target),
                    'absolute_weight_gap': float(abs(known_weights[c] - target)),
                    'absolute_weight_gap_decimal': str(abs(known_weights[c] - target)),
                    'candidate_target_shares': shares[c], 'requested_side': None,
                    'requested_qty': 0, 'requested_notional': 0.,
                    'band_pass': None, 'notional_pass': None,
                    'rejection_reason': None, 'budgeted_qty': 0,
                    'budgeted_notional': 0., 'executed_qty': 0,
                    'executed_notional': 0., 'executed_commission': 0.}
                plans[c] = plan
                if not active:
                    continue
                last_targets[c] = target
                b = self.bars[c].get(day)
                if b is None or b['open'] <= 0 or b['amount_cny'] <= 0:
                    plan['candidate_target_shares'] = 0 if action == 'mandatory_ineligible_exit' else None
                    plan['rejection_reason'] = 'missing_execution_quote'
                    missing.append(c)
                    blocked += 1
                    continue
                buy_price = fill(b['open'], 'BUY', slippage_rate, minimum_slippage_ticks)
                buy_prices[c] = buy_price
                desired = 0 if action == 'mandatory_ineligible_exit' else int(
                    (known_nav * target / (buy_price * 100)).to_integral_value(rounding=ROUND_FLOOR)) * 100
                plan['candidate_target_shares'] = desired
                target_shares[c] = desired
                if desired == shares[c]:
                    plan['rejection_reason'] = 'already_at_rounded_target'
                    continue
                side = 'BUY' if desired > shares[c] else 'SELL'
                qty = abs(desired - shares[c])
                execution_price = fill(b['open'], side, slippage_rate, minimum_slippage_ticks)
                requested_amount = money(execution_price * qty)
                plan.update({'requested_side': side, 'requested_qty': qty,
                             'requested_notional': float(requested_amount)})
                if optional and use_band:
                    plan['band_pass'] = weight_band_passes(known_weights[c], target, band)
                    if not plan['band_pass']:
                        plan['rejection_reason'] = 'weight_gap_below_band'
                        continue
                    # Buy notional is deliberately NOT gated before proportional budgeting.
                    if side == 'SELL':
                        plan['notional_pass'] = optional_amount_passes(requested_amount, minimum_optional)
                        if not plan['notional_pass']:
                            plan['rejection_reason'] = 'sell_notional_below_minimum'
                            continue
                if side == 'SELL':
                    sell_orders[c] = qty
                else:
                    wants[c] = qty

            # Allowed sells determine available cash; rejected sells raise no cash.
            for c in codes:
                if c in sell_orders:
                    p = plans[c]
                    t = trade(c, day, self.bars[c][day], 'SELL', sell_orders[c], decision,
                              reasons, weights[c], p['action_type'], p['optional_existing_resize'], known_weights[c])
                    p.update({'executed_qty': t['shares'], 'executed_notional': t['notional'],
                              'executed_commission': t['commission']})
            after_sells_cash = cash
            quantities, needs, budgets = original.allocate_buys(wants, buy_prices, cash,
                                                                commission_rate, minimum_commission)
            # Compute all quantities first; cancelled orders never donate budget to another buy.
            final_buys = {}
            for c in codes:
                if c not in wants:
                    continue
                p, qty = plans[c], quantities[c]
                amount = money(buy_prices[c] * qty)
                p.update({'budgeted_qty': qty, 'budgeted_notional': float(amount)})
                if p['gate_applies']:
                    p['notional_pass'] = optional_amount_passes(amount, minimum_optional)
                    if not p['notional_pass']:
                        p['rejection_reason'] = 'budgeted_buy_notional_below_minimum'
                        continue
                if not qty:
                    p['rejection_reason'] = 'insufficient_cash_for_lot'
                    continue
                final_buys[c] = qty
            for c in codes:
                if c in final_buys:
                    p = plans[c]
                    t = trade(c, day, self.bars[c][day], 'BUY', final_buys[c], decision,
                              reasons, weights[c], p['action_type'], p['optional_existing_resize'], known_weights[c])
                    p.update({'executed_qty': t['shares'], 'executed_notional': t['notional'],
                              'executed_commission': t['commission']})

            if allowed:
                initialized = True
            decision_record = {'execution_date': day, 'decision_date': decision,
                'decision_kind': 'waiting' if not allowed else 'full_scheduled_review' if full_review else 'entries_and_exits_only',
                'allowed': allowed, 'initialization': initialization, 'decision_is_friday': friday,
                'full_review': full_review, 'trigger_reason': reasons,
                'nav_known_at_decision': float(known_nav), 'nav_known_at_decision_decimal': str(known_nav),
                'known_weights': {c: float(w) for c, w in known_weights.items()},
                'known_weights_decimal': {c: str(w) for c, w in known_weights.items()},
                'known_security_values_decimal': {c: str(known_values[c]) for c in codes},
                'known_shares': known_shares.copy(), 'shares_before_execution': before_shares,
                'eligible': eligible, 'previous_eligible': previous_eligible,
                'newly_eligible': entrants, 'mandatory_exits': mandatory_exits,
                'scores': {c: rows[c]['score'] for c in codes},
                'target_weights': {c: float(w) for c, w in weights.items()},
                'score_targets': {c: float(w) for c, w in score_weights.items()},
                'target_total_weight': float(sum(weights.values(), D(0))),
                'score_total_weight': float(sum(score_weights.values(), D(0))),
                'target_shares': target_shares, 'missing_execution_quotes': missing,
                'cash_before_sells': float(before_cash), 'cash_after_sells': float(after_sells_cash),
                'cash_after_buys': float(cash), 'actions': plans,
                'buy_allocations': {c: {'desired_qty': wants[c], 'desired_cost': float(needs[c]),
                    'allocated_budget': float(budgets[c]), 'budgeted_qty': quantities[c],
                    'qty': final_buys.get(c, 0), 'price': float(buy_prices[c]),
                    'final_notional': float(money(buy_prices[c] * final_buys.get(c, 0))),
                    'rejection_reason': plans[c]['rejection_reason']} for c in wants}}
            decisions.append(decision_record)

            # Registration and today's payment take place after all opening trades.
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
            history[day] = {'equity': equity, 'values': values.copy(), 'shares': shares.copy()}
            ordered_weights = sorted([float(values[c] / equity) for c in codes], reverse=True)
            rebalance_attempted = any(p['active_review'] for p in plans.values())
            curve.append({'date': day, 'equity': float(equity), 'cash': float(cash),
                'security_value': float(mv), 'dividend_receivable': float(rv),
                'exposure': float(mv / equity), 'invested_sleeves': sum(q > 0 for q in shares.values()),
                'max_weight': ordered_weights[0], 'top3_weight': sum(ordered_weights[:3]),
                'stale_mark': any(mark_dates[c] != day for c in codes),
                'decision_date': decision, 'rebalanced': rebalance_attempted,
                'full_review': full_review,
                'target_weights': {c: float(w) for c, w in last_targets.items()},
                'reference_target_weights': {c: float(w) for c, w in weights.items()},
                'positions': {c: {'shares': shares[c], 'security_value': float(values[c]),
                    'dividend_receivable': float(recv[c]), 'mark_close': float(marks[c]),
                    'mark_source_date': mark_dates[c], 'stale_mark': mark_dates[c] != day,
                    'weight': float(values[c] / equity), 'net_cashflow': float(asset_cashflow[c]),
                    'profit': float(money(asset_cashflow[c] + values[c] + recv[c]))} for c in codes}})

        metrics = original.enrich_metrics(curve, trades, capital)
        metrics['blocked_orders'] = blocked
        metrics['dividend_received'] = sum(e['amount'] for e in events if e['type'] == 'dividend_payment')
        rejected = [p for d in decisions for p in d['actions'].values() if p['rejection_reason'] in
                    ['weight_gap_below_band', 'sell_notional_below_minimum', 'budgeted_buy_notional_below_minimum']]
        metrics.update({'daily_decision_records': len(decisions),
            'full_scheduled_review_days': sum(d['full_review'] for d in decisions),
            'actual_trading_days': len({t['date'] for t in trades}),
            'optional_rejected_orders': len(rejected),
            'optional_rejected_weight_band': sum(p['rejection_reason'] == 'weight_gap_below_band' for p in rejected),
            'optional_rejected_sell_notional': sum(p['rejection_reason'] == 'sell_notional_below_minimum' for p in rejected),
            'optional_rejected_budgeted_buy_notional': sum(p['rejection_reason'] == 'budgeted_buy_notional_below_minimum' for p in rejected),
            'executed_existing_resizes': sum(t['optional_existing_resize'] for t in trades)})
        contributions = [{'code': c, 'sector': self.assets[c]['identity']['sector'],
            'profit': curve[-1]['positions'][c]['profit'],
            'contribution_to_initial_total': curve[-1]['positions'][c]['profit'] / capital,
            'final_security_weight': curve[-1]['positions'][c]['weight']} for c in codes]
        assert abs(sum(D(x['profit']) for x in contributions) - (D(curve[-1]['equity']) - initial)) < D('.005')
        p = {'model': model, 'start': start, 'end': end, 'shared_capital': True,
             'parameters': {'start': start, 'end': end, 'capital': capital,
                'commission_rate': commission_rate, 'minimum_commission': minimum_commission,
                'slippage_rate': slippage_rate, 'minimum_slippage_ticks': minimum_slippage_ticks, 'delay': delay,
                'execution_variant': model[0], 'weight_model': weight_model,
                'weight_band': float(band) if use_band else None,
                'minimum_optional_notional': float(minimum_optional) if use_band else None},
             'metrics': metrics, 'curve': curve, 'trades': trades, 'corporate_events': events,
             'decisions': decisions, 'contributions': contributions,
             'years': original.legacy.yearly(curve, capital),
             'decision_schema_notes': [
                 'One decision record every market day, including waiting/no-order days; counts are not trade counts.',
                 'target_weights are original reference targets; rules may intentionally retain drifting positions.',
                 'curve.target_weights are last actively reviewed targets, not actual marked weights.',
                 'candidate_target_shares precede optional gates and cash limits; executed quantities are explicit.',
                 'known weights divide exact Decimal decision-date security values by that date NAV.',
                 'Optional buy amount is tested only after proportional budgeting and integer lots; no reallocation.',
             ]}
        return {'portfolio': p}
