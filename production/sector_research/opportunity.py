"""Read-only sector observations, with no scoring or allocation engine.

The ETF return convention is frozen research's ex-date reinvested economic
series.  Technical indicators use its separate causal continuity adjustment.
Neither series represents a funded, costed, executable trading account.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import deque
from copy import deepcopy
from decimal import Decimal, localcontext
import math
import statistics
from urllib.parse import parse_qs, urlsplit

if __package__:
    from .core import Environment, SECTORS, DISPLAY_START, _clock, _number
else:
    from core import Environment, SECTORS, DISPLAY_START, _clock, _number


SCHEMA = "sector-opportunities.v1"
BENCHMARK_KEY = "CSI_ALL_TR"
BENCHMARK_CODE = "H00985"
SKDJ_N = 9
SKDJ_M = 3
SKDJ_WARMUP_BARS = 18
STATUS_LABELS = {
    "both": "趋势资格且相对领先",
    "trend_only": "仅趋势资格",
    "relative_only": "仅相对领先",
    "neither": "两项均未成立",
    "unknown": "资料不足",
}


class Opportunity:
    """Compute fixed ten-sector descriptive observations from an Environment.

    Instantiation validates the additional total-return benchmark identity and
    the ex-date return constraints.  Missing benchmark rows degrade only the
    relative observations; malformed observations reject the data package.
    """

    def __init__(self, env: Environment):
        if not isinstance(env, Environment):
            raise TypeError("Opportunity 需要已校验的 Environment 实例")
        self.env = env
        self._benchmark_missing = False
        self._benchmark_source = None
        self._benchmark_dates = []
        self._benchmark_bars = {}
        self._economic = {}
        self._skdj = {}
        self._features = {}
        try:
            self._validate_benchmark()
            self._build_sector_series()
            self._build_features()
        except (KeyError, TypeError, IndexError, OverflowError) as exc:
            raise ValueError(f"板块机会数据包结构或数值无效: {exc}") from exc

    def _validate_benchmark(self):
        series = self.env._index["series"]
        if BENCHMARK_KEY not in series:
            self._benchmark_missing = True
            return
        # Environment already validates all present series.  Repeat explicitly
        # here because this module relies on H00985 and must not silently accept
        # a different series or malformed in-memory adapter value.
        rows = series[BENCHMARK_KEY]
        dates, bars = self.env._validate_bars(rows, BENCHMARK_KEY, allow_null_ohl=True)
        sources = [s for s in self.env._index["sources"] if s.get("key") == "csi_H00985"]
        if len(sources) != 1:
            raise ValueError("CSI_ALL_TR 缺少唯一的中证全指全收益 H00985 来源记录")
        source = sources[0]
        url = urlsplit(source.get("url", ""))
        query = parse_qs(url.query)
        if (url.scheme != "https" or url.hostname not in ("www.csindex.com.cn", "csindex.com.cn")
                or query.get("indexCode") != [BENCHMARK_CODE] or not source.get("sha256")):
            raise ValueError("CSI_ALL_TR 来源不能确认是官方 H00985 全收益指数")
        self._benchmark_source = source
        self._benchmark_dates, self._benchmark_bars = dates, bars

    def _build_sector_series(self):
        for code, _ in SECTORS:
            asset = self.env._market["assets"][code]
            bars = asset["bars"]
            economic = {}
            skdj = {}
            wealth = float(bars[0]["close"])
            factor = 1.0
            previous = None
            missing_since = None
            lows, highs = deque(maxlen=SKDJ_N), deque(maxlen=SKDJ_N)
            k_values = deque(maxlen=SKDJ_M)
            first_ema = second_ema = None
            previous_k = previous_d = None
            previous_ready = False
            carried_rsv = None
            state = False
            alpha = 2.0 / (SKDJ_M + 1)
            for count, bar in enumerate(bars, 1):
                d = bar["date"]
                raw_close = float(bar["close"])
                events = []
                daily_return = None
                if "amount_cny" in bar:
                    _number(bar["amount_cny"], f"{code} {d} amount_cny", positive=False)
                if previous is not None:
                    between = self.env._calendar[
                        self.env._calendar_pos[previous["date"]]+1:self.env._calendar_pos[d]]
                    unexplained = [day for day in between if not self.env._known_suspension(code, day)]
                    if unexplained and missing_since is None:
                        missing_since = unexplained[0]
                    with localcontext() as context:
                        context.prec = 28  # frozen features_model default precision
                        ratio, cash = Decimal(1), Decimal(0)
                        for action in asset["splits"]:
                            if previous["date"] < action["ex_date"] <= d:
                                ratio *= Decimal(str(action["ratio"]))
                                events.append(action["event_id"])
                        for action in asset["dividends"]:
                            if previous["date"] < action["ex_date"] <= d:
                                if action["record_date"] != previous["date"]:
                                    raise ValueError(
                                        f"{code} {action['event_id']} 登记日不等于前一实际行情日，"
                                        "不能按本经济总收益口径计算")
                                cash += Decimal(str(action["cash_per_share"]))
                                events.append(action["event_id"])
                        gross = (Decimal(str(bar["close"])) * ratio + cash) / Decimal(str(previous["close"]))
                        wealth *= float(gross)
                        daily_return = float(gross - 1)
                    reference = float(previous["close"])
                    for action in self.env._adjustment_events[code]:
                        if not previous["date"] < action["ex_date"] <= d:
                            continue
                        if action["event_type"] == "split":
                            factor *= action["ratio"]
                            reference /= action["ratio"]
                        else:
                            cash_per_share = action["cash_per_share"]
                            if reference <= cash_per_share:
                                raise ValueError(f"{code} {d} 分红不小于前收盘参考价")
                            factor *= reference / (reference - cash_per_share)
                            reference -= cash_per_share
                if (not math.isfinite(wealth) or wealth <= 0
                        or (daily_return is not None and not math.isfinite(daily_return))):
                    raise ValueError(f"{code} {d} 经济总收益计算无效")
                covered = d <= self.env._action_through
                economic[d] = {
                    "economic_tr": wealth if covered else None,
                    "economic_return": daily_return if covered else None,
                    "events": events,
                }
                low, high, close = (float(bar[k]) * factor for k in ("low", "high", "close"))
                if not all(math.isfinite(v) and v > 0 for v in (low, high, close)):
                    raise ValueError(f"{code} {d} 因果连续化 OHLC 无效")
                lows.append(low)
                highs.append(high)
                k = signal = None
                if len(lows) == SKDJ_N:
                    lo, hi = min(lows), max(highs)
                    if hi == lo:
                        rsv = 50.0 if carried_rsv is None else carried_rsv
                    else:
                        rsv = 100.0 * (close - lo) / (hi - lo)
                    carried_rsv = rsv
                    if first_ema is None:
                        first_ema = second_ema = rsv
                    else:
                        # Match pandas ewm's constant-value preservation.
                        if first_ema != rsv:
                            first_ema = (1.0 - alpha) * first_ema + alpha * rsv
                        if second_ema != first_ema:
                            second_ema = (1.0 - alpha) * second_ema + alpha * first_ema
                    k = second_ema
                    k_values.append(k)
                    if len(k_values) == SKDJ_M:
                        signal = math.fsum(k_values) / SKDJ_M
                ready = count >= SKDJ_WARMUP_BARS and k is not None and signal is not None
                if ready and previous_ready:
                    if k > signal and previous_k <= previous_d:
                        state = True
                    if k < signal and previous_k >= previous_d:
                        state = False
                eligible = state if ready else None
                reason = "处于原 SKDJ 入选状态" if state else "未处于原 SKDJ 入选状态"
                if not ready:
                    reason = f"SKDJ 准备数据不足（{count}/{SKDJ_WARMUP_BARS} 根）"
                output_ready, output_k, output_d = ready, k, signal
                if missing_since is not None:
                    eligible = None
                    output_ready = False
                    output_k = output_d = None
                    reason = f"存在未解释的历史行情缺口（{missing_since}），SKDJ 不可确认"
                if not covered:
                    eligible = None
                    output_ready = False
                    output_k = output_d = None
                    reason = f"超过公司行动核验截止 {self.env._action_through}"
                skdj[d] = {"k": output_k, "d": output_d, "ready": output_ready,
                           "eligible": eligible, "reason": reason}
                previous = bar
                previous_k, previous_d, previous_ready = k, signal, ready
            self._economic[code] = economic
            self._skdj[code] = skdj

    def _window_days(self, d, count):
        end = self.env._calendar_pos[d] + 1
        if end < count:
            return None
        return self.env._calendar[end-count:end]

    def _economic_window(self, code, d, count):
        days = self._window_days(d, count)
        if days is None:
            return None
        rows = [self._economic[code].get(day) for day in days]
        if any(row is None or row["economic_tr"] is None for row in rows):
            return None
        return rows

    def _benchmark_return60(self, d):
        days = self._window_days(d, 61)
        if days is None or any(day not in self._benchmark_bars for day in days):
            return None
        return float(self._benchmark_bars[days[-1]]["close"]) / float(self._benchmark_bars[days[0]]["close"]) - 1.0

    def _build_features(self):
        self._benchmark_returns = {day: self._benchmark_return60(day) for day in self.env._calendar}
        for code, _ in SECTORS:
            result = {}
            for d in self.env._sector_dates[code]:
                row = {"return20": None, "return60": None, "benchmark_return60": self._benchmark_returns[d],
                       "relative60": None, "relative_rank60": None, "volatility20": None,
                       "drawdown60": None, "amount20": None}
                for horizon in (20, 60):
                    window = self._economic_window(code, d, horizon + 1)
                    if window is not None:
                        row[f"return{horizon}"] = window[-1]["economic_tr"] / window[0]["economic_tr"] - 1.0
                if row["return60"] is not None and row["benchmark_return60"] is not None:
                    row["relative60"] = (1.0 + row["return60"]) / (1.0 + row["benchmark_return60"]) - 1.0
                window = self._economic_window(code, d, 21)
                if window is not None:
                    returns = [r["economic_return"] for r in window[1:]]
                    if all(r is not None for r in returns):
                        row["volatility20"] = statistics.stdev(returns) * math.sqrt(252)
                window = self._economic_window(code, d, 60)
                if window is not None:
                    row["drawdown60"] = 1.0 - window[-1]["economic_tr"] / max(r["economic_tr"] for r in window)
                days = self._window_days(d, 20)
                if days is not None:
                    amounts = [self.env._sector_bars[code].get(day, {}).get("amount_cny") for day in days]
                    if all(value is not None for value in amounts):
                        row["amount20"] = math.fsum(amounts) / 20
                if any(isinstance(value, float) and not math.isfinite(value) for value in row.values()):
                    raise ValueError(f"{code} {d} 衍生指标出现非有限数值")
                result[d] = row
            self._features[code] = result
        # A fixed ten-sector pool, never a changing available-data subset.
        for d in self.env._calendar:
            candidates = []
            for code, _ in SECTORS:
                row = self._features[code].get(d)
                trix = self.env._sector_features[code].get(d, {}).get("eligible")
                if row is None or row["relative60"] is None or trix is None:
                    break
                candidates.append((code, row["relative60"]))
            if len(candidates) == len(SECTORS):
                values = [value for _, value in candidates]
                for code, value in candidates:
                    stronger = sum(other > value for other in values)
                    ties = sum(other == value for other in values)
                    self._features[code][d]["relative_rank60"] = 1.0 + stronger + (ties - 1) / 2.0

    def _sector_row(self, sector, d):
        code = sector["code"]
        skdj = self._skdj[code].get(d, {"eligible": None, "ready": False, "k": None, "d": None,
                                      "reason": "该日缺少 ETF 行情，SKDJ 不可确认"})
        observed = self._features[code].get(d)
        if observed is None:
            observed = {"return20": None, "return60": None,
                        "benchmark_return60": self._benchmark_returns[d], "relative60": None,
                        "relative_rank60": None, "volatility20": None,
                        "drawdown60": None, "amount20": None}
        trix = sector["eligible"]
        relative = observed["relative60"]
        if trix is None or relative is None:
            status = "unknown"
        elif trix and relative > 0:
            status = "both"
        elif trix:
            status = "trend_only"
        elif relative > 0:
            status = "relative_only"
        else:
            status = "neither"
        reasons = [sector["reason"]]
        if relative is not None:
            reasons.append("近60日经济总收益跑赢中证全指全收益参照" if relative > 0
                           else "近60日经济总收益未跑赢中证全指全收益参照")
        else:
            if observed["return60"] is None:
                reasons.append("ETF 的61个连续市场日经济总收益窗口不足或超过公司行动核验范围")
            if observed["benchmark_return60"] is None:
                reasons.append("H00985 基准缺少61个连续市场日窗口，相对强弱不可确认")
        if observed["relative_rank60"] is None:
            reasons.append("完整十板块研究池有资料未知，未对部分板块单独排名")
        if skdj["eligible"] is None:
            reasons.append(skdj["reason"])
        if status == "both" and observed["return60"] is not None and observed["return60"] < 0:
            reasons.append("虽然相对领先，近60日绝对经济总收益仍为负")
        if observed["amount20"] is None:
            reasons.append("近20个连续市场日成交额资料不足")
        return {"code": code, "name": sector["name"], "close": sector["close"], "data_date": sector["data_date"],
                "trix_eligible": trix, "trix_ready": sector["ready"],
                "skdj_eligible": skdj["eligible"], "skdj_ready": skdj["ready"],
                "skdj_k": skdj["k"], "skdj_d": skdj["d"], **observed,
                "status": status, "status_label": STATUS_LABELS[status], "reasons": reasons}

    def snapshot(self, as_of=None, now=None):
        base = self.env.snapshot(as_of=as_of, now=now)
        d = base["snapshot_date"]
        sectors = [self._sector_row(sector, d) for sector in base["sectors"]]
        counts = {status: sum(row["status"] == status for row in sectors) for status in STATUS_LABELS}
        ranking_known = sum(row["relative_rank60"] is not None for row in sectors)
        relative_known = sum(row["relative60"] is not None for row in sectors)
        warnings = list(base["warnings"])
        warnings.extend([
            "经济总收益按除息日理论再投，不是实际到账日记账或扣除投资者交易成本与税费后的账户收益。",
            "相对领先只表示近60日跑赢同一全收益参照；即使处于‘趋势资格且相对领先’，绝对收益也可能为负。",
            "同日同基准下，相对60日收益与ETF自身60日收益排序相同，不是两个独立因子，也不叠加打分。",
            "SKDJ 是独立技术参考，不与 TRIX 合并成买卖、资金或胜率指令。",
            "成交额均值衡量交易活跃度，不是资金净流入；距60日经济总收益高点不是账户最大回撤。",
        ])
        if ranking_known == 0:
            warnings.append(f"相对强弱数值可用 {relative_known}/10；完整研究池存在未知项，全部名次留空。")
        sources = deepcopy(base["sources"])
        sources.append({"name": "中证全指全收益指数 H00985", "kind": "official_total_return_index",
                        "url": self._benchmark_source.get("url") if self._benchmark_source else None,
                        "sha256": self._benchmark_source.get("sha256") if self._benchmark_source else None,
                        "data_file": "index_data.json", "data_sha256": self.env._hashes["index_data.json"],
                        "description": "ETF 相对强弱和归一曲线的全收益参照；不是000985价格指数。"})
        freshness = deepcopy(base["freshness"])
        if self._benchmark_returns[d] is None:
            freshness["notes"].append("本模块 H00985 全收益参照窗口不完整，相对强弱与排名未知；市场环境价指及其他有效 ETF 指标仍分别保留。")
        return {"schema": SCHEMA, "snapshot_date": d, "mode": base["mode"],
                "calculated_at": base["calculated_at"], "freshness": freshness,
                "sources": sources, "warnings": warnings,
                "market_context": {"trend": base["trend"], "breadth": base["breadth"]},
                "summary": {"groups": counts, "ranking_known": ranking_known,
                            "relative_known": relative_known, "total": len(SECTORS)},
                "sectors": sectors}

    def history(self, code, as_of=None, limit=252):
        names = dict(SECTORS)
        if code not in names:
            raise ValueError("code 必须为固定十板块的 sh/sz 加六位 ETF 代码")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError("limit 必须为 1 到 5000 的整数")
        d = self.env._select(as_of, _clock())
        end = self.env._calendar_pos[d] + 1
        days = [day for day in self.env._calendar[max(0, end-limit):end] if day >= DISPLAY_START]
        base_date = next((day for day in days
                          if self._economic[code].get(day, {}).get("economic_tr") is not None
                          and day in self._benchmark_bars), None)
        rows = []
        for day in days:
            etf_value = benchmark_value = None
            if base_date is not None and day >= base_date:
                value = self._economic[code].get(day, {}).get("economic_tr")
                if value is not None:
                    etf_value = value / self._economic[code][base_date]["economic_tr"] * 100.0
                if day in self._benchmark_bars:
                    benchmark_value = (float(self._benchmark_bars[day]["close"])
                                       / float(self._benchmark_bars[base_date]["close"]) * 100.0)
            rows.append({"date": day, "etf_normalized": etf_value, "benchmark_normalized": benchmark_value})
        notes = ["ETF 使用除息日理论再投经济总收益；中证全指 H00985 使用官方全收益指数。",
                 "所选窗口首个双方共同有效日各自从100起算；不模拟投资者交易成本、税费、到账等待和再投资执行。",
                 "按第一模块市场交易日历保留缺失行，缺失处应断线显示；早于共同基日的值不显示。",
                 "原始 ETF 交易价已反映基金运行和跟踪表现，本曲线不是实际投资账户净值。"]
        if base_date is None:
            notes.append("当前窗口没有双方共同有效的基日，无法归一比较。")
        if any(row["etf_normalized"] is None or row["benchmark_normalized"] is None for row in rows):
            notes.append("窗口存在资料缺失或公司行动覆盖边界，缺口未填补。")
        return {"code": code, "name": names[code], "snapshot_date": d,
                "rows": rows, "base_date": base_date, "notes": notes}
