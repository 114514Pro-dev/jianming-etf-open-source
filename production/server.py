"""Private web interface for the unchanged SimpleETF trading engines.

Only Runtime's single executor touches Bridge. HTTP handlers use immutable
snapshots or durable jobs. No desktop account directory is used implicitly.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import getpass
import hashlib
from io import BytesIO
import hmac
import json
import logging
import math
import multiprocessing as mp
import os
from pathlib import Path
from ipaddress import ip_address
from urllib.parse import urlsplit
import queue
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
import zlib
from contextlib import asynccontextmanager, contextmanager, closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from d0_connector_sync import ConnectorSync, SyncError
from d0_signal_feed import SignalFeed
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from web_automation import market_schedule
from realtime_paper_rationale import project_holding_rationale
from realtime_paper_charts import project_indicator_history
from realtime_paper_commentary import project_indicator_commentary
from realtime_paper_price_history import project_daily_price_history
from realtime_paper_pnl import project_account_pnl
from realtime_paper_pnl_history import project_account_pnl_history
from realtime_paper_signal_summary import project_signal_summary
from web_auth_sessions import PersistentSessions, SessionStoreUnavailable, DEVICE_TTL

ROOT = Path(__file__).resolve().parent
CN = timezone(timedelta(hours=8))
LOG = logging.getLogger("etfweb")
MAX_UPLOAD = 25 * 1024 * 1024
ACTIONS = {"create", "advance", "compare", "switch", "attach", "refresh", "reference",
           "export", "import", "history_export", "quotes_export", "full_backup", "delete", "restore"}
INTERNAL_ACTIONS = {"quotes", "auto_scan", "auto_advance"}
FINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class PaperApiError(Exception):
    def __init__(self, code, detail, status=400):
        self.code, self.detail, self.status = code, detail, status


class PaperHttpAdapter:
    """Pure presentation adapter for the isolated ledger's durable snapshots.

    Commands keep the ledger's returned first result. This class never polls,
    submits an order, rewrites a signal, or maintains an idempotency cache.
    """
    SYMBOLS = ("sz159915", "sh512800", "sh518880", "sh511010")
    MODEL_VERSION = "observed_new_trade_full_order_estimate"
    REASONS = {
        "quotes_collection_failed": "报价采集失败，连续报价计数已清除；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。",
        "quotes_collection_state_invalid": "报价采集状态无效，等待核对与恢复；恢复后须重新取得故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。",
        "quote_precedes_collection_failure": "当前报价的行情源时间或接收时间不晚于采集故障时点，不能用于恢复；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。",
        "not_observed": "尚未观察到有效资料",
        "context_missing": "尚未记录来源观察状态，等待核对",
        "quotes_missing": "等待当日新鲜报价",
        "quotes_stale": "报价过期，等待后续新鲜报价",
        "quotes_invalid": "报价无效，等待有效资料",
        "quote_queue_delay": "报价接收后的处理延迟过大",
        "daily_data_missing": "缺少确认日线资料",
        "daily_data_invalid": "确认日线资料无效",
        "confirmed_daily_data_missing": "缺少应有确认日资料",
        "calendar_unavailable": "交易日历不在已核验范围",
        "historical_data_revision": "历史资料修订，等待核对",
        "history_baseline_missing": "找不到与原信号一致的可信历史快照，保留账本并等待核对",
        "history_anchor_invalid": "原信号历史凭据无效，等待核对",
        "history_checkpoint_invalid": "D0 历史留存凭据校验失败，等待核对",
        "history_checkpoint_write_failed": "D0 历史留存凭据保存失败，等待恢复",
        "history_continuity_gap": "历史行情日期存在缺失或插入，等待核对",
        "corporate_action_review_required": "公司行动资料需要核对",
        "holdings_history_unverified": "持仓历史资料需要核对",
        "source_unavailable": "数据来源暂不可用",
        "source_read_failed": "读取资料失败，等待重试",
        "worker_iteration_failed": "观察服务异常，等待恢复",
    }

    def __init__(self, service):
        self.service = service
        self.metadata = json.loads((ROOT / "realtime_paper_rules.json").read_text("utf-8-sig"))

    @staticmethod
    def decimal(value):
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise RuntimeError("invalid presentation decimal")
        return format(number, "f")

    @staticmethod
    def moment(value):
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise RuntimeError("presentation timestamp requires timezone")
        return moment.astimezone(CN)

    def now(self):
        current = getattr(self.service, "now", None)
        return self.moment(current() if callable(current) else current) if current is not None else datetime.now(CN)

    def security(self, symbol):
        if symbol not in self.SYMBOLS:
            raise RuntimeError("unsupported presentation symbol")
        return {"symbol": symbol, "code": symbol[2:], "name": self.metadata["symbols"][symbol]["name"]}

    def fees(self, values, version):
        return {"version": version, "rate": self.decimal(values["rate"]),
                "min_fee": self.decimal(values["minimum"]), "slippage_bps": self.decimal(values["slippage_bps"]),
                "label": "模拟费用与滑点假设"}

    def identity(self, account_id, order_id=None):
        raw = self.service.snapshot()
        account = raw.get("account")
        if not account or account.get("id") != account_id:
            raise PaperApiError("ACCOUNT_NOT_FOUND", "未找到此独立模拟账户", 404)
        if order_id is not None and not any(order.get("id") == order_id for order in raw.get("orders", [])):
            raise PaperApiError("ORDER_NOT_FOUND", "未找到此账户的模拟委托", 404)
        return raw

    def snapshot(self):
        return self.view(self.service.snapshot())

    def account_detail(self, account_id):
        result = self.view(self.identity(account_id))
        return {key: value for key, value in result.items() if key != "accounts"} | {"account": result["accounts"][0]}

    def create_account(self, name, initial_cash, idempotency_key):
        return self.view(self.service.create(initial_cash, name=name, idempotency_key=idempotency_key), command=True)

    def configure_capital(self, account_id, initial_cash, idempotency_key):
        self.identity(account_id)
        return self.view(self.service.capital(initial_cash, idempotency_key=idempotency_key), command=True)

    def start_account(self, account_id, idempotency_key):
        self.identity(account_id)
        return self.view(self.service.set_running(True, idempotency_key=idempotency_key), command=True)

    def pause_account(self, account_id, idempotency_key):
        self.identity(account_id)
        return self.view(self.service.set_running(False, idempotency_key=idempotency_key), command=True)

    def cancel_order(self, account_id, order_id, idempotency_key):
        self.identity(account_id, order_id)
        return self.view(self.service.cancel(order_id, idempotency_key=idempotency_key), command=True)

    def market_quotes(self, batch, current):
        # Display-only observation. Never substituted into valuation or fill evidence.
        if not isinstance(batch, dict) or not isinstance(batch.get('quotes'), dict):
            return []
        rows = []
        for symbol in self.SYMBOLS:
            quote = batch['quotes'].get(symbol)
            if not isinstance(quote, dict):
                continue
            try:
                source_at, received_at = self.moment(quote['quote_at']), self.moment(batch['received_at'])
                price = self.decimal(quote['price'])
                age, delay = (current-source_at).total_seconds(), (received_at-source_at).total_seconds()
                receipt_age = (current-received_at).total_seconds()
                fresh = source_at.date() == current.date() and 0 <= age <= 60 and 0 <= delay <= 60 and 0 <= receipt_age <= 60
                if Decimal(price) <= 0:
                    continue
                previous_close, change_ratio = None, None
                try:
                    previous = Decimal(str(quote.get('previous_close')))
                    if previous.is_finite() and 0 < previous <= Decimal('1e100'):
                        ratio = Decimal(price) / previous - 1
                        if ratio.is_finite() and abs(ratio) <= Decimal('1e100'):
                            previous_close, change_ratio = format(previous, 'f'), float(ratio)
                except (ValueError, ArithmeticError):
                    pass
                rows.append({**self.security(symbol), 'price': price, 'quote_at': quote['quote_at'],
                    'previous_close': previous_close, 'change_ratio': change_ratio,
                    'received_at': batch['received_at'], 'source': str(quote.get('source', batch.get('source', '公开报价'))),
                    'fresh': fresh, 'display_only': True, 'age_seconds': age})
            except (KeyError, TypeError, ValueError, ArithmeticError, RuntimeError, AttributeError):
                continue
        return rows

    def price_histories(self, raw, current, command=False):
        result = {'contract_version': 'd0-price-history-v1', 'assets': []}
        if command:
            return result
        # service.snapshot() has already released the ledger lock. This shared
        # reader observes existing samples only and never calls the collector.
        reader = getattr(self.service, 'intraday_charts', None)
        try:
            intraday = reader.snapshot(current) if reader is not None else {}
        except Exception:
            intraday = {}
        daily = raw.get('daily_price_histories') or {}
        for symbol in self.SYMBOLS:
            sampled = intraday.get(symbol) if isinstance(intraday, dict) else None
            if not isinstance(sampled, dict):
                sampled = {'status': 'unavailable', 'reason': 'read_failed', 'session_day': None,
                           'source': 'recorded_public_quotes', 'coverage': 'recorded_samples_only',
                           'points': [], 'truncated': False}
            result['assets'].append({'symbol': symbol, 'intraday': sampled,
                'daily': project_daily_price_history(daily.get(symbol) if isinstance(daily, dict) else None,
                                                     raw.get('signal'), symbol)})
        return result

    def view(self, raw, command=False):
        revision = raw["revision"]
        if not isinstance(revision, str) or not re.fullmatch(r"\d+", revision):
            raise RuntimeError("durable presentation revision required")
        account = raw.get("account")
        events, raw_orders, raw_fills = raw.get("events", []), raw.get("orders", []), raw.get("fills", [])
        # A command result uses only its own durable time, including on retries.
        generated = raw["response_at"] if command else self.now().isoformat()
        current = self.moment(generated)
        account_id = account["id"] if account else None
        orders_by_id = {order["id"]: order for order in raw_orders}
        passed_quote_ids = {fill["evidence"][-1]["id"] for fill in raw_fills if len(fill.get("evidence", [])) == 2}
        quotes, quotes_by_symbol = [], {}
        for symbol, quote in raw.get("quotes", {}).items():
            source_at, received_at = self.moment(quote["quote_at"]), self.moment(quote["received_at"])
            invalid = quote["status"] in {"halted", "unknown"}
            row = {**self.security(symbol), "id": quote["id"], "price": self.decimal(quote["price"]),
                   "previous_close": self.decimal(quote["previous_close"]), "quote_at": quote["quote_at"],
                   "received_at": quote["received_at"], "source": quote["source"], "source_time_kind": "snapshot",
                   "time_precision": "millisecond" if re.search(r":\d{2}\.\d+", quote["quote_at"]) else "second",
                   "source_delay_seconds": (received_at-source_at).total_seconds(),
                   "age_seconds": (current-source_at).total_seconds(), "queue_delay_seconds": (current-received_at).total_seconds(),
                   "cumulative_volume": self.decimal(Decimal(quote["volume_lots"])*100),
                   "cumulative_amount": self.decimal(quote["amount_cny"]),
                   "market_status": "suspended" if quote["status"] == "halted" else "invalid" if invalid else "unverified",
                   "activity_gate": "invalid" if invalid else "passed" if quote["id"] in passed_quote_ids else "waiting",
                   "waiting_reason": "报价状态无效或公司行动待核对" if invalid else None if quote["id"] in passed_quote_ids else "等待委托后的两份有效活动报价"}
            quotes.append(row)
            quotes_by_symbol[symbol] = row
        core_rules = raw["rules"]
        rules = []
        for symbol, rule in core_rules["instruments"].items():
            authority = self.metadata["symbols"][symbol]
            same_rule = (rule["lot"] == authority["buy_qty_lot"] and Decimal(rule["tick"]) == Decimal(authority["price_tick"])
                         and rule["settlement"] == "T"+str(authority["tplus"]) and Decimal(rule["limit_pct"]) == Decimal(authority["limit_pct"]))
            covered = core_rules["coverage_from"] <= current.date().isoformat() <= core_rules["coverage_until"]
            rules.append({**self.security(symbol), "version": core_rules["version"],
                          "effective_from": authority["effective_from"], "effective_to": authority.get("effective_to"),
                          "lot_size": rule["lot"], "price_tick": self.decimal(rule["tick"]),
                          "settlement": "T+0" if rule["settlement"] == "T0" else "T+1",
                          "price_limit_ratio": self.decimal(rule["limit_pct"]), "verified": same_rule and covered,
                          "sources": [self.metadata["sources"][key]["url"] for key in authority["sources"]],
                          "waiting_reason": None if same_rule and covered else "交易规则或模型日历范围需要核对"})
        model_version = raw_fills[-1]["model"] if raw_fills else self.MODEL_VERSION
        model = {"version": model_version, "mode": "quote_driven_estimate", "fill_kind": "whole_order_estimate",
                 "label": "报价驱动整单模拟估计", "limitations": [
                     "公共报价未核验停牌状态。", "没有盘口、排队或可成交量证据。", "模型假设整单流动性，不生成部分成交。",
                     "费用与滑点是模拟参数，不代表实际券商收费。", "公司行动需核对，现有资料缺失不能证明无事件。"],
                 "freshness": {"source_delay_max_seconds": core_rules["source_delay_max_seconds"],
                               "match_age_max_seconds": core_rules["match_age_max_seconds"],
                               "queue_delay_max_seconds": core_rules["queue_delay_max_seconds"], "boundary": "inclusive"},
                 "activity_quotes_required": 2, "windows": ["09:30-11:30", "13:00-14:57"],
                 "timezone": "Asia/Shanghai", "expiry_time": "14:57:00"}
        signal = None
        if raw.get("signal"):
            original = raw["signal"]
            signal = {key: original[key] for key in ("id", "signal_at", "known_at", "data_cutoff", "confirmed_day",
                      "execution_day", "version", "source", "valid", "waiting_reason")}
            signal["weights"] = {symbol: self.decimal(weight) for symbol, weight in original["weights"].items()}
            signal["rationale"] = project_holding_rationale(original)
            if not command and isinstance(raw.get("indicator_histories"), dict):
                for asset in signal["rationale"]["assets"]:
                    asset["indicator_history"] = project_indicator_history(
                        raw["indicator_histories"].get(asset["symbol"]), original, asset["symbol"])
            for asset in signal["rationale"]["assets"]:
                asset["commentary"] = project_indicator_commentary(original, asset)
        fresh = bool(quotes) and all(quote["market_status"] == "unverified" and
                self.moment(quote["quote_at"]).date() == current.date() and
                0 <= quote["source_delay_seconds"] <= 60 and 0 <= quote["age_seconds"] <= 60 and
                0 <= quote["queue_delay_seconds"] <= 5 for quote in quotes)
        source_state = raw.get("source_status")
        if source_state is None:
            # A saved response without source context cannot prove readiness.
            source_state = "waiting"
        elif source_state == "ready" and not fresh:
            # Read-only ageing must not advertise a cached observation as fresh.
            source_state = "waiting"
        reason_code = raw.get("reason", "context_missing" if raw.get("source_status") is None else "not_observed")
        waiting_message = self.REASONS.get(reason_code, "等待有效的确认目标和新鲜报价")
        observed = raw.get("last_observed") or (max((quote["received_at"] for quote in quotes), default=None))
        thread = None if command else getattr(self.service, "_thread", None)
        observer = "error" if reason_code in {"worker_iteration_failed", "source_read_failed"} else "waiting" if source_state != "ready" or command and account and account["running"] else "running" if thread is not None and thread.is_alive() else "stopped"
        service = {"status": "ready" if source_state == "ready" else "degraded", "observer_status": observer,
                   "last_observed_at": observed, "last_error": waiting_message if source_state == "blocked" else None,
                   "reason_code": reason_code, "waiting_reason": waiting_message if source_state != "ready" else None,
                   "calendar_version": core_rules["version"], "calendar_verified_through": self.metadata["verified_through"]}
        service['history_continuity'] = raw.get('history_continuity') if not command else None
        market_quotes = self.market_quotes(raw.get('market_observation'), current) if not command else []
        accounts = []
        if account:
            orders = [{**self.security(order["symbol"]), "id": order["id"], "account_id": account_id,
                       "plan_id": order["plan_id"], "intent_id": order["intent_id"], "signal_id": order["signal_id"],
                       "side": order["side"], "limit_price": self.decimal(order["limit_price"]),
                       "quantity": order["qty"], "remaining_quantity": order["remaining_qty"], "status": order["status"],
                       "waiting_reason": order.get("reason"), **{key: order[key] for key in ("signal_at", "submitted_at", "eligible_at", "expires_at", "rule_version", "fee_version")},
                       "frozen_cash": self.decimal(order["reserved_cash"]), "frozen_quantity": order["reserved_qty"],
                       "cancelable": order["status"] == "pending"} for order in raw_orders]
            fills = []
            for fill in raw_fills:
                evidence = fill["evidence"][-1]
                if evidence["quote_at"] != fill["quote_at"] or evidence["received_at"] != fill["received_at"]:
                    raise RuntimeError("fill quote evidence mismatch")
                fills.append({**self.security(fill["symbol"]), "id": fill["id"], "account_id": account_id,
                              "order_id": fill["order_id"], "plan_id": fill["plan_id"], "intent_id": fill["intent_id"],
                              "signal_id": fill["signal_id"], "quote_id": evidence["id"], "source": evidence["source"],
                              "side": fill["side"], "label": "模拟估计成交", "price": self.decimal(fill["price"]),
                              "quantity": fill["qty"], "gross_amount": self.decimal(fill["gross"]), "fee": self.decimal(fill["fee"]),
                              "slippage_bps": self.decimal(fill["fees"]["slippage_bps"]), "model_version": fill["model"],
                              **{key: fill[key] for key in ("signal_at", "submitted_at", "eligible_at", "quote_at", "received_at", "matched_at", "rule_version", "fee_version")}})
            holdings = []
            for position in raw.get("positions", []):
                if not position["qty"]:
                    continue
                quote = quotes_by_symbol.get(position["symbol"])
                holdings.append({**self.security(position["symbol"]), "quantity": position["qty"],
                                 "frozen_quantity": position["reserved_qty"], "sellable_quantity": position["available_qty"],
                                 "locked_quantity": position["qty"]-position["settled_qty"],
                                 "price": None if position["price"] is None else self.decimal(position["price"]),
                                 "value": None if position["market_value"] is None else self.decimal(position["market_value"]),
                                 "valuation_status": {"current": "fresh", "stale": "stale", "unknown": "missing"}[position["valuation_status"]],
                                 **{key: quote[key] if quote else None for key in ("quote_at", "received_at", "source")},
                                 "quote_id": quote["id"] if quote else None})
            event_types = {"created": "account_created", "submitted": "order_submitted", "cancelled": "order_cancelled",
                           "expired": "order_expired", "rejected": "order_rejected"}
            event_messages = {"created": "已创建默认停止的独立模拟账户", "capital_changed": "已修改模拟本金",
                              "started": "已启用前瞻观察", "paused": "已暂停账户并撤销有效余单", "submitted": "已提交模拟限价委托",
                              "cancelled": "已撤销模拟委托", "expired": "模拟委托已到期", "rejected": "模拟委托被拒绝",
                              "estimated_fill": "已记入整单模拟估计成交", "plan_created": "已建立独立D0执行计划"}
            visible_events = []
            for event in events:
                order = orders_by_id.get(event.get("order_id"), {})
                message = event_messages.get(event["type"], "模拟账户状态更新")
                if event.get("reason") in {"corporate_actions_unknown", "previous_close_changed"}:
                    message += "，资料需要核对"
                visible_events.append({"id": event["id"], "type": event_types.get(event["type"], event["type"]),
                                       "account_id": account_id, "order_id": event.get("order_id"), "fill_id": event.get("fill_id"),
                                       "plan_id": event.get("plan_id", order.get("plan_id")), "at": event["at"], "message": message})
            paused = [event["at"] for event in events if event["type"] == "paused"]
            running = account["running"]
            needs_review = reason_code.startswith("history_") or reason_code in {"historical_data_revision", "corporate_action_review_required", "holdings_history_unverified", "calendar_unavailable"}
            execution = "needs_review" if running and needs_review else "stopped" if not running else "active" if source_state == "ready" else "waiting"
            try:
                signal_summary = project_signal_summary(raw, now=current, source_status=source_state,
                                                        observer_status=observer, command=command)
            except Exception:
                # Optional explanation must never interrupt the account view.
                LOG.exception("D0 signal summary unavailable")
                signal_summary = None
            marked = None if any(holding["value"] is None for holding in holdings) else self.decimal(sum((Decimal(holding["value"]) for holding in holdings), Decimal("0")))
            accounts.append({"id": account_id, "name": account["name"], "strategy": account["strategy"],
                             "status": "running" if running else "paused" if paused else "stopped", "execution_state": execution,
                             "waiting_reason": waiting_message if running and execution != "active" else None,
                             "created_at": account["created_at"], "started_at": account["resumed_at"], "paused_at": paused[-1] if paused else None,
                             "initial_cash": self.decimal(account["initial_capital"]), "cash": self.decimal(account["cash"]),
                             "frozen_cash": self.decimal(account["reserved_cash"]), "available_cash": self.decimal(account["available_cash"]),
                             "holdings_value": marked, "equity": None if account["equity"] is None else self.decimal(account["equity"]),
                             "valuation_status": {"current": "fresh", "stale": "stale", "unknown": "missing"}[account["valuation_status"]],
                             "pnl": project_account_pnl(raw),
                             "pnl_history": project_account_pnl_history(raw),
                             "can_edit_capital": not running and not fills and not any(order["status"] == "pending" for order in orders),
                             "can_start": not running, "can_pause": running, "action_reason": None,
                             "signal": signal, "signal_summary": signal_summary,
                             "plan_id": (raw.get("plan") or {}).get("id"), "holdings": holdings,
                             "orders": orders, "fills": fills, "events": visible_events, "fee_config": self.fees(account["fees"], account["fee_version"])})
        from realtime_paper_alerts import project_trade_alerts
        trade_alerts = project_trade_alerts(
            raw, now=current, source_status=source_state, observer_status=observer, command=command,
            security_names={symbol: self.security(symbol)["name"] for symbol in self.SYMBOLS})
        return {"contract_version": "realtime-paper-v1", "generated_at": current.isoformat(), "revision": revision,
                "accounts": accounts, "model": model, "quotes": quotes, "market_quotes": market_quotes, "rules": rules, "service": service,
                "trade_alerts": trade_alerts, "price_histories": self.price_histories(raw, current, command)}


def frontend_release():
    """One release identity for HTML and its assets, computed at app startup."""
    folder = ROOT / "web_static"
    digest = hashlib.sha256()
    for name in ("index.html", "app.js", "style.css", "locale-en.js", "i18n.js", "company-research.js", "valuation-scenarios.js", "valuation-scenarios.css", "company-review.js", "company-review.css", "quality-checks.js", "quality-checks.css", "featured-strategies.js", "featured-strategies.css", "featured-research-data.js", "d0-control.html", "d0-control.js", "dashboard.css", "dashboard-theme.js"):
        digest.update(name.encode())
        digest.update((folder / name).read_bytes())
    for name in ("realtime-paper.js", "realtime-paper.css", "realtime-paper-comparison.js", "realtime-paper-comparison.css",
                 "realtime-paper-wechat.js"):
        digest.update(name.encode())
        digest.update((folder / name).read_bytes())
    # New research assets share the host's existing cache/version lifecycle.
    digest.update(b"sector-research-host.js")
    digest.update((folder / "sector-research-host.js").read_bytes())
    module_root = ROOT / "sector_research"
    for asset in sorted((module_root / "web").rglob("*")):
        if asset.is_file():
            digest.update(asset.relative_to(module_root).as_posix().encode())
            digest.update(asset.read_bytes())
    for asset in sorted(module_root.glob("*contract.json")):
        digest.update(asset.name.encode())
        digest.update(asset.read_bytes())
    version = digest.hexdigest()[:20]
    html = (folder / "index.html").read_text("utf8").replace("__UI_VERSION__", version)
    return version, html


class BodyLimitMiddleware:
    """Bound actual received bytes, including chunked bodies without a length."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        limit = MAX_UPLOAD + 100000 if scope["path"] == "/api/upload" else 384000 if scope["path"].startswith("/api/research/valuation/") else 24000
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise HTTPException(413, "上传或请求内容过大")
            return message

        await self.app(scope, limited_receive, send)


