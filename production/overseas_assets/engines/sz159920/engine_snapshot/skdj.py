"""China A-share/ETF daily data and SKDJ downloader."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
import json
import math
from pathlib import Path
import queue
import re
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

try:
    import requests as _requests
except ImportError:  # Source-only fallback; packaged desktop app includes requests.
    _requests = None

CN_TZ = timezone(timedelta(hours=8))
ENDPOINT = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_ENDPOINT = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
ADJUSTMENTS = {"none": "0", "qfq": "1", "hfq": "2"}
ADJUST_LABELS = {"不复权": "none", "前复权": "qfq", "后复权": "hfq"}


class DataError(ValueError):
    """Input or upstream data error suitable for displaying to the user."""


def cn_today():
    return datetime.now(CN_TZ).date()


def parse_date(value):
    try:
        text = str(value)
        if re.fullmatch(r"\d{8}", text):
            return datetime.strptime(text, "%Y%m%d").date()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
    except ValueError:
        pass
    raise DataError(f"日期无效：{value}；请用 YYYY-MM-DD 或 YYYYMMDD。")


def normalize_symbol(value):
    text = value.strip().lower()
    match = re.fullmatch(r"(?:(sh|sz|bj))?(\d{6})(?:\.(sh|sz|bj))?", text)
    if not match:
        raise DataError(f"股票代码无效：{value}；示例 600519、sz000001、600519.SH。")
    prefix, code, suffix = match.groups()
    if code.startswith(("600", "601", "603", "605", "688", "689")) or _is_sh_etf_code(code):
        market = "sh"
    elif code.startswith(("000", "001", "002", "003", "300", "301", "159")):
        market = "sz"
    elif code.startswith(("43", "83", "87", "92")):
        market = "bj"
    else:
        raise DataError(f"暂不支持此代码段：{code}；本工具支持沪深京 A 股和沪深交易所 ETF。")
    if (prefix and prefix != market) or (suffix and suffix != market):
        raise DataError(f"交易所与股票代码不匹配：{value}。")
    return market + code


def normalize_index_symbol(value):
    """Normalize a mainland market-index code without confusing it with an A-share code."""
    text = str(value).strip().lower()
    match = re.fullmatch(r"(?:(sh|sz|bj))?(\d{6})(?:\.(sh|sz|bj))?", text)
    if not match:
        raise DataError(f"基准指数代码无效：{value}；示例 000300、sh000300、399006.SZ。")
    prefix, code, suffix = match.groups()
    supported = {
        "000300": "sh",  # 沪深300
        "000905": "sh",  # 中证500
        "000852": "sh",  # 中证1000
        "000688": "sh",  # 科创50
        "399006": "sz",  # 恒生指数指
    }
    market = supported.get(code)
    if market is None:
        raise DataError("当前基准仅支持 000300、000905、000852、000688、399006。")
    if (prefix and prefix != market) or (suffix and suffix != market):
        raise DataError(f"交易所与基准指数代码不匹配：{value}。")
    return market + code


def _is_sh_etf_code(code):
    return code.startswith(("510", "511", "512", "513", "515", "516", "517", "518",
                            "520", "521", "522", "523", "560", "561", "562", "563",
                            "588", "589"))


def is_etf_symbol(symbol):
    normalized = normalize_symbol(symbol)
    code = normalized[2:]
    return normalized.startswith("sz159") or normalized.startswith("sh") and _is_sh_etf_code(code)


def parse_symbols(text):
    result = list(dict.fromkeys(normalize_symbol(x) for x in re.split(r"[\s,，;；]+", text.strip()) if x))
    if not result:
        raise DataError("请至少输入一只股票代码。")
    if len(result) > 50:
        raise DataError("每次最多 50 只股票，请分批获取。")
    return result


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    close: float
    high: float
    low: float
    volume_lots: float
    amount_cny: float


@dataclass
class Result:
    symbol: str
    name: str
    start: str
    end: str
    adjust: str
    n: int
    m: int
    fetched_at: str
    calculation_start: str
    prior_bars: int
    warnings: list[str]
    rows: list[dict]
    source: str = "东方财富公开日线行情"


def check_periods(n, m):
    if isinstance(n, bool) or isinstance(m, bool) or not isinstance(n, int) or not isinstance(m, int):
        raise DataError("N、M 必须是整数。")
    if not 1 <= n <= 250 or not 1 <= m <= 100:
        raise DataError("N 范围 1–250，M 范围 1–100。")


def validate_bars(bars):
    previous = None
    for bar in bars:
        day = parse_date(bar.date)
        if previous is not None and day <= previous:
            raise DataError("行情日期必须严格递增且不重复。")
        previous = day
        numbers = (bar.open, bar.close, bar.high, bar.low, bar.volume_lots, bar.amount_cny)
        if not all(math.isfinite(x) for x in numbers):
            raise DataError(f"{bar.date} 存在缺失或非有限数值，已停止计算。")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or bar.low > bar.high:
            raise DataError(f"{bar.date} 开高低收数据不一致，已停止计算。")
        if bar.volume_lots < 0 or bar.amount_cny < 0:
            raise DataError(f"{bar.date} 成交数据为负，已停止计算。")


def calculate_skdj(bars, n=9, m=3):
    """Full N-bar range; EMA seeded by first RSV; D requires M K values.

    If the N-bar range is flat, carry the previous raw RSV (50 initially).
    No J line: the selected SKDJ definition has K and D only.
    """
    check_periods(n, m)
    validate_bars(bars)
    output, k_values = [], []
    previous_raw, smooth_rsv, smooth_k = 50.0, None, None
    alpha = 2.0 / (m + 1)
    for i, bar in enumerate(bars):
        row = asdict(bar)
        row.update(raw_rsv=None, rsv=None, k=None, d=None)
        if i >= n - 1:
            window = bars[i - n + 1:i + 1]
            lo, hi = min(b.low for b in window), max(b.high for b in window)
            raw = previous_raw if hi == lo else (bar.close - lo) / (hi - lo) * 100.0
            previous_raw = raw
            smooth_rsv = raw if smooth_rsv is None else alpha * raw + (1 - alpha) * smooth_rsv
            smooth_k = smooth_rsv if smooth_k is None else alpha * smooth_rsv + (1 - alpha) * smooth_k
            k_values.append(smooth_k)
            d = math.fsum(k_values[-m:]) / m if len(k_values) >= m else None
            row.update(raw_rsv=raw, rsv=smooth_rsv, k=smooth_k, d=d)
        output.append(row)
    return output


def request_json(params, timeout=15):
    if _requests is not None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://quote.eastmoney.com/",
        }
        last_error = None
        # Direct access first avoids stale/broken Windows proxy settings. If a
        # network requires its configured proxy, the second mode preserves it.
        for trust_environment in (False, True):
            session = _requests.Session()
            session.trust_env = trust_environment
            try:
                for attempt in range(2):
                    try:
                        response = session.get(ENDPOINT, params=params, headers=headers,
                                               timeout=(6, timeout))
                        response.raise_for_status()
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise DataError("行情接口未返回 JSON 对象。")
                        return payload
                    except DataError:
                        raise
                    except (_requests.exceptions.RequestException, ValueError, UnicodeError) as exc:
                        last_error = exc
                        if attempt == 0:
                            time.sleep(0.5)
            finally:
                session.close()
        detail = type(last_error).__name__ if last_error else "未知网络错误"
        raise DataError(f"行情接口连接失败（{detail}）；已尝试直连和系统代理，请稍后重试。") from last_error
    request = Request(ENDPOINT + "?" + urlencode(params), headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://quote.eastmoney.com/",
    })
    direct_opener = build_opener(ProxyHandler({}))
    last_error = None
    for attempt in range(4):
        try:
            opener = direct_opener if attempt < 2 else None
            with (opener.open(request, timeout=timeout) if opener else urlopen(request, timeout=timeout)) as response:
                payload = json.loads(response.read().decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise DataError("行情接口未返回 JSON 对象。")
            return payload
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise DataError(f"行情接口 HTTP {exc.code}；请稍后重试。") from exc
        except (URLError, TimeoutError, OSError, HTTPException, json.JSONDecodeError, UnicodeError) as exc:
            last_error = exc
            if attempt == 3:
                raise DataError(f"行情接口连接失败（{type(exc).__name__}）；已尝试直连和系统代理，请稍后重试。") from exc
        time.sleep(0.5 * (attempt + 1))
    raise DataError("无法获取行情。")


def request_text(url, params, timeout=15):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://gu.qq.com/",
    }
    last_error = None
    if _requests is not None:
        for trust_environment in (False, True):
            session = _requests.Session()
            session.trust_env = trust_environment
            try:
                for attempt in range(2):
                    try:
                        response = session.get(url, params=params, headers=headers, timeout=(6, timeout))
                        response.raise_for_status()
                        return response.content.decode("utf-8-sig")
                    except (_requests.exceptions.RequestException, ValueError, UnicodeError) as exc:
                        last_error = exc
                        if attempt == 0:
                            time.sleep(0.5)
            finally:
                session.close()
    else:
        request = Request(url + "?" + urlencode(params), headers=headers)
        direct_opener = build_opener(ProxyHandler({}))
        for attempt in range(4):
            try:
                opener = direct_opener if attempt < 2 else None
                with (opener.open(request, timeout=timeout) if opener else urlopen(request, timeout=timeout)) as response:
                    return response.read().decode("utf-8-sig")
            except (URLError, TimeoutError, OSError, HTTPException, UnicodeError) as exc:
                last_error = exc
                if attempt in (0, 2):
                    time.sleep(0.5)
    detail = type(last_error).__name__ if last_error else "未知网络错误"
    raise DataError(f"备用行情接口连接失败（{detail}）。") from last_error


def parse_payload(payload, code):
    if payload.get("rc", 0) != 0:
        raise DataError(f"行情接口返回错误码 {payload.get('rc')}。")
    data = payload.get("data")
    if data is None:
        return "", []
    if not isinstance(data, dict) or str(data.get("code")) != code:
        raise DataError("接口返回的股票代码不匹配。")
    lines = data.get("klines")
    if lines is None:
        return str(data.get("name", code)), []
    if not isinstance(lines, list):
        raise DataError("接口 K 线结构异常。")
    bars = []
    for line in lines:
        try:
            fields = line.split(",")
            bars.append(Bar(parse_date(fields[0]).isoformat(), *(float(v) for v in fields[1:7])))
        except (ValueError, TypeError, AttributeError, IndexError) as exc:
            raise DataError("接口存在无法解析的 K 线，已停止计算。") from exc
    validate_bars(sorted(bars, key=lambda bar: bar.date))
    return str(data.get("name", code)), bars


def _fetch_history_eastmoney(symbol, start, end, adjust, request_fn):
    code = symbol[2:]
    params = {
        "secid": f"{1 if symbol.startswith('sh') else 0}.{code}",
        "klt": "101", "fqt": ADJUSTMENTS[adjust],
        "lmt": "10000",
        "beg": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    name, bars = parse_payload(request_fn(params), code)
    for bar in bars:
        if not start <= date.fromisoformat(bar.date) <= end:
            raise DataError("接口返回了查询区间外的行情，无法确认完整性。")
    return name or code, bars


def _fetch_history_tencent(symbol, start, end, adjust):
    adjust_value = {"none": "", "qfq": "qfq", "hfq": "hfq"}[adjust]
    cursor, by_date, name = start, {}, symbol[2:]
    while cursor <= end:
        chunk_end = min(date(min(9999, cursor.year + 1), 12, 31), end)
        params = {
            "_var": f"kline_day{adjust_value}{cursor.year}",
            "param": f"{symbol},day,{cursor.isoformat()},{chunk_end.isoformat()},640,{adjust_value}",
        }
        text = request_text(TENCENT_ENDPOINT, params)
        try:
            payload = json.loads(text[text.index("=") + 1:])
            if payload.get("code") != 0:
                raise DataError(f"备用行情接口返回错误码 {payload.get('code')}。")
            stock_data = payload.get("data", {}).get(symbol, {})
            quote = stock_data.get("qt", {}).get(symbol, [])
            if len(quote) > 1 and quote[1]:
                name = str(quote[1])
            if adjust_value and stock_data.get('day') and f'{adjust_value}day' not in stock_data:
                raise DataError('备用源仅返回未标明复权的日线，不能替代所请求的复权行情')
            lines = stock_data.get(f"{adjust_value}day" if adjust_value else "day", [])
            if not isinstance(lines, list):
                raise DataError("备用行情接口 K 线结构异常。")
            for fields in lines:
                day = parse_date(fields[0])
                if not cursor <= day <= chunk_end:
                    continue
                bar = Bar(day.isoformat(), float(fields[1]), float(fields[2]), float(fields[3]),
                          float(fields[4]), float(fields[5]), float(fields[8]) * 10000.0)
                if bar.date in by_date and by_date[bar.date] != bar:
                    raise DataError("备用源重复日期的行情冲突。")
                by_date[bar.date] = bar
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError) as exc:
            if isinstance(exc, DataError):
                raise
            raise DataError("备用行情接口返回了无法解析的数据。") from exc
        cursor = chunk_end + timedelta(days=1)
        if cursor <= end:
            time.sleep(0.12)
    bars = sorted(by_date.values(), key=lambda item: item.date)
    validate_bars(bars)
    return name, bars


def fetch_history(symbol, start, end, adjust, request_fn=None):
    """Use Eastmoney first, then one-source Tencent fallback on network failure."""
    if request_fn is not None:
        return _fetch_history_eastmoney(symbol, start, end, adjust, request_fn)
    try:
        name, bars = _fetch_history_eastmoney(symbol, start, end, adjust, request_json)
        if not bars:
            raise DataError('主行情源返回空历史，尝试完整备用源')
        return name, bars
    except DataError as primary_error:
        try:
            # The public endpoint sometimes rejects one HTTP header profile.
            # Retry the complete same-provider series before changing providers.
            name, bars = _fetch_history_eastmoney(symbol, start, end, adjust,
                lambda params: json.loads(request_text(ENDPOINT, params)))
            if not bars: raise DataError('主行情源的备用请求仍返回空历史')
            return name, bars
        except (DataError, ValueError):
            pass
        try:
            return _fetch_history_tencent(symbol, start, end, adjust)
        except DataError as fallback_error:
            raise DataError(
                f"两个行情源均不可用：东方财富为 {primary_error}；腾讯备用源为 {fallback_error}"
            ) from fallback_error


def get_skdj(symbol, start, end, adjust="qfq", n=9, m=3, request_fn=None):
    symbol = normalize_symbol(symbol)
    start, end = parse_date(start), parse_date(end)
    check_periods(n, m)
    if start > end:
        raise DataError("开始日期不能晚于结束日期。")
    if start < date(1990, 1, 1) or end > cn_today():
        raise DataError("日期范围应在 1990-01-01 至北京时间今天之间。")
    if adjust not in ADJUSTMENTS:
        raise DataError("复权方式必须为 none、qfq 或 hfq。")
    target_warmup = n + 10 * m
    warm_start = max(date(1990, 1, 1), start - timedelta(days=max(365, target_warmup * 3)))
    name, bars = fetch_history(symbol, warm_start, end, adjust, request_fn)
    if not bars:
        raise DataError(f"{symbol} 未返回行情：请核对股票代码、日期及数据源覆盖情况。")
    calculated = calculate_skdj(bars, n, m)
    rows = [row for row in calculated if start.isoformat() <= row["date"] <= end.isoformat()]
    if not rows:
        raise DataError(f"{symbol} 在所选区间没有行情；可能为休市、停牌或未上市。")
    prior_bars = sum(bar.date < rows[0]["date"] for bar in bars)
    warnings = []
    if prior_bars < target_warmup:
        warnings.append(f"预热仅 {prior_bars} 根 K 线，低于建议 {target_warmup} 根；早期指标可能与行情软件不同。")
    if any(row["d"] is None for row in rows):
        warnings.append("部分日期不足 N+M-1 根历史 K 线，相关指标保留为空。")
    if any(all(b.high == b.low == b.close for b in bars[i - n + 1:i + 1]) and
           max(b.high for b in bars[i - n + 1:i + 1]) == min(b.low for b in bars[i - n + 1:i + 1])
           for i in range(n - 1, len(bars))):
        warnings.append("存在 N 周期价格区间为零的情况：沿用上一原始 RSV，初值为 50。")
    if rows[-1]["date"] == cn_today().isoformat():
        warnings.append("包含北京时间当日行情，可能仍在更新；日线请在收盘后核对。")
    if (end - date.fromisoformat(rows[-1]["date"])).days > 7:
        warnings.append(f"最新行情截至 {rows[-1]['date']}，距结束日期超过 7 天；请核对休市、停牌或接口缺数。")
    return Result(symbol, name, start.isoformat(), end.isoformat(), adjust, n, m,
                  datetime.now(CN_TZ).isoformat(timespec="seconds"), bars[0].date,
                  prior_bars, warnings, rows)


def csv_safe(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(results, path, latest_only=False, overwrite=False):
    fields = ["symbol", "name", "date", "open", "high", "low", "close", "volume_lots", "amount_cny",
              "raw_rsv", "rsv", "k", "d", "adjust", "n", "m", "source", "fetched_at",
              "start", "end", "calculation_start", "prior_bars", "warnings"]
    with Path(path).open("w" if overwrite else "x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in results:
            metadata = {key: getattr(result, key) for key in fields if hasattr(result, key)}
            metadata["warnings"] = "；".join(result.warnings)
            for row in (result.rows[-1:] if latest_only else result.rows):
                writer.writerow({key: csv_safe(value) for key, value in (metadata | row).items()})


def format_number(value):
    return "—" if value is None else f"{value:.4f}"


def _run_legacy_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("A 股 SKDJ 数据工具")
    root.geometry("1080x780")
    root.minsize(900, 660)
    root.configure(bg="#f2f5f8")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background="#f2f5f8")
    style.configure("TLabel", background="#f2f5f8", font=("Microsoft YaHei UI", 10))
    style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=7)
    style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 10))
    style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
    main = ttk.Frame(root, padding=24)
    main.pack(fill="both", expand=True)
    ttk.Label(main, text="A 股 / SKDJ", font=("Microsoft YaHei UI", 24, "bold")).pack(anchor="w")
    ttk.Label(main, text="获取沪深京日线 · 计算慢速随机指标 · 导出 CSV", foreground="#536477").pack(anchor="w", pady=(4, 18))
    form = ttk.Frame(main)
    form.pack(fill="x")
    variables = {"symbols": tk.StringVar(value="600519, 000001"),
                 "start": tk.StringVar(value=(cn_today() - timedelta(days=365)).isoformat()),
                 "end": tk.StringVar(value=cn_today().isoformat()),
                 "adjust": tk.StringVar(value="前复权"), "n": tk.StringVar(value="9"), "m": tk.StringVar(value="3")}
    ttk.Label(form, text="股票代码（逗号或空格分隔，最多 50 只）").grid(row=0, column=0, columnspan=6, sticky="w")
    symbols_entry = ttk.Entry(form, textvariable=variables["symbols"], font=("Microsoft YaHei UI", 11))
    symbols_entry.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(6, 12))
    for col, (key, label, width) in enumerate((("start", "开始日期", 15), ("end", "结束日期", 15),
                                              ("adjust", "复权", 10), ("n", "N / 区间", 8), ("m", "M / 平滑", 8))):
        ttk.Label(form, text=label).grid(row=2, column=col, sticky="w")
        if key == "adjust":
            widget = ttk.Combobox(form, textvariable=variables[key], values=list(ADJUST_LABELS), state="readonly", width=width)
        else:
            widget = ttk.Entry(form, textvariable=variables[key], width=width)
        widget.grid(row=3, column=col, sticky="ew", padx=(0, 12), pady=(6, 12))
        form.columnconfigure(col, weight=1)
    toolbar = ttk.Frame(main)
    toolbar.pack(fill="x", pady=(0, 10))
    state = {"results": [], "busy": False, "closed": False}
    events = queue.Queue()
    status = tk.StringVar(value="尚未获取数据。输入代码后点击“获取 SKDJ”。")
    query_button = ttk.Button(toolbar, text="获取 SKDJ")
    query_button.pack(side="left")
    export_button = ttk.Button(toolbar, text="导出全部历史 CSV", state="disabled")
    export_button.pack(side="left", padx=8)
    latest_button = ttk.Button(toolbar, text="导出每股最新值", state="disabled")
    latest_button.pack(side="left")
    ttk.Label(main, textvariable=status, wraplength=980, foreground="#245674").pack(anchor="w", pady=(0, 10))
    table_frame = ttk.Frame(main)
    table_frame.pack(fill="both", expand=True)
    cols = ("symbol", "name", "date", "close", "k", "d")
    table = ttk.Treeview(table_frame, columns=cols, show="headings", height=6, selectmode="browse")
    for key, label in zip(cols, ("股票", "名称", "最新行情日期", "收盘", "SKDJ K", "SKDJ D")):
        table.heading(key, text=label)
        table.column(key, width=145, anchor="center")
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    chart = tk.Canvas(main, height=170, background="white", highlightthickness=0)
    chart.pack(fill="x", pady=12)
    details = tk.StringVar(value="选择结果行可查看最近 120 根日线的 K / D 曲线。")
    ttk.Label(main, textvariable=details, wraplength=980, foreground="#536477").pack(anchor="w")
    ttk.Label(main, text="仅提供数据，不构成投资建议。接口可能限流或缺数；与行情软件对照时请统一复权、参数和历史范围。",
              foreground="#697788", wraplength=980).pack(anchor="w", pady=(8, 0))

    def draw_chart(_event=None):
        chart.delete("all")
        selection = table.selection()
        if not selection:
            chart.create_text(24, 30, text="等待真实行情数据", anchor="w", fill="#697788", font=("Microsoft YaHei UI", 11))
            return
        result = state["results"][int(selection[0])]
        rows = result.rows[-120:]
        width, height = max(chart.winfo_width(), 300), 170
        left, right, top, bottom = 42, width - 20, 26, height - 28
        for level in (0, 20, 50, 80, 100):
            y = bottom - level / 100 * (bottom - top)
            chart.create_line(left, y, right, y, fill="#e6ecf2", dash=(3, 4))
            chart.create_text(left - 8, y, text=str(level), anchor="e", fill="#718096")
        chart.create_text(left, 10, text=f"{result.symbol} · 最近 {len(rows)} 根日线", anchor="w", fill="#334155")
        for key, color, offset in (("k", "#147eae", 100), ("d", "#dd8b22", 45)):
            chart.create_text(right - offset, 10, text=key.upper(), fill=color)
            segment = []
            for i, row in enumerate(rows):
                value = row[key]
                if value is None:
                    if len(segment) >= 4:
                        chart.create_line(*segment, fill=color, width=2)
                    segment = []
                    continue
                x = left + i / max(1, len(rows) - 1) * (right - left)
                y = bottom - value / 100 * (bottom - top)
                segment.extend((x, y))
            if len(segment) >= 4:
                chart.create_line(*segment, fill=color, width=2)
            elif len(segment) == 2:
                x, y = segment
                chart.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline=color)
        chart.create_text(left, height - 10, text=rows[0]["date"], anchor="w", fill="#718096")
        chart.create_text(right, height - 10, text=rows[-1]["date"], anchor="e", fill="#718096")
        details.set(f"{result.name} | {result.adjust} | N={result.n}, M={result.m} | {len(result.rows)} 条 | 获取于 {result.fetched_at}\n"
                    + ("；".join(result.warnings) or "已使用查询开始日期之前的日线进行指标预热。"))

    def worker(symbols, start, end, adjust, n, m):
        successes, failures = [], []
        for index, symbol in enumerate(symbols):
            if state["closed"]:
                return
            events.put(("progress", f"正在获取 {index + 1}/{len(symbols)}：{symbol}（含历史预热数据）…"))
            try:
                successes.append(get_skdj(symbol, start, end, adjust, n, m))
            except Exception as exc:
                failures.append(f"{symbol}：{exc}")
            if index < len(symbols) - 1:
                time.sleep(0.3)
        events.put(("done", successes, failures))

    def query():
        if state["busy"]:
            return
        try:
            symbols = parse_symbols(variables["symbols"].get())
            start, end = parse_date(variables["start"].get()), parse_date(variables["end"].get())
            n, m = int(variables["n"].get()), int(variables["m"].get())
            check_periods(n, m)
            if start > end or start < date(1990, 1, 1) or end > cn_today():
                raise DataError("请填写 1990-01-01 至北京时间今天内的有效起止日期。")
            adjust = ADJUST_LABELS[variables["adjust"].get()]
        except (ValueError, KeyError) as exc:
            messagebox.showerror("检查输入", str(exc), parent=root)
            return
        state["busy"], state["results"] = True, []
        table.delete(*table.get_children())
        details.set("正在联网获取；未使用示例数据或旧结果。")
        draw_chart()
        for button in (query_button, export_button, latest_button):
            button.configure(state="disabled")
        threading.Thread(target=worker, args=(symbols, start.isoformat(), end.isoformat(), adjust, n, m), daemon=True).start()

    def poll():
        try:
            while True:
                event = events.get_nowait()
                if event[0] == "progress":
                    status.set(event[1])
                else:
                    results, failures = event[1:]
                    state["results"], state["busy"] = results, False
                    query_button.configure(state="normal")
                    status.set(f"获取完成：成功 {len(results)} 只，失败 {len(failures)} 只。各股票实际日期见下表。")
                    for i, result in enumerate(results):
                        row = result.rows[-1]
                        table.insert("", "end", iid=str(i), values=(result.symbol, result.name, row["date"],
                            format_number(row["close"]), format_number(row["k"]), format_number(row["d"])))
                    if results:
                        export_button.configure(state="normal")
                        latest_button.configure(state="normal")
                        table.selection_set("0")
                        draw_chart()
                    if failures:
                        details.set("部分股票获取失败；成功结果仍可导出。" if results else "获取失败，没有可导出的数据。")
                        messagebox.showwarning("获取失败明细", "\n\n".join(failures), parent=root)
        except queue.Empty:
            pass
        if not state["closed"]:
            root.after(100, poll)

    def save(latest):
        if not state["results"]:
            return
        filename = filedialog.asksaveasfilename(parent=root, title="保存 SKDJ 数据", defaultextension=".csv",
            filetypes=[("CSV 数据", "*.csv")], initialfile=f"skdj_{'latest' if latest else 'history'}_{cn_today()}.csv")
        if filename:
            try:
                export_csv(state["results"], filename, latest_only=latest, overwrite=True)
                status.set(f"已导出：{filename}")
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=root)

    def close():
        state["closed"] = True
        root.destroy()

    query_button.configure(command=query)
    export_button.configure(command=lambda: save(False))
    latest_button.configure(command=lambda: save(True))
    table.bind("<<TreeviewSelect>>", draw_chart)
    chart.bind("<Configure>", draw_chart)
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(100, poll)
    root.mainloop()


def run_gui():
    """Start the focused SKDJ backtest desktop application."""
    import workbench_ui
    workbench_ui.run(sys.modules[__name__])


def main(argv=None):
    parser = argparse.ArgumentParser(description="获取沪深京 A 股日线，计算 SKDJ K/D；无参数启动中文窗口。")
    parser.add_argument('--etf-research',action='store_true',help='打开ETF研究与未来预测工作区')
    parser.add_argument('--bear-gold',action='store_true',help='进入黄金防守通用策略回测')
    parser.add_argument('--dynamic',action='store_true',help='打开每日收盘动态操作分析')
    parser.add_argument("--symbols", help="股票代码，以逗号或空格分隔")
    parser.add_argument("--start", default=(cn_today() - timedelta(days=365)).isoformat())
    parser.add_argument("--end", default=cn_today().isoformat())
    parser.add_argument("--adjust", choices=ADJUSTMENTS, default="qfq")
    parser.add_argument("--n", type=int, default=9)
    parser.add_argument("--m", type=int, default=3)
    parser.add_argument("--output", type=Path, help="CSV 或 JSON 路径；不指定时只打印最新值")
    parser.add_argument("--latest", action="store_true", help="CSV 仅导出每股最新值（JSON 始终保留历史及元数据）")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖指定输出文件")
    args = parser.parse_args(argv)
    if args.bear_gold:
        from workbench_ui import WorkbenchApp
        from bear_gold_main import LABEL
        app=WorkbenchApp(sys.modules[__name__]);app.vars['mode'].set(LABEL);app._on_mode_changed()
        app.show_page('backtest');app.run();return 0
    if args.dynamic:
        from workbench_ui import WorkbenchApp as BacktestApp
        from bear_gold_main import LABEL
        from etf_dynamic_ui import open_window
        app=BacktestApp(sys.modules[__name__]);app.vars['mode'].set(LABEL);app._on_mode_changed()
        open_window(app);app.run();return 0
    if args.etf_research:
        from workbench_ui import WorkbenchApp as BacktestApp
        from bear_gold_main import LABEL
        from etf_research_ui import open_window
        app=BacktestApp(sys.modules[__name__]);app.vars['mode'].set(LABEL);app._on_mode_changed()
        open_window(app);app.run();return 0
    if args.symbols is None:
        if argv or len(sys.argv) > 1:
            parser.error("命令行模式必须指定 --symbols；无参数时启动窗口。")
        run_gui()
        return 0
    try:
        symbols = parse_symbols(args.symbols)
        check_periods(args.n, args.m)
        if args.output and args.output.suffix.lower() not in (".csv", ".json"):
            raise DataError("输出文件扩展名必须为 .csv 或 .json。")
        if args.output and args.output.exists() and not args.overwrite:
            raise DataError("输出文件已存在；请选择新文件，或加 --overwrite。")
    except ValueError as exc:
        parser.error(str(exc))
    results, errors = [], {}
    for symbol in symbols:
        try:
            result = get_skdj(symbol, args.start, args.end, args.adjust, args.n, args.m)
            results.append(result)
            row = result.rows[-1]
            print(f"{symbol} {result.name} {row['date']} close={row['close']} K={format_number(row['k'])} D={format_number(row['d'])}")
            for warning in result.warnings:
                print(f"  提示：{warning}", file=sys.stderr)
        except Exception as exc:
            errors[symbol] = str(exc)
            print(f"失败 {symbol}：{exc}", file=sys.stderr)
    if args.output and (results or args.output.suffix.lower() == ".json"):
        try:
            if args.output.suffix.lower() == ".csv":
                export_csv(results, args.output, args.latest, args.overwrite)
            else:
                with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as stream:
                    json.dump({"results": [asdict(r) for r in results], "errors": errors}, stream,
                              ensure_ascii=False, indent=2, allow_nan=False)
            print(f"已保存：{args.output.resolve()}")
        except OSError as exc:
            print(f"保存失败：{exc}", file=sys.stderr)
            return 1
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
