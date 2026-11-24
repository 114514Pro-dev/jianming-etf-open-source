"""WeChat subscription endpoints with private paper ledgers and no live sender."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
from realtime_paper_engine import PaperLedger
from realtime_paper_service import PaperService, PaperServiceBackupActive
from server import create_app, hash_password
from test_d0_comparison_api import request, SyntheticRuntime

ENDPOINT = "/api/realtime-paper/wechat"
WW = "D0I-BOND-WW"


class WechatApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "Synthetic-WeChat-API-test-only"
        cls.encoded = hash_password(cls.password)

    async def asyncSetUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=os.getenv("ETF_TEST_TMPDIR"))))
        self.services = {}
        for strategy, folder in (("D0", "realtime-paper"), (WW, "realtime-paper-ww")):
            ledger = PaperLedger(home / "web" / folder, strategy=strategy)
            service = PaperService(home, ledger=ledger, strategy=strategy,
                                   source=SimpleNamespace(strategy=strategy), start_worker=False)
            self.services[strategy] = service
            stack.callback(service.close)
        stack.enter_context(patch.dict(os.environ, {"ETF_WEB_PASSWORD_HASH": self.encoded,
                             "ETF_WEB_TRUSTED_HOSTS": "testserver"}))
        stack.enter_context(patch("server.Runtime", SyntheticRuntime))
        stack.enter_context(patch("server.shutdown_runtime", new_callable=AsyncMock))
        for target in ("realtime_paper_comparison.D0ComparisonService",
                       "account_benchmark_service.AccountBenchmarkService",
                       "market_index_service.MarketIndexBenchmarkService",
                       "company_research.service.ResearchService",
                       "sector_research.research_service.ResearchService"):
            stack.enter_context(patch(target, return_value=None))
        self.dispatcher = SimpleNamespace(configured=True, start=lambda: None)

        def wechat_factory(services):
            self.assertEqual(list(services), list(self.services.values()))
            return self.dispatcher

        self.app = create_app(home, paper_factory=lambda _: self.services["D0"],
                              ww_paper_factory=lambda _: self.services[WW], wechat_factory=wechat_factory)
        await self.enterAsyncContext(self.app.router.lifespan_context(self.app))
        status, headers, body = await request(self.app, "/api/login", method="POST",
                                             data={"password": self.password})
        self.assertEqual(status, 200)
        self.cookie = headers["set-cookie"].split(";", 1)[0]
        self.csrf = body["csrf"]

    async def call(self, *, strategy="D0", suffix="", body=None, csrf=True):
        return await request(self.app, ENDPOINT + suffix, query_string="strategy=" + strategy,
                             method="GET" if body is None else "POST", cookie=self.cookie,
                             csrf=self.csrf if csrf else None, data=body)

    def create(self, strategy="D0"):
        ledger = self.services[strategy].ledger
        account = ledger.create("100000")["account"]
        return {"account_id": account["id"], "account_created_at": account["created_at"]}

    async def test_subscription_binds_to_current_strategy_and_creation(self):
        status, _, empty = await self.call(strategy=WW)
        self.assertEqual((status, empty["account_id"], empty["last_delivery"]), (200, None, None))
        d0, ww = self.create(), self.create(WW)
        prefs = {"enabled": True, "orders_enabled": True}
        self.assertEqual((await self.call(strategy=WW, body={**d0, **prefs}))[0], 409)
        self.assertEqual((await self.call(strategy=WW, body={**ww, **prefs, "account_created_at": "old"}))[0], 409)
        status, _, saved = await self.call(strategy=WW, body={**ww, **prefs})
        self.assertEqual(status, 200)
        self.assertEqual(saved, {**ww, **prefs, "contract_version": "paper-wechat-v1",
                                 "configured": True, "strategy": WW, "last_delivery": None})
        self.assertFalse((await self.call())[2]["enabled"])
        self.assertIn(self.dispatcher, [v[1] for v in self.app.state.runtime.dependencies])

    async def test_requires_login_csrf_and_exact_request_fields(self):
        binding = self.create()
        self.assertEqual((await request(self.app, ENDPOINT))[0], 401)
        body = {**binding, "enabled": True, "orders_enabled": False}
        for suffix, value in (("", body), ("/test", binding)):
            self.assertEqual((await self.call(suffix=suffix, body=value, csrf=False))[0], 403)
        for extra in ({"enabled": 1}, {"token": "never-accept-client-secrets"}, {"orders_enabled": "true"}):
            self.assertEqual((await self.call(body={**body, **extra}))[0], 400)
        self.assertIsNone((await self.call())[2]["last_delivery"])
        self.assertFalse((await self.call())[2]["enabled"])

    async def test_unconfigured_disables_existing_subscription_and_disallows_outbound_test(self):
        bound = self.create()
        self.assertEqual((await self.call(body={**bound, "enabled": True, "orders_enabled": False}))[0], 200)
        self.dispatcher.configured = False
        self.assertEqual((await self.call(suffix="/test", body=bound))[0], 503)
        self.assertEqual((await self.call(body={**bound, "enabled": True, "orders_enabled": False}))[0], 503)
        status, _, result = await self.call(body={**bound, "enabled": False, "orders_enabled": False})
        self.assertEqual((status, result["enabled"], result["configured"], result["last_delivery"]),
                         (200, False, False, None))

    async def test_test_message_is_explicit_limited_and_independent_of_subscription(self):
        bound = self.create()
        status, _, result = await self.call(suffix="/test", body=bound)
        self.assertEqual((status, result["enabled"], result["last_delivery"]["kind"]), (200, False, "test"))
        status, _, error = await self.call(suffix="/test", body=bound)
        self.assertEqual((status, error["code"]), (429, "NOTIFICATION_RATE_LIMIT"))

    async def test_notification_writes_respect_backup_and_shutdown_admission(self):
        bound = self.create()
        service = self.services["D0"]
        with service.backup_guard():
            with self.assertRaises(PaperServiceBackupActive):
                service.write_notification(service.ledger.notifications.queue_test, **bound)
        service.request_stop()
        self.assertEqual((await self.call(suffix="/test", body=bound))[0], 503)
        self.assertIsNone(service.ledger.notifications.settings()["last_delivery"])
