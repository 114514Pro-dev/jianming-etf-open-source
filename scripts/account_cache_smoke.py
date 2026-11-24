"""Measure real account-cache refreshes using six temporary public-seed accounts.

No application data directory is accepted. Network, subprocesses and application
threads are blocked. Account creation is deliberately separate from the measured
read-only refreshes. Run this script in a fresh process for meaningful peak RSS.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch


def emit(**value):
    print(json.dumps(value, ensure_ascii=True, allow_nan=False), flush=True)


def memory():
    """ru_maxrss is a process-lifetime high water mark, including fixture setup."""
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        unit = 'bytes' if sys.platform == 'darwin' else 'KiB'
        result = dict(ru_maxrss=peak, ru_maxrss_unit=unit,
                      peak_rss_bytes=int(peak if unit == 'bytes' else peak * 1024))
    except ImportError:
        result = dict(ru_maxrss=None, ru_maxrss_unit='unavailable_on_windows', peak_rss_bytes=None)
    status = Path('/proc/self/status')
    if sys.platform.startswith('linux') and status.is_file():
        for line in status.read_text().splitlines():
            if line.startswith('VmRSS:'):
                result['current_rss_bytes'] = int(line.split()[1]) * 1024
    return result


def fingerprints(home):
    output = {}
    for path in sorted(home.rglob('*')):
        if path.is_symlink():
            raise AssertionError('temporary fixture unexpectedly contains a symlink')
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            output[path.relative_to(home).as_posix()] = (path.stat().st_size, digest.hexdigest())
    return output


def deny(*_args, **_kwargs):
    raise AssertionError('network, subprocesses, application threads and queued reads are forbidden')


def exercise(repo, requested_end):
    sys.path.insert(0, str(repo / 'production'))
    from server import Runtime
    from web_bridge import Bridge

    with tempfile.TemporaryDirectory(prefix='account-cache-public-seed-') as folder:
        home = Path(folder).resolve()
        os.environ['SIMPLE_ETF_HOME'] = os.environ['ETF_SUITE_HOME'] = str(home)
        started = time.perf_counter()
        bridge = Bridge(home)
        emit(phase='bridge_initialized', seconds=round(time.perf_counter() - started, 6), **memory())
        # Use only days present in all three bundled public seed datasets.
        top = bridge.top5._snapshot(bridge.top5.settings['snapshot_id'])
        seven = bridge.seven.snapshot()
        common = set(bridge.original.market.dates)
        common &= {row['datetime'][:10] for row in top['hourly'] if row['datetime'].endswith('15:00:00')}
        common &= {row['datetime'][:10] for row in seven['hourly'] if row['datetime'].endswith('15:00:00')}
        for rows in seven['bars'].values():
            common &= {row['date'] for row in rows}
        days = sorted(day for day in common if '2023-01-03' <= day <= requested_end)
        if len(days) < 120:
            raise AssertionError('fixture must contain at least 120 common confirmed trading days')
        start, end = days[0], days[-1]
        del top, seven
        emit(phase='fixture_plan', start=start, end=end, common_trading_days=len(days),
             accounts_per_group=2, data_source='bundled public seeds only')
        accounts = []
        specs = [('original', 'D0'), ('original', 'DW'), ('top5', 'T5VOTE'),
                 ('top5', 'T5SUPER'), ('seven', 'A_T5VOTE_P2'), ('seven', 'B_D5')]
        for group, strategy in specs:
            began = time.perf_counter()
            name = 'Synthetic cache smoke ' + strategy
            if group == 'original':
                created = bridge.original.create(name, 100000, start, strategy)
                identity = created['id']
                bridge.original.run(identity, end)
            elif group == 'top5':
                created = bridge.top5.create_account(name, strategy, start, 100000)
                identity = created['account']['id']
                bridge.top5.advance_account(identity, end)
            else:
                created = bridge.seven.create_account(strategy, name, 100000, start)
                identity = created['id']
                bridge.seven.advance(identity, end)
            accounts.append((group, identity, strategy))
            emit(phase='fixture_account_created', group=group, strategy=strategy,
                 seconds=round(time.perf_counter() - began, 6), **memory())

        # Discard setup's cached calculations so the first measured refresh also
        # exercises cold detail/overview projections. No ledger data is changed.
        bridge.top5._signals_cache.clear()
        bridge.seven.cache.clear()
        bridge.seven.signal_cache.clear()
        runtime = Runtime.__new__(Runtime)  # Never starts Runtime or its scheduler.
        runtime.cache, runtime.cache_lock, runtime.revision_number = {}, threading.RLock(), 0
        runtime.tasks = SimpleNamespace(put_nowait=deny)
        offered = []
        runtime.signals = SimpleNamespace(offer=lambda value: offered.append(value is bridge))
        baseline = fingerprints(home)
        baseline_memory = memory()
        emit(phase='refresh_baseline', fixture_files=len(baseline),
             fixture_bytes=sum(size for size, _ in baseline.values()), **baseline_memory)
        real_account = bridge.account
        timings = []

        def timed_account(group, identity):
            began = time.perf_counter()
            try:
                return real_account(group, identity)
            finally:
                timings.append(dict(group=group, seconds=time.perf_counter() - began))

        with patch.object(bridge, 'account', timed_account):
            for iteration in (1, 2):
                timings.clear()
                began = time.perf_counter()
                runtime.refresh_cache(bridge)
                seconds = time.perf_counter() - began
                expected = {('account', group, identity) for group, identity, _ in accounts}
                actual = {key for key in runtime.cache if key[0] == 'account'}
                if expected != actual:
                    raise AssertionError('refresh did not warm exactly all six account details')
                for group in ('original', 'top5', 'seven', 'nasdaq', 'hangseng', 'hangtech'):
                    rows = json.loads(runtime.cache[('accounts', group)])
                    if len(rows) != (2 if group in ('original', 'top5', 'seven') else 0):
                        raise AssertionError('account list count mismatch: ' + group)
                details = []
                for group, identity, strategy in accounts:
                    detail = runtime.query('account', group, identity)
                    if not str(detail['summary']['day']).startswith(end):
                        raise AssertionError('cached account endpoint mismatch')
                    details.append(dict(group=group, strategy=strategy,
                        curve_points=len(detail['curve']), events=len(detail['events']),
                        json_bytes=len(runtime.cache[('account', group, identity)].encode())))
                after = fingerprints(home)
                if after != baseline:
                    changed = sorted(key for key in baseline.keys() | after.keys()
                                     if baseline.get(key) != after.get(key))
                    raise AssertionError('read-only refresh changed fixture files: ' + repr(changed))
                report = dict(phase='cache_refresh', iteration=iteration, seconds=round(seconds, 6),
                    account_detail_seconds=round(sum(row['seconds'] for row in timings), 6),
                    account_detail_seconds_by_group={group: round(sum(row['seconds'] for row in timings
                        if row['group'] == group), 6) for group in ('original', 'top5', 'seven')},
                    cache_bytes=sum(len(value.encode()) for value in runtime.cache.values()),
                    cache_entries=len(runtime.cache), details=details, file_hashes_unchanged=True, **memory())
                emit(**report)
        if runtime.revision_number != 2 or offered != [True, True]:
            raise AssertionError('refresh publication/offer count mismatch')
        emit(status='passed', checks=['six_public_seed_accounts', 'cold_and_warm_refresh',
             'all_six_group_lists', 'cached_query_never_queues', 'all_fixture_file_hashes_unchanged'],
             total_seconds=round(time.perf_counter() - started, 6), platform=sys.platform,
             network='blocked', application_threads='blocked', data='fresh temporary home only',
             note='Peak RSS is cumulative and includes account creation; refresh seconds exclude file hashing.',
             **memory())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--end', default='2024-12-31', help='maximum bundled history date; default two years')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    try:
        date.fromisoformat(args.end)
    except ValueError:
        parser.error('--end must be YYYY-MM-DD')
    if not 60 <= args.timeout <= 1800:
        parser.error('--timeout must be 60..1800 seconds')
    repo = args.repo.resolve()
    if not (repo / 'production/server.py').is_file():
        parser.error('repo does not contain the maintained application')

    def expired():
        emit(status='failed', reason='account_cache_smoke_timeout')
        os._exit(124)

    timer = threading.Timer(args.timeout, expired)
    timer.daemon = True
    timer.start()  # Only this watchdog is allowed to create a thread.
    safe = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR',
        'PATH', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH') if key in os.environ}
    safe.update(ETF_WEB_AUTO_REFRESH='0', ETF_WEB_BENCHMARK_REFRESH='0', ETF_WEB_INDEX_BENCHMARK_REFRESH='0',
        ETF_SECTOR_RESEARCH_AUTO_UPDATE='0', PYTHONDONTWRITEBYTECODE='1',
        OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2')
    logging.basicConfig(level=logging.ERROR)
    sys.dont_write_bytecode = True
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, safe, clear=True))
            for target in ('socket.create_connection', 'socket.getaddrinfo', 'socket.socket.connect',
                           'socket.socket.connect_ex', 'subprocess.Popen', 'threading.Thread.start'):
                stack.enter_context(patch(target, side_effect=deny))
            exercise(repo, args.end)
    finally:
        timer.cancel()


if __name__ == '__main__':
    main()
