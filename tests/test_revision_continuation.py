"""Public seeds + synthetic revisions, real engines and disposable accounts.

Never mounts a production profile. Networking and scheduler startup are absent.
All five Top5, seven combinations and 3 x 21 overseas account paths are replayed.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from test_market_revisions import source, CN
from chinext_service import BY_ID as TOP5, _write
from seven_service import SevenService, BY_ID as SEVEN
from web_auto import WebTop5Service, AutoSupport
from web_overseas import OverseasService, MARKETS, TITLES, SCHEMA
from simulator_core import write_json

START, BEFORE, AFTER = '2026-08-03', '2026-09-10', '2026-09-15'


def changed(rows, key):
    # Simulates meaningful provider corrections, not rounding or stale dates.
    rows = deepcopy([r for r in rows if '2026-09-09' <= r[key][:10] <= AFTER])
    row = next(r for r in rows if r[key][:10] == BEFORE)
    row['high'] += .002
    row['close'] = min(row['high'], row['close'] + .001)
    row['volume' if key == 'datetime' else 'volume_lots'] *= 1.25
    return rows


def files_under(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*.json')}


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.moment = datetime(2026, 9, 17, 17, tzinfo=CN)
        # Passive settings preservation sentinel; no Runtime/scheduler is started.
        self.settings = self.home / 'web' / 'settings.json'
        write_json(self.settings, dict(auto_refresh=True, auto_simulate=True,
                                      paused_accounts=['fixture-paused-account']))
        self.settings_before = self.settings.read_bytes()
        self.network = patch('socket.create_connection', side_effect=AssertionError('No network in fixture'))
        self.network.start(); self.addCleanup(self.network.stop)

    def preserved(self, service_folder, before):
        current = files_under(service_folder)
        for path, sha in before.items():
            self.assertEqual(current[path], sha, path)
        self.assertEqual(self.settings.read_bytes(), self.settings_before)

    def assert_prefix(self, old, new):
        self.assertEqual(new['curve'][:len(old['curve'])], old['curve'])
        self.assertEqual(new['events'][:len(old['events'])], old['events'])
        self.assertEqual(new['end'], AFTER)

    def test_top5_and_seven_recover_without_rewriting_history(self):
        top5 = WebTop5Service(self.home)
        full_top = top5._snapshot(); short_top = deepcopy(full_top)
        for collection, key in [('daily', 'date'), ('hourly', 'datetime')]:
            short_top[collection] = [r for r in full_top[collection] if r[key][:10] <= BEFORE]
        top5.settings['snapshot_id'] = top5._store_snapshot(short_top)
        _write(top5._state_path, top5.settings)
        seven = SevenService(self.home)
        full_seven = seven.snapshot(); short_seven = deepcopy(full_seven)
        for c in short_seven['bars']:
            short_seven['bars'][c] = [r for r in full_seven['bars'][c] if r['date'] <= BEFORE]
        short_seven['hourly'] = [r for r in full_seven['hourly'] if r['datetime'][:10] <= BEFORE]
        seven.settings['snapshot'] = seven.store(short_seven)
        write_json(seven.settings_path, seven.settings)
        seven.top5 = top5
        seven.market_service = SimpleNamespace(market=SimpleNamespace(
            bars={c:[r for r in rows if r['date'] <= AFTER] for c,rows in full_seven['bars'].items()},
            inputs=SimpleNamespace(actions=full_seven['actions'], splits=full_seven['splits'])))
        b = SimpleNamespace(top5=top5, seven=seven, _group=lambda g:g,
            _check_stop=lambda _:None, _top5_summary=lambda a:dict(day=a['last_bar']),
            _seven_summary=lambda a:dict(day=a['result']['end']))
        auto = AutoSupport(b, lambda:self.moment)
        prior_top, prior_seven = {}, {}
        for code in TOP5:
            a = top5.create_account('Independent '+code, code, START, 100000)['account']
            top5.advance_account(a['id'], BEFORE)
            prior_top[a['id']] = top5._load_account(a['id'])
        for code in SEVEN:
            a = seven.create_account(code, 'Independent '+code, 100000, START)
            prior_seven[a['id']] = seven.advance(a['id'], BEFORE)
        snapshots_top = files_under(top5.folder / '行情快照')
        snapshots_seven = files_under(seven.folder / '行情快照')
        account_files = (files_under(top5.folder / '账户'), files_under(seven.folder / '账户'))
        fresh = dict(daily=[r for r in full_top['daily'] if '2026-09-09' <= r['date'] <= AFTER],
                     hourly=changed(full_top['hourly'], 'datetime'), warnings=[])
        # Daily and hourly revisions both retain their complete accepted rows.
        fresh['daily'] = deepcopy(fresh['daily'])
        fresh['daily'][0]['high'] += .002
        fresh['daily'][0]['volume'] *= 1.2
        def incoming(*args, **kwargs):
            return dict(deepcopy(fresh), fetched_at=self.moment.isoformat(),
                        sources=[source(self.moment, key='date'), source(self.moment)])
        with patch('chinext_refresh_support.fetch_market_updates', side_effect=incoming), \
                patch.object(WebTop5Service, '_quality_now', lambda _:self.moment):
            with patch('web_market_revisions.write_json', side_effect=OSError('synthetic full disk')):
                with self.assertRaisesRegex(ValueError, '持久保存'):
                    top5.refresh()
            self.assertEqual(top5._snapshot(), short_top)
            with self.assertRaisesRegex(ValueError, '60秒'):
                top5.refresh()
            self.assertEqual(account_files, (files_under(top5.folder / '账户'), files_under(seven.folder / '账户')))
            self.assertEqual(top5._snapshot(), short_top)
            self.moment += timedelta(seconds=61)
            # Reconstruct service to prove pending observations survive restart.
            top5 = WebTop5Service(self.home); seven.top5=top5; b.top5=top5
            complete_hourly=fresh['hourly']
            fresh['hourly']=[r for r in complete_hourly if r['datetime']!='2026-09-11 14:00:00']
            with self.assertRaises(ValueError):
                top5.refresh()
            self.assertEqual(top5._snapshot(),short_top)
            self.assertEqual(account_files,(files_under(top5.folder/'账户'),files_under(seven.folder/'账户')))
            fresh['hourly']=complete_hourly
            refreshed = top5.refresh()
            self.assertEqual(refreshed['latest_daily'], AFTER)
            self.assertEqual(len(refreshed['history_revisions']['retained']), 2)
            seven.sync()
            total_events = 0
            for group, prior in [('top5', prior_top), ('seven', prior_seven)]:
                for identity, old in prior.items():
                    outcome = auto.advance(dict(group=group, id=identity), None, lambda _:None)
                    self.assertTrue(outcome['advanced'], outcome)
                    if group == 'top5':
                        new = top5._load_account(identity)
                        for key in ('ledger', 'events', 'history'):
                            self.assertEqual(new[key][:len(old[key])], old[key])
                        self.assertEqual(new['through'], AFTER+' 15:00:00')
                        total_events += len(old['events'])
                        path = top5._account_path(identity)
                    else:
                        new = seven.get_account(identity)
                        self.assert_prefix(old['result'], new['result'])
                        total_events += len(old['result']['events'])
                        path = seven.folder / '账户' / (identity+'.json')
                    for key in ('id', 'name'):
                        self.assertEqual(new[key], old[key])
                    before_bytes = path.read_bytes()
                    self.assertFalse(auto.advance(dict(group=group, id=identity), None, lambda _:None)['advanced'])
                    self.assertEqual(path.read_bytes(), before_bytes)
            self.assertGreater(total_events, 0)
            self.assertFalse(top5.refresh()['updated'])
        self.preserved(top5.folder / '行情快照', snapshots_top)
        self.preserved(seven.folder / '行情快照', snapshots_seven)
        print(json.dumps(dict(check='top5_seven_continuation', passed=True, accounts=12,
            previous=BEFORE, reached=AFTER, historical_events_preserved=total_events), ensure_ascii=False), flush=True)

    def test_all_overseas_markets_and_strategies_recover_with_old_prefixes(self):
        svc = OverseasService(self.home)
        full = deepcopy(svc.snapshot); short = deepcopy(full)
        for ds in short['datasets'].values():
            ds['bars'] = [r for r in ds['bars'] if r['date'] <= BEFORE]
            ds['hourly'] = [r for r in ds['hourly'] if r['datetime'][:10] <= BEFORE]
            ds['asof'] = BEFORE
        svc.snapshot=short; svc.settings['snapshot']=svc.store(short); svc.save_settings()
        prior = {}
        for group in MARKETS:
            # The actual worker computes fixture accounts in one batch per market.
            # Subsequent advances below use the real per-account execute path.
            for result in svc.run(group, list(TITLES), START, BEFORE, 100000):
                a = dict(schema=SCHEMA, id=uuid.uuid4().hex, name='Independent '+result['strategy'],
                         group=group, created=self.moment.isoformat(), result=result)
                svc.save(a); prior[(group,a['id'])] = deepcopy(a)
        old_files = files_under(svc.folder / 'accounts')
        old_snapshots = files_under(svc.folder / 'snapshots')
        incoming = {c:(changed(ds['bars'],'date'), changed(ds['hourly'],'datetime'))
                    for c,ds in full['datasets'].items()}
        def fetch(_, c, limit):
            d,h=incoming[c]
            return deepcopy(d),deepcopy(h),[source(self.moment,c,'date'),source(self.moment,c)]
        with patch.object(OverseasService, '_fetch_dataset', fetch), patch('web_overseas.now', lambda:self.moment):
            outcome=svc.refresh(AFTER)
            self.assertFalse(outcome['ok']); self.assertIn('60秒',str(outcome['errors']))
            self.assertEqual(svc.snapshot,short)
            self.assertEqual(files_under(svc.folder/'accounts'),old_files)
            self.moment+=timedelta(seconds=61)
            svc=OverseasService(self.home)
            outcome=svc.refresh(AFTER)
            self.assertTrue(outcome['ok'],outcome)
            self.assertEqual(set(outcome['ends'].values()),{AFTER})
            self.assertEqual(len(outcome['history_revisions']['retained']),12)
            total_events=0
            for (group,identity),old in prior.items():
                result=svc.execute('auto_advance',dict(group=group,id=identity,expected_day=BEFORE))
                self.assertTrue(result['advanced'],result)
                new=svc.get(group,identity)
                self.assert_prefix(old['result'],new['result'])
                for key in ('id','name','created','group'):
                    self.assertEqual(old[key],new[key])
                total_events+=len(old['result']['events'])
                path=svc._path(group,identity); before_bytes=path.read_bytes()
                self.assertFalse(svc.execute('auto_advance',dict(group=group,id=identity))['advanced'])
                self.assertEqual(path.read_bytes(),before_bytes)
                print(json.dumps(dict(check='overseas_continuation',passed=True,market=group,
                    strategy=old['result']['strategy'],reached=new['result']['end']),ensure_ascii=False),flush=True)
            self.assertGreater(total_events,0)
        self.preserved(svc.folder/'snapshots',old_snapshots)
        print(json.dumps(dict(check='overseas_preservation',passed=True,accounts=63,
            historical_events_preserved=total_events),ensure_ascii=False),flush=True)

    def test_pending_market_does_not_block_unrelated_overseas_groups(self):
        svc=OverseasService(self.home); full=deepcopy(svc.snapshot); short=deepcopy(full)
        for ds in short['datasets'].values():
            ds['bars']=[r for r in ds['bars'] if r['date']<=BEFORE]
            ds['hourly']=[r for r in ds['hourly'] if r['datetime'][:10]<=BEFORE]
            ds['asof']=BEFORE
        svc.snapshot=short;svc.settings['snapshot']=svc.store(short);svc.save_settings()
        def fetch(_,c,limit):
            ds=full['datasets'][c]
            daily=deepcopy([r for r in ds['bars'] if '2026-09-09'<=r['date']<=AFTER])
            hourly=deepcopy([r for r in ds['hourly'] if '2026-09-09'<=r['datetime'][:10]<=AFTER])
            if c==MARKETS['nasdaq']['symbol']:hourly=changed(ds['hourly'],'datetime')
            return daily,hourly,[source(self.moment,c,'date'),source(self.moment,c)]
        with patch.object(OverseasService,'_fetch_dataset',fetch),patch('web_overseas.now',lambda:self.moment):
            result=svc.refresh(AFTER)
            self.assertFalse(result['ok'])
            self.assertEqual(set(result['errors']),{'nasdaq'})
            self.assertEqual(result['ends'],dict(nasdaq=BEFORE,hangseng=AFTER,hangtech=AFTER))
            self.moment+=timedelta(seconds=61)
            svc=OverseasService(self.home)
            result=svc.refresh(AFTER)
            self.assertTrue(result['ok'],result)
            self.assertEqual(set(result['ends'].values()),{AFTER})
        self.assertEqual(self.settings.read_bytes(),self.settings_before)


if __name__ == '__main__':
    unittest.main()
