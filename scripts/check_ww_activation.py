"""Read-only activation evidence for the existing D0 and new stopped WW ledger.

The operator must explicitly supply the application data mount. This script
never imports the application, opens authentication files, creates an account,
starts a worker, submits an order, or changes SQLite state. The optional baseline
file contains hashes and non-financial identities only and must be outside data.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

SCHEMA = 'simple-etf.ww-activation-check.v1'
DBS = {'D0': 'web/realtime-paper/realtime-paper.sqlite3',
       'D0I-BOND-WW': 'web/realtime-paper-ww/realtime-paper.sqlite3'}
AUTOMATION_KEYS = ('auto_refresh', 'auto_simulate', 'paused_accounts', 'auto_backup_required')
CORE_KEYS = ('id', 'strategy', 'name', 'created_at', 'initial_capital',
             'fees', 'fee_version', 'rule_version', 'activation_generation', 'resumed_at')
MAX_PAYLOAD = 128 * 1024 * 1024


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def reject_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('linked path refused')


def read_ledger(path, expected, required=False):
    reject_links(path)
    if not path.exists():
        if required:
            raise ValueError('required ledger missing')
        return {'present': False, 'account_id': None, 'strategy': expected, 'account_present': False,
                'running': False, 'fills_count': 0, 'fills_hash': digest([]), 'fill_hashes': [],
                'positions_hash': digest({}), 'cash_hash': digest(None), 'account_core_hash': digest(None)}
    if not path.is_file():
        raise ValueError('non-regular ledger refused')
    # mode=ro cannot create a missing DB; a deferred read transaction supplies
    # one consistent SQLite view without borrowing the application's writers.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA busy_timeout=3000')
        db.execute('BEGIN')
        rows = db.execute('SELECT id,length(data) FROM ledger LIMIT 2').fetchall()
        if len(rows) != 1 or rows[0][0] != 1 or not 0 < rows[0][1] <= MAX_PAYLOAD:
            raise ValueError('invalid ledger envelope')
        state = json.loads(db.execute('SELECT data FROM ledger WHERE id=1').fetchone()[0])
    account, fills, positions = state.get('account'), state.get('fills'), state.get('positions')
    if not isinstance(fills, list) or not isinstance(positions, dict):
        raise ValueError('invalid ledger evidence')
    if account is not None:
        if not isinstance(account, dict):
            raise ValueError('unexpected account identity')
        # Older D0 ledgers may predate the explicit strategy field. Only an
        # absent key has this legacy meaning; null/empty/foreign values do not.
        account = dict(account)
        if expected == 'D0' and 'strategy' not in account:
            account['strategy'] = 'D0'
        if (account.get('strategy') != expected or not isinstance(account.get('id'), str)
                or type(account.get('running')) is not bool):
            raise ValueError('unexpected account identity')
    account = account or {}
    fill_hashes = [digest(fill) for fill in fills]
    return {'present': True, 'account_id': account.get('id'), 'strategy': expected,
            'account_present': bool(account), 'running': account.get('running', False),
            'account_core_hash': digest({key: account.get(key) for key in CORE_KEYS} if account else None),
            'cash_hash': digest(account.get('cash') if account else None),
            'fills_count': len(fills), 'fills_hash': digest(fill_hashes), 'fill_hashes': fill_hashes,
            'positions_hash': digest(positions),
            'unfilled_order_count': sum(order.get('status') == 'pending' for order in state.get('orders', [])),
            # These fields are expected to change after an ordinary restart or
            # collector observation; no exact-equality claim is made for them.
            'volatile_hash': digest({key: state.get(key) for key in
                ('revision', 'reset_at', 'observations', 'quotes', 'signal', 'plan')})}


def capture(data_root, *, require_ww=False):
    root = Path(data_root)
    if not root.is_absolute():
        raise ValueError('explicit absolute data root required')
    reject_links(root)
    if not root.is_dir():
        raise ValueError('data root missing')
    ledgers = {strategy: read_ledger(root / relative, strategy,
                required=strategy == 'D0' or require_ww) for strategy, relative in DBS.items()}
    settings = root / 'web/settings.json'
    reject_links(settings)
    flags = {}
    if settings.is_file():
        if settings.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('settings envelope too large')
        value = json.loads(settings.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError('invalid automation settings')
        flags = {key: value[key] for key in AUTOMATION_KEYS if key in value}
    return {'schema': SCHEMA, 'captured_at': datetime.now(timezone.utc).isoformat(),
            'ledgers': ledgers, 'automation_flags_hash': digest(flags)}


def public_capture(value):
    return {**value, 'ledgers': {code: {key: item for key, item in ledger.items() if key != 'fill_hashes'}
                               for code, ledger in value['ledgers'].items()}}


def compare(before, after):
    if before.get('schema') != SCHEMA or after.get('schema') != SCHEMA:
        raise ValueError('unknown evidence schema')
    checks, runtime_changes = [], []
    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
    check('automation_flags_preserved', before['automation_flags_hash'] == after['automation_flags_hash'])
    for code in DBS:
        old, new = before['ledgers'][code], after['ledgers'][code]
        check(code + ':ledger_present', new['present'])
        check(code + ':account_identity_preserved',
              old['account_id'] == new['account_id'] and old['account_core_hash'] == new['account_core_hash'])
        preserved = new['fill_hashes'][:old['fills_count']] == old['fill_hashes']
        check(code + ':old_fills_preserved', preserved and new['fills_count'] >= old['fills_count'])
        if new['fills_count'] == old['fills_count']:
            check(code + ':positions_preserved_without_new_fills', old['positions_hash'] == new['positions_hash'])
            check(code + ':cash_preserved_without_new_fills', old.get('cash_hash') == new.get('cash_hash'))
        elif new['fills_count'] > old['fills_count']:
            runtime_changes.append(code + ':new_fills_since_capture')
        if old['running'] != new['running']:
            runtime_changes.append(code + ':running_state_changed')
        if old.get('volatile_hash') != new.get('volatile_hash'):
            runtime_changes.append(code + ':restart_or_quote_signal_state_changed')
    ww = after['ledgers']['D0I-BOND-WW']
    check('WW_not_started', ww['running'] is False)
    if not before['ledgers']['D0I-BOND-WW']['account_present']:
        check('WW_account_not_automatically_created', not ww['account_present'])
        check('WW_no_automatic_fills', ww['fills_count'] == 0)
    failed = any(not row['passed'] for row in checks)
    needs_review = any(not row.endswith(':restart_or_quote_signal_state_changed') for row in runtime_changes)
    return {'schema': SCHEMA, 'status': 'failed' if failed else 'review_required' if needs_review else 'passed',
            'checks': checks, 'runtime_changes': runtime_changes, 'snapshot': public_capture(after),
            'note': 'Signal, quote, plan, revision and restart observations may advance normally. New fills or a running-state change require operator review; they are not silently called unchanged.'}


def write_baseline(path, value, data_root):
    path, root = Path(path).absolute(), Path(data_root).resolve()
    reject_links(path)
    if path == root or root in path.parents:
        raise ValueError('baseline must stay outside application data')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags, 0o600), 'w', encoding='utf-8') as output:
        json.dump(value, output, sort_keys=True, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True,
                        help='Explicit application data mount; no default or credential discovery')
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--capture-before', type=Path, help='New root-private baseline file outside data')
    operation.add_argument('--compare-after', type=Path, help='Read a prior baseline; never creates/starts an account')
    args = parser.parse_args()
    try:
        current = capture(args.data_root, require_ww=args.compare_after is not None)
        if args.capture_before is not None:
            write_baseline(args.capture_before, current, args.data_root)
            result = {'status': 'captured', 'snapshot': public_capture(current)}
        else:
            reject_links(args.compare_after)
            if args.compare_after.stat().st_size > 32 * 1024 * 1024:
                raise ValueError('baseline too large')
            before = json.loads(args.compare_after.read_text(encoding='utf-8'))
            result = compare(before, current)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 1 if result['status'] == 'failed' else 2 if result['status'] == 'review_required' else 0
    except Exception as error:
        # Do not echo SQL, account data, file contents, or credential-bearing errors.
        print(json.dumps({'status': 'error', 'reason': 'activation_check_failed',
                          'exception_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
