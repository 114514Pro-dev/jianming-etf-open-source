"""Exercise a confirmed close through the observer, ledger, restart and delivery worker."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
from realtime_paper_service import PaperService
from realtime_paper_wechat import SendResult, WechatDispatcher


class WechatSignalFlowTests(unittest.TestCase):
    def test_one_rotation_after_close_survives_restart_without_browser_or_live_quotes(self):
        tz = timezone(timedelta(hours=8))
        now = datetime(2026, 11, 2, 10, tzinfo=tz)
        with tempfile.TemporaryDirectory() as home:
            source = Mock(spec=["read"])
            def open_paper():
                return PaperService(home, source=source, now=lambda: now, start_worker=False)

            def observe(paper, bank, bond):
                day = now.date().isoformat()
                next_day = (now.date() + timedelta(days=1)).isoformat()
                source.read.return_value = {
                    "source_status": "waiting", "reason": "outside_session", "batch": None,
                    "signal": {
                        "id": day, "strategy": "D0", "day": day, "valid": True,
                        "market_hash": day, "spec_hash": "synthetic", "reason": "合成行情测试",
                        "weights": {"sh512800": bank, "sh511010": bond},
                        "data_cutoff": day + "T15:00:00+08:00", "signal_at": now.isoformat(),
                        "known_at": now.isoformat(), "received_at": now.isoformat(),
                        "confirmed_day": day, "execution_day": next_day,
                        "eligible_at": next_day + "T09:30:00+08:00",
                    },
                }
                paper.poll_once()

            paper = open_paper()
            try:
                account = paper.create("100000.00")["account"]
                paper.ledger.set_running(True)
                paper.ledger.notifications.save_settings(account["id"], account["created_at"], True, False)
                now = now.replace(hour=16, minute=11)
                observe(paper, "1.0", "0")
                now += timedelta(days=1)
                observe(paper, "0.25", "0.75")
                paper.poll_once()  # Re-read the same confirmed signal before the worker starts.
            finally:
                paper.close()

            paper = open_paper()
            try:
                with patch("realtime_paper_wechat._configured_token", return_value="synthetic"), \
                     patch("realtime_paper_wechat._send", return_value=SendResult("accepted", "provider_accepted", "receipt")) as send:
                    worker = WechatDispatcher([paper])
                    worker._dispatch_once()
                    now += timedelta(days=1)
                    observe(paper, "0.2500", "0.750")
                    worker._dispatch_once()
                    send.assert_called_once()
                    item = send.call_args.args[1]
                    self.assertIn("512800", item["content"])
                    self.assertIn("511010", item["content"])
                    self.assertIn("2026-11-04", item["content"])
                    self.assertEqual(paper.ledger.notifications.settings()["last_delivery"]["status"], "accepted")
                    self.assertEqual(paper.ledger.snapshot()["orders"], [])
            finally:
                paper.close()
