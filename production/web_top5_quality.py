"""Web-only source finalization and one reviewed immutable-history exception.

No indicator, trading, account or immutable snapshot is modified here. A source
observation must be durably recorded before the caller may publish an extension.
"""
from copy import deepcopy
from datetime import datetime, time, timedelta
from pathlib import Path

from chinext_service import CN, _digest, _numeric_row, _read, _write

SCHEMA = 'web.top5.quality.v1'
JOURNAL_NAME = '网页行情质量审计.json'
REVIEW_ID = 'sz159915-20260930-150000-volume-frozen-v1'
ACCEPTED_ROW = dict(datetime='2026-09-30 15:00:00', open=3.161, high=3.163,
                    low=3.151, close=3.154, volume=256117862.0, amount=None)
OBSERVED_ROW = dict(ACCEPTED_ROW, volume=270397585.0)
REVIEW_EVIDENCE = dict(
    accepted_snapshot='dd27f05dbfd38f55cae35f589afe0b47742ede63bdc801852ed483223b824425',
    accepted_fetched_at='2026-09-30T15:01:02+08:00',
    accepted_source_sha256='ab0be8902055429f9252b22a656d140430e9c7c735f4d1852ea8e4ba5aead018',
    verified_source_sha256='728af14e954d9c3ed0fddb25737eb0c285dac4fc555de1e63650d2619f9ec14f',
    verified_observed_at=['2026-09-30T21:25:59+08:00', '2026-09-30T21:30:41+08:00'],
    reviewed_export_sha256='1b13499d8845bb0da13fba623dab0f8b2fefd351991927c50508f624d89b3ea0',
    scope='4000 overlapping hourly rows: this volume only; all five Top5 signals '
          'and reviewed T5VOTE ledger/events/trades/state/metrics/pending unchanged through 2026-09-30.',
    policy='Preserve the previously accepted historical row; do not replace it with the revised source row. '
           'Past equality is not a guarantee of equal signals after future bars.')


def reviewed_volume_change(previous, incoming, key):
    # Check raw keys too: do not silently discard an unknown field in this exception.
    return key == 'datetime' and previous == ACCEPTED_ROW and incoming == OBSERVED_ROW


