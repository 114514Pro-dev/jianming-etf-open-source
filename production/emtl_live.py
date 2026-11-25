"""Opt-in, manual EMTL limit orders. No scheduled execution or automatic retry."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from d0_order_preview import _market
from d0_order_math import LOT, MAX_ORDER_QTY, SYMBOLS
from realtime_paper_engine import D, TZ, dt

CONFIRMATION = "确认实盘"
DEFAULT_SINGLE = Decimal("800000")
DEFAULT_DAILY = HARD_LIMIT = Decimal("5000000")


class LiveError(ValueError):
    """Only display-safe broker and validation messages cross the API boundary."""


def _limits(single, daily):
    if not all(isinstance(value, str) and re.fullmatch(r"[0-9]{1,7}(?:\.[0-9]{1,2})?", value)
               for value in (single, daily)):
        raise LiveError("限额须为正数，最多两位小数。")
    single, daily = D(single), D(daily)
    if not 0 < single <= daily <= HARD_LIMIT:
        raise LiveError("单笔限额不能高于单日限额，两者均不能超过 500 万元。")
    return single, daily


SECURITIES = {s: (s[2:], "SA" if s.startswith("sz") else "HA") for s in SYMBOLS}
TERMINAL = frozenset({"已成", "已成交", "已撤", "已撤单", "废单", "部撤"})


def _rows(payload):
    if (not isinstance(payload, dict) or type(payload.get("Status")) is not int or payload["Status"] != 0
            or not isinstance(payload.get("Data"), list) or any(not isinstance(row, dict) for row in payload["Data"])):
        raise LiveError("券商响应无法核实；没有提交委托。")
    return payload["Data"]


def _nonnegative(value):
    try:
        number = D(value)
    except ValueError:
        raise LiveError("券商资金或持仓字段无法核实。") from None
    if not 0 <= number <= Decimal("1000000000000"):
        raise LiveError("券商资金或持仓字段无法核实。")
    return number


def _account(payload):
    rows = _rows(payload)
    if len(rows) != 1 or not isinstance(rows[0].get("positions"), list):
        raise LiveError("券商资金持仓格式尚未核实；没有提交委托。")
    row = rows[0]
    cash = _nonnegative(row.get("Kyzj"))
    positions = {}
    for pos in row["positions"]:
        if not isinstance(pos, dict) or not isinstance(pos.get("Zqdm"), str) or not re.fullmatch(r"[0-9]{6}", pos["Zqdm"]):
            raise LiveError("券商持仓格式尚未核实；没有提交委托。")
        code = pos["Zqdm"]
        held, sellable = _nonnegative(pos.get("Zqsl")), _nonnegative(pos.get("Kysl"))
        if (code in positions or not sellable <= held
                or any(v != v.to_integral_value() for v in (held, sellable))):
            raise LiveError("券商持仓数量异常或代码重复；没有提交委托。")
        positions[code] = {"held": int(held), "sellable": int(sellable)}
    return {"available_cash": str(cash), "positions": {s: positions.get(code, {"held": 0, "sellable": 0}) for s, (code, _) in SECURITIES.items()}}


def _receipt(payload, day):
    try:
        rows = _rows(payload)
    except LiveError:
        return None
    if len(rows) != 1 or rows[0].get("Wtrq") != day.replace("-", ""):
        return None
    broker_id = rows[0].get("Wtbh")
    return broker_id if isinstance(broker_id, str) and re.fullmatch(r"[0-9]{1,24}", broker_id) else None


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    price: Decimal
    quantity: int

    @property
    def notional(self):
        return self.price * self.quantity

    def public(self):
        return {"symbol": self.symbol, "side": self.side, "price": str(self.price),
                "quantity": self.quantity, "notional": str(self.notional)}


class BrokerDesk:
    connection_seconds = 300
    draft_seconds = 30

    def __init__(self, path, account, single_limit, daily_limit, client_factory, *, enrollment_sha256=None,
                 now=lambda: datetime.now(TZ)):
        self.path, self.factory = Path(path), client_factory
        self.enrollment_sha256 = enrollment_sha256
        self.account_tag = None
        self.session_tail = None
        self.single_limit, self.daily_limit, self.now = single_limit, daily_limit, now
        self.lock = threading.RLock()
        self.owner = self.client = self.timer = self.draft = None
        self.expires = self.next_login = 0
        with closing(self._db()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS intent (id TEXT PRIMARY KEY, day TEXT NOT NULL, symbol TEXT NOT NULL, "
                       "side TEXT NOT NULL, price TEXT NOT NULL, qty INTEGER NOT NULL, notional TEXT NOT NULL, "
                       "state TEXT NOT NULL, receipt TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS broker_policy (id INTEGER PRIMARY KEY CHECK(id = 1), "
                       "account_tag TEXT NOT NULL, single_cap TEXT, daily_cap TEXT)")
            row = db.execute("SELECT * FROM broker_policy WHERE id=1").fetchone()
            configured_tag = sha256(account.encode()).hexdigest() if account else None
            if row is None:
                if db.execute("SELECT 1 FROM intent LIMIT 1").fetchone():
                    raise RuntimeError("旧委托日志缺少账户绑定；请先人工核对。")
                if configured_tag:
                    db.execute("INSERT INTO broker_policy VALUES (1, ?, NULL, NULL)", (configured_tag,))
                    self.account_tag = configured_tag
                elif not self.enrollment_sha256:
                    raise RuntimeError("未绑定资金账号，且未配置首次绑定开通码。")
            else:
                self.account_tag = row["account_tag"]
                if configured_tag and not secrets.compare_digest(self.account_tag, configured_tag):
                    raise RuntimeError("委托日志属于另一资金账号；须人工核对后使用独立日志。")
                if row["single_cap"] is not None:
                    self.single_limit, self.daily_limit = _limits(row["single_cap"], row["daily_cap"])

    @property
    def bound(self):
        return self.account_tag is not None

    @classmethod
    def from_env(cls, path):
        from emtl import TradingClient
        from requests import Session

        def direct_session():
            result = Session()
            result.trust_env = False
            return result

        if version("emtl") != "0.3.1":
            raise RuntimeError("EMTL 网页交易需要锁定 emtl==0.3.1")
        account = os.environ.get("ETF_EMTL_ACCOUNT", "")
        if account and not re.fullmatch(r"[0-9]{6,20}", account):
            raise RuntimeError("ETF_EMTL_ACCOUNT 格式无效")
        enrollment = os.environ.get("ETF_EMTL_ENROLLMENT_SHA256", "")
        if enrollment and not re.fullmatch(r"[a-f0-9]{64}", enrollment):
            raise RuntimeError("ETF_EMTL_ENROLLMENT_SHA256 格式无效")
        single, daily = _limits(os.environ.get("ETF_EMTL_MAX_ORDER_CNY", str(DEFAULT_SINGLE)),
                                os.environ.get("ETF_EMTL_MAX_DAY_CNY", str(DEFAULT_DAILY)))
        return cls(path, account, single, daily, lambda **settings: TradingClient(session_factory=direct_session, **settings),
                   enrollment_sha256=enrollment or None)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _close_client(client):
        try:
            if client is not None:
                client.close()
        except Exception:
            pass

    def _drop(self):
        if self.timer:
            self.timer.cancel()
        client = self.client
        self.owner = self.client = self.timer = self.draft = self.session_tail = None
        self.expires = 0
        self._close_client(client)

    def _expire(self, reference):
        with self.lock:
            if reference is self.client:
                self._drop()

    def close(self):
        with self.lock:
            self._drop()

    def _current(self, owner):
        if self.client and time.monotonic() >= self.expires:
            self._drop()
        return self.client if self.owner == owner else None

    def disconnect(self, owner):
        with self.lock:
            if self._current(owner):
                self._drop()
            return {"connected": False}

    @staticmethod
    def _query(fn):
        try:
            return fn()
        except Exception:
            # Transport failures may embed broker tokens or URLs.
            raise LiveError("券商查询未成功；请核对连接状态。") from None

    def connect(self, owner, username, password):
        return self._authenticate(owner, username, password)

    def enroll(self, owner, fields):
        if fields.get("confirmation") != "同意绑定":
            raise LiveError("请输入「同意绑定」，确认此资金账号是唯一操作账户。")
        code = fields.get("enrollment_code")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", code):
            raise LiveError("开通码无效。")
        return self._authenticate(owner, fields.get("username"), fields.get("password"), enrollment_code=code)

    def _authenticate(self, owner, username, password, *, enrollment_code=None):
        if (not isinstance(username, str) or not re.fullmatch(r"[0-9]{6,20}", username)
                or not isinstance(password, str) or not password.strip() or len(password) > 128):
            raise LiveError("无法连接：资金账号或登录信息无效。")
        tag = sha256(username.encode()).hexdigest()
        with self.lock:
            if enrollment_code is not None:
                if self.bound:
                    raise LiveError("已经绑定唯一实盘账号，网页不能更换。")
                if not self.enrollment_sha256 or not secrets.compare_digest(
                        sha256(enrollment_code.encode()).hexdigest(), self.enrollment_sha256):
                    raise LiveError("开通码无效。")
            elif not self.bound or not secrets.compare_digest(tag, self.account_tag):
                raise LiveError("无法连接：此资金账号未获准。")
            self._current(owner)
            if self.client:
                raise LiveError("已有券商连接；请先断开，或等待原连接失效。")
            if time.monotonic() < self.next_login:
                raise LiveError("券商登录请求过于频繁，请稍后再试。")
            self.next_login = time.monotonic() + 5
            client = None
            try:
                client = self.factory(username=username, password=password, connect_timeout=4,
                                      read_timeout=10, captcha_read_timeout=8, captcha_max_attempts=2)
                if not client.login(duration=5):
                    raise ValueError
                # Validate only what the dashboard and pre-submit checks consume.
                account = _account(client.query_asset_and_position())
                _rows(client.query_orders())
            except Exception:
                self._close_client(client)
                raise LiveError("券商登录或只读核对失败；请核对密码、账户权限及响应格式。") from None
            if enrollment_code is not None:
                try:
                    with closing(self._db()) as db, db:
                        db.execute("BEGIN IMMEDIATE")
                        if db.execute("SELECT 1 FROM broker_policy WHERE id=1").fetchone():
                            raise LiveError("已经绑定唯一实盘账号，网页不能更换。")
                        db.execute("INSERT INTO broker_policy VALUES (1, ?, NULL, NULL)", (tag,))
                except BaseException:
                    self._close_client(client)
                    raise
                self.account_tag = tag
                self.enrollment_sha256 = None
            self.owner, self.client, self.session_tail = owner, client, username[-4:]
            self.expires = time.monotonic() + self.connection_seconds
            self.timer = threading.Timer(self.connection_seconds, self._expire, args=(client,))
            self.timer.daemon = True
            self.timer.start()
            return {"connected": True, "account_bound": True, "account_tail": self.session_tail, "limits": self._public_limits(), **account}

    def status(self, owner):
        with self.lock:
            client = self._current(owner)
            if not client:
                return {"connected": False, "account_bound": self.bound}
            return {"connected": True, "account_bound": True, "account_tail": self.session_tail, "limits": self._public_limits(),
                    "remaining_seconds": max(0, int(self.expires - time.monotonic()))}

    def _public_limits(self):
        return {"single_cny": str(self.single_limit), "daily_cny": str(self.daily_limit), "maximum_cny": str(HARD_LIMIT)}

    def update_limits(self, owner, fields):
        with self.lock:
            if not self._current(owner):
                raise LiveError("请先连接已授权的东方财富证券账号。")
            single, daily = _limits(fields.get("single_cny"), fields.get("daily_cny"))
            with closing(self._db()) as db, db:
                db.execute("UPDATE broker_policy SET single_cap=?, daily_cap=? WHERE id=1", (str(single), str(daily)))
            self.single_limit, self.daily_limit = single, daily
            self.draft = None
            return self._public_limits()

    def _readiness(self, order, read_market):
        try:
            now = dt(self.now())
            _, _, _, prices, _ = _market(read_market(), now)
        except (ValueError, ArithmeticError, KeyError, TypeError):
            raise LiveError("仅在 D0 当前执行日的连续交易时段且行情新鲜时提交；当前不可委托。") from None
        _, low, high = prices[order.symbol]
        if not low <= order.price <= high:
            raise LiveError(f"请以当前 D0 报价附近的限价委托：{low}–{high} 元。")
        return now.date().isoformat()

    def draft_order(self, owner, fields, read_market):
        symbol, side, raw_price, quantity = (fields.get(k) for k in ("symbol", "side", "price", "quantity"))
        if (not isinstance(symbol, str) or symbol not in SECURITIES or side not in ("buy", "sell")
                or not isinstance(raw_price, str) or not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,3})?", raw_price)
                or type(quantity) is not int or not LOT <= quantity <= MAX_ORDER_QTY or quantity % LOT):
            raise LiveError("请选择 D0 的 ETF 和买卖方向；价格最多三位小数，份额必须是 100 的整数倍。")
        order = Order(symbol, side, Decimal(raw_price), quantity)
        with self.lock:
            if not self._current(owner):
                raise LiveError("请先连接东方财富证券。")
            self.draft = None
            if not order.price or order.notional > self.single_limit:
                raise LiveError("委托价格无效或超过单笔金额上限。")
            day = self._readiness(order, read_market)
            token = secrets.token_urlsafe(24)
            self.draft = (token, time.monotonic() + self.draft_seconds, day, order)
            return {"order_token": token, "expires_in": self.draft_seconds, **order.public()}

    def _claim(self, token, day, order, current_orders):
        with closing(self._db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for item in db.execute("SELECT * FROM intent WHERE state != 'terminal'").fetchall():
                if item["state"] != "submitted" or item["day"] != day:
                    raise LiveError("存在未核对的历史委托；请在券商端核对并由管理员处理后再操作。")
                code, _ = SECURITIES[item["symbol"]]
                matches = [r for r in current_orders if r.get("Wtbh") == item["receipt"]
                           and r.get("Wtrq") == day.replace("-", "") and r.get("Zqdm") == code]
                if (len(matches) != 1 or str(matches[0].get("Wtzt")) not in TERMINAL
                        or str(matches[0].get("Wtsl")) != str(item["qty"])):
                    raise LiveError("上笔真实委托尚未看到明确终态。")
                db.execute("UPDATE intent SET state='terminal' WHERE id=?", (item["id"],))
            if any(str(r.get("Wtzt")) not in TERMINAL for r in current_orders):
                raise LiveError("券商有未结或状态未知的委托，请先核对。")
            used = sum(Decimal(r[0]) for r in db.execute("SELECT notional FROM intent WHERE day=?", (day,)))
            if used + order.notional > self.daily_limit:
                raise LiveError("超过控制台的本日委托金额上限。")
            db.execute("INSERT INTO intent VALUES (?, ?, ?, ?, ?, ?, ?, 'sending', NULL)",
                       (token, day, order.symbol, order.side, str(order.price), order.quantity, str(order.notional)))

    def submit(self, owner, fields, read_market):
        with self.lock:
            client = self._current(owner)
            if not client or not self.draft:
                raise LiveError("连接或确认已失效，请重新核对委托。")
            token, expires, day, order = self.draft
            if (fields.get("order_token") != token or time.monotonic() >= expires
                    or fields.get("confirmation") != CONFIRMATION):
                raise LiveError("委托确认已失效或确认文字不正确。")
            self.draft = None
            account = _account(self._query(client.query_asset_and_position))
            orders = _rows(self._query(client.query_orders))
            if len(orders) >= 100:
                raise LiveError("券商当日委托记录可能被截断，请人工核对；没有提交委托。")
            if self._current(owner) is not client or time.monotonic() >= expires or self._readiness(order, read_market) != day:
                raise LiveError("行情或确认已过期；没有提交委托。")
            if order.side == "sell" and order.quantity > account["positions"][order.symbol]["sellable"]:
                raise LiveError("券商可卖份额不足。")
            if order.side == "buy" and order.notional + max(Decimal(5), order.notional * Decimal("0.001")) > Decimal(account["available_cash"]):
                raise LiveError("券商可用资金不足（含预留手续费）。")
            self._claim(token, day, order, orders)
            code, exchange = SECURITIES[order.symbol]
            try:
                response = client.create_order(code, "B" if order.side == "buy" else "S", exchange,
                                               float(order.price), order.quantity)
                receipt = _receipt(response, day)
            except Exception:
                receipt = None
            state = "submitted" if receipt else "unknown"
            try:
                with closing(self._db()) as db, db:
                    db.execute("UPDATE intent SET state=?, receipt=? WHERE id=?", (state, receipt, token))
            except sqlite3.Error:
                # The durable 'sending' marker still blocks all further trades.
                state, receipt = "unknown", None
            return {"state": state, "broker_receipt": receipt, **order.public()}