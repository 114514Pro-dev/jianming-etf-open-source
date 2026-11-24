"""Independent index workers and read-only account comparisons."""
from __future__ import annotations

import logging
import os
import threading

from market_index_benchmark import INDICES, MarketIndexCache, build_index_benchmark, unavailable_index

LOG = logging.getLogger('etfweb.market_indices')


def unavailable_indices(message='指数行情暂不可用，账户资产曲线仍可查看。'):
    return [unavailable_index(symbol, message) for symbol, _ in INDICES]


class MarketIndexBenchmarkService:
    def __init__(self, folder, *, refresh_enabled=None, interval=300):
        self.caches = {symbol: MarketIndexCache(folder, symbol) for symbol, _ in INDICES}
        self.halt = threading.Event()
        self.interval = max(1, interval)
        self.thread = None
        if refresh_enabled is None:
            refresh_enabled = os.environ.get('ETF_WEB_INDEX_BENCHMARK_REFRESH',
                                             os.environ.get('ETF_WEB_BENCHMARK_REFRESH', '1')) == '1'
        if refresh_enabled:
            self.thread = threading.Thread(target=self._worker, name='benchmark-indices', daemon=True)
            self.thread.start()

    def refresh(self):
        results = []
        for symbol, _ in INDICES:
            if self.halt.is_set():
                break
            try:
                result = self.caches[symbol].refresh()
            except Exception as exc:
                LOG.exception('index refresh failed: %s', symbol)
                result = dict(status='unavailable', symbol=symbol, message=str(exc))
            if result.get('status') == 'unavailable':
                LOG.warning('index refresh unavailable: %s: %s', symbol, result.get('message'))
            results.append(result)
        return results

    def _worker(self):
        while not self.halt.is_set():
            self.refresh()
            if self.halt.wait(self.interval):
                break

    def compare(self, detail):
        """Only cache reads and pure calculations; one bad index stays isolated."""
        results = []
        for symbol, _ in INDICES:
            try:
                cache = self.caches[symbol]
                result = build_index_benchmark(detail, cache.read(), symbol)
                if cache.last_error:
                    result.setdefault('notes', []).append('指数行情最新刷新未成功；仅使用已校验资料，比较截止日以图中标注为准。')
                results.append(result)
            except Exception:
                LOG.exception('index comparison failed: %s', symbol)
                results.append(unavailable_index(symbol))
        return results

    def close(self):
        self.halt.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
