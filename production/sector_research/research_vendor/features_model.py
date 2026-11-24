"""Frozen, causal price/turnover ranks and monthly research probability model.

The score is a cross-sectional rank, NOT a probability.  Probabilities have no
role in the allocation engine.  All inputs are local, versioned frozen data.
"""
from pathlib import Path
from decimal import Decimal
import argparse, bisect, hashlib, json, math
import numpy as np
import pandas as pd
from .legacy_engine import Study

ROOT = Path(__file__).resolve().parent
FEATURES = ['trend120', 'relative60', 'flow20', 'volatility60']
SCORE_NAMES = ['trend', 'relative', 'flow', 'risk']
RIDGE = .01

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def economic_series(asset):
    """Daily ex-date reinvested total return; never backward rewrites prices.

    Distributions are per record-date share.  This dataset's record date is
    the immediately preceding actual bar, asserted below.  A split on the
    ex-date changes today's shares; cash remains per previous recorded share.
    Daily reinvestment is a feature convention, not the trading cash ledger.
    """
    bars = asset['bars']
    output = []
    wealth = float(bars[0]['close'])
    for i, bar in enumerate(bars):
        ratio = Decimal(1)
        cash = Decimal(0)
        events = []
        if i:
            previous = bars[i - 1]
            for action in asset['splits']:
                if previous['date'] < action['ex_date'] <= bar['date']:
                    ratio *= Decimal(str(action['ratio']))
                    events.append(action['event_id'])
            for action in asset['dividends']:
                if previous['date'] < action['ex_date'] <= bar['date']:
                    assert action['record_date'] == previous['date'], action
                    cash += Decimal(str(action['cash_per_share']))
                    events.append(action['event_id'])
            gross = (Decimal(str(bar['close'])) * ratio + cash) / Decimal(str(previous['close']))
            wealth *= float(gross)
            daily_return = float(gross - 1)
        else:
            daily_return = None
        output.append({'date': bar['date'], 'economic_tr': wealth,
                       'economic_return': daily_return, 'events': events})
    return output

def holding_label(asset, calendar, decision_date, horizon=20):
    """One share bought next open; cash dividends not reinvested; no costs.

    There are exactly horizon market sessions including entry and terminal.
    Register after entry on record day, accrue only when ex-date occurs.
    An entitlement registered at the terminal close but not yet ex is not
    added to value, since that terminal quote is still cum-dividend.
    """
    i = bisect.bisect_left(calendar, decision_date)
    assert i < len(calendar) and calendar[i] == decision_date
    if i + horizon >= len(calendar):
        return None
    days = calendar[i + 1:i + horizon + 1]
    bars = {bar['date']: bar for bar in asset['bars']}
    if any(day not in bars for day in days):
        return None
    shares = Decimal(0)
    dividend = Decimal(0)
    registered = {}
    events = []
    previous = decision_date
    for day in days:
        for action in asset['dividends']:
            if previous < action['ex_date'] <= day:
                entitlement = registered.get(action['event_id'], Decimal(0))
                amount = entitlement * Decimal(str(action['cash_per_share']))
                dividend += amount
                if amount:
                    events.append({'date': day, 'event_id': action['event_id'],
                                   'kind': 'dividend_accrual', 'registered_shares': float(entitlement), 'amount': float(amount)})
        for action in asset['splits']:
            if previous < action['ex_date'] <= day:
                shares *= Decimal(str(action['ratio']))
                if shares:
                    events.append({'date': day, 'event_id': action['event_id'], 'kind': 'split', 'shares_after': float(shares)})
        if day == days[0]:
            shares = Decimal(1)
        for action in asset['dividends']:
            if action['record_date'] == day:
                registered[action['event_id']] = shares
        previous = day
    entry_price = Decimal(str(bars[days[0]]['open']))
    terminal_value = shares * Decimal(str(bars[days[-1]]['close'])) + dividend
    result = terminal_value / entry_price - 1
    return {'entry_date': days[0], 'end_date': days[-1], 'sessions': horizon,
            'entry_open': float(entry_price), 'terminal_close': float(bars[days[-1]]['close']),
            'terminal_shares': float(shares), 'dividend_cash_and_receivable': float(dividend),
            'return': float(result), 'up': int(result > 0), 'events': events}

