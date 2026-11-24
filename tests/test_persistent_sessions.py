"""Device authentication on temporary synthetic directories only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing, ExitStack
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "production"))
from web_auth_sessions import PersistentSessions, SessionStoreUnavailable, DEVICE_TTL, RENEW_WINDOW, MAX_DEVICES
from server import create_app, hash_password


class DeviceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("ETF_TEST_TMPDIR"))
        self.home = Path(self.temp.name)
        self.now = 1800000000
        self.store = PersistentSessions(self.home, "synthetic-credential-A", clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def reopened(self, credential="synthetic-credential-A"):
        return PersistentSessions(self.home, credential, clock=lambda: self.now)

    def sql(self, command, values=()):
        with closing(sqlite3.connect(self.store.path)) as connection:
            with connection:
                return connection.execute(command, values).fetchall()

    def test_constructor_and_unknown_cookie_do_not_create_store(self):
        self.assertIsNone(self.store.lookup(secrets.token_urlsafe(32)))
        self.assertFalse(self.store.directory.exists())

    def test_only_cookie_digest_is_saved_in_private_store(self):
        token, session = self.store.issue()
        self.assertEqual(len(token), 43)
        self.assertEqual(session["expires"], self.now + DEVICE_TTL)
        self.assertNotIn(token.encode(), self.store.path.read_bytes())
        rows = self.sql("SELECT token_hash,csrf FROM devices")
        self.assertEqual(rows, [(hashlib.sha256(token.encode()).hexdigest(), session["csrf"])])

    def test_same_home_reopens_same_session_without_changing_password(self):
        token, session = self.store.issue()
        restored = self.reopened().lookup(token)
        self.assertEqual(restored["csrf"], session["csrf"])
        self.assertEqual(restored["expires"], session["expires"])
        self.assertTrue(restored["remembered"])

    def test_invalid_and_tampered_tokens_never_authorize(self):
        token, _ = self.store.issue()
        for bad in (None, 1, "", token + "x", "../" + token, "\x00" * 43, "a" * 10000,
                    ("b" if token[0] == "a" else "a") + token[1:]):
            with self.subTest(kind=type(bad).__name__):
                self.assertIsNone(self.store.lookup(bad))

    def test_expiry_boundary_cannot_be_renewed(self):
        token, session = self.store.issue()
        self.now = session["expires"] - 1
        self.assertIsNotNone(self.store.lookup(token))
        self.now += 1
        self.assertIsNone(self.store.lookup(token, renew=True))
        self.assertEqual(self.sql("SELECT count(*) FROM devices"), [(0,)])

    def test_renewal_is_bounded_to_last_thirty_days(self):
        token, session = self.store.issue()
        self.now = session["expires"] - RENEW_WINDOW - 1
        first = self.store.lookup(token, renew=True)
        self.assertFalse(first["renewed"])
        self.assertEqual(first["expires"], session["expires"])
        self.now += 1
        second = self.store.lookup(token, renew=True)
        self.assertTrue(second["renewed"])
        self.assertEqual(second["expires"], self.now + DEVICE_TTL)
        self.assertEqual(self.reopened().lookup(token)["expires"], second["expires"])
        self.assertFalse(self.store.lookup(token, renew=True)["renewed"])

    def test_logout_revocation_survives_restart_and_preserves_other_device(self):
        first, _ = self.store.issue()
        second, _ = self.store.issue()
        self.store.revoke(first)
        self.store.revoke(first)
        self.assertIsNone(self.reopened().lookup(first))
        self.assertIsNotNone(self.reopened().lookup(second))

    def test_password_change_invalidates_all_sessions_without_resurrection(self):
        old, _ = self.store.issue()
        changed = self.reopened("synthetic-credential-B")
        self.assertIsNone(changed.lookup(old))
        self.assertIsNone(self.reopened().lookup(old))

    def test_device_count_and_expired_cleanup_are_bounded(self):
        first, _ = self.store.issue()
        for _ in range(MAX_DEVICES):
            self.now += 1
            self.store.issue()
        self.assertEqual(self.sql("SELECT count(*) FROM devices"), [(MAX_DEVICES,)])
        self.assertIsNone(self.store.lookup(first))
        self.now += DEVICE_TTL
        self.store.issue()
        self.assertEqual(self.sql("SELECT count(*) FROM devices"), [(1,)])

    def test_distinct_instances_can_issue_and_revoke_concurrently(self):
        self.store.issue()  # Initialize before cross-instance concurrency.
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: self.reopened().issue(), range(12)))
            self.assertEqual(len({token for token, _ in rows}), 12)
            list(pool.map(lambda row: self.reopened().revoke(row[0]), rows))
        for token, _ in rows:
            self.assertIsNone(self.reopened().lookup(token))

    def test_concurrent_renewal_cannot_resurrect_revoked_session(self):
        token, session = self.store.issue()
        self.now = session["expires"] - 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.reopened().lookup, token, renew=True) for _ in range(8)]
            futures.append(pool.submit(self.reopened().revoke, token))
            for future in futures:
                future.result()
        self.assertIsNone(self.reopened().lookup(token))

    def test_corrupt_or_existing_empty_store_is_not_rebuilt(self):
        token, _ = self.store.issue()
        for bad in (b"not a database", b""):
            self.store.path.write_bytes(bad)
            with self.assertRaises(SessionStoreUnavailable):
                self.reopened().lookup(token)
            with self.assertRaises(SessionStoreUnavailable):
                self.reopened().issue()
            self.assertEqual(self.store.path.read_bytes(), bad)

    def test_unknown_schema_or_invalid_record_is_rejected(self):
        token, _ = self.store.issue()
        self.sql("PRAGMA user_version=9")
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)
        self.sql("PRAGMA user_version=1")
        self.sql("UPDATE devices SET expires_at='invalid'")
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)

    def test_store_size_and_record_count_limits_fail_closed(self):
        token, _ = self.store.issue()
        for n in range(MAX_DEVICES):
            self.sql("INSERT INTO devices VALUES(?,?,?,?)", (str(n), "x" * 43, self.now, self.now + 10))
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)
        with self.store.path.open("ab") as stream:
            stream.write(b"x" * (2 * 1024 * 1024))
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)

    def test_write_and_revoke_errors_do_not_report_success(self):
        token, _ = self.store.issue()
        with patch("web_auth_sessions.sqlite3.connect", side_effect=sqlite3.OperationalError("synthetic failure")):
            with self.assertRaises(SessionStoreUnavailable):
                self.store.issue()
            with self.assertRaises(SessionStoreUnavailable):
                self.store.revoke(token)
        self.assertIsNotNone(self.store.lookup(token))

    def test_non_delete_journal_and_unexpected_sidecars_are_rejected(self):
        token, _ = self.store.issue()
        sidecar = Path(str(self.store.path) + "-wal")
        sidecar.write_bytes(b"")
        sidecar.chmod(0o600)
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)
        sidecar.unlink()
        body = bytearray(self.store.path.read_bytes())
        body[18:20] = b"\x02\x02"
        self.store.path.write_bytes(body)
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)

    def test_disappearing_rollback_journal_does_not_hide_other_sidecar_errors(self):
        token, session = self.store.issue()
        original_lstat = Path.lstat
        for suffix, error in (("-journal", FileNotFoundError), ("-journal", PermissionError),
                              ("-wal", FileNotFoundError), ("-shm", FileNotFoundError)):
            with self.subTest(suffix=suffix, error=error.__name__):
                sidecar = Path(str(self.store.path) + suffix)
                sidecar.write_bytes(b"")
                sidecar.chmod(0o600)
                checked = []

                def racing_lstat(path, *args, **kwargs):
                    if path == sidecar and not checked:
                        checked.append(path)
                        if error is FileNotFoundError:
                            path.unlink()  # The existence check already passed.
                        else:
                            raise error("synthetic sidecar permission failure")
                    return original_lstat(path, *args, **kwargs)

                try:
                    with patch.object(Path, "lstat", racing_lstat):
                        if suffix == "-journal" and error is FileNotFoundError:
                            restored = self.reopened().lookup(token)
                            self.assertEqual(restored["csrf"], session["csrf"])
                            self.assertEqual(len(checked), 1)
                        else:
                            with self.assertRaises(SessionStoreUnavailable):
                                self.reopened().lookup(token)
                    if suffix != "-journal":
                        # Observing forbidden sidecars is enough to reject them;
                        # no missing-file exception may turn that into success.
                        self.assertEqual(checked, [])
                finally:
                    if sidecar.exists():
                        sidecar.unlink()
        self.assertIsNotNone(self.reopened().lookup(token))

    @unittest.skipUnless(os.name == "posix", "POSIX owner/mode checks require Linux")
    def test_private_modes_and_untrusted_permissions(self):
        token, _ = self.store.issue()
        self.assertEqual(stat.S_IMODE(self.store.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        for path, bad, good in ((self.store.path, 0o644, 0o600), (self.store.directory, 0o755, 0o700),
                                (self.home / "web", 0o777, 0o700)):
            path.chmod(bad)
            try:
                with self.assertRaises(SessionStoreUnavailable):
                    self.store.lookup(token)
            finally:
                path.chmod(good)
        with patch("web_auth_sessions.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaises(SessionStoreUnavailable):
                self.store.lookup(token)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink checks require Linux")
    def test_symlink_and_hardlink_store_are_rejected(self):
        token, _ = self.store.issue()
        original = self.store.path.with_name("retained.sqlite3")
        self.store.path.rename(original)
        self.store.path.symlink_to(original)
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)
        self.store.path.unlink()
        os.link(original, self.store.path)
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)
        self.store.path.unlink()
        original.rename(self.store.path)
        sidecar = Path(str(self.store.path) + "-journal")
        sidecar.symlink_to(self.store.path)
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)
        sidecar.unlink()
        real_directory = self.store.directory.with_name("retained-directory")
        self.store.directory.rename(real_directory)
        self.store.directory.symlink_to(real_directory, target_is_directory=True)
        with self.assertRaises(SessionStoreUnavailable):
            self.store.lookup(token)


async def request(app, path, *, method="GET", data=None, cookie=None, csrf=None, origin=None):
    body = b"" if data is None else json.dumps(data).encode()
    headers = [(b"host", b"testserver"), (b"content-length", str(len(body)).encode())]
    if data is not None:
        headers.append((b"content-type", b"application/json"))
    for name, value in (("cookie", cookie), ("x-csrf-token", csrf), ("origin", origin)):
        if value:
            headers.append((name.encode(), value.encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "https", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": headers, "client": ("127.0.0.1", 52000), "server": ("testserver", 443)}
    sent = False
    output = []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Future()

    async def send(message):
        output.append(message)

    await app(scope, receive, send)
    response = next(row for row in output if row["type"] == "http.response.start")
    payload = b"".join(row.get("body", b"") for row in output if row["type"] == "http.response.body")
    return response["status"], {key.decode().lower(): value.decode() for key, value in response["headers"]}, json.loads(payload)


class SyntheticRuntime:
    def __init__(self, home):
        self.home = home

    def status(self):
        return {"ready": True}

    def query(self, *values):
        return {"synthetic": True}

    def change_settings(self, value):
        return {"synthetic": True}


class DeviceAuthRouteTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "Synthetic-device-only-2026"
        cls.encoded = hash_password(cls.password)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("ETF_TEST_TMPDIR"))
        self.home = Path(self.temp.name)
        self.home.joinpath("web").mkdir(mode=0o700)
        self.auth = self.home / "web" / "auth.json"
        self.auth.write_text(json.dumps({"password_hash": self.encoded}))
        self.auth.chmod(0o600)
        self.ledger = self.home / "synthetic-ledger.json"
        self.ledger.write_bytes(b'{"account":"synthetic","running":true,"fills":[1]}')
        self.before = {path: path.read_bytes() for path in (self.auth, self.ledger)}
        self.stack = ExitStack()
        self.stack.enter_context(patch.dict(os.environ, {"ETF_WEB_PASSWORD_HASH": "", "ETF_WEB_SECURE_COOKIE": "1", "ETF_WEB_TRUSTED_HOSTS": "testserver"}))
        self.stack.enter_context(patch("server.Runtime", SyntheticRuntime))
        self.stack.enter_context(patch("server.shutdown_runtime"))
        for target in ("account_benchmark_service.AccountBenchmarkService", "market_index_service.MarketIndexBenchmarkService",
                       "company_research.service.ResearchService", "sector_research.research_service.ResearchService"):
            self.stack.enter_context(patch(target, return_value=None))
        self.stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("No test network")))

    async def asyncTearDown(self):
        self.stack.close()
        for path, body in self.before.items():
            self.assertEqual(path.read_bytes(), body)
        self.temp.cleanup()

    @asynccontextmanager
    async def app(self):
        app = create_app(self.home, paper_factory=lambda _: None)
        async with app.router.lifespan_context(app):
            yield app

    async def login(self, app, remember=True):
        status, headers, body = await request(app, "/api/login", method="POST",
            data={"password": self.password, "remember_device": remember})
        self.assertEqual(status, 200)
        return headers["set-cookie"].split(";", 1)[0], body["csrf"], headers, body

    async def test_real_app_rebuild_keeps_remembered_cookie_and_original_data(self):
        async with self.app() as app:
            cookie, csrf, headers, body = await self.login(app)
            self.assertTrue(body["remembered"])
            for flag in ("HttpOnly", "Secure", "SameSite=strict", f"Max-Age={DEVICE_TTL}"):
                self.assertIn(flag, headers["set-cookie"])
        async with self.app() as rebuilt:
            status, _, body = await request(rebuilt, "/api/session", cookie=cookie)
            self.assertEqual((status, body["authenticated"], body["remembered"], body["csrf"]), (200, True, True, csrf))
            self.assertEqual((await request(rebuilt, "/api/catalog", cookie=cookie))[0], 200)

    async def test_real_logout_stays_revoked_after_app_rebuild(self):
        async with self.app() as app:
            cookie, csrf, _, _ = await self.login(app)
            status, headers, _ = await request(app, "/api/logout", method="POST", data={}, cookie=cookie, csrf=csrf)
            self.assertEqual(status, 200)
            self.assertIn("Max-Age=0", headers["set-cookie"])
        async with self.app() as rebuilt:
            self.assertEqual((await request(rebuilt, "/api/catalog", cookie=cookie))[0], 401)
            self.assertFalse((await request(rebuilt, "/api/session", cookie=cookie))[2]["authenticated"])

    async def test_app_password_change_revokes_previous_device(self):
        async with self.app() as app:
            cookie, _, _, _ = await self.login(app)
        changed_password = "Another-synthetic-password-2026"
        try:
            self.auth.write_text(json.dumps({"password_hash": hash_password(changed_password)}))
            async with self.app() as rebuilt:
                self.assertEqual((await request(rebuilt, "/api/catalog", cookie=cookie))[0], 401)
                self.assertEqual((await request(rebuilt, "/api/login", method="POST", data={"password": self.password, "remember_device": True}))[0], 401)
                self.assertEqual((await request(rebuilt, "/api/login", method="POST", data={"password": changed_password, "remember_device": True}))[0], 200)
        finally:
            self.auth.write_bytes(self.before[self.auth])
        async with self.app() as rebuilt:
            self.assertEqual((await request(rebuilt, "/api/catalog", cookie=cookie))[0], 401)

    async def test_legacy_login_without_remember_remains_twelve_hour_session(self):
        async with self.app() as app:
            status, headers, body = await request(app, "/api/login", method="POST", data={"password": self.password})
            self.assertEqual(status, 200)
            self.assertFalse(body["remembered"])
            self.assertIn("Max-Age=43200", headers["set-cookie"])
            cookie = headers["set-cookie"].split(";", 1)[0]
            self.assertFalse((self.home / "web" / "auth-sessions").exists())
        async with self.app() as rebuilt:
            self.assertFalse((await request(rebuilt, "/api/session", cookie=cookie))[2]["authenticated"])

    async def test_remember_flag_is_strict_and_wrong_password_is_rejected(self):
        async with self.app() as app:
            for value in ("true", 1, None, [], {}):
                self.assertEqual((await request(app, "/api/login", method="POST", data={"password": self.password, "remember_device": value}))[0], 400)
            self.assertEqual((await request(app, "/api/login", method="POST", data={"password": "wrong", "remember_device": True}))[0], 401)
            self.assertFalse((self.home / "web" / "auth-sessions").exists())

    async def test_persistent_cookie_preserves_csrf_and_origin_guards(self):
        async with self.app() as app:
            self.assertEqual((await request(app, "/api/catalog"))[0], 401)
            cookie, csrf, _, _ = await self.login(app)
            for value in (None, "wrong"):
                self.assertEqual((await request(app, "/api/settings", method="POST", data={}, cookie=cookie, csrf=value))[0], 403)
            self.assertEqual((await request(app, "/api/settings", method="POST", data={}, cookie=cookie, csrf=csrf, origin="https://outside.invalid"))[0], 403)
            self.assertEqual((await request(app, "/api/settings", method="POST", data={}, cookie=cookie, csrf=csrf))[0], 200)

    async def test_session_and_api_activity_renew_server_and_browser_expiry(self):
        async with self.app() as app:
            for endpoint in ("/api/session", "/api/catalog"):
                cookie, _, _, _ = await self.login(app)
                now = int(time.time())
                with closing(sqlite3.connect(app.state.device_sessions.path)) as db:
                    with db:
                        db.execute("UPDATE devices SET expires_at=?", (now + 60,))
                status, headers, _ = await request(app, endpoint, cookie=cookie)
                self.assertEqual(status, 200)
                self.assertIn("HttpOnly", headers["set-cookie"])
                age = int(headers["set-cookie"].split("Max-Age=")[1].split(";")[0])
                self.assertTrue(DEVICE_TTL - 3 <= age <= DEVICE_TTL)
                token = cookie.split("=", 1)[1]
                self.assertGreaterEqual(app.state.device_sessions.lookup(token)["expires"], now + DEVICE_TTL)

    async def test_storage_failures_cannot_issue_cookie_or_fake_logout(self):
        async with self.app() as app:
            with patch.object(app.state.device_sessions, "issue", side_effect=SessionStoreUnavailable("synthetic")):
                status, headers, _ = await request(app, "/api/login", method="POST", data={"password": self.password, "remember_device": True})
                self.assertEqual(status, 503)
                self.assertNotIn("set-cookie", headers)
            cookie, csrf, _, _ = await self.login(app)
            with patch.object(app.state.device_sessions, "revoke", side_effect=SessionStoreUnavailable("synthetic")):
                status, headers, _ = await request(app, "/api/logout", method="POST", data={}, cookie=cookie, csrf=csrf)
                self.assertEqual(status, 503)
                self.assertNotIn("set-cookie", headers)
            self.assertEqual((await request(app, "/api/catalog", cookie=cookie))[0], 200)

    async def test_slow_session_storage_does_not_block_asgi_event_loop(self):
        async with self.app() as app:
            cookie, _, _, _ = await self.login(app)
            started, release = threading.Event(), threading.Event()
            lookup = app.state.device_sessions.lookup

            def delayed(*args, **kwargs):
                started.set()
                if not release.wait(3):
                    raise AssertionError("Session worker was never released")
                return lookup(*args, **kwargs)

            with patch.object(app.state.device_sessions, "lookup", side_effect=delayed):
                pending = asyncio.create_task(request(app, "/api/catalog", cookie=cookie))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 1))
                    self.assertEqual((await asyncio.wait_for(request(app, "/healthz"), 0.5))[0], 200)
                finally:
                    release.set()
                    await pending


if __name__ == "__main__":
    unittest.main()
