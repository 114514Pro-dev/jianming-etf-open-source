"""Read-only in-app reminders projected from committed paper-ledger events.

This module has no clock, storage, observer, transport, or trading side effects.
An item records a submitted simulated order; it never instructs a trade.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation


CONTRACT_VERSION = "paper-trade-alerts-v1"
CN = timezone(timedelta(hours=8))
SYMBOLS = frozenset(("sz159915", "sh512800", "sh518880", "sh511010"))
LABEL = "D0 模拟委托提醒（仅供核对）"


def _identifier(value):
    return value if type(value) is str and value.strip() and len(value) <= 4096 else None


def _moment(value):
    try:
        if type(value) is str:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif type(value) is not datetime:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(CN)
    except (ValueError, TypeError, OverflowError):
        return None


def _price(value):
    if type(value) not in (str, int, float, Decimal):
        return None
    try:
        number = Decimal(str(value))
        # Preserve a finite decimal representation without expanding arbitrary
        # exponents from malformed input into an unbounded output string.
        return str(number) if number.is_finite() and number > 0 else None
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None


def _time_text(value):
    moment = _moment(value)
    return (value if type(value) is str else moment.isoformat()) if moment is not None else None


def _day(value):
    try:
        return value if type(value) is str and date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _timestamp_reason(values):
    if any(value is None or value == "" for value in values):
        return "missing_timestamp"
    if any(_moment(value) is None for value in values):
        return "invalid_timestamp"
    return None


def _reference(order, event, account, signal, plan, now_value, source, observer, command):
    """Return a conservative presentation state, never an execution gate."""
    if any(_identifier(order.get(key)) is None for key in ("signal_id", "plan_id", "intent_id")):
        return "needs_review", "missing_association"
    symbol = order.get("symbol")
    if (order.get("side") not in ("buy", "sell") or type(symbol) is not str or symbol not in SYMBOLS
            or type(order.get("qty")) is not int or order["qty"] <= 0
            or _price(order.get("limit_price")) is None or account.get("strategy") not in ("D0", "D0I-BOND-WW")):
        return "needs_review", "invalid_order_fields"
    time_values = [order.get(key) for key in ("signal_at", "submitted_at", "eligible_at", "expires_at")]
    bad_time = _timestamp_reason([*time_values, event.get("at"), now_value])
    if bad_time:
        return "needs_review", bad_time
    signal_at, submitted, eligible, expires = map(_moment, time_values)
    event_at, now = _moment(event["at"]), _moment(now_value)
    if any(value > now for value in (signal_at, submitted, event_at)):
        return "needs_review", "future_timestamp"
    if not signal_at <= submitted <= event_at or not submitted <= eligible < expires:
        return "needs_review", "inconsistent_timestamps"
    status = order.get("status")
    if status in ("cancelled", "expired", "filled"):
        return "historical", {"cancelled": "order_cancelled", "expired": "order_expired",
                              "filled": "order_filled"}[status]
    if status != "pending":
        return "needs_review", "order_not_pending"
    if (type(order.get("remaining_qty")) is not int or not 0 < order["remaining_qty"] <= order["qty"]
            or type(order.get("qty_filled")) is not int or order["qty_filled"] < 0
            or order["remaining_qty"] + order["qty_filled"] != order["qty"]
            or order.get("terminal_at") is not None):
        return "needs_review", "invalid_order_fields"
    if command is not False:
        return "historical", "command_snapshot"
    if account.get("running") is False:
        return "historical", "account_stopped"
    if account.get("running") is not True:
        return "needs_review", "unknown_state"
    if any(_identifier(value) is None for value in (signal.get("id"), plan.get("id"), plan.get("signal_id"))):
        return "needs_review", "missing_association"
    if order["signal_id"] != signal["id"]:
        return "historical", "old_signal"
    if order["plan_id"] != plan["id"] or plan["signal_id"] != signal["id"]:
        return "historical", "old_plan"
    generation = account.get("activation_generation")
    if (type(generation) is not int or generation < 0
            or type(plan.get("generation")) is not int or plan["generation"] < 0):
        return "needs_review", "invalid_order_fields"
    if plan["generation"] != generation:
        return "historical", "generation_mismatch"
    if signal.get("strategy") != account.get("strategy") or signal.get("valid") is not True:
        return "needs_review", "unknown_state"
    signal_values = [signal.get(key) for key in
                     ("data_cutoff", "signal_at", "known_at", "received_at", "eligible_at")]
    bad_time = _timestamp_reason([*signal_values, account.get("resumed_at"), plan.get("created_at")])
    if bad_time:
        return "needs_review", bad_time
    cutoff, signal_time, known, received, signal_eligible = map(_moment, signal_values)
    resumed, created = _moment(account["resumed_at"]), _moment(plan["created_at"])
    if any(value > now for value in (cutoff, signal_time, known, received, resumed, created)):
        return "needs_review", "future_timestamp"
    if (not cutoff <= signal_time <= known <= received <= created <= submitted
            or signal_at != signal_time or not resumed <= created
            or eligible < signal_eligible):
        return "needs_review", "inconsistent_timestamps"
    execution_day, session_day = _day(signal.get("execution_day")), _day(plan.get("session_day"))
    if execution_day is None or session_day is None:
        return "needs_review", "invalid_order_fields"
    if execution_day != now.date().isoformat():
        return "historical", "old_signal"
    if session_day != now.date().isoformat():
        return "historical", "old_plan"
    if any(value.date() != now.date() for value in (submitted, event_at, eligible, expires)):
        return "needs_review", "inconsistent_timestamps"
    if now >= expires:
        return "historical", "expired_by_time"
    if now < eligible:
        return "historical", "before_eligible"
    if source != "ready":
        return "needs_review", "source_not_ready"
    if observer != "running":
        return "needs_review", "observer_not_running"
    local_time = now.time().replace(tzinfo=None)
    if not (time(9, 30) <= local_time < time(11, 30) or time(13) <= local_time < time(14, 57)):
        return "historical", "outside_session"
    return "current_reference", "current_reference"


def project_trade_alerts(raw, *, now, source_status, observer_status, command=False, security_names=None):
    """Project a deterministic, detached reminder view from one ledger snapshot.

    Only a submitted event associated with exactly one non-rejected order can
    produce an item. No target weights, plans, fills, or rejection events create
    reminders. Missing or inconsistent evidence can never establish a current
    reference. ``now`` and source/observer status are supplied by the caller.
    """
    raw = raw if type(raw) is dict else {}
    account = raw.get("account") if type(raw.get("account")) is dict else {}
    account_id = _identifier(account.get("id"))
    result = {"contract_version": CONTRACT_VERSION, "channel": "in_app",
              "email_status": "not_integrated", "account_id": account_id, "items": []}
    if account_id is None or type(raw.get("orders")) is not list or type(raw.get("events")) is not list:
        return result

    orders, duplicate_ids = {}, set()
    for order in raw["orders"]:
        if type(order) is not dict:
            continue
        order_id = _identifier(order.get("id"))
        if order_id is None:
            continue
        if order_id in orders:
            duplicate_ids.add(order_id)
        else:
            orders[order_id] = order
    events, event_signatures = {}, {}
    for event in raw["events"]:
        if type(event) is not dict:
            continue
        event_id, order_id = _identifier(event.get("id")), _identifier(event.get("order_id"))
        if event_id is None:
            continue
        try:
            signature = json.dumps(event, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError, RecursionError):
            signature = None
        event_signatures.setdefault(event_id, set()).add(signature)
        if event.get("type") != "submitted":
            continue
        if order_id not in orders or order_id in duplicate_ids:
            continue
        order = orders[order_id]
        if (order.get("status") == "rejected"
                or "account_id" in order and order["account_id"] != account_id
                or "account_id" in event and event["account_id"] != account_id):
            continue
        events.setdefault(order_id, []).append((event_id, event, signature))

    signal = raw.get("signal") if type(raw.get("signal")) is dict else {}
    plan = raw.get("plan") if type(raw.get("plan")) is dict else {}
    names = security_names if type(security_names) is dict else {}
    for order_id, submissions in events.items():
        order = orders[order_id]
        source_ids = sorted({event_id for event_id, _, _ in submissions})
        signatures = {signature for _, _, signature in submissions}
        ambiguous = (len(source_ids) != 1 or len(signatures) != 1 or None in signatures
                     or any(len(event_signatures[event_id]) != 1 for event_id in source_ids))
        event = submissions[0][1]
        state, reason = (("needs_review", "ambiguous_submission") if ambiguous else
                         _reference(order, event, account, signal, plan, now,
                                    source_status, observer_status, command))
        identity = json.dumps([account_id, order_id], ensure_ascii=True, separators=(",", ":"))
        symbol = _identifier(order.get("symbol"))
        item = {"id": CONTRACT_VERSION + ":submitted:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                "kind": "submitted_order", "event_id": None if ambiguous else event["id"],
                "source_event_ids": source_ids, "account_id": account_id,
                "order_id": order_id, "signal_id": _identifier(order.get("signal_id")),
                "plan_id": _identifier(order.get("plan_id")), "intent_id": _identifier(order.get("intent_id")),
                "triggered_at": None if ambiguous else _time_text(event.get("at")),
                "side": order.get("side") if order.get("side") in ("buy", "sell") else None,
                "symbol": symbol, "code": symbol[2:] if symbol in SYMBOLS else None,
                "name": _identifier(names.get(symbol)) if symbol in SYMBOLS else None,
                "quantity": order.get("qty") if type(order.get("qty")) is int and order["qty"] > 0 else None,
                "limit_price": _price(order.get("limit_price")),
                **{key: _time_text(order.get(key)) for key in
                   ("signal_at", "submitted_at", "eligible_at", "expires_at")},
                "order_status": _identifier(order.get("status")) or "unknown",
                "reference_status": state, "reason_code": reason,
                "label": LABEL if account.get('strategy') != 'D0I-BOND-WW' else 'D0I-BOND-WW 模拟委托提醒（仅供核对）',
                "is_trade_instruction": False}
        result["items"].append(item)
    result["items"].sort(key=lambda item: (item["triggered_at"] is None,
                          _moment(item["triggered_at"]) or datetime.max.replace(tzinfo=CN), item["id"]))
    return result
