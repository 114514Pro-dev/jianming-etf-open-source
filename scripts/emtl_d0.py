"""D0 order preview and EMTL read-only diagnostics. No order submission path."""
from __future__ import annotations

import argparse
from datetime import datetime, time
from decimal import Decimal
import getpass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from http.cookies import CookieError, SimpleCookie
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
from d0_order_math import LOT, MAX_ORDER_QTY, SYMBOLS, commission, limit_price, target_quantity
from realtime_paper_engine import D, TZ, TradingCalendar, dt


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


def _market(snapshot, now):
    if snapshot.get("contract_version") != "realtime-paper-v1" or snapshot.get("strategy") != "D0":
        raise ValueError("请提供 D0 模拟盘 API 快照")
    if snapshot.get("source_status") != "ready" or snapshot.get("historical_seed") is not False:
        raise ValueError("行情来源未就绪，或当前仅有历史种子")
    cal = TradingCalendar()
    signal = _mapping(snapshot.get("signal"))
    signal_id = signal.get("id")
    if (signal.get("strategy") != "D0" or signal.get("valid") is not True
            or not isinstance(signal_id, str) or not re.fullmatch(r"[0-9a-f]{64}", signal_id)):
        raise ValueError("缺少有效的已确认 D0 信号")
    confirmed = cal.expected_confirmed_day(now)
    eligible = dt(signal.get("eligible_at"))
    if (not confirmed or signal.get("confirmed_day") != confirmed.isoformat()
            or cal.next_session(confirmed) != now.date() or signal.get("execution_day") != now.date().isoformat()
            or eligible.date() != now.date() or eligible.time() != time(9, 30)
            or not eligible <= now or not cal.is_continuous(now)):
        raise ValueError("信号过期、交易日历未知，或不在 D0 连续交易时段")
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


def preview(snapshot, balances, *, now):
    """Preview one stage against explicitly allocated D0 cash and holdings only."""
    now = dt(now)
    signal_id, eligible, weights, prices, received = _market(_mapping(snapshot), now)
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

    return {"mode": "preview_only", "strategy": "D0", "signal_id": signal_id, "eligible_at": eligible.isoformat(),
            "stage": stage, "quote_received_at": received.isoformat(), "quote_receive_age_ms": round((now - received).total_seconds() * 1000),
            "targets": targets, "orders": orders, "sell_remainder": blocked}


def inspect_emtl(client_factory, username, password):
    """Connect via an account-bound EMTL client and only issue query methods."""
    stage = "client_init"
    client = None
    timings = {}

    def timed(name, action):
        nonlocal stage
        stage = name
        start = perf_counter()
        try:
            return action()
        finally:
            timings[name] = round((perf_counter() - start) * 1000, 1)

    try:
        client = client_factory(username=username, password=password)
        if not timed("login", client.login):
            raise ValueError("login rejected")
        kinds = {}
        for name, query in (("assets_positions", client.query_asset_and_position),
                            ("orders", client.query_orders), ("trades", client.query_trades)):
            payload = timed(name, query)
            if not isinstance(payload, dict) or type(payload.get("Status")) is not int or payload["Status"] != 0 or "Data" not in payload:
                raise ValueError("query rejected")
            data = payload["Data"]
            if type(data) not in (list, dict):
                raise ValueError("unexpected Data shape")
            kinds[name] = "array" if isinstance(data, list) else "object"
        return {"mode": "read_only", "ok": True, "data_shapes": kinds, "elapsed_ms": timings}
    except Exception:
        # Transport exceptions can embed request URLs with session tokens.
        return {"mode": "read_only", "ok": False, "failed_stage": stage, "elapsed_ms": timings}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass  # Never surface transport objects or credentials in diagnostics.


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _site_origin(site):
    url = urlsplit(site)
    if (not url.hostname or url.username is not None or url.password is not None
            or url.path not in ("", "/") or url.query or url.fragment
            or not (url.scheme == "https" or url.scheme == "http" and url.hostname in ("127.0.0.1", "::1", "localhost"))):
        raise ValueError("站点须为 HTTPS 根地址，仅本机回环地址可用 HTTP")
    return url


