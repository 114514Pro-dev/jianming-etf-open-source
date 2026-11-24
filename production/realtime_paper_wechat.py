"""Deliver committed paper notifications to the configured personal WeChat service account."""
from __future__ import annotations

import http.client
import json
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as day_time, timedelta, timezone
from pathlib import Path


LOGGER = logging.getLogger(__name__)
HOST = "www.pushplus.plus"
TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 8192
MAX_ATTEMPTS = 3
RECEIPT = re.compile(r"[A-Za-z0-9_-]{1,96}")
CHINA = timezone(timedelta(hours=8))


def _configured_token():
    """Only read operator configuration. Invalid or conflicting configuration disables delivery."""
    value = os.environ.get("PUSHPLUS_TOKEN", "")
    filename = os.environ.get("PUSHPLUS_TOKEN_FILE", "")
    if filename:
        if value or not Path(filename).is_absolute():
            return ""
        try:
            with open(filename, "rb") as secret:
                value = secret.read(513).decode("ascii")
        except (OSError, UnicodeError, ValueError):
            return ""
        if len(value) > 512:
            return ""
    value = value.strip()
    return value if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) else ""


@dataclass(frozen=True)
class SendResult:
    status: str
    reason: str
    receipt: str | None = None


def _response_result(http_status, raw, token):
    if http_status == 429:
        return SendResult("retry", "rate_limited")
    if 300 <= http_status < 500 and http_status != 408:
        return SendResult("failed", "http_rejected")
    if http_status != 200 or len(raw) > MAX_RESPONSE_BYTES:
        return SendResult("uncertain", "unexpected_response")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return SendResult("uncertain", "unexpected_response")
    code = body.get("code") if isinstance(body, dict) else None
    if type(code) is not int:
        return SendResult("uncertain", "unexpected_response")
    if code == 200:
        receipt = body.get("data")
        if isinstance(receipt, str) and RECEIPT.fullmatch(receipt) and token not in receipt:
            return SendResult("accepted", "provider_accepted", receipt)
        return SendResult("uncertain", "missing_receipt")
    # Store only local reason codes. The response message can contain private request data.
    rejections = {
        302: "unauthorized", 401: "unauthorized", 403: "unauthorized",
        600: "invalid_request", 805: "unauthorized", 888: "quota_exhausted",
        900: "provider_restricted", 903: "invalid_token", 905: "verification_required",
        999: "invalid_request",
    }
    if code in rejections:
        return SendResult("failed", rejections[code])
    return SendResult("uncertain", "provider_error")


def _send(token, item):
    # A dedicated HTTPS connection has no redirection, HTTP proxy or automatic POST replay.
    # Separating connect from request lets us safely retry failures before any body was sent.
    payload = json.dumps({
        "token": token, "channel": "wechat", "template": "txt",
        "title": item["title"], "content": item["content"],
    }, ensure_ascii=False).encode("utf-8")
    connection = http.client.HTTPSConnection(HOST, timeout=TIMEOUT_SECONDS)
    try:
        try:
            connection.connect()
        except OSError:
            return SendResult("retry", "connect_failed")
        try:
            connection.request("POST", "/send", payload, {"Content-Type": "application/json; charset=utf-8"})
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (http.client.HTTPException, OSError):
            return SendResult("uncertain", "connection_interrupted")
        return _response_result(response.status, raw, token)
    finally:
        connection.close()


class WechatDispatcher:
    """One delivery worker for both ledgers; external IO always runs outside the ledger lock."""

    def __init__(self, services):
        self._services = tuple(services)
        self._token = _configured_token()
        self._stop = threading.Event()
        self._thread = None
        self._recent = deque()
        self._next_service = 0
        self._resume_at = 0

    @property
    def configured(self):
        return bool(self._token)

    @property
    def closed(self):
        return self._thread is None or not self._thread.is_alive()

    def start(self):
        if self.configured and self._services and self._thread is None and not self._stop.is_set():
            self._thread = threading.Thread(target=self._run, name="paper-wechat-notifications", daemon=True)
            self._thread.start()

    def request_stop(self):
        self._stop.set()

    def close(self, timeout=15):
        self.request_stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("WeChat notification worker is still active")

    def _run(self):
        while not self._stop.is_set():
            delay = self._dispatch_once()
            self._stop.wait(delay)

    def _dispatch_once(self):
        if not self.configured:
            return 2
        now = time.monotonic()
        if now < self._resume_at:
            return self._resume_at - now
        while self._recent and now - self._recent[0] >= 61:
            self._recent.popleft()
        if len(self._recent) >= 5:
            return self._recent[0] + 61 - now

        for _ in self._services:
            if self._stop.is_set():
                break
            service = self._services[self._next_service]
            self._next_service = (self._next_service + 1) % len(self._services)
            try:
                store = service.ledger.notifications
                item = service.write_notification(store.claim)
                if item is None:
                    continue
                self._deliver(service, store, item)
            except Exception:
                # An interrupted send or failed completion write leaves a lease. The store
                # reconciles it as uncertain, so a storage failure cannot trigger a repost.
                LOGGER.warning("WeChat notification worker could not service a ledger")
                continue
            return 0
        return 2

    def _deliver(self, service, store, item):
        if self._stop.is_set():
            service.write_notification(store.finish, item["id"], item["lease"], "retry", reason="worker_stopping")
            return
        self._recent.append(time.monotonic())
        result = _send(self._token, item)
        if result.reason == "provider_restricted":
            # Code 900 applies to the provider account; further requests risk a longer suspension.
            now = datetime.now(CHINA)
            midnight = datetime.combine(now.date() + timedelta(days=1), day_time(), CHINA)
            self._resume_at = time.monotonic() + (midnight - now).total_seconds()
        elif result.reason == "rate_limited":
            self._resume_at = time.monotonic() + 61
        status, delay = result.status, 0
        if status == "retry":
            if item["attempts"] >= MAX_ATTEMPTS:
                status = "failed"
            else:
                delay = 60 * item["attempts"]
        service.write_notification(store.finish, item["id"], item["lease"], status,
                                   receipt=result.receipt, reason=result.reason, delay=delay)
