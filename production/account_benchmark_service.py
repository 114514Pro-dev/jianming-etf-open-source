"""Independent read-only comparison service; never schedules account trades."""
from __future__ import annotations

import logging
import os
import threading

from account_benchmark import BenchmarkCache, build_account_benchmark, NAME, SYMBOL, METHOD

LOG = logging.getLogger("etfweb.benchmark")


def unavailable(message="基准行情暂不可用，账户资产曲线仍可查看。"):
    return dict(status="unavailable", symbol=SYMBOL, name=NAME, message=message,
                methodology=METHOD, notes=[], account_curve=[], benchmark_curve=[])


class AccountBenchmarkService:
    def __init__(self, folder, *, refresh_enabled=None, interval=300):
        self.cache = BenchmarkCache(folder)
        self.halt = threading.Event()
        self.interval = max(1, interval)
        self.thread = None
        if refresh_enabled is None:
            refresh_enabled = os.environ.get("ETF_WEB_BENCHMARK_REFRESH", "1") == "1"
        if refresh_enabled:
            self.thread = threading.Thread(target=self._worker, name="benchmark-market", daemon=True)
            self.thread.start()

    def _worker(self):
        while not self.halt.is_set():
            try:
                result = self.cache.refresh()
                if result.get("status") == "unavailable":
                    LOG.warning("benchmark refresh unavailable: %s", result.get("message"))
            except Exception:
                LOG.exception("benchmark refresh failed; existing account operations unaffected")
            if self.halt.wait(self.interval):
                break

    def compare(self, detail):
        try:
            result = build_account_benchmark(detail, self.cache.read())
            if self.cache.last_error:
                result.setdefault("notes", []).append("基准行情最新刷新未成功；仅使用已校验资料，比较截止日以图中标注为准。")
            return result
        except Exception:
            LOG.exception("benchmark comparison failed; returning independent unavailable state")
            return unavailable()

    def close(self):
        self.halt.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
