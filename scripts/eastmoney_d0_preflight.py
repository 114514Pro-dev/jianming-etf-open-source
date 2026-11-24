# SPDX-License-Identifier: LicenseRef-D0-Addons
"""Read-only D0 connection check, loaded as an Eastmoney Quant Python strategy."""
from decimal import Decimal, InvalidOperation
from http.cookiejar import CookieJar
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener


SYMBOLS = ("SZSE.159915", "SHSE.512800", "SHSE.518880", "SHSE.511010")


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("网站返回重定向，请配置网站的最终 HTTPS 地址")


def read_signal(site, password):
    url = urlsplit(site)
    loopback = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not url.hostname or url.username is not None or url.password is not None
        or url.path not in {"", "/"} or url.query or url.fragment
        or not (url.scheme == "https" or url.scheme == "http" and loopback)
    ):
        raise ValueError("网站地址须为 HTTPS，或本机 HTTP 站点根地址")
    origin = site.rstrip("/")
    browser = build_opener(RejectRedirect(), HTTPCookieProcessor(CookieJar()))
    login = Request(
        origin + "/api/login",
        data=json.dumps({"password": password, "remember_device": False}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": origin},
    )
    try:
        with browser.open(login, timeout=5) as response:
            if json.load(response).get("authenticated") is not True:
                raise ValueError("简明 ETF 网站登录未成功")
        with browser.open(origin + "/api/live-trading/signal?strategy=D0", timeout=5) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 409:
            raise ValueError("网站暂无当前已确认的 D0 信号") from None
        raise ValueError(f"简明 ETF 网站返回 HTTP {error.code}") from None


def nonnegative(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("收到无效的账户数值或策略权重") from None
    if not number.is_finite() or number < 0:
        raise ValueError("收到无效的账户数值或策略权重")
    return number


def preflight(signal, account_id, *, get_cash, get_position):
    targets = signal.get("targets")
    if (
        signal.get("schema") != "jianming-etf.confirmed-target.v1"
        or signal.get("strategy") != "D0" or not signal.get("signal_id")
        or not isinstance(targets, dict) or set(targets) != set(SYMBOLS)
    ):
        raise ValueError("D0 信号格式或标的范围不符")
    weights = {symbol: nonnegative(targets[symbol]) for symbol in SYMBOLS}
    if any(weight > 1 for weight in weights.values()) or sum(weights.values()) > Decimal("1.000001"):
        raise ValueError("D0 目标权重无效")
    if not account_id:
        raise ValueError("请指定东财掘金关联的交易账户 ID")
    cash = get_cash(account_id=account_id)
    if not isinstance(cash, dict) or cash.get("account_id") != account_id:
        raise ValueError("东财掘金未返回所指定账户的资金记录")
    positions = get_position(account_id=account_id)
    if not isinstance(positions, list):
        raise ValueError("东财掘金持仓查询返回格式异常")
    holdings = {}
    for row in positions:
        if not isinstance(row, dict) or row.get("account_id") != account_id:
            raise ValueError("东财掘金持仓记录与所指定账户不符")
        symbol = row.get("symbol")
        if symbol not in weights:
            continue
        if symbol in holdings or row.get("side") != 1:
            raise ValueError("D0 标的存在重复或非多头持仓，请核对账户")
        volume = nonnegative(row.get("volume"))
        available = nonnegative(row.get("available_now"))
        if available > volume or any(value != value.to_integral_value() for value in (volume, available)):
            raise ValueError("东财掘金返回的持仓或可卖份额异常")
        holdings[symbol] = (int(volume), int(available))
    return {
        "mode": "read_only",
        "signal_id": signal["signal_id"],
        "execution_day": signal["execution_day"],
        "eligible_at": signal["eligible_at"],
        "available_cash": format(nonnegative(cash.get("available")), "f"),
        "targets": [
            {"symbol": symbol, "weight": format(weights[symbol], "f"),
             "held": holdings.get(symbol, (0, 0))[0],
             "sellable": holdings.get(symbol, (0, 0))[1]}
            for symbol in SYMBOLS
        ],
    }


def init(context):
    """Run once when the strategy starts inside the signed-in terminal."""
    from gm.api import get_cash, get_position

    config = {key: os.environ.get(key, "") for key in (
        "JIANMING_SITE_URL", "JIANMING_SITE_PASSWORD", "EASTMONEY_ACCOUNT_ID",
    )}
    if not all(config.values()):
        raise ValueError("请配置 JIANMING_SITE_URL、JIANMING_SITE_PASSWORD 和 EASTMONEY_ACCOUNT_ID")
    signal = read_signal(config["JIANMING_SITE_URL"], config["JIANMING_SITE_PASSWORD"])
    report = preflight(signal, config["EASTMONEY_ACCOUNT_ID"], get_cash=get_cash, get_position=get_position)
    print(json.dumps(report, ensure_ascii=False))
