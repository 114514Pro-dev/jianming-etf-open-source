from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from d0_connector_sync import ConnectorSync, SyncError


class SyncExpiryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sync = ConnectorSync(now=lambda: self.now)

    def test_expired_codes_and_results_disappear(self):
        first = self.sync.start('browser')['code']
        self.now += self.sync.pair_seconds
        self.assertEqual(self.sync.status('browser'), {'state': 'not_linked'})
        with self.assertRaises(SyncError):
            self.sync.claim(first)
        token = self.sync.claim(self.sync.start('browser')['code'])['sync_token']
        self.sync.report(token, 'failed')
        self.now += self.sync.link_seconds
        self.assertEqual(self.sync.status('browser'), {'state': 'not_linked'})

    def test_new_pair_and_logout_revoke_previous_token(self):
        token = self.sync.claim(self.sync.start('browser')['code'])['sync_token']
        pair = self.sync.start('browser')['code']
        with self.assertRaises(SyncError):
            self.sync.report(token, 'verified')
        self.sync.revoke('browser')
        with self.assertRaises(SyncError):
            self.sync.claim(pair)
