"""Isolated forward-only D0 paper trading service; old market stores are read only."""
from __future__ import annotations

import copy
from contextlib import closing, contextmanager
import hashlib
import json
import math
import re
from pathlib import Path
import sqlite3
import threading
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from time import monotonic
from d0_order_math import LOT, MAX_ORDER_QTY, SYMBOLS, commission, limit_price, target_quantity
from realtime_paper_history import AcceptedHistory, HistoryContinuityError
from realtime_paper_charts import extract_indicator_histories, unavailable as unavailable_chart_history
from realtime_paper_price_history import extract_daily_price_histories, unavailable as unavailable_price_history
from realtime_paper_intraday_charts import IntradayChartReader

TZ = ZoneInfo("Asia/Shanghai")
ACTIVE = {"pending", "submitted", "accepted", "open", "partially_filled"}
MODEL = {
    "name": "公开报价观察后估计成交",
    "description": "D0 保留收盘确认；只对启动后提交的委托观察报价，不补造已错过的开盘成交。",
    "limit_tolerance_bps": 20,
    "limits": ["公开报价没有权威停牌字段，交易状态保持未核实。", "满足两次活动证据后按整单估计，无盘口数量或真实排队及流动性证明。", "佣金及滑点为固定模拟假设，不代表实际券商收费与成交成本。", "公司行动只检测现有行情资料中的记录；缺失记录不能视为已核验无事件。", "未提供盘口、排队顺序或流动性证明。", "成交为模型估计，不代表券商成交。", "暂停会撤销待成交委托，既有成交保留。"],
}


def _now(value=None):
    value = value() if callable(value) else value
    value = value or datetime.now(TZ)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _decimal(value, default="0"):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else Decimal(default)
    except Exception:
        return Decimal(default)


