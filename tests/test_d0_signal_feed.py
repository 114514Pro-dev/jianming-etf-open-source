import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from d0_signal_feed import SignalFeed


class SignalFeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_publication_wakes_an_already_waiting_reader(self):
        feed = SignalFeed()
        initial = await feed.next('', lambda: True)
        task = asyncio.create_task(feed.next(initial['cursor'], lambda: True))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        feed.publish({'signal_id': 'D0-1'})
        update = await asyncio.wait_for(task, 1)
        self.assertEqual(update['signal'], {'signal_id': 'D0-1'})
        self.assertNotEqual(initial['cursor'], update['cursor'])

    async def test_recheck_refreshes_health_without_republishing_then_invalidates(self):
        now = 0
        feed = SignalFeed(monotonic=lambda: now, wall=lambda: 1000 + now)
        payload = {'signal_id': 'D0-1'}
        feed.publish(payload)
        first = await feed.next('', lambda: True)
        now = 10
        feed.publish(payload)
        self.assertEqual(first, await feed.next('', lambda: True))
        now = 26
        latest = await feed.next(first['cursor'], lambda: True)
        self.assertIsNone(latest['signal'])
        self.assertNotEqual(latest['cursor'], first['cursor'])
        with self.assertRaises(PermissionError):
            await feed.next('', lambda: False)
