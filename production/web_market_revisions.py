"""Audit source revisions without rewriting accepted market or account history.

Two fresh, identical source observations at least 60 seconds apart authorize
retaining the accepted row, NOT adopting the revision. Native continuity,
corporate-action and account replay checks remain responsible for publication.
This web policy neither fetches data nor opens any account or scheduler file.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import hashlib
import json
import math
import re

from simulator_core import write_json

SCHEMA = 'web.market-revisions.v1'
JOURNAL = '行情修订保留审计.json'
POLICY = ('来源历史行情已修订；经间隔至少60秒的两次相同观测，保留已接受的原值，'
          '仅追加后续确认行情。历史成交不重写；未来信号可能与全量修订行情不同。')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class RevisionGuard:
    def __init__(self, folder, now, snapshot_id):
        if now.tzinfo is None:
            raise ValueError('行情修订核验时间必须带时区。')
        self.now, self.snapshot_id = now, snapshot_id
        self.path = Path(folder) / JOURNAL
        self.pending, self.retained = [], []
        self.dirty = False
        try:
            if self.path.exists():
                payload = json.loads(self.path.read_text('utf-8-sig'))
                integrity = payload.pop('integrity', None)
                if (payload.get('schema') != SCHEMA or not isinstance(payload.get('records'), dict)
                        or digest(payload) != integrity):
                    raise ValueError('schema/integrity')
                self.data = payload
            else:
                self.data = dict(schema=SCHEMA, policy=POLICY, records={})
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError('行情修订审计无法读取或校验失败，停止发布行情。') from exc

    def _evidence(self, sources, symbol, key):
        name = '腾讯未复权日线' if key == 'date' else None
        matches = [s for s in sources if s.get('source') == name] if name else [
            s for s in sources if s.get('source') in ('新浪未复权60分钟', '新浪未复权小时线')]
        if len(matches) != 1 or matches[0].get('error'):
            raise ValueError('行情修订缺少唯一来源证据。')
        source = matches[0]
        url = urlparse(source.get('url', ''))
        query = parse_qs(url.query)
        valid = (url.scheme == 'https' and (
            (key == 'date' and url.netloc == 'proxy.finance.qq.com'
             and url.path == '/ifzqgtimg/appstock/app/newfqkline/get'
             and query.get('param', [''])[0].startswith(symbol + ',day,')
             and query.get('param', [''])[0].endswith(',640,')) or
            (key == 'datetime' and url.netloc == 'money.finance.sina.com.cn'
             and url.path == '/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
             and query.get('symbol') == [symbol] and query.get('scale') == ['60'])))
        if (not valid or not re.fullmatch('[a-f0-9]{64}', str(source.get('sha256', '')))
                or source.get('adjustment', 'none') != 'none'
                or source.get('price_adjustment', 'none') != 'none'):
            raise ValueError('行情修订的来源、标的、周期或摘要不符。')
        try:
            observed = datetime.fromisoformat(source['fetched_at'])
            if observed.tzinfo is None or not timedelta(0) <= self.now - observed <= timedelta(minutes=15):
                raise ValueError('stale/future source')
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('行情修订来源时间无效、过期或晚于核验时间。') from exc
        return deepcopy(source), observed

    @staticmethod
    def _rows(rows, key, fields):
        found = {}
        for row in rows:
            stamp = row[key]
            fmt = '%Y-%m-%d' if key == 'date' else '%Y-%m-%d %H:%M:%S'
            if datetime.strptime(stamp, fmt).strftime(fmt) != stamp:
                raise ValueError('行情时间格式不正确。')
            values = {f: float(row[f]) for f in fields}
            if any(not math.isfinite(v) or v < 0 for v in values.values()):
                raise ValueError('行情数值无效。')
            if min(values[f] for f in ('open', 'high', 'low', 'close')) <= 0 or not (
                    values['low'] <= min(values['open'], values['close']) <=
                    max(values['open'], values['close']) <= values['high']):
                raise ValueError('行情价格范围无效。')
            if stamp in found and found[stamp] != row:
                raise ValueError('来源重复返回不同的' + stamp + '行情，保留旧快照。')
            found[stamp] = row
        return found

    def retain(self, old, new, key, fields, symbol, sources, exempt=None):
        """Stage both streams before finish(); pending revisions cannot publish."""
        known = {r[key]: r for r in old}
        incoming = self._rows(new, key, fields)
        if not incoming:
            return deepcopy(new)
        first, last = min(incoming), max(incoming)
        if not known.keys() & incoming.keys():
            raise ValueError('行情窗口没有重叠，拒绝跳过历史缺口。')
        if any(t not in incoming for t in known if first <= t <= last):
            raise ValueError('来源重叠区间缺失已接受行情，保留旧快照。')
        end = max(known)
        stream = dict(symbol=symbol, interval=key, adjustment='none')
        result = []
        for stamp, row in sorted(incoming.items()):
            previous = known.get(stamp)
            if previous is None:
                if stamp <= end:
                    raise ValueError('来源插入既有历史范围行情，拒绝回写：' + stamp)
                result.append(deepcopy(row))
                continue
            changed = [f for f in fields if float(row[f]) != float(previous[f])]
            identity = digest(dict(stream=stream, time=stamp, accepted=previous))
            record = self.data['records'].get(identity)
            if not changed or (exempt and exempt(previous, row, key)):
                if record and record.get('active') is not None:
                    record['active'] = None
                    self.dirty = True
                result.append(deepcopy(row))
                continue
            evidence, observed = self._evidence(sources, symbol, key)
            # Diagnostic amount is not part of a strategy revision fingerprint.
            fingerprint = digest({f: row[f] for f in fields})
            if record is None:
                record = dict(stream=stream, time=stamp, accepted_row=deepcopy(previous),
                              first_snapshot=self.snapshot_id, active=None, observations=[])
                self.data['records'][identity] = record
            if record.get('accepted_row') != previous or record.get('stream') != stream:
                raise ValueError('行情修订审计与已接受历史不一致。')
            active = record.get('active')
            if active is not None:
                last_observed = datetime.fromisoformat(active['last_observed_at'])
                if observed < last_observed or (observed == last_observed and active['fingerprint'] != fingerprint):
                    raise ValueError('行情修订来源观测倒退或同一次采集内容冲突。')
            if active is None or active['fingerprint'] != fingerprint:
                active = dict(fingerprint=fingerprint, observed_row=deepcopy(row), fields=changed,
                              first_observed_at=observed.isoformat(), last_observed_at=observed.isoformat(),
                              first_source=evidence, last_source=evidence, confirmed=False)
                record['observations'].append(active)
                record['active'] = active
            else:
                # Persisted JSON does not preserve shared object identity.
                active = deepcopy(active)
                active.update(last_observed_at=observed.isoformat(), last_source=evidence)
                if observed - datetime.fromisoformat(active['first_observed_at']) >= timedelta(seconds=60):
                    active['confirmed'] = True
                record['active'] = active
                record['observations'][-1] = active
            record['last_snapshot'] = self.snapshot_id
            self.dirty = True
            summary = dict(symbol=symbol, time=stamp, fields=changed, audit_id=identity)
            if active['confirmed']:
                self.retained.append(summary)
            else:
                self.pending.append(summary)
            result.append(deepcopy(previous))
        return result

    def finish(self, *, allow_pending=False):
        if self.dirty:
            try:
                write_json(self.path, dict(self.data, integrity=digest(self.data)))
            except Exception as exc:
                raise ValueError('行情修订审计无法持久保存，停止发布行情。') from exc
        if self.pending and not allow_pending:
            raise ValueError('检测到' + str(len(self.pending)) + '条来源历史修订，旧值与账户保留；'
                '等待至少60秒后的相同来源观测再接续。首条：' + self.pending[0]['time'])
        count = sum(any(o.get('confirmed') for o in r['observations'])
                    for r in self.data['records'].values())
        return dict(policy=POLICY, audit_file=JOURNAL, retained=deepcopy(self.retained),
                    retained_history_count=count, pending=deepcopy(self.pending))
