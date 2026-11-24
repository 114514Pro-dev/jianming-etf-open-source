import pandas as pd
def continuous_bars(raw, splits):
    f = pd.DataFrame(raw).set_index('date').sort_index()
    factor = 1.0
    factors = []
    for d in f.index:
        factor *= splits.get(d, {}).get('ratio', 1.0)
        factors.append(factor)
    factors = pd.Series(factors, index=f.index)
    for col in ['open', 'high', 'low', 'close']:
        f[col] = f[col] * factors
    f['volume'] = f.volume_lots * 100 / factors
    f['amount'] = f.amount_cny
    f['split_factor'] = factors
    f.index = pd.to_datetime(f.index)
    f['open_time'] = f.index + pd.Timedelta(hours=9, minutes=30)
    f.index = f.index + pd.Timedelta(hours=15)
    return f