def stamp():
    return datetime.now(CN).isoformat(timespec="seconds")


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix("." + secrets.token_hex(6) + ".tmp")
    tmp.write_text(dump(value), encoding="utf8")
    os.replace(tmp, path)


def hash_password(password):
    if len(password) < 12:
        raise ValueError("登录口令至少12个字符")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000).hex()
    return f"pbkdf2_sha256$600000${salt}${digest}"


def verify_password(password, encoded):
    try:
        name, rounds, salt, expected = encoded.split("$")
        if name != "pbkdf2_sha256" or not 100000 <= int(rounds) <= 2000000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False


class FolderLock:
    """OS lock survives neither a crash nor a reboot; prevents multiple writers."""
    def __init__(self, path):
        self.file = open(path, "a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("此数据目录已有网页版进程运行；请勿启动多个worker")

    def close(self):
        if self.file.closed:
            return
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()


def copy_business(source, target):
    """Run only with the business executor idle/owned; SQLite uses backup API."""
    source, target = Path(source), Path(target)
    for p in source.rglob("*"):
        rel = p.relative_to(source)
        if rel.parts[0] == "web" or p.is_symlink() or not p.is_file():
            continue
        if p.name.endswith(("-wal", "-shm", ".tmp", ".lock")):
            continue
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".sqlite3":
            with closing(sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)) as old, closing(sqlite3.connect(out)) as new:
                old.backup(new)
        else:
            shutil.copy2(p, out)


