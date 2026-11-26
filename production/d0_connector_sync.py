"""Short-lived, session-bound status sync and optional same-network proof."""
from dataclasses import dataclass
from hashlib import sha256
import re
import secrets
from threading import Lock
from time import monotonic


class SyncError(ValueError):
    pass


@dataclass
class Pairing:
    digest: str | None
    state: str
    expires: float
    signal_digest: str | None = None
    expected_peer: str | None = None
    authorized_peer: str | None = None


class ConnectorSync:
    pair_seconds = 300
    link_seconds = 900
    capacity = 128

    def __init__(self, now=monotonic):
        self._now = now
        self._entries = {}
        self._lock = Lock()

    @staticmethod
    def _digest(value):
        return sha256(value.encode('ascii')).hexdigest()

    @classmethod
    def _verify_format(cls, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', token):
            raise SyncError('同步凭证无效、过期或已使用。')
        return cls._digest(token)

    def _prune(self, now):
        for owner, entry in list(self._entries.items()):
            if entry.expires <= now:
                self._entries.pop(owner)

    def start(self, owner, *, peer=None):
        with self._lock:
            now = self._now()
            self._prune(now)
            if owner not in self._entries and len(self._entries) >= self.capacity:
                raise SyncError('同步服务繁忙，请稍后重试。')
            code = secrets.token_urlsafe(24)
            self._entries[owner] = Pairing(self._digest(code), 'waiting', now + self.pair_seconds, expected_peer=peer)
            return {'code': code, 'expires_in': self.pair_seconds}

    def status(self, owner, *, peer=None, include_network=False):
        with self._lock:
            self._prune(self._now())
            entry = self._entries.get(owner)
            result = {'state': entry.state if entry else 'not_linked'}
            if include_network:
                result['broker_network_authorized'] = bool(entry and peer and entry.authorized_peer == peer)
                result['broker_network_mismatch'] = bool(entry and entry.expected_peer and not entry.authorized_peer
                                                         and entry.state != 'waiting')
            return result

    def network_lease(self, owner, peer):
        """In-process identity of this exact pairing, never returned to the web client."""
        with self._lock:
            self._prune(self._now())
            entry = self._entries.get(owner)
            return entry.signal_digest if peer and entry and entry.authorized_peer == peer else None

    def revoke(self, owner):
        with self._lock:
            self._entries.pop(owner, None)

    def _match(self, digest, state):
        for entry in self._entries.values():
            if entry.state == state and entry.digest and secrets.compare_digest(entry.digest, digest):
                return entry
        raise SyncError('同步凭证无效、过期或已使用。')

    def claim(self, code, *, peer=None):
        digest = self._verify_format(code)
        with self._lock:
            now = self._now()
            self._prune(now)
            entry = self._match(digest, 'waiting')
            token = secrets.token_urlsafe(24)
            signal_token = secrets.token_urlsafe(24)
            entry.digest, entry.state, entry.expires = self._digest(token), 'linked', now + self.link_seconds
            entry.signal_digest = self._digest(signal_token)
            if peer and peer == entry.expected_peer:
                entry.authorized_peer = peer
            return {'sync_token': token, 'signal_token': signal_token, 'expires_in': self.link_seconds}

    def signal_owner(self, token):
        try:
            token_digest = self._verify_format(token)
        except SyncError:
            return None
        with self._lock:
            self._prune(self._now())
            for owner, entry in self._entries.items():
                if entry.signal_digest and secrets.compare_digest(entry.signal_digest, token_digest):
                    return owner
            return None

    def report(self, token, state):
        if state not in ('verified', 'failed'):
            raise SyncError('不支持的同步状态。')
        digest = self._verify_format(token)
        with self._lock:
            now = self._now()
            self._prune(now)
            entry = self._match(digest, 'linked')
            entry.digest, entry.state = None, state
            return {'ok': True}
