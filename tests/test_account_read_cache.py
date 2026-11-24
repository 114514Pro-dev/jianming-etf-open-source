"""Account reads stay available during serialized work, using synthetic data only."""
from pathlib import Path
import queue
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
from server import Runtime


GROUPS = ("original", "top5", "seven", "nasdaq", "hangseng", "hangtech")


class SyntheticBridge:
    def __init__(self):
        self.rows = {group: [{"id": group + "_synthetic", "day": "2026-11-10"}]
                     for group in GROUPS}
        self.failed_groups = set()
        self.failed_details = set()
        self.calls = []
        self.detail_hook = None

    def catalog(self):
        return {"groups": list(GROUPS)}

    def overview(self):
        return {"synthetic": True}

    def overseas_overview(self):
        return {"synthetic": True}

    def accounts(self, group):
        self.calls.append(("accounts", group))
        if group in self.failed_groups:
            raise ValueError("synthetic unreadable list")
        return self.rows[group]

    def account(self, group, identity):
        self.calls.append(("account", group, identity))
        if self.detail_hook:
            self.detail_hook(group, identity)
        if identity in self.failed_details:
            raise ValueError("synthetic unreadable detail")
        row = next(row for row in self.rows[group] if row["id"] == identity)
        return {"group": group, "id": identity, "summary": dict(row),
                "positions": [{"symbol": "synthetic", "qty": 1}],
                "curve": [], "events": []}


def runtime_shell():
    """Use the actual cache/query/worker methods without services or a live home."""
    runtime = Runtime.__new__(Runtime)
    runtime.home = None
    runtime.cache = {}
    runtime.cache_lock = threading.RLock()
    runtime.revision_number = 0
    runtime.tasks = queue.Queue(maxsize=64)
    runtime.halt = threading.Event()
    runtime.ready = threading.Event()
    runtime.init_error = None
    runtime.stops = {}
    runtime.update = Mock()
    runtime.record_automation = Mock()
    return runtime