def build_features(market, index_data, data_as_of='2026-09-30'):
    assets = market['assets']
    codes = list(assets)
    index = {x['date']: float(x['close']) for x in index_data['series']['CSI_ALL_TR']}
    calendar = [d for d in market['calendar'] if d <= data_as_of]
    # Reuse the original causal TRIX state without invoking its old protocol.
    old = object.__new__(Study)
    old.assets = assets
    old.cache = {}
    candidates = {}
    for code, asset in assets.items():
        bars = [b for b in asset['bars'] if b['date'] <= data_as_of]
        local_asset = {**asset, 'bars': bars}
        economic = economic_series(local_asset)
        values = np.array([r['economic_tr'] for r in economic], dtype=float)
        rets = np.array([r['economic_return'] if r['economic_return'] is not None else np.nan for r in economic])
        amounts = np.array([b['amount_cny'] for b in bars], dtype=float)
        assert np.all(amounts >= 0)
        trix = {x['date']: x for x in old.features(code)}
        rows = {}
        for i, bar in enumerate(bars):
            if i < 119:
                continue
            day, earlier = bar['date'], bars[i - 60]['date']
            if day not in index or earlier not in index:
                continue
            turnover = amounts[i - 19:i + 1]
            denominator = float(turnover.sum())
            assert denominator > 0
            trend = values[i] / values[i - 119:i + 1].mean() - 1.
            relative = (values[i] / values[i - 60]) / (index[day] / index[earlier]) - 1.
            flow = float(np.dot(np.sign(rets[i - 19:i + 1]), turnover) / denominator)
            vol = float(rets[i - 59:i + 1].std(ddof=1) * math.sqrt(252))
            rows[day] = {'date': day, 'economic_tr': float(values[i]),
                         'trix_long': bool(trix[day]['TRIX_long']), 'trix_ready': bool(trix[day]['TRIX_ready']),
                         'raw': dict(zip(FEATURES, map(float, [trend, relative, flow, vol])))}
        candidates[code] = rows
    common = sorted(set(calendar).intersection(*(set(candidates[c]) for c in codes)))
    assert common and all(len(candidates[c]) >= len(common) for c in codes)
    for day in common:
        for key, name in zip(FEATURES, SCORE_NAMES):
            raw = pd.Series([candidates[c][day]['raw'][key] for c in codes])
            ranks = (raw.rank(method='average', ascending=(key != 'volatility60')) - 1) / (len(codes) - 1) * 100
            for code, rank in zip(codes, ranks):
                candidates[code][day].setdefault('scores', {})[name] = float(rank)
        for code in codes:
            row = candidates[code][day]
            row['score'] = float(sum(row['scores'].values()) / 4)
            row['label20'] = holding_label(assets[code], calendar, day)
    return {'schema': 'ten-sector.price-score.features.v1',
            'metadata': {'data_as_of': data_as_of, 'common_feature_start': common[0], 'common_feature_end': common[-1],
                         'common_dates': len(common), 'rows': len(common) * len(codes),
                         'raw_feature_order': FEATURES, 'score_component_order': SCORE_NAMES,
                         'score_is_probability': False, 'economic_tr_reinvested_on_ex_date': True,
                         'label_dividends_reinvested': False, 'label_trading_costs': False,
                         'economic_tr_is_prior_indicator_adjustment': False},
            'calendar': common, 'codes': codes,
            'assets': {c: {'identity': assets[c]['identity'], 'rows': [candidates[c][d] for d in common]} for c in codes}}

