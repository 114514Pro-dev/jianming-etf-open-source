import contextlib
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import emtl_d0


NOW = datetime.fromisoformat("2026-11-24T09:30:05+08:00")
SYMBOLS = emtl_d0.SYMBOLS


def inputs():
    stamp = (NOW - timedelta(seconds=1)).isoformat()
    snapshot = {
        "contract_version": "realtime-paper-v1", "strategy": "D0", "source_status": "ready", "historical_seed": False,
        "signal": {"strategy": "D0", "valid": True, "id": "a" * 64, "confirmed_day": "2026-11-23",
                   "execution_day": "2026-11-24", "eligible_at": "2026-11-24T09:30:00+08:00",
                   "data_cutoff": "2026-11-23T15:00:00+08:00", "known_at": "2026-11-23T16:10:00+08:00",
                   "weights": {"sz159915": "0.5", "sh512800": "0.5"}},
        "market_observation": {"received_at": stamp, "quotes": {
            s: {"symbol": s, "price": "1.000", "previous_close": "1.000", "quote_at": stamp, "started": True}
            for s in SYMBOLS}},
    }
    balances = {"observed_at": stamp, "cash": "1005", "available_cash": "1005", "pending_orders": False,
                "commission_rate": "0.0003", "min_fee": "5",
                "positions": {symbol: {"held": 0, "sellable": 0} for symbol in SYMBOLS}}
    return snapshot, balances


class PreviewTests(unittest.TestCase):
    def test_buy_uses_lots_limit_and_shared_cash_after_fees(self):
        result = emtl_d0.preview(*inputs(), now=NOW)
        self.assertEqual(result["stage"], "buy")
        self.assertEqual(result["mode"], "preview_only")
        self.assertEqual(result["targets"]["sz159915"], 500)
        self.assertEqual([(o["symbol"], o["quantity"], o["limit_price"]) for o in result["orders"]],
                         [("sz159915", 500, "1.002"), ("sh512800", 400, "1.002")])
        self.assertEqual(result["quote_receive_age_ms"], 1000)

    def test_sells_first_even_if_there_is_already_enough_cash(self):
        snapshot, balances = inputs()
        balances["positions"]["sh518880"] = {"held": 550, "sellable": 300}
        result = emtl_d0.preview(snapshot, balances, now=NOW)
        self.assertEqual(result["stage"], "sell_first")
        self.assertEqual(result["orders"], [{"symbol": "sh518880", "side": "sell", "quantity": 300, "limit_price": "0.998"}])
        self.assertEqual(result["sell_remainder"][0]["shares_not_in_preview"], 250)
        balances["positions"]["sh518880"]["sellable"] = 0
        result = emtl_d0.preview(snapshot, balances, now=NOW)
        self.assertEqual((result["stage"], result["orders"]), ("sell_blocked", []))

    def test_rejects_unconfirmed_wrong_expired_premarket_and_mixed_data(self):
        cases = [
            ("strategy", "strategy", "D0I-BOND-WW", NOW),
            ("signal", "valid", False, NOW),
            ("signal", "execution_day", "2026-11-25", NOW),
            ("signal", "weights", {"sz159915": "NaN"}, NOW),
            ("signal", "weights", {"sz159915": "0.9", "sh512800": "0.5"}, NOW),
            ("strategy", "source_status", "waiting", NOW),
            ("strategy", "historical_seed", True, NOW),
            ("quote", "status", "halted", NOW),
            ("quote", "quote_at", "2026-11-24T09:30:06+08:00", NOW),
            ("quote", "price", "1.201", NOW),
            ("account", "pending_orders", True, NOW),
            ("account", "observed_at", "2026-11-24T09:29:00+08:00", NOW),
            ("account", "available_cash", "1006", NOW),
            ("market", "received_at", "2026-11-24T09:29:59+08:00", NOW),
            ("strategy", "strategy", "D0", NOW - timedelta(seconds=6)),
            ("strategy", "strategy", "D0", NOW + timedelta(days=1)),
        ]
        for place, key, value, now in cases:
            with self.subTest(place=place, key=key, value=value, now=now):
                snapshot, balances = inputs()
                market = snapshot["market_observation"]
                mapping = {"strategy": snapshot, "signal": snapshot["signal"], "account": balances,
                           "market": market, "quote": market["quotes"]["sz159915"]}[place]
                mapping[key] = value
                with self.assertRaises(ValueError):
                    emtl_d0.preview(snapshot, balances, now=now)

    def test_cli_preview_keeps_broker_out_of_path(self):
        snapshot, balances = inputs()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as stdout:
            snapshot_path, balances_path = Path(folder) / "snapshot.json", Path(folder) / "balances.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            balances_path.write_text(json.dumps(balances), encoding="utf-8")
            with patch.object(emtl_d0, "datetime") as clock, patch.dict(sys.modules, {"emtl": None}):
                clock.now.return_value = NOW
                self.assertEqual(emtl_d0.main(["preview", "--snapshot", str(snapshot_path), "--balances", str(balances_path)]), 0)
            self.assertIn("plan_ms", json.loads(stdout.getvalue()))