def read_paper_snapshot(site, password):
    """Read the normal D0 paper API, not the separately licensed live-signal add-on."""
    url = _site_origin(site)
    origin = f"{url.scheme}://{url.netloc}"
    connect = HTTPSConnection if url.scheme == "https" else HTTPConnection
    connection = connect(url.hostname, url.port, timeout=5)
    try:
        connection.request("POST", "/api/login", body=json.dumps({"password": password}),
                           headers={"Content-Type": "application/json", "Origin": origin})
        reply = connection.getresponse()
        if reply.status != 200:
            raise ValueError(f"站点登录未成功（HTTP {reply.status}）")
        cookie = SimpleCookie(reply.headers.get("Set-Cookie", "")).get("etf_session")
        if not cookie or not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie.value):
            raise ValueError("站点未返回预期的登录会话")
        if url.scheme == "http" and cookie["secure"]:
            raise ValueError("站点使用安全 Cookie，请改用 HTTPS")
        if len(reply.read(4097)) > 4096:
            raise ValueError("站点登录响应过大")
        connection.request("GET", "/api/realtime-paper?strategy=D0", headers={"Cookie": cookie.OutputString(attrs=[])})
        reply = connection.getresponse()
        if reply.status != 200:
            raise ValueError(f"无法读取 D0 模拟盘（HTTP {reply.status}）")
        limit = 16 * 1024 * 1024
        raw = reply.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("D0 模拟盘响应过大")
        return json.loads(raw)
    finally:
        connection.close()


def _prompt(label):
    if not sys.stdin.isatty():
        raise ValueError("请在交互式终端运行；请勿将口令写入命令或脚本")
    value = getpass.getpass(label)
    if not value.strip():
        raise ValueError("口令不能为空")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    plan = subs.add_parser("preview", help="读取 D0 和资金快照，仅打印拟委托")
    source = plan.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", help="登录后保存的 D0 模拟盘 API JSON")
    source.add_argument("--site", help="直接读取简明 ETF 的 D0 模拟盘 API")
    plan.add_argument("--balances", required=True, help="手工确认的 D0 资金持仓 JSON")
    probe = subs.add_parser("probe", help="通过 EMTL 登录并仅读取账户数据")
    probe.add_argument("--authorized-read-only", action="store_true", required=True,
                       help="你已确认有权在本设备进行委托、成交和资金持仓查询")
    args = parser.parse_args(argv)
    try:
        if args.command == "preview":
            if args.site:
                _site_origin(args.site)
                password = _prompt("简明 ETF 网站口令（不回显，不是证券交易密码）: ")
                start = perf_counter()
                snapshot = read_paper_snapshot(args.site, password)
                site_ms = round((perf_counter() - start) * 1000, 1)
            else:
                snapshot, site_ms = _read_json(args.snapshot), None
            balances = _read_json(args.balances)
            start = perf_counter()
            report = preview(snapshot, balances, now=datetime.now(TZ))
            report["plan_ms"] = round((perf_counter() - start) * 1000, 3)
            if site_ms is not None:
                report["site_login_and_read_ms"] = site_ms
        else:
            try:
                from emtl import TradingClient
            except ImportError:
                raise ValueError("请在独立执行环境安装 emtl==0.3.1") from None
            username = os.environ.get("EM_USERNAME", "").strip()
            if not username:
                raise ValueError("请在本机设置 EM_USERNAME")
            password = _prompt("东方财富证券交易密码（不回显）: ")
            report = inspect_emtl(TradingClient, username, password)
    except (OSError, ArithmeticError, HTTPException, CookieError):
        parser.exit(2, "失败：文件、站点连接或金额/价格计算异常。\n")
    except ValueError as exc:
        parser.exit(2, f"失败：{exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
