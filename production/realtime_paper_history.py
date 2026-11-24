"""D0 continuity from authenticated, immutable public market snapshots.

The ledger's previous signal hash is the anchor. Only the already validated
public market store supplies later rows. Revised prior prices are never adopted.
No account, order, fill, automation setting or old market file is written here.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class HistoryContinuityError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def durable_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class AcceptedHistory:
    SCHEMA = 'd0.accepted-history.v1'
    POLICY = '保留原信号已确认历史，仅追加公共行情库已核验的后续完整日线；旧成交不重算。'
    # These fields can change accounting/adjustment semantics, never price-only revisions.
    METADATA = ('schema', 'attack_symbol', 'first_dates', 'history_start',
                'split_adjustments', 'actions', 'splits', 'dividends', 'adjustments',
                'corporate_actions', 'adjustment', 'price_adjustment')

    def __init__(self, home, history_hash, truncate, validate, market_digest, *, folder=None):
        self.home = Path(home)
        self.folder = Path(folder) if folder is not None else self.home / 'web' / 'realtime-paper-history'
        self.history_hash, self.truncate = history_hash, truncate
        self.validate, self.market_digest = validate, market_digest
        self._anchors = {}
        self._search_errors = {}

    def _checkpoint(self, cutoff, identity):
        if (not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{64}', identity)
                or date.fromisoformat(cutoff).isoformat() != cutoff):
            raise HistoryContinuityError('history_anchor_invalid')
        return self.folder / 'checkpoints' / (cutoff + '-' + identity + '.json')

    @staticmethod
    def _read(path):
        if path.is_symlink() or path.stat().st_size > 96 * 1024 * 1024:
            raise HistoryContinuityError('history_checkpoint_invalid')
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        integrity = value.pop('integrity', None)
        if digest(value) != integrity:
            raise HistoryContinuityError('history_checkpoint_invalid')
        return value

    @classmethod
    def _metadata(cls, data):
        return {group: {key: data[group].get(key) for key in cls.METADATA}
                for group in ('chi', 'bank')}

    def _anchor(self, cutoff, identity):
        key = (cutoff, identity)
        path = self._checkpoint(*key)
        if path.exists():
            value = self._read(path)
            if (value.get('schema') != self.SCHEMA or value.get('cutoff') != cutoff
                    or value.get('history_hash') != identity
                    or self.history_hash(value.get('data'), cutoff) != identity):
                raise HistoryContinuityError('history_checkpoint_invalid')
            return value['data']
        if key in self._anchors:
            return deepcopy(self._anchors[key])
        snapshots = self.home / '行情快照'
        # Legacy signal hashes omit some adjustment metadata. Migration must not
        # choose the newest of conflicting snapshots that share the old hash.
        search = (key, snapshots.stat().st_mtime_ns if snapshots.exists() else None)
        if search in self._search_errors:
            raise HistoryContinuityError(self._search_errors[search])
        paths = sorted((p for p in snapshots.glob('*.json')
                        if re.fullmatch('[a-f0-9]{64}', p.stem)),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
        baseline, metadata = None, None
        for candidate in paths[:256]:
            if candidate.is_symlink() or candidate.stat().st_size > 96 * 1024 * 1024:
                continue
            try:
                raw = json.loads(candidate.read_text(encoding='utf-8-sig'))
                # Identical metadata cannot create ambiguity. Avoid validating
                # and hashing an entire price history again for those files.
                if baseline is not None and self._metadata(raw) == metadata:
                    continue
                data = self.validate(raw)
                if self.market_digest(data) != candidate.stem:
                    continue
                if self.history_hash(data, cutoff) != identity:
                    continue
                candidate_metadata = self._metadata(data)
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
            if baseline is not None and candidate_metadata != metadata:
                self._search_errors[search] = 'corporate_action_review_required'
                raise HistoryContinuityError('corporate_action_review_required')
            baseline, metadata = self.truncate(data, cutoff)[0], candidate_metadata
        # A bounded scan cannot prove unambiguous legacy metadata beyond its
        # limit. Existing checkpoints bypass migration and this archive scan.
        if baseline is None or len(paths) > 256:
            self._search_errors[search] = 'history_baseline_missing'
            raise HistoryContinuityError('history_baseline_missing')
        self._anchors[key] = baseline
        return deepcopy(baseline)

    def reconcile(self, data, previous, source_reference):
        """Use only a hash-authenticated canonical store; seeds never authorize recovery."""
        cutoff, identity = previous.get('history_cutoff'), previous.get('history_hash')
        if not cutoff or not identity:
            return data, None
        unchanged = self.history_hash(data, cutoff) == identity
        if not source_reference:
            if not unchanged:
                raise HistoryContinuityError('historical_data_revision')
            # Bundled/legacy data may continue unchanged without authorizing a
            # recovery. A prior checkpoint, if present, still guards metadata.
            if not self._checkpoint(cutoff, identity).exists():
                return data, None
        elif (not re.fullmatch('[a-f0-9]{64}', source_reference)
                or self.market_digest(data) != source_reference):
            raise HistoryContinuityError('historical_data_revision')
        baseline = self._anchor(cutoff, identity)
        if self._metadata(baseline) != self._metadata(data):
            raise HistoryContinuityError('corporate_action_review_required')
        if unchanged:
            return data, None
        output = deepcopy(data)
        changes = []
        for group in ('chi', 'bank'):
            old, new = baseline[group], output[group]
            if any(old.get(key) != new.get(key) for key in self.METADATA):
                raise HistoryContinuityError('corporate_action_review_required')
            if set(old['bars']) != set(new['bars']):
                raise HistoryContinuityError('history_continuity_gap')
            for symbol, accepted in old['bars'].items():
                rows = new['bars'][symbol]
                stamps = [row['date'] for row in rows]
                old_stamps = [row['date'] for row in accepted]
                if (stamps != sorted(set(stamps)) or old_stamps != sorted(set(old_stamps))
                        or [day for day in stamps if day <= cutoff] != old_stamps):
                    raise HistoryContinuityError('history_continuity_gap')
                revisions = [{'date': a['date'], 'accepted': a, 'observed': b}
                             for a, b in zip(accepted, rows) if a != b]
                if revisions:
                    changes.append({'group': group, 'symbol': symbol, 'rows': revisions})
                new['bars'][symbol] = deepcopy(accepted) + [r for r in rows if r['date'] > cutoff]
        output = self.validate(output)
        if self.history_hash(output, cutoff) != identity:
            raise HistoryContinuityError('history_continuity_gap')
        evidence = dict(policy=self.POLICY, previous_cutoff=cutoff, previous_hash=identity,
                        source_reference=source_reference, changes=changes)
        return output, evidence

    def commit(self, data, cutoff, source_reference, evidence, observed_at):
        """Persist evidence and new checkpoint before a new signal can reach the ledger."""
        if not source_reference:
            return
        accepted = self.truncate(data, cutoff)[0]
        identity = self.history_hash(accepted, cutoff)
        checkpoint = self._checkpoint(cutoff, identity)
        if evidence:
            value = dict(schema='d0.history-retention-audit.v1', **evidence,
                         accepted_cutoff=cutoff, accepted_hash=identity)
            audit_id = digest(value)
            path = self.folder / 'audits' / (audit_id + '.json')
            if path.exists():
                saved = self._read(path)
                saved.pop('first_observed_at', None)
                if saved != value:
                    raise HistoryContinuityError('history_checkpoint_invalid')
            else:
                value['first_observed_at'] = observed_at
                durable_json(path, dict(value, integrity=digest(value)))
        if checkpoint.exists():
            baseline = self._anchor(cutoff, identity)
            if self._metadata(baseline) != self._metadata(accepted):
                raise HistoryContinuityError('corporate_action_review_required')
        else:
            value = dict(schema=self.SCHEMA, cutoff=cutoff, history_hash=identity,
                         source_reference=source_reference, data=accepted)
            durable_json(checkpoint, dict(value, integrity=digest(value)))
        return dict(policy=self.POLICY, retained=bool(evidence), cutoff=cutoff,
                    history_hash=identity, audit_id=audit_id if evidence else None)
