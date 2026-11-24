"""Versioned public-data updates; never infer corporate-action clearance.

Network updates append raw ETF/index observations.  Official action review is
an independent, explicit package-import workflow.  A directory is published
only after all parsers, overlap checks and application validators pass.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import json
import math
import os
import re
import shutil
import threading
import uuid
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

if __package__:
    from .core import Environment, SECTORS
    from .opportunity import Opportunity
else:
    from core import Environment, SECTORS
    from opportunity import Opportunity

FILES = ('market.json', 'index_data.json', 'verified_actions.json', 'calendar_2026.json')
QQ = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get'
CSI = 'https://www.csindex.com.cn/csindex-home/perf/index-perf'
SHANGHAI = timezone(timedelta(hours=8))
OFFICIAL_HOSTS = ('sse.com.cn', 'szse.cn', 'cninfo.com.cn', 'csrc.gov.cn',
                  'efunds.com.cn', 'gffunds.com.cn', 'funds.gtfund.com', 'gtfund.com',
                  'huabao-fund.com', 'hwabao.com', 'funds.hwabao.com',
                  'csfunds.com.cn', 'southernfund.com', 'csindex.com.cn', '99fund.com',
                  'fsfund.com', 'nffund.com', 'chinaamc.com')


class UpdateError(ValueError):
    pass


class ActionIdentityError(UpdateError):
    def __init__(self, code, title_codes, body_codes, response_hash):
        self.pending = {'code': code, 'kind': 'source_identity_conflict',
                        'reason': '公司行动来源标题或分红正文基金身份不一致；不能据此归属事件',
                        'title_codes': title_codes, 'body_codes': body_codes,
                        'response_sha256': response_hash}
        super().__init__(code + ' 公司行动来源基金身份不一致，已保留原始响应等待复核')


def _stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _json(data):
    return json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(UpdateError('非法 JSON 数值: ' + value)))


def _read(path):
    return _json(Path(path).read_text(encoding='utf-8-sig'))


def _write(path, value):
    path = Path(path)
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise UpdateError('无效行情日期')
    datetime.strptime(value, '%Y-%m-%d')
    return value


def _finite(value, positive=False):
    if isinstance(value, bool):
        raise UpdateError('布尔值不是价格或成交额')
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise UpdateError('无效数值') from exc
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise UpdateError('价格/成交量/成交额无效')
    return value


def pending_id(item):
    fields = {k: v for k, v in item.items() if k != 'pending_id'}
    return sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:24]


def parse_tencent(data, code):
    text = data.decode('utf-8-sig') if isinstance(data, bytes) else data
    if not text.lstrip().startswith('{'):
        if '=' not in text:
            raise UpdateError('腾讯响应没有 JSON 数据')
        text = text.split('=', 1)[1]
    obj = _json(text.rstrip().rstrip(';'))
    if obj.get('code') != 0:
        raise UpdateError('腾讯行情服务返回错误')
    raw = obj.get('data', {}).get(code, {}).get('day')
    if not isinstance(raw, list) or not raw:
        raise UpdateError(code + ' 未返回未复权 day 行情')
    rows = []
    for line in raw:
        if not isinstance(line, list) or len(line) < 9:
            raise UpdateError(code + ' 行情字段不足，不能猜测成交额单位')
        row = dict(date=_date(line[0]), open=_finite(line[1], True), close=_finite(line[2], True),
                   high=_finite(line[3], True), low=_finite(line[4], True),
                   volume_lots=_finite(line[5]), amount_cny=_finite(line[8]) * 10000)
        if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
            raise UpdateError(code + ' OHLC 不一致')
        shares = row['volume_lots'] * 100.0
        tolerance = 100.0 + 50.0 * row['high']
        if not row['low'] * shares - tolerance <= row['amount_cny'] <= row['high'] * shares + tolerance:
            raise UpdateError(code + ' 成交额、份数与日内价格范围不一致，疑似单位或字段变化')
        rows.append(row)
    _ordered(rows)
    return rows


def parse_csi(data, code):
    obj = _json(data.decode('utf-8-sig') if isinstance(data, bytes) else data)
    if str(obj.get('code')) != '200' or not isinstance(obj.get('data'), list) or not obj['data']:
        raise UpdateError('中证指数响应为空或失败')
    rows = []
    for item in obj['data']:
        if item.get('indexCode') != code:
            raise UpdateError('中证响应指数身份不一致')
        d = str(item.get('tradeDate', ''))
        if not re.fullmatch(r'\d{8}', d):
            raise UpdateError('中证指数日期无效')
        row = {'date': _date(d[:4]+'-'+d[4:6]+'-'+d[6:]), 'close': _finite(item.get('close'), True)}
        for key in ('open', 'high', 'low'):
            value = item.get(key)
            if code == '000985' and value is None:
                raise UpdateError('价格指数缺少完整 OHLC')
            row[key] = None if value is None else _finite(value, True)
        rows.append(row)
    rows.sort(key=lambda row: row['date'])
    _ordered(rows)
    return rows


def _ordered(rows):
    if any(a['date'] >= b['date'] for a, b in zip(rows, rows[1:])):
        raise UpdateError('行情日期重复或未按时间排序')


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_action_discovery(data, code=None):
    text = data.decode('utf-8-sig') if isinstance(data, bytes) else data
    if '拆分详情' not in text or '分红送配详情' not in text:
        raise UpdateError('公司行动发现页结构改变，不能把未解析视作无事件')
    if code is not None:
        # A live response had the requested ETF in <title>, but another fund's
        # annual summary and dividend table. Do not trust the URL/title alone.
        title = re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I)
        title_codes = re.findall(r'[（(](\d{6})[）)]', title.group(1) if title else '')
        prefix = text[:text.index('分红送配详情')]
        labels = re.findall(r'<label\b[^>]*>(.*?)</label>', prefix, re.S | re.I)
        annual = [label for label in labels if re.search(r'\d{4}年度', label)]
        body_codes = re.findall(r'fund\.eastmoney\.com/(\d{6})\.html', annual[-1] if annual else '')
        if title_codes != [code[2:]] or body_codes != [code[2:]]:
            raw = data if isinstance(data, bytes) else data.encode('utf-8')
            raise ActionIdentityError(code, title_codes, body_codes, sha256(raw).hexdigest())
    parser = _TableParser()
    parser.feed(text)
    events = []
    for row in parser.rows:
        if len(row) == 5 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[1]):
            amount = re.search(r'派现金([\d.]+)', row[3])
            if not amount:
                raise UpdateError('分红发现行无法识别')
            events.append({'kind': 'cash_dividend', 'record_date': _date(row[1]),
                           'ex_date': _date(row[2]), 'cash_per_share': _finite(amount.group(1), True)/10,
                           'pay_date': _date(row[4])})
        elif len(row) == 4 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[1]):
            value = re.search(r'[:：]\s*([\d.]+)', row[3])
            if not value:
                raise UpdateError('拆分发现行无法识别')
            events.append({'kind': 'split', 'vendor_date': _date(row[1]), 'ratio': _finite(value.group(1), True),
                           'date_boundary': '供应商拆分折算日，不直接视为除权实施日'})
    return {'events': events, 'official_clearance': False,
            'boundary': '第三方发现页；无新记录不构成官方无事件证明，不自动延长核验覆盖。'}


def public_fetch(url, headers, timeout):
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        if response.status != 200:
            raise UpdateError('公开来源 HTTP 状态异常')
        result = response.read(16 * 1024 * 1024 + 1)
    if len(result) > 16 * 1024 * 1024:
        raise UpdateError('来源响应超过大小限制')
    return result


class DataUpdater:
    """A single-flight updater for one isolated application data store.

    validator(candidate_dir) runs before publication.  on_publish(active_dir)
    runs after atomic pointer commit and should swap prebuilt app instances;
    callback errors restore the prior pointer and are reported as failures.
    Neither callback is allowed to write into a version directory.
    """

    def __init__(self, seed_data_dir, store_dir, validator=None, on_publish=None, fetcher=None, clock=None):
        self.seed_data_dir = Path(seed_data_dir).resolve()
        self.store_dir = Path(store_dir).resolve()
        if self.store_dir == self.seed_data_dir or self.seed_data_dir in self.store_dir.parents:
            raise UpdateError('更新目录必须在种子数据目录之外')
        self.store_dir.mkdir(parents=True, exist_ok=True)
        for name in ('versions', 'staging', 'attempts'):
            (self.store_dir/name).mkdir(exist_ok=True)
        self.validator, self.on_publish = validator, on_publish
        self.fetcher, self.clock = fetcher or public_fetch, clock or (lambda: datetime.now(SHANGHAI))
        self._mutex, self._state_lock = threading.Lock(), threading.RLock()
        self._stop, self._scheduler = threading.Event(), None
        self._worker = None
        self._closed, self._run_thread = False, None
        self._interval = None
        self._active = self.seed_data_dir
        self._state = {'schema': 'sector-data-update.status.v1', 'running': False, 'automatic_enabled': False,
                       'state': 'not_checked', 'message': '尚未执行联网核对', 'generation': 'seed',
                       'last_attempt_at': None, 'last_success_at': None, 'pending_review': [],
                       'action_policy': '公司行动核验截止不因行情刷新或第三方空记录而自动延长'}
        prior_status = self.store_dir/'status.json'
        if prior_status.exists():
            try:
                prior = _read(prior_status)
                if not isinstance(prior, dict) or prior.get('schema') != self._state['schema']:
                    raise UpdateError('状态 schema 无效')
                for key in ('last_attempt_at', 'last_success_at'):
                    value = prior.get(key)
                    if value is not None and (not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None):
                        raise UpdateError('状态时间无效')
                if 'pending_review' not in prior or ('publication_blocked' in prior and not isinstance(prior['publication_blocked'], bool)):
                    raise UpdateError('状态缺少待核验队列或发布阻断类型无效')
                pending = prior['pending_review']
                if not isinstance(pending, list):
                    raise UpdateError('待核验队列必须是数组')
                for item in pending:
                    if not isinstance(item, dict) or not isinstance(item.get('reason'), str) or not item['reason'].strip():
                        raise UpdateError('待核验记录结构无效')
                    if item.get('pending_id') != pending_id(item):
                        raise UpdateError('待核验记录身份校验失败')
                    if item.get('kind'):
                        if item.get('code') not in {c for c, _ in SECTORS} or item['kind'] not in ('cash_dividend', 'split', 'source_identity_conflict'):
                            raise UpdateError('待核验事件种类或ETF无效')
                        if item['kind'] == 'cash_dividend':
                            for field in ('record_date', 'ex_date', 'pay_date'):
                                _date(item.get(field))
                            _finite(item.get('cash_per_share'), True)
                        elif item['kind'] == 'split':
                            _date(item.get('vendor_date'))
                            _finite(item.get('ratio'), True)
                        elif (not re.fullmatch(r'[0-9a-f]{64}', str(item.get('response_sha256', '')))
                              or any(not isinstance(item.get(k), list) or any(not isinstance(c, str) or not re.fullmatch(r'\d{6}', c) for c in item[k]) for k in ('title_codes', 'body_codes'))):
                            raise UpdateError('来源身份冲突证据结构无效')
                    else:
                        _date(item.get('from')); _date(item.get('through'))
                        if item.get('codes') != [c for c, _ in SECTORS]:
                            raise UpdateError('覆盖缺口ETF清单无效')
                if not isinstance(prior.get('sources', []), list) or any(not isinstance(item, dict) for item in prior.get('sources', [])):
                    raise UpdateError('状态来源记录无效')
                for key in ('last_attempt_at', 'last_success_at', 'pending_review', 'sources'):
                    if key in prior:
                        self._state[key] = prior[key]
                if prior.get('publication_blocked') is True:
                    self._state.update(publication_blocked=True, state='store_invalid',
                                       status_warning=str(prior.get('status_warning') or prior.get('message') or '上次更新状态已禁止发布，须先核查本地更新目录'))
            except (ValueError, OSError, TypeError):
                try:
                    preserved = self.store_dir/('status.invalid.'+uuid.uuid4().hex+'.json')
                    shutil.copy2(prior_status, preserved)
                    self._state['invalid_status_evidence'] = preserved.name
                except OSError:
                    self._state['invalid_status_evidence'] = '原状态文件无法复制；请保留原文件进行恢复'
                self._state.update(state='store_invalid', publication_blocked=True,
                                   status_warning='上次更新状态文件无效；原始数据保留，发布暂停，不能丢弃可能的待核验记录后声称完整可用')
        elif (self.store_dir/'current.json').exists() or any((self.store_dir/'attempts').iterdir()):
            self._state.update(state='store_invalid', publication_blocked=True,
                               status_warning='已有更新记录但状态文件缺失；保留数据并暂停发布，须核查可能丢失的待核验事项')
        self._load_pointer()
        if self._state.get('publication_blocked') and self._state.get('status_warning'):
            self._state.update(state='store_invalid', message=self._state['status_warning'])
        self._refresh_dates()

    @property
    def active_data_dir(self):
        with self._state_lock:
            return self._active

    def _now(self):
        now = self.clock()
        if now.tzinfo is None:
            raise UpdateError('更新时钟必须包含时区')
        return now.astimezone(SHANGHAI)

    def _load_pointer(self):
        pointer = self.store_dir/'current.json'
        if not pointer.exists():
            Environment(self.seed_data_dir)
            return
        try:
            data = _read(pointer)
            generation = data['generation']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', generation):
                raise UpdateError('非法版本路径')
            path = (self.store_dir/'versions'/generation).resolve()
            if path.parent != (self.store_dir/'versions').resolve():
                raise UpdateError('版本路径越界')
            if _hash(path/'manifest.json') != data.get('manifest_sha256'):
                raise UpdateError('已发布版本 manifest 哈希不一致')
            manifest = _read(path/'manifest.json')
            if manifest.get('generation') != generation or not set(FILES).issubset(manifest.get('files', {})):
                raise UpdateError('已发布版本清单不完整')
            for filename, expected_hash in manifest['files'].items():
                item = (path/filename).resolve()
                if path not in item.parents or item.is_symlink() or _hash(item) != expected_hash:
                    raise UpdateError('已发布版本文件哈希不一致')
            Environment(path)
            Opportunity(Environment(path))
            self._active = path
            self._state.update(generation=generation, state='loaded', message='已载入上次发布的数据版本')
        except Exception as exc:
            # Never silently overwrite a corrupt pointer with seed data.
            self._state.update(state='store_invalid', message='已发布版本损坏，暂用原始种子；请检查更新目录',
                               error=str(exc), publication_blocked=True)
            Environment(self.seed_data_dir)

    def _refresh_dates(self):
        env = Environment(self._active)
        self._date_env = env
        now = self._now()
        expected = env._expected(now)
        snapshot = env.snapshot(now=now)
        self._state.update(data_through=snapshot['snapshot_date'], expected_date=expected,
                           action_verified_through=env._action_through,
                           calendar_verified_through=env._calendar_verified_until,
                           active_data_dir=str(self._active),
                           fully_usable=bool(expected is not None and snapshot['snapshot_date'] == expected
                                             and expected <= env._action_through and not self._state['pending_review']
                                             and not self._state.get('publication_blocked')))

    def status(self):
        with self._state_lock:
            result = deepcopy(self._state)
            if hasattr(self, '_date_env'):
                expected = self._date_env._expected(self._now())
                result['expected_date'] = expected
                date_current = expected is not None and result['data_through'] == expected
                result['fully_usable'] = bool(result.get('fully_usable') and date_current)
                if not date_current and result['state'] in ('current', 'loaded', 'not_checked'):
                    result['state'] = 'stale'
                    result['message'] = ('交易日历未覆盖当前日期，等待新日历核验' if expected is None
                                         else '已发布行情落后当前应完成交易日；请更新或检查来源')
            result['automatic_enabled'] = self._scheduler is not None and self._scheduler.is_alive()
            result['interval_seconds'] = self._interval
            result['closed'] = self._closed
            return result

    def _persist_status(self):
        _write(self.store_dir/'status.json', self.status())

    def _download(self, key, url, folder):
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/html,*/*',
                   'Referer': 'https://www.csindex.com.cn/' if 'csindex.com.cn' in url else 'https://gu.qq.com/'}
        began = _stamp(self._now())
        data = self.fetcher(url, headers, 25)
        if not isinstance(data, bytes) or not data:
            raise UpdateError(key + ' 没有返回原始字节')
        if len(data) > 16*1024*1024:
            raise UpdateError('来源响应过大')
        raw = folder/(key+'.raw')
        raw.write_bytes(data)
        receipt = {'key': key, 'url': url, 'started_utc': began, 'finished_utc': _stamp(self._now()),
                   'bytes': len(data), 'sha256': sha256(data).hexdigest(), 'raw_file': raw.name,
                   'transport': 'public HTTPS response; data dates checked separately'}
        _write(folder/(key+'.receipt.json'), receipt)
        return data, receipt

    def _merge(self, old, fresh, start, expected, calendar, label):
        # Tencent often ignores requested start; CSI may return holiday fillers.
        selected = [row for row in fresh if start <= row['date'] <= expected and row['date'] in calendar]
        dates = {row['date'] for row in selected}
        required = {day for day in calendar if start <= day <= expected}
        if dates != required:
            raise UpdateError(label+' 来源未覆盖完整请求窗口: '+','.join(sorted(required-dates)[:8]))
        previous = {row['date']: row for row in old}
        overlap = 0
        for row in selected:
            if row['date'] in previous:
                overlap += 1
                prior = previous[row['date']]
                for key, value in row.items():
                    if key == 'date':
                        continue
                    known = prior.get(key)
                    if value is None or known is None:
                        equal = value == known
                    else:
                        equal = math.isclose(value, known, rel_tol=1e-12, abs_tol=1e-7)
                    if not equal:
                        raise UpdateError(f'{label} 历史重叠不一致 {row["date"]} {key}；保留旧版等待复核')
        if not overlap:
            raise UpdateError(label+' 缺少与旧版的重叠核对')
        added = [row for row in selected if row['date'] not in previous]
        merged = sorted(old + added, key=lambda row: row['date'])
        return merged, {'overlap_rows': overlap, 'added_rows': len(added),
                        'ignored_outside_request_or_calendar': len(fresh)-len(selected)}

    def _candidate_network(self, folder):
        env = Environment(self._active)
        now = self._now()
        expected = env._expected(now)
        if expected is None:
            raise UpdateError('calendar_required: 当前年度交易日历未核验，不能推断应完成日期')
        common = env.snapshot(now=now)['snapshot_date']
        if common > expected:
            raise UpdateError('当前数据晚于应完成日期')
        end = env._calendar_pos[common]
        start = env._calendar[max(0, end-19)]
        if env._calendar_pos[expected] - env._calendar_pos[start] >= 620:
            raise UpdateError('积压超过单次可验证窗口，请导入完整审核包')
        sources = folder/'sources'
        sources.mkdir()
        jobs = {}
        for code, _ in SECTORS:
            jobs['tencent_'+code] = QQ+'?'+urlencode({'_var': 'sector_update', 'param': f'{code},day,{start},{expected},640,'})
            jobs['actions_'+code] = f'https://fundf10.eastmoney.com/fhsp_{code[2:]}.html'
        for code in ('000985', 'H00985'):
            jobs['csi_'+code] = CSI+'?'+urlencode({'indexCode': code, 'startDate': start.replace('-', ''), 'endDate': expected.replace('-', '')})
        outputs, failures = {}, []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self._download, key, url, sources): key for key, url in jobs.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    outputs[key] = future.result()
                except Exception as exc:
                    failures.append(key+': '+str(exc))
        if failures:
            raise UpdateError('部分公开来源失败；旧版保留。'+' | '.join(failures))
        market, index = _read(self._active/'market.json'), _read(self._active/'index_data.json')
        # Disappearing supplier rows do not resolve an official-review queue.
        old_pending = self._state.get('pending_review', [])
        pending = [deepcopy(item) for item in old_pending if isinstance(item, dict) and item.get('kind')]
        diagnostics, discoveries = {}, {}
        added = 0
        for code, _ in SECTORS:
            key = 'tencent_'+code
            bars, diagnostic = self._merge(market['assets'][code]['bars'], parse_tencent(outputs[key][0], code),
                                            start, expected, env._calendar_set, code)
            market['assets'][code]['bars'] = bars
            diagnostics[code] = diagnostic
            added += diagnostic['added_rows']
            discovery = parse_action_discovery(outputs['actions_'+code][0], code)
            discoveries[code] = discovery
            for event in discovery['events']:
                event_date = event.get('ex_date', event.get('vendor_date'))
                if event_date > env._action_through:
                    pending.append({'code': code, 'reason': '供应商发现新事件，实施日期与条款待官方核验', **event})
                else:
                    asset = market['assets'][code]
                    if event['kind'] == 'cash_dividend':
                        matches = [known for known in asset['dividends'] if
                                   all(known.get(k) == event[k] for k in ('record_date', 'ex_date', 'pay_date'))
                                   and math.isclose(known['cash_per_share'], event['cash_per_share'], abs_tol=1e-10)]
                    else:
                        matches = [known for known in asset['splits'] if
                                   (event['vendor_date'] in (known['record_date'], known['ex_date'])
                                    or (env._known_suspension(code, event['vendor_date'])
                                        and known['ex_date'] == '2021-03-29'))
                                   and math.isclose(known['ratio'], event['ratio'], abs_tol=1e-10)]
                    if not matches:
                        pending.append({'code': code, 'reason': '供应商历史事件与已核验清单不一致，等待复核', **event})
        for code, series in (('000985', 'CSI_ALL_PRICE'), ('H00985', 'CSI_ALL_TR')):
            key = 'csi_'+code
            rows, diagnostic = self._merge(index['series'][series], parse_csi(outputs[key][0], code),
                                           start, expected, env._calendar_set, code)
            index['series'][series] = rows
            diagnostics[series] = diagnostic
            added += diagnostic['added_rows']
            receipt = deepcopy(outputs[key][1])
            receipt['relative_path'] = 'sources/'+receipt['raw_file']
            history = index.setdefault('source_history', [])
            for prior in index['sources']:
                if prior.get('key') == key and prior not in history:
                    history.append(deepcopy(prior))
            index['sources'] = [r for r in index['sources'] if r.get('key') != key] + [receipt]
        if expected > env._action_through:
            pending.insert(0, {'reason': '新增行情超过公司行动核验截止；十只ETF需要完整覆盖复核',
                               'from': env._action_through, 'through': expected, 'codes': [c for c, _ in SECTORS]})
        distinct = {}
        for item in pending:
            item['pending_id'] = pending_id(item)
            distinct[item['pending_id']] = item
        pending = list(distinct.values())
        report = {'schema': 'sector-data-update.attempt.v1', 'checked_at': _stamp(now),
                  'expected_date': expected, 'request_start': start, 'new_observations': added,
                  'diagnostics': diagnostics, 'action_discovery': discoveries, 'pending_review': pending,
                  'sources': [r for _, r in outputs.values()], 'action_verified_through': env._action_through,
                  'fully_usable': expected <= env._action_through and not pending}
        _write(folder/'update_report.json', report)
        if not added:
            return report, False
        market['calendar'] = [day for day in env._calendar if day <= expected]
        market['updated_utc'] = _stamp(now)
        market['data_update'] = {'method': 'append-only public sources with overlap validation',
                                 'expected_date': expected, 'action_coverage_extended': False}
        if 'checks' in market:
            market['seed_checks'] = market.pop('checks')
        index['frozen_utc'], index['requested_end'] = _stamp(now), expected
        _write(folder/'market.json', market)
        _write(folder/'index_data.json', index)
        for filename in ('verified_actions.json', 'calendar_2026.json'):
            shutil.copy2(self._active/filename, folder/filename)
        return report, True

    def _publish(self, folder, report, kind):
        Environment(folder)
        Opportunity(Environment(folder))
        if self.validator:
            self.validator(folder)
        generation = self._now().strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:10]
        manifest = {'schema': 'sector-data-version.v1', 'generation': generation, 'kind': kind,
                    'published_at': _stamp(self._now()), 'previous_generation': self._state['generation'],
                    'files': {path.relative_to(folder).as_posix(): _hash(path)
                              for path in sorted(folder.rglob('*')) if path.is_file()},
                    'data_through': report['expected_date'], 'action_verified_through': report['action_verified_through'],
                    'fully_usable': report['fully_usable'], 'pending_review': report['pending_review']}
        _write(folder/'manifest.json', manifest)
        final = self.store_dir/'versions'/generation
        os.replace(folder, final)
        pointer = self.store_dir/'current.json'
        old_pointer = pointer.read_bytes() if pointer.exists() else None
        try:
            _write(pointer, {'schema': 'sector-data-pointer.v1', 'generation': generation,
                             'manifest_sha256': _hash(final/'manifest.json')})
            if self.on_publish:
                self.on_publish(final)
        except Exception:
            if old_pointer is None:
                pointer.unlink(missing_ok=True)
            else:
                rollback = pointer.with_name('current.rollback.tmp')
                rollback.write_bytes(old_pointer)
                os.replace(rollback, pointer)
            raise
        with self._state_lock:
            self._active = final
            self._state['generation'] = generation
        return final

    def _process_lock(self):
        handle = (self.store_dir/'update.lock').open('a+b')
        try:
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            handle.close()
            return None

    def _run(self, reason, builder, kind):
        if not self._mutex.acquire(blocking=False):
            return {**self.status(), 'accepted': False, 'message': '已有数据更新正在运行'}
        self._run_thread = threading.current_thread()
        folder = self.store_dir/'staging'/uuid.uuid4().hex
        process_lock = None
        try:
            with self._state_lock:
                if self._closed:
                    return {**self.status(), 'accepted': False, 'message': '数据更新器已关闭'}
            process_lock = self._process_lock()
            if process_lock is None:
                return {**self.status(), 'accepted': False, 'message': '另一个程序实例正在更新此数据目录'}
            if (self.store_dir/'current.json').exists():
                self._load_pointer()
            folder.mkdir()
            with self._state_lock:
                if self._state.get('publication_blocked'):
                    raise UpdateError('当前版本指针损坏，先修复更新目录，禁止覆盖故障证据')
                self._state.update(running=True, state='updating', message='正在抓取和核对来源',
                                   reason=reason, last_attempt_at=_stamp(self._now()), error=None)
            self._persist_status()
            report, changed = builder(folder)
            if changed:
                self._publish(folder, report, kind)
            else:
                os.replace(folder, self.store_dir/'attempts'/folder.name)
            with self._state_lock:
                usable = report['fully_usable']
                self._state.update(state='current' if usable else 'needs_action_verification',
                                   message=('已核对公开来源，行情覆盖应完成日期' if usable else
                                            '行情已核对；公司行动待核验，不能认定全部板块指标可用于新增交易判断'),
                                   last_success_at=_stamp(self._now()), pending_review=report['pending_review'],
                                   fully_usable=usable, new_observations=report.get('new_observations', 0),
                                   sources=report.get('sources', []))
                self._refresh_dates()
        except Exception as exc:
            with self._state_lock:
                if isinstance(exc, ActionIdentityError):
                    item = exc.pending
                    item['pending_id'] = pending_id(item)
                    queue = {p['pending_id']: p for p in self._state['pending_review']}
                    queue[item['pending_id']] = item
                    self._state['pending_review'] = list(queue.values())
                self._state.update(state='failed', message='本次更新失败；继续保留先前已发布版本', error=str(exc))
                try:
                    self._refresh_dates()
                except Exception as refresh_error:
                    self._state.update(fully_usable=False, status_warning=str(refresh_error))
            if folder.exists():
                _write(folder/'failure.json', {'at': _stamp(self._now()), 'error': str(exc)})
                os.replace(folder, self.store_dir/'attempts'/folder.name)
        finally:
            with self._state_lock:
                self._state['running'] = False
            try:
                if process_lock is not None:
                    self._persist_status()
            except OSError as exc:
                with self._state_lock:
                    self._state['status_persistence_error'] = str(exc)
            finally:
                if process_lock is not None:
                    process_lock.close()
                self._run_thread = None
                self._mutex.release()
        return {**self.status(), 'accepted': True}

    def update_now(self, reason='manual'):
        return self._run(reason, self._candidate_network, 'network_raw_data')

    def request_update(self, reason='manual'):
        with self._state_lock:
            if self._closed:
                return {**self.status(), 'accepted': False, 'message': '数据更新器已关闭'}
            if self._mutex.locked() or (self._worker is not None and self._worker.is_alive()):
                return {**self.status(), 'accepted': False}
            self._worker = threading.Thread(target=self.update_now, args=(reason,), daemon=True, name='sector-data-update')
            self._worker.start()
            return {**self.status(), 'accepted': True}

    def start(self, interval_seconds=1800):
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (float, int)) or not 300 <= interval_seconds <= 86400:
            raise UpdateError('定时更新间隔须在300到86400秒之间')
        with self._state_lock:
            if self._closed:
                raise UpdateError('数据更新器已关闭，不能重启')
            if self._scheduler is not None and self._scheduler.is_alive():
                return self.status()
            self._stop.clear()
            self._interval = interval_seconds
            def loop():
                self.request_update('scheduled_start')
                while not self._stop.wait(interval_seconds):
                    self.request_update('scheduled')
            self._scheduler = threading.Thread(target=loop, daemon=True, name='sector-data-scheduler')
            self._scheduler.start()
        return self.status()

    def stop(self):
        self._stop.set()
        if self._scheduler:
            self._scheduler.join(timeout=2)
        return self.status()

    def close(self):
        """Permanently stop scheduling and wait for an in-flight transaction.

        Call from the owning service thread, never inside a validator/callback.
        Network request timeouts remain bounded; close does not cancel writes.
        """
        if self._run_thread is threading.current_thread():
            raise UpdateError('不能从更新回调内部关闭更新器')
        with self._state_lock:
            self._closed = True
        self.stop()
        if self._worker is not None:
            self._worker.join()
        with self._mutex:
            pass
        return self.status()

    def import_reviewed_package(self, package_dir):
        package = Path(package_dir).resolve()
        def build(folder):
            review = _read(package/'review.json')
            if review.get('schema') != 'sector-action-review.v1' or not str(review.get('reviewer', '')).strip():
                raise UpdateError('审核包须有review.json及明确复核人声明')
            through = _date(review.get('through'))
            old_env = Environment(self._active)
            start = _date(review.get('from'))
            next_day = (datetime.fromisoformat(old_env._action_through)+timedelta(days=1)).date().isoformat()
            if start > through or start > next_day or through < old_env._action_through:
                raise UpdateError('审核包公司行动覆盖有缺口或倒退')
            if through > self._now().date().isoformat():
                raise UpdateError('审核包不能声称核验未来日期')
            evidence = review.get('evidence', [])
            by_id = {}
            for item in evidence:
                identifier = item.get('id')
                if not identifier or identifier in by_id:
                    raise UpdateError('来源证据id缺失或重复')
                path = (package/str(item.get('file', ''))).resolve()
                if package not in path.parents or not path.is_file() or path.is_symlink():
                    raise UpdateError('审核证据必须是包内真实文件')
                host = urlsplit(item.get('url', '')).hostname or ''
                official = any(host == domain or host.endswith('.'+domain) for domain in OFFICIAL_HOSTS)
                if not official or urlsplit(item.get('url', '')).scheme != 'https':
                    raise UpdateError('本次新覆盖证据须指向官方 HTTPS 来源')
                if _hash(path) != item.get('sha256') or not str(item.get('scope', '')).strip():
                    raise UpdateError('审核证据哈希或范围说明不完整')
                by_id[identifier] = item
            covered = review.get('assets', [])
            if not isinstance(covered, list) or {x.get('code') for x in covered} != {c for c, _ in SECTORS} or len(covered) != 10:
                raise UpdateError('审核覆盖须恰好包含固定十ETF')
            for item in covered:
                if item.get('from') != start or item.get('through') != through or item.get('complete_listing_reviewed') is not True:
                    raise UpdateError('每只ETF须声明完整期间的公告清单已逐页复核')
                if item.get('conclusion') not in ('no_new_events', 'events_verified') or not item.get('evidence_ids'):
                    raise UpdateError('审核结论或关联证据缺失')
                if any(identifier not in by_id for identifier in item['evidence_ids']):
                    raise UpdateError('审核结论引用不存在的证据')
            resolutions = review.get('pending_resolutions', [])
            resolution_map = {item.get('pending_id'): item for item in resolutions}
            if len(resolution_map) != len(resolutions):
                raise UpdateError('待核验事项的解决声明重复')
            for pending in self._state.get('pending_review', []):
                if not pending.get('kind'):
                    continue
                resolution = resolution_map.get(pending.get('pending_id', pending_id(pending)))
                if (not resolution or resolution.get('conclusion') not in ('verified_event', 'supplier_error', 'not_applicable')
                        or not str(resolution.get('explanation', '')).strip()
                        or not resolution.get('evidence_ids')
                        or any(identifier not in by_id for identifier in resolution['evidence_ids'])):
                    raise UpdateError('待核验事件缺少明确解决声明和关联官方证据')
            for name in FILES:
                source = package/name
                if not source.is_file() or source.is_symlink():
                    raise UpdateError('审核包缺少数据文件: '+name)
                shutil.copy2(source, folder/name)
            candidate = Environment(folder)
            Opportunity(candidate)
            if candidate._action_through != through:
                raise UpdateError('review覆盖截止与行动receipt不一致')
            reviewed_on = _date(candidate._actions['as_of'])
            if not through <= reviewed_on <= self._now().date().isoformat():
                raise UpdateError('公司行动receipt核验日期未覆盖本次期间或晚于当前日期')
            for code, _ in SECTORS:
                old_rows = {r['date']: r for r in old_env._market['assets'][code]['bars']}
                new_rows = {r['date']: r for r in candidate._market['assets'][code]['bars']}
                if any(new_rows.get(day) != row for day, row in old_rows.items()):
                    raise UpdateError('审核包不可静默改写旧ETF行情')
                before = old_env._market['assets'][code]['action_coverage'].get('official_full_life_event_archive_exhaustively_reviewed', False)
                after = candidate._market['assets'][code]['action_coverage'].get('official_full_life_event_archive_exhaustively_reviewed', False)
                if after and not before:
                    raise UpdateError('增量审核不能升级为全生命周期官方无事件证明')
            old_events = {r['event_id']: r for r in old_env._actions['events']}
            new_events = {r['event_id']: r for r in candidate._actions['events']}
            if any(new_events.get(key) != row for key, row in old_events.items()):
                raise UpdateError('审核包不可静默改写已核验事件')
            urls = {item['url'] for item in evidence}
            assertions = {item['code']: item for item in covered}
            for key, event in new_events.items():
                if key not in old_events:
                    if event['source_url'] not in urls:
                        raise UpdateError('新增事件未关联本次官方证据')
                    code = next(c for c, _ in SECTORS if c[2:] == event['code'])
                    assertion = assertions[code]
                    linked_urls = {by_id[i]['url'] for i in assertion['evidence_ids']}
                    if assertion['conclusion'] != 'events_verified' or event['source_url'] not in linked_urls:
                        raise UpdateError('新增事件与该ETF审核结论或证据关联不一致')
                    if not start <= event['ex_date'] <= through:
                        raise UpdateError('新增事件不在此次覆盖审核区间')
            for pending in self._state.get('pending_review', []):
                if not pending.get('kind'):
                    continue
                resolution = resolution_map[pending.get('pending_id', pending_id(pending))]
                if resolution['conclusion'] != 'verified_event':
                    continue
                if pending['kind'] == 'source_identity_conflict':
                    raise UpdateError('来源身份冲突须明确复核为供应商错误或不适用，不能声明为ETF已核验事件')
                matches = [event for event in new_events.values()
                           if event['code'] == pending['code'][2:] and event['event_type'] == pending['kind']]
                if pending['kind'] == 'cash_dividend':
                    matches = [event for event in matches
                               if all(event.get(k) == pending.get(k) for k in ('record_date', 'ex_date', 'pay_date'))
                               and math.isclose(event['cash_per_share'], pending['cash_per_share'], abs_tol=1e-10)]
                else:
                    matches = [event for event in matches
                               if (pending['vendor_date'] in (event['record_date'], event['ex_date'])
                                   or (candidate._known_suspension(pending['code'], pending['vendor_date'])
                                       and event['ex_date'] == '2021-03-29'))
                               and math.isclose(event['ratio'], pending['ratio'], abs_tol=1e-10)]
                if not matches:
                    raise UpdateError('verified_event 解决声明没有匹配的已核验事件；日期差异须明确复核供应商错误')
            for series, old_rows in old_env._index['series'].items():
                incoming = {r['date']: r for r in candidate._index['series'].get(series, [])}
                if any(incoming.get(row['date']) != row for row in old_rows):
                    raise UpdateError('审核包不可静默改写旧指数行情')
            evidence_dir = folder/'review_evidence'
            evidence_dir.mkdir()
            published_review = deepcopy(review)
            for identifier, item in by_id.items():
                filename = sha256(identifier.encode()).hexdigest()+Path(item['file']).suffix
                shutil.copy2(package/item['file'], evidence_dir/filename)
                next(r for r in published_review['evidence'] if r['id'] == identifier)['file'] = 'review_evidence/'+filename
            _write(folder/'review.json', published_review)
            expected = candidate._expected(self._now())
            snapshot = candidate.snapshot(now=self._now())
            if expected is None or snapshot['snapshot_date'] != expected or through < expected:
                raise UpdateError('审核包尚未覆盖当前应完成行情和公司行动日期')
            opportunities = Opportunity(candidate).snapshot(now=self._now())
            if opportunities['summary']['ranking_known'] != len(SECTORS):
                raise UpdateError('审核包仍缺少完整十池技术或全收益比较资料，不能宣称完整可用')
            report = {'expected_date': expected, 'action_verified_through': through, 'pending_review': [],
                      'fully_usable': True, 'new_observations': None, 'sources': evidence,
                      'boundary': '来源文件哈希和审核声明校验通过；不能代替复核人对官方内容和完整分页的真实审核。'}
            _write(folder/'update_report.json', report)
            return report, True
        return self._run('reviewed_package', build, 'reviewed_package')