class Top5QualityGate:
    def __init__(self, folder, now):
        if now.tzinfo is None:
            raise ValueError('网页行情确认必须使用带时区的时间。')
        self.now = now.astimezone(CN)
        self.path = Path(folder) / JOURNAL_NAME
        self.sources = []
        self.snapshot_id = None
        self.waiting = []
        self._review_recorded = False
        if self.path.exists():
            payload = _read(self.path)
            if (not isinstance(payload, dict) or payload.get('schema') != SCHEMA or
                    not isinstance(payload.get('revisions'), dict) or
                    not isinstance(payload.get('settlement'), dict) or
                    payload.get('integrity') != _digest({k:v for k,v in payload.items() if k != 'integrity'})):
                raise ValueError('网页行情质量审计损坏或校验不符，停止发布行情。')
            self.data = {k:v for k,v in payload.items() if k != 'integrity'}
        else:
            self.data = dict(schema=SCHEMA, revisions={}, settlement={})

    def _save(self):
        payload = dict(self.data, integrity=_digest(self.data))
        try:
            _write(self.path, payload)
        except Exception as exc:
            raise ValueError('网页行情质量审计无法持久保存，未允许发布行情：' + str(exc)) from exc

    def _source_evidence(self, source_names):
        result = []
        for name in source_names:
            matches = [r for r in self.sources if r.get('source') == name and not r.get('error')]
            if len(matches) != 1:
                raise ValueError('缺少唯一可核验的行情来源记录：' + name)
            row = matches[0]
            digest = row.get('sha256', '')
            if (len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or
                    not isinstance(row.get('fetched_at'), str)):
                raise ValueError('行情来源缺少有效SHA256或采集时间：' + name)
            stamp = datetime.fromisoformat(row['fetched_at'])
            if stamp.tzinfo is None or stamp > self.now:
                raise ValueError('行情来源采集时间无时区或晚于确认时间：' + name)
            result.append(deepcopy(row))
        return result

    def retain_reviewed_volume(self, previous, incoming, key):
        if not reviewed_volume_change(previous, incoming, key):
            return False
        if self._review_recorded:
            return True  # Identical duplicate source rows are one refresh observation.
        evidence = self._source_evidence(['新浪未复权60分钟'])
        now = self.now.isoformat(timespec='seconds')
        record = self.data['revisions'].get(REVIEW_ID)
        if record is None:
            record = dict(id=REVIEW_ID, policy='冻结已接受历史，保留原成交量；未采用来源修订量。',
                          accepted_row=deepcopy(ACCEPTED_ROW), observed_row=deepcopy(OBSERVED_ROW),
                          verified_evidence=deepcopy(REVIEW_EVIDENCE),
                          first_detected_at=now, first_source_evidence=evidence,
                          first_snapshot_id=self.snapshot_id, observation_count=0)
        elif (record.get('accepted_row') != ACCEPTED_ROW or record.get('observed_row') != OBSERVED_ROW or
              record.get('verified_evidence') != REVIEW_EVIDENCE):
            raise ValueError('已核验成交量修订的审计记录不一致，停止发布行情。')
        record = deepcopy(record)
        record.update(last_detected_at=now, last_source_evidence=evidence,
                      last_snapshot_id=self.snapshot_id, observation_count=record['observation_count'] + 1)
        self.data['revisions'][REVIEW_ID] = record
        self._save()  # Including no-new-bar refreshes; failure occurs before snapshot publication.
        self._review_recorded = True
        return True

    @staticmethod
    def _rows(rows, key):
        result = {}
        for raw in rows:
            row = _numeric_row(raw, key)
            stamp = row[key]
            if stamp in result and row != result[stamp]:
                raise ValueError('来源重复返回不同的' + stamp + '行情，保留旧快照。')
            result[stamp] = row
        return result

    def prepare(self, old, fresh):
        self.snapshot_id = _digest(old)
        self.sources = deepcopy(fresh.get('sources', []))
        result = deepcopy(fresh)
        daily = self._rows(fresh.get('daily', []), 'date')
        hourly = self._rows(fresh.get('hourly', []), 'datetime')
        old_daily = {r['date']:r for r in old['daily']}
        old_hourly = {r['datetime']:r for r in old['hourly']}
        # Finalized historical rows are still checked by the native merger. Only
        # previously unaccepted dates/tails are eligible for this publication gate.
        days = sorted({d for d in daily if d not in old_daily} |
                      {t[:10] for t in hourly if t.endswith('15:00:00') and t not in old_hourly})
        block_from = None
        changed = False
        for day in days:
            stamp = day + ' 15:00:00'
            drow = daily.get(day, old_daily.get(day))
            hrow = hourly.get(stamp, old_hourly.get(stamp))
            eligible = datetime.combine(datetime.fromisoformat(day).date(), time(16, 10), CN)
            reason = None
            if self.now < eligible:
                reason = '尚未到当日16:10，暂缓正式日线与15点尾柱。'
            elif drow is None or hrow is None:
                reason = '正式日线或15点尾柱缺失，等待成对核验。'
            else:
                evidence = self._source_evidence(['腾讯未复权日线', '新浪未复权60分钟'])
                # A replay of an earlier response cannot count as a fresh post-close observation.
                source_times = [datetime.fromisoformat(r['fetched_at']).astimezone(CN) for r in evidence]
                pair_started = min(source_times)
                observed = max(source_times)
                candidate = dict(daily=drow, hourly=hrow)
                candidate_hash = _digest(candidate)
                previous = self.data['settlement'].get(day)
                if pair_started < eligible:
                    reason = '来源采集早于16:10，等待较晚的正式收盘观测。'
                elif previous is None or previous.get('candidate_hash') != candidate_hash:
                    self.data['settlement'][day] = dict(
                        day=day, candidate=candidate, candidate_hash=candidate_hash,
                        first_observed_at=observed.isoformat(), last_observed_at=observed.isoformat(),
                        first_source_evidence=evidence, last_source_evidence=evidence,
                        confirmed=False, reset_count=(previous.get('reset_count', 0) + 1 if previous else 0))
                    changed = True
                    reason = '已过16:10；等待至少60秒后的相同收盘观测。'
                else:
                    if previous.get('candidate') != candidate:
                        raise ValueError('收盘候选内容与哈希不一致，停止发布行情。')
                    first = datetime.fromisoformat(previous['first_observed_at'])
                    last = datetime.fromisoformat(previous['last_observed_at'])
                    if observed < last:
                        reason = '来源观测时间倒退，等待新的收盘观测。'
                    else:
                        previous = deepcopy(previous)
                        previous.update(last_observed_at=observed.isoformat(), last_source_evidence=evidence)
                        if pair_started - first >= timedelta(seconds=60):
                            previous['confirmed'] = True
                            previous.setdefault('confirmed_at', self.now.isoformat(timespec='seconds'))
                        self.data['settlement'][day] = previous
                        changed = True
                        if not previous['confirmed']:
                            reason = '第二次相同收盘观测尚未与首次间隔60秒。'
            if reason:
                block_from = min(block_from or day, day)
                self.waiting.append(dict(day=day, reason=reason))
        if changed:
            self._save()  # Candidate/confirmation persistence precedes any immutable snapshot.
        if block_from:
            # Keep all accepted overlap for native revision checks; never hide a
            # conflicting old bar merely because new rows are being held back.
            result['daily'] = [r for r in fresh.get('daily', [])
                               if r['date'] in old_daily or r['date'] < block_from]
            cutoff = block_from + ' 15:00:00'
            result['hourly'] = [r for r in fresh.get('hourly', [])
                                if r['datetime'] in old_hourly or r['datetime'] < cutoff]
            result['warnings'] = list(result.get('warnings', [])) + [
                '网页收盘确认：' + item['day'] + ' ' + item['reason'] for item in self.waiting]
        return result

    def result_metadata(self):
        return dict(policy='16:10后日线与15点尾柱成对确认，两个相同来源观测至少间隔60秒。',
                    audit_file=JOURNAL_NAME, waiting=deepcopy(self.waiting),
                    retained_volume_revisions=deepcopy(list(self.data['revisions'].values())))