def sigmoid(z):
    z = np.asarray(z, dtype=float)
    out = np.empty_like(z)
    positive = z >= 0
    out[positive] = 1. / (1. + np.exp(-z[positive]))
    ez = np.exp(z[~positive])
    out[~positive] = ez / (1. + ez)
    return out

def fit_logistic(raw, labels):
    x = np.asarray(raw, dtype=float)
    y = np.asarray(labels, dtype=float)
    center, scale = x.mean(axis=0), x.std(axis=0, ddof=0)
    scale[scale == 0] = 1.
    z = np.clip((x - center) / scale, -5., 5.)
    design = np.column_stack([np.ones(len(z)), z])
    rate = float(y.mean())
    assert 0 < rate < 1, 'A two-class training sample is required.'
    beta = np.array([math.log(rate / (1. - rate)), 0., 0., 0., 0.])
    penalty = np.diag([0., RIDGE, RIDGE, RIDGE, RIDGE])
    def objective(b):
        logit = design @ b
        return float(np.mean(np.logaddexp(0., logit) - y * logit) + .5 * b @ penalty @ b)
    converged = False
    for iteration in range(100):
        p = sigmoid(design @ beta)
        gradient = design.T @ (p - y) / len(y) + penalty @ beta
        max_gradient = float(np.max(np.abs(gradient)))
        if max_gradient < 1e-10:
            converged = True
            break
        hessian = design.T @ ((p * (1. - p))[:, None] * design) / len(y) + penalty
        step = np.linalg.solve(hessian, gradient)
        old_loss = objective(beta)
        length = 1.
        while length > 2.**-30:
            proposed = beta - length * step
            if objective(proposed) <= old_loss - 1e-4 * length * float(gradient @ step):
                beta = proposed
                break
            length *= .5
        else:
            # Roundoff can prevent strict decrease near a stationary point.
            if max_gradient < 1e-8:
                converged = True
                break
            raise RuntimeError('Logistic Newton line search did not converge')
    gradient = design.T @ (sigmoid(design @ beta) - y) / len(y) + penalty @ beta
    assert np.max(np.abs(gradient)) < 1e-8
    return {'center': center.tolist(), 'scale': scale.tolist(), 'intercept': float(beta[0]),
            'coefficients': beta[1:].tolist(), 'ridge': RIDGE, 'clip': 5.,
            'standardization_ddof': 0, 'iterations': iteration + 1,
            'converged': bool(converged or np.max(np.abs(gradient)) < 1e-8),
            'gradient_max_abs': float(np.max(np.abs(gradient))), 'objective': objective(beta)}

def predict(model, raw):
    x = np.clip((np.asarray(raw) - np.asarray(model['center'])) / np.asarray(model['scale']), -5., 5.)
    return sigmoid(model['intercept'] + x @ np.asarray(model['coefficients']))

