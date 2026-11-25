"""Loopback benchmark: synthetic website D0 target -> native receiver -> mock receipt.

No EMTL client and no production endpoint. HTTP listeners/clients are hard-bound
to 127.0.0.1. This measures a local synthetic order acknowledgement, not a fill.
"""
import argparse
import asyncio
import http.client
import json
from pathlib import Path
import queue
import socket
from statistics import median
import sys
import threading
from time import perf_counter_ns
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('production', 'production/d0_connector', 'tests')]
from d0_order_preview import preview
from d0_signal_feed import SignalFeed
from live_signal import project_live_signal
from pilot import SYNC_BASE, listen_signals
from realtime_paper_engine import TradingCalendar
from test_emtl_d0 import NOW, inputs

READ_TOKEN = 'L' * 32  # Synthetic only; the local server never uses production auth.
ORDER = {'symbol': 'sz159915', 'side': 'buy', 'quantity': 435000, 'limit_price': '1.002'}


class LoopbackSession:
    def __init__(self, port):
        self.wire = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
        self.cookies = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.wire.close()

    def get(self, url, *, headers, params, timeout, allow_redirects):
        assert url == SYNC_BASE + 'signal' and not allow_redirects
        self.wire.request('GET', '/api/d0-control/sync/signal?' + urlencode(params), headers=headers)
        res = self.wire.getresponse()
        data = res.read()
        return SimpleNamespace(status_code=res.status, json=lambda: json.loads(data))


def timed_stats(values):
    ordered = sorted(values)
    return {key: round(val, 3) for key, val in (
        ('median', median(ordered)), ('p95', ordered[(len(ordered) * 95 + 99) // 100 - 1]), ('max', ordered[-1]))}


async def benchmark(samples, warmup):
    app = FastAPI()
    feed = SignalFeed()
    feed.wait_seconds = 1  # A local heartbeat keeps shutdown bounded.
    waiting = asyncio.Event()
    received_ids = set()
    outcomes = queue.Queue()
    stop = threading.Event()

    @app.get('/api/d0-control/sync/signal')
    async def signal(request: Request, after: str = ''):
        if request.headers.get('authorization') != 'Bearer ' + READ_TOKEN:
            raise HTTPException(401)
        if after:
            waiting.set()
        return await feed.next(after, lambda: not stop.is_set())

    @app.post('/mock-broker')
    async def mock_broker(request: Request):
        data = await request.json()
        identity = data.get('signal_id')
        if data != {'signal_id': identity, 'order': ORDER} or identity in received_ids:
            raise HTTPException(409, 'Unexpected or duplicate synthetic order')
        received_ids.add(identity)
        return {'ack': 'mock-' + identity, 'filled': False}

    def app_target(port, target):
        arrived = perf_counter_ns()
        try:
            snapshot, balances = inputs()
            balances.update(cash='870000', available_cash='870000')
            signal = {key: target[key] for key in ('strategy', 'confirmed_day', 'execution_day',
                                                    'eligible_at', 'known_at', 'data_cutoff')}
            signal.update(id=target['signal_id'], valid=True, weights={
                ('sh' if code.startswith('SHSE.') else 'sz') + code[5:]: weight
                for code, weight in target['targets'].items()})
            plan = preview({**snapshot, 'signal': signal}, balances, now=NOW)
            planned = perf_counter_ns()
            if plan['stage'] != 'buy' or plan['orders'] != [ORDER]:
                raise RuntimeError('Unexpected D0 preview result')
            broker = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                broker.request('POST', '/mock-broker', body=json.dumps({'signal_id': target['signal_id'], 'order': plan['orders'][0]}),
                               headers={'Content-Type': 'application/json'})
                res = broker.getresponse()
                reply = json.loads(res.read())
                acked = perf_counter_ns()
                if res.status != 200 or reply != {'ack': 'mock-' + target['signal_id'], 'filled': False}:
                    raise RuntimeError('Unexpected mock acknowledgement')
            finally:
                broker.close()
            outcomes.put((target['signal_id'], arrived, planned, acked))
        except Exception as exc:
            outcomes.put(exc)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='critical', lifespan='off'))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    worker = None
    measured = []
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(.005)
        worker = threading.Thread(target=listen_signals,
                                  args=(READ_TOKEN, stop, lambda _: None, lambda: LoopbackSession(port)),
                                  kwargs={'on_target': lambda target: app_target(port, target)}, daemon=True)
        worker.start()
        snapshot, _ = inputs()
        original = {**snapshot['signal'], 'weights': {'sz159915': '.5'}}
        cal = TradingCalendar()
        for i in range(samples + warmup):
            await asyncio.wait_for(waiting.wait(), 5)
            waiting.clear()
            identity = f'{i + 1:064x}'
            target = project_live_signal(signal={**original, 'id': identity}, strategy='D0', calendar=cal,
                                         now=NOW, observed_at=NOW, source_status='ready')
            published = perf_counter_ns()
            feed.publish(target)
            outcome = await asyncio.to_thread(outcomes.get, True, 5)
            if isinstance(outcome, Exception):
                raise outcome
            result_id, arrived, planned, acked = outcome
            if result_id != identity or not published <= arrived <= planned <= acked:
                raise RuntimeError('Unexpected ordering or identity')
            if i >= warmup:
                measured.append([(end - start) / 1e6 for start, end in (
                    (published, arrived), (arrived, planned), (planned, acked),
                    (published, planned), (published, acked))])
        if len(received_ids) != samples + warmup:
            raise RuntimeError('Missing mock acknowledgement')
    finally:
        stop.set()
        feed.publish(None)
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()
        if worker is not None:
            await asyncio.to_thread(worker.join, 1)
    return {'synthetic_only': True, 'transport': 'localhost HTTP', 'samples': samples, 'warmup': warmup,
            'mock_orders': len(received_ids), 'fills': 0, 'example_order': ORDER,
            'milliseconds': {name: timed_stats(list(values)) for name, values in zip(
                ('published_to_validated', 'validated_to_order', 'order_to_mock_ack',
                 'published_to_order', 'published_to_mock_ack'), zip(*measured))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=100, choices=range(1, 1001), metavar='1..1000')
    parser.add_argument('--warmup', type=int, default=10, choices=range(0, 101), metavar='0..100')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(benchmark(args.samples, args.warmup)), indent=2))


if __name__ == '__main__':
    main()
