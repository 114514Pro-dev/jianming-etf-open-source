"""Account-bound WeChat subscriptions and the transactional paper notification outbox."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import uuid


CN = timezone(timedelta(hours=8))
NAMES = {"sh512800": "银行ETF 512800", "sz159915": "创业板ETF 159915",
         "sh518880": "黄金ETF 518880", "sh511010": "国债ETF 511010", "cash": "现金"}
DELIVERY_REASONS = frozenset(("rate_limited", "http_rejected", "unexpected_response", "provider_accepted",
    "missing_receipt", "unauthorized", "invalid_request", "quota_exhausted", "provider_restricted",
    "invalid_token", "verification_required", "provider_error", "connect_failed", "connection_interrupted",
    "worker_stopping"))


class NotificationError(ValueError):
    def __init__(self, code, status, message):
        super().__init__(message)
        self.code = code
        self.status_code = status


def _binding(account):
    return json.dumps([account["strategy"], account["id"], account["created_at"]], separators=(",", ":"))


def _targets(signal):
    weights = {s: Decimal(signal["weights"].get(s, "0")) for s in NAMES if s != "cash"}
    weights["cash"] = 1 - sum(weights.values())
    return weights


def _percent(weight):
    return format(weight * 100, ".4f").rstrip("0").rstrip(".") + "%"


def _date_text(stamp):
    return datetime.fromtimestamp(stamp, CN).isoformat()


class PaperNotifications:
    def __init__(self, connection, clock, strategy):
        self._connection = connection
        self._clock = clock
        self.strategy = strategy

    @staticmethod
    def initialize(db):
        db.execute("""CREATE TABLE IF NOT EXISTS wechat_subscriptions (
            binding TEXT PRIMARY KEY, enabled INTEGER NOT NULL, orders_enabled INTEGER NOT NULL,
            enabled_at REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS wechat_outbox (
            id INTEGER PRIMARY KEY, binding TEXT NOT NULL, kind TEXT NOT NULL, event_id TEXT NOT NULL,
            title TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
            status TEXT NOT NULL, due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            lease TEXT, receipt TEXT, reason TEXT, expires REAL, retry_allowed INTEGER NOT NULL DEFAULT 1,
            UNIQUE(binding,kind,event_id))""")
        db.execute("CREATE INDEX IF NOT EXISTS wechat_due ON wechat_outbox(status,due,id)")
        db.execute("CREATE INDEX IF NOT EXISTS wechat_recent ON wechat_outbox(binding,id DESC)")

    @contextmanager
    def _transaction(self, write=False):
        with closing(self._connection()) as db, db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db

    def _account(self, db):
        row = db.execute("""SELECT json_extract(data,'$.account.id'),
            json_extract(data,'$.account.created_at'),json_extract(data,'$.account.strategy')
            FROM ledger WHERE id=1""").fetchone()
        if not row or row[0] is None:
            return None
        if not row[1] or row[2] != self.strategy:
            raise NotificationError("NOTIFICATION_BINDING", 409, "模拟账户绑定已变化，请刷新")
        return {"id": row[0], "created_at": row[1], "strategy": row[2]}

    def _require_account(self, db, account_id, account_created_at):
        account = self._account(db)
        if not account:
            raise NotificationError("NOTIFICATION_ACCOUNT", 409, "请先创建模拟账户")
        if (account["id"], account["created_at"]) != (account_id, account_created_at):
            raise NotificationError("NOTIFICATION_BINDING", 409, "模拟账户绑定已变化，请刷新")
        return account

    def _settings(self, db, account):
        result = {"strategy": self.strategy, "account_id": None, "account_created_at": None,
                  "enabled": False, "orders_enabled": False, "last_delivery": None}
        if account is None:
            return result
        result.update(account_id=account["id"], account_created_at=account["created_at"])
        binding = _binding(account)
        row = db.execute("SELECT enabled,orders_enabled FROM wechat_subscriptions WHERE binding=?",
                         (binding,)).fetchone()
        if row:
            result.update(enabled=bool(row[0]), orders_enabled=bool(row[1]))
        last = db.execute("""SELECT kind,status,created,updated,reason FROM wechat_outbox
            WHERE binding=? ORDER BY id DESC LIMIT 1""", (binding,)).fetchone()
        if last:
            result["last_delivery"] = dict(kind=last[0], status=last[1], created_at=_date_text(last[2]),
                                           updated_at=_date_text(last[3]), reason=last[4])
        return result

    def settings(self):
        with self._transaction() as db:
            return self._settings(db, self._account(db))

    def _cancel(self, db, binding, reason, signals=True, orders=True):
        # A request already in transit cannot be recalled. Prevent a later retry even if
        # the account or subscription has been reactivated before that request finishes.
        db.execute("""UPDATE wechat_outbox SET retry_allowed=0,reason=?,updated=?,
            status=CASE WHEN status='sending' THEN status ELSE 'cancelled' END
            WHERE binding=? AND status IN ('pending','retry','sending')
            AND ((kind='signal' AND ?) OR (kind='order' AND ?))""",
                   (reason, self._clock().timestamp(), binding, signals, orders))

    def account_paused(self, db, account):
        self._cancel(db, _binding(account), "account_paused")

    def save_settings(self, account_id, account_created_at, enabled, orders_enabled):
        if type(enabled) is not bool or type(orders_enabled) is not bool or (orders_enabled and not enabled):
            raise NotificationError("NOTIFICATION_INVALID", 400, "请核对微信提醒选项")
        with self._transaction(write=True) as db:
            account = self._require_account(db, account_id, account_created_at)
            binding = _binding(account)
            now = self._clock().timestamp()
            db.execute("""INSERT INTO wechat_subscriptions(binding,enabled,orders_enabled,enabled_at)
                VALUES(?,?,?,?) ON CONFLICT(binding) DO UPDATE SET enabled=excluded.enabled,
                orders_enabled=excluded.orders_enabled, enabled_at=CASE WHEN enabled=0 AND excluded.enabled=1
                THEN excluded.enabled_at ELSE enabled_at END""", (binding, enabled, orders_enabled, now))
            self._cancel(db, binding, "subscription_disabled", signals=not enabled, orders=not orders_enabled)
            return self._settings(db, account)

    def _enqueue(self, db, binding, kind, event_id, title, content, *, expires=None):
        now = self._clock().timestamp()
        db.execute("""INSERT INTO wechat_outbox
            (binding,kind,event_id,title,content,created,updated,status,due,expires)
            VALUES(?,?,?,?,?,?,?,'pending',?,?) ON CONFLICT(binding,kind,event_id) DO NOTHING""",
                   (binding, kind, event_id, title, content, now, now, now, expires))

    def queue_test(self, account_id, account_created_at):
        with self._transaction(write=True) as db:
            account = self._require_account(db, account_id, account_created_at)
            binding = _binding(account)
            recent = db.execute("""SELECT 1 FROM wechat_outbox WHERE binding=? AND kind='test'
                AND created>? LIMIT 1""", (binding, self._clock().timestamp() - 60)).fetchone()
            if recent:
                raise NotificationError("NOTIFICATION_RATE_LIMIT", 429, "测试提醒每分钟最多一次")
            self._enqueue(db, binding, "test", uuid.uuid4().hex, "简明ETF · 微信提醒测试",
                          f"{self.strategy} 实时模拟的微信提醒测试。")
            return self._settings(db, account)

    def record_signal(self, db, account, previous, signal):
        if (not account or not account.get("running") or not previous or previous["id"] == signal["id"]
                or previous.get("valid") is not True or signal.get("valid") is not True):
            return
        binding = _binding(account)
        row = db.execute("SELECT enabled_at FROM wechat_subscriptions WHERE binding=? AND enabled=1",
                         (binding,)).fetchone()
        if not row:
            return
        # On first poll after enabling/resuming the observer can rediscover an older daily close.
        start = max(datetime.fromtimestamp(row[0], CN), datetime.fromisoformat(account["resumed_at"]))
        if signal["day"] < start.astimezone(CN).date().isoformat() or datetime.fromisoformat(signal["signal_at"]) < start:
            return
        before, after = _targets(previous), _targets(signal)
        changes = []
        for symbol, name in NAMES.items():
            if before[symbol] == after[symbol]:
                continue
            old, new = _percent(before[symbol]), _percent(after[symbol])
            change = f"{old} → {new}" if old != new else f"约 {new}（变动不足 0.0001 个百分点）"
            changes.append(f"{name}　{change}")
        if changes:
            self._cancel(db, binding, "signal_superseded")
            execution_day = signal.get("execution_day") or datetime.fromisoformat(signal["eligible_at"]).date().isoformat()
            composition = "、".join(f"{name} {_percent(after[symbol])}" for symbol, name in NAMES.items()
                                   if after[symbol] > 0)
            body = "\n".join([f"{signal['day']} 确认目标调仓", *changes, f"本次目标组合：{composition}",
                              f"策略依据：{signal['reason'][:500]}",
                              f"最早执行日：{execution_day}"])
            session_close = datetime.fromisoformat(signal["eligible_at"]).astimezone(CN).replace(
                hour=14, minute=57, second=0, microsecond=0)
            self._enqueue(db, binding, "signal", signal["id"], f"简明ETF · {self.strategy} 模拟调仓", body,
                          expires=session_close.timestamp())

    def record_order(self, db, account, order):
        binding = _binding(account)
        if not db.execute("""SELECT 1 FROM wechat_subscriptions WHERE binding=?
                AND enabled=1 AND orders_enabled=1""", (binding,)).fetchone():
            return
        side = "买入" if order["side"] == "buy" else "卖出"
        body = (f"模拟委托提交时尚未成交。\n{side} {NAMES[order['symbol']]}　{order['qty']} 份"
                f"\n模拟限价：{order['limit_price']} 元\n提交时间：{order['submitted_at']}")
        self._enqueue(db, binding, "order", order["id"], f"简明ETF · {self.strategy} 模拟委托已提交", body,
                      expires=datetime.fromisoformat(order["expires_at"]).timestamp())

    @staticmethod
    def _ready(db, now):
        return db.execute("""SELECT id FROM wechat_outbox WHERE status IN ('pending','retry','sending')
            AND due<=? ORDER BY id LIMIT 1""", (now,)).fetchone()

    def claim(self):
        now = self._clock().timestamp()
        # Most polls have no work. Check the queue index before acquiring the ledger write lock.
        with self._transaction() as db:
            if not self._ready(db, now):
                return None
        with self._transaction(write=True) as db:
            db.execute("""UPDATE wechat_outbox SET status='uncertain',reason='send_interrupted',updated=?,lease=NULL
                WHERE status='sending' AND due<=?""", (now, now))
            db.execute("""UPDATE wechat_outbox SET status='cancelled',reason='notification_expired',updated=?
                WHERE status IN ('pending','retry') AND expires<=?""", (now, now))
            row = self._ready(db, now)
            if not row:
                return None
            event_id = row[0]
            binding, kind, title, content, attempts = db.execute("""SELECT binding,kind,title,content,attempts
                FROM wechat_outbox WHERE id=?""", (event_id,)).fetchone()
            account = self._account(db)
            if not account or _binding(account) != binding:
                db.execute("""UPDATE wechat_outbox SET status='cancelled',reason='account_changed',updated=?
                    WHERE id=?""", (now, event_id))
                return None
            lease = uuid.uuid4().hex
            db.execute("""UPDATE wechat_outbox SET status='sending',attempts=attempts+1,lease=?,due=?,updated=?
                WHERE id=?""", (lease, now + 60, now, event_id))
            return dict(id=event_id, lease=lease, kind=kind, title=title, content=content,
                        attempts=attempts + 1, receipt=None)

    def finish(self, id, lease, status, *, receipt=None, delay=0, reason=None):
        if status not in {"sent", "accepted", "failed", "uncertain", "retry"}:
            raise ValueError("invalid delivery status")
        if reason is not None and reason not in DELIVERY_REASONS:
            reason = "delivery_error"
        with self._transaction(write=True) as db:
            now = self._clock().timestamp()
            # If an opt-out raced with IO, a definitely unsuccessful send must not be scheduled again.
            if status == "retry":
                cancelled = db.execute("SELECT reason FROM wechat_outbox WHERE id=? AND retry_allowed=0",
                                       (id,)).fetchone()
                if cancelled:
                    status, reason = "cancelled", cancelled[0]
            db.execute("""UPDATE wechat_outbox SET status=?,updated=?,due=?,receipt=?,reason=?,lease=NULL
                WHERE id=? AND lease=? AND status='sending'""",
                       (status, now, now + delay, receipt, reason, id, lease))
