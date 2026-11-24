"""Read-only, standard-library market environment adapter.

All calculations use confirmed daily observations.  This module neither fetches
prices nor reads, writes, or imports a trading account.  The causal continuity
adjustment is the frozen research TRIX convention, not a total-return account.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics


SCHEMA = "sector-market-environment.v1"
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
CLOSE_COMPLETION_TIME = time(16, 10)
DISPLAY_START = "2022-04-01"
INDEX_KEY = "CSI_ALL_PRICE"
TRIX_PERIOD = 12
TRIX_SIGNAL_PERIOD = 9
TRIX_WARMUP_BARS = 45
VOLATILITY_WINDOW = 20
VOLATILITY_REFERENCE_MAX = 252
VOLATILITY_REFERENCE_MIN = 60
VOLATILITY_LOW = 0.20
VOLATILITY_HIGH = 0.80
SECTORS = (
    ("sh512800", "银行"), ("sh512880", "证券"),
    ("sz159928", "主要消费"), ("sz159929", "医药卫生"),
    ("sh512480", "半导体"), ("sh512720", "计算机"),
    ("sh512660", "军工"), ("sh515220", "煤炭"),
    ("sh512400", "有色金属"), ("sz159611", "电力公用事业"),
)


def _iso(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须为 YYYY-MM-DD 日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 不是有效日期: {value}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} 必须为 YYYY-MM-DD 日期: {value}")
    return value


def _number(value, field, positive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须为有限数字")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} 必须为有限数字") from exc
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        suffix = "正数" if positive else "非负数"
        raise ValueError(f"{field} 必须为有限{suffix}")
    return value


def _ordered_dates(values, field):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{field} 必须为非空日期列表")
    last = None
    for value in values:
        _iso(value, field)
        if last is not None and value <= last:
            raise ValueError(f"{field} 日期重复或未严格升序: {value}")
        last = value
    return values


def _no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"JSON 出现重复键: {key}")
        obj[key] = value
    return obj


def _read_json(path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"),
                           object_pairs_hook=_no_duplicate_keys,
                           parse_constant=lambda x: (_ for _ in ()).throw(
                               ValueError(f"JSON 非有限数字: {x}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取数据包 {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须为 JSON 对象")
    return value, hashlib.sha256(raw).hexdigest()


def _clock(now=None):
    if now is None:
        return datetime.now(SHANGHAI)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now 必须为带时区的 datetime")
    return now.astimezone(SHANGHAI)


class Environment:
    """Validate a complete data directory and expose immutable JSON-ready views.

    Source data may extend beyond an injected historical ``now``; such rows are
    excluded by the selection cutoff.  Actual future-dated market observations
    relative to the system clock are rejected when the directory is loaded.
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self._hashes = {}
        documents = {}
        for name in ("market.json", "index_data.json", "verified_actions.json",
                     "calendar_2026.json"):
            documents[name], self._hashes[name] = _read_json(self.data_dir / name)
        self._market = documents["market.json"]
        self._index = documents["index_data.json"]
        self._actions = documents["verified_actions.json"]
        self._calendar_document = documents["calendar_2026.json"]
        try:
            self._validate_calendar()
            self._validate_market()
            self._validate_actions()
            self._validate_index()
            self._compute_index()
            self._compute_sectors()
        except (KeyError, TypeError, IndexError, OverflowError) as exc:
            raise ValueError(f"数据包结构或数值无效: {exc}") from exc
        self._selectable = [d for d in self._index_dates if d >= DISPLAY_START]
        if not self._selectable:
            raise ValueError(f"指数没有 {DISPLAY_START} 之后的可选历史日期")
        self._selectable_set = set(self._selectable)
        self._common = [d for d in self._selectable
                        if all(d in self._sector_bars[c] for c, _ in SECTORS)]
        if not self._common:
            raise ValueError("指数与十只 ETF 没有共同可用日期")
        self._sources = self._source_details()

    def _validate_calendar(self):
        cal = self._calendar_document
        if cal.get("year") != 2026 or cal.get("verified_through") != "2026-12-31":
            raise ValueError("v1 只支持已核验到 2026-12-31 的官方 2026 年日历")
        if cal.get("timezone") != "Asia/Shanghai":
            raise ValueError("日历时区必须为 Asia/Shanghai")
        if cal.get("close_completion_time") != "16:10:00":
            raise ValueError("收盘完成缓冲须固定为 16:10:00")
        official = _ordered_dates(cal["sessions_2026"], "2026 官方交易日历")
        holidays = set()
        for interval in cal["holiday_ranges"]:
            start = date.fromisoformat(_iso(interval["start"], "假期开始"))
            end = date.fromisoformat(_iso(interval["end"], "假期结束"))
            if start.year != 2026 or end.year != 2026 or start > end:
                raise ValueError("2026 休市区间无效")
            while start <= end:
                holidays.add(start.isoformat())
                start += timedelta(days=1)
        expected = []
        day = date(2026, 1, 1)
        while day.year == 2026:
            if day.weekday() < 5 and day.isoformat() not in holidays:
                expected.append(day.isoformat())
            day += timedelta(days=1)
        if official != expected or len(official) != 242:
            raise ValueError("2026 交易日与官方假期/周末规则不一致")
        if not cal.get("sources"):
            raise ValueError("官方日历缺少来源信息")
        observed = _ordered_dates(self._market["calendar"], "冻结交易日历")
        official_set = set(official)
        for d in observed:
            if date.fromisoformat(d).weekday() >= 5:
                raise ValueError(f"冻结日历包含周末: {d}")
            if d >= "2027-01-01" or (d >= "2026-01-01" and d not in official_set):
                raise ValueError(f"冻结日历超出核验范围或包含官方休市日: {d}")
        self._calendar = [d for d in observed if d < "2026-01-01"] + official
        self._calendar_set = set(self._calendar)
        self._calendar_pos = {d: i for i, d in enumerate(self._calendar)}
        self._calendar_verified_until = cal["verified_through"]

    def _validate_bars(self, rows, field, allow_null_ohl=False):
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{field} 行情必须为非空列表")
        dates = _ordered_dates([row["date"] for row in rows], field)
        actual_today = _clock().date().isoformat()
        for row in rows:
            d = row["date"]
            if d not in self._calendar_set:
                raise ValueError(f"{field} 含未核验的非交易日: {d}")
            if d > actual_today:
                raise ValueError(f"{field} 含未来行情: {d}")
            values = {"close": _number(row["close"], f"{field} {d} close")}
            for key in ("open", "high", "low"):
                value = row.get(key)
                if value is None and allow_null_ohl:
                    continue
                values[key] = _number(value, f"{field} {d} {key}")
            if "high" in values and "low" in values:
                if values["high"] < values["low"]:
                    raise ValueError(f"{field} {d} high 小于 low")
                if not values["low"] <= values["close"] <= values["high"]:
                    raise ValueError(f"{field} {d} close 不在 high/low 范围内")
                if "open" in values and not values["low"] <= values["open"] <= values["high"]:
                    raise ValueError(f"{field} {d} open 不在 high/low 范围内")
            for key in ("volume_lots", "amount_cny"):
                if key in row:
                    _number(row[key], f"{field} {d} {key}", positive=False)
        return dates, {row["date"]: row for row in rows}

    def _validate_market(self):
        if self._market.get("schema") != "ten-sector-portfolio.market.v1":
            raise ValueError("不支持的 ETF 数据 schema")
        assets = self._market["assets"]
        if not isinstance(assets, dict) or set(assets) != {c for c, _ in SECTORS}:
            raise ValueError("数据包必须恰好包含约定的十只 ETF")
        self._sector_dates = {}
        self._sector_bars = {}
        for code, _ in SECTORS:
            asset = assets[code]
            if asset["identity"].get("code") != code[2:]:
                raise ValueError(f"{code} 标的身份不一致")
            dates, bars = self._validate_bars(asset["bars"], code)
            self._sector_dates[code] = dates
            self._sector_bars[code] = bars

    def _validate_actions(self):
        receipt = self._actions
        if self._market.get("corporate_action_receipt_sha256") != self._hashes["verified_actions.json"]:
            raise ValueError("公司行动核验文件 SHA256 与 market.json 不一致")
        self._action_through = _iso(receipt["requested_window"]["through"], "公司行动核验截止日")
        _iso(receipt["as_of"], "公司行动核验日期")
        checked_assets = receipt["assets"]
        if not isinstance(checked_assets, list) or len(checked_assets) != 10:
            raise ValueError("公司行动核验应覆盖固定十 ETF")
        checked = {a["code"]: a for a in checked_assets}
        if len(checked) != 10 or set(checked) != {c[2:] for c, _ in SECTORS}:
            raise ValueError("公司行动核验标的重复或不一致")
        events = receipt["events"]
        event_map = {e["event_id"]: e for e in events}
        if len(event_map) != len(events):
            raise ValueError("公司行动事件编号重复")
        seen = set()
        self._adjustment_events = {}
        self._coverage_partial = []
        for code, _ in SECTORS:
            asset, official = self._market["assets"][code], checked[code[2:]]
            if asset["action_coverage"] != official["coverage"]:
                raise ValueError(f"{code} 公司行动覆盖边界与核验记录不一致")
            if not official["coverage"].get("official_full_life_event_archive_exhaustively_reviewed", False):
                self._coverage_partial.append(code)
            adjusted = []
            for key, kind in (("splits", "split"), ("dividends", "cash_dividend")):
                if asset[key] != official[key]:
                    raise ValueError(f"{code} {key} 与公司行动核验记录不一致")
                for event in asset[key]:
                    event_id = event["event_id"]
                    if event_id in seen or event_map.get(event_id) != event:
                        raise ValueError(f"公司行动事件重复或与核验列表不一致: {event_id}")
                    seen.add(event_id)
                    if event["code"] != code[2:] or event["event_type"] != kind:
                        raise ValueError(f"公司行动类型或代码错误: {event_id}")
                    ann = _iso(event["announcement_date"], "公告日")
                    record = _iso(event["record_date"], "权益登记日")
                    ex = _iso(event["ex_date"], "除权除息日")
                    if ann > ex or record > ex or ex not in self._calendar_set:
                        raise ValueError(f"公司行动日期无效: {event_id}")
                    if ex > self._action_through:
                        raise ValueError(f"公司行动超出核验范围: {event_id}")
                    if kind == "split":
                        _number(event["ratio"], "拆分比例")
                    else:
                        _number(event["cash_per_share"], "每份分红")
                        if _iso(event["pay_date"], "派息日") < ex:
                            raise ValueError(f"派息日在除息日前: {event_id}")
                    if not event.get("verification_tier") or not event.get("source_url") or not event.get("receipt_sha256"):
                        raise ValueError(f"公司行动缺少核验证据字段: {event_id}")
                    adjusted.append(event)
            # Same-day dividends precede splits, matching frozen legacy kind sort.
            self._adjustment_events[code] = sorted(adjusted, key=lambda e: (e["ex_date"], e["event_type"]))
        if seen != set(event_map):
            raise ValueError("公司行动核验事件未完整映射到十只 ETF")

    def _validate_index(self):
        if self._index.get("schema") != "ten-sector-market-filter.index-data.v1":
            raise ValueError("不支持的指数数据 schema")
        series = self._index["series"]
        if INDEX_KEY not in series:
            raise ValueError("缺少中证全指价格指数 CSI_ALL_PRICE")
        for name, rows in series.items():
            dates, bars = self._validate_bars(rows, name, allow_null_ohl=name != INDEX_KEY)
            if name == INDEX_KEY:
                self._index_dates, self._index_bars = dates, bars
        frozen = self._index.get("frozen_utc")
        if not isinstance(frozen, str):
            raise ValueError("指数缺少来源冻结时间")
        try:
            dt = datetime.fromisoformat(frozen.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("来源冻结时间缺少时区")
        except ValueError as exc:
            raise ValueError("来源冻结时间无效") from exc
        self._source_frozen_at = frozen
        if not self._index.get("sources"):
            raise ValueError("指数缺少来源信息")

    def _window(self, d, count):
        end = self._calendar_pos[d] + 1
        if end < count:
            return None
        values = [self._index_bars.get(day) for day in self._calendar[end-count:end]]
        if any(row is None for row in values):
            return None
        return [float(row["close"]) for row in values]

    def _compute_index(self):
        self._index_features = {}
        previous_volatilities = deque(maxlen=VOLATILITY_REFERENCE_MAX)
        for d in self._index_dates:
            close = float(self._index_bars[d]["close"])
            result = {"date": d, "close": close}
            for n in (20, 60, 120):
                values = self._window(d, n)
                result[f"ma{n}"] = None if values is None else math.fsum(values) / n
            values = self._window(d, 60)
            result["drawdown60"] = None if values is None else 1.0 - close / max(values)
            values = self._window(d, VOLATILITY_WINDOW + 1)
            vol = None
            if values is not None:
                returns = [values[j] / values[j-1] - 1.0 for j in range(1, len(values))]
                vol = statistics.stdev(returns) * math.sqrt(252)
            result["volatility20"] = vol
            result["percentile_samples"] = len(previous_volatilities)
            percentile = None
            if vol is not None and len(previous_volatilities) >= VOLATILITY_REFERENCE_MIN:
                less = sum(x < vol for x in previous_volatilities)
                equal = sum(x == vol for x in previous_volatilities)
                percentile = (less + 0.5 * equal) / len(previous_volatilities)
            result["percentile"] = percentile
            if percentile is None:
                result["volatility_label"] = "资料不足"
            elif percentile <= VOLATILITY_LOW:
                result["volatility_label"] = "相对偏低"
            elif percentile >= VOLATILITY_HIGH:
                result["volatility_label"] = "相对偏高"
            else:
                result["volatility_label"] = "历史中间区间"
            previous_date = self._prior_market_date(d, 5)
            previous = self._index_features.get(previous_date, {})
            change = None
            if result["ma20"] is not None and previous.get("ma20") is not None:
                change = result["ma20"] - previous["ma20"]
            result["ma20_change_5"] = change
            if any(result[k] is None for k in ("ma20", "ma60", "ma120", "ma20_change_5")):
                result["label"] = "资料不足"
            elif close > result["ma20"] > result["ma60"] > result["ma120"] and change > 0:
                result["label"] = "上行排列"
            elif close < result["ma20"] < result["ma60"] < result["ma120"] and change < 0:
                result["label"] = "下行排列"
            else:
                result["label"] = "未形成一致排列"
            self._index_features[d] = result
            if vol is not None:
                previous_volatilities.append(vol)

    def _known_suspension(self, code, d):
        # The only omitted ETF session in the seed is explicitly explained by
        # the verified 2021 semiconductor split receipt; no price is invented.
        return (code == "sh512480" and d == "2021-03-26" and any(
            e["event_type"] == "split" and e["ex_date"] == "2021-03-29"
            and e["record_date"] == "2021-03-25" and e["ratio"] == 2
            for e in self._adjustment_events[code]))

    def _compute_sectors(self):
        self._sector_features = {}
        alpha = 2.0 / (TRIX_PERIOD + 1)
        for code, _ in SECTORS:
            features = {}
            factor = 1.0
            prev_day = prev_raw_close = prev_e3 = None
            e1 = e2 = e3 = None
            previous_trix = previous_signal = None
            previous_ready = False
            state = False
            trix_values = deque(maxlen=TRIX_SIGNAL_PERIOD)
            missing_since = None
            actions = self._adjustment_events[code]
            for count, d in enumerate(self._sector_dates[code], 1):
                row = self._sector_bars[code][d]
                raw_close = float(row["close"])
                if prev_day is not None:
                    between = self._calendar[self._calendar_pos[prev_day]+1:self._calendar_pos[d]]
                    unexplained = [x for x in between if not self._known_suspension(code, x)]
                    if missing_since is None and unexplained:
                        missing_since = unexplained[0]
                    reference = prev_raw_close
                    for event in actions:
                        if not prev_day < event["ex_date"] <= d:
                            continue
                        if event["event_type"] == "split":
                            factor *= event["ratio"]
                            reference /= event["ratio"]
                        else:
                            cash = event["cash_per_share"]
                            if reference <= cash:
                                raise ValueError(f"{code} {d} 分红不小于前收盘参考价")
                            factor *= reference / (reference - cash)
                            reference -= cash
                adjusted = raw_close * factor
                if not math.isfinite(adjusted) or adjusted <= 0:
                    raise ValueError(f"{code} {d} 因果调整价格无效")
                if e1 is None:
                    e1 = e2 = e3 = adjusted
                else:
                    # pandas ewm preserves equal values exactly, avoiding tiny
                    # roundoff trends in a constant series (e.g. price 0.051).
                    if e1 != adjusted:
                        e1 = (1.0 - alpha) * e1 + alpha * adjusted
                    if e2 != e1:
                        e2 = (1.0 - alpha) * e2 + alpha * e1
                    if e3 != e2:
                        e3 = (1.0 - alpha) * e3 + alpha * e2
                trix = None if prev_e3 is None else 100.0 * (e3 / prev_e3 - 1.0)
                if trix is not None:
                    trix_values.append(trix)
                signal = math.fsum(trix_values) / TRIX_SIGNAL_PERIOD if len(trix_values) == TRIX_SIGNAL_PERIOD else None
                ready = count >= TRIX_WARMUP_BARS and trix is not None and signal is not None
                if ready and previous_ready:
                    if trix > signal and previous_trix <= previous_signal:
                        state = True
                    if trix < signal and previous_trix >= previous_signal:
                        state = False
                reason = "满足原 TRIX 入选状态" if state else "未处于原 TRIX 入选状态"
                eligible = state if ready else None
                if not ready:
                    reason = f"TRIX 准备数据不足（{count}/{TRIX_WARMUP_BARS} 根）"
                if missing_since is not None:
                    trix_out = signal_out = None
                    ready_out = False
                    eligible = None
                    reason = f"存在未解释的历史行情缺口（{missing_since}），TRIX 不可确认"
                else:
                    trix_out, signal_out, ready_out = trix, signal, ready
                if d > self._action_through:
                    eligible = None
                    reason = f"超过公司行动核验截止 {self._action_through}，等待核验新数据包"
                features[d] = {
                    "close": raw_close, "trix": trix_out, "signal": signal_out,
                    "ready": ready_out, "eligible": eligible, "reason": reason,
                }
                prev_day, prev_raw_close, prev_e3 = d, raw_close, e3
                previous_trix, previous_signal, previous_ready = trix, signal, ready
            self._sector_features[code] = features

    def _prior_market_date(self, d, count):
        position = self._calendar_pos[d] - count
        return self._calendar[position] if position >= 0 else None

    def _expected(self, now):
        today = now.date().isoformat()
        if today > self._calendar_verified_until:
            return None
        end = bisect_right(self._calendar, today)
        if today in self._calendar_set and now.timetz().replace(tzinfo=None) < CLOSE_COMPLETION_TIME:
            end -= 1
        return self._calendar[end-1] if end > 0 else None

    def _cutoff(self, now):
        expected = self._expected(now)
        # Past the verified calendar, show the last verified historical state
        # with calendar_unknown.  Do not invent the present expected session.
        if expected is None and now.date().isoformat() > self._calendar_verified_until:
            return self._calendar_verified_until
        return expected

    def _select(self, as_of, now):
        cutoff = self._cutoff(now)
        if cutoff is None:
            raise ValueError("当前时钟之前没有已核验且应完成的交易日")
        if as_of is not None:
            _iso(as_of, "as_of")
            if as_of not in self._selectable_set:
                raise ValueError("as_of 不是可选的实际指数交易日期")
            if as_of > cutoff:
                raise ValueError("as_of 晚于当前时钟应完成的交易日")
            return as_of
        pos = bisect_right(self._common, cutoff)
        if pos == 0:
            raise ValueError("当前时钟之前没有指数与十 ETF 同日齐全的数据")
        return self._common[pos-1]

    @staticmethod
    def _latest(dates, cutoff):
        end = bisect_right(dates, cutoff)
        return dates[end-1] if end else None

    def _sector_rows(self, d):
        rows = []
        for code, name in SECTORS:
            data_date = self._latest(self._sector_dates[code], d)
            result = {"code": code, "name": name, "data_date": data_date}
            feature = self._sector_features[code].get(d)
            if feature is None:
                result.update(close=None, trix=None, signal=None, eligible=None,
                              ready=False, reason="该交易日缺少 ETF 行情，不以前值替代")
            else:
                result.update(feature)
            rows.append(result)
        return rows

    def _breadth_counts(self, d):
        if d is None:
            return 0, 0
        values = [self._sector_features[c].get(d, {}).get("eligible") for c, _ in SECTORS]
        return sum(value is True for value in values), sum(value is not None for value in values)

    def dates(self):
        """Selectable index dates, excluding incomplete/future sessions today."""
        cutoff = self._cutoff(_clock())
        return [] if cutoff is None else self._selectable[:bisect_right(self._selectable, cutoff)]

    def _freshness(self, d, historical, now):
        expected = self._expected(now)
        cutoff = d if historical else self._cutoff(now)
        index_date = self._latest(self._index_dates, cutoff)
        sector_dates = [self._latest(self._sector_dates[c], cutoff) for c, _ in SECTORS]
        oldest = min(sector_dates) if all(x is not None for x in sector_dates) else None
        notes = ["行情日期与计算时间不同；数据包冻结读取，无自动联网更新。",
                 "当日收盘数据在上海时间 16:10 后才计入应完成交易日。"]
        if expected is None:
            status, label = "calendar_unknown", "当前交易日历未核验"
            notes.append(f"交易日历仅核验至 {self._calendar_verified_until}；不能推测此后的应完成日期。")
        elif historical:
            status, label = "historical", "历史回看"
            notes.append(f"当前显示 {d} 历史状态；当前应完成日期为 {expected}，仅用作今天的时效参照。")
        elif index_date != expected or oldest != expected or d != expected:
            status, label = "stale", "数据未覆盖应完成交易日"
            notes.append(f"应完成 {expected}，本页共同数据截止 {d}；缺失没有插值或前填。")
        else:
            status, label = "current", "已覆盖应完成交易日"
        missing = [c for c, _ in SECTORS if d not in self._sector_bars[c]]
        if missing:
            notes.append("所选日期缺少 ETF 行情：" + "、".join(missing))
        if d > self._action_through:
            notes.append(f"公司行动仅核验至 {self._action_through}，其后 ETF 资格为未知。")
        return {"status": status, "label": label, "expected_date": expected,
                "index_date": index_date, "oldest_sector_date": oldest,
                "calendar_verified_until": self._calendar_verified_until,
                "source_frozen_at": self._source_frozen_at, "notes": notes}

    def snapshot(self, as_of=None, now=None):
        now = _clock(now)
        d = self._select(as_of, now)
        index = self._index_features[d]
        sectors = self._sector_rows(d)
        count, known = self._breadth_counts(d)
        previous_date = self._prior_market_date(d, 5)
        previous_count, previous_known = self._breadth_counts(previous_date)
        complete = known == len(SECTORS)
        previous_complete = previous_known == len(SECTORS)
        delta = count - previous_count if complete and previous_complete else None
        warnings = [
            "只读环境描述，不是上涨概率、收益预测、交易建议或仓位指令。",
            "板块广度仅覆盖固定十只 ETF，不代表全部 A 股行业。",
            "历史回看使用当前冻结的历史记录；历史发布版本和修订时点未逐时验证。",
        ]
        if self._coverage_partial:
            warnings.append("十只 ETF 的已发现分红/拆分有核验记录，但官方全生命周期无事件证明不完整；空记录不等于没有事件。")
        if any(e["verification_tier"] != "official_host_original_notice"
               for events in self._adjustment_events.values() for e in events
               if e["ex_date"] <= d):
            warnings.append("半导体 ETF 2026 年拆分使用基金公司原文第三方镜像，并有上交所日期佐证；原托管站正公告未取得。")
        if not complete:
            warnings.append("所选日部分 ETF 资格未知，板块广度比例和变化不计算。")
        if index["label"] == "资料不足":
            warnings.append("指数趋势所需连续窗口不完整，未以已有数据缩短窗口。")
        if index["volatility20"] is None or index["percentile"] is None:
            warnings.append("波动窗口或历史参考样本不足，不能给出波动高低标签。")
        return {
            "schema": SCHEMA, "snapshot_date": d,
            "mode": "historical" if as_of is not None else "latest",
            "calculated_at": now.isoformat(),
            "trend": {k: index[k] for k in ("label", "close", "ma20", "ma60", "ma120", "ma20_change_5")},
            "risk": {k: index[k] for k in ("volatility20", "percentile", "percentile_samples", "volatility_label", "drawdown60")},
            "breadth": {"eligible": count, "known": known, "total": len(SECTORS),
                        "ratio": count / len(SECTORS) if complete else None,
                        "previous_date": previous_date,
                        "previous_eligible": previous_count if previous_complete else None,
                        "delta_count": delta,
                        "delta_pp": delta * 100.0 / len(SECTORS) if delta is not None else None},
            "sectors": sectors,
            "freshness": self._freshness(d, as_of is not None, now),
            "sources": deepcopy(self._sources), "warnings": warnings,
        }

    def history(self, as_of=None, limit=252):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError("limit 必须为 1 到 5000 的整数")
        d = self._select(as_of, _clock())
        end = bisect_right(self._selectable, d)
        rows = []
        for day in self._selectable[max(0, end-limit):end]:
            feature = self._index_features[day]
            count, known = self._breadth_counts(day)
            rows.append({**{k: feature[k] for k in ("date", "close", "ma20", "ma60", "ma120", "volatility20")},
                         "breadth_ratio": count / len(SECTORS) if known == len(SECTORS) else None})
        return rows

    def _source_details(self):
        source = next((s for s in self._index["sources"] if s.get("key") == "csi_000985"), None)
        result = [{"name": "中证全指价格指数 000985", "kind": "official_index",
                   "url": source.get("url") if source else None,
                   "description": "中证指数官方日线价格指数；不是可直接交易的 ETF。",
                   "sha256": source.get("sha256") if source else None,
                   "data_file": "index_data.json", "data_sha256": self._hashes["index_data.json"]},
                  {"name": "固定十板块 ETF 原始日线", "kind": "frozen_etf_bars",
                   "description": "复用已冻结供应商原始 OHLC；TRIX 使用已核验事件进行因果连续化。",
                   "data_file": "market.json", "data_sha256": self._hashes["market.json"]},
                  {"name": "ETF 公司行动核验记录", "kind": "verified_actions",
                   "description": "正事件核验与部分期间无分红证据；不声称官方全生命周期完整。",
                   "verified_through": self._action_through,
                   "data_file": "verified_actions.json", "data_sha256": self._hashes["verified_actions.json"]}]
        for s in self._calendar_document["sources"]:
            result.append({"name": "2026 年交易所休市公告", "kind": "official_calendar",
                           "url": s["url"], "sha256": s.get("sha256"),
                           "data_file": "calendar_2026.json", "data_sha256": self._hashes["calendar_2026.json"]})
        return result
