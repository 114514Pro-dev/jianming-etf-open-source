"""Run the actual website on loopback with disposable, synthetic D0 data.

This is a manual browser-test harness, never a deployment entry point. It does
not accept an existing application home. All outbound connections are blocked,
and only a marked fixture directory can be resumed. The signal, market clock
and quotes are synthetic; the app, HTTP adapter, ledger and frontend are real.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import copy, deepcopy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import uuid


MARKER = "jianming-etf-isolated-browser-fixture-v1"
TEST_PASSWORD = "isolated-browser-fixture-only"
REPOSITORY = Path(__file__).resolve().parents[1]
SYMBOLS = ("sz159915", "sh512800", "sh518880", "sh511010")
CASES = ("live", "gold", "bond-target", "bond-next-day", "mixed", "cash", "missing", "nonfinite",
         "original-chi", "original-bank", "original-gold", "original-bond", "original-missing",
         "original-future", "bank-hold", "negative-trix", "line-chi", "line-bank", "line-gold", "line-bond",
         "history-gap", "history-range", "single-point", "no-history", "future-history", "identity-mismatch")


def add_original_evidence(signal, name):
    """Synthetic native StagedSignals fields; the real projector decides validity."""
    if name in ("missing", "original-missing"):
        return
    day = signal["confirmed_day"]
    long = {symbol: signal["weights"][symbol] > 0 for symbol in SYMBOLS}
    weekly = {"k": 68., "d": 55., "trix": .125, "signal": .08, "close": 11., "ma": 10.5,
              "week_end": "2026-10-16", "available": "2026-10-16"}
    if not long["sz159915"]:
        weekly.update(k=42., d=53., trix=-.125, signal=-.08)
    market = {**weekly, "close": 11. if long["sz159915"] else 9., "ma": 10.}
    bank = {"k": 23., "d": 19., "trix": None, "signal": None, "ma": None,
            "volume_ratio": 1.3, "ready": True, "entry": long["sh512800"],
            "exit": False, "positive": long["sh512800"]}
    signal.update(ready={symbol: True for symbol in SYMBOLS}, available={symbol: True for symbol in SYMBOLS},
        longs=long, chi_long=long["sz159915"], bank_long=long["sh512800"],
        gold_long=long["sh518880"], bond_long=long["sh511010"],
        weekly_date=weekly["week_end"], weekly_confirmed=weekly["available"], chi_quote_date=day,
        chi_state={"date": day, "close_market": "bull" if long["sz159915"] else "bear",
                   "next_risk": float(long["sz159915"]), "holding_days": 8 if long["sz159915"] else 0,
                   "blocked": False, "reason": "合成原策略：多头延续" if long["sz159915"] else "合成原策略：维持防御配置"},
        bank_state={"date": day, "next_risk": float(long["sh512800"]),
                    "holding_days": 4 if long["sh512800"] else 0,
                    "reason": "合成原策略：继续持有银行参考仓位" if long["sh512800"] else "合成原策略：等待银行低位金叉"})
    features = {"chi_weekly": weekly, "chi_market": market, "bank": bank,
                "dynamic": deepcopy(signal.get("dynamic", {}))}
    for key, symbol, window in (("gold", "sh518880", 120), ("bond", "sh511010", 60)):
        features[key] = {"close": 10., "value": 11. if long[symbol] else 9., "ma": 10., "ma_window": window,
                         "momentum20": .03 if long[symbol] else -.02, "count": 250,
                         "ready": True, "long": long[symbol], "quote_date": day}
    signal["features"] = features
    if name == "bank-hold":
        # A new entry is not required for an existing reference position to persist.
        bank.update(entry=False, positive=False)
    elif name == "negative-trix":
        # Native TRIX is already in percentage points; -0.125 must not show -12.5%.
        weekly.update(trix=-.125, signal=-.25)
    elif name == "original-future":
        for row in (weekly, market):
            row.update(week_end="2026-10-23", available="2026-10-23")
        signal.update(weekly_date="2026-10-23", weekly_confirmed="2026-10-23", chi_quote_date="2026-10-23")
        signal["chi_state"]["date"] = signal["bank_state"]["date"] = "2026-10-23"
        features["gold"]["quote_date"] = features["bond"]["quote_date"] = "2026-10-23"
    elif name == "nonfinite":
        for row in (weekly, market, bank):
            row.update(k="NaN", d="Infinity", trix="-Infinity", signal="NaN", close="Infinity", ma="NaN")
        for key in ("gold", "bond"):
            features[key].update(value="NaN", ma="Infinity", momentum20="-Infinity")


def indicator_histories(signal, name):
    """Entirely synthetic histories, ending at this case's saved signal values.

    These are presentation inputs to the real history projector, never market
    downloads or additions to a ledger. Explicit irregular dates exercise a
    calendar-time axis; only the last point comes from the synthetic signal.
    """
    if name in ("missing", "original-missing", "no-history"):
        return {}
    confirmed = signal["confirmed_day"]
    day = datetime.fromisoformat(confirmed).date()
    daily = []
    while len(daily) < (120 if name == "history-range" else 6):
        if day.weekday() < 5:
            daily.append(day.isoformat())
        day -= timedelta(days=1)
    daily.reverse()
    patterns = {
        "skdj": {"k": [18., 32., 25., 49., 60., None], "d": [27., 29., 35., 40., 52., None]},
        "trix": {"trix": [-.32, -.20, -.07, .03, .11, None], "signal": [-.28, -.23, -.16, -.06, .04, None]},
        "trend": {"value": [9.3, 9.7, 9.5, 10.2, 10.7, None], "ma": [9.8, 9.9, 9.95, 10., 10.2, None]},
        "momentum": {"m20": [-.02, -.03, -.01, .005, .015, None], "m60": [-.04, -.02, .01, .02, .04, None]},
        "volatility": {"vol": [.07, .09, .11, .10, .08, None]},
    }

    def chart(identifier, frequency, unit, basis, latest, weekly=None):
        dates = [(value, None) for value in daily]
        if weekly:
            end = datetime.fromisoformat(weekly["week_end"]).date()
            offsets = range(103 * 7, -1, -7) if name == "history-range" else (42, 35, 28, 21, 7, 0)
            periods = [end - timedelta(days=offset) for offset in offsets]
            dates = [((period + timedelta(days=3)).isoformat(), period.isoformat()) for period in periods[:-1]]
            dates.append((weekly["available"], weekly["week_end"]))
        points = []
        for index, (available, period_end) in enumerate(dates):
            values = {key: sequence[index % (len(sequence) - 1)] for key, sequence in patterns[identifier].items()}
            if index == len(dates) - 1:
                values.update(latest)
            point = {"date": available, "available_on": available, "values": values, "break_before": False}
            if period_end:
                point["period_end"] = period_end
            points.append(point)
        if name == "history-gap":
            # One series can be missing while another remains visible; a later
            # explicit break must not be connected by an invented segment.
            points[1]["values"][next(iter(points[1]["values"]))] = None
            points[3]["break_before"] = True
        elif name == "single-point":
            points = points[-1:]
        elif name == "future-history":
            future = (datetime.fromisoformat(confirmed).date() + timedelta(days=1)).isoformat()
            points[-1].update(date=future, available_on=future)
        return {"id": identifier, "frequency": frequency, "unit": unit, "basis": basis, "points": points}

    features = signal["features"]
    histories = {}
    for symbol in SYMBOLS:
        charts = []
        if symbol == "sz159915":
            weekly, market = features["chi_weekly"], features["chi_market"]
            charts.append(chart("skdj", "weekly", "indicator", "confirmed_weekly_indicator",
                                {key: weekly[key] for key in ("k", "d")}, weekly))
            charts.append(chart("trix", "weekly", "percent_points", "confirmed_weekly_indicator",
                                {key: weekly[key] for key in ("trix", "signal")}, weekly))
            charts.append(chart("trend", "weekly", "price", "weekly_adjusted_close_ma50",
                                {"value": market["close"], "ma": market["ma"]}, market))
        elif symbol == "sh512800":
            charts.append(chart("skdj", "daily", "indicator", "daily_indicator",
                                {key: features["bank"][key] for key in ("k", "d")}))
        else:
            key, window = ("gold", 120) if symbol == "sh518880" else ("bond", 60)
            charts.append(chart("trend", "daily", "index_points", "total_return_ma" + str(window),
                                {"value": features[key]["value"], "ma": features[key]["ma"]}))
        dynamic = signal["dynamic"][symbol]
        charts.append(chart("momentum", "daily", "ratio", "dynamic_total_return",
                            {"m20": dynamic["momentum20"], "m60": dynamic["momentum60"]}))
        charts.append(chart("volatility", "daily", "ratio", "dynamic_total_return", {"vol": dynamic["volatility20"]}))
        histories[symbol] = {"contract_version": "d0-indicator-history-v1", "source": "confirmed_input_history",
            "signal_key": signal["id"] if name != "identity-mismatch" else "synthetic-previous-signal",
            "confirmed_day": confirmed, "status": "available", "reason": None, "charts": charts}
    return histories


def presentation_snapshot(raw, state):
    """Copy a marked fixture's snapshot for UI cases, never alter its ledger.

    Named cases still pass through the real HTTP adapter and rationale projector.
    Nonfinite inputs are strings so the fixture never emits invalid JSON numbers.
    """
    name = state["case"]
    if name not in CASES:
        raise ValueError("Unsupported fixture case")
    if name == "live" and not state.get("generation"):
        return raw, None
    result = deepcopy(raw)
    result["revision"] = str(int(raw["revision"]) + state.get("generation", 0) * 10**12)
    if name == "live":
        return result, None
    if not result.get("account"):
        raise ValueError("Create the disposable fixture account before selecting a case")
    day = "2026-10-21" if name == "gold" else "2026-10-22"
    now = datetime.fromisoformat(day + "T10:00:00+08:00") + timedelta(seconds=state.get("elapsed", 0))
    quote_at = now - timedelta(seconds=2 + state.get("elapsed", 0) - state.get("quote_elapsed", 0))
    stale = (now - quote_at).total_seconds() > 60
    confirmed = "2026-10-20" if name == "gold" else "2026-10-21"
    weights = {symbol: 0. for symbol in SYMBOLS}
    held = {symbol: 0 for symbol in SYMBOLS}
    selected = {"original-chi": "sz159915", "negative-trix": "sz159915", "original-bank": "sh512800",
                "bank-hold": "sh512800", "original-gold": "sh518880", "original-bond": "sh511010",
                "line-chi": "sz159915", "line-bank": "sh512800", "line-gold": "sh518880", "line-bond": "sh511010",
                "history-gap": "sz159915", "history-range": "sz159915", "single-point": "sz159915", "no-history": "sz159915",
                "future-history": "sz159915", "identity-mismatch": "sz159915"}.get(name)
    if selected:
        weights[selected] = 1.; held[selected] = 9700
    elif name == "gold":
        weights["sh518880"] = 1.; held["sh518880"] = 9800
    elif name == "mixed":
        weights.update(sh512800=.4, sh518880=.6); held.update(sh512800=3500, sh518880=6000)
    elif name != "cash":
        weights["sh511010"] = 1.
        held["sh518880" if name == "bond-target" else "sh511010"] = 9800 if name == "bond-target" else 9700
    dynamic = {symbol: {"eligible": weight > 0, "score_ready": True,
        "momentum20": .03 if weight else -.02, "momentum60": .06 if weight else -.04,
        "volatility20": .12, "effective_score": weight * .8, "quote_date": confirmed} for symbol, weight in weights.items()}
    # Positive momentum is not evidence that the original strategy gate passed.
    dynamic["sh512800"].update(momentum20=.08, momentum60=.10, volatility20=.04)
    signal = {"id": "synthetic-case-" + name, "strategy": "D0", "version": "D0-forward-v1",
        "source": "合成可视化验收信号", "valid": True, "waiting_reason": None,
        "day": confirmed, "confirmed_day": confirmed, "execution_day": day,
        "data_cutoff": confirmed + "T15:00:00+08:00", "signal_at": confirmed + "T16:10:00+08:00",
        "known_at": confirmed + "T16:10:00+08:00", "eligible_at": day + "T09:30:00+08:00",
        "weights": weights, "reason": "合成验收场景：" + name + "；不代表真实行情或交易。",
        "dynamic": dynamic, "notes": {symbol: "合成验收：" + ("通过配置资格。" if weight else "未通过配置资格。")
                                           for symbol, weight in weights.items()}}
    if name == "missing":
        signal.pop("dynamic"); signal.pop("notes")
    elif name == "nonfinite":
        for row in dynamic.values():
            row.update(momentum20="NaN", momentum60="Infinity", volatility20="-Infinity",
                       effective_score="NaN", score_ready="unknown")
    add_original_evidence(signal, name)
    result.update(signal=signal, indicator_histories=indicator_histories(signal, name),
                  positions=[], quotes={}, orders=[], fills=[], events=[], plan=None,
                  response_at=now.isoformat(), source_status="waiting" if stale else "ready",
                  reason="quotes_stale" if stale else "ready", last_observed=quote_at.isoformat())
    for symbol, quantity in held.items():
        result["positions"].append({"symbol": symbol, "qty": quantity, "settled_qty": quantity,
            "reserved_qty": 0, "available_qty": quantity, "price": "10.000" if quantity else None,
            "market_value": str(quantity * 10) if quantity else None, "valuation_status": "stale" if stale else "current"})
        result["quotes"][symbol] = {"id": "synthetic-" + symbol, "price": "10.000", "previous_close": "10.000",
            "quote_at": quote_at.isoformat(), "received_at": quote_at.isoformat(), "source": "合成验收报价",
            "status": "unverified", "volume_lots": "1000", "amount_cny": "1000000"}
    cash = str(100000 - sum(held.values()) * 10)
    result["account"].update(initial_capital="100000.00", cash=cash, reserved_cash="0.00", available_cash=cash,
        equity="100000.00", running=False, valuation_status="stale" if stale else "current")
    display_quotes = deepcopy(result["quotes"])
    for quote in display_quotes.values():
        quote.update(price="10.020", quote_at=now.isoformat(), received_at=now.isoformat())
    result["market_observation"] = {"received_at": now.isoformat(), "source": "合成验收最新来源报价", "quotes": display_quotes}
    return result, now


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def verified_root(path):
    if path.is_symlink():
        raise ValueError("Fixture root must not be a symlink")
    root = path.resolve()
    marker = root / "fixture.json"
    if root.is_symlink() or not marker.is_file():
        raise ValueError("A marked browser fixture is required")
    data = json.loads(marker.read_text("utf-8"))
    if data.get("kind") != MARKER or data.get("root") != str(root):
        raise ValueError("Fixture identity mismatch")
    return root


def command(args):
    root = verified_root(args.root)
    identity = uuid.uuid4().hex
    write_json(root / "commands" / (identity + ".json"), {"action": args.action, "case": args.case})
    result = root / "results" / (identity + ".json")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if result.is_file():
            response = json.loads(result.read_text("utf-8"))
            print(json.dumps(response, ensure_ascii=False))
            if not response.get("ok"):
                raise SystemExit(1)
            return
        time.sleep(0.2)
    raise TimeoutError("Fixture command was not processed")


def serve(args):
    root = args.root.resolve()
    if args.resume:
        verified_root(root)
    else:
        root.mkdir(parents=True, exist_ok=False)
        write_json(root / "fixture.json", {"kind": MARKER, "root": str(root)})
    for name in ("commands", "results", "home", "market", "desktop", "temp"):
        (root / name).mkdir(exist_ok=True)
    # Never inherit the user's auth, model keys, proxy settings or app homes.
    safe = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "PATH") if name in os.environ}
    safe.update({
        "LOCALAPPDATA": str(root / "desktop"), "USERPROFILE": str(root / "desktop"),
        "HOME": str(root / "desktop"), "TEMP": str(root / "temp"), "TMP": str(root / "temp"),
        "SIMPLE_ETF_HOME": str(root / "home"), "ETF_SUITE_HOME": str(root / "home" / "suite"),
        "ETF_WEB_AUTO_REFRESH": "0", "ETF_WEB_BENCHMARK_REFRESH": "0",
        "ETF_WEB_INDEX_BENCHMARK_REFRESH": "0", "ETF_SECTOR_RESEARCH_AUTO_UPDATE": "0",
        "ETF_WEB_SECURE_COOKIE": "1", "ETF_WEB_TRUSTED_HOSTS": "127.0.0.1,localhost",
        "PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "2", "OMP_NUM_THREADS": "2",
        "RELEASE_REVISION": "isolated-browser-fixture",
    })
    blocked = []

    def refuse_network(*values, **kwargs):
        blocked.append("outbound_connection_blocked")
        raise OSError("Outbound connections are disabled in the browser fixture")

    # Windows asyncio needs a loopback socketpair before network isolation.
    import asyncio
    with asyncio.Runner() as runner:
        runner.get_loop()
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, safe, clear=True))
            for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
                stack.enter_context(patch(target, side_effect=refuse_network))
            sys.path.insert(0, str(REPOSITORY / "production"))
            import intraday
            from realtime_paper_engine import PaperLedger, TZ
            from realtime_paper_service import PaperService, ReadOnlyPaperSource, SYMBOLS
            from server import create_app, hash_password, PaperHttpAdapter
            import uvicorn

            os.environ["ETF_WEB_PASSWORD_HASH"] = hash_password(TEST_PASSWORD)
            clock_file = root / "clock.json"
            current = [datetime.fromisoformat(json.loads(clock_file.read_text())["now"])
                       if clock_file.exists() else datetime(2026, 10, 21, 10, 0, tzinfo=TZ)]
            sequence = [json.loads(clock_file.read_text()).get("sequence", 0)
                        if clock_file.exists() else 0]
            presentation_file = root / "presentation.json"
            presentation = (json.loads(presentation_file.read_text("utf-8")) if presentation_file.exists()
                            else {"case": "live", "generation": 0, "elapsed": 0, "quote_elapsed": 0})
            actual_view = PaperHttpAdapter.view

            def fixture_view(adapter, raw, command=False):
                prepared, moment = presentation_snapshot(raw, dict(presentation))
                if moment is not None:
                    adapter = copy(adapter)
                    adapter.now = lambda: moment
                return actual_view(adapter, prepared, command=command)

            stack.enter_context(patch.object(PaperHttpAdapter, "view", fixture_view))

            class SyntheticMarket:
                def __init__(self, data):
                    self.data = data

                def observation(self, code, day):
                    # Rich synthetic rationale exercises the real read-only projection.
                    dynamic = {symbol: {"eligible": symbol == "sh518880", "score_ready": True,
                        "momentum20": .03 if symbol == "sh518880" else -.02,
                        "momentum60": .06 if symbol == "sh518880" else -.04,
                        "volatility20": .12, "effective_score": .8 if symbol == "sh518880" else 0}
                        for symbol in SYMBOLS}
                    return {"weights": {symbol: int(symbol == "sh518880") for symbol in SYMBOLS},
                        "reason": "Synthetic browser fixture", "dynamic": dynamic,
                        "notes": {symbol: "合成验收数据：黄金通过多头条件，其他资产未通过；本例不代表真实行情。"
                                  for symbol in SYMBOLS}}

                def at(self, day):
                    return {"dates": {symbol: day for symbol in SYMBOLS},
                            "prices": {symbol: 10 for symbol in SYMBOLS}}

            daily = {group: {"bars": {symbol: [{"date": "2026-10-20", "open": 10,
                     "close": 10, "high": 10, "low": 10, "volume_lots": 1000,
                     "amount_cny": 1000000}] for symbol in SYMBOLS}} for group in ("chi", "bank")}
            write_json(root / "market" / "联合行情缓存.json", daily)
            service_box = []

            def factory(home):
                source = ReadOnlyPaperSource(root / "market", now=lambda: current[0],
                    market_factory=SyntheticMarket, spec_factory=lambda _: {"synthetic": True})
                ledger = PaperLedger(home / "web" / "realtime-paper", now=lambda: current[0])
                service = PaperService(home, source=source, ledger=ledger, now=lambda: current[0])
                service_box.append(service)
                return service

            app = create_app(root / "home", paper_factory=factory)
            faults = {"snapshot": False}

            @app.middleware("http")
            async def fixture_fault(request, call_next):
                if faults["snapshot"] and request.method == "GET" and request.url.path == "/api/realtime-paper":
                    faults["snapshot"] = False
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"detail": "Synthetic temporary read failure"}, status_code=503)
                return await call_next(request)

            config = uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                    log_level="warning", access_log=False, loop="asyncio")
            server = uvicorn.Server(config)
            done = threading.Event()

            def save_status():
                service = service_box[0]
                snapshot = service.snapshot()
                visible, _ = presentation_snapshot(snapshot, presentation)
                write_json(clock_file, {"now": current[0].isoformat(), "sequence": sequence[0]})
                write_json(presentation_file, presentation)
                write_json(root / "fixture-status.json", {"synthetic": True,
                    "outboundAttemptsBlocked": len(blocked), "case": presentation["case"], "snapshot": visible})
                return {"case": presentation["case"], "presentationOnly": presentation["case"] != "live",
                        "confirmedDay": (visible.get("signal") or {}).get("confirmed_day"),
                        "source": visible.get("source_status"), "reason": visible.get("reason"),
                        "orders": len(snapshot.get("orders", [])), "fills": len(snapshot.get("fills", [])),
                        "running": (snapshot.get("account") or {}).get("running", False)}

            def control():
                while not done.wait(0.2):
                    if not service_box:
                        continue
                    for path in sorted((root / "commands").glob("*.json")):
                        output = root / "results" / path.name
                        if output.exists():
                            continue
                        try:
                            request = json.loads(path.read_text("utf-8")); action = request["action"]
                            service = service_box[0]
                            with service._lock:
                                if action == "case":
                                    name = request.get("case")
                                    if name not in CASES:
                                        raise ValueError("Unsupported fixture case")
                                    if name != "live" and not service.snapshot().get("account"):
                                        service.create("100000.00", name="合成可视化验收账户")
                                    presentation.update(case=name, generation=presentation["generation"] + 1,
                                                        elapsed=0, quote_elapsed=0)
                                    faults["snapshot"] = False
                                elif presentation["case"] != "live" and action in ("quote", "recover", "stale"):
                                    presentation["elapsed"] += 70 if action == "stale" else 2
                                    presentation["generation"] += 1
                                    if action != "stale":
                                        presentation["quote_elapsed"] = presentation["elapsed"]
                                        faults["snapshot"] = False
                                elif action in ("quote", "recover"):
                                    faults["snapshot"] = False
                                    current[0] += timedelta(seconds=2)
                                    sequence[0] += 1
                                    rows = []
                                    for symbol in SYMBOLS:
                                        fields = ["0"] * 38
                                        for index, value in {1: symbol, 2: symbol[2:], 3: "10.000", 4: "10.000",
                                            5: "10.000", 6: str(1000 + sequence[0] * 100),
                                            30: current[0].strftime("%Y%m%d%H%M%S"), 33: "10.100",
                                            34: "9.900", 37: str(100 + sequence[0] * 10)}.items():
                                            fields[index] = value
                                        rows.append('v_' + symbol + '="' + '~'.join(fields) + '";')
                                    batch = intraday.parse_quotes("\n".join(rows), received=current[0])
                                    intraday.LiveStore(root / "market").save(batch)
                                    service.poll_once()
                                elif action == "stale":
                                    current[0] += timedelta(seconds=70)
                                    service.poll_once()
                                elif action == "read-failure":
                                    faults["snapshot"] = True
                                elif action == "stop":
                                    server.should_exit = True
                                elif action != "status":
                                    raise ValueError("Unsupported fixture command")
                                response = {"ok": True, "action": action, **save_status()}
                        except Exception as exc:
                            response = {"ok": False, "error": str(exc)}
                        write_json(output, response)

            worker = threading.Thread(target=control, daemon=True)
            worker.start()
            print(json.dumps({"fixture": str(root), "url": f"http://127.0.0.1:{args.port}",
                              "synthetic": True, "network": "outbound blocked"}), flush=True)
            try:
                runner.run(server.serve())
            finally:
                done.set()
                worker.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    start = commands.add_parser("serve")
    start.add_argument("--root", type=Path, required=True)
    start.add_argument("--port", type=int, default=8765)
    start.add_argument("--resume", action="store_true")
    send = commands.add_parser("command")
    send.add_argument("--root", type=Path, required=True)
    send.add_argument("action", choices=("quote", "recover", "stale", "read-failure", "status", "stop", "case"))
    send.add_argument("case", nargs="?", choices=CASES)
    args = parser.parse_args()
    if args.mode == "serve":
        if not 1024 <= args.port <= 65535:
            parser.error("Use an unprivileged loopback port")
        serve(args)
    else:
        if (args.action == "case") != (args.case is not None):
            parser.error("Use 'command --root <fixture> case <name>' only with a case name")
        command(args)


if __name__ == "__main__":
    main()
