"""Exercise the outbound worker with synthetic ledger rows and no network."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
import realtime_paper_wechat as wechat


TOKEN = "synthetic-send-only-token"
ITEM = {"id": "a", "lease": "lease-a", "attempts": 1, "title": "模拟调仓", "content": "测试详情"}


class TestPushplus(unittest.TestCase):
    def test_single_post_uses_private_wechat_text_request(self):
        with patch.object(wechat.http.client, "HTTPSConnection") as https:
            connection = https.return_value
            response = connection.getresponse.return_value
            response.status = 200
            response.read.return_value = b'{"code":200,"data":"abc-123"}'
            result = wechat._send(TOKEN, ITEM)
        self.assertEqual(result, wechat.SendResult("accepted", "provider_accepted", "abc-123"))
        self.assertEqual(https.call_args.args, ("www.pushplus.plus",))
        method, path, body, headers = connection.request.call_args.args
        self.assertEqual((method, path), ("POST", "/send"))
        self.assertEqual(json.loads(body), {"channel": "wechat", "template": "txt", "title": ITEM["title"],
                                          "content": ITEM["content"], "token": TOKEN})
        self.assertNotIn(TOKEN, str(headers))
        self.assertNotIn(TOKEN, repr(result))
        connection.close.assert_called_once()

    def test_only_retry_when_request_definitely_not_accepted(self):
        with patch.object(wechat.http.client, "HTTPSConnection") as https:
            connection = https.return_value
            connection.connect.side_effect = OSError("simulate DNS failure")
            self.assertEqual(wechat._send(TOKEN, ITEM).status, "retry")
            connection.request.assert_not_called()
            connection.connect.side_effect = None
            connection.getresponse.side_effect = TimeoutError("after submission")
            self.assertEqual(wechat._send(TOKEN, ITEM).status, "uncertain")
            connection.request.assert_called_once()

    def test_redirect_is_not_followed_and_malformed_ack_cannot_be_treated_as_success(self):
        with patch.object(wechat.http.client, "HTTPSConnection") as https:
            connection = https.return_value
            response = connection.getresponse.return_value
            response.status = 307
            response.read.return_value = b""
            self.assertEqual(wechat._send(TOKEN, ITEM).status, "failed")
            connection.request.assert_called_once()
        for status, body, expected in [
            (200, b"null", "uncertain"), (200, b"not json", "uncertain"),
            (200, b'{"code":200,"data":null}', "uncertain"),
            (200, json.dumps({"code": 200, "data": TOKEN}).encode(), "uncertain"),
            (200, json.dumps({"code": 903, "msg": TOKEN}).encode(), "failed"),
            (429, b"", "retry"), (503, b"", "uncertain"),
        ]:
            with self.subTest(status=status, expected=expected):
                result = wechat._response_result(status, body, TOKEN)
                self.assertEqual(result.status, expected)
                self.assertNotIn(TOKEN, repr(result))

    def test_secret_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("ETF_TEST_TMPDIR")) as directory:
            path = Path(directory) / "message-token"
            path.write_bytes((TOKEN + "\n").encode())
            for env, expected in [
                ({}, False), ({"PUSHPLUS_TOKEN": TOKEN}, True),
                ({"PUSHPLUS_TOKEN_FILE": str(path)}, True),
                ({"PUSHPLUS_TOKEN_FILE": str(path), "PUSHPLUS_TOKEN": TOKEN}, False),
                ({"PUSHPLUS_TOKEN_FILE": str(path.with_name("missing"))}, False),
                ({"PUSHPLUS_TOKEN_FILE": "relative.txt"}, False),
                ({"PUSHPLUS_TOKEN": "not a token"}, False),
            ]:
                with self.subTest(configured=expected), patch.dict(os.environ, env, clear=True):
                    worker = wechat.WechatDispatcher([])
                    self.assertEqual(worker.configured, expected)
                    self.assertNotIn(TOKEN, repr(worker))
            path.write_bytes(b"x" * 514)
            with patch.dict(os.environ, {"PUSHPLUS_TOKEN_FILE": str(path)}, clear=True):
                self.assertFalse(wechat.WechatDispatcher([]).configured)


class Store:
    def __init__(self, items):
        self.items = list(items)
        self.completed = []
        self.finished = threading.Event()

    def claim(self):
        return self.items.pop(0) if self.items else None

    def finish(self, *args, **kwargs):
        self.completed.append((args, kwargs))
        self.finished.set()


class Service:
    def __init__(self, items):
        self.ledger = MagicMock(notifications=Store(items))
        self.writing = False

    def write_notification(self, fn, *args, **kwargs):
        self.writing = True
        try:
            return fn(*args, **kwargs)
        finally:
            self.writing = False


class TestDispatcher(unittest.TestCase):
    def test_worker_runs_for_each_strategy_without_a_web_request(self):
        services = [Service([ITEM]), Service([dict(ITEM, id="ww")])]

        def fake_send(token, item):
            if any(service.writing for service in services):
                raise AssertionError("network IO occurred within ledger operation")
            return wechat.SendResult("accepted", "provider_accepted", "receipt-" + item["id"])

        with patch.dict(os.environ, {"PUSHPLUS_TOKEN": TOKEN}, clear=True), patch.object(wechat, "_send", fake_send):
            worker = wechat.WechatDispatcher(services)
            worker.start()
            try:
                for service in services:
                    self.assertTrue(service.ledger.notifications.finished.wait(2))
            finally:
                worker.close()
        self.assertTrue(worker.closed)
        for service in services:
            completed = service.ledger.notifications.completed
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0][0][2], "accepted")

    def test_opt_out_and_retry_budget(self):
        service = Service([dict(ITEM, attempts=2), dict(ITEM, attempts=3), ITEM])
        with patch.dict(os.environ, {}, clear=True), patch.object(wechat, "_send") as sender:
            worker = wechat.WechatDispatcher([service])
            worker.start()
            self.assertTrue(worker.closed)
            worker._dispatch_once()
            sender.assert_not_called()
        with patch.dict(os.environ, {"PUSHPLUS_TOKEN": TOKEN}, clear=True), patch.object(wechat, "_send") as sender:
            worker = wechat.WechatDispatcher([service])
            sender.side_effect = [wechat.SendResult("retry", "connect_failed"),
                                  wechat.SendResult("retry", "connect_failed"),
                                  wechat.SendResult("uncertain", "connection_interrupted")]
            for _ in range(3):
                worker._dispatch_once()
        records = service.ledger.notifications.completed
        self.assertEqual([row[0][2] for row in records], ["retry", "failed", "uncertain"])
        self.assertGreater(records[0][1]["delay"], 0)
        self.assertFalse(records[-1][1]["delay"])

    def test_worker_caps_rate_across_both_accounts(self):
        services = [Service([ITEM] * 5), Service([ITEM] * 5)]
        with patch.dict(os.environ, {"PUSHPLUS_TOKEN": TOKEN}, clear=True), patch.object(
                wechat, "_send", return_value=wechat.SendResult("accepted", "provider_accepted", "r")) as send:
            worker = wechat.WechatDispatcher(services)
            with patch.object(wechat.time, "monotonic", return_value=5):
                for _ in range(5):
                    worker._dispatch_once()
                self.assertGreaterEqual(worker._dispatch_once(), 60)
                self.assertEqual(send.call_count, 5)
            with patch.object(wechat.time, "monotonic", return_value=66):
                worker._dispatch_once()
                self.assertEqual(send.call_count, 6)

    def test_account_restriction_pauses_both_strategies(self):
        services = [Service([ITEM]), Service([ITEM])]
        with patch.dict(os.environ, {"PUSHPLUS_TOKEN": TOKEN}, clear=True), patch.object(
                wechat, "_send", return_value=wechat.SendResult("failed", "provider_restricted")) as send:
            worker = wechat.WechatDispatcher(services)
            worker._dispatch_once()
            self.assertGreater(worker._dispatch_once(), 0)
            send.assert_called_once()
            self.assertEqual(len(services[1].ledger.notifications.items), 1)
