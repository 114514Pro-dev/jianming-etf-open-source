"""Serialized web-only automation; no strategy engine or execution rule changes.

Quotes never become ledger prices. Only immutable, confirmed native snapshots
can advance an account. The HTTP owner supplies its single business executor.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import math
import time

import bank_model
import trade_book
from intraday import fetch_quotes, provisional_market
from simulator_core import ORDER, compatible, amount_only_extension
from chinext_service import BY_ID as TOP5, Top5Service, _numeric_row, CN
from seven_service import BY_ID as SEVEN, CODES as SEVEN_CODES
from web_top5_quality import Top5QualityGate, reviewed_volume_change
from web_market_revisions import RevisionGuard, POLICY as REVISION_POLICY


class WebTop5Service(Top5Service):
    """Append confirmed data while auditing and retaining accepted history."""
    def _quality_now(self):
        return datetime.now(CN)

    def _prepare_refresh(self, old, fresh):
        self._quality_gate = Top5QualityGate(self.folder, self._quality_now())
        prepared = self._quality_gate.prepare(old, fresh)
        guard = RevisionGuard(self.folder, self._quality_now(), self.settings['snapshot_id'])
        for collection, key in [('daily', 'date'), ('hourly', 'datetime')]:
            # Validate and observe the full source overlap even when the close
            # publication gate is temporarily holding back newly fetched rows.
            normalized = [_numeric_row(r, key) for r in fresh.get(collection, [])]
            retained = guard.retain(old[collection], normalized, key,
                ['open', 'high', 'low', 'close', 'volume'], 'sz159915', fresh.get('sources', []),
                exempt=reviewed_volume_change)
            allowed = {r[key] for r in prepared.get(collection, [])}
            prepared[collection] = [r for r in retained if r[key] in allowed]
        self._revision_metadata = guard.finish()
        if self._revision_metadata['retained_history_count']:
            prepared['warnings'] = list(prepared.get('warnings', [])) + [REVISION_POLICY]
        return prepared

    def _merge_rows(self, old, additions, key):
        old_map = {row[key]: row for row in old}
        observed = {}
        normalized = []
        for raw in additions:
            row = _numeric_row(raw, key)
            stamp = row[key]
            if stamp in observed and row != observed[stamp]:
                raise ValueError('来源重复返回不同的' + stamp + '行情，保留旧快照。')
            observed[stamp] = deepcopy(row)
            previous = old_map.get(stamp)
            if previous is not None:
                if reviewed_volume_change(previous, raw, key):
                    gate = getattr(self, '_quality_gate', None)
                    if gate is None or not gate.retain_reviewed_volume(previous, raw, key):
                        raise ValueError('历史成交量例外缺少持久审计，拒绝接续。')
                    row['volume'] = previous['volume']
                changed = [field for field in row if row[field] != previous.get(field)]
                if changed == ['amount']:
                    old_amount, new_amount = previous.get('amount'), row['amount']
                    # Match the native engine's existing representation tolerance;
                    # a CSV/JSON float round-trip is not a source revision.
                    diagnostic_revision = (old_amount is None or new_amount is None or
                        abs(new_amount - old_amount) > max(1e-8, 4 * math.ulp(old_amount)))
                    if diagnostic_revision:
                        item = dict(time=stamp, retained_amount=old_amount,
                                    source_amount=new_amount, prices_and_volume_identical=True)
                        if not hasattr(self, '_retained_amount_revisions'):
                            self._retained_amount_revisions = []
                        if item not in self._retained_amount_revisions:
                            self._retained_amount_revisions.append(item)
                    row['amount'] = previous.get('amount')
            normalized.append(row)
        return super()._merge_rows(old, normalized, key)

    def refresh(self, progress=None):
        with self._lock:
            return self._refresh_with_quality(progress)

    def _refresh_with_quality(self, progress=None):
        self._retained_amount_revisions = []
        result = super().refresh(progress)
        result['quality'] = self._quality_gate.result_metadata()
        result['history_revisions'] = self._revision_metadata
        if result['quality']['retained_volume_revisions']:
            result['warnings'] = list(result.get('warnings', [])) + [
                '已核验2026-09-30 15点来源成交量修订；按冻结历史政策保留原已接受值，'
                '并未采用来源修订量。审计记录已持久保存；不保证未来信号与修订行情相同。']
        if self._retained_amount_revisions:
            result['retained_amount_revisions'] = deepcopy(self._retained_amount_revisions)
            result['warnings'] = list(result.get('warnings', [])) + [
                '来源修订了' + str(len(self._retained_amount_revisions)) +
                '条历史成交金额；价格和成交量完全一致，保留历史金额原值，仅接受后续确认行情。']
        return result


class AutoSupport:
    PREVIEW_INTERVAL = 300

    def __init__(self, bridge, clock):
        self.b = bridge
        self.clock = clock
        self.source_errors = {}
        self.reference_cache = {}
        self.compatibility_cache = {}
        self.preview_key = None
        self.preview_built = 0
        self.preview_quote_at = None
        self.preview_computed_at = None
        self.quote_failed = False

    def _calendar(self):
        return self.b.top5._snapshot()['calendar']

    def daily_limit(self, moment):
        calendar = self._calendar()
        limit = min(bank_model.cutoff(moment), calendar['verified_through'])
        return max((day for day in calendar['sessions'] if day <= limit), default=None)

    def original_reference(self, code, capital):
        b = self.b
        amount = trade_book.number(capital, '参考本金', 1e9)
        if amount < 1000:
            raise ValueError('参考本金至少1000元')
        moment = self.clock()
        today = moment.date().isoformat()
        calendar = self._calendar()
        batch = b.live.batch
        use_live = False
        note = '当前无可用盘中报价，使用已确认收盘数据。'
        if batch and not self.quote_failed and today <= calendar['verified_through']:
            quotes = batch['quotes']
            stamps = [datetime.fromisoformat(q['quote_at']) for q in quotes.values()]
            use_live = (today in calendar['sessions'] and b.original.market.latest < today
                        and all(q['day'] == today and q['started'] for q in quotes.values())
                        and max(stamps) - min(stamps) <= timedelta(minutes=30)
                        and timedelta(0) <= moment - max(stamps) <= timedelta(hours=3))
            if not use_live:
                note = '盘中报价已过期、尚未开盘或已有正式日线，使用已确认收盘数据。'
        if use_live:
            key = (b.original.market.hash, today)
            if (self.preview_key != key or b.live.preview is None or
                    time.monotonic() - self.preview_built >= self.PREVIEW_INTERVAL):
                try:
                    b.live.preview = provisional_market(b.original.market, batch, moment)
                    b.live.observations = {}
                    self.preview_key = key
                    self.preview_built = time.monotonic()
                    self.preview_quote_at = max(q['quote_at'] for q in batch['quotes'].values())
                    self.preview_computed_at = moment.isoformat()
                except ValueError as exc:
                    use_live = False
                    note = str(exc) + '；使用已确认收盘数据。'
                    b.live.preview = None
            if use_live:
                if code not in b.live.observations:
                    b.live.observations[code] = deepcopy(
                        b.live.preview.observation(code, b.live.preview.latest))
                plan = b.live.plan(code, amount)
                b.live.preview_note = '盘中临时目标：指标最多每5分钟重算；不作为账户成交价格。'
                return dict(available=True, strategy=code, capital=amount,
                            as_of=plan['day'], basis='provisional',
                            computed_at=self.preview_computed_at,
                            quote_as_of=self.preview_quote_at,
                            refresh_interval_seconds=self.PREVIEW_INTERVAL,
                            weights=plan['observation']['weights'], budgets=plan['budgets'],
                            cash=plan['cash'], notes=[b.live.preview_note],
                            details=plan['observation'])
        b.live.preview = None
        b.live.observations = {}
        b.live.preview_note = note
        limit = self.daily_limit(moment)
        day = max((day for day in b.original.market.dates if limit and day <= limit), default=None)
        if day is None:
            return dict(available=False, strategy=code, capital=amount, as_of=None,
                        basis='unavailable', computed_at=moment.isoformat(),
                        weights={}, budgets={}, cash=None, notes=[note])
        key = ('original', b.original.market.hash, day, code, amount)
        if key in self.reference_cache:
            result = deepcopy(self.reference_cache[key])
            result['notes'][0] = note
            return result
        obs = deepcopy(b.original.market.observation(code, day))
        result = dict(available=True, strategy=code, capital=amount, as_of=day,
                    basis='confirmed_daily', computed_at=moment.isoformat(),
                    quote_as_of=None, weights=obs['weights'],
                    budgets={c: amount * obs['weights'][c] for c in trade_book.CODES},
                    cash=amount * max(0, 1 - sum(obs['weights'].values())),
                    notes=[note, '已确认收盘参考截至' + day + '；不是当前实时报价或已成交仓位。'],
                    details=obs)
        self.reference_cache[key] = deepcopy(result)
        while len(self.reference_cache) > 32:
            self.reference_cache.pop(next(iter(self.reference_cache)))
        return result

    def reference(self, code, capital, force=False):
        b = self.b
        if code in ORDER:
            if force:
                self.preview_key = None
            return b._reference(code, capital)
        if code in TOP5:
            source = b.top5.settings['snapshot_id']
        elif code in SEVEN:
            source = b.seven.settings['snapshot']
        else:
            raise ValueError('请选择21种参考策略之一。')
        key = (code, float(capital), source)
        if key not in self.reference_cache:
            value = b._reference(code, capital)
            value['basis'] = 'confirmed_bars'
            value['computed_at'] = self.clock().isoformat()
            self.reference_cache[key] = deepcopy(value)
            while len(self.reference_cache) > 32:
                self.reference_cache.pop(next(iter(self.reference_cache)))
        return deepcopy(self.reference_cache[key])

    def saved_reference(self):
        b = self.b
        code = b.original.settings.get('live_reference_strategy', 'T5VOTE')
        capital = b.original.settings.get('live_reference_capital', 100000)
        try:
            b.last_reference = self.reference(code, capital)
            return b.last_reference, None
        except Exception as exc:
            b.last_reference = None
            return None, '策略参考更新失败：' + str(exc)

    def quotes(self, params, stop, progress, update_reference=True):
        b = self.b
        b._check_stop(stop)
        progress('正在采集四只ETF真实报价…')
        result = dict(sources={}, notes=[], account_advanced=False)
        try:
            batch = fetch_quotes()
            b._check_stop(stop)
            b.live.store.save(batch)
            b.live.batch = batch
            self.quote_failed = False
            b.live.store.record_attempt('成功', '网页快速报价采集成功')
            result['sources']['quotes'] = dict(ok=True, received_at=batch['received_at'],
                quote_as_of=min(q['quote_at'] for q in batch['quotes'].values()))
        except InterruptedError:
            raise
        except Exception as exc:
            self.quote_failed = True
            self.preview_key = None
            b.live.preview = None
            b.live.observations = {}
            b.live.preview_note = '本次报价采集失败，显示上次保存的报价；' + str(exc)
            b.live.store.record_attempt('失败', str(exc))
            result['sources']['quotes'] = dict(ok=False, error=str(exc))
            result['notes'].append(b.live.preview_note)
        if update_reference:
            result['reference'], error = self.saved_reference()
            if error:
                result['notes'].append(error)
        result['ok'] = result['sources']['quotes']['ok']
        result['market'] = b._market_info()
        b.quote_notes = list(result['notes'])
        return result

    def refresh(self, params, stop, progress):
        b = self.b
        result = dict(sources={}, notes=[], account_advanced=False)
        if params.get('update_quotes', True):
            quoted = self.quotes(params, stop, progress, update_reference=False)
            result['sources'].update(quoted['sources'])
        if params.get('update_history', True):
            b._check_stop(stop)
            try:
                limit = self.daily_limit(self.clock())
                if params.get('force_history') or (limit and b.original.market.latest < limit):
                    note = b.original.update_market(progress=progress)
                else:
                    note = '暂无新的应确认交易日，保留已校验日线。'
                b.live.history_error = ''
                b.live.history_note = note
                self.source_errors.pop('original', None)
                result['sources']['daily'] = dict(ok=True, end=b.original.market.latest, note=note)
            except Exception as exc:
                b.live.history_error = str(exc)
                b.live.history_note = '收盘日线更新失败：' + str(exc)
                self.source_errors['original'] = b.live.history_note
                result['sources']['daily'] = dict(ok=False, end=b.original.market.latest, error=str(exc))
        if params.get('update_top5', True):
            b._check_stop(stop)
            try:
                row = b.top5.refresh(progress=progress)
                failures = [note for note in row.get('warnings', []) if '失败' in note]
                result['sources']['top5'] = dict(row, ok=not failures,
                    status='partial' if failures else ('updated' if row.get('updated') else 'unchanged'))
                if failures:
                    self.source_errors['top5'] = '；'.join(failures)
                else:
                    self.source_errors.pop('top5', None)
            except Exception as exc:
                self.source_errors['top5'] = str(exc)
                result['sources']['top5'] = dict(ok=False, error=str(exc))
        b._check_stop(stop)
        try:
            result['sources']['seven'] = dict(ok=True, **b.seven.sync())
            self.source_errors.pop('seven', None)
        except Exception as exc:
            self.source_errors['seven'] = str(exc)
            result['sources']['seven'] = dict(ok=False, error=str(exc))
        result['notes'] = [name + '：' + row['error'] for name, row in result['sources'].items()
                           if row.get('error')]
        for name, row in result['sources'].items():
            result['notes'].extend(name + '：' + note for note in row.get('warnings', []))
        result['reference'], reference_error = self.saved_reference()
        if reference_error:
            result['notes'].append(reference_error)
        b.refresh_notes = result['notes']
        result['ok'] = all(row.get('ok', False) for row in result['sources'].values())
        result['market'] = b._market_info()
        return result

    def _extension_error(self, group, old_key, new_key, state):
        if old_key == new_key:
            return None
        through = (state.get('through') if group == 'top5' else
                   state['result']['end'] if group == 'seven' else None)
        key = (group, old_key, new_key, through)
        if key in self.compatibility_cache:
            return self.compatibility_cache[key]
        b = self.b
        error = None
        try:
            if group == 'original':
                if amount_only_extension(b.original.market_by_hash(old_key), b.original.market) is None:
                    raise ValueError('新行情修订了账户配套历史；原账户和待执行目标保持不变。')
            elif group == 'top5':
                b.top5._assert_extension(b.top5._snapshot(old_key), b.top5._snapshot(new_key), state['through'])
            else:
                old, new = b.seven.snapshot(old_key), b.seven.snapshot(new_key)
                for code in SEVEN_CODES:
                    if old['bars'][code] != new['bars'][code][:len(old['bars'][code])]:
                        raise ValueError('七组合既有日线发生修订。')
                    end = old['bars'][code][-1]['date']
                    if {k:v for k,v in old['splits'][code].items() if k <= end} != {
                            k:v for k,v in new['splits'][code].items() if k <= end}:
                        raise ValueError('七组合历史份额折算发生修订。')
                    prior = lambda rows: [r for r in rows if min(r.get(k, '9999') for k in ('record','ex','pay')) <= end]
                    if prior(old['actions'][code]['dividends']) != prior(new['actions'][code]['dividends']):
                        raise ValueError('七组合历史分红发生修订。')
                if old['hourly'] != new['hourly'][:len(old['hourly'])]:
                    raise ValueError('七组合既有60分钟柱发生修订。')
                end = state['result']['end']
                if [d for d in old['calendar']['sessions'] if d <= end] != [d for d in new['calendar']['sessions'] if d <= end]:
                    raise ValueError('七组合既有交易日历发生修订。')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            error = str(exc)
        self.compatibility_cache[key] = error
        while len(self.compatibility_cache) > 128:
            self.compatibility_cache.pop(next(iter(self.compatibility_cache)))
        return error

    def candidate(self, group, identity):
        b = self.b
        group = b._group(group)
        moment = self.clock()
        calendar = self._calendar()
        known = set(calendar['sessions'])
        limit = self.daily_limit(moment)
        target = None
        if group == 'original':
            state = b.original.book.get(identity)
            current = state['day']
            code = state['auto']['strategy']
            old_key = state['simulator']['market']
            new_key = b.original.market.hash
            target = max((d for d in b.original.market.dates if limit and d <= limit and d in known), default=None)
        elif group == 'top5':
            state = b.top5._load_account(identity)
            current = state['through']
            code = state['strategy_id']
            old_key, new_key = state['snapshot_id'], b.top5.settings['snapshot_id']
            cutoff = (moment - timedelta(seconds=60)).strftime('%Y-%m-%d %H:%M:%S')
            target = max((r['datetime'] for r in b.top5._snapshot()['hourly']
                          if r['datetime'] <= cutoff and r['datetime'][:10] in known), default=None)
        else:
            state = b.seven.get_account(identity)
            current = state['result']['end']
            code = state['result']['strategy']
            old_key, new_key = state['result']['snapshot'], b.seven.settings['snapshot']
            snap = b.seven.snapshot()
            hours = {}
            for row in snap['hourly']:
                hours.setdefault(row['datetime'][:10], set()).add(row['datetime'][11:])
            full = {d for d, values in hours.items() if values == {'10:30:00','11:30:00','14:00:00','15:00:00'}}
            common = full.intersection(known, *[{r['date'] for r in snap['bars'][c]} for c in SEVEN_CODES])
            target = max((d for d in common if limit and d <= limit), default=None)
        row = dict(group=group, id=identity, name=state['name'], strategy=code, current=current,
                   target=target, can_advance=False, market_key=new_key,
                   requires_attach=(group == 'original' and old_key != new_key), reason='')
        if moment.date().isoformat() > calendar['verified_through']:
            row['reason'] = '交易日历仅核验至' + calendar['verified_through'] + '，暂停自动推进。'
        elif group == 'original' and state['auto'].get('execution', 'auto') != 'auto':
            row['reason'] = '此账户为手动演练模式，保持暂停。'
        elif self.source_errors.get(group):
            row['reason'] = '本组行情更新失败，保留账户：' + self.source_errors[group]
        elif group == 'seven' and any(self.source_errors.get(g) for g in ('original', 'top5')):
            row['reason'] = '七组合依赖的确认行情更新失败，等待下次成功核验。'
        elif not target or (current and target <= current):
            row['reason'] = '尚无晚于账户日期的已确认完整数据。'
        else:
            error = self._extension_error(group, old_key, new_key, state)
            row['reason'] = error or ('等待按原规则推进至' + target)
            row['can_advance'] = error is None
        return row

    def candidates(self):
        b = self.b
        result = []
        identities = {'original': [row['id'] for row in b.original.book.list()],
                      'top5': [row['id'] for row in b.top5.list_accounts()],
                      'seven': [row['id'] for row in b.seven.accounts()]}
        for group, ids in identities.items():
            for identity in ids:
                try:
                    result.append(self.candidate(group, identity))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    result.append(dict(group=group, id=identity, can_advance=False,
                                       target=None, current=None, reason='账户核验失败：' + str(exc)))
        return result

    def attach_original_extension(self, identity, *, event_kind='自动更新配套行情', note='仅追加确认行情；保留既有待执行目标与收盘分析。'):
        """One path for manual/automatic continuation; never replay old trades."""
        b=self.b
        with b.original.book.lease(identity):
            with b.original.book.connection() as con:
                state=b.original.book.get(identity,con)
                old=b.original.account_market(state)
                extended,changes=b.original.extension_market(old)
                if old.hash!=extended.hash:
                    state['simulator']['market']=extended.hash
                    if changes:note+=' 来源修订的'+str(len(changes))+'条历史成交金额保留原值；价格、成交量与公司行动核对一致。'
                    b.original.book.event(con,state,event_kind,dict(previous=old.hash,current=extended.hash,
                        source_market=b.original.market.hash,end=extended.latest,
                        retained_amount_revisions=changes,note=note))
                    b.original.book.save(con,state)
        return extended

    def advance(self, params, stop, progress):
        b = self.b
        group, identity = b._group(params.get('group')), params['id']
        b._check_stop(stop)
        row = self.candidate(group, identity)
        result = dict(row, advanced=False, previous=row['current'], day=row['current'])
        if not row['can_advance']:
            return result
        target = row['target']
        progress('自动模拟：按已确认行情推进至' + target)
        if group == 'original':
            if row['requires_attach']:
                # Native update_market also clears pending and re-evaluates the
                # old day. Automatic extension instead preserves its confirmed
                # intent/evidence, last_target, and evaluated date verbatim.
                self.attach_original_extension(identity)
            b._check_stop(stop)
            b.original.run(identity, target, stop=stop, progress=progress)
            summary = b._original_summary(identity)
        elif group == 'top5':
            detail = b.top5.advance_account(identity, target)
            summary = b._top5_summary(detail['account'])
        else:
            account = b.seven.advance(identity, target)
            summary = b._seven_summary(account)
        result.update(day=summary['day'], summary=summary,
                      advanced=summary['day'] != row['current'],
                      reason='已按原策略规则推进至' + summary['day'])
        return result
