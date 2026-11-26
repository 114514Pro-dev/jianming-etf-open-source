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

    def test_network_access_expires_and_cannot_be_extended_by_status_report(self):
        peer = '8.8.8.8'

        def authorized():
            return self.sync.status('browser', peer=peer, include_network=True)['broker_network_authorized']

        pair = self.sync.start('browser', peer=peer)['code']
        self.assertFalse(authorized())
        token = self.sync.claim(pair, peer=peer)['sync_token']
        self.assertTrue(authorized())
        self.now += self.sync.link_seconds - 1
        self.sync.report(token, 'verified')
        self.assertTrue(authorized())
        self.now += 1
        self.assertFalse(authorized())
        self.sync.claim(self.sync.start('browser', peer=peer)['code'], peer=peer)
        self.sync.start('browser', peer=peer)
        self.assertFalse(authorized())

    def test_network_lease_cannot_be_renewed_by_repairing_at_same_address(self):
        peer = '8.8.8.8'
        self.sync.claim(self.sync.start('browser', peer=peer)['code'], peer=peer)
        first = self.sync.network_lease('browser', peer)
        self.assertIsNotNone(first)
        self.assertIsNone(self.sync.network_lease('other-browser', peer))
        self.sync.start('browser', peer=peer)
        self.assertIsNone(self.sync.network_lease('browser', peer))
        self.sync.claim(self.sync.start('browser', peer=peer)['code'], peer=peer)
        self.assertNotEqual(first, self.sync.network_lease('browser', peer))

    def test_new_pair_and_logout_revoke_previous_token(self):
        token = self.sync.claim(self.sync.start('browser')['code'])['sync_token']
        pair = self.sync.start('browser')['code']
        with self.assertRaises(SyncError):
            self.sync.report(token, 'verified')
        self.sync.revoke('browser')
        with self.assertRaises(SyncError):
            self.sync.claim(pair)