class AccountReadCacheTests(unittest.TestCase):
    def setUp(self):
        self.runtime = runtime_shell()
        self.bridge = SyntheticBridge()

    def test_startup_warms_unvisited_details_for_every_group(self):
        self.runtime.refresh_cache(self.bridge)
        for group in GROUPS:
            identity = self.bridge.rows[group][0]["id"]
            detail = self.runtime.query("account", group, identity)
            self.assertEqual(detail["summary"]["day"], "2026-11-10")
            self.assertEqual(detail["group"], group)
        self.assertTrue(self.runtime.tasks.empty(), "detail GET must not enqueue work")

    def test_first_detail_read_succeeds_while_real_worker_is_busy(self):
        entered, release = threading.Event(), threading.Event()

        def long_job(*_args):
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release synthetic job")
            return {"synthetic": True}

        self.runtime.execute = long_job
        self.runtime.job = lambda _identity: {"action": "compare", "params": {}}
        self.runtime.stops["synthetic-job"] = threading.Event()
        self.runtime.tasks.put(("job", "synthetic-job"))
        thread = threading.Thread(target=self.runtime.worker, daemon=True)
        with patch("web_bridge.Bridge", return_value=self.bridge), \
                patch("socket.create_connection", side_effect=AssertionError("No network")):
            thread.start()
            try:
                self.assertTrue(self.runtime.ready.wait(3))
                self.assertTrue(entered.wait(3))
                # Without prewarming this enters Future.result(timeout=12).
                # Fail immediately instead of making the regression test sleep.
                with patch("server.concurrent.futures.Future", side_effect=AssertionError("queued read")):
                    detail = self.runtime.query("account", "seven", "seven_synthetic")
                    rows = self.runtime.query("accounts", "seven")
                self.assertEqual(detail["summary"]["day"], rows[0]["day"])
                self.assertFalse(release.is_set(), "read must finish before the long job")
            finally:
                self.runtime.halt.set()
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_create_delete_restore_refresh_detail_membership(self):
        self.runtime.refresh_cache(self.bridge)
        self.bridge.rows["seven"].append({"id": "new_synthetic", "day": "2026-11-11"})
        self.runtime.refresh_cache(self.bridge)
        self.assertEqual(self.runtime.query("account", "seven", "new_synthetic")["id"], "new_synthetic")
        removed = self.bridge.rows["seven"].pop(0)
        self.runtime.refresh_cache(self.bridge)
        self.assertNotIn(("account", "seven", removed["id"]), self.runtime.cache)
        self.assertEqual(len(self.runtime.query("accounts", "seven")), 1)
        self.bridge.rows["seven"].append(removed)
        self.runtime.refresh_cache(self.bridge)
        self.assertEqual(self.runtime.query("account", "seven", removed["id"])["summary"], removed)

    def test_unreadable_group_invalidates_only_its_old_details(self):
        self.runtime.refresh_cache(self.bridge)
        self.bridge.failed_groups.add("seven")
        with self.assertLogs("etfweb", level="ERROR"):
            self.runtime.refresh_cache(self.bridge)
        self.assertNotIn(("accounts", "seven"), self.runtime.cache)
        self.assertNotIn(("account", "seven", "seven_synthetic"), self.runtime.cache)
        self.assertIn(("account", "original", "original_synthetic"), self.runtime.cache)

    def test_one_bad_detail_does_not_block_other_accounts_and_can_recover(self):
        self.runtime.refresh_cache(self.bridge)
        self.bridge.failed_details.add("seven_synthetic")
        self.bridge.rows["seven"].append({"id": "healthy_synthetic", "day": "2026-11-11"})
        with self.assertLogs("etfweb", level="ERROR"):
            self.runtime.refresh_cache(self.bridge)
        self.assertNotIn(("account", "seven", "seven_synthetic"), self.runtime.cache)
        self.assertIn(("account", "seven", "healthy_synthetic"), self.runtime.cache)
        self.bridge.failed_details.clear()
        self.runtime.refresh_cache(self.bridge)
        self.assertEqual(self.runtime.query("account", "seven", "seven_synthetic")["id"], "seven_synthetic")

    def test_refresh_publishes_list_and_details_as_one_generation(self):
        self.runtime.refresh_cache(self.bridge)
        self.bridge.rows["seven"][0]["day"] = "2026-11-11"
        before = dict(self.runtime.cache)
        revision = self.runtime.revision_number
        observed = []

        def during_refresh(group, identity):
            self.assertEqual(self.runtime.cache, before)
            self.assertEqual(self.runtime.revision_number, revision)
            observed.append(self.runtime.query("account", group, identity)["summary"]["day"])

        self.bridge.detail_hook = during_refresh
        self.runtime.refresh_cache(self.bridge)
        self.assertEqual(observed, ["2026-11-10"] * len(GROUPS))
        detail = self.runtime.query("account", "seven", "seven_synthetic")
        self.assertEqual(detail["summary"]["day"], "2026-11-11")
        self.assertEqual(detail["summary"], self.runtime.query("accounts", "seven")[0])
        self.assertEqual(self.runtime.revision_number, revision + 1)

    def test_quote_only_refresh_does_not_read_or_replace_account_snapshots(self):
        self.runtime.refresh_cache(self.bridge)
        before = dict(self.runtime.cache)
        self.bridge.calls.clear()
        self.runtime.refresh_cache(self.bridge, quotes_only=True)
        self.assertEqual(self.bridge.calls, [])
        for key, value in before.items():
            if key[0] in {"account", "accounts"}:
                self.assertEqual(self.runtime.cache[key], value)

    def test_response_mutation_cannot_change_cached_or_bridge_state(self):
        self.runtime.refresh_cache(self.bridge)
        detail = self.runtime.query("account", "seven", "seven_synthetic")
        detail["positions"][0]["qty"] = 999
        detail["summary"]["day"] = "bad"
        repeated = self.runtime.query("account", "seven", "seven_synthetic")
        self.assertEqual(repeated["positions"][0]["qty"], 1)
        self.assertEqual(repeated["summary"]["day"], "2026-11-10")
        self.assertEqual(self.bridge.rows["seven"][0]["day"], "2026-11-10")


if __name__ == "__main__":
    unittest.main()
