"""Read-only, bounded long polling for local D0 tools. No order messages."""
import asyncio
import copy
import secrets
import time


class SignalFeed:
    wait_seconds = 10
    freshness_seconds = 15
    max_listeners = 8

    def __init__(self, monotonic=time.monotonic, wall=time.time):
        self._mono, self._wall = monotonic, wall
        self._last_checked = None
        self._target = None
        self._cursor = secrets.token_hex(8)
        self._published_ms = None
        self._changed = asyncio.Event()
        self.active = set()

    def publish(self, target):
        """Call on the application event loop, after the paper source updates."""
        self._last_checked = self._mono()
        if target == self._target:
            return
        self._target = copy.deepcopy(target)
        self._cursor = secrets.token_hex(8)
        self._published_ms = round(self._wall() * 1000) if target is not None else None
        event, self._changed = self._changed, asyncio.Event()
        event.set()

    def _current(self):
        if self._last_checked is None or self._mono() - self._last_checked > self.freshness_seconds:
            self.publish(None)
        return {'cursor': self._cursor, 'signal': self._target, 'published_at_ms': self._published_ms}

    async def next(self, after, allowed):
        deadline = self._mono() + self.wait_seconds
        while True:
            if not allowed():
                raise PermissionError('Signal subscription ended')
            state = self._current()
            if state['cursor'] != after:
                return state
            seconds = deadline - self._mono()
            if seconds <= 0:
                return {'cursor': after, 'unchanged': True}
            try:
                await asyncio.wait_for(self._changed.wait(), min(seconds, 1))
            except TimeoutError:
                pass