def verified_backup_time(path):
    """Fully read an archive and verify its manifest before treating it as a recovery point."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "备份校验.json" not in names:
            raise ValueError("备份条目重复或缺少校验清单")
        manifest = json.loads(archive.read("备份校验.json"))
        hashes = manifest.get("sha256")
        if not isinstance(hashes, dict) or set(hashes) != set(names) - {"备份校验.json"}:
            raise ValueError("备份文件与校验清单不一致")
        for name, expected in hashes.items():
            with archive.open(name) as member:
                actual = hashlib.file_digest(member, "sha256").hexdigest()
            if actual != expected:
                raise ValueError("备份内容SHA256校验失败")
        created = datetime.fromisoformat(manifest["created"])
        if created.tzinfo is None:
            raise ValueError("备份创建时间缺少时区")
        return created.astimezone(CN)


def verify_paper_backup(path):
    """Verify the new component as well as every legacy archive member."""
    from realtime_paper_backup import BACKUP_SCHEMA, PAPER_PATH, WW_PAPER_PATH, HISTORY_PATHS, HISTORY_BACKUP_SCHEMA
    created = verified_backup_time(path)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("备份校验.json"))
        components = manifest.get("components", {})
        component = components.get("realtime_paper", {})
        hashes = manifest["sha256"]
        required = {"realtime_paper": PAPER_PATH}
        if "realtime_paper_ww" in components:
            required["realtime_paper_ww"] = WW_PAPER_PATH
        history_files = set()
        for key, prefix in HISTORY_PATHS.items():
            if key not in components:
                continue
            entry = components[key]
            paths = entry.get("files")
            if (entry.get("schema") != HISTORY_BACKUP_SCHEMA or entry.get("path") != prefix
                    or entry.get("method") != 'guarded-file-copy' or entry.get("integrity") != 'verified'
                    or not isinstance(paths, list) or len(paths) != len(set(paths))
                    or any(not isinstance(name, str) or not name.startswith(prefix + '/')
                           or '..' in name.split('/') or name not in hashes for name in paths)):
                raise ValueError("已确认行情备份组件无效")
            history_files.update(paths)
        if {name for name in hashes if name.startswith("web/")} != set(required.values()) | history_files:
            raise ValueError("备份缺少经校验的独立模拟账户组件")
        for key, relative in required.items():
            component = components[key]
            if (component.get("schema") != BACKUP_SCHEMA or component.get("path") != relative
                    or component.get("method") != "sqlite-backup-api"
                    or component.get("integrity") != "verified"
                    or component.get("sha256") != hashes.get(relative)):
                raise ValueError("备份缺少经校验的独立模拟账户组件")
            if key == "realtime_paper_ww" and component.get("strategy") != "D0I-BOND-WW":
                raise ValueError("独立模拟账户备份策略无效")
            started = datetime.fromisoformat(component["snapshot_started_at"])
            completed = datetime.fromisoformat(component["snapshot_completed_at"])
            if started.tzinfo is None or completed.tzinfo is None or completed < started:
                raise ValueError("独立模拟账户备份时间无效")
    return created


def comparison_process(folder, params, stop, messages, output):
    os.environ["SIMPLE_ETF_HOME"] = str(folder)
    try:
        from web_bridge import Bridge
        bridge = Bridge(folder)
        result = bridge.execute("compare", params, stop, lambda x: messages.put(str(x)))
        atomic_json(output, {"ok": True, "result": result})
    except Exception as exc:
        atomic_json(output, {"ok": False, "error": str(exc)})


class Runtime:
    def __init__(self, folder):
        self.home = Path(folder).resolve()
        # Explicit protection against accidentally selecting the user's desktop ledger.
        desktop = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SimpleETFSimulator"
        if self.home == desktop.resolve():
            raise RuntimeError("网页版须使用独立数据目录；正式桌面账本迁移须先一致性备份")
        self.private = self.home / "web"
        self.private.mkdir(parents=True, exist_ok=True)
        self.lock = FolderLock(self.private / "server.lock")
        for name in ("uploads", "exports", "backups", "scratch"):
            (self.private / name).mkdir(exist_ok=True)
        self.db_path = self.private / "jobs.sqlite3"
        with self.db() as con:
            con.executescript("""
              CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, key TEXT UNIQUE, payload TEXT NOT NULL,
                action TEXT NOT NULL, params TEXT NOT NULL, status TEXT NOT NULL,
                created TEXT NOT NULL, updated TEXT NOT NULL, progress TEXT,
                result TEXT, error TEXT);
              CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL,
                kind TEXT NOT NULL, created REAL NOT NULL);
            """)
            con.execute("UPDATE jobs SET status='interrupted', error=?, updated=? WHERE status IN ('queued','running')",
                        ("服务已重启；请先核对账户当前日期再提交接续，历史任务不会自动重放。", stamp()))
        self.tasks = queue.Queue(maxsize=64)
        self.halt = threading.Event()
        self.shutdown_dependencies = []
        self.shutdown_lock = threading.RLock()
        self.shutdown_verified = False
        self.shutdown_generation = 0
        self._shutdown_in_progress = False
        # Backups must fail closed until the isolated writer is fully bound.
        self.paper_service = None
        self.ww_paper_service = None
        self.ready = threading.Event()
        self.stops = {}
        self.cache = {}
        self.cache_lock = threading.RLock()
        self.submit_lock = threading.RLock()
        self.settings_lock = threading.RLock()
        self.init_error = None
        settings = self.private / "settings.json"
        self.settings = json.loads(settings.read_text("utf8")) if settings.exists() else {}
        self.settings.setdefault("auto_refresh", os.environ.get("ETF_WEB_AUTO_REFRESH", "1") == "1")
        self.settings.setdefault("last_backup", "")
        self.settings.setdefault("auto_simulate", False)
        self.settings.setdefault("paused_accounts", [])
        self.settings.setdefault("auto_backup_required", self.settings["auto_simulate"])
        calendar = json.loads((ROOT / "data/chinext/calendar.json").read_text("utf8"))
        self.sessions = frozenset(calendar["sessions"])
        self.calendar_end = calendar["verified_through"]
        automation_file = self.private / "automation.json"
        self.automation = json.loads(automation_file.read_text("utf8")) if automation_file.exists() else {}
        self.automation["current_action"] = ""
        self.auto_retry = {}
        self.revision_prefix = secrets.token_hex(8)
        self.revision_number = 0
        self.next_refresh = time.time() + 5
        self.next_history = time.time() + 10
        self.next_auto = time.time() + 20
        self.next_backup_attempt = time.time() + 15
        self.last_market_session = None
        from web_signal_board import SignalBoard
        self.signals = SignalBoard(self.private / 'strategy-signals')
        self.thread = threading.Thread(target=self.worker, name="unique-business-executor", daemon=True)
        self.thread.start()
        self.scheduler = threading.Thread(target=self.schedule, name="market-scheduler", daemon=True)
        self.scheduler.start()

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def status(self):
        with self.settings_lock:
            settings = dict(self.settings)
            automation = json.loads(dump(self.automation))
        return {"ready": self.ready.is_set() and not self.init_error and not self.halt.is_set(),
                "error": self.init_error, "time": stamp(),
                "auto_refresh": settings["auto_refresh"],
                "auto_simulate": settings["auto_simulate"],
                "paused_accounts": settings["paused_accounts"],
                "next_refresh_seconds": max(0, round(self.next_refresh - time.time())),
                "next_history_seconds": max(0, round(self.next_history - time.time())),
                "last_backup": settings.get("last_backup", ""),
                "automation": automation,
                "revision": self.revision_prefix + ":" + str(self.revision_number),
                "calendar_verified_through": self.calendar_end,
                **market_schedule(datetime.now(CN), self.sessions, self.calendar_end)}

    def email_draft(self, snapshot_provider, value=None, *, save=False, strategy="D0"):
        from realtime_paper_email_draft import (
            MISSING, SETTINGS_KEY, EmailDraftError, draft_response, prepare_draft, validate_payload)
        if strategy not in ("D0", "D0I-BOND-WW"):
            raise EmailDraftError("EMAIL_DRAFT_INVALID")
        settings_key = SETTINGS_KEY if strategy == "D0" else SETTINGS_KEY + "_ww"
        if save:
            validate_payload(value)
        with self.settings_lock:
            if type(self.settings) is not dict:
                raise EmailDraftError("EMAIL_DRAFT_UNAVAILABLE")
            try:
                snapshot = snapshot_provider()
            except Exception:
                snapshot = None
            saved = self.settings.get(settings_key, MISSING)
            if not save:
                return draft_response(saved, snapshot)
            prepared = prepare_draft(value, snapshot, saved)
            response = draft_response(prepared, snapshot)
            settings = {**self.settings, settings_key: prepared}
            try:
                atomic_json(self.private / "settings.json", settings)
            except Exception:
                raise EmailDraftError("EMAIL_DRAFT_SAVE_FAILED") from None
            self.settings.update(settings)
            return response

    def change_settings(self, value):
        if not isinstance(value, dict) or not value or set(value) - {"auto_refresh", "auto_simulate", "paused_accounts", "account_auto"}:
            raise HTTPException(400, "后台设置无效")
        value = dict(value)
        if "account_auto" in value and value["account_auto"] is None:
            raise HTTPException(400, "单个账户的自动设置无效")
        account_auto = value.pop("account_auto", None)
        if account_auto is not None:
            if (not isinstance(account_auto, dict) or set(account_auto) != {"key", "enabled"} or
                    not isinstance(account_auto["enabled"], bool) or not isinstance(account_auto["key"], str) or
                    not re.fullmatch(r"(original|top5|seven|nasdaq|hangseng|hangtech):[A-Za-z0-9_-]{1,100}", account_auto["key"]) or
                    "paused_accounts" in value):
                raise HTTPException(400, "单个账户的自动设置无效")
            group, account_id = account_auto["key"].split(":", 1)
            if not any(a["id"] == account_id for a in self.query("accounts", group)):
                raise HTTPException(400, "账户不存在")
        elif not value:
            raise HTTPException(400, "后台设置无效")
        for key in ("auto_refresh", "auto_simulate"):
            if key in value and not isinstance(value[key], bool):
                raise HTTPException(400, "后台开关必须为布尔值")
        if "paused_accounts" in value:
            paused = value["paused_accounts"]
            if not isinstance(paused, list) or len(paused) > 500 or any(
                    not isinstance(k, str) or not re.fullmatch(r"(original|top5|seven|nasdaq|hangseng|hangtech):[A-Za-z0-9_-]{1,100}", k) for k in paused):
                raise HTTPException(400, "暂停账户列表无效")
            known = {g + ":" + a["id"] for g in ("original", "top5", "seven", "nasdaq", "hangseng", "hangtech") for a in self.query("accounts", g)}
            if set(paused) - known:
                raise HTTPException(400, "暂停列表包含不存在的账户")
            value = {**value, "paused_accounts": sorted(set(paused))}
        with self.settings_lock:
            if account_auto is not None:
                paused = set(self.settings["paused_accounts"])
                if account_auto["enabled"]:
                    paused.discard(account_auto["key"])
                else:
                    paused.add(account_auto["key"])
                value["paused_accounts"] = sorted(paused)
            if value.get("auto_simulate") and not self.settings["auto_simulate"]:
                self.settings["auto_backup_required"] = True
            self.settings.update(value)
            atomic_json(self.private / "settings.json", self.settings)
            if value.get("auto_refresh"):
                self.next_refresh = self.next_history = time.time()
            if value.get("auto_simulate") or "paused_accounts" in value:
                self.next_auto = time.time()
            # A running original-nine account observes its stop event between days.
            for job in self.jobs():
                p = job["params"]
                if p.get("_automatic") and job["status"] not in FINAL and job["id"] in self.stops:
                    key = p.get("group", "") + ":" + p.get("id", "")
                    if ((job["action"] in {"auto_scan", "auto_advance"} and
                         (not self.settings["auto_simulate"] or key in self.settings["paused_accounts"])) or
                        (job["action"] in {"refresh", "quotes"} and not self.settings["auto_refresh"])):
                        self.stops[job["id"]].set()
        return self.status()

    def record_automation(self, **values):
        with self.settings_lock:
            self.automation.update(values)
            atomic_json(self.private / "automation.json", self.automation)

    def row(self, row):
        if not row:
            raise HTTPException(404, "任务不存在")
        result = dict(row)
        result.pop("key", None)
        result.pop("payload", None)
        result["params"] = json.loads(result["params"])
        result["params"].pop("path", None)
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def jobs(self):
        with self.db() as con:
            # Frequent polling must not push the user's own comparisons/exports
            # off the task page. Full results remain durably addressable by id.
            return [self.row(r) for r in con.execute("""
                WITH selected AS (
                    SELECT id FROM (SELECT id FROM jobs WHERE COALESCE(json_extract(params,'$._automatic'),0)=0 ORDER BY created DESC,rowid DESC LIMIT 40)
                    UNION SELECT id FROM (SELECT id FROM jobs WHERE json_extract(params,'$._automatic')=1 ORDER BY created DESC,rowid DESC LIMIT 20)
                    UNION SELECT id FROM jobs WHERE status IN ('queued','running')
                )
                SELECT id,key,payload,action,params,status,created,updated,progress,NULL AS result,error,
                       (result IS NOT NULL) AS result_available FROM jobs WHERE id IN selected
                ORDER BY created DESC,rowid DESC
            """)]

    def job(self, identity):
        with self.db() as con:
            return self.row(con.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone())

    def update(self, identity, **values):
        values["updated"] = stamp()
        with self.db() as con:
            con.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
                        (*values.values(), identity))

    def submit(self, action, params, key, *, internal=False):
        if not isinstance(action, str) or action not in ACTIONS | (INTERNAL_ACTIONS if internal else set()):
            raise HTTPException(400, "不支持的操作")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
            raise HTTPException(400, "需要8—100位任务幂等编号")
        payload = json.dumps({"action": action, "params": params}, sort_keys=True, ensure_ascii=False)
        if len(payload) > 10000:
            raise HTTPException(400, "任务参数过长")
        with self.submit_lock:
            with self.db() as con:
                prior = con.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
                if prior:
                    if prior["payload"] != payload:
                        raise HTTPException(409, "同一请求编号的参数不一致，请重新操作")
                    return self.row(prior)
                pending = con.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
                if pending >= 12:
                    raise HTTPException(429, "后台任务较多，请等待后再提交")
                identity = secrets.token_hex(16)
                con.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (identity, key, payload, action, dump(params), "queued", stamp(), stamp(), "等待执行", None, None))
            self.stops[identity] = threading.Event()
            try:
                self.tasks.put_nowait(("job", identity))
            except queue.Full:
                self.stops.pop(identity, None)
                self.update(identity, status="failed", error="请求队列已满，请稍后重新提交", progress="未执行")
                raise HTTPException(503, "请求队列已满，请等待当前任务完成后再试")
        return self.job(identity)

    def query(self, name, *args):
        key = (name, *args)
        with self.cache_lock:
            if key in self.cache:
                return json.loads(self.cache[key])
        future = concurrent.futures.Future()
        try:
            self.tasks.put_nowait(("query", (key, future)))
        except queue.Full:
            raise HTTPException(503, "后台正在处理任务，请稍后读取")
        try:
            return future.result(timeout=12)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise HTTPException(503, "后台正在计算，稍后即可读取账户；任务页仍可查看进度")

    def refresh_cache(self, bridge, quotes_only=False):
        # Copy JSON strings, never share mutable Bridge state with HTTP threads.
        with self.cache_lock:
            # Derive detail keys from this refresh's visible account lists. A
            # removed/unreadable account must not survive as an old snapshot.
            keys = {key for key in self.cache if key[0] != "account"}
        keys.update({("catalog",), ("overview",), ("overseas_overview",), *(('accounts', g) for g in ("original", "top5", "seven", "nasdaq", "hangseng", "hangtech"))})
        if quotes_only:
            keys = {("overview",), ("overseas_overview",)}
        new = {}
        for key in sorted(keys, key=lambda item: (item[0] == "overview", item)):
            try:
                result = getattr(bridge, key[0])(*key[1:])
                new[key] = dump(result)
            except Exception:
                LOG.exception("snapshot refresh failed: %s", key[0])
                continue
            if key[0] == "accounts":
                # Warm every visible detail before starting the next long job,
                # including on startup and immediately after create/restore.
                # Only this executor reads Bridge; HTTP threads can keep reading
                # the previous complete generation while we build the next one.
                for row in result:
                    try:
                        detail_key = ("account", key[1], row["id"])
                        new[detail_key] = dump(bridge.account(*detail_key[1:]))
                    except Exception:
                        LOG.exception("snapshot refresh failed: account in %s", key[1])
        with self.cache_lock:
            if quotes_only:
                self.cache.update(new)
            else:
                self.cache = new
            self.revision_number += 1
        if not quotes_only and hasattr(bridge, 'original') and hasattr(bridge, 'overseas'):
            try:
                self.signals.offer(bridge)
            except Exception:
                LOG.exception('Signal board input capture failed; existing results retained')

    def compare(self, params, stop, progress):
        # Freeze a consistent business copy while this unique executor owns it.
        with tempfile.TemporaryDirectory(prefix="etf-compare-", dir=self.private / "scratch") as tmp:
            frozen = Path(tmp) / "data"
            copy_business(self.home, frozen)
            output = Path(tmp) / "result.json"
            ctx = mp.get_context("spawn")
            cancel, messages = ctx.Event(), ctx.Queue()
            child = ctx.Process(target=comparison_process, args=(str(frozen), params, cancel, messages, str(output)))
            child.start()
            try:
                while child.is_alive():
                    if stop.is_set() or self.halt.is_set():
                        cancel.set()
                    try:
                        progress(messages.get(timeout=0.3))
                    except queue.Empty:
                        pass
                child.join()
                if not output.exists():
                    raise RuntimeError("回测进程提前结束，账本未被回测进程写入")
                result = json.loads(output.read_text("utf8"))
                if not result["ok"]:
                    raise ValueError(result["error"])
                return result["result"]
            finally:
                if child.is_alive():
                    child.terminate()
                    child.join()
                messages.close()

    def register_file(self, path, kind="download", name=None):
        path = Path(path).resolve()
        if not path.is_relative_to(self.private.resolve()) or not path.is_file():
            raise ValueError("导出文件位置无效")
        identity = secrets.token_hex(24)
        with self.db() as con:
            con.execute("INSERT INTO files VALUES (?,?,?,?,?)", (identity, str(path), name or path.name, kind, time.time()))
        return {"file_id": identity, "download_url": "/api/download/" + identity,
                "filename": name or path.name, "size": path.stat().st_size}

    def file(self, identity, kind="download"):
        if not re.fullmatch("[a-f0-9]{48}", identity):
            raise HTTPException(404, "文件不存在")
        with self.db() as con:
            row = con.execute("SELECT * FROM files WHERE id=? AND kind=?", (identity, kind)).fetchone()
        if not row:
            raise HTTPException(404, "文件不存在")
        path = Path(row["path"]).resolve()
        if not path.is_relative_to(self.private.resolve()) or not path.is_file():
            raise HTTPException(404, "文件已过期或已清理")
        return path, row["name"]

    def backup(self, automatic=False):
        from realtime_paper_backup import PAPER_PATH, snapshot_business_for_backup
        created = datetime.now(CN)
        dest = self.private / "backups" / (created.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4) + ".zip")
        partial = dest.with_suffix(".partial")
        try:
            with tempfile.TemporaryDirectory(prefix="etf-backup-", dir=self.private / "scratch") as tmp:
                # The existing executor owns old business; the guard also drains
                # and excludes the new worker and every paper HTTP mutation.
                # 900s is an explicit copy/SQLite budget for the existing large
                # business tree, not a hard bound on compression or shutdown.
                component = snapshot_business_for_backup(
                    self.home, tmp, copy_business, self.paper_service, timeout=900,
                    additional_services={"D0I-BOND-WW": self.ww_paper_service}
                    if getattr(self, "ww_paper_service", None) is not None else None)
                components = {"realtime_paper": {key: value for key, value in component.items()
                                                if key != "additional_components"},
                              **component.get("additional_components", {})}
                manifest = {}
                with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as out:
                    for path in Path(tmp).rglob("*"):
                        if path.is_file():
                            relative = path.relative_to(tmp).as_posix()
                            out.write(path, relative)
                            with path.open("rb") as source:
                                manifest[relative] = hashlib.file_digest(source, "sha256").hexdigest()
                    if PAPER_PATH not in manifest:
                        raise ValueError("独立模拟账户备份组件缺失")
                    for value in components.values():
                        if "files" in value:
                            if any(path not in manifest for path in value["files"]):
                                raise ValueError("已确认行情备份组件缺失")
                        else:
                            if value["path"] not in manifest:
                                raise ValueError("独立模拟账户备份组件缺失")
                            value["sha256"] = manifest[value["path"]]
                    out.writestr("备份校验.json", dump({"created": created.isoformat(), "sha256": manifest,
                        "components": components}))
                verify_paper_backup(partial)
                os.replace(partial, dest)
            result = self.register_file(dest, name="简明ETF完整业务备份_" + dest.name)
            with self.settings_lock:
                settings = {**self.settings, "last_backup": stamp()}
                atomic_json(self.private / "settings.json", settings)
                self.settings.update(settings)
        except BaseException:
            # Publication starts only after both snapshots and the ZIP verify.
            # A failure registering/saving its status also withdraws this new
            # unique archive and its download record; old backups stay intact.
            dest.unlink(missing_ok=True)
            with self.db() as con:
                con.execute("DELETE FROM files WHERE path=?", (str(dest.resolve()),))
            raise
        finally:
            partial.unlink(missing_ok=True)
        # Dates come from the verified manifest, never mutable filesystem mtime.
        # Damaged/unknown archives remain untouched and cannot displace valid ones.
        valid, warnings = [], []
        for path in (self.private / "backups").glob("*.zip"):
            try:
                moment = created if path == dest else verified_backup_time(path)
                valid.append((moment, path.name, path))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError, EOFError, zlib.error):
                warnings.append("有旧备份未通过校验，原文件保留且不占有效恢复点名额：" + path.name)
        valid.sort(reverse=True)
        keep = {path for _, _, path in valid[:7]} | {dest}
        days, weeks = set(), set()
        for moment, _, path in valid:
            day, week = moment.date(), moment.isocalendar()[:2]
            if day not in days and len(days) < 7:
                keep.add(path)
                days.add(day)
            if week not in weeks and len(weeks) < 4:
                keep.add(path)
                weeks.add(week)
        for _, _, path in valid:
            if path not in keep:
                try:
                    path.unlink()
                except OSError:
                    warnings.append("旧备份暂未清理，文件仍保留：" + path.name)
        result["note"] = "备份已逐项校验；保留最近7份有效文件、最近7个不同日期各一份、最近4个有备份自然周各一份（重合只计一份）。"
        if warnings:
            result["warnings"] = warnings
            result["note"] += "有" + str(len(warnings)) + "份旧文件保留待核查，详情见本次完整结果。"
        return result

    def execute(self, bridge, job, stop):
        action, params, identity = job["action"], dict(job["params"]), job["id"]
        progress = lambda message: self.update(identity, progress=str(message)[-1500:])
        if params.pop("_automatic", False):
            with self.settings_lock:
                enabled = self.settings["auto_simulate"] if action in {"auto_scan", "auto_advance"} else self.settings["auto_refresh"]
                paused = params.get("group", "") + ":" + params.get("id", "") in self.settings["paused_accounts"]
            if not enabled or paused or stop.is_set():
                return {"skipped": True, "reason": "后台操作已暂停"}
            if action == "refresh":
                params["update_quotes"] = False  # The fast quote timer is independent.
        if action == "auto_scan":
            return self.scan_accounts(bridge, stop, progress)
        if action == "auto_advance" and datetime.now(CN).date().isoformat() > self.calendar_end:
            return {"advanced": False, "reason": "交易日历需更新，自动模拟已暂停"}
        if action == "full_backup":
            return self.backup()
        if action == "import":
            path, _ = self.file(params.pop("upload_id", ""), "upload")
            params["path"] = str(path)
        if action in {"export", "history_export", "quotes_export"}:
            dest = self.private / "exports" / identity
            dest.mkdir(exist_ok=True)
            # Bridge owns format/suffix selection beneath this trusted destination.
            params["path"] = str(dest)
        if action == "compare":
            result = self.compare(params, stop, progress)
            bridge.accept_comparison(params, result)
        else:
            result = bridge.execute(action, params, stop, progress)
        if action in {"export", "history_export", "quotes_export"}:
            files = [p for p in dest.rglob("*") if p.is_file()]
            if not files:
                raise ValueError("未生成可下载文件")
            if len(files) == 1:
                return self.register_file(files[0])
            if action == "export":
                native = [p for p in files if p.suffix == ".zip" and "账户备份" in p.name]
                if len(native) == 1:
                    main = self.register_file(native[0])
                    main["files"] = [self.register_file(p) for p in files if p != native[0]]
                    return main
            package = dest.with_suffix(".zip")
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    z.write(p, p.relative_to(dest).as_posix())
            return self.register_file(package, name="简明ETF账户导出.zip")
        return result

    def scan_accounts(self, bridge, stop, progress):
        with self.settings_lock:
            needs_backup = self.settings.get("auto_backup_required", True)
        if needs_backup:
            progress("启用自动模拟前，先保存完整业务备份…")
            saved = self.backup()
            with self.settings_lock:
                self.settings["auto_backup_required"] = False
                atomic_json(self.private / "settings.json", self.settings)
            self.record_automation(pre_auto_backup=saved["filename"])
        if stop.is_set():
            return {"skipped": True, "reason": "已停止"}
        candidates = bridge.auto_candidates()
        queued = []
        for candidate in candidates:
            group, account_id = candidate["group"], candidate["id"]
            key = group + ":" + account_id
            with self.settings_lock:
                enabled = self.settings["auto_simulate"] and key not in self.settings["paused_accounts"]
            if stop.is_set() or not enabled or not candidate.get("can_advance"):
                continue
            if self.auto_retry.get(key, 0) > time.time():
                candidate["reason"] = "上次推进失败，5分钟后重新核对"
                continue
            with self.db() as con:
                active = con.execute("SELECT params FROM jobs WHERE action='auto_advance' AND status IN ('queued','running')").fetchall()
            if any((lambda p: p.get("group") == group and p.get("id") == account_id)(json.loads(r[0])) for r in active):
                continue
            try:
                job = self.submit("auto_advance", {"group": group, "id": account_id, "_automatic": True},
                                  "auto_account_" + secrets.token_hex(16), internal=True)
                queued.append(job["id"])
            except HTTPException:
                break
            if len(queued) >= 3:
                break
        self.record_automation(last_cycle=stamp(), last_accounts=candidates, queued_accounts=len(queued))
        return {"candidates": candidates, "queued": queued}

    def worker(self):
        try:
            from web_bridge import Bridge
            bridge = Bridge(self.home)
            self.refresh_cache(bridge)
        except Exception as exc:
            self.init_error = str(exc)
            LOG.exception("business initialization failed")
            self.ready.set()
            return
        self.ready.set()
        while not self.halt.is_set():
            try:
                kind, data = self.tasks.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == "query":
                key, future = data
                if future.set_running_or_notify_cancel():
                    try:
                        result = getattr(bridge, key[0])(*key[1:])
                        encoded = dump(result)
                        with self.cache_lock:
                            self.cache[key] = encoded
                        future.set_result(json.loads(encoded))
                    except Exception as exc:
                        future.set_exception(ValueError(str(exc)))
                continue
            identity = data
            stop = self.stops[identity]
            if stop.is_set():
                self.update(identity, status="cancelled", progress="排队任务已取消")
                self.stops.pop(identity, None)
                continue
            self.update(identity, status="running", progress="开始执行")
            job = self.job(identity)
            action, params = job["action"], job["params"]
            self.record_automation(current_action=action)
            try:
                result = self.execute(bridge, job, stop)
                if action in {"quotes", "refresh"} and not result.get("skipped"):
                    errors = [name + ": " + (row.get("error") or "; ".join(row.get("warnings", [])) or "来源暂不可用")
                              for name, row in result.get("sources", {}).items() if not row.get("ok", False)]
                    self.record_automation(last_quote_check=(stamp() if "quotes" in result.get("sources", {}) else self.automation.get("last_quote_check", "")), last_error="; ".join(errors),
                                           last_reference=(result.get("reference") or {}).get("computed_at", self.automation.get("last_reference", "")))
                if action == "auto_advance":
                    self.auto_retry.pop(params["group"] + ":" + params["id"], None)
                    self.record_automation(last_account_result=result, last_account_at=stamp())
                completed = dict(status="cancelled" if stop.is_set() else "succeeded",
                                 progress="已在安全步骤停止，请核对账户当前日期" if stop.is_set() else "已完成",
                                 result=dump(result))
            except Exception as exc:
                LOG.exception("job failed: %s", identity)
                if params.get("_automatic"):
                    self.record_automation(last_error=str(exc)[:1000])
                    if action == "auto_advance":
                        self.auto_retry[params["group"] + ":" + params["id"]] = time.time() + 300
                completed = dict(status="cancelled" if stop.is_set() else "failed",
                                 error=str(exc)[:2000], progress="已停止，请核对当前账户状态" if stop.is_set() else "执行失败，查看原因")
            finally:
                self.refresh_cache(bridge, quotes_only=action == "quotes")
                self.record_automation(current_action="")
            self.update(identity, **completed)
            self.stops.pop(identity, None)

    def schedule_once(self, now=None):
        now = time.time() if now is None else now
        moment = datetime.fromtimestamp(now, CN)
        cadence = market_schedule(moment, self.sessions, self.calendar_end)
        if cadence["market_session"] != self.last_market_session:
            if cadence["market_session"] in {"交易中", "收盘核对"}:
                self.next_refresh = min(self.next_refresh, now)
                self.next_history = min(self.next_history, now)
            self.last_market_session = cadence["market_session"]
        with self.settings_lock:
            settings = dict(self.settings)
        due = []
        if settings["auto_refresh"]:
            if now >= self.next_refresh:
                due.append(("quotes", "next_refresh", cadence["quote_interval_seconds"]))
            if now >= self.next_history:
                due.append(("refresh", "next_history", cadence["history_interval_seconds"]))
        if settings["auto_simulate"] and now >= self.next_auto:
            due.append(("auto_scan", "next_auto", 60))
        for action, clock_field, interval in due:
            try:
                with self.db() as con:
                    active = con.execute("SELECT action FROM jobs WHERE status IN ('queued','running')").fetchall()
                if len(active) >= 8:
                    continue  # Reserve capacity for a user's manual operation.
                if any(r[0] == action for r in active):
                    continue
                self.submit(action, {"_automatic": True}, "timer_" + secrets.token_hex(16), internal=True)
                setattr(self, clock_field, now + interval)
            except Exception:
                LOG.exception("scheduled %s failed to queue", action)
                setattr(self, clock_field, now + 30)
        today = moment.strftime("%Y-%m-%d")
        if settings.get("last_backup", "")[:10] != today and now >= self.next_backup_attempt:
            self.next_backup_attempt = now + 3600
            try:
                with self.db() as con:
                    pending = con.execute("SELECT 1 FROM jobs WHERE action='full_backup' AND status IN ('queued','running')").fetchone()
                if not pending:
                    self.submit("full_backup", {}, "backup_" + today.replace("-", "") + "_" + secrets.token_hex(8))
            except Exception:
                LOG.exception("scheduled backup failed to queue")

    def schedule(self):
        self.ready.wait()
        if self.init_error:
            return
        while not self.halt.wait(2):
            try:
                self.schedule_once()
            except Exception:
                LOG.exception("scheduler cycle failed; retrying next cycle")

    def register_shutdown_dependency(self, service, *, name="dependency", stopped=None):
        """Startup ownership registration, including an explicit exit proof."""
        with self.shutdown_lock:
            if not any(item[0] is service for item in self.shutdown_dependencies):
                if stopped is None:
                    stopped = lambda: service.closed is True
                # Own the object even if startup races a stop request. The caller
                # must not swallow registration failure as optional init failure.
                self.shutdown_dependencies.append((service, name, stopped))
                self.shutdown_verified = False
                self.shutdown_generation += 1
            if self.halt.is_set():
                raise RuntimeError("cannot register a writer while runtime is stopping")

    def _shutdown_confirmation_errors(self):
        errors = []
        for service, name, stopped in self.shutdown_dependencies:
            try:
                if stopped() is not True:
                    raise TimeoutError(name + " shutdown is not confirmed; retain host lock")
            except BaseException as exc:
                errors.append(exc)
        try:
            # The board owns a subprocess as well as its scheduler thread.
            # A dead parent thread alone cannot prove that writer was reaped.
            if self.signals.shutdown_complete is not True:
                raise TimeoutError("signal subprocess shutdown is not confirmed; retain host lock")
        except BaseException as exc:
            errors.append(exc)
        for label, thread in (("business", self.thread), ("scheduler", self.scheduler),
                              ("signals", self.signals.thread)):
            try:
                if thread is not None and thread.is_alive():
                    raise TimeoutError(label + " worker is still active; retain host lock")
            except BaseException as exc:
                errors.append(exc)
        return errors

    def release_shutdown_lock(self, *, generation=None):
        """Release only a current successful attempt, rechecking every writer."""
        with self.shutdown_lock:
            if (self._shutdown_in_progress or not self.halt.is_set()
                    or not self.shutdown_verified
                    or (generation is not None and generation != self.shutdown_generation)):
                raise RuntimeError("shutdown confirmation is missing or stale; retain host lock")
            errors = self._shutdown_confirmation_errors()
            if errors:
                self.shutdown_verified = False
                raise errors[0]
            self.lock.close()

    def close(self, *, release_lock=True):
        # A single coordinator owns ALL services, including failed/partial ones.
        # Retry repeats closure and confirmation of every registered dependency.
        with self.shutdown_lock:
            if self._shutdown_in_progress:
                raise RuntimeError("runtime cannot confirm a reentrant shutdown")
            self._shutdown_in_progress = True
            self.shutdown_verified = False
            self.shutdown_generation += 1
            generation = self.shutdown_generation
            self.halt.set()
            errors = []
            try:
                try:
                    # Stop signal-child admission before another dependency's
                    # potentially long close, while retaining its ownership.
                    self.signals.request_stop()
                except BaseException as exc:
                    errors.append(exc)
                for service, name, stopped in self.shutdown_dependencies:
                    try:
                        request_stop = getattr(service, "request_stop", None)
                        if request_stop is not None:
                            request_stop()
                    except BaseException as exc:
                        errors.append(exc)
                for stop in list(self.stops.values()):
                    try:
                        stop.set()
                    except BaseException as exc:
                        errors.append(exc)
                for service, name, stopped in self.shutdown_dependencies:
                    try:
                        service.close()
                    except BaseException as exc:
                        errors.append(exc)
                try:
                    self.signals.close()
                except BaseException as exc:
                    errors.append(exc)
                deadline = time.monotonic() + 45
                for label, thread in (("business", self.thread), ("scheduler", self.scheduler),
                                      ("signals", self.signals.thread)):
                    try:
                        if thread is None:
                            continue
                        if thread is threading.current_thread():
                            raise RuntimeError("runtime cannot confirm its own writer shutdown")
                        thread.join(timeout=max(0, deadline - time.monotonic()))
                    except BaseException as exc:
                        errors.append(exc)
                errors.extend(self._shutdown_confirmation_errors())
                if errors:
                    raise errors[0]
                self.shutdown_verified = True
            finally:
                self._shutdown_in_progress = False
            if release_lock:
                self.release_shutdown_lock(generation=generation)
            return generation


def shutdown_threads_stopped(threads):
    """Use known owned threads; missing service attributes must raise upstream."""
    return all(thread is None or not thread.is_alive() for thread in threads)


async def shutdown_runtime(runtime, *, interrupted=False):
    """Drain despite cancellation; only an uninterrupted waiter may unlock."""
    runtime.halt.set()
    cleanup = asyncio.create_task(asyncio.to_thread(runtime.close, release_lock=False))
    cancelled = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as exc:
            cancelled = exc
            interrupted = True
        except BaseException:
            # Retrieve the actual cleanup error below. The synchronous
            # coordinator has already attempted the remaining dependencies.
            break
    try:
        generation = cleanup.result()
    except BaseException:
        if cancelled is not None:
            raise cancelled
        raise
    if cancelled is not None:
        raise cancelled
    current = asyncio.current_task()
    if interrupted or (current is not None and current.cancelling()):
        return
    # No await between successful completion/cancellation check and lock release.
    runtime.release_shutdown_lock(generation=generation)


def create_app(folder=None, *, paper_factory=None, ww_paper_factory=None, wechat_factory=None):
    home = Path(folder or os.environ.get("SIMPLE_ETF_HOME", str(ROOT.parent / "runtime-data"))).resolve()
    sessions = {}
    failures = {}
    auth_lock = threading.Lock()
    secure = os.environ.get("ETF_WEB_SECURE_COOKIE", "0") == "1"
    hosts = [h.strip() for h in os.environ.get("ETF_WEB_TRUSTED_HOSTS", "127.0.0.1,localhost,::1,testserver").split(",") if h.strip()]
    d0_web = os.environ.get("ETF_D0_WEB_PREVIEW") == "1"
    connector_sync = ConnectorSync() if d0_web else None
    signal_feed = SignalFeed() if d0_web else None
    signal_path = "/api/d0-control/sync/signal"
    connector_native = {"/api/d0-control/sync/claim", "/api/d0-control/sync/report"} if connector_sync else set()
    emtl_web = os.environ.get("ETF_EMTL_WEB_LIVE") == "1"
    broker_origin = os.environ.get("ETF_EMTL_ORIGIN", "")
    broker_orders = os.environ.get("ETF_EMTL_ORDERS_ENABLED") == "1"
    broker_connector_ip = emtl_web and os.environ.get("ETF_EMTL_CONNECTOR_IP") == "1"
    allowed_broker_ips, proxy_ips = set(), set()
    if emtl_web:
        parsed = urlsplit(broker_origin)
        if (not d0_web or not secure or parsed.scheme != "https" or parsed.hostname not in hosts
                or parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
                or broker_origin != f"https://{parsed.netloc}"):
            raise RuntimeError("EMTL 实盘要求私有 HTTPS、Secure Cookie、明确受信主机和 ETF_EMTL_ORIGIN")
        try:
            raw_ips = os.environ.get("ETF_EMTL_ALLOWED_IPS", "").strip()
            allowed_broker_ips = {ip_address(value.strip()) for value in raw_ips.split(",")} if raw_ips else set()
            proxy_ips = {ip_address(value.strip()) for value in os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1").split(",")}
            if (not (allowed_broker_ips or broker_connector_ip) or allowed_broker_ips & proxy_ips
                    or any(ip.is_unspecified or ip.is_multicast for ip in allowed_broker_ips | proxy_ips)):
                raise ValueError
        except ValueError:
            raise RuntimeError("EMTL 要求明确的访问 IP 白名单及可信代理 IP；不允许通配符") from None

    def broker_at_origin(request: Request):
        return emtl_web and str(request.base_url).rstrip("/") == broker_origin

    def peer_ip(request: Request):
        try:
            return ip_address(request.client.host) if request.client else None
        except ValueError:
            return None

    def connector_peer(request: Request):
        if broker_connector_ip and broker_at_origin(request):
            ip = peer_ip(request)
            if ip is not None and ip.is_global and not ip.is_multicast and ip not in proxy_ips and '%' not in str(ip):
                return str(ip)
        return None

    def session_owner(request: Request):
        return hashlib.sha256(request.cookies["etf_session"].encode()).hexdigest()

    def broker_available(request: Request):
        if not broker_at_origin(request):
            return False
        if peer_ip(request) in allowed_broker_ips:
            return True
        peer = connector_peer(request)
        return bool(peer and request.cookies.get("etf_session") and connector_sync.status(
            session_owner(request), peer=peer, include_network=True)["broker_network_authorized"])

    @asynccontextmanager
    async def lifespan(app):
        encoded = os.environ.get("ETF_WEB_PASSWORD_HASH", "")
        authfile = home / "web" / "auth.json"
        if not encoded and authfile.exists():
            encoded = json.loads(authfile.read_text("utf8"))["password_hash"]
        if not encoded or not re.fullmatch(r"pbkdf2_sha256\$600000\$[a-f0-9]{32}\$[a-f0-9]{64}", encoded):
            raise RuntimeError("请先运行 python server.py --set-password 配置私人登录口令")
        app.state.password_hash = encoded
        app.state.device_sessions = PersistentSessions(home, encoded)
        app.state.runtime = Runtime(home)
        interrupted = False
        app.state.broker_desk = None
        try:
            if emtl_web:
                from emtl_live import BrokerDesk
                app.state.broker_desk = BrokerDesk.from_env(home / "web" / "emtl-manual.sqlite3")
            app.state.realtime_paper = None
            try:
                from realtime_paper_service import PaperService
                if paper_factory is not None:
                    app.state.realtime_paper = paper_factory(home)
                else:
                    from realtime_paper_engine import PaperLedger
                    app.state.realtime_paper = PaperService(home, ledger=PaperLedger(home / "web" / "realtime-paper"))
            except Exception:
                LOG.exception("prospective paper service initialization failed; existing services remain available")
            if app.state.realtime_paper is not None:
                app.state.runtime.register_shutdown_dependency(app.state.realtime_paper, name="paper")
                app.state.runtime.paper_service = app.state.realtime_paper
                attach_signal = getattr(app.state.realtime_paper, "set_signal_listener", None)
                if signal_feed and callable(attach_signal):
                    loop = asyncio.get_running_loop()
                    attach_signal(lambda target: loop.call_soon_threadsafe(signal_feed.publish, target))

            app.state.ww_paper = None
            # A supplied legacy test factory remains an explicit single-service
            # host unless the test also supplies the separate WW dependency.
            if ww_paper_factory is not None or paper_factory is None:
                try:
                    if ww_paper_factory is not None:
                        app.state.ww_paper = ww_paper_factory(home)
                    else:
                        from realtime_paper_engine import PaperLedger
                        from realtime_paper_service import ReadOnlyPaperSource
                        ledger = PaperLedger(home / "web" / "realtime-paper-ww", strategy="D0I-BOND-WW")
                        app.state.ww_paper = PaperService(home, ledger=ledger, strategy="D0I-BOND-WW",
                            source=ReadOnlyPaperSource(home, strategy="D0I-BOND-WW", calendar=ledger.calendar))
                except Exception:
                    LOG.exception("WW prospective paper initialization failed; D0 remains unchanged")
            app.state.paper_services = {"D0": app.state.realtime_paper,
                                       "D0I-BOND-WW": app.state.ww_paper}
            if app.state.ww_paper is not None:
                app.state.runtime.register_shutdown_dependency(app.state.ww_paper, name="WW paper")
                app.state.runtime.ww_paper_service = app.state.ww_paper

            # Injected paper accounts must opt into a sender explicitly. A test
            # fixture must never inherit a host's real delivery credentials.
            app.state.paper_wechat = None
            if wechat_factory is not None or (paper_factory is None and ww_paper_factory is None):
                services = [s for s in app.state.paper_services.values()
                            if s is not None and callable(getattr(s, "write_notification", None))]
                if services:
                    try:
                        from realtime_paper_wechat import WechatDispatcher
                        dispatcher = (wechat_factory or WechatDispatcher)(services)
                    except Exception:
                        LOG.error("paper WeChat sender configuration unavailable")
                    else:
                        app.state.runtime.register_shutdown_dependency(dispatcher, name="paper WeChat")
                        try:
                            dispatcher.start()
                        except Exception:
                            LOG.error("paper WeChat dispatcher failed to start")
                        else:
                            app.state.paper_wechat = dispatcher

            app.state.benchmark = None
            try:
                from account_benchmark_service import AccountBenchmarkService
                app.state.benchmark = AccountBenchmarkService(home / "web" / "account-benchmark")
            except Exception:
                LOG.exception("benchmark initialization failed; trading remains available")
            if app.state.benchmark is not None:
                service = app.state.benchmark
                app.state.runtime.register_shutdown_dependency(service, name="benchmark",
                    stopped=lambda service=service: shutdown_threads_stopped((service.thread,)))

            # This service is present in the actual 398-file production host.
            app.state.market_indices = None
            try:
                from market_index_service import MarketIndexBenchmarkService
                app.state.market_indices = MarketIndexBenchmarkService(home / "web" / "market-index-benchmark")
            except Exception:
                LOG.exception("market index initialization failed; trading remains available")
            if app.state.market_indices is not None:
                service = app.state.market_indices
                app.state.runtime.register_shutdown_dependency(service, name="market indices",
                    stopped=lambda service=service: shutdown_threads_stopped((service.thread,)))

            app.state.d0_comparison = None
            if app.state.realtime_paper is not None:
                try:
                    from realtime_paper_comparison import D0ComparisonService
                    app.state.d0_comparison = D0ComparisonService(
                        home / "web" / "d0-performance-comparison", app.state.realtime_paper,
                        app.state.market_indices)
                except Exception:
                    LOG.exception("D0 comparison initialization failed; trading remains available")
            if app.state.d0_comparison is not None:
                service = app.state.d0_comparison
                app.state.runtime.register_shutdown_dependency(service, name="D0 comparison",
                    stopped=lambda service=service: shutdown_threads_stopped((service.thread,)))

            app.state.ww_comparison = None
            if app.state.ww_paper is not None:
                try:
                    from realtime_paper_comparison import D0ComparisonService
                    app.state.ww_comparison = D0ComparisonService(
                        home / "web" / "ww-performance-comparison", app.state.ww_paper,
                        app.state.market_indices, strategy="D0I-BOND-WW")
                except Exception:
                    LOG.exception("WW comparison initialization failed; paper accounts remain unchanged")
            if app.state.ww_comparison is not None:
                service = app.state.ww_comparison
                app.state.runtime.register_shutdown_dependency(service, name="WW comparison",
                    stopped=lambda service=service: shutdown_threads_stopped((service.thread,)))

            app.state.research = None
            try:
                from company_research.service import ResearchService
                app.state.research = ResearchService(home / "web" / "company-research")
            except Exception:
                LOG.exception("company research initialization failed; trading remains available")
            if app.state.research is not None:
                service = app.state.research
                app.state.runtime.register_shutdown_dependency(service, name="company research",
                    stopped=lambda service=service: shutdown_threads_stopped((service.thread,)))

            app.state.sector_research = None
            try:
                from sector_research.research_service import ResearchService as SectorResearchService
                app.state.sector_research = SectorResearchService(
                    ROOT / "sector_research", home / "web" / "sector-research",
                    auto_update=os.environ.get("ETF_SECTOR_RESEARCH_AUTO_UPDATE", "1") == "1")
            except Exception:
                LOG.exception("sector research initialization failed; existing services remain available")
            if app.state.sector_research is not None:
                service = app.state.sector_research
                app.state.runtime.register_shutdown_dependency(service, name="sector research",
                    stopped=lambda service=service: service.shutdown_complete is True)
            yield
        except BaseException:
            interrupted = True
            raise
        finally:
            try:
                if app.state.broker_desk:
                    await asyncio.to_thread(app.state.broker_desk.close)
            finally:
                await shutdown_runtime(app.state.runtime, interrupted=interrupted)

    ui_version, ui_html = frontend_release()
    app = FastAPI(title="简明ETF模拟交易", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.add_middleware(BodyLimitMiddleware)
    from company_research.routes import install_routes
    install_routes(app)

    def session(request, required=True, *, renew=False):
        token = request.cookies.get("etf_session", "")
        with auth_lock:
            current = sessions.get(token)
            if current and current["expires"] <= time.time():
                sessions.pop(token, None)
                current = None
        if current is None and token:
            try:
                current = app.state.device_sessions.lookup(token, renew=renew)
            except SessionStoreUnavailable:
                raise HTTPException(503, "设备登录状态暂不可用，请稍后重试") from None
        if required and not current:
            raise HTTPException(401, "请先登录")
        return current

    def set_session_cookie(response, token, max_age):
        response.set_cookie("etf_session", token, httponly=True, secure=secure, samesite="strict", max_age=max_age)

    from sector_research.routes import install_routes as install_sector_routes
    app.state.sector_host_ui_version = ui_version
    install_sector_routes(app, session)

    @app.middleware("http")
    async def guard(request, call_next):
        path = request.url.path
        current = None
        try:
            native_sync = (request.method == "POST" and path in connector_native) or (signal_feed and request.method == "GET" and path == signal_path)
            if path.startswith("/api/") and path not in {"/api/session", "/api/login"} and not native_sync:
                current = await asyncio.to_thread(session, request, renew=True)
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    csrf = request.headers.get("x-csrf-token", "")
                    if not csrf or not hmac.compare_digest(csrf, current["csrf"]):
                        raise HTTPException(403, "页面会话已过期，请刷新后重试")
            if request.method == "POST":
                origin = request.headers.get("origin")
                if origin and origin != str(request.base_url).rstrip("/"):
                    raise HTTPException(403, "拒绝跨站请求")
                limit = MAX_UPLOAD + 100000 if path == "/api/upload" else 384000 if path.startswith("/api/research/valuation/") else 24000
                length = request.headers.get("content-length", "0")
                if not length.isdigit():
                    raise HTTPException(400, "请求长度无效")
                if int(length) > limit:
                    raise HTTPException(413, "上传或请求内容过大")
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers["X-UI-Version"] = ui_version
        if path == "/" or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
        if current and current.get("remembered") and path != "/api/logout":
            set_session_cookie(response, request.cookies.get("etf_session", ""),
                               max(0, int(current["expires"] - time.time())))
        return response

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(PaperApiError)
    async def invalid_paper(_, exc):
        return JSONResponse({"detail": exc.detail, "code": exc.code, "retryable": False}, status_code=exc.status)

    @app.get("/healthz")
    def health():
        ready = app.state.runtime.status()["ready"]
        return JSONResponse({"status": "ok" if ready else "starting", "revision": os.environ.get("RELEASE_REVISION", "unknown")}, status_code=200 if ready else 503)

    @app.get("/api/session")
    def get_session(request: Request):
        current = session(request, False, renew=True)
        response = JSONResponse({"authenticated": bool(current), "csrf": current["csrf"] if current else None,
                                 "remembered": bool(current and current.get("remembered"))})
        if current and current.get("remembered"):
            set_session_cookie(response, request.cookies.get("etf_session", ""),
                               max(0, int(current["expires"] - time.time())))
        return response

    @app.post("/api/login")
    async def login(request: Request):
        body = await request.json()
        password = body.get("password", "") if isinstance(body, dict) else ""
        remember = body.get("remember_device", False) if isinstance(body, dict) else False
        if type(remember) is not bool:
            raise HTTPException(400, "记住设备选项必须为布尔值")
        if not isinstance(password, str) or len(password) > 256:
            raise HTTPException(400, "口令格式无效")
        peer = request.client.host if request.client else "unknown"
        with auth_lock:
            attempts = [x for x in failures.get(peer, []) if x > time.time() - 900]
            if len(attempts) >= 8:
                raise HTTPException(429, "尝试次数过多，请15分钟后再试")
            failures[peer] = attempts + [time.time()]
        valid = await asyncio.to_thread(verify_password, password, app.state.password_hash)
        if not valid:
            raise HTTPException(401, "登录口令不正确")
        if remember:
            try:
                token, current = await asyncio.to_thread(app.state.device_sessions.issue)
            except SessionStoreUnavailable:
                raise HTTPException(503, "无法保存设备登录状态，请稍后重试") from None
        with auth_lock:
            failures.pop(peer, None)
            for old, item in list(sessions.items()):
                if item["expires"] < time.time():
                    sessions.pop(old, None)
            if not remember:
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                current = {"csrf": csrf, "expires": time.time() + 43200}
                sessions[token] = current
        result = JSONResponse({"authenticated": True, "csrf": current["csrf"], "remembered": remember})
        set_session_cookie(result, token, DEVICE_TTL if remember else 43200)
        return result

    @app.post("/api/logout")
    def logout(request: Request):
        token = request.cookies.get("etf_session", "")
        current = session(request)
        if current.get("remembered"):
            try:
                app.state.device_sessions.revoke(token)
            except SessionStoreUnavailable:
                raise HTTPException(503, "无法撤销设备登录状态，请稍后重试") from None
        with auth_lock:
            sessions.pop(token, None)
        owner = hashlib.sha256(token.encode()).hexdigest()
        if connector_sync:
            connector_sync.revoke(owner)
        if app.state.broker_desk:
            app.state.broker_desk.disconnect(owner)
        response = JSONResponse({"ok": True})
        response.delete_cookie("etf_session", httponly=True, secure=secure, samesite="strict")
        return response

    def paper_strategy(request):
        values = request.query_params.getlist("strategy")
        if len(values) > 1 or (values and values[0] not in ("D0", "D0I-BOND-WW")):
            raise PaperApiError("INVALID_REQUEST", "请选择已支持的前瞻模拟策略", 400)
        return values[0] if values else "D0"

    def paper_service_instance(strategy):
        service = getattr(app.state, "ww_paper" if strategy == "D0I-BOND-WW" else "realtime_paper", None)
        if service is None:
            raise PaperApiError("PAPER_UNAVAILABLE", "前瞻模拟模块暂不可用；原模拟账户可继续使用", 503)
        bound = getattr(service, "strategy", getattr(getattr(service, "ledger", None), "strategy", None))
        if bound not in (None, strategy) or (strategy != "D0" and bound != strategy):
            raise PaperApiError("PAPER_UNAVAILABLE", "模拟服务策略与请求不一致，请重新核对", 503)
        return service

    def paper_service(strategy="D0"):
        service = paper_service_instance(strategy)
        # API-native implementations and host test substitutes already speak v1.
        return service if callable(getattr(service, "create_account", None)) else PaperHttpAdapter(service)

    async def paper_body(request, required):
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise PaperApiError("INVALID_REQUEST", "请提交有效的模拟操作") from None
        if not isinstance(body, dict) or set(body) != set(required) | {"idempotency_key"}:
            raise PaperApiError("INVALID_REQUEST", "模拟操作字段不完整或包含不支持的字段")
        key = body["idempotency_key"]
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
            raise PaperApiError("INVALID_REQUEST", "请提供有效的操作幂等编号")
        if "initial_cash" in body:
            cash = body["initial_cash"]
            if not isinstance(cash, str) or not re.fullmatch(r"\d{1,10}(?:\.\d{1,2})?", cash) or not Decimal("0") < Decimal(cash) <= Decimal("1000000000"):
                raise PaperApiError("INVALID_CAPITAL", "本金须为大于零且不超过十亿元的十进制金额，最多两位小数")
        if "name" in body:
            if not isinstance(body["name"], str) or not 1 <= len(body["name"].strip()) <= 80 or any(ord(c) < 32 for c in body["name"]):
                raise PaperApiError("INVALID_REQUEST", "账户名称须为1至80个可显示字符")
            body["name"] = body["name"].strip()
        return body

    def paper_identity(identity):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identity):
            raise PaperApiError("INVALID_REQUEST", "模拟账户或委托编号无效")
        return identity

    async def paper_call(method, *args, strategy="D0", **kwargs):
        try:
            result = await asyncio.to_thread(getattr(paper_service(strategy), method), *args, **kwargs)
            if isinstance(result, dict):
                accounts = result.get("accounts", [])
                accounts = accounts if isinstance(accounts, list) else []
                if isinstance(result.get("account"), dict):
                    accounts = accounts + [result["account"]]
                if any(not isinstance(account, dict) or account.get("strategy") != strategy for account in accounts):
                    raise PaperApiError("PAPER_UNAVAILABLE", "模拟账户策略与请求不一致，请重新核对", 503)
                return {**result, "strategy": strategy}
            return result
        except ValueError as exc:
            code = getattr(exc, "code", "INVALID_REQUEST")
            code = {"ACCOUNT_EXISTS": "INVALID_STATE", "VALIDATION_ERROR": "INVALID_REQUEST"}.get(code, code)
            errors = {
                "INVALID_REQUEST": (400, "模拟操作不符合规则，请核对输入和当前状态"),
                "INVALID_CAPITAL": (400, "模拟本金无效，请核对金额"),
                "ACCOUNT_NOT_FOUND": (404, "未找到此独立模拟账户"),
                "ORDER_NOT_FOUND": (404, "未找到此账户的模拟委托"),
                "IDEMPOTENCY_CONFLICT": (409, "操作编号已用于不同请求，请核对原操作"),
                "CAPITAL_LOCKED": (409, "当前账户不能修改本金，请核对成交与运行状态"),
                "INVALID_STATE": (409, "当前状态不能执行此模拟操作"),
            }
            status, detail = errors.get(code, errors["INVALID_REQUEST"])
            raise PaperApiError(code if code in errors else "INVALID_REQUEST", detail, status) from None
        except PaperApiError:
            raise
        except Exception:
            LOG.error("prospective paper operation failed; existing services remain available")
            raise PaperApiError("PAPER_UNAVAILABLE", "前瞻模拟服务暂不可用，请稍后只读核对状态", 503) from None

    def email_draft_call(value=None, *, save=False, strategy="D0"):
        from realtime_paper_email_draft import EmailDraftError
        runtime = getattr(app.state, "runtime", None)
        try:
            if runtime is None:
                raise EmailDraftError("EMAIL_DRAFT_UNAVAILABLE")
            return runtime.email_draft(lambda: paper_service(strategy).snapshot(), value, save=save, strategy=strategy)
        except EmailDraftError as exc:
            return JSONResponse(exc.response(), status_code=exc.status)

    def paper_wechat(strategy, action="settings", body=None):
        from realtime_paper_notifications import NotificationError
        service = paper_service_instance(strategy)
        dispatcher = getattr(app.state, "paper_wechat", None)
        configured = dispatcher is not None and dispatcher.configured is True
        try:
            store = service.ledger.notifications
            if action == "settings":
                settings = store.settings()
            else:
                if (action == "queue_test" or body.get("enabled") is True) and not configured:
                    raise PaperApiError("NOTIFICATION_UNCONFIGURED", "请先在服务器配置微信推送凭据", 503)
                settings = service.write_notification(getattr(store, action), **body)
            return {"contract_version": "paper-wechat-v1", "configured": configured, **settings}
        except NotificationError as exc:
            messages = {"NOTIFICATION_ACCOUNT": "请先创建模拟账户",
                        "NOTIFICATION_BINDING": "模拟账户已变更，请刷新后重试",
                        "NOTIFICATION_INVALID": "微信提醒设置无效",
                        "NOTIFICATION_RATE_LIMIT": "测试提醒每分钟最多发送一次"}
            raise PaperApiError(exc.code, messages.get(exc.code, "微信提醒操作失败"), exc.status_code) from None
        except PaperApiError:
            raise
        except Exception:
            LOG.error("paper WeChat notification store unavailable")
            raise PaperApiError("NOTIFICATION_UNAVAILABLE", "微信提醒暂不可用，请稍后重试", 503) from None

    async def wechat_write(request, action):
        strategy = paper_strategy(request)
        fields = {"account_id", "account_created_at"}
        if action == "save_settings":
            fields.update(("enabled", "orders_enabled"))
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            body = None
        if (type(body) is not dict or set(body) != fields
                or any(type(body[k]) is not str or not 1 <= len(body[k]) <= 100
                       for k in ("account_id", "account_created_at"))
                or (action == "save_settings"
                    and any(type(body[k]) is not bool for k in ("enabled", "orders_enabled")))):
            raise PaperApiError("NOTIFICATION_INVALID", "微信提醒请求字段无效")
        return await asyncio.to_thread(paper_wechat, strategy, action, body)

    @app.get("/api/realtime-paper/wechat")
    def paper_wechat_get(request: Request):
        return paper_wechat(paper_strategy(request))

    @app.post("/api/realtime-paper/wechat")
    async def paper_wechat_save(request: Request):
        return await wechat_write(request, "save_settings")

    @app.post("/api/realtime-paper/wechat/test")
    async def paper_wechat_test(request: Request):
        return await wechat_write(request, "queue_test")

    @app.get("/api/realtime-paper/email-draft")
    def paper_email_draft_get(request: Request):
        return email_draft_call(strategy=paper_strategy(request))

    @app.post("/api/realtime-paper/email-draft")
    async def paper_email_draft_save(request: Request):
        strategy = paper_strategy(request)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            from realtime_paper_email_draft import EmailDraftError
            exc = EmailDraftError("EMAIL_DRAFT_INVALID")
            return JSONResponse(exc.response(), status_code=exc.status)
        return await asyncio.to_thread(email_draft_call, body, save=True, strategy=strategy)

    @app.get("/api/realtime-paper")
    async def paper_status(request: Request):
        strategy = paper_strategy(request)
        result = await paper_call("snapshot", strategy=strategy)
        if isinstance(result, dict):
            result = {**result, "strategy": strategy, "strategies": [
                {"code": code, "name": name, "available": getattr(app.state, attr, None) is not None}
                for code, name, attr in (("D0", "原D0四资产", "realtime_paper"),
                                        ("D0I-BOND-WW", "双股择时 周线择债", "ww_paper"))]}
        return result

    @app.get("/api/realtime-paper/d0-order-preview-input")
    def d0_order_preview_input():
        read = getattr(paper_service_instance("D0"), "order_preview_input", None)
        if not callable(read):
            raise PaperApiError("PAPER_UNAVAILABLE", "D0 拟单资料暂不可用", 503)
        return read()

    if d0_web:
        @app.get("/d0-control")
        def d0_control_page():
            page = (ROOT / "web_static" / "d0-control.html").read_text("utf-8")
            return HTMLResponse(page.replace("__UI_VERSION__", ui_version), headers={"Cache-Control": "no-store"})

        def require_sync_https(request: Request):
            if not secure or request.url.scheme != "https":
                raise HTTPException(403, "同步工具仅支持 HTTPS 网站。")

        def sync_owner(request: Request):
            require_sync_https(request)
            return session_owner(request)

        @app.get("/api/d0-control/sync/download")
        def sync_download(request: Request):
            require_sync_https(request)
            buf = BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as bundle:
                for name in ("launch.cmd", "bootstrap.ps1", "pilot.py", "requirements-win.lock", "README.txt"):
                    bundle.write(ROOT / "d0_connector" / name, f"Jianming-ETF-Sync/{name}")
            return Response(buf.getvalue(), media_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="Jianming-ETF-Sync-Windows-v3.zip"'})

        @app.get("/api/d0-control/sync/status")
        def sync_status(request: Request):
            return connector_sync.status(sync_owner(request), peer=connector_peer(request),
                                         include_network=broker_connector_ip)

        @app.post("/api/d0-control/sync/pair")
        def sync_pair(request: Request):
            owner = sync_owner(request)
            if request.headers.get("origin") != str(request.base_url).rstrip("/"):
                raise HTTPException(403, "请在原网站生成配对码。")
            return connector_sync.start(owner, peer=connector_peer(request))

        async def sync_payload(request: Request, keys):
            require_sync_https(request)
            if request.headers.get("origin") or request.headers.get("cookie"):
                raise HTTPException(403, "此接口只允许本机同步工具使用。")
            try:
                raw = await request.body()
                if len(raw) > 512:
                    raise ValueError
                value = json.loads(raw)
                if not isinstance(value, dict) or set(value) != keys:
                    raise ValueError
                return value
            except (ValueError, UnicodeError):
                raise HTTPException(400, "同步请求无效。") from None

        @app.post("/api/d0-control/sync/claim")
        async def sync_claim(request: Request):
            fields = await sync_payload(request, {"code"})
            try:
                return connector_sync.claim(fields["code"], peer=connector_peer(request))
            except SyncError as exc:
                raise HTTPException(409, str(exc)) from None

        @app.post("/api/d0-control/sync/report")
        async def sync_report(request: Request):
            fields = await sync_payload(request, {"sync_token", "state"})
            try:
                return connector_sync.report(fields["sync_token"], fields["state"])
            except SyncError as exc:
                raise HTTPException(409, str(exc)) from None

        @app.get(signal_path)
        async def sync_signal(request: Request):
            require_sync_https(request)
            if request.headers.get("origin") or request.headers.get("cookie"):
                raise HTTPException(403, "此接口只允许本机同步工具使用。")
            auth = request.headers.get("authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else ""
            owner = connector_sync.signal_owner(token)
            if owner is None:
                raise HTTPException(401, "信号订阅已过期，请重新配对。")
            after = request.query_params.get("after", "")
            if after and not re.fullmatch(r"[a-f0-9]{16}", after):
                raise HTTPException(400, "信号游标无效。")
            if owner in signal_feed.active or len(signal_feed.active) >= signal_feed.max_listeners:
                raise HTTPException(429, "信号通道正在使用，请稍后重试。")
            signal_feed.active.add(owner)
            try:
                return await signal_feed.next(after, lambda: connector_sync.signal_owner(token) == owner)
            except PermissionError:
                raise HTTPException(401, "信号订阅已过期，请重新配对。") from None
            finally:
                signal_feed.active.discard(owner)

        @app.get("/api/d0-control/status")
        def d0_control_status(request: Request):
            from realtime_paper_engine import TradingCalendar

            try:
                source = d0_order_preview_input()
            except PaperApiError:
                source = {"source_status": "unavailable"}
            signal = source.get("signal") or {}
            now = datetime.now(CN)
            calendar = TradingCalendar()
            available = broker_available(request)
            if not emtl_web:
                broker_state = "disabled"
            elif available:
                broker_state = "available"
            elif broker_connector_ip and broker_at_origin(request):
                broker_state = "connector_pairing_required"
            else:
                broker_state = "private_origin_required"
            desk = app.state.broker_desk
            account_bound = bool(available and desk and desk.bound)
            orders_enabled = bool(account_bound and broker_orders and desk.status(session_owner(request)).get("orders_armed"))
            return {"mode": "preview_only", "live_orders_enabled": orders_enabled,
                    "broker_orders_configured": available and broker_orders, "account_bound": account_bound, "broker_state": broker_state,
                    "strategy": "D0", "source_status": source.get("source_status"), "historical_seed": source.get("historical_seed"),
                    "market_state": "unknown" if calendar.is_session(now.date()) is None else "open" if calendar.segment(now) else "closed",
                    "execution_day": signal.get("execution_day"), "eligible_at": signal.get("eligible_at")}

        @app.post("/api/d0-control/preview")
        async def d0_control_preview(request: Request):
            from d0_order_preview import preview

            if request.headers.get("origin") != str(request.base_url).rstrip("/"):
                raise HTTPException(403, "拟单必须在控制台的网页内操作")
            try:
                balances = await request.json()
            except (ValueError, UnicodeError):
                raise HTTPException(400, "资金持仓格式无效") from None

            def calculate():
                return preview(d0_order_preview_input(), balances, now=datetime.now(CN))

            try:
                return await asyncio.to_thread(calculate)
            except (ValueError, ArithmeticError) as exc:
                detail = str(exc) if isinstance(exc, ValueError) else "资金或行情计算异常"
                raise PaperApiError("D0_PREVIEW_UNAVAILABLE", detail, 409) from None

    if emtl_web:
        def broker_access(request: Request):
            if not broker_available(request) or (request.method == "POST" and request.headers.get("origin") != broker_origin):
                raise HTTPException(403, "请从已配置的私有 HTTPS 控制台访问券商交易。")
            return app.state.broker_desk, session_owner(request)

        @app.get("/api/d0-control/broker")
        async def broker_status(request: Request):
            desk, owner = broker_access(request)
            return await asyncio.to_thread(desk.status, owner)

        @app.post("/api/d0-control/broker/{action}")
        async def broker_action(request: Request, action: str):
            from emtl_live import LiveError

            desk, owner = broker_access(request)
            keys = {"connect": {"username", "password"}, "disconnect": set(),
                    "enroll": {"username", "password", "enrollment_code", "confirmation"}, "unbind": {"confirmation"},
                    "live": {"confirmation"}, "arm": {"username", "password", "confirmation"}, "stop": set(),
                    "draft": {"symbol", "side", "price", "quantity"}, "submit": {"order_token", "confirmation"},
                    "limits": {"single_cny", "daily_cny"}}
            if action not in keys:
                raise HTTPException(404, "不支持的券商操作")
            if action in {"arm", "draft", "submit"} and not broker_orders:
                raise HTTPException(403, "券商当前只允许登录和只读核对，真实委托尚未开放。")
            try:
                payload = await request.json()
            except (ValueError, UnicodeError):
                raise HTTPException(400, "券商操作格式无效") from None
            if not isinstance(payload, dict) or set(payload) != keys[action]:
                raise HTTPException(400, "券商操作字段不符")
            try:
                if action == "connect":
                    return await asyncio.to_thread(desk.connect, owner, payload["username"], payload["password"])
                if action == "enroll":
                    return await asyncio.to_thread(desk.enroll, owner, payload)
                if action == "unbind":
                    state = await asyncio.to_thread(desk.unbind, owner, payload)
                    return JSONResponse(state, headers={"Cache-Control": "no-store"})
                if action == "disconnect":
                    return await asyncio.to_thread(desk.disconnect, owner)
                if action == "live":
                    return await asyncio.to_thread(desk.enable_live, owner, payload)
                if action == "arm":
                    return await asyncio.to_thread(desk.arm_orders, owner, payload)
                if action == "stop":
                    return await asyncio.to_thread(desk.stop_live, owner)
                if action == "limits":
                    return await asyncio.to_thread(desk.update_limits, owner, payload)
                operation = desk.draft_order if action == "draft" else desk.submit
                return await asyncio.to_thread(operation, owner, payload, d0_order_preview_input)
            except LiveError as exc:
                raise HTTPException(409, str(exc)) from None
            except sqlite3.Error:
                raise HTTPException(503, "委托日志不可用，请先在券商端核对，勿重复提交。") from None

    @app.get("/api/live-trading/signal")
    async def live_trading_signal(request: Request):
        strategy = paper_strategy(request)
        export = getattr(paper_service_instance(strategy), "export_live_signal", None)
        if not callable(export):
            raise PaperApiError("LIVE_SIGNAL_UNAVAILABLE", "当前服务无法导出策略信号", 503)
        try:
            result = await asyncio.to_thread(export)
        except (ValueError, TypeError, KeyError):
            raise PaperApiError("LIVE_SIGNAL_UNAVAILABLE", "暂无可交接的当前确认信号", 409) from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/api/realtime-paper/accounts/{account_id}")
    async def paper_account(account_id: str, request: Request):
        return await paper_call("account_detail", paper_identity(account_id), strategy=paper_strategy(request))

    @app.get("/api/realtime-paper/comparison")
    async def paper_comparison(account_id: str, request: Request):
        strategy = paper_strategy(request)
        identity = paper_identity(account_id)
        service = getattr(app.state, "ww_comparison" if strategy == "D0I-BOND-WW" else "d0_comparison", None)
        if service is None:
            raise PaperApiError("COMPARISON_UNAVAILABLE", "收益对比暂不可用，请稍后重试", 503)
        try:
            result = await asyncio.to_thread(service.snapshot, identity)
        except Exception:
            LOG.error("D0 comparison snapshot unavailable")
            raise PaperApiError("COMPARISON_UNAVAILABLE", "收益对比暂不可用，请稍后重试", 503) from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.post("/api/realtime-paper/accounts")
    async def paper_create(request: Request):
        strategy = paper_strategy(request)
        body = await paper_body(request, {"name", "initial_cash"})
        return await paper_call("create_account", strategy=strategy, **body)

    @app.post("/api/realtime-paper/accounts/{account_id}/capital")
    async def paper_capital(account_id: str, request: Request):
        strategy = paper_strategy(request)
        body = await paper_body(request, {"initial_cash"})
        return await paper_call("configure_capital", paper_identity(account_id), strategy=strategy, **body)

    @app.post("/api/realtime-paper/accounts/{account_id}/start")
    async def paper_start(account_id: str, request: Request):
        strategy = paper_strategy(request)
        body = await paper_body(request, set())
        return await paper_call("start_account", paper_identity(account_id), strategy=strategy, **body)

    @app.post("/api/realtime-paper/accounts/{account_id}/pause")
    async def paper_pause(account_id: str, request: Request):
        strategy = paper_strategy(request)
        body = await paper_body(request, set())
        return await paper_call("pause_account", paper_identity(account_id), strategy=strategy, **body)

    @app.post("/api/realtime-paper/accounts/{account_id}/orders/{order_id}/cancel")
    async def paper_cancel(account_id: str, order_id: str, request: Request):
        strategy = paper_strategy(request)
        body = await paper_body(request, set())
        return await paper_call("cancel_order", paper_identity(account_id), paper_identity(order_id), strategy=strategy, **body)

    @app.get("/api/catalog")
    def catalog():
        return app.state.runtime.query("catalog")

    @app.get("/api/signals")
    def strategy_signals():
        return app.state.runtime.signals.snapshot()

    @app.get("/api/overview")
    def overview():
        result = app.state.runtime.query("overview")
        result["server"] = app.state.runtime.status()
        return result

    @app.get("/api/overseas")
    def overseas():
        return app.state.runtime.query("overseas_overview")

    @app.get("/api/overseas/research")
    def overseas_research():
        return FileResponse(ROOT / "overseas_assets" / "research-summary.json", media_type="application/json")

    @app.get("/api/overseas/curve")
    def overseas_curve(group: str, strategy: str, variant: str = "base"):
        from web_overseas import MARKETS, TITLES
        if group not in MARKETS or strategy not in TITLES or variant not in {"base", "cost2", "delay"}:
            raise HTTPException(400, "海外市场、策略或研究情景无效")
        return app.state.runtime.query("overseas_curve", group, strategy, variant)

    @app.get("/api/overseas/report")
    def overseas_report():
        return FileResponse(ROOT / "overseas_assets" / "research.pdf", media_type="application/pdf")

    @app.get("/api/accounts")
    def accounts(group: str = "original"):
        if group not in {"original", "top5", "seven", "nasdaq", "hangseng", "hangtech"}:
            raise HTTPException(400, "账户组无效")
        return app.state.runtime.query("accounts", group)

    @app.get("/api/account")
    def account(group: str, id: str):
        if group not in {"original", "top5", "seven", "nasdaq", "hangseng", "hangtech"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", id):
            raise HTTPException(400, "账户参数无效")
        return app.state.runtime.query("account", group, id)

    @app.get("/api/account-benchmark")
    def account_benchmark(group: str, id: str):
        if group not in {"original", "top5", "seven", "nasdaq", "hangseng", "hangtech"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", id):
            raise HTTPException(400, "账户参数无效")
        detail = app.state.runtime.query("account", group, id)
        # Only the existing executor reads account data; independent market
        # refresh never touches Bridge, jobs, settings or account files.
        from account_benchmark_service import unavailable
        service = getattr(app.state, "benchmark", None)
        result = service.compare(detail) if service is not None else unavailable()
        indices = getattr(app.state, "market_indices", None)
        if indices is not None:
            try:
                result["index_benchmarks"] = indices.compare(detail)
            except Exception:
                LOG.exception("market index comparison failed; ETF comparison remains available")
                from market_index_service import unavailable_indices
                result["index_benchmarks"] = unavailable_indices()
        else:
            from market_index_service import unavailable_indices
            result["index_benchmarks"] = unavailable_indices()
        return result

    @app.get("/api/accounts/deleted")
    def deleted_accounts(group: str = "original"):
        if group not in {"original", "top5", "seven", "nasdaq", "hangseng", "hangtech"}:
            raise HTTPException(400, "账户组无效")
        return app.state.runtime.query("deleted_accounts", group)

    @app.get("/api/jobs")
    def jobs():
        return app.state.runtime.jobs()

    @app.get("/api/jobs/{identity}")
    def job(identity: str):
        return app.state.runtime.job(identity)

    @app.post("/api/jobs")
    async def submit(request: Request):
        data = await request.json()
        if not isinstance(data, dict) or not isinstance(data.get("params", {}), dict):
            raise HTTPException(400, "任务格式无效")
        params = data.get("params", {})
        if set(params) - {"group", "id", "name", "strategy", "capital", "start", "end", "upload_id", "expected_day", "force_history"}:
            raise HTTPException(400, "不支持的参数；不能指定服务器文件路径")
        return app.state.runtime.submit(data.get("action", ""), params, data.get("idempotency_key", ""))

    @app.post("/api/jobs/{identity}/cancel")
    def cancel(identity: str):
        runtime = app.state.runtime
        job = runtime.job(identity)
        if job["status"] not in FINAL and identity in runtime.stops:
            if job["params"].get("_automatic"):
                if job["action"] == "auto_advance":
                    key = job["params"]["group"] + ":" + job["params"]["id"]
                    runtime.change_settings({"account_auto": {"key": key, "enabled": False}})
                elif job["action"] == "auto_scan":
                    runtime.change_settings({"auto_simulate": False})
                elif job["action"] in {"quotes", "refresh"}:
                    runtime.change_settings({"auto_refresh": False})
            stop = runtime.stops.get(identity)
            if stop is not None:
                stop.set()
                runtime.update(identity, progress="已申请停止，等待当前安全步骤完成")
        return runtime.job(identity)

    @app.get("/api/settings")
    def settings():
        return app.state.runtime.status()

    @app.post("/api/settings")
    async def change_settings(request: Request):
        value = await request.json()
        return await asyncio.to_thread(app.state.runtime.change_settings, value)

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".zip", ".json"}:
            raise HTTPException(400, "只支持原程序导出的ZIP或JSON账户备份")
        runtime = app.state.runtime
        path = runtime.private / "uploads" / (secrets.token_hex(24) + suffix)
        length = 0
        try:
            with path.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    length += len(chunk)
                    if length > MAX_UPLOAD:
                        raise HTTPException(413, "账户备份不能超过25MB")
                    out.write(chunk)
            if suffix == ".zip":
                try:
                    with zipfile.ZipFile(path) as z:
                        items = z.infolist()
                        if len(items) > 500 or sum(x.file_size for x in items) > 100 * 1024 * 1024:
                            raise ValueError("备份解压后过大")
                        for info in items:
                            parts = info.filename.replace("\\", "/").split("/")
                            if ".." in parts or info.filename.startswith(("/", "\\")) or ":" in info.filename:
                                raise ValueError("备份包含不安全路径")
                except (zipfile.BadZipFile, ValueError) as exc:
                    raise HTTPException(400, str(exc))
            entry = runtime.register_file(path, "upload", file.filename)
            return {"upload_id": entry["file_id"], "size": length}
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @app.get("/api/download/{identity}")
    def download(identity: str):
        path, name = app.state.runtime.file(identity)
        return FileResponse(path, filename=name, media_type="application/octet-stream")

    @app.get("/api/report")
    def report():
        return FileResponse(ROOT / "创业板策略研究与应用报告.pdf", media_type="application/pdf")

    @app.get("/")
    def index():
        control_link = '<a class="button secondary" href="/d0-control#broker">东方财富证券</a>' if d0_web else ""
        broker_nav = ('<a class="nav-item" href="/d0-control#broker"><span aria-hidden="true">↗</span>'
                      '<span>东方财富证券</span></a>') if d0_web else ""
        return HTMLResponse(ui_html.replace("__D0_CONTROL_LINK__", control_link).replace("__BROKER_NAV__", broker_nav))

    app.mount("/static", StaticFiles(directory=ROOT / "web_static", check_dir=False), name="static")
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--set-password", action="store_true")
    parser.add_argument("--hash-password", action="store_true")
    args = parser.parse_args()
    if args.set_password or args.hash_password:
        password = getpass.getpass("设置登录口令（至少12字符）: ")
        if password != getpass.getpass("再次输入: "):
            raise SystemExit("两次口令不一致")
        encoded = hash_password(password)
        if args.hash_password:
            print(encoded)
        else:
            home = Path(os.environ.get("SIMPLE_ETF_HOME", str(ROOT.parent / "runtime-data")))
            atomic_json(home / "web" / "auth.json", {"password_hash": encoded})
            try:
                (home / "web" / "auth.json").chmod(0o600)
            except OSError:
                pass
            print("登录口令已保存。")
        return
    if args.host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("ETF_WEB_SECURE_COOKIE") != "1":
        raise SystemExit("非本机监听需配置HTTPS反向代理，并设置ETF_WEB_SECURE_COOKIE=1")
    import uvicorn
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1, access_log=False,
                proxy_headers=True, forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    mp.freeze_support()
    main()
