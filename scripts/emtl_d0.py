"""D0 order preview and EMTL read-only diagnostics. No order submission path."""
from __future__ import annotations

import argparse
from datetime import datetime
import getpass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from http.cookies import CookieError, SimpleCookie
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
from d0_order_math import SYMBOLS
from d0_order_preview import preview
from realtime_paper_engine import TZ


def inspect_emtl(client_factory, username, password):
    """Connect via an account-bound EMTL client and only issue query methods."""
    stage = "client_init"
    client = None
    timings = {}

    def timed(name, action):
        nonlocal stage
        stage = name
        start = perf_counter()
        try:
            return action()
        finally:
            timings[name] = round((perf_counter() - start) * 1000, 1)

    try:
        client = client_factory(username=username, password=password)
        if not timed("login", client.login):
            raise ValueError("login rejected")
        kinds = {}
        for name, query in (("assets_positions", client.query_asset_and_position),
                            ("orders", client.query_orders), ("trades", client.query_trades)):
            payload = timed(name, query)
            if not isinstance(payload, dict) or type(payload.get("Status")) is not int or payload["Status"] != 0 or "Data" not in payload:
                raise ValueError("query rejected")
            data = payload["Data"]
            if type(data) not in (list, dict):
                raise ValueError("unexpected Data shape")
            kinds[name] = "array" if isinstance(data, list) else "object"
        return {"mode": "read_only", "ok": True, "data_shapes": kinds, "elapsed_ms": timings}
    except Exception:
        # Transport exceptions can embed request URLs with session tokens.
        return {"mode": "read_only", "ok": False, "failed_stage": stage, "elapsed_ms": timings}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass  # Never surface transport objects or credentials in diagnostics.


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _site_origin(site):
    url = urlsplit(site)
    if (not url.hostname or url.username is not None or url.password is not None
            or url.path not in ("", "/") or url.query or url.fragment
            or not (url.scheme == "https" or url.scheme == "http" and url.hostname in ("127.0.0.1", "::1", "localhost"))):
        raise ValueError("站点须为 HTTPS 根地址，仅本机回环地址可用 HTTP")
    return url


def read_paper_snapshot(site, password):
    """Read the D0 order preview input, not the separately licensed live-signal add-on."""
    url = _site_origin(site)
    origin = f"{url.scheme}://{url.netloc}"
    connect = HTTPSConnection if url.scheme == "https" else HTTPConnection
    connection = connect(url.hostname, url.port, timeout=5)
    try:
        connection.request("POST", "/api/login", body=json.dumps({"password": password}),
                           headers={"Content-Type": "application/json", "Origin": origin})
        reply = connection.getresponse()
        if reply.status != 200:
            raise ValueError(f"站点登录未成功（HTTP {reply.status}）")
        cookie = SimpleCookie(reply.headers.get("Set-Cookie", "")).get("etf_session")
        if not cookie or not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie.value):
            raise ValueError("站点未返回预期的登录会话")
        if url.scheme == "http" and cookie["secure"]:
            raise ValueError("站点使用安全 Cookie，请改用 HTTPS")
        if len(reply.read(4097)) > 4096:
            raise ValueError("站点登录响应过大")
        connection.request("GET", "/api/realtime-paper/d0-order-preview-input", headers={"Cookie": cookie.OutputString(attrs=[])})
        reply = connection.getresponse()
        if reply.status != 200:
            raise ValueError(f"无法读取 D0 模拟盘（HTTP {reply.status}）")
        limit = 64 * 1024
        raw = reply.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("D0 模拟盘响应过大")
        return json.loads(raw)
    finally:
        connection.close()


def _prompt(label):
    if not sys.stdin.isatty():
        raise ValueError("请在交互式终端运行；请勿将口令写入命令或脚本")
    value = getpass.getpass(label)
    if not value.strip():
        raise ValueError("口令不能为空")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    plan = subs.add_parser("preview", help="读取 D0 和资金快照，仅打印拟委托")
    source = plan.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", help="登录后保存的 D0 模拟盘 API JSON")
    source.add_argument("--site", help="直接读取简明 ETF 的 D0 模拟盘 API")
    plan.add_argument("--balances", required=True, help="手工确认的 D0 资金持仓 JSON")
    probe = subs.add_parser("probe", help="通过 EMTL 登录并仅读取账户数据")
    probe.add_argument("--authorized-read-only", action="store_true", required=True,
                       help="你已确认有权在本设备进行委托、成交和资金持仓查询")
    args = parser.parse_args(argv)
    try:
        if args.command == "preview":
            if args.site:
                _site_origin(args.site)
                password = _prompt("简明 ETF 网站口令（不回显，不是证券交易密码）: ")
                start = perf_counter()
                snapshot = read_paper_snapshot(args.site, password)
                site_ms = round((perf_counter() - start) * 1000, 1)
            else:
                snapshot, site_ms = _read_json(args.snapshot), None
            balances = _read_json(args.balances)
            start = perf_counter()
            report = preview(snapshot, balances, now=datetime.now(TZ))
            report["plan_ms"] = round((perf_counter() - start) * 1000, 3)
            if site_ms is not None:
                report["site_login_and_read_ms"] = site_ms
        else:
            try:
                from emtl import TradingClient
            except ImportError:
                raise ValueError("请在独立执行环境安装 emtl==0.3.1") from None
            username = os.environ.get("EM_USERNAME", "").strip()
            if not username:
                raise ValueError("请在本机设置 EM_USERNAME")
            password = _prompt("东方财富证券交易密码（不回显）: ")
            report = inspect_emtl(TradingClient, username, password)
    except (OSError, ArithmeticError, HTTPException, CookieError):
        parser.exit(2, "失败：文件、站点连接或金额/价格计算异常。\n")
    except ValueError as exc:
        parser.exit(2, f"失败：{exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
