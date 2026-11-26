"""Fail-closed D0 order calculation; never contacts a broker."""
from datetime import time
from decimal import Decimal
import re

from d0_order_math import LOT, MAX_ORDER_QTY, SYMBOLS, commission, limit_price, target_quantity
from realtime_paper_engine import D, TradingCalendar, cash as format_cny, dt


def _mapping(value):
    if not isinstance(value, dict):
        raise ValueError("预期对象，收到无效数据")
    return value


def _amount(value):
    number = D(value)
    if not 0 <= number <= Decimal("1000000000000"):
        raise ValueError("金额、价格、费率或数量超出允许范围")
    return number


def _shares(value):
    number = _amount(value)
    if number != number.to_integral_value():
        raise ValueError("ETF 份额必须是整数")
    return int(number)


def _lots(quantity):
    return max(0, quantity) // LOT * LOT


def _market(snapshot, now, *, strategy="D0"):
    contract = "d0-order-preview-input-v1" if strategy == "D0" else "f0-order-preview-input-v1"
    if strategy not in {"D0", "F0"} or snapshot.get("contract_version") != contract or snapshot.get("strategy") != strategy:
        raise ValueError("拟单输入与所选策略不一致")
    if snapshot.get("source_status") != "ready" or snapshot.get("historical_seed") is not False:
        raise ValueError("行情来源未就绪，或当前仅有历史种子")
    cal = TradingCalendar()
    signal = _mapping(snapshot.get("signal"))
    signal_id = signal.get("id")
    if (signal.get("strategy") != strategy or signal.get("valid") is not True
            or not isinstance(signal_id, str) or not re.fullmatch(r"[0-9a-f]{64}", signal_id)):
        raise ValueError("缺少所选策略的已确认信号")
    confirmed = cal.expected_confirmed_day(now)
    eligible = dt(signal.get("eligible_at"))
    if (not confirmed or signal.get("confirmed_day") != confirmed.isoformat()
            or cal.next_session(confirmed) != now.date() or signal.get("execution_day") != now.date().isoformat()
            or eligible.date() != now.date() or eligible.time() != time(9, 30)
            or not eligible <= now or not cal.is_continuous(now)):
        raise ValueError("信号过期、交易日历未知，或不在连续交易时段")
    cutoff, known = dt(signal.get("data_cutoff")), dt(signal.get("known_at"))
    if not (cutoff.date() == confirmed and cutoff < eligible and cutoff <= known <= now):
        raise ValueError("信号的确认时间无效")
    raw_weights = _mapping(signal.get("weights"))
    weights = {symbol: _amount(raw_weights.get(symbol, 0)) for symbol in SYMBOLS}
    if not raw_weights or raw_weights.keys() - set(SYMBOLS) or any(w > 1 for w in weights.values()) or sum(weights.values()) > Decimal("1.000001"):
        raise ValueError("D0 目标权重无效")

    batch = _mapping(snapshot.get("market_observation"))
    received = dt(batch.get("received_at"))
    if not 0 <= (now - received).total_seconds() <= 5 or cal.segment(received) != cal.segment(now):
        raise ValueError("行情批次过期或不在当前交易时段")
    raw_quotes = _mapping(batch.get("quotes"))
    prices = {}
    for symbol in SYMBOLS:
        quote = _mapping(raw_quotes.get(symbol))
        quote_at = dt(quote.get("quote_at"))
        if (quote.get("symbol") != symbol or quote.get("status") not in (None, "normal", "unverified")
                or quote.get("started") is not True or quote_at.date() != now.date()
                or cal.segment(quote_at) != cal.segment(now)
                or not 0 <= (now - quote_at).total_seconds() <= 60 or quote_at > received):
            raise ValueError(f"{symbol} 行情过期、交易状态异常或尚未开盘")
        price, previous = _amount(quote.get("price")), _amount(quote.get("previous_close"))
        if not price or not previous:
            raise ValueError(f"{symbol} 行情价格无效")
        sell_limit = limit_price(symbol, "sell", price, previous)
        buy_limit = limit_price(symbol, "buy", price, previous)
        if not 0 < sell_limit <= price <= buy_limit:
            raise ValueError(f"{symbol} 行情价格不在 D0 限价范围内")
        prices[symbol] = price, sell_limit, buy_limit
    return signal_id, eligible, weights, prices, received


