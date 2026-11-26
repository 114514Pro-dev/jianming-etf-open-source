"""Owner-authorized, one-cycle D0/F0 executor. Shares the manual intent ledger."""
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
import secrets
from threading import Event
import time

from d0_order_math import LOT, MAX_ORDER_QTY, SYMBOLS, target_quantity
from d0_order_preview import _market
from emtl_live import CONFIRMATION, LiveError, SECURITIES, TERMINAL, _account, _rows
from realtime_paper_engine import dt

AUTO_CONFIRMATION = "确认自动委托"
STRATEGIES = frozenset({"D0", "F0"})


@dataclass
class Plan:
    token: str
    strategy: str
    day: str
    signal: str
    expires: float
    targets: dict
    held: dict
    reserve: Decimal
    price_limits: dict


class AutoOrders:
    """All calls, including ticks, run under the owning BrokerDesk lock."""

    cycle_seconds = 15 * 60

    def __init__(self, desk, *, enabled, equity_field, budget):
        self.desk, self.enabled, self.equity_field, self.budget = desk, enabled, equity_field, budget
        self.plan = None
        self.active = False
        self.note = "自动委托未运行。"
        self.read = self.access = None
        self.pending = None
        self.used = Decimal(0)
        self.next_tick = self.deadline = 0
        self.reserved = False
        self.stop_requested = Event()

    def status(self):
        return {"enabled": self.enabled, "configured": bool(self.equity_field), "active": self.active,
                "strategy": self.plan.strategy if self.plan else None, "message": self.note,
                "budget_cny": str(self.budget), "sent_cny": str(self.used)}

    def stop(self, note="自动委托已停止；已送达券商的委托不会撤销。"):
        self.plan = self.read = self.access = self.pending = None
        self.active = False
        self.desk.draft = None
        self.note = note
        return self.status()

    @staticmethod
    def _market(read, strategy, now):
        try:
            return _market(read(strategy), now, strategy=strategy)
        except (ValueError, ArithmeticError, KeyError, TypeError):
            raise LiveError("当前没有该策略的有效执行信号或新鲜行情；不会发单。") from None

    def _account(self, client):
        return _account(self.desk._query(client.query_asset_and_position), equity_field=self.equity_field)

    @staticmethod
    def _held(account):
        return {symbol: row["held"] for symbol, row in account["positions"].items()}

    @staticmethod
    def _queue(targets, held):
        sells = [(s, "sell", held[s] - targets[s]) for s in SYMBOLS if held[s] > targets[s]]
        buys = [(s, "buy", targets[s] - held[s]) for s in SYMBOLS if held[s] < targets[s]]
        if any(q < LOT or q > MAX_ORDER_QTY or q % LOT for _, _, q in sells + buys):
            raise LiveError("存在非整手或超量差额；请先人工核对，未生成自动委托。")
        return sells + buys

    def preview(self, owner, strategy, read):
        if not isinstance(strategy, str) or strategy not in STRATEGIES:
            raise LiveError("请选择 D0 或 F0 主策略。")
        client = self.desk._current(owner)
        if not client or not self.equity_field or self.active:
            raise LiveError("请先登录券商并停止旧的自动委托；总资产字段须已核实。")
        self.plan = None
        account = self._account(client)
        orders = _rows(self.desk._query(client.query_orders))
        if len(orders) >= 100 or any(str(r.get("Wtzt")) not in TERMINAL for r in orders):
            raise LiveError("券商有未结或无法核对的委托，不能拟定自动委托。")
        now = dt(self.desk.now())
        signal, _, weights, prices, _ = self._market(read, strategy, now)
        equity = Decimal(account["equity"])
        targets = {s: target_quantity(equity, weights[s], prices[s][0]) for s in SYMBOLS}
        held = self._held(account)
        reserve = equity * max(Decimal(0), 1 - sum(weights.values()))
        queue = self._queue(targets, held)
        projected, price_limits = [], {}
        for symbol, side, quantity in queue:
            price = prices[symbol][1 if side == "sell" else 2]
            if side == "sell" and quantity > account["positions"][symbol]["sellable"]:
                raise LiveError("目标需要卖出的数量超过可卖份额；请先核对。")
            price_limits[symbol] = price
            projected.append({"symbol": symbol, "side": side, "quantity": quantity, "price_limit": str(price),
                              "notional": str(quantity * price)})
        good_budget = (sum(Decimal(r["notional"]) for r in projected) <= min(self.budget, self.desk.daily_limit)
                       and all(Decimal(r["notional"]) <= self.desk.single_limit for r in projected))
        plan = Plan(secrets.token_urlsafe(24), strategy, now.date().isoformat(), signal, time.monotonic() + 60,
                    targets, held, reserve, price_limits)
        self.plan = plan if good_budget and projected else None
        return {"strategy": strategy, "token": plan.token if self.plan else None, "targets": targets, "orders": projected,
                "cash_reserve_cny": str(reserve), "auto_enabled": self.enabled, "expires_in": 60,
                "message": "仅预演，未发单。" if good_budget else "方案超过自动周期或委托限额，不可开启。"}

    def _day_allowed(self, day, orders):
        with closing(self.desk._db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS auto_cycle (day TEXT PRIMARY KEY, strategy TEXT NOT NULL, signal TEXT NOT NULL)")
            if db.execute("SELECT 1 FROM auto_cycle WHERE day=?", (day,)).fetchone():
                raise LiveError("今日已启动过实盘自动周期；不可改策略后重复自动发单。")
            self.desk._reconcile(db, day, orders)

    def start(self, owner, fields, read, access):
        client = self.desk._order_client(owner)
        if not self.enabled or not self.equity_field or not access():
            raise LiveError("本部署尚未开放自动委托，或网络授权已经失效。")
        plan = self.plan
        if (not plan or fields.get("confirmation") != AUTO_CONFIRMATION or self.active
                or fields.get("token") != plan.token or time.monotonic() >= plan.expires):
            raise LiveError("请重新预演，并输入「确认自动委托」。")
        now = dt(self.desk.now())
        signal, *_ = self._market(read, plan.strategy, now)
        if plan.day != now.date().isoformat() or signal != plan.signal:
            raise LiveError("已确认的信号变化，必须重新预演。")
        self._day_allowed(plan.day, _rows(self.desk._query(client.query_orders)))
        self.read, self.access = read, access
        self.stop_requested.clear()
        self.deadline = time.monotonic() + self.cycle_seconds
        self.next_tick, self.used, self.pending, self.reserved = 0, Decimal(0), None, False
        self.desk.draft = None
        self.active = True
        self.note = "已授权，等待交易条件。现在可在网页停止。"
        return self.status()

    def _filled(self, orders, plan):
        receipt, symbol, side, quantity = self.pending
        rows = [r for r in orders if r.get("Wtbh") == receipt and r.get("Wtrq") == plan.day.replace("-", "")
                and r.get("Zqdm") == SECURITIES[symbol][0]]
        if len(rows) != 1:
            raise LiveError("券商委托记录未能唯一匹配；自动委托已停止。")
        row = rows[0]
        state = row.get("Wtzt")
        if str(row.get("Wtsl")) != str(quantity):
            raise LiveError("券商委托数量不匹配；自动委托已停止。")
        if state in ("未报", "待报", "已报", "已受理") and str(row.get("Cjsl")) in ("0", "None"):
            return False
        if state not in ("已成", "已成交") or str(row.get("Cjsl")) != str(quantity):
            raise LiveError("券商未确认整笔成交（可能部分成交、撤单或字段未知）；自动委托已停止。")
        plan.held[symbol] += quantity if side == "buy" else -quantity
        self.pending = None
        return True

    def _allowed(self):
        return self.active and not self.stop_requested.is_set() and time.monotonic() < self.deadline and self.access()

    def _tick(self):
        desk, plan = self.desk, self.plan
        owner = desk.owner
        client = desk._order_client(owner, automatic=True)
        if not self._allowed():
            raise LiveError("自动周期或配对授权已失效；自动委托已停止。")
        orders = _rows(desk._query(client.query_orders))
        if len(orders) >= 100:
            raise LiveError("券商委托列表可能被截断；自动委托已停止。")
        if self.pending and not self._filled(orders, plan):
            return
        if any(str(r.get("Wtzt")) not in TERMINAL for r in orders):
            raise LiveError("检测到未结委托；自动委托已停止。")
        account = self._account(client)
        if self._held(account) != plan.held:
            raise LiveError("券商实际持仓与已核对的成交不一致；自动委托已停止。")
        queue = self._queue(plan.targets, plan.held)
        if not queue:
            with closing(desk._db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                desk._reconcile(db, plan.day, orders)
            self.stop("本轮目标已达到。请在券商官方客户端复核。")
            return

        def read_market():
            if not self._allowed():
                raise LiveError("自动委托授权已失效。")
            view = self.read(plan.strategy)
            if (view.get("signal") or {}).get("id") != plan.signal or dt(desk.now()).date().isoformat() != plan.day:
                raise LiveError("信号或执行日已变化；不得继续旧方案。")
            return view

        now = dt(desk.now())
        _, _, _, prices, _ = self._market(lambda _: read_market(), plan.strategy, now)
        symbol, side, quantity = queue[0]
        price = prices[symbol][1 if side == "sell" else 2]
        if side == "sell":
            price = max(price, plan.price_limits[symbol])
        else:
            price = min(price, plan.price_limits[symbol])
        notional = price * quantity
        if self.used + notional > self.budget:
            raise LiveError("自动周期金额已达上限；未发出下一笔委托。")
        draft = desk.draft_order(owner, {"symbol": symbol, "side": side, "price": str(price), "quantity": quantity},
                                 read_market, automatic=True, strategy=plan.strategy)

        def preflight(latest, _records):
            if not self._allowed() or self._held(latest) != plan.held:
                raise LiveError("账户持仓或自动授权变化；未提交委托。")
            if side == "buy" and Decimal(latest["available_cash"]) - notional - max(Decimal(5), notional * Decimal("0.001")) < plan.reserve:
                raise LiveError("资金尚未可用，或此单会侵占策略保留现金；未提交委托。")
            if not self.reserved:
                with closing(desk._db()) as db, db:
                    db.execute("INSERT INTO auto_cycle VALUES (?,?,?)", (plan.day, plan.strategy, plan.signal))
                self.reserved = True

        trade = desk.submit(owner, {"order_token": draft["order_token"], "confirmation": CONFIRMATION}, read_market,
                            automatic=True, strategy=plan.strategy, preflight=preflight)
        self.used += notional
        if trade["state"] != "submitted":
            raise LiveError("报单结果不明；自动委托已停止，请到券商端核对，勿重发。")
        self.pending = trade["broker_receipt"], symbol, side, quantity
        self.note = "已收到券商委托回执，等待核实完整成交。"

    def tick(self):
        if not self.active or time.monotonic() < self.next_tick:
            return
        self.next_tick = time.monotonic() + 3
        try:
            if dt(self.desk.now()).date().isoformat() != self.plan.day:
                raise LiveError("自动周期已跨日；需要重新授权。")
            self._tick()
        except LiveError as exc:
            self.stop(str(exc))
        except Exception:
            self.stop("自动执行异常；不会重试。请到券商端核对。")
