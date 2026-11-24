"""Deterministic visualization cases, using only disposable synthetic ledgers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "production"))
spec = importlib.util.spec_from_file_location("d0_browser_fixture", ROOT / "scripts/d0_browser_fixture.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
from realtime_paper_engine import PaperLedger
from server import PaperHttpAdapter


class BrowserFixtureCases(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.environ.get("ETF_TEST_TMPDIR"))
        self.now = datetime(2026, 10, 21, 10, tzinfo=timezone(timedelta(hours=8)))
        self.ledger = PaperLedger(Path(self.directory.name), now=lambda: self.now)
        self.ledger.create("100000.00", name="Synthetic case test")
        self.raw = self.ledger.snapshot()
        self.before = deepcopy(self.raw)

    def tearDown(self):
        self.ledger.close()
        self.directory.cleanup()

    def view(self, name, generation=1, elapsed=0, quote_elapsed=0):
        raw, moment = fixture.presentation_snapshot(self.raw, dict(case=name, generation=generation,
            elapsed=elapsed, quote_elapsed=quote_elapsed))
        adapter = PaperHttpAdapter(SimpleNamespace(now=lambda: moment or self.now))
        result = adapter.view(raw)
        json.dumps(result, allow_nan=False)
        self.assertEqual(self.raw, self.before)
        self.assertEqual(self.ledger.snapshot(), self.before)
        return result, result["accounts"][0]

    def test_date_target_and_actual_holdings_change_independently(self):
        first, gold = self.view("gold", generation=1)
        second, target = self.view("bond-target", generation=2)
        third, held = self.view("bond-next-day", generation=3)
        self.assertEqual(gold["signal"]["confirmed_day"], "2026-10-20")
        self.assertEqual(target["signal"]["confirmed_day"], "2026-10-21")
        self.assertEqual(target["signal"]["execution_day"], "2026-10-22")
        self.assertEqual(float(gold["signal"]["weights"]["sh518880"]), 1)
        self.assertEqual(float(target["signal"]["weights"]["sh511010"]), 1)
        self.assertEqual(target["holdings"][0]["symbol"], "sh518880")
        self.assertEqual(held["holdings"][0]["symbol"], "sh511010")
        self.assertEqual(target["holdings"][0]["quantity"], 9800)
        self.assertEqual(held["holdings"][0]["quantity"], 9700)
        self.assertLess(int(first["revision"]), int(second["revision"]))
        self.assertLess(int(second["revision"]), int(third["revision"]))

    def test_mixed_and_cash_cases_have_consistent_values(self):
        _, mixed = self.view("mixed")
        self.assertEqual({h["symbol"]: h["quantity"] for h in mixed["holdings"]},
                         {"sh512800": 3500, "sh518880": 6000})
        self.assertEqual(float(mixed["cash"]), 5000)
        self.assertEqual(float(mixed["holdings_value"]) + float(mixed["cash"]), float(mixed["equity"]))
        _, cash = self.view("cash")
        self.assertEqual(cash["holdings"], [])
        self.assertEqual(float(cash["cash"]), 100000)
        self.assertTrue(all(float(v) == 0 for v in cash["signal"]["weights"].values()))
        self.assertTrue(all(a["eligible"] is False for a in cash["signal"]["rationale"]["assets"]))

    def test_missing_and_nonfinite_metrics_are_unavailable_after_real_projection(self):
        _, missing = self.view("missing")
        for row in missing["signal"]["rationale"]["assets"]:
            for key in ("eligible", "score_ready", "note", "momentum20", "momentum60", "volatility20", "effective_score"):
                self.assertIsNone(row[key])
        _, nonfinite = self.view("nonfinite")
        for row in nonfinite["signal"]["rationale"]["assets"]:
            for key in ("score_ready", "momentum20", "momentum60", "volatility20", "effective_score"):
                self.assertIsNone(row[key])
        _, gold = self.view("gold")
        bank = next(a for a in gold["signal"]["rationale"]["assets"] if a["symbol"] == "sh512800")
        self.assertFalse(bank["eligible"])
        self.assertGreater(bank["momentum20"], 0)
        self.assertGreater(bank["momentum60"], 0)
        self.assertEqual(bank["effective_score"], 0)
        self.assertLess(bank["volatility20"], .08)

    def test_stale_and_recovery_keep_quantity_but_change_valuation_freshness(self):
        fresh_data, fresh = self.view("bond-next-day")
        stale_data, stale = self.view("bond-next-day", generation=2, elapsed=70)
        _, recovered = self.view("bond-next-day", generation=3, elapsed=72, quote_elapsed=72)
        self.assertEqual([a["valuation_status"] for a in (fresh, stale, recovered)], ["fresh", "stale", "fresh"])
        self.assertEqual([a["holdings"][0]["quantity"] for a in (fresh, stale, recovered)], [9700] * 3)
        self.assertEqual(stale["holdings"][0]["valuation_status"], "stale")
        self.assertEqual(recovered["holdings"][0]["valuation_status"], "fresh")
        self.assertNotEqual(fresh_data["market_quotes"][0]["quote_at"], fresh_data["quotes"][0]["quote_at"])
        self.assertEqual(float(stale_data["market_quotes"][0]["price"]), 10.02)
        self.assertTrue(stale_data["market_quotes"][0]["fresh"])
        self.assertEqual(float(stale["holdings"][0]["price"]), 10)

    def test_live_default_is_unchanged_and_returning_from_cases_keeps_revision_order(self):
        raw, moment = fixture.presentation_snapshot(self.raw, {"case": "live", "generation": 0})
        self.assertIs(raw, self.raw)
        self.assertIsNone(moment)
        case, _ = fixture.presentation_snapshot(self.raw, {"case": "gold", "generation": 1})
        live, moment = fixture.presentation_snapshot(self.raw, {"case": "live", "generation": 2})
        self.assertGreater(int(live["revision"]), int(case["revision"]))
        self.assertIsNone(moment)
        self.assertEqual({k:v for k,v in live.items() if k != "revision"},
                         {k:v for k,v in self.raw.items() if k != "revision"})

    def test_original_asset_cases_pass_native_saved_fields_through_real_projection(self):
        cases = (("original-chi", "sz159915", "chi_weekly"),
                 ("original-bank", "sh512800", "bank_daily"),
                 ("original-gold", "sh518880", "defense_daily"),
                 ("original-bond", "sh511010", "defense_daily"))
        for name, symbol, kind in cases:
            with self.subTest(case=name):
                _, account = self.view(name)
                asset = next(row for row in account["signal"]["rationale"]["assets"] if row["symbol"] == symbol)
                gate = asset["original_gate"]
                self.assertEqual(gate["contract_version"], "d0-original-gate-v1")
                self.assertEqual(gate["source"], "saved_signal")
                self.assertEqual(gate["kind"], kind)
                self.assertEqual(gate["timing"]["status"], "confirmed")
                self.assertEqual(gate["timing"]["confirmed_day"], account["signal"]["confirmed_day"])
                self.assertTrue(gate["state"]["ready"])
                self.assertTrue(gate["state"]["long"])
                self.assertEqual(float(account["signal"]["weights"][symbol]), 1)
                self.assertEqual(account["holdings"][0]["symbol"], symbol)
                if kind == "chi_weekly":
                    self.assertEqual(gate["timing"]["period_end"], "2026-10-16")
                    self.assertEqual(gate["metrics"]["k"], 68)
                elif kind == "bank_daily":
                    self.assertEqual(gate["timing"]["state_day"], "2026-10-21")
                    self.assertEqual(gate["metrics"]["k"], 23)
                else:
                    self.assertEqual(gate["metrics"]["ma_window"], 120 if symbol == "sh518880" else 60)
                    self.assertEqual(gate["metrics"]["value"], 11)

    def test_missing_original_fields_do_not_infer_original_gate_from_positive_weight(self):
        _, account = self.view("original-missing")
        self.assertEqual(float(account["signal"]["weights"]["sh511010"]), 1)
        for asset in account["signal"]["rationale"]["assets"]:
            gate = asset["original_gate"]
            self.assertEqual(gate["timing"]["status"], "unknown")
            self.assertIsNone(gate["state"]["ready"])
            self.assertIsNone(gate["state"]["long"])
            self.assertTrue(all(value is None for value in gate["metrics"].values()))

    def test_future_original_dates_do_not_expose_unconfirmed_indicators(self):
        _, account = self.view("original-future")
        for asset in account["signal"]["rationale"]["assets"]:
            gate = asset["original_gate"]
            self.assertEqual(gate["timing"]["status"], "invalid")
            self.assertTrue(all(value is None for value in gate["metrics"].values()))
            for key in ("ready", "long", "entry", "next_risk"):
                if key in gate["state"]:
                    self.assertIsNone(gate["state"][key])

    def test_bank_hold_is_distinct_from_new_entry_and_negative_trix_keeps_units(self):
        _, account = self.view("bank-hold")
        bank = next(a for a in account["signal"]["rationale"]["assets"] if a["symbol"] == "sh512800")
        state = bank["original_gate"]["state"]
        self.assertFalse(state["entry"])
        self.assertFalse(state["positive"])
        self.assertTrue(state["long"])
        self.assertEqual(state["next_risk"], 1)
        self.assertEqual(state["holding_days"], 4)
        self.assertEqual(bank["target_weight"], 1)
        _, account = self.view("negative-trix")
        chi = account["signal"]["rationale"]["assets"][0]["original_gate"]
        self.assertEqual(chi["timing"]["status"], "confirmed")
        self.assertEqual(chi["metrics"]["trix_pct"], -.125)
        self.assertEqual(chi["metrics"]["signal_pct"], -.25)
        self.assertTrue(chi["state"]["long"])

    def test_nonfinite_original_metrics_are_null_after_real_projection(self):
        _, account = self.view("nonfinite")
        for asset in account["signal"]["rationale"]["assets"]:
            gate = asset["original_gate"]
            for key in ("k", "d", "trix_pct", "signal_pct", "weekly_close", "weekly_ma", "market_close",
                        "market_ma", "ma", "value", "momentum20"):
                if key in gate["metrics"]:
                    self.assertIsNone(gate["metrics"][key])

    def history_snapshot(self, name, generation=1, elapsed=0, quote_elapsed=0):
        result, _ = fixture.presentation_snapshot(self.raw, dict(case=name, generation=generation,
            elapsed=elapsed, quote_elapsed=quote_elapsed))
        json.dumps(result, allow_nan=False)
        self.assertEqual(self.raw, self.before)
        self.assertEqual(self.ledger.snapshot(), self.before)
        return result

    def test_history_asset_cases_are_bound_to_the_saved_signal_and_have_bounded_dates(self):
        for name, selected in zip(("line-chi", "line-bank", "line-gold", "line-bond"), fixture.SYMBOLS):
            with self.subTest(case=name):
                raw = self.history_snapshot(name)
                signal = raw["signal"]
                self.assertEqual(signal["weights"][selected], 1)
                self.assertEqual(next(p["symbol"] for p in raw["positions"] if p["qty"]), selected)
                self.assertEqual(set(raw["indicator_histories"]), set(fixture.SYMBOLS))
                for history in raw["indicator_histories"].values():
                    self.assertEqual(history["contract_version"], "d0-indicator-history-v1")
                    self.assertEqual(history["source"], "confirmed_input_history")
                    self.assertEqual(history["signal_key"], signal["id"])
                    self.assertEqual(history["confirmed_day"], signal["confirmed_day"])
                    self.assertEqual(history["status"], "available")
                    self.assertIsNone(history["reason"])
                    for chart in history["charts"]:
                        dates = [p["date"] for p in chart["points"]]
                        self.assertEqual(dates, sorted(set(dates)))
                        self.assertLessEqual(len(dates), 104 if chart["frequency"] == "weekly" else 120)
                        self.assertTrue(all(p["date"] == p["available_on"] <= signal["confirmed_day"] for p in chart["points"]))
                        if chart["frequency"] == "weekly":
                            self.assertTrue(all(p["period_end"] <= p["available_on"] for p in chart["points"]))

    def test_every_history_endpoint_matches_its_saved_original_or_dynamic_value(self):
        for name in ("line-chi", "line-bank", "line-gold", "line-bond", "negative-trix", "bank-hold", "history-range"):
            with self.subTest(case=name):
                raw = self.history_snapshot(name)
                signal = raw["signal"]; features = signal["features"]
                for symbol, history in raw["indicator_histories"].items():
                    expected = {"momentum": {"m20": signal["dynamic"][symbol]["momentum20"],
                                             "m60": signal["dynamic"][symbol]["momentum60"]},
                                "volatility": {"vol": signal["dynamic"][symbol]["volatility20"]}}
                    if symbol == "sz159915":
                        expected.update(skdj={k: features["chi_weekly"][k] for k in ("k", "d")},
                            trix={k: features["chi_weekly"][k] for k in ("trix", "signal")},
                            trend={"value": features["chi_market"]["close"], "ma": features["chi_market"]["ma"]})
                    elif symbol == "sh512800":
                        expected["skdj"] = {k: features["bank"][k] for k in ("k", "d")}
                    else:
                        key = "gold" if symbol == "sh518880" else "bond"
                        expected["trend"] = {k: features[key][k] for k in ("value", "ma")}
                    self.assertEqual({c["id"] for c in history["charts"]}, set(expected))
                    for chart in history["charts"]:
                        self.assertEqual(chart["points"][-1]["values"], expected[chart["id"]])
                        if chart["frequency"] == "daily":
                            self.assertEqual(chart["points"][-1]["date"], signal["confirmed_day"])
                        else:
                            key = "chi_market" if chart["id"] == "trend" else "chi_weekly"
                            self.assertEqual(chart["points"][-1]["date"], features[key]["available"])
                            self.assertEqual(chart["points"][-1]["period_end"], features[key]["week_end"])
                chi_trend = next(c for c in raw["indicator_histories"]["sz159915"]["charts"] if c["id"] == "trend")
                self.assertNotEqual(chi_trend["points"][-1]["values"]["ma"], features["chi_weekly"]["ma"])

    def test_history_dates_are_not_equally_spaced_and_gaps_are_explicit(self):
        raw = self.history_snapshot("history-gap")
        for history in raw["indicator_histories"].values():
            for chart in history["charts"]:
                points = chart["points"]
                dates = [datetime.fromisoformat(p["date"]) for p in points]
                self.assertGreater(len({(b - a).days for a, b in zip(dates, dates[1:])}), 1)
                self.assertIn(None, points[1]["values"].values())
                self.assertTrue(points[3]["break_before"])
                self.assertTrue(all(value is not None for value in points[-1]["values"].values()))
        skdj = raw["indicator_histories"]["sz159915"]["charts"][0]
        self.assertIsNone(skdj["points"][1]["values"]["k"])
        self.assertIsNotNone(skdj["points"][1]["values"]["d"])

    def test_single_missing_future_and_wrong_identity_are_separate_history_cases(self):
        single = self.history_snapshot("single-point")
        self.assertTrue(all(len(c["points"]) == 1 for h in single["indicator_histories"].values() for c in h["charts"]))
        missing = self.history_snapshot("no-history")
        self.assertEqual(missing["indicator_histories"], {})
        self.assertIn("features", missing["signal"])
        future = self.history_snapshot("future-history")
        self.assertTrue(all(c["points"][-1]["date"] > future["signal"]["confirmed_day"]
                            for h in future["indicator_histories"].values() for c in h["charts"]))
        mismatch = self.history_snapshot("identity-mismatch")
        self.assertTrue(all(h["signal_key"] != mismatch["signal"]["id"] for h in mismatch["indicator_histories"].values()))
        self.assertTrue(all(h["confirmed_day"] == mismatch["signal"]["confirmed_day"]
                            for h in mismatch["indicator_histories"].values()))

    def test_negative_trix_history_keeps_percentage_points_and_polling_keeps_history_identity(self):
        raw = self.history_snapshot("negative-trix")
        chart = next(c for c in raw["indicator_histories"]["sz159915"]["charts"] if c["id"] == "trix")
        self.assertEqual(chart["unit"], "percent_points")
        self.assertEqual(chart["points"][-1]["values"], {"trix": -.125, "signal": -.25})
        self.assertLess(min(p["values"]["trix"] for p in chart["points"]), 0)
        self.assertGreater(max(p["values"]["trix"] for p in chart["points"]), 0)
        fresh = self.history_snapshot("line-chi", generation=1)
        stale = self.history_snapshot("line-chi", generation=2, elapsed=70)
        recovered = self.history_snapshot("line-chi", generation=3, elapsed=72, quote_elapsed=72)
        self.assertEqual(fresh["indicator_histories"], stale["indicator_histories"])
        self.assertEqual(stale["indicator_histories"], recovered["indicator_histories"])
        self.assertLess(int(fresh["revision"]), int(stale["revision"]))
        self.assertLess(int(stale["revision"]), int(recovered["revision"]))
        fresh["indicator_histories"]["sz159915"]["charts"][0]["points"][-1]["values"]["k"] = 0
        self.assertEqual(self.history_snapshot("line-chi")["indicator_histories"], recovered["indicator_histories"])

    def test_history_cases_pass_real_adapter_projection_with_explicit_unavailable_states(self):
        for name in ("line-chi", "line-bank", "line-gold", "line-bond", "negative-trix", "history-gap", "single-point"):
            with self.subTest(case=name):
                raw = self.history_snapshot(name)
                _, account = self.view(name)
                for asset in account["signal"]["rationale"]["assets"]:
                    self.assertEqual(asset["indicator_history"], raw["indicator_histories"][asset["symbol"]])
        for name, status, reason in (("no-history", "unavailable", "cache_unavailable"),
                                     ("future-history", "invalid", "invalid_history"),
                                     ("identity-mismatch", "invalid", "signal_mismatch")):
            with self.subTest(case=name):
                _, account = self.view(name)
                for asset in account["signal"]["rationale"]["assets"]:
                    history = asset["indicator_history"]
                    self.assertEqual(history["status"], status)
                    self.assertEqual(history["reason"], reason)
                    self.assertEqual(history["charts"], [])
                    self.assertEqual(history["signal_key"], account["signal"]["id"])

    def test_history_range_reaches_limits_and_keeps_all_endpoint_values(self):
        raw = self.history_snapshot("history-range")
        _, account = self.view("history-range")
        for asset in account["signal"]["rationale"]["assets"]:
            history = asset["indicator_history"]
            self.assertEqual(history, raw["indicator_histories"][asset["symbol"]])
            for chart in history["charts"]:
                self.assertEqual(len(chart["points"]), 104 if chart["frequency"] == "weekly" else 120)
                dates = [p["date"] for p in chart["points"]]
                self.assertEqual(dates, sorted(set(dates)))
        raw_again = self.history_snapshot("history-range", generation=4, elapsed=6, quote_elapsed=6)
        self.assertEqual(raw["indicator_histories"], raw_again["indicator_histories"])

    def test_nonfinite_history_values_become_null_without_changing_saved_raw_inputs(self):
        raw = self.history_snapshot("nonfinite")
        _, account = self.view("nonfinite")
        for asset in account["signal"]["rationale"]["assets"]:
            history = asset["indicator_history"]
            self.assertEqual(history["status"], "available")
            self.assertTrue(all(value is None for chart in history["charts"] for value in chart["points"][-1]["values"].values()))
        self.assertEqual(raw["indicator_histories"]["sz159915"]["charts"][0]["points"][-1]["values"]["k"], "NaN")


if __name__ == "__main__":
    unittest.main()