def _num(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


class SourceUnavailable(ValueError):
    pass


class ReadOnlyPaperSource:
    """Read public daily JSON and intraday SQLite without opening old accounts.

    Timestamp fields always preserve their producer values. Reading a cached quote
    again does not give it a new received_at time.
    """
    def __init__(self, home, now=None, calendar=None, market_factory=None, spec_factory=None, max_quote_age=60, validator=None, digester=None, strategy='D0'):
        if strategy not in ('D0', 'D0I-BOND-WW'):
            raise ValueError('unsupported paper strategy')
        self.strategy = strategy
        self.home = Path(home)
        self.now = now
        self.calendar = calendar
        self.market_factory = market_factory
        self.spec_factory = spec_factory
        self.max_quote_age = max_quote_age
        self.validator = validator
        self.digester = digester
        self._history_archive = None
        self._continuity_key = None
        self._continuity_data = None
        self._daily_reference = None
        self._daily_key = None
        self._daily = None
        self._signal_key = None
        self._signal = None
        self._market = None
        self._producer_barrier = None
        self._producer_table_seen = False
        self._producer_attempt_seen = False
        self._producer_problem = None
        self._producer_cursor = 0
        self._producer_latest = None
        self._producer_latest_invalid = False
        self._pending_producer_invalidation = None

    def indicator_history(self, saved_signal):
        # Snapshot-only cache projection. Never warm a cache or read source data
        # here: its identity must already match the ledger's confirmed signal.
        return extract_indicator_histories(saved_signal, self._signal, self._signal_key, self._market)

    def daily_price_history(self, saved_signal):
        return extract_daily_price_histories(saved_signal, self._signal, self._signal_key, self._market)

    def _calendar(self):
        if self.calendar is None:
            from realtime_paper_engine import TradingCalendar
            self.calendar = TradingCalendar()
        return self.calendar

    def _is_session(self, day):
        cal = self._calendar()
        return bool(cal.is_session(day))

    def _expected(self, current):
        cal = self._calendar()
        if hasattr(cal, "expected_confirmed_day"):
            confirmed = cal.expected_confirmed_day(current)
            if confirmed is None:
                raise SourceUnavailable("calendar_unavailable")
            return str(confirmed)[:10]
        day = current.date()
        if self._is_session(day) and current.time().replace(tzinfo=None) >= time(16, 10):
            return day.isoformat()
        for back in range(1, 20):
            candidate = day - timedelta(days=back)
            if self._is_session(candidate):
                return candidate.isoformat()
        raise SourceUnavailable("calendar_unavailable")

    def _next(self, day):
        cal = self._calendar()
        if hasattr(cal, "next_session"):
            result = cal.next_session(date.fromisoformat(day))
            if result is None:
                raise SourceUnavailable("calendar_unavailable")
            return str(result)[:10]
        origin = date.fromisoformat(day)
        for ahead in range(1, 20):
            candidate = origin + timedelta(days=ahead)
            if self._is_session(candidate):
                return candidate.isoformat()
        raise SourceUnavailable("calendar_unavailable")

    def _daily_data(self):
        settings_path = self.home / "设置.json"
        expected_hash = None
        if settings_path.is_file():
            settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            if not isinstance(settings, dict):
                raise SourceUnavailable("market_settings_invalid")
            reference = settings.get("market")
            if reference is not None and reference != "":
                if not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{64}", reference):
                    raise SourceUnavailable("market_reference_invalid")
                primary = self.home / "行情快照" / (reference + ".json")
                expected_hash = reference
            else:
                primary = Path(__file__).with_name("初始行情.json")
        else:
            # Compatibility for explicitly provided earlier public caches only.
            primary = self.home / "联合行情缓存.json"
            if not primary.is_file():
                primary = Path(__file__).with_name("初始行情.json")
        self._daily_origin = "home_snapshot" if expected_hash is not None else ("bundled_historical_seed" if primary.name == "初始行情.json" else "legacy_public_cache")
        if not primary.is_file():
            raise SourceUnavailable("daily_data_missing")
        self._daily_reference = expected_hash
        stat = primary.stat()
        key = (str(primary), stat.st_size, stat.st_mtime_ns, expected_hash)
        if key != self._daily_key:
            data = json.loads(primary.read_text(encoding="utf-8-sig"))
            if expected_hash is not None:
                if self.validator is None or self.digester is None:
                    from bank_model import validate_data, digest
                validator = self.validator or validate_data
                digester = self.digester or digest
                data = validator(data)
                if digester(data) != expected_hash:
                    raise SourceUnavailable("market_snapshot_hash_mismatch")
            if not isinstance(data, dict) or any(not isinstance(data.get(k), dict) for k in ("chi", "bank")):
                raise SourceUnavailable("daily_data_invalid")
            available_days = []
            for group in ("chi", "bank"):
                for symbol, rows in data[group].get("bars", {}).items():
                    if symbol in SYMBOLS and isinstance(rows, list):
                        days = [row.get("date") for row in rows if isinstance(row, dict) and isinstance(row.get("date"), str)]
                        if days:
                            available_days.append(max(days))
            self._daily_asof = min(available_days) if available_days else None
            self._daily, self._daily_key = data, key
        return copy.deepcopy(self._daily)

    @staticmethod
    def _truncate(data, cutoff):
        output = copy.deepcopy(data)
        found = {}
        for group in ("chi", "bank"):
            bars = output[group].get("bars")
            if not isinstance(bars, dict):
                raise SourceUnavailable("daily_data_invalid")
            for symbol, rows in bars.items():
                if not isinstance(rows, list):
                    raise SourceUnavailable("daily_data_invalid")
                selected = [r for r in rows if isinstance(r, dict) and isinstance(r.get("date"), str) and r["date"] <= cutoff]
                selected.sort(key=lambda r: r["date"])
                bars[symbol] = selected
                if symbol in SYMBOLS:
                    found.setdefault(symbol, []).append(selected[-1]["date"] if selected else None)
        return output, found

    @staticmethod
    def _history_hash(data, cutoff):
        truncated, _ = ReadOnlyPaperSource._truncate(data, cutoff)
        # Metadata such as actions/splits remains in the fingerprint. A revision
        # needs an accounting review; quantities are never silently adjusted.
        stable = {}
        for group in ("chi", "bank"):
            child = truncated[group]
            stable[group] = {"bars": {symbol: rows for symbol, rows in child["bars"].items() if symbol in SYMBOLS}}
            for key in ("actions", "splits", "dividends", "adjustments", "corporate_actions"):
                if key in child:
                    stable[group][key] = child[key]
        return _hash(stable)

    @staticmethod
    def _asset_event(market, start_day, end_day):
        inputs = getattr(market, "inputs", None)
        for name in ("actions", "splits"):
            collection = getattr(inputs, name, {}) if inputs is not None else {}
            for symbol in SYMBOLS:
                item = collection.get(symbol, {}) if isinstance(collection, dict) else {}
                if name == "splits" and isinstance(item, dict) and any(start_day < str(day)[:10] <= end_day for day in item):
                    return True
                if name == "actions" and isinstance(item, dict):
                    for row in item.get("dividends", []):
                        if isinstance(row, dict) and any(value and start_day < str(value)[:10] <= end_day for value in (row.get("record"), row.get("ex"), row.get("pay"))):
                            return True
        return False

    def _invalidate_producer(self, reason, stamp):
        self._activity_invalidation = reason
        self._pending_producer_invalidation = reason
        self._last_batch_was_valid = False
        self._producer_barrier = max(self._producer_barrier or stamp, stamp)

    def acknowledge_activity_invalidation(self):
        # A failed ledger transaction must not consume the producer notification.
        self._pending_producer_invalidation = None

    @staticmethod
    def _attempt_time(row, current):
        try:
            if not isinstance(row[1], str) or not row[1] or not isinstance(row[2], str) or not row[2]:
                return None
            stamp = datetime.fromisoformat(row[2].replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None or stamp > current:
                return None
            return stamp.astimezone(TZ)
        except (ValueError, TypeError, OverflowError):
            return None

    def _producer_state(self, connection):
        """Consume producer failures once, in the same read transaction as quotes.

        Success is recorded after its snapshot in a separate producer transaction.
        A newer quote may therefore recover from a known failed attempt before its
        success row arrives. Both quote and receipt must be after that failure.
        """
        problem = None
        latest = None
        rows = []
        try:
            exists = connection.execute("SELECT type FROM sqlite_master WHERE name='attempts'").fetchone()
            if not exists:
                if self._producer_table_seen:
                    problem = "attempts_table_disappeared"
            elif exists[0] != "table":
                problem = "attempts_schema_invalid"
            else:
                self._producer_table_seen = True
                # 日线失败 belongs to the older daily-refresh interface, not quotes.
                latest = connection.execute("SELECT rowid,id,attempted_at,status FROM attempts WHERE status IS NULL OR status != '日线失败' ORDER BY rowid DESC LIMIT 1").fetchone()
                last_rowid = connection.execute("SELECT COALESCE(MAX(rowid),0) FROM attempts").fetchone()[0]
                if not last_rowid and self._producer_attempt_seen:
                    problem = "attempts_history_disappeared"
                elif last_rowid < self._producer_cursor:
                    problem = "attempts_history_replaced"
                else:
                    rows = connection.execute("SELECT rowid,id,attempted_at,status FROM attempts WHERE rowid > ? ORDER BY rowid LIMIT 513", (self._producer_cursor,)).fetchall()
                    self._producer_attempt_seen |= bool(last_rowid)
        except sqlite3.Error:
            problem = "attempts_unreadable"
        # A producer can commit after read() starts but before this snapshot.
        # Validate against completion time, never an earlier sampling instant.
        current = _now(self.now)
        if problem:
            if problem != self._producer_problem:
                self._invalidate_producer("quotes_collection_state_invalid", current)
            self._producer_problem = problem
            self._producer_cursor = 0
            return "quotes_collection_state_invalid", current
        pending = len(rows) > 512
        for attempt in rows[:512]:
            if attempt[3] == "日线失败":
                continue
            stamp = self._attempt_time(attempt, current)
            valid = attempt[3] in {"成功", "失败"} and stamp is not None
            if not valid or attempt[3] == "失败":
                self._invalidate_producer("quotes_collection_failed" if valid else "quotes_collection_state_invalid", stamp if valid else current)
        if rows:
            self._producer_cursor = rows[min(511, len(rows) - 1)][0]
        if pending:
            if self._producer_problem != "attempts_backlog":
                self._invalidate_producer("quotes_collection_state_invalid", current)
            self._producer_problem = "attempts_backlog"
            return "quotes_collection_state_invalid", current
        self._producer_problem = None
        if latest is None:
            return None, current  # Legacy missing/empty history remains readable.
        stamp = self._attempt_time(latest, current)
        invalid = latest[3] not in {"成功", "失败"} or stamp is None
        if latest == self._producer_latest:
            invalid = invalid or self._producer_latest_invalid
        elif latest not in rows and (invalid or latest[3] == "失败"):
            self._invalidate_producer("quotes_collection_state_invalid" if invalid else "quotes_collection_failed", current if invalid else stamp)
        self._producer_latest = latest
        self._producer_latest_invalid = invalid
        return ("quotes_collection_state_invalid" if invalid else None), current

    def _batch(self, current):
        self._batch_observed_this_read = True
        path = self.home / "盘中行情.sqlite3"
        if not path.is_file():
            self._observation_state = "unavailable"
            self._activity_invalidation = "quotes_missing"
            return None, "quotes_missing"
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            row = connection.execute("SELECT payload, received_at FROM snapshots ORDER BY received_at DESC LIMIT 1").fetchone()
            producer_problem, current = self._producer_state(connection)
        if not row:
            self._observation_state = "unavailable"
            self._activity_invalidation = "quotes_missing"
            return None, "quotes_missing"
        batch = json.loads(row[0])
        self._observed_batch = batch if isinstance(batch, dict) else None
        identity = _hash(batch)
        repeated = identity == getattr(self, "_last_batch_fingerprint", None)
        accepted_repeat = repeated and getattr(self, "_last_batch_was_valid", False)
        self._last_batch_fingerprint = identity
        if not repeated:
            self._last_batch_was_valid = False
        self._observation_state = "repeat" if repeated else "new"

        def reject(reason):
            # A quote producer may update every 30 seconds while this observer
            # polls every five. Aging the same accepted cache is not new failure.
            if accepted_repeat and reason in {"quote_queue_delay", "quotes_stale"}:
                return None, reason
            self._observation_state = "repeat_invalid" if repeated else "new_invalid"
            if not repeated:
                self._activity_invalidation = reason
            return None, reason

        if producer_problem:
            self._observation_state = "producer_blocked"
            return None, producer_problem
        if repeated and not accepted_repeat:
            return reject("cached_invalid_quote")
        if not isinstance(batch, dict) or not isinstance(batch.get("quotes"), dict):
            return reject("quotes_invalid")
        try:
            received = _now(batch.get("received_at")) if batch.get("received_at") else None
            if received is None or str(batch.get("received_at")) != str(row[1]):
                return reject("quotes_invalid")
            if self._producer_barrier is not None and received <= self._producer_barrier:
                return reject("quote_precedes_collection_failure")
            if not 0 <= (current - received).total_seconds() <= self.max_quote_age:
                return reject("quotes_stale")
            if (current - received).total_seconds() > 5:
                return reject("quote_queue_delay")
            for symbol in SYMBOLS:
                quote = batch["quotes"].get(symbol)
                if not isinstance(quote, dict) or not quote.get("quote_at"):
                    return reject("quotes_missing")
                stamp = _now(quote["quote_at"])
                if self._producer_barrier is not None and stamp <= self._producer_barrier:
                    return reject("quote_precedes_collection_failure")
                if not 0 <= (received - stamp).total_seconds() <= self.max_quote_age or not 0 <= (current - stamp).total_seconds() <= self.max_quote_age or stamp.date() != current.date():
                    return reject("quotes_stale")
                if _num(quote.get("price")) <= 0 or _num(quote.get("previous_close")) <= 0:
                    return reject("quotes_invalid")
        except (ValueError, TypeError, OverflowError):
            return reject("quotes_invalid")
        self._last_batch_was_valid = True
        self._observation_state = "repeat" if repeated else "new_valid"
        return batch, "ready"

    def read(self, previous_signal=None):
        current = _now(self.now)
        result = {"signal": None, "batch": None, "source_status": "blocked", "reason": "source_unavailable", "observed_at": current.isoformat()}
        self._batch_observed_this_read = False
        self._observed_batch = None
        self._observation_state = "unavailable"
        self._activity_invalidation = self._pending_producer_invalidation
        try:
            expected = self._expected(current)
            data = self._daily_data()
            result.update(daily_origin=self._daily_origin, daily_asof=self._daily_asof, historical_seed=self._daily_origin == "bundled_historical_seed")
            if self._history_archive is None:
                from bank_model import validate_data, digest
                history_options = {} if self.strategy == 'D0' else {'folder': self.home / 'web' / 'realtime-paper-ww-history'}
                self._history_archive = AcceptedHistory(self.home, self._history_hash, self._truncate,
                    self.validator or validate_data, self.digester or digest, **history_options)
            continuity_key = (self._daily_key, expected, (previous_signal or {}).get("history_cutoff"),
                              (previous_signal or {}).get("history_hash"))
            if continuity_key != self._continuity_key:
                data, retention = self._history_archive.reconcile(data, previous_signal or {}, self._daily_reference)
                self._continuity_data = (copy.deepcopy(data), retention)
                self._continuity_key = continuity_key
            else:
                data, retention = copy.deepcopy(self._continuity_data)
            truncated, found = self._truncate(data, expected)
            if any(not found.get(s) or any(day != expected for day in found[s]) for s in SYMBOLS):
                raise SourceUnavailable("confirmed_daily_data_missing")
            history_hash = self._history_hash(data, expected)
            signal_key = (expected, history_hash) if self.strategy == 'D0' else (expected, history_hash, self.strategy)
            if self.spec_factory is None and self.strategy != 'D0':
                from d0i_bond_ww import spec as ww_spec
                specification = ww_spec()
            elif self.spec_factory is None:
                from bank_model import spec
                specification = spec("D0")
            else:
                specification = self.spec_factory(self.strategy)
            spec_hash = _hash(specification)
            # A same-day rule upgrade must not reuse the old target. Keep the
            # public history key shape used by read-only chart projections.
            if self._signal_key != signal_key or (self._signal or {}).get('spec_hash') != spec_hash:
                if self.market_factory is None:
                    from trade_book import Market
                    factory = Market
                else:
                    factory = self.market_factory
                market = factory(data=truncated)
                if self.strategy == 'D0':
                    observation = dict(market.observation("D0", expected))
                else:
                    from d0i_bond_ww import observation as ww_observation
                    observation = ww_observation(market, expected)
                confirmed = market.at(expected)
                if any(confirmed.get("dates", {}).get(symbol) != expected or _decimal(confirmed.get("prices", {}).get(symbol)) <= 0 for symbol in SYMBOLS):
                    raise SourceUnavailable("confirmed_daily_data_missing")
                observation["reference_prices"] = {symbol: str(_decimal(confirmed["prices"][symbol])) for symbol in SYMBOLS}
                weights = observation.get("weights")
                if not isinstance(weights, dict) or any(s not in SYMBOLS or _num(w, -1) < 0 for s, w in weights.items()) or sum(_num(w) for w in weights.values()) > 1.000001:
                    raise SourceUnavailable("signal_invalid")
                observation.update(market_hash=history_hash, spec_hash=spec_hash)
                if not observation.get("reason"):
                    raise SourceUnavailable("signal_reason_missing")
                next_day = self._next(expected)
                observation.update({"id": _hash({"day": expected, "weights": weights, "history": history_hash, "spec": specification}), "strategy": self.strategy, "day": expected, "signal_at": current.isoformat(), "received_at": current.isoformat(), "market_at": f"{expected}T15:00:00+08:00", "eligible_at": f"{next_day}T09:30:00+08:00", "history_cutoff": expected, "history_hash": history_hash})
                version = 'D0-forward-bank-ma50-v1' if self.strategy == 'D0' else self.strategy + '-forward-v1'
                observation.update({"known_at": current.isoformat(), "data_cutoff": observation["market_at"], "confirmed_day": expected, "execution_day": next_day, "version": version, "source": "已确认日线 " + self.strategy, "valid": True, "waiting_reason": None})
                completed = _now(self.now)
                if self._expected(completed) != expected:
                    raise SourceUnavailable("confirmation_boundary_changed")
                observation.update(signal_at=completed.isoformat(), known_at=completed.isoformat(), received_at=completed.isoformat())
                current = completed
                result["observed_at"] = completed.isoformat()
                if previous_signal and previous_signal.get("id") == observation["id"]:
                    for field in ("signal_at", "received_at", "known_at"):
                        if previous_signal.get(field):
                            observation[field] = previous_signal[field]
                self._signal, self._signal_key, self._market = observation, signal_key, market
            previous_day = (previous_signal or {}).get("confirmed_day", (previous_signal or {}).get("day", expected))
            if self._asset_event(self._market, previous_day, current.date().isoformat()):
                raise SourceUnavailable("corporate_action_review_required")
            try:
                result['history_continuity'] = self._history_archive.commit(data, expected,
                    self._daily_reference, retention, current.isoformat())
            except HistoryContinuityError:
                raise
            except (OSError, ValueError):
                raise SourceUnavailable('history_checkpoint_write_failed')
            result["signal"] = copy.deepcopy(self._signal)
            batch, reason = self._batch(current)
            status = "ready" if batch else ("blocked" if reason == "quotes_collection_state_invalid" else "waiting")
            result.update(batch=batch, source_status=status, reason=reason)
        except (SourceUnavailable, HistoryContinuityError) as exc:
            result["reason"] = str(exc)
        except Exception:
            result["reason"] = "source_read_failed"
        if not self._batch_observed_this_read:
            # Daily data can block trading without hiding a new explicit halt.
            try:
                self._batch(_now(self.now))
            except Exception:
                self._activity_invalidation = "quotes_read_failed"
        if result["source_status"] == "blocked" and result["reason"] != "quotes_collection_state_invalid":
            self._activity_invalidation = result["reason"]
        result.update(observed_batch=copy.deepcopy(self._observed_batch), observation_state=self._observation_state, activity_invalidation=self._activity_invalidation)
        return result


class PaperServiceStopping(RuntimeError):
    """The service has stopped admitting operations that may write."""


class PaperServiceShutdownTimeout(TimeoutError):
    """Shutdown is incomplete; the host must retain its exclusive data lock."""


class PaperServiceBackupTimeout(TimeoutError):
    """No backup barrier was acquired before its deadline."""


class PaperServiceBackupActive(RuntimeError):
    """A backup owner may read state but must not reenter a mutation."""


class PaperService:
    """One isolated account and worker. This class never invokes the old Runtime."""
    def __init__(self, home, source=None, ledger=None, now=None, start_worker=True, strategy='D0'):
        if strategy not in ('D0', 'D0I-BOND-WW'):
            raise ValueError('unsupported paper strategy')
        self.strategy = strategy
        self.home = Path(home)
        self.now = now
        if ledger is None:
            from realtime_paper_engine import PaperLedger
            ledger = PaperLedger(self.home, now=now, strategy=strategy)
        if getattr(ledger, 'strategy', strategy) != strategy:
            raise ValueError('paper service and ledger strategy mismatch')
        self.ledger = ledger
        self.source = source or ReadOnlyPaperSource(home, now=now, calendar=getattr(ledger, "calendar", None), strategy=strategy)
        if getattr(self.source, 'strategy', strategy) != strategy:
            raise ValueError('paper service and source strategy mismatch')
        # Shared across HTTP adapters. Construction performs no IO; only a
        # display GET reads this bounded, read-only cache, outside _lock.
        self.intraday_charts = IntradayChartReader(self.home)
        self._lock = threading.RLock()
        self._admission = threading.Condition()
        self._active_writes = {}
        self._active_operations = {}
        self._backup_owners = {}
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._source_state = {"source_status": "waiting", "reason": "not_observed", "last_observed": None}
        self._last_batch = None
        self._plans = 0
        self._signal_listener = None
        self._thread = None
        if start_worker:
            self._thread = threading.Thread(target=self._worker, name="realtime-paper" + ("-ww" if strategy != 'D0' else ""), daemon=True)
            self._thread.start()

    def _worker(self):
        while not self._stop.is_set():
            try:
                self.poll_once()
            except PaperServiceStopping:
                break
            except Exception:
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._source_state.update(source_status="blocked", reason="worker_iteration_failed")
                    try:
                        self._write(self.ledger.invalidate_activity, "worker_iteration_failed")
                    except PaperServiceStopping:
                        break
                    except Exception:
                        self._source_state["reason"] = "activity_invalidation_failed"
            self._notify_signal_listener()
            self._stop.wait(5)

    def set_signal_listener(self, listener):
        """Attach the optional D0 read-only publisher; never mutate the ledger."""
        if self.strategy != 'D0':
            raise ValueError('signal listener only supports D0')
        self._signal_listener = listener

    def _notify_signal_listener(self):
        listener = self._signal_listener
        if listener is None or self._stop.is_set():
            return
        try:
            with self._lock:
                target = None if self._source_state.get('historical_seed') else self.export_live_signal()
        except Exception:
            target = None
        try:
            listener(target)
        except Exception:
            # A failed website listener must not stop market updates.
            pass

    def _ensure_open(self):
        with self._admission:
            if self._stop.is_set() or self._closed.is_set():
                raise PaperServiceStopping("paper service is stopping; writes are not accepted")

    def _ensure_mutation_allowed(self):
        with self._admission:
            self._ensure_open()
            if self._backup_owners.get(threading.get_ident(), 0):
                raise PaperServiceBackupActive("paper backup owner may not mutate the ledger")

    @contextmanager
    def _mutation(self):
        self._ensure_mutation_allowed()  # Do not queue rejected commands behind a reader.
        with self._lock:
            identity = threading.get_ident()
            with self._admission:
                self._ensure_mutation_allowed()  # Recheck a command queued before stop/backup.
                self._active_operations[identity] = self._active_operations.get(identity, 0) + 1
            try:
                yield
            finally:
                with self._admission:
                    self._active_operations[identity] -= 1
                    if not self._active_operations[identity]:
                        del self._active_operations[identity]
                    self._admission.notify_all()

    def _write(self, operation, *args, **kwargs):
        identity = threading.get_ident()
        with self._admission:
            if self._stop.is_set() or self._closed.is_set():
                raise PaperServiceStopping("paper service is stopping; writes are not accepted")
            if self._backup_owners.get(identity, 0):
                raise PaperServiceBackupActive("paper backup owner may not mutate the ledger")
            self._active_writes[identity] = self._active_writes.get(identity, 0) + 1
        try:
            # This one admitted ledger operation may commit or roll back fully.
            return operation(*args, **kwargs)
        finally:
            with self._admission:
                self._active_writes[identity] -= 1
                if not self._active_writes[identity]:
                    del self._active_writes[identity]
                self._admission.notify_all()

    @contextmanager
    def backup_guard(self, timeout=15.0):
        """Hold the observer lock across a host-owned business snapshot.

        Lock order: old Runtime executor -> service lock -> short admission lock.
        The guard is an active operation; close cannot confirm its own guard.
        This barrier does not pause the account, cancel orders or change intent.
        """
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("backup timeout must be a finite nonnegative number")
        self._ensure_open()
        deadline = monotonic() + timeout
        if not self._lock.acquire(timeout=max(0, deadline - monotonic())):
            self._ensure_open()
            raise PaperServiceBackupTimeout("paper backup barrier was not acquired")
        identity = threading.get_ident()
        admitted = False
        try:
            with self._admission:
                self._ensure_open()
                self._active_operations[identity] = self._active_operations.get(identity, 0) + 1
                self._backup_owners[identity] = self._backup_owners.get(identity, 0) + 1
                admitted = True
            yield
        finally:
            if admitted:
                with self._admission:
                    self._backup_owners[identity] -= 1
                    if not self._backup_owners[identity]:
                        del self._backup_owners[identity]
                    self._active_operations[identity] -= 1
                    if not self._active_operations[identity]:
                        del self._active_operations[identity]
                    self._admission.notify_all()
            self._lock.release()

    def request_stop(self):
        with self._admission:
            self._stop.set()

    @property
    def closed(self):
        return self._closed.is_set()

    def close(self, timeout=45.0):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("shutdown timeout must be a finite nonnegative number")
        deadline = monotonic() + timeout
        self.request_stop()
        with self._admission:
            if threading.get_ident() in self._active_operations or threading.get_ident() in self._active_writes or self._thread is threading.current_thread():
                raise PaperServiceStopping("an active paper writer cannot confirm its own shutdown")
            if not self._admission.wait_for(lambda: not self._active_writes and not self._active_operations, timeout=max(0, deadline - monotonic())):
                raise PaperServiceShutdownTimeout("paper operation is still active; retain host lock")
        if self._thread:
            self._thread.join(timeout=max(0, deadline - monotonic()))
            if self._thread.is_alive():
                raise PaperServiceShutdownTimeout("paper observer is still active; retain host lock")
        if not self._lock.acquire(timeout=max(0, deadline - monotonic())):
            raise PaperServiceShutdownTimeout("paper operation is still active; retain host lock")
        try:
            with self._admission:
                if self._active_writes or self._active_operations or (self._thread and self._thread.is_alive()):
                    raise PaperServiceShutdownTimeout("paper shutdown is not complete; retain host lock")
                self._closed.set()
        finally:
            self._lock.release()

    def _command_context(self):
        # Called only while the service lock protects the observed source state.
        from realtime_paper_engine import RESPONSE_CONTEXT_FIELDS
        return {key:copy.deepcopy(value) for key,value in self._source_state.items() if key in RESPONSE_CONTEXT_FIELDS}

    def write_notification(self, operation, *args, **kwargs):
        """Admit a local notification-store write through the same backup and stop barrier."""
        with self._mutation():
            return self._write(operation, *args, **kwargs)

    def create(self, capital, fees=None, name=None, idempotency_key=None):
        with self._mutation():
            return self._write(self.ledger.create, capital, fees=fees or {}, name=name, idempotency_key=idempotency_key, response_context=self._command_context())

    def capital(self, capital, idempotency_key=None):
        with self._mutation():
            return self._write(self.ledger.set_capital, capital, idempotency_key=idempotency_key, response_context=self._command_context())

    def set_running(self, running, idempotency_key=None):
        self._ensure_open()
        if not isinstance(running, bool):
            raise ValueError("running must be a boolean")
        with self._mutation():
            # Core commits state, cancellation and idempotency response together.
            return self._write(self.ledger.set_running, running, idempotency_key=idempotency_key, response_context=self._command_context())

    def cancel(self, order_id, idempotency_key=None):
        with self._mutation():
            return self._write(self.ledger.cancel, order_id, idempotency_key=idempotency_key, response_context=self._command_context())

    @staticmethod
    def _positions(snapshot):
        positions = snapshot.get("positions", [])
        if isinstance(positions, dict):
            positions = [dict(value, symbol=symbol) if isinstance(value, dict) else {"symbol": symbol, "quantity": value} for symbol, value in positions.items()]
        return {row["symbol"]: row for row in positions if isinstance(row, dict) and row.get("symbol") in SYMBOLS}

    @staticmethod
    def _quantity(row):
        return int(_num(row.get("quantity", row.get("qty", row.get("shares", 0)))))

    @staticmethod
    def _cash(snapshot):
        account = snapshot.get("account") or {}
        cash = snapshot.get("cash", account.get("cash", 0))
        return _decimal(cash.get("total", cash.get("balance", 0)) if isinstance(cash, dict) else cash)

    @staticmethod
    def _available(snapshot):
        account = snapshot.get("account") or {}
        cash = snapshot.get("cash", account.get("cash", 0))
        if isinstance(cash, dict):
            return _decimal(cash.get("available", cash.get("available_cash", 0)))
        return _decimal(snapshot.get("available_cash", account.get("available_cash", cash)))

    @staticmethod
    def _running(snapshot):
        return bool(snapshot.get("running", (snapshot.get("account") or {}).get("running", False)))

    def _targets(self, snapshot, signal, batch):
        positions = self._positions(snapshot)
        equity = self._cash(snapshot) + sum(self._quantity(row) * _decimal(batch["quotes"].get(symbol, {}).get("price")) for symbol, row in positions.items())
        return {symbol: target_quantity(equity, _decimal(signal.get("weights", {}).get(symbol)),
                                        _decimal(batch["quotes"][symbol]["price"], "1")) for symbol in SYMBOLS}

    @staticmethod
    def _limit(symbol, side, quote):
        return limit_price(symbol, side, Decimal(str(quote["price"])), Decimal(str(quote["previous_close"])))

    @staticmethod
    def _fee(snapshot, notional):
        fees = snapshot.get("fees", (snapshot.get("account") or {}).get("fees", {})) or {}
        rate = _decimal(fees.get("commission_rate", fees.get("rate", "0.0003")))
        minimum = _decimal(fees.get("min_fee", fees.get("minimum", fees.get("minimum_commission", fees.get("min_commission", "5")))))
        return commission(notional, rate, minimum)

    def _continuous(self, current):
        cal = getattr(self.ledger, "calendar", None)
        if cal is not None and hasattr(cal, "is_continuous"):
            return bool(cal.is_continuous(current))
        if cal is not None and hasattr(cal, "phase"):
            return cal.phase(current) in {"continuous", "continuous_am", "continuous_pm"}
        # There is no weekday-only fallback: missing verified calendar blocks.
        return False

    def _ready(self, snapshot, signal, batch):
        current = _now(self.now)
        if not (self._running(snapshot) and signal and signal.get('strategy') == self.strategy and batch and self._source_state["source_status"] == "ready" and _now(signal["eligible_at"]) <= current and self._continuous(current)):
            return False
        try:
            times = [batch["received_at"]] + [batch["quotes"][symbol]["quote_at"] for symbol in SYMBOLS]
            return 0 <= (current - _now(batch["received_at"])).total_seconds() <= 5 and all(0 <= (current - _now(stamp)).total_seconds() <= 60 for stamp in times)
        except (ValueError, TypeError, KeyError):
            return False

    def _ensure_plan(self, snapshot, signal, batch):
        session_day = _now(self.now).date().isoformat()
        generation = snapshot.get("activation_generation", (snapshot.get("account") or {}).get("activation_generation", 0))
        plan_id = _hash({"signal": signal["id"], "day": session_day, "generation": generation})
        plan = snapshot.get("plan") or {}
        if plan.get("id") == plan_id:
            return plan
        plan = {"id": plan_id, "signal_id": signal["id"], "session_day": session_day, "generation": generation, "targets": self._targets(snapshot, signal, batch), "created_at": _now(self.now).isoformat(), "reference_prices": {symbol: str(_decimal(batch["quotes"][symbol]["price"])) for symbol in SYMBOLS}}
        self._write(self.ledger.set_plan, plan)
        return plan

    def _plan(self, snapshot, signal, batch):
        if not self._ready(snapshot, signal, batch):
            return
        plan = self._ensure_plan(snapshot, signal, batch)
        targets = plan["targets"]
        session_day = _now(self.now).date().isoformat()
        for side in ("sell", "buy"):
            if side == "buy" and any(order.get("side") == "sell" and order.get("status") in ACTIVE for order in self.ledger.snapshot().get("orders", [])):
                break
            for symbol in SYMBOLS:
                snapshot = self.ledger.snapshot()
                orders = snapshot.get("orders", [])
                if any(o.get("symbol") == symbol and o.get("status") in ACTIVE for o in orders):
                    continue
                generation = snapshot.get("activation_generation", (snapshot.get("account") or {}).get("activation_generation", 0))
                identity = {"signal": signal["id"], "day": session_day, "generation": generation, "symbol": symbol, "side": side}
                by_client = {order.get("client_order_id"): order for order in orders}
                child = 0
                while True:
                    client_id = _hash(dict(identity, child=child))
                    previous_child = by_client.get(client_id)
                    # Compatibility with the candidate's original one-order ID.
                    if child == 0 and previous_child is None:
                        previous_child = by_client.get(_hash(identity))
                    if previous_child is None or previous_child.get("status") != "filled":
                        break
                    child += 1
                if previous_child is not None:
                    # A cancelled/rejected/expired child is an explicit terminal
                    # intent. Only a completed fill advances to the next child.
                    continue
                position = self._positions(snapshot).get(symbol, {})
                current_qty = self._quantity(position)
                gap = targets[symbol] - current_qty
                quantity = min(MAX_ORDER_QTY, max(0, gap if side == "buy" else -gap) // LOT * LOT)
                if side == "sell":
                    available = int(_num(position.get("available_qty", position.get("available_quantity", position.get("sellable", position.get("sellable_quantity", current_qty))))))
                    quantity = min(quantity, available // LOT * LOT)
                limit = self._limit(symbol, side, batch["quotes"][symbol])
                if side == "buy":
                    available = self._available(snapshot)
                    quantity = min(quantity, int(available / limit / LOT) * LOT)
                    while quantity > 0 and quantity * limit + self._fee(snapshot, quantity * limit) > available:
                        quantity -= LOT
                if quantity <= 0:
                    continue
                self._write(self.ledger.submit, symbol=symbol, side=side, qty=quantity, limit_price=str(limit), signal_id=signal["id"], client_order_id=client_id)
                self._plans += 1

    def submit_order(self, body):
        self._ensure_open()
        if not isinstance(body, dict):
            raise ValueError("order must be an object")
        with self._mutation():
            snapshot = self.ledger.snapshot()
            signal = snapshot.get("signal")
            batch = self._last_batch
            if not self._ready(snapshot, signal, batch):
                raise ValueError("current signal and fresh trading quotes are required")
            symbol, side = body.get("symbol"), body.get("side")
            if symbol not in SYMBOLS or side not in {"buy", "sell"} or body.get("signal_id") != signal["id"]:
                raise ValueError("order must follow current D0 signal")
            if any(o.get("symbol") == symbol and o.get("status") in ACTIVE for o in snapshot.get("orders", [])):
                raise ValueError("symbol already has an active order")
            targets = self._ensure_plan(snapshot, signal, batch)["targets"]
            current = self._quantity(self._positions(snapshot).get(symbol, {}))
            gap = targets[symbol] - current
            qty = body.get("qty", body.get("quantity"))
            if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0 or qty % 100 or qty > (gap if side == "buy" else -gap):
                raise ValueError("order quantity exceeds current target gap")
            self._write(self.ledger.submit, symbol=symbol, side=side, qty=qty, limit_price=body.get("limit_price"), expires_at=body.get("expires_at"), signal_id=signal["id"], client_order_id=body.get("client_order_id"))
            return self.snapshot()

    def poll_once(self):
        with self._mutation():
            self._write(self.ledger.tick)
            snapshot = self.ledger.snapshot()
            if any(self._quantity(row) > 0 for row in self._positions(snapshot).values()) and not (snapshot.get("signal") or {}).get("history_cutoff"):
                self._write(self.ledger.invalidate_activity, "holdings_history_unverified")
                self._source_state.update(source_status="blocked", reason="holdings_history_unverified", last_observed=_now(self.now).isoformat())
                self._last_batch = None
                return self.snapshot()
            try:
                source = self.source.read(previous_signal=snapshot.get("signal"))
            except Exception:
                self._write(self.ledger.invalidate_activity, "source_read_failed")
                self._source_state.update(source_status="blocked", reason="source_read_failed", last_observed=_now(self.now).isoformat())
                self._last_batch = None
                return self.snapshot()
            self._source_state = {"source_status": source.get("source_status", "blocked"), "reason": source.get("reason", "source_unavailable"), "last_observed": source.get("observed_at", _now(self.now).isoformat())}
            self._source_state.update({key: source.get(key) for key in ("daily_origin", "daily_asof", "historical_seed", "history_continuity")})
            self._source_state["market_observation"] = copy.deepcopy(source.get("observed_batch"))
            invalidation = source.get("activity_invalidation")
            if invalidation:
                if isinstance(invalidation, dict):
                    self._write(self.ledger.invalidate_activity, invalidation["reason"], symbols=invalidation.get("symbols"))
                else:
                    self._write(self.ledger.invalidate_activity, str(invalidation))
                if not isinstance(invalidation, dict) or invalidation.get("symbols") is None:
                    acknowledge = getattr(self.source, "acknowledge_activity_invalidation", None)
                    if acknowledge is not None:
                        acknowledge()
            observed_batch = source.get("observed_batch")
            if observed_batch is not None:
                try:
                    if not isinstance(observed_batch, dict) or not isinstance(observed_batch.get("quotes"), (dict, list)):
                        raise ValueError("invalid status batch shape")
                    self._write(self.ledger.observe_status, observed_batch)
                except (ValueError, TypeError):
                    # The direct poll path must also fail closed. Storage and
                    # other unexpected failures still propagate to the worker.
                    self._write(self.ledger.invalidate_activity, "invalid_status_batch")
                    self._source_state.update(source_status="blocked", reason="invalid_status_batch")
                    self._last_batch = None
                    return self.snapshot()
            self._source_state["observation_state"] = source.get("observation_state")
            signal, batch = source.get("signal"), source.get("batch")
            if signal and signal.get('strategy') != self.strategy:
                self._write(self.ledger.invalidate_activity, "signal_strategy_mismatch")
                self._source_state.update(source_status="blocked", reason="signal_strategy_mismatch")
                self._last_batch = None
                return self.snapshot()
            self._last_batch = batch if source.get("source_status") == "ready" else None
            if signal:
                previous = snapshot.get("signal")
                if previous and previous.get("id") != signal.get("id"):
                    for order in snapshot.get("orders", []):
                        if order.get("status") in ACTIVE:
                            self._write(self.ledger.cancel, order["id"])
                if not previous or previous.get("id") != signal.get("id"):
                    self._write(self.ledger.set_signal, signal)
            if self._last_batch:
                # Existing orders see this batch first. New orders created below
                # must wait for subsequent observations, never this cached quote.
                self._write(self.ledger.ingest_batch, batch)
                self._plan(self.ledger.snapshot(), signal, batch)
            return self.snapshot()

    def order_preview_input(self):
        """Read-only D0 inputs; do not export paper balances or the ledger history."""
        if self.strategy != "D0":
            raise ValueError("order previews support D0 only")
        with self._lock:
            raw = self.ledger.snapshot()
            state = self._source_state
            signal = raw.get("signal")
            batch = self._last_batch if state.get("source_status") == "ready" else None
            observation = None
            if batch is not None:
                quotes = {}
                for symbol in SYMBOLS:
                    row = batch["quotes"].get(symbol)
                    if not isinstance(row, dict):
                        continue
                    quote = {key: row.get(key) for key in ("symbol", "price", "previous_close", "quote_at", "started", "status")}
                    status = (raw.get("quotes") or {}).get(symbol, {}).get("status")
                    if status in {"halted", "unknown"}:
                        quote["status"] = status
                    quotes[symbol] = quote
                observation = {"received_at": batch.get("received_at"), "quotes": quotes}
            fields = ("id", "strategy", "valid", "confirmed_day", "execution_day", "eligible_at", "data_cutoff", "known_at", "weights")
            return {"contract_version": "d0-order-preview-input-v1", "strategy": self.strategy,
                    "source_status": state.get("source_status"), "historical_seed": state.get("historical_seed"),
                    "signal": {key: copy.deepcopy(signal.get(key)) for key in fields} if isinstance(signal, dict) else None,
                    "market_observation": observation}

    def export_live_signal(self):
        from live_signal import project_live_signal

        with self._lock:
            return project_live_signal(
                signal=self.ledger.confirmed_target(), strategy=self.strategy,
                calendar=self.ledger.calendar, now=_now(self.now),
                observed_at=self._source_state.get("last_observed"),
                source_status=self._source_state.get("source_status"),
            )

    def snapshot(self):
        with self._lock:
            result = copy.deepcopy(self.ledger.snapshot())
            result.update(copy.deepcopy(self._source_state))
            try:
                project = getattr(self.source, "indicator_history", None)
                histories = project(result.get("signal")) if callable(project) else None
                if not isinstance(histories, dict):
                    histories = {symbol: unavailable_chart_history(result.get("signal")) for symbol in SYMBOLS}
            except Exception:
                # Charts are optional display data. A malformed or unavailable
                # cache cannot interrupt account/quote/order presentation.
                histories = {symbol: unavailable_chart_history(result.get("signal"), "invalid_history", "invalid") for symbol in SYMBOLS}
            result["indicator_histories"] = histories
            try:
                project = getattr(self.source, "daily_price_history", None)
                prices = project(result.get("signal")) if callable(project) else None
                if not isinstance(prices, dict):
                    prices = {symbol: unavailable_price_history(result.get("signal")) for symbol in SYMBOLS}
            except Exception:
                prices = {symbol: unavailable_price_history(result.get("signal"), "invalid_history", "invalid") for symbol in SYMBOLS}
            result["daily_price_histories"] = prices
            model = copy.deepcopy(result.get("model") or {})
            defaults = {"version": "observed_new_trade_full_order_estimate", "mode": "quote_driven_estimate", "fill_kind": "whole_order_estimate", "label": "报价驱动整单模拟估计", "freshness": {"source_delay_max_seconds": 60, "match_age_max_seconds": 60, "queue_delay_max_seconds": 5, "boundary": "inclusive"}, "activity_quotes_required": 2, "windows": ["09:30-11:30", "13:00-14:57"], "timezone": "Asia/Shanghai", "expiry_time": "14:57"}
            for key, value in defaults.items():
                model.setdefault(key, value)
            model["limitations"] = list(dict.fromkeys(list(model.get("limitations") or []) + MODEL["limits"]))
            model.setdefault("description", MODEL["description"])
            if getattr(self, 'strategy', 'D0') != 'D0':
                model['description'] = 'D0I-BOND-WW 保留收盘确认和已完成周国债资格；仅观察启动后委托，不补造已错过的历史成交。'
            model.setdefault("limit_tolerance_bps", MODEL["limit_tolerance_bps"])
            result.update(model=model, plan_count=self._plans)
            return result