class WebsiteTests(unittest.TestCase):
    def test_reads_paper_api_with_website_session_only(self):
        login = Mock(status=200, headers={"Set-Cookie": "etf_session=" + "a" * 43 + "; Secure; HttpOnly"})
        login.read.return_value = b'{"authenticated":true}'
        snapshot = inputs()[0]
        paper = Mock(status=200)
        paper.read.return_value = json.dumps(snapshot).encode()
        with patch.object(emtl_d0, "HTTPSConnection") as connect:
            server = connect.return_value
            server.getresponse.side_effect = [login, paper]
            self.assertEqual(emtl_d0.read_paper_snapshot("https://etf.example", "SITE_TEST"), snapshot)
            auth, read = server.request.call_args_list
            self.assertEqual(auth.args, ("POST", "/api/login"))
            self.assertEqual(auth.kwargs["headers"]["Origin"], "https://etf.example")
            self.assertEqual(read.args, ("GET", "/api/realtime-paper?strategy=D0"))
            self.assertEqual(read.kwargs["headers"], {"Cookie": "etf_session=" + "a" * 43})
            server.close.assert_called_once()

    def test_redirect_not_followed_and_cleartext_remote_origin_rejected(self):
        with patch.object(emtl_d0, "HTTPSConnection") as connect:
            server = connect.return_value
            server.getresponse.return_value = Mock(status=302)
            with self.assertRaisesRegex(ValueError, "HTTP 302"):
                emtl_d0.read_paper_snapshot("https://etf.example", "SITE_TEST")
            server.request.assert_called_once()
            server.close.assert_called_once()
        with self.assertRaises(ValueError):
            emtl_d0.read_paper_snapshot("http://etf.example", "SITE_TEST")


class BrokerTests(unittest.TestCase):
    def test_probe_only_uses_read_only_calls_and_drops_sensitive_payloads(self):
        calls = []

        class Client:
            def __init__(self, username, password):
                calls.append("init")

            def login(self):
                calls.append("login")
                return "private-session-value"

            def query_asset_and_position(self):
                calls.append("assets")
                return {"Status": 0, "Data": [{"account": "private-account-value"}]}

            def query_orders(self):
                calls.append("orders")
                return {"Status": 0, "Data": []}

            def query_trades(self):
                calls.append("trades")
                return {"Status": 0, "Data": []}

            def close(self):
                calls.append("close")

        result = emtl_d0.inspect_emtl(Client, "TEST_ACCOUNT", "TEST_PASSWORD")
        self.assertTrue(result["ok"])
        self.assertNotIn("private-", json.dumps(result))
        self.assertEqual(calls, ["init", "login", "assets", "orders", "trades", "close"])

        def fail(_):
            calls.append("failed_orders")
            raise RuntimeError("private-session-url")

        calls.clear()
        Client.query_orders = fail
        result = emtl_d0.inspect_emtl(Client, "TEST_ACCOUNT", "TEST_PASSWORD")
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_stage"], "orders")
        self.assertNotIn("private-", json.dumps(result))
        self.assertEqual(calls, ["init", "login", "assets", "failed_orders", "close"])

    def test_probe_requires_explicit_opt_in(self):
        with self.assertRaises(SystemExit) as error, contextlib.redirect_stderr(io.StringIO()):
            emtl_d0.main(["probe"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