def preview(snapshot, balances, *, now, strategy="D0"):
    """Preview one stage against explicitly allocated D0 cash and holdings only."""
    now = dt(now)
    signal_id, eligible, weights, prices, received = _market(_mapping(snapshot), now, strategy=strategy)
    balances = _mapping(balances)
    cash, available = _amount(balances.get("cash")), _amount(balances.get("available_cash"))
    if available > cash or balances.get("pending_orders") is not False:
        raise ValueError("可用资金异常，或未明确核实没有未结委托")
    account_at = dt(balances.get("observed_at"))
    if account_at.date() != now.date() or not 0 <= (now - account_at).total_seconds() <= 60:
        raise ValueError("账户快照过期；即使未变化也须重新确认")
    rate, minimum = _amount(balances.get("commission_rate")), _amount(balances.get("min_fee"))
    if rate > 1:
        raise ValueError("佣金费率须为小数，例如 0.0003")
    positions = _mapping(balances.get("positions"))
    if set(positions) != set(SYMBOLS):
        raise ValueError("必须明确提供四只 D0 ETF 的持有和可卖份额，空仓须写 0")
    held, sellable = {}, {}
    for symbol in SYMBOLS:
        holding = _mapping(positions[symbol])
        held[symbol], sellable[symbol] = _shares(holding.get("held")), _shares(holding.get("sellable"))
        if sellable[symbol] > held[symbol]:
            raise ValueError("可卖份额不能超过持仓")
    equity = cash + sum(held[symbol] * prices[symbol][0] for symbol in SYMBOLS)
    targets = {symbol: target_quantity(equity, weights[symbol], prices[symbol][0]) for symbol in SYMBOLS}
    excess = {s: held[s] - targets[s] for s in SYMBOLS if held[s] > targets[s]}
    orders, blocked = [], []

    def add(symbol, side, quantity, limit):
        orders.append({"symbol": symbol, "side": side, "quantity": quantity, "limit_price": str(limit)})

    if excess:
        for symbol, gap in excess.items():
            quantity = min(_lots(gap), _lots(sellable[symbol]), MAX_ORDER_QTY)
            if quantity:
                add(symbol, "sell", quantity, prices[symbol][1])
            if quantity < gap:
                blocked.append({"symbol": symbol, "shares_not_in_preview": gap - quantity})
        stage = "sell_first" if orders else "sell_blocked"
    else:
        for symbol in SYMBOLS:
            limit = prices[symbol][2]
            quantity = min(_lots(targets[symbol] - held[symbol]), _lots(int(available / limit)), MAX_ORDER_QTY)
            # Fee is max(minimum, rate * notional), so both bounds must hold.
            quantity = min(quantity, _lots(int(max(Decimal(0), available - minimum) / limit)),
                           _lots(int(available / (1 + rate) / limit)))
            # Guard against division rounding at an exact lot boundary.
            if quantity and quantity * limit + commission(quantity * limit, rate, minimum) > available:
                quantity -= LOT
            if quantity:
                add(symbol, "buy", quantity, limit)
                available -= quantity * limit + commission(quantity * limit, rate, minimum)
        stage = "buy" if orders else ("no_affordable_lot" if any(targets[s] > held[s] for s in SYMBOLS) else "at_target")

    cash_weight = max(Decimal(0), 1 - sum(weights.values()))
    allocation = {s: {"weight": str(w), "target_value": format_cny(equity * w)} for s, w in weights.items()}
    allocation["cash"] = {"weight": str(cash_weight), "target_value": format_cny(equity * cash_weight)}
    return {"mode": "preview_only", "strategy": strategy, "signal_id": signal_id, "eligible_at": eligible.isoformat(),
            "stage": stage, "quote_received_at": received.isoformat(), "quote_receive_age_ms": round((now - received).total_seconds() * 1000),
            "equity": format_cny(equity), "allocation": allocation,
            "targets": targets, "orders": orders, "sell_remainder": blocked}
