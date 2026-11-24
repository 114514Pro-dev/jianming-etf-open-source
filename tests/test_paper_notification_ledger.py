"""Exercise notification subscriptions and delivery recovery on real, isolated SQLite ledgers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
from realtime_paper_engine import PaperLedger
from realtime_paper_notifications import NotificationError


CN = timezone(timedelta(hours=8))
BANK, BOND = "sh512800", "sh511010"


class NotificationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 11, 2, 10, tzinfo=CN)
        self.ledger = self.open()
        self.store = self.ledger.notifications
        account = self.ledger.create("100000")["account"]
        self.binding = (account["id"], account["created_at"])
        self.ledger.set_running(True)

    def open(self, strategy="D0"):
        return PaperLedger(Path(self.temp.name) / strategy, now=lambda: self.now, strategy=strategy)

    def signal(self, key, weights, day=None):
        day = day or self.now.date()
        at = min(self.now, datetime.combine(day, time(16, 10), CN))
        eligible = datetime.combine(self.ledger.calendar.next_session(day), time(9, 30), CN)
        return self.ledger.set_signal(dict(id=key, strategy="D0", valid=True, day=day.isoformat(),
            reason="合成信号", market_hash="fixture", spec_hash="fixture", signal_at=at.isoformat(),
            received_at=at.isoformat(), data_cutoff=at.isoformat(), eligible_at=eligible.isoformat(),
            execution_day=eligible.date().isoformat(), weights=weights))

    def quote(self, **overrides):
        at = self.now.isoformat()
        row = dict(symbol=BANK, quote_at=at, price=1, previous_close=1, volume_lots=100,
                   amount_cny=10000, status="normal")
        self.ledger.ingest_batch(dict(source="fixture", received_at=at, quotes={BANK: {**row, **overrides}}))

    def order(self, key, qty=100):
        return self.ledger.submit(BANK, "buy", qty, "1.000", signal_id="friday", client_order_id=key)

    def test_one_consolidated_change_and_restart_no_replay(self):
        self.signal("prior", {BANK: "0.25"})
        self.store.save_settings(*self.binding, True, False)
        self.signal("different-id-same", {BANK: "0.25000", BOND: "0"})
        self.assertIsNone(self.store.claim())
        self.signal("rotate", {BOND: "0.8"})
        self.signal("rotate", {BOND: "0.8"})
        with ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(lambda _: self.store.claim(), range(2)))
        (job,) = [j for j in claims if j]
        for text in ("银行ETF 512800　25% → 0%", "国债ETF 511010　0% → 80%", "现金　75% → 20%",
                     "本次目标组合：国债ETF 511010 80%、现金 20%", "2026-11-02", "2026-11-03", "合成信号"):
            self.assertIn(text, job["content"])
        self.store.finish(job["id"], job["lease"], "accepted", receipt="provider-receipt")
        self.ledger = self.open()
        self.signal("rotate", {BOND: "0.8"})
        self.assertIsNone(self.ledger.notifications.claim())
        self.assertEqual(self.ledger.notifications.settings()["last_delivery"]["status"], "accepted")

    def test_first_signal_sets_baseline_and_resume_skips_older_close(self):
        self.store.save_settings(*self.binding, True, False)
        self.signal("baseline", {BANK: 1})
        self.assertIsNone(self.store.claim())
        self.ledger.set_running(False)
        self.signal("paused", {BOND: 1})
        self.now += timedelta(days=1)
        self.ledger.set_running(True)
        self.signal("old-after-resume", {BANK: 1}, self.now.date() - timedelta(days=1))
        self.assertIsNone(self.store.claim())
        self.signal("fresh", {BOND: 1})
        self.assertEqual(self.store.claim()["kind"], "signal")

    def test_only_subscribed_submissions_queue_no_rejected_or_duplicate_order(self):
        self.store.save_settings(*self.binding, True, False)
        self.signal("friday", {BANK: 1}, self.now.date() - timedelta(days=3))
        self.quote()
        self.assertEqual(self.order("muted")["orders"][-1]["status"], "pending")
        self.store.save_settings(*self.binding, True, True)
        self.assertEqual(self.order("invalid", 1)["orders"][-1]["status"], "rejected")
        self.assertIsNone(self.store.claim())
        order = self.order("first")
        self.assertEqual(order["orders"][-1]["status"], "pending")
        self.assertEqual(self.order("first")["order_id"], order["order_id"])
        item = self.store.claim()
        self.assertIn("买入 银行ETF 512800　100 份", item["content"])
        self.assertIn("1.000 元", item["content"])
        self.store.finish(item["id"], item["lease"], "accepted")
        self.assertIsNone(self.store.claim())
        self.order("mute-next")
        self.store.save_settings(*self.binding, True, False)
        self.store.save_settings(*self.binding, True, True)
        self.assertIsNone(self.store.claim())

    def test_account_instance_scope_and_explicit_test_before_subscription(self):
        ww = self.open("D0I-BOND-WW").notifications
        self.assertIsNone(ww.settings()["account_id"])
        with self.assertRaises(NotificationError):
            ww.queue_test(*self.binding)
        with self.assertRaises(NotificationError):
            self.store.save_settings(self.binding[0], "old-date", True, False)
        first = self.store.queue_test(*self.binding)
        self.assertEqual(first["last_delivery"]["kind"], "test")
        self.assertFalse(first["enabled"])
        with self.assertRaises(NotificationError) as error:
            self.open().notifications.queue_test(*self.binding)
        self.assertEqual(error.exception.status_code, 429)
        self.assertIsNone(ww.claim())
        self.assertEqual(self.store.claim()["kind"], "test")

    def test_uncertain_request_never_retried_and_known_failure_retries_once(self):
        self.store.queue_test(*self.binding)
        first = self.store.claim()
        self.store.finish(first["id"], first["lease"], "retry", delay=5, reason="connect_failed")
        self.assertIsNone(self.store.claim())
        self.now += timedelta(seconds=6)
        retried = self.store.claim()
        self.assertEqual((retried["id"], retried["attempts"]), (first["id"], 2))
        self.store.finish(first["id"], first["lease"], "accepted")
        self.assertEqual(self.store.settings()["last_delivery"]["status"], "sending")
        self.now += timedelta(minutes=2)
        self.assertIsNone(self.open().notifications.claim())
        self.assertEqual(self.store.settings()["last_delivery"]["status"], "uncertain")

    def test_rollback_includes_outbox_and_preserves_old_signal(self):
        self.store.save_settings(*self.binding, True, False)
        self.signal("baseline", {BANK: 1})
        with patch("realtime_paper_engine.update_and_read_history", side_effect=RuntimeError("simulated failure")):
            with self.assertRaises(RuntimeError):
                self.signal("change", {BOND: 1})
        self.assertEqual(self.ledger.snapshot()["signal"]["id"], "baseline")
        self.assertIsNone(self.store.claim())
        self.signal("change", {BOND: 1})
        self.assertEqual(self.store.claim()["kind"], "signal")

    def test_supersession_pause_racing_retry_and_expired_signal(self):
        self.store.save_settings(*self.binding, True, True)
        self.signal("baseline", {BANK: 1})
        self.signal("change", {BOND: 1})
        self.signal("revised", {BOND: "0.5"})
        current = self.store.claim()
        self.assertIn("100% → 50%", current["content"])
        self.ledger.set_running(False)
        self.ledger.set_running(True)
        self.store.finish(current["id"], current["lease"], "retry", reason="connect_failed")
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.settings()["last_delivery"]["reason"], "account_paused")
        self.signal("dated", {BANK: 1})
        self.now += timedelta(days=3)
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.settings()["last_delivery"]["reason"], "notification_expired")

    def test_protective_pause_and_order_expiry_cancel_pending_orders(self):
        self.store.save_settings(*self.binding, True, True)
        self.signal("friday", {BANK: 1}, self.now.date() - timedelta(days=3))
        self.quote()
        self.order("expiring")
        self.now = self.now.replace(hour=14, minute=57)
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.settings()["last_delivery"]["reason"], "notification_expired")
        self.now += timedelta(days=1)
        self.now = self.now.replace(hour=10, minute=0)
        self.quote()
        self.order("protective")
        self.now += timedelta(seconds=1)
        self.quote(previous_close="1.001", volume_lots=101, amount_cny=10100)
        self.assertFalse(self.ledger.snapshot()["account"]["running"])
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.settings()["last_delivery"]["reason"], "account_paused")


if __name__ == "__main__":
    unittest.main()