def build_probability(features, market_calendar, start='2024-04-01', end='2026-09-30'):
    codes = features['codes']
    days = features['calendar']
    by_code = {c: {r['date']: r for r in features['assets'][c]['rows']} for c in codes}
    forecast_days = [d for d in days if start <= d <= end]
    months = sorted({d[:7] for d in forecast_days})
    models = {}
    predictions = []
    def monthly_fit(month):
        cutoff = max(d for d in market_calendar if d < month + '-01')
        train = [(d, c, by_code[c][d]) for d in days for c in codes
                 if d <= cutoff and by_code[c][d]['label20'] is not None
                 and by_code[c][d]['label20']['end_date'] <= cutoff]
        x = [[r['raw'][f] for f in FEATURES] for d, c, r in train]
        y = [r['label20']['up'] for d, c, r in train]
        model = fit_logistic(x, y)
        frequencies = {c: float(np.mean([r['label20']['up'] for d, cc, r in train if cc == c])) for c in codes}
        dates = sorted({d for d, c, r in train})
        label_ends = [r['label20']['end_date'] for d, c, r in train]
        assert len(train) == len(dates) * len(codes)
        training_digest = hashlib.sha256(json.dumps([[d, c, r['raw'], r['label20']['end_date'], r['label20']['up']]
                                                    for d, c, r in train], separators=(',', ':'), sort_keys=True).encode()).hexdigest()
        model['metadata'] = {'forecast_month': month, 'fit_cutoff': cutoff,
                             'first_training_feature_date': dates[0], 'last_training_feature_date': dates[-1],
                             'first_training_label_end': min(label_ends), 'last_training_label_end': max(label_ends),
                             'training_dates': len(dates), 'training_rows': len(train), 'training_up_count': int(sum(y)),
                             'training_rows_per_code': {c: sum(cc == c for d, cc, r in train) for c in codes},
                             'training_input_sha256': training_digest, 'raw_feature_order': FEATURES,
                             'baseline_overall': float(np.mean(y)), 'baseline_by_fund': frequencies}
        return model
    def make_prediction(day, code, model, kind):
        row = by_code[code][day]
        p = float(predict(model, np.array([[row['raw'][f] for f in FEATURES]]))[0])
        return {'date': day, 'code': code, 'sector': features['assets'][code]['identity']['sector'],
                'model_month': model['metadata']['forecast_month'], 'fit_cutoff': model['metadata']['fit_cutoff'],
                'prediction_kind': kind, 'probability': p,
                'baseline_overall': model['metadata']['baseline_overall'],
                'baseline_fund': model['metadata']['baseline_by_fund'][code],
                'score': row['score'], 'component_scores': row['scores'], 'trix_long': row['trix_long'],
                'label20': row['label20']}
    for month in months:
        model = monthly_fit(month)
        models[month] = model
        for day in forecast_days:
            if day.startswith(month):
                predictions.extend(make_prediction(day, c, model, 'historical_monthly_frozen') for c in codes)
    year, month_num = map(int, end[:7].split('-'))
    next_month = f'{year + int(month_num == 12):04d}-{1 if month_num == 12 else month_num + 1:02d}'
    observation_model = monthly_fit(next_month)
    latest = [make_prediction(forecast_days[-1], c, observation_model, 'next_month_observation_on_frozen_prices') for c in codes]
    return {'schema': 'ten-sector.price-score.probability.v1',
            'metadata': {'start': start, 'end': end, 'feature_order': FEATURES, 'forecast_dates': len(forecast_days),
                         'prediction_rows': len(predictions), 'models': len(models), 'horizon_sessions': 20,
                         'probability_is_calibrated_claim': False, 'used_for_allocation': False,
                         'latest_prices_as_of': forecast_days[-1], 'labels_exclude_trading_costs': True},
            'models': models, 'predictions': predictions,
            'latest_historical': [r for r in predictions if r['date'] == forecast_days[-1]],
            'observation_model': observation_model, 'latest_observation': latest}

def verify_freeze(root):
    receipt = read(root / 'freeze_receipt.json')
    for relative, expected in receipt['inputs'].items():
        assert sha(root / relative) == expected, relative

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--features-only', action='store_true')
    parser.add_argument('--model-only', action='store_true')
    args = parser.parse_args()
    verify_freeze(ROOT)
    protocol = read(ROOT / 'protocol.json')
    market = read(ROOT / 'data/market.json')
    if not args.model_only:
        features = build_features(market, read(ROOT / 'data_index/index_data.json'), protocol['data_as_of'])
        write(ROOT / 'output/features.json', features)
        print(json.dumps(features['metadata'], ensure_ascii=False))
    else:
        features = read(ROOT / 'output/features.json')
    if not args.features_only:
        probability = build_probability(features, market['calendar'], **protocol['period'])
        write(ROOT / 'output/probability.json', probability)
        print(json.dumps(probability['metadata'], ensure_ascii=False))

if __name__ == '__main__':
    main()
