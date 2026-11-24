"""Display-only rankings from a completed, like-for-like historical comparison."""
from datetime import date
import math
from simulator_core import ORDER, TITLES, ENGINE
from bank_model import spec


class StrategyLabels:
    def __init__(self):
        self.badges={};self.result=None
        self.note='尚无完整比较，暂不标注排名；在“策略对比”页运行比较后自动显示。'

    def update(self,result):
        # A cancelled run must not replace the last completed comparison.
        try:
            if result.get('engine')!=ENGINE or result.get('completed') is not True:return False
            start,end=result['start'],result['end']
            elapsed=(date.fromisoformat(end)-date.fromisoformat(start)).days
            if elapsed<=0 or start<'2013-01-01':return False
            capital=float(result['capital'])
            if not math.isfinite(capital) or capital<=0:return False
            rows=result['rows'];expected={c for c in ORDER if start>=spec(c)['anchor']}
            if len(rows)!=len(expected) or {r['code'] for r in rows}!=expected:return False
            if any(r['start']!=start or r['end']!=end for r in rows):return False
            if any(not math.isfinite(r['max_drawdown']) or not -1<=r['max_drawdown']<=0 for r in rows):return False
            if elapsed>=365 and any(r['cagr'] is None or not math.isfinite(r['cagr']) for r in rows):return False
        except (KeyError,TypeError,ValueError,OverflowError):return False
        badges={c:[] for c in ORDER}
        def mark(key,label):
            # Drawdown is signed: the value closest to zero is the smallest loss.
            best=max(r[key] for r in rows)
            winners=[r['code'] for r in rows if math.isclose(r[key],best,rel_tol=0,abs_tol=1e-10)]
            for c in winners:badges[c].append(('并列' if len(winners)>1 else '')+label)
        if elapsed>=365:mark('cagr','年化收益最高')
        mark('max_drawdown','回撤最低')
        self.badges=badges;self.result=result
        self.note=f'标签依据：{start} 至 {end} · 本金 {capital:,.0f} 元 · {len(rows)} 种策略完整比较，已计交易成本。仅为该区间历史排名。'
        if len(rows)<len(ORDER):self.note+=' L系列未参与。'
        if elapsed<365:self.note+=' 区间不足一年，不标年化最高。'
        return True

    def label(self,code):
        suffix=''.join('【'+tag+'】' for tag in self.badges.get(code,[]))
        return f'{code}  {TITLES[code]}'+('  '+suffix if suffix else '')

    def values(self):return [self.label(c) for c in ORDER]
