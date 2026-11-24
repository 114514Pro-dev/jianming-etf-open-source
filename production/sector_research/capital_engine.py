"""Adapters for the frozen research ledgers and explicit holding what-if plans.

No account persistence, order routing, market download or probability fitting.
Vendored historical engines retain their original accounting and formulas.
"""
from __future__ import annotations
from bisect import bisect_left, bisect_right
from copy import deepcopy
from datetime import date
from decimal import Decimal, DecimalException, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
from threading import RLock
from types import FunctionType

if __package__:
    from .core import Environment, SECTORS, _clock
    from .opportunity import Opportunity
    from .research_vendor import improved_engine, portfolio_backtest, market_filter, features_model
else:
    from core import Environment, SECTORS, _clock
    from opportunity import Opportunity
    from research_vendor import improved_engine, portfolio_backtest, market_filter, features_model

D, money, fee, fill = (portfolio_backtest.D, portfolio_backtest.money,
                       portfolio_backtest.fee, portfolio_backtest.fill)
VENDOR = Path(__file__).resolve().parent / "research_vendor"
SHARED = {"SCORE", "B_SCORE", "B_EQUAL"}
GATES = {"INDEPENDENT_ENTRY_GATE": "ENTRY_GATE", "INDEPENDENT_FULL_GATE": "FULL_GATE"}
MODEL_NAMES = {
    "HOLD": "十板块独立持有", "INDEPENDENT_TRIX": "十板块独立TRIX",
    "SCORE": "原价量评分共享资金", "B_SCORE": "减少小额调仓的评分配置B",
    "B_EQUAL": "同目标总仓位等额配置B",
    "INDEPENDENT_ENTRY_GATE": "独立TRIX加大盘入场过滤",
    "INDEPENDENT_FULL_GATE": "独立TRIX加大盘完整过滤",
}
COSTS = {"commission_rate": .0003, "minimum_commission": 5,
         "slippage_rate": .0002, "minimum_slippage_ticks": 1}
SCENARIOS = {
    "primary": {},
    "double_cost": {"commission_rate": .0006, "minimum_commission": 10,
                    "slippage_rate": .0004, "minimum_slippage_ticks": 2},
    "extra_execution_day": {"delay": 2},
    "no_minimum_commission": {"minimum_commission": 0},
}


def _amount(value, field, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{field} 必须为人民币金额")
    try:
        number = D(value)
    except Exception as exc:
        raise ValueError(f"{field} 金额无效") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise ValueError(f"{field} 须为有限{'正' if positive else '非负'}金额")
    if number > D('1000000000000'):
        raise ValueError(f"{field} 不可超过1万亿元")
    try:
        rounded = money(number)
    except DecimalException as exc:
        raise ValueError(f"{field} 金额精度超出支持范围") from exc
    if number != rounded:
        raise ValueError(f"{field} 最多保留两位人民币小数")
    return number


def _qty(value, field, lots=True):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} 必须为非负整数份数")
    if lots and value % 100:
        raise ValueError(f"{field} 必须为100份整手")
    if value > 1_000_000_000_000:
        raise ValueError(f"{field} 不可超过1万亿份")
    return value


def _json_decimal(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_decimal(v) for v in value]
    return value


