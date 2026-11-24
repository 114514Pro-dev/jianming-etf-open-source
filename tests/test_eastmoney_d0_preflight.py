import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock

from scripts.eastmoney_d0_preflight import SYMBOLS, preflight, read_signal


SIGNAL = {
    "schema": "jianming-etf.confirmed-target.v1", "strategy": "D0",
    "signal_id": "synthetic-d0", "execution_day": "2026-11-25",
    "eligible_at": "2026-11-25T09:30:00+08:00",
    "targets": dict(zip(SYMBOLS, ("0.6", "0.4", "0", "0"))),
}


class WebsiteFixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, body, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/login" and body["password"] == "fixture":
            self.respond(200, {"authenticated": True}, "etf_session=fixture; Path=/; HttpOnly")
        else:
            self.respond(401, {})

    def do_GET(self):
        if self.path != "/api/live-trading/signal?strategy=D0" or self.headers.get("Cookie") != "etf_session=fixture":
            self.respond(401, {})
        else:
            self.respond(200, SIGNAL)


class EastmoneyD0PreflightTests(unittest.TestCase):
    def test_authenticated_website_signal_combines_with_read_only_terminal_queries(self):
        with HTTPServer(("127.0.0.1", 0), WebsiteFixture) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                signal = read_signal(f"http://127.0.0.1:{server.server_port}", "fixture")
            finally:
                server.shutdown()
                worker.join()

        get_cash = Mock(return_value={"account_id": "test", "available": 1250.25})
        get_position = Mock(return_value=[
            {"account_id": "test", "symbol": SYMBOLS[0], "side": 1, "volume": 300, "available_now": 100},
        ])
        report = preflight(signal, "test", get_cash=get_cash, get_position=get_position)
        get_cash.assert_called_once_with(account_id="test")
        get_position.assert_called_once_with(account_id="test")
        self.assertEqual(report["mode"], "read_only")
        self.assertEqual(report["available_cash"], "1250.25")
        self.assertEqual(report["targets"][0],
                         {"symbol": SYMBOLS[0], "weight": "0.6", "held": 300, "sellable": 100})
        self.assertEqual(report["targets"][1]["held"], 0)
        self.assertNotIn("account_id", report)

    def test_wrong_account_or_portfolio_never_yields_a_report(self):
        cash = Mock(return_value={"account_id": "other", "available": 5})
        positions = Mock(return_value=[])
        with self.assertRaises(ValueError):
            preflight(dict(SIGNAL, strategy="D0I-BOND-WW"), "test", get_cash=cash, get_position=positions)
        cash.assert_not_called()
        with self.assertRaises(ValueError):
            preflight(SIGNAL, "test", get_cash=cash, get_position=positions)
        positions.assert_not_called()
        with self.assertRaises(ValueError):
            read_signal("http://example.com", "fixture")