class CapitalResearch:
    def __init__(self, env: Environment, opportunity: Opportunity):
        if not isinstance(env, Environment) or not isinstance(opportunity, Opportunity) or opportunity.env is not env:
            raise TypeError("CapitalResearch 需要同一数据源的 Environment 与 Opportunity")
        self.env, self.opportunity = env, opportunity
        self.codes = [c for c, _ in SECTORS]
        self.names = dict(SECTORS)
        self._lock = RLock()
        self._features = self._study = None
        self._score_rows = {c: {} for c in self.codes}
        self._feature_error = None
        self._vendor_manifest = json.loads((VENDOR / "source_manifest.json").read_text("utf-8"))
        for entry in self._vendor_manifest["files"]:
            actual = hashlib.sha256((VENDOR / entry["file"]).read_bytes()).hexdigest()
            if actual != entry["runtime_sha256"]:
                raise ValueError(f"已登记研究引擎文件发生变化: {entry['file']}")
        self._gate_study = market_filter.Study(VENDOR / "filter", market=env._market, index_data=env._index)
        self._events = {c: {e["event_id"]: e for e in env._market["assets"][c]["dividends"]} for c in self.codes}

    def _ensure_study(self):
        with self._lock:
            if self._study is not None:
                return
            if not self.opportunity._benchmark_bars:
                self._feature_error = "缺少H00985全收益基准，不能计算原四项评分"
                self._features = {"calendar": [], "assets": {c: {"rows": []} for c in self.codes}}
                self._study = improved_engine.ImprovedStudy(VENDOR, market=self.env._market, features=self._features)
                return
            cutoff = self.env.snapshot()["snapshot_date"]
            cutoff = min(cutoff, self.env._action_through)
            # Same frozen feature code, with outcome-label construction replaced
            # by a constant no-op in a private globals dictionary.  No mutation
            # of the imported module, and no labels/probability fits are needed.
            globals_for_features = dict(features_model.build_features.__globals__)
            globals_for_features["holding_label"] = lambda *args, **kwargs: None
            build = FunctionType(features_model.build_features.__code__, globals_for_features,
                                 "build_features_without_outcomes")
            try:
                self._features = build(self.env._market, self.env._index, cutoff)
                self._study = improved_engine.ImprovedStudy(VENDOR, market=self.env._market,
                                                            features=self._features)
            except (AssertionError, KeyError, IndexError, ZeroDivisionError, ValueError, TypeError) as exc:
                self._feature_error = f"原评分所需完整历史资料不足: {exc}"
                self._features = {"calendar": [], "assets": {c: {"rows": []} for c in self.codes}}
                self._study = improved_engine.ImprovedStudy(VENDOR, market=self.env._market, features=self._features)
                return
            self._score_rows = {c: {r["date"]: r for r in self._features["assets"][c]["rows"]} for c in self.codes}

    def _model(self, model):
        if not isinstance(model, str) or model not in MODEL_NAMES:
            raise ValueError("不支持的研究模型")
        return model

    def _gate(self, d):
        checked = self.env._index_features.get(d)
        original = self._gate_study.market_features.get(d)
        ready = checked is not None and checked["ma120"] is not None and original is not None and original["market_ready"]
        return {"ready": bool(ready), "allowed": original["market_allowed"] if ready else None,
                "close": original["market_close"] if original else None,
                "ma120": original["market_ma120"] if ready else None}

    def models(self):
        self._ensure_study()
        first_shared = None
        if len(self._features["calendar"]) > 1:
            first = self._features["calendar"][1]
            pos = self.env._calendar_pos[first]
            first_shared = self.env._calendar[pos+1]
        return {"schema": "sector-capital.models.v1",
                "models": [{"id": m, "name": name, "shared_capital": m in SHARED,
                            "earliest_start": first_shared if m in SHARED else "2022-04-01",
                            "available": m not in SHARED or first_shared is not None}
                           for m, name in MODEL_NAMES.items()],
                "scenarios": list(SCENARIOS), "default_start": "2024-04-01",
                "data_as_of": min(self.env.snapshot()["snapshot_date"], self.env._action_through),
                "costs": dict(COSTS),
                "warnings": ["同一比较必须使用相同区间、本金和费用场景。",
                             "评分是原四项价量秩，不是上涨概率；默认费用并未代表用户券商实际收费。",
                             "独立模型的十份现金互不借用；共享模型可在规则触发时重配。"]}

    def _validate_interval(self, model, start, end, capital, scenario):
        self._model(model)
        if model in SHARED and self._feature_error:
            raise ValueError(self._feature_error)
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            raise ValueError("不支持的费用/延迟场景")
        amount = _amount(capital, "capital", positive=True)
        if model not in SHARED and amount / 10 != money(amount / 10):
            raise ValueError("独立十袖套等额本金必须可按人民币分精确分成十份（本金为0.10元的整数倍）")
        dates = self.env._market["calendar"]
        if not isinstance(start, str) or not isinstance(end, str) or start not in dates or end not in dates:
            raise ValueError("回测起止必须为数据包中的实际交易日")
        if start < "2022-04-01" or start >= end:
            raise ValueError("回测至少包含两个市场日，且不得早于2022-04-01")
        if end > min(self.env.snapshot()["snapshot_date"], self.env._action_through):
            raise ValueError("回测终点超过已完成行情或公司行动核验范围")
        lo, hi = bisect_left(dates, start), bisect_right(dates, end)
        delay = SCENARIOS[scenario].get("delay", 1)
        if lo < delay+1:
            raise ValueError("缺少回测前置信息")
        signal_days = dates[lo-delay-1:hi-delay]
        for day in signal_days:
            if model in SHARED and any(day not in self._score_rows[c] for c in self.codes):
                raise ValueError(f"{day} 缺少完整评分或前一日评分；请推迟起点")
            if model != "HOLD" and any(self.env._sector_features[c].get(day, {}).get("eligible") is None for c in self.codes):
                raise ValueError(f"{day} 技术资格未知，不能进行此历史模拟")
            if model in GATES and not self._gate(day)["ready"]:
                raise ValueError(f"{day} 缺少完整大盘MA120窗口")
        if model in SHARED:
            for day in signal_days:
                if self.opportunity._benchmark_return60(day) is None:
                    raise ValueError(f"{day} 缺少相对评分的完整全收益基准窗口")
        # Preserve the original ledger's initial Decimal textual evidence for
        # whole-yuan input (100000, rather than the distinct string 100000.0).
        return int(amount) if amount == amount.to_integral_value() else float(amount)

    def backtest(self, model, start, end, capital, scenario="primary"):
        self._ensure_study()
        capital = self._validate_interval(model, start, end, capital, scenario)
        parameters = {**COSTS, **SCENARIOS[scenario]}
        if model in GATES:
            sleeves = [self._gate_study.run(c, GATES[model], start=start, end=end,
                                            capital=capital / 10, **parameters) for c in self.codes]
            result = {"portfolio": market_filter.portfolio(sleeves, capital), "sleeves": sleeves}
        else:
            result = self._study.run(model, start=start, end=end, capital=capital, **parameters)
        return {"schema": "sector-capital.backtest.v1", "model": model, "start": start, "end": end,
                "capital": capital, "scenario": scenario, "result": result,
                "provenance": {"inputs": deepcopy(self.env._hashes),
                               "engines": {e["file"]: e["runtime_sha256"] for e in self._vendor_manifest["files"]},
                               "feature_outcome_labels_used": False, "probability_used": False},
                "warnings": ["历史已在此前研究中反复观察，不是真正未见样本外。",
                             "期末按持仓市值及合法应收结算，没有强制平仓；区间不同不能直接排名。",
                             "下一交易日开盘先卖后买及日线成交量可用性是研究假设，不证明真实成交深度。",
                             "20%是共享模型复核时目标上限，实际权重可能随价格漂移超过20%。",
                             "保留冻结数据、公司行动证据不完整和历史版本修订的原限制。"]}

    def _rights(self, d, next_day, positions, entitlements, receivables):
        entries = {c: {} for c in self.codes}
        pending = {c: {} for c in self.codes}
        blocked = []
        for provided, output, kind in ((entitlements, entries, "entitlements"),
                                       (receivables, pending, "receivables")):
            if provided is not None:
                if not isinstance(provided, dict) or set(provided) - set(self.codes):
                    raise ValueError(f"{kind} 必须为固定ETF代码到事件映射")
                for c, mapping in provided.items():
                    if not isinstance(mapping, dict):
                        raise ValueError(f"{kind}.{c} 必须为事件映射")
                    for event_id, value in mapping.items():
                        event = self._events[c].get(event_id)
                        if event is None:
                            raise ValueError(f"{kind} 包含未知分红事件: {event_id}")
                        if kind == "entitlements":
                            if event["record_date"] > d:
                                raise ValueError("不能提前登记尚未发生的权益")
                            output[c][event_id] = _qty(value, f"{kind}.{event_id}", lots=False)
                        else:
                            if not event["ex_date"] <= d < event["pay_date"]:
                                raise ValueError("应收必须已经除息且在模型支付日尚未到账")
                            amount = _amount(value, f"{kind}.{event_id}")
                            if amount:
                                output[c][event_id] = amount
        for c in self.codes:
            for event_id, event in self._events[c].items():
                if event["record_date"] == d:
                    if event_id in entries[c] and entries[c][event_id] != positions[c]:
                        raise ValueError("D日登记权益份数必须等于输入D日收盘持仓")
                    entries[c][event_id] = positions[c]
                if (entitlements is None and next_day is not None
                        and event["record_date"] < d < event["ex_date"] <= next_day):
                    blocked.append(f"{c} {event_id} 未提供已登记权益；需确认份数或显式声明无权益")
                if receivables is None and event["ex_date"] <= d < event["pay_date"]:
                    blocked.append(f"{c} {event_id} 未提供尚未到账应收；需确认金额或显式声明无应收")
                if event_id in pending[c] and event_id in entries[c]:
                    if pending[c][event_id] != money(D(entries[c][event_id]) * D(event["cash_per_share"])):
                        raise ValueError("应收金额与已提供登记份额不一致")
        return entries, pending, blocked

    def _state(self, model, d, next_day, cash, positions, sleeve_cash, initialized, entitlements, receivables):
        cash = _amount(cash, "cash")
        if not isinstance(positions, dict) or set(positions) - set(self.codes):
            raise ValueError("positions 只能含固定十只ETF代码")
        shares = {c: _qty(positions.get(c, 0), f"positions.{c}") for c in self.codes}
        if not isinstance(initialized, bool):
            raise ValueError("initialized 必须是布尔值")
        sleeves = None
        if model not in SHARED:
            if not isinstance(sleeve_cash, dict) or set(sleeve_cash) != set(self.codes):
                raise ValueError("独立模型必须提供完整十个 sleeve_cash，不能假定总现金等分")
            sleeves = {c: _amount(sleeve_cash[c], f"sleeve_cash.{c}") for c in self.codes}
            if sum(sleeves.values(), D(0)) != cash:
                raise ValueError("十份袖套现金之和必须等于cash，不能重复计入")
        elif sleeve_cash is not None:
            raise ValueError("共享资金模型不接受sleeve_cash，请传null")
        entries, pending, blocked = self._rights(d, next_day, shares, entitlements, receivables)
        receivable_known = not (receivables is None and any(
            e["ex_date"] <= d < e["pay_date"] for events in self._events.values() for e in events.values()))
        security_value_known = True
        values = {}
        for c in self.codes:
            bar = self.env._sector_bars[c].get(d)
            if bar is None:
                if shares[c]:
                    blocked.append(f"{c} 决策日缺少收盘价，持仓净值不可确认")
                    security_value_known = False
                values[c] = D(0)
            else:
                values[c] = money(D(shares[c]) * D(bar["close"]))
        recv = sum((sum(v.values(), D(0)) for v in pending.values()), D(0))
        equity = money(cash + sum(values.values(), D(0)) + recv)
        valuation_complete = receivable_known and security_value_known
        if equity <= 0 and valuation_complete:
            raise ValueError("输入账户净值必须大于零")
        state = {"date": d, "cash": cash, "shares": shares, "sleeve_cash": sleeves,
                 "initialized": initialized, "entitlements": entries, "receivables": pending,
                 "values": values, "equity": equity, "valuation_complete": valuation_complete,
                 "receivable_known": receivable_known, "security_value_known": security_value_known,
                 "weights": {c: values[c] / equity if equity > 0 else D(0) for c in self.codes}}
        return state, blocked

    def _decisions(self, model, d, state):
        if not state["valuation_complete"]:
            return [], [], self._gate(d), ["决策日净值资料不全，目标金额与数量暂不计算"]
        previous = self.env._prior_market_date(d, 1)
        eligible, prior_eligible, unknown = [], [], []
        scores = {c: None for c in self.codes}
        rows = {}
        for c in self.codes:
            feature = self.env._sector_features[c].get(d, {})
            prior = self.env._sector_features[c].get(previous, {})
            if feature.get("eligible") is None and model != "HOLD":
                unknown.append(f"{c} 当前TRIX资格未知")
            if feature.get("eligible") is True:
                eligible.append(c)
            if prior.get("eligible") is True:
                prior_eligible.append(c)
            if model in SHARED:
                source = self._score_rows[c].get(d)
                if source is None or previous not in self._score_rows[c]:
                    unknown.append(f"{c} 缺少完整当前或前日评分")
                elif self.opportunity._benchmark_return60(d) is None:
                    unknown.append("H00985全收益基准窗口不完整，原评分不可确认")
                else:
                    rows[c] = {"date": d, "score": source["score"], "trix_long": feature.get("eligible") is True}
                    scores[c] = source["score"]
        gate = self._gate(d)
        if model in GATES and not gate["ready"]:
            unknown.append("大盘MA120窗口未知")
        if unknown:
            return [], [], gate, list(dict.fromkeys(unknown))
        weights = {c: D(0) for c in self.codes}
        if model in SHARED:
            weight_model = "MATCH_EQUAL" if model == "B_EQUAL" else "SCORE"
            eligible, weights, _ = portfolio_backtest.allocation(rows, self.codes, weight_model)
        initialization = not state["initialized"]
        friday = date.fromisoformat(d).weekday() == 4
        reasons = []
        changed = eligible != prior_eligible
        if model in SHARED:
            if initialization:
                reasons.append("initialization")
            if model == "SCORE" and changed:
                reasons.append("eligible_set_changed")
            if friday:
                reasons.append("friday_close_review")
        else:
            reasons.append("independent_daily_review" if model != "HOLD" else "hold_initial_purchase_or_keep")
        entrants = [c for c in eligible if c not in prior_eligible]
        if model.startswith("B_") and entrants:
            reasons.append("new_eligibility")
        full = initialization or friday
        plans = []
        for c in self.codes:
            shares = state["shares"][c]
            is_eligible = c in eligible
            optional = False
            if model in SHARED:
                target = weights[c]
                if model == "SCORE":
                    active = initialization or friday or changed
                    action = "shared_full_review" if active else "keep_current_position"
                elif not is_eligible:
                    action = "mandatory_ineligible_exit" if shares else "empty_ineligible"
                    active = shares > 0
                elif full:
                    active = True
                    if not shares:
                        action = "initial_entry" if initialization else "scheduled_zero_position_entry"
                    elif initialization:
                        action = "initial_existing_review"
                    else:
                        action, optional = "scheduled_existing_resize", True
                elif c in entrants and shares == 0:
                    action, active = "new_eligible_entry", True
                else:
                    action = "keep_eligible_incumbent" if shares else "wait_for_next_entry_review"
                    active = False
                value = state["equity"] * target
            else:
                if model == "HOLD":
                    is_eligible = True
                    # A HOLD ledger never sells.  Zero shares therefore means
                    # its initial purchase has not yet succeeded; retry, as in
                    # the original ledger, after a missing quote/small budget.
                    active = shares == 0
                    action = "initial_entry" if active else "hold_existing_or_completed"
                else:
                    if model == "INDEPENDENT_ENTRY_GATE":
                        is_eligible = is_eligible and (shares > 0 or gate["allowed"])
                    elif model == "INDEPENDENT_FULL_GATE":
                        is_eligible = is_eligible and gate["allowed"]
                    active = (is_eligible and shares == 0) or (not is_eligible and shares > 0)
                    action = "independent_entry" if active and is_eligible else "independent_exit" if active else "keep_independent_position"
                value = state["values"][c] if is_eligible and shares else state["sleeve_cash"][c] if is_eligible and (active or model != "HOLD") else D(0)
                target = value / state["equity"]
            plans.append({"code": c, "name": self.names[c], "eligible": bool(is_eligible), "score": scores[c],
                          "current_shares": shares, "current_weight": float(state["weights"][c]),
                          "target_weight": float(target), "target_value": float(value),
                          "action_type": action, "review_required": bool(active),
                          "weight_gap": float(abs(state["weights"][c] - target)),
                          "gate_applies": optional, "_target_decimal": target,
                          "_known_weight_decimal": state["weights"][c]})
        if model.startswith("B_") and any(p["action_type"] == "mandatory_ineligible_exit" for p in plans):
            reasons.append("mandatory_ineligible_exit")
        return plans, reasons, gate, []

    def _quotes(self, d, execution_prices):
        if execution_prices is None:
            return None, "none"
        if execution_prices == "last_close":
            return {c: {"price": D(self.env._sector_bars[c][d]["close"]), "tradable": True}
                    for c in self.codes if d in self.env._sector_bars[c]}, "last_close_assumption"
        if not isinstance(execution_prices, dict) or set(execution_prices) - set(self.codes):
            raise ValueError("execution_prices 必须为null、last_close或固定ETF报价映射")
        quotes = {}
        for c, value in execution_prices.items():
            if not isinstance(value, dict) or not isinstance(value.get("tradable"), bool):
                raise ValueError(f"{c} 报价必须包含price和布尔tradable")
            price = value.get("price")
            if price is None and value["tradable"] is False:
                quotes[c] = {"price": None, "tradable": False}
                continue
            if isinstance(price, bool) or not isinstance(price, (int, float, str, Decimal)):
                raise ValueError(f"{c} 假设价格必须为正数")
            try:
                price = D(price)
            except Exception as exc:
                raise ValueError(f"{c} 假设价格无效") from exc
            if not price.is_finite() or price <= 0:
                raise ValueError(f"{c} 假设价格必须为有限正数")
            if not D('.001') <= price <= D('1000000000'):
                raise ValueError(f"{c} 假设价格须在0.001至10亿元之间")
            quotes[c] = {"price": price, "tradable": value["tradable"]}
        return quotes, "manual_assumption"

    def _simulate_open(self, model, state, execution_date, plans, quotes, costs=None):
        """Pure one-opening adapter; independent audit compares frozen day cuts.

        plans retain Decimal private keys.  No execution-day closing values or
        total daily turnover enter sizing.  quotes are explicit price/tradable
        assumptions; historical audit supplies the corresponding observed bar.
        """
        costs = {**COSTS, **(costs or {})}
        cash, shares = state["cash"], dict(state["shares"])
        sleeve = dict(state["sleeve_cash"]) if state["sleeve_cash"] is not None else None
        recv = deepcopy(state["receivables"])
        events, trades = [], []
        actions = {p["code"]: {k: v for k, v in p.items() if not k.startswith("_")} for p in plans}
        plan_map = {p["code"]: p for p in plans}
        for c in self.codes:
            asset = self.env._market["assets"][c]
            for event in asset["dividends"]:
                event_id = event["event_id"]
                if state["date"] < event["ex_date"] <= execution_date:
                    q = state["entitlements"][c].get(event_id, 0)
                    amount = money(D(q) * D(event["cash_per_share"]))
                    if amount:
                        recv[c][event_id] = amount
                        events.append({"date": execution_date, "event_date": event["ex_date"], "code": c,
                                       "event_id": event_id, "type": "dividend_receivable",
                                       "eligible_shares": q, "cash_per_share": event["cash_per_share"], "amount": float(amount)})
            for event in asset["splits"]:
                if state["date"] < event["ex_date"] <= execution_date:
                    old = shares[c]
                    new = D(old) * D(event["ratio"])
                    if new != new.to_integral_value() or int(new) % 100:
                        raise ValueError("此研究执行器不支持产生零碎份额的拆分")
                    shares[c] = int(new)
                    if old:
                        events.append({"date": execution_date, "event_date": event["ex_date"], "code": c,
                                       "event_id": event["event_id"], "type": "split", "before": old,
                                       "after": shares[c], "ratio": event["ratio"]})
            for event in asset["dividends"]:
                event_id = event["event_id"]
                if state["date"] < event["pay_date"] < execution_date and event_id in recv[c]:
                    amount = recv[c].pop(event_id)
                    cash = money(cash + amount)
                    if sleeve is not None:
                        sleeve[c] = money(sleeve[c] + amount)
                    events.append({"date": execution_date, "event_date": event["pay_date"], "code": c,
                                   "event_id": event_id, "type": "dividend_payment", "amount": float(amount)})

        def execute(c, side, qty):
            nonlocal cash
            price = fill(quotes[c]["price"], side, costs["slippage_rate"], costs["minimum_slippage_ticks"])
            if price <= 0:
                raise ValueError("滑点后卖价不为正，无法按假设计算")
            notional = money(price * qty)
            commission = fee(notional, costs["commission_rate"], costs["minimum_commission"])
            before = sleeve[c] if sleeve is not None else cash
            old = shares[c]
            change = -notional - commission if side == "BUY" else notional - commission
            cash = money(cash + change)
            if sleeve is not None:
                sleeve[c] = money(sleeve[c] + change)
            shares[c] += qty if side == "BUY" else -qty
            if cash < 0 or shares[c] < 0 or (sleeve is not None and sleeve[c] < 0):
                raise ValueError("费用或数量导致负现金，预演已拒绝")
            after = sleeve[c] if sleeve is not None else cash
            record = {"date": execution_date, "code": c, "side": side, "shares": qty,
                      "fill": float(price), "notional": float(notional), "commission": float(commission),
                      "slippage_cost": float(D(qty) * abs(price - quotes[c]["price"])),
                      "cash_before": float(before), "cash_after": float(after),
                      "shares_before": old, "shares_after": shares[c],
                      "decision_date": state["date"], "action_type": plan_map[c]["action_type"]}
            trades.append(record)
            actions[c].update(executed_qty=qty, executed_notional=float(notional), executed_commission=float(commission))

        wants, buy_prices, sells = {}, {}, {}
        for c in self.codes:
            p, a = plan_map[c], actions[c]
            a.update(shares_before_execution=shares[c], candidate_target_shares=shares[c], requested_side=None,
                     requested_qty=0, requested_notional=0., band_pass=None, notional_pass=None,
                     rejection_reason=None, budgeted_qty=0, budgeted_notional=0., executed_qty=0,
                     executed_notional=0., executed_commission=0.)
            if not p["review_required"]:
                continue
            quote = quotes.get(c)
            if quote is None or not quote["tradable"] or quote["price"] is None:
                a["rejection_reason"] = "missing_execution_quote"
                a["candidate_target_shares"] = 0 if not p["eligible"] else None
                continue
            buy_price = fill(quote["price"], "BUY", costs["slippage_rate"], costs["minimum_slippage_ticks"])
            buy_prices[c] = buy_price
            if model in SHARED:
                desired = int((state["equity"] * p["_target_decimal"] / (buy_price * 100))
                              .to_integral_value(rounding=ROUND_FLOOR)) * 100
            elif not p["eligible"]:
                desired = 0
            elif shares[c] > 0:
                desired = shares[c]
            else:
                desired = portfolio_backtest.affordable_lots(buy_price, sleeve[c], costs["commission_rate"], costs["minimum_commission"])
            a["candidate_target_shares"] = desired
            if desired == shares[c]:
                a["rejection_reason"] = "already_at_rounded_target"
                continue
            side = "BUY" if desired > shares[c] else "SELL"
            qty = abs(desired - shares[c])
            price = fill(quote["price"], side, costs["slippage_rate"], costs["minimum_slippage_ticks"])
            if price <= 0:
                a["rejection_reason"] = "nonpositive_slipped_price"
                continue
            amount = money(price * qty)
            a.update(requested_side=side, requested_qty=qty, requested_notional=float(amount))
            if p["gate_applies"]:
                a["band_pass"] = improved_engine.weight_band_passes(p["_known_weight_decimal"], p["_target_decimal"], D(".02"))
                if not a["band_pass"]:
                    a["rejection_reason"] = "weight_gap_below_band"
                    continue
                if side == "SELL":
                    a["notional_pass"] = improved_engine.optional_amount_passes(amount, D(5000))
                    if not a["notional_pass"]:
                        a["rejection_reason"] = "sell_notional_below_minimum"
                        continue
            if side == "SELL":
                sells[c] = qty
            else:
                wants[c] = qty
        if model not in SHARED:
            # Original independent accounts execute in code order, each using
            # only its own cash.  Ordering cannot lend proceeds to another ETF.
            for c in self.codes:
                if c in sells:
                    execute(c, "SELL", sells[c])
                elif c in wants:
                    qty = wants[c]
                    actions[c].update(budgeted_qty=qty, budgeted_notional=float(money(buy_prices[c] * qty)))
                    execute(c, "BUY", qty)
            allocations = {}
        else:
            for c in self.codes:
                if c in sells:
                    execute(c, "SELL", sells[c])
            quantities, needs, budgets = portfolio_backtest.allocate_buys(
                wants, buy_prices, cash, costs["commission_rate"], costs["minimum_commission"])
            allocations = {}
            final_buys = {}
            for c in wants:
                qty = quantities[c]
                amount = money(buy_prices[c] * qty)
                a = actions[c]
                a.update(budgeted_qty=qty, budgeted_notional=float(amount))
                if plan_map[c]["gate_applies"]:
                    a["notional_pass"] = improved_engine.optional_amount_passes(amount, D(5000))
                    if not a["notional_pass"]:
                        a["rejection_reason"] = "budgeted_buy_notional_below_minimum"
                    else:
                        final_buys[c] = qty
                elif qty:
                    final_buys[c] = qty
                else:
                    a["rejection_reason"] = "insufficient_cash_for_lot"
                allocations[c] = {"desired_qty": wants[c], "desired_cost": float(needs[c]),
                                  "allocated_budget": float(budgets[c]), "budgeted_qty": qty,
                                  "qty": final_buys.get(c, 0), "price": float(buy_prices[c])}
            for c in self.codes:
                if final_buys.get(c, 0):
                    execute(c, "BUY", final_buys[c])
        return {"trades": trades, "actions": actions, "cash_after_open": float(cash),
                "positions_after_open": shares,
                "sleeve_cash_after_open": _json_decimal(sleeve),
                "receivables_after_open": _json_decimal(recv), "corporate_events": events,
                "buy_allocations": allocations,
                "commission": sum(t["commission"] for t in trades),
                "slippage_cost": sum(t["slippage_cost"] for t in trades)}

    def preview(self, model, cash, positions, as_of=None, execution_prices=None,
                sleeve_cash=None, initialized=True, entitlements=None, receivables=None):
        self._model(model)
        base = self.env.snapshot(as_of=as_of)
        d = base["snapshot_date"]
        pos = self.env._calendar_pos[d]
        next_day = self.env._calendar[pos+1] if pos+1 < len(self.env._calendar) else None
        if model in SHARED:
            self._ensure_study()
        state, blocked = self._state(model, d, next_day, cash, positions, sleeve_cash,
                                     initialized, entitlements, receivables)
        plans, trigger, gate, unknown = self._decisions(model, d, state)
        blocked.extend(unknown)
        if next_day is None:
            blocked.append("下一交易日尚无已核验日历")
        quotes, quote_mode = self._quotes(d, execution_prices)
        simulation = None
        if quotes is not None and not blocked:
            simulation = self._simulate_open(model, state, next_day, plans, quotes)
        warnings = list(base["warnings"])
        warnings.extend(["这是手工输入收盘状态的目标与假设预演，不证明原账户已按本模型执行，也不会写入任何账户。",
                         "默认佣金万3、每笔最低5元及滑点是研究假设，请与实际券商收费区分。",
                         "次日真实开盘价、成交深度及全天成交额尚未知；假设份数不等于可执行订单。"])
        assumptions = ["输入cash和positions是决策日收盘结算后状态，预演期间没有其他出入金或交易。",
                       "预演固定下一市场日执行，不把当日open冒充未来报价。"]
        if model not in SHARED:
            assumptions.append("独立模型每个袖套仅使用自己的开盘前可用现金；已知非交易日到账可能增加开盘预算，已有合格持仓不补仓。")
        if quotes is not None:
            assumptions.append("用户显式提供报价和可交易假设；仅在这些假设下计算整手、费用与现金。")
        if next_day is not None and next_day > self.env._action_through:
            assumptions.append(f"执行日超过公司行动核验截止 {self.env._action_through}，本次估算假设无新增公司行动。")
        if entitlements == {}:
            assumptions.append("用户显式声明没有额外未结登记权益，决策日当日登记另按收盘持仓处理。")
        if receivables == {}:
            assumptions.append("用户显式声明没有尚未到账应收。")
        public_plans = [{k: v for k, v in p.items() if not k.startswith("_")} for p in plans]
        account = {"cash": float(state["cash"]), "security_value": float(sum(state["values"].values(), D(0))) if state["security_value_known"] else None,
                   "dividend_receivable": float(sum((sum(v.values(), D(0)) for v in state["receivables"].values()), D(0))) if state["receivable_known"] else None,
                   "equity": float(state["equity"]) if state["valuation_complete"] else None, "positions": dict(state["shares"]),
                   "sleeve_cash": _json_decimal(state["sleeve_cash"]), "initialized": initialized}
        return {"schema": "sector-capital.preview.v1", "model": model, "decision_date": d,
                "execution_date": next_day, "mode": "target_only" if quotes is None else "what_if",
                "quote_mode": quote_mode, "execution_verified": False, "ready": not blocked,
                "blocked_reasons": list(dict.fromkeys(blocked)), "account": account, "market_gate": gate,
                "targets": public_plans, "target_total_weight": sum(p["target_weight"] for p in public_plans) if public_plans else None,
                "trigger_reason": trigger, "simulation": simulation, "freshness": base["freshness"],
                "warnings": warnings, "assumptions": assumptions}
