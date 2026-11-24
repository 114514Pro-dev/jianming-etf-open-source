#!/usr/bin/env node
'use strict';

// Exercise the real comparison parser and row building code in memory. This test
// never opens a browser, fetches quotes, reads a ledger, or sends account commands.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const file = path.join(root, 'production/web_static/realtime-paper-comparison.js');
const source = fs.readFileSync(file, 'utf8');
const marker = 'window.RealtimePaperComparison =';
assert.equal(source.split(marker).length, 2, 'Expected one production public export');
const context = vm.createContext({
  window: { ETF_I18n: { language: 'zh' }, addEventListener() {} },
  document: { addEventListener() {} },
  console,
});
vm.runInContext(source.replace(marker,
  'window.__comparisonTest = {readComparison, comparisonRows, comparisonRangeRows};\n' + marker),
context, { filename: 'realtime-paper-comparison.js' });
const { readComparison, comparisonRows, comparisonRangeRows } = context.window.__comparisonTest;

const account = { id: 'account-fixture', created_at: '2026-10-01T01:00:00Z', initial_capital: '100000' };
// The HTTP account endpoint calls its opening capital initial_cash. Keep the
// older alias fixture as compatibility coverage, but exercise the actual shape.
const httpAccount = { id: account.id, created_at: account.created_at, strategy: 'D0',
  name: 'Synthetic D0 account', initial_cash: '100000', cash: '100000' };
const ids = ['account', 'market', 'chinext', 'd0'];
const phases = { account: 'reconstructed_close', market: 'index_close', chinext: 'index_close', d0: 'model_close' };
const methods = { account: 'recorded_fills_reconstruction', market: 'price_index', chinext: 'price_index', d0: 'native_open_replay' };
const iso = date => date + 'T07:00:00Z';
const clone = value => JSON.parse(JSON.stringify(value));

function point(id, date = '2026-10-01', overrides = {}) {
  return { key: id + '-' + date, at: iso(date), date, segment_id: 'initial',
    equity: '100000', return_ratio: 0, phase: phases[id],
    source_at: iso(date), observed_at: iso(date), break_before: false, ...overrides };
}

function fixture() {
  return { contract_version: 'd0-performance-comparison-v1', status: 'available', reason: null,
    account_id: account.id, account_created_at: account.created_at,
    generated_at: '2026-10-27T07:05:00Z', requested_start_at: account.created_at,
    normalization: 'first_shared_confirmed_close',
    segments: [{ id: 'initial', capital: '100000', starts_at: account.created_at,
      ends_at: null, baseline_at: iso('2026-10-01'), baseline_equity: '100000' }],
    series: ids.map(id => ({ id, status: 'available', reason: null, method: methods[id],
      as_of: iso('2026-10-02'), points: [point(id), point(id, '2026-10-02', { equity: '101000', return_ratio: 0.01 })] })),
    notes: [] };
}

function twoSegments() {
  const data = fixture();
  data.segments[0].ends_at = '2026-10-02T08:00:00Z';
  data.segments.push({ id: 'capital-2', capital: '200000', starts_at: '2026-10-02T08:00:00Z',
    ends_at: null, baseline_at: '2026-10-02T08:30:00Z', baseline_equity: '200000' });
  for (const line of data.series) {
    line.points.push(point(line.id, '2026-10-02', { key: line.id + '-capital-2',
      at: '2026-10-02T08:30:00Z', source_at: '2026-10-02T08:30:00Z', observed_at: '2026-10-02T08:30:00Z',
      segment_id: 'capital-2', equity: '200000', return_ratio: 0, break_before: true }));
    line.as_of = '2026-10-02T08:30:00Z';
  }
  return data;
}

function cashFixture({ observed = '2026-10-27T07:00:10Z', at = '2026-10-27T06:00:00Z', marked = true } = {}) {
  const data = fixture();
  for (const id of ['account', 'd0']) {
    const line = data.series.find(item => item.id === id);
    const cashPoint = point(id, '2026-10-27', { key: id + '-cash-live', phase: 'intraday_estimate',
      at, source_at: null, observed_at: observed, equity: '102000', return_ratio: 0.02 });
    if (marked) cashPoint.cash_only = true;
    line.points.push(cashPoint); line.as_of = observed || at;
  }
  return data;
}

function retainedFixture() {
  const data = fixture();
  data.generated_at = '2026-10-27T07:00:30Z';
  for (const line of data.series) {
    const retained = ['account', 'd0'].includes(line.id), at = retained ? '2026-10-27T07:00:05Z' : '2026-10-27T07:00:25Z';
    const item = point(line.id, '2026-10-27', { key: line.id + '-live', phase: 'intraday_estimate',
      at, source_at: at, observed_at: at, equity: '102000', return_ratio: 0.02 });
    if (retained) Object.assign(item, { retained: true, retained_reason: 'waiting_verified_quote' });
    line.points.push(item); line.as_of = at;
  }
  data.notes.push('gaps_not_filled');
  return data;
}

let checks = 0;
const cases = [];
const failures = [];
function same(actual, expected, message) { checks++; assert.equal(actual, expected, message); }
function ok(actual, message) { checks++; assert.ok(actual, message); }
function test(name, body) {
  try { body(); cases.push(name); }
  catch (error) { failures.push({ name, error }); }
}
function parsed(data = fixture(), selectedAccount = account) { return readComparison(data, selectedAccount); }
function available(data = fixture()) {
  const result = parsed(data);
  same(result.status, 'available', 'A complete, consistent contract must be accepted');
  ok(result.data, 'An available parse exposes validated chart data');
  return result.data;
}
function invalid(mutate, message) {
  const data = fixture();
  mutate(data);
  const result = parsed(data);
  same(result.status, 'invalid', message);
  same(result.data, null, 'Invalid values must not reach the chart');
}
function freeze(value) {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

test('accepts a consistent four-line contract without mutating it', () => {
  const data = freeze(fixture());
  const before = JSON.stringify(data);
  available(data);
  same(JSON.stringify(data), before);
});

test('binds responses to the selected account id', () => {
  const result = parsed(fixture(), { ...account, id: 'different-account' });
  same(result.status, 'invalid'); same(result.data, null);
});

test('binds responses to the account creation time', () => {
  const result = parsed(fixture(), { ...account, created_at: '2026-10-02T01:00:00Z' });
  same(result.status, 'invalid'); same(result.data, null);
});

test('accepts the actual HTTP account shape without initial_capital', () => {
  same(Object.hasOwn(httpAccount, 'initial_capital'), false);
  const result = parsed(fixture(), httpAccount);
  same(result.status, 'available'); ok(result.data);
  same(parsed(fixture(), { ...httpAccount, initial_cash: 100000 }).status, 'available');
});

test('initial_cash is the primary field when the legacy alias conflicts', () => {
  same(parsed(fixture(), { ...httpAccount, initial_capital: 'invalid-legacy-value' }).status, 'available');
  same(parsed(fixture(), { ...httpAccount, initial_capital: '200000' }).status, 'available');
});

test('an invalid present initial_cash never falls back to initial_capital', () => {
  for (const value of [null, undefined, '', '-1', '0', 'NaN', 'Infinity', 0, -1, NaN, Infinity]) {
    const result = parsed(fixture(), { ...httpAccount, initial_cash: value, initial_capital: '100000' });
    same(result.status, 'invalid'); same(result.data, null);
  }
});

test('rejects absent and malformed envelopes', () => {
  for (const input of [null, undefined, [], 'bad', 0, {}]) same(readComparison(input, account).status, 'invalid');
});

test('requires the named contract version and normalization', () => {
  invalid(data => { data.contract_version = 'd0-performance-comparison-v2'; });
  invalid(data => { data.normalization = 'account_creation_minute'; });
});

test('requires the four unique known series', () => {
  invalid(data => { data.series.pop(); });
  invalid(data => { data.series[3].id = 'market'; });
  invalid(data => { data.series[3].id = 'other'; });
});

test('rejects unknown statuses and point phases', () => {
  invalid(data => { data.status = 'ready'; });
  invalid(data => { data.series[0].status = 'ready'; });
  invalid(data => { data.series[0].points[0].phase = 'forecast'; });
});

test('bounds the number of points accepted from a response', () => {
  invalid(data => {
    const base = Date.parse(iso('2026-10-01'));
    data.series[0].points = Array.from({ length: 5001 }, (_, index) => {
      const time = new Date(base + index * 1000).toISOString();
      return point('account', '2026-10-01', { key: 'bounded-' + index,
        at: time, source_at: time, observed_at: time });
    });
  });
});

test('rejects duplicate point keys within a line', () => {
  invalid(data => { data.series[0].points[1].key = data.series[0].points[0].key; });
});

test('rejects invalid calendar dates and timestamps', () => {
  invalid(data => { data.series[0].points[0].date = '2026-02-30'; });
  invalid(data => { data.series[0].points[0].date = '2026-1-01'; });
  invalid(data => { data.series[0].points[0].at = 'not-a-date'; });
  invalid(data => { data.generated_at = '2026-02-30T07:05:00Z'; });
});

test('rejects points, observations, and source times after generation', () => {
  for (const field of ['at', 'source_at', 'observed_at']) {
    invalid(data => { data.series[0].points[1][field] = '2026-10-28T07:00:00Z'; }, field + ' is from the future');
  }
  invalid(data => { data.series[0].as_of = '2026-10-28T07:00:00Z'; });
});

test('rejects unsorted points rather than silently changing chronology', () => {
  invalid(data => { data.series[0].points.reverse(); });
});

test('requires known segments and unique segment ids', () => {
  invalid(data => { data.series[0].points[0].segment_id = 'missing'; });
  invalid(data => { data.segments.push(clone(data.segments[0])); });
});

test('requires positive finite capital and a finite baseline', () => {
  for (const value of ['-1', 'NaN', 'Infinity', '', '0']) invalid(data => { data.segments[0].capital = value; });
  for (const value of ['-1', 'NaN', 'Infinity', '']) invalid(data => { data.segments[0].baseline_equity = value; });
});

test('rejects nonfinite, negative, and non-string equity', () => {
  for (const value of ['-1', 'NaN', 'Infinity', '', 100000, NaN, Infinity]) {
    invalid(data => { data.series[0].points[0].equity = value; });
  }
});

test('rejects nonfinite and nonnumeric return ratios', () => {
  for (const value of [NaN, Infinity, -Infinity, '0', undefined, -1.00001]) {
    invalid(data => { data.series[0].points[0].return_ratio = value; });
  }
});

test('checks returns against each segment baseline equity', () => {
  invalid(data => { data.series[0].points[1].return_ratio = 0.02; });
  invalid(data => { data.series[0].points[1].equity = '102000'; });
  const data = fixture();
  data.series[0].points[1].return_ratio = 0.01000000001;
  available(data);
});

test('a present baseline point must itself be zero even when its arithmetic is consistent', () => {
  for (const id of ids) {
    invalid(data => {
      const baseline = data.series.find(line => line.id === id).points[0];
      baseline.equity = '101000'; baseline.return_ratio = 0.01;
    }, id + ' must be normalized to zero at the declared shared baseline');
  }
});

test('accepts zero equity only with the corresponding total loss', () => {
  const data = fixture();
  data.series[0].points[1].equity = '0'; data.series[0].points[1].return_ratio = -1;
  const result = available(data);
  same(result.series[0].points[1].return_ratio, -1);
  invalid(input => { input.series[0].points[1].equity = '0'; input.series[0].points[1].return_ratio = 0; });
});

test('preserves null gaps instead of converting them to zero', () => {
  const data = fixture();
  data.series[0].points[1].equity = null; data.series[0].points[1].return_ratio = null;
  const result = available(data);
  const rows = comparisonRows(result);
  same(result.series[0].points[1].return_ratio, null);
  same(rows[1].points.account.return_ratio, null);
  same(rows[1].points.account.equity, null);
});

test('rejects a gap with only one of equity and return missing', () => {
  invalid(data => { data.series[0].points[1].equity = null; });
  invalid(data => { data.series[0].points[1].return_ratio = null; });
});

test('accepts a singleton without inventing an earlier or later point', () => {
  const data = fixture();
  for (const line of data.series) { line.points = [line.points[0]]; line.as_of = line.points[0].at; }
  const rows = comparisonRows(available(data));
  same(rows.length, 1);
  same(rows[0].phase, 'daily');
  ok(Number.isFinite(rows[0].at));
  same(rows[0].date, '2026-10-01');
  for (const id of ids) same(rows[0].points[id].return_ratio, 0);
});

test('builds daily union rows without carrying missing line values', () => {
  const data = fixture();
  data.series[1].points.splice(1); data.series[1].as_of = iso('2026-10-01');
  for (const line of data.series) {
    if (line.id === 'chinext') continue;
    line.points.push(point(line.id, '2026-10-03', { equity: '102000', return_ratio: 0.02 }));
    line.as_of = iso('2026-10-03');
  }
  const rows = comparisonRows(available(data));
  same(rows.length, 3);
  same(rows[2].points.chinext, undefined);
  same(rows[1].points.market, undefined);
  same(rows[1].points.account.return_ratio, 0.01);
  same(rows[1].at - rows[0].at, 86400000);
});

test('retains calendar distances through weekends and missing dates', () => {
  const data = fixture();
  for (const line of data.series) {
    line.points[1] = point(line.id, '2026-10-12', { equity: '101000', return_ratio: 0.01 });
    line.as_of = iso('2026-10-12');
  }
  const rows = comparisonRows(available(data));
  same(rows.length, 2);
  same(rows[1].at - rows[0].at, 11 * 86400000);
});

test('keeps same-date capital segments as separate zero-based rows', () => {
  const data = available(twoSegments());
  const rows = comparisonRows(data);
  same(rows.length, 3);
  same(rows[1].date, rows[2].date);
  ok(rows[1].key !== rows[2].key);
  same(rows[1].segment_id, 'initial'); same(rows[2].segment_id, 'capital-2');
  for (const id of ids) {
    same(rows[2].points[id].equity, '200000');
    same(rows[2].points[id].return_ratio, 0);
    same(rows[2].points[id].break_before, true);
  }
});

test('checks each capital segment against its own baseline', () => {
  const data = twoSegments();
  data.series[3].points.push(point('d0', '2026-10-03', { segment_id: 'capital-2',
    equity: '202000', return_ratio: 0.01 }));
  data.series[3].as_of = iso('2026-10-03');
  available(data);
  data.series[3].points[3].return_ratio = 1.02;
  same(parsed(data).status, 'invalid');
});

test('groups asynchronous live estimates and preserves each source time', () => {
  const data = fixture();
  const times = ['07:00:01', '07:00:03', '07:00:02', '07:00:04'];
  data.series.forEach((line, index) => {
    const time = '2026-10-27T' + times[index] + 'Z';
    line.points.push(point(line.id, '2026-10-27', { key: line.id + '-live', at: time,
      source_at: time, observed_at: '2026-10-27T07:00:05Z', phase: 'intraday_estimate',
      equity: String(102000 + index * 1000), return_ratio: 0.02 + index * 0.01 }));
    line.as_of = time;
  });
  const result = available(data);
  const rows = comparisonRows(result);
  same(rows.length, 3);
  const live = rows[2];
  same(live.phase, 'live');
  same(live.at, Date.parse('2026-10-27T07:00:05Z'));
  data.series.forEach((line, index) => {
    same(live.points[line.id].source_at, '2026-10-27T' + times[index] + 'Z');
    same(live.points[line.id].observed_at, '2026-10-27T07:00:05Z');
    same(result.series[index].as_of, line.as_of);
  });
});

test('rejects multiple live estimates from one series in the same capital segment across dates', () => {
  for (const id of ids) {
    invalid(data => {
      const line = data.series.find(item => item.id === id);
      for (const date of ['2026-10-26', '2026-10-27']) {
        line.points.push(point(id, date, { key: id + '-live-' + date,
          phase: 'intraday_estimate', equity: '102000', return_ratio: 0.02 }));
      }
      line.as_of = iso('2026-10-27');
    }, id + ' must not silently overwrite an older live row in the same segment');
  }
});

test('accepts explicit cash-only live account and model points plus ordinary false flags', () => {
  const result = available(cashFixture());
  for (const id of ['account', 'd0']) {
    const last = result.series.find(line => line.id === id).points.at(-1);
    same(last.cash_only, true); same(last.source_at, null);
  }
  const data = fixture();
  for (const line of data.series) for (const item of line.points) item.cash_only = false;
  available(data);
});

test('rejects cash-only flags on indices, confirmed closes, or points with a quote source', () => {
  for (const id of ['market', 'chinext']) {
    invalid(data => {
      const line = data.series.find(item => item.id === id);
      line.points.push(point(id, '2026-10-27', { key: id + '-invalid-cash', phase: 'intraday_estimate',
        cash_only: true, source_at: null, equity: '102000', return_ratio: 0.02 }));
      line.as_of = iso('2026-10-27');
    });
  }
  invalid(data => { data.series[0].points[0].cash_only = true; data.series[0].points[0].source_at = null; });
  const withSource = cashFixture(); withSource.series[0].points.at(-1).source_at = '2026-10-27T06:00:00Z';
  same(parsed(withSource).status, 'invalid');
});

test('rejects nonboolean optional cash_only values instead of interpreting them as truthy', () => {
  for (const flag of [null, undefined, 'true', 'false', 0, 1, {}, []]) {
    invalid(data => { data.series[0].points[0].cash_only = flag; });
  }
});

test('accepts retained account and model live points without changing original timestamps', () => {
  const data = freeze(retainedFixture()), before = JSON.stringify(data), result = available(data);
  for (const id of ['account', 'd0']) {
    const item = result.series.find(line => line.id === id).points.at(-1);
    same(item.retained, true); same(item.retained_reason, 'waiting_verified_quote');
    for (const field of ['at', 'source_at', 'observed_at']) same(item[field], '2026-10-27T07:00:05Z');
  }
  same(JSON.stringify(data), before);
});

test('retained metadata must be boolean, paired, known, and limited to account or model live points', () => {
  for (const flag of [null, undefined, 'true', 'false', 0, 1, {}, []]) {
    const data = retainedFixture(); data.series[0].points.at(-1).retained = flag;
    same(parsed(data).status, 'invalid');
  }
  for (const reason of [undefined, null, '', 'unknown', '<script>', true, {}]) {
    const data = retainedFixture(); data.series[0].points.at(-1).retained_reason = reason;
    same(parsed(data).status, 'invalid');
  }
  for (const flag of [false, undefined]) {
    const data = retainedFixture();
    if (flag === undefined) delete data.series[0].points.at(-1).retained;
    else data.series[0].points.at(-1).retained = flag;
    same(parsed(data).status, 'invalid');
  }
  for (const id of ['market', 'chinext']) {
    const data = retainedFixture();
    Object.assign(data.series.find(line => line.id === id).points.at(-1), { retained: true, retained_reason: 'waiting_verified_quote' });
    same(parsed(data).status, 'invalid');
  }
  for (const flag of [false, true]) invalid(data => { data.series[0].points[0].retained = flag; });
});

test('an explicit false retained flag on a live point does not imply retained state', () => {
  const data = retainedFixture();
  for (const id of ['account', 'd0']) {
    const item = data.series.find(line => line.id === id).points.at(-1);
    item.retained = false; delete item.retained_reason;
  }
  const result = available(data);
  same(result.series[0].points.at(-1).retained, false);
  same(result.series[3].points.at(-1).retained, false);
});

test('retained points must contain a real value from today in the current open segment', () => {
  const priorDay = retainedFixture(); priorDay.generated_at = '2026-10-28T01:00:00Z';
  same(parsed(priorDay).status, 'invalid');
  const empty = retainedFixture(); empty.series[0].points.at(-1).equity = null;
  empty.series[0].points.at(-1).return_ratio = null;
  same(parsed(empty).status, 'invalid');
  const closed = retainedFixture(); closed.segments[0].ends_at = closed.generated_at;
  same(parsed(closed).status, 'invalid');
});

test('a live row date and range cutoff use the latest observation across midnight', () => {
  const historicAccount = { ...httpAccount, created_at: '2026-09-01T01:00:00Z' };
  const data = fixture();
  data.account_created_at = historicAccount.created_at; data.requested_start_at = historicAccount.created_at;
  data.segments[0].starts_at = historicAccount.created_at; data.segments[0].baseline_at = iso('2026-09-01');
  for (const line of data.series) {
    line.points = [point(line.id, '2026-09-01'),
      point(line.id, '2026-09-27', { equity: '101000', return_ratio: 0.01 }),
      point(line.id, '2026-09-28', { equity: '101000', return_ratio: 0.01 })];
    line.as_of = iso('2026-09-28');
  }
  const sourceTime = '2026-10-26T15:59:58Z'; // 23:59:58 in China.
  const observed = ['2026-10-26T15:59:59Z', '2026-10-26T16:00:05Z'];
  data.series.slice(0, 2).forEach((line, index) => {
    line.points.push(point(line.id, '2026-10-26', { key: line.id + '-midnight-live', at: sourceTime,
      phase: 'intraday_estimate', source_at: sourceTime, observed_at: observed[index],
      equity: '102000', return_ratio: 0.02 }));
    line.as_of = sourceTime;
  });
  const result = parsed(data, historicAccount); same(result.status, 'available');
  const rows = comparisonRows(result.data), live = rows[rows.length - 1];
  same(rows.length, 4); same(live.phase, 'live');
  same(live.at, Date.parse(observed[1])); same(live.date, '2026-10-27');
  same(live.points.account.date, '2026-10-26');
  same(live.points.account.observed_at, observed[0]); same(live.points.market.observed_at, observed[1]);
  const recent = comparisonRangeRows(rows, 30);
  same(recent.map(row => row.date).join(','), '2026-09-28,2026-10-27');
  same(recent[recent.length - 1].key, live.key);
});

test('does not put a daily close into a missing live estimate', () => {
  const data = fixture();
  data.series[0].points.push(point('account', '2026-10-27', {
    key: 'account-live', at: '2026-10-27T07:00:01Z', source_at: '2026-10-27T07:00:01Z',
    observed_at: '2026-10-27T07:00:02Z', phase: 'intraday_estimate', equity: '102000', return_ratio: 0.02 }));
  data.series[0].as_of = '2026-10-27T07:00:01Z';
  const rows = comparisonRows(available(data));
  same(rows.length, 3);
  same(rows[2].phase, 'live');
  same(rows[2].points.market, undefined);
  same(rows[2].points.chinext, undefined);
  same(rows[2].points.d0, undefined);
});

test('an unavailable benchmark leaves the other three lines usable', () => {
  const data = fixture();
  data.series[1].status = 'unavailable'; data.series[1].reason = 'index_history_unavailable';
  data.series[1].points = []; data.series[1].as_of = null;
  const rows = comparisonRows(available(data));
  same(rows.length, 2);
  for (const row of rows) {
    same(row.points.market, undefined);
    ok(row.points.account); ok(row.points.chinext); ok(row.points.d0);
  }
});

test('waiting and unavailable envelopes do not fabricate chart data', () => {
  for (const status of ['waiting', 'unavailable', 'invalid']) {
    const data = fixture(); data.status = status; data.reason = 'not_ready';
    data.segments[0].baseline_at = null; data.segments[0].baseline_equity = null;
    for (const line of data.series) { line.status = 'unavailable'; line.reason = 'not_ready'; line.points = []; line.as_of = null; }
    same(parsed(data).status, 'waiting');
  }
});

test('range selection uses elapsed calendar time and never fills missing rows', () => {
  const dates = ['2026-01-01', '2026-07-01', '2026-08-20', '2026-10-01', '2026-10-20', '2026-10-27'];
  const rows = dates.map((date, index) => ({ key: 'row-' + index, at: Date.parse(iso(date)),
    date, segment_id: 'initial', phase: 'daily', points: index % 2 ? { account: point('account', date) } : {} }));
  const all = comparisonRangeRows(rows, 'all');
  const recent30 = comparisonRangeRows(rows, 30);
  const recent90 = comparisonRangeRows(rows, 90);
  same(all.length, 6); same(recent30.length, 3); same(recent90.length, 4);
  same(recent30.map(row => row.date).join(','), '2026-10-01,2026-10-20,2026-10-27');
  same(recent90.map(row => row.date).join(','), '2026-08-20,2026-10-01,2026-10-20,2026-10-27');
  same(recent30[1].points.account, undefined);
  same(JSON.stringify(rows[4].points), '{}');
  same(comparisonRangeRows([], 30).length, 0);
});

// A small inert DOM lets lifecycle tests use the public API and real renderer.
// Timers are recorded, never run, and the only loader is a synthetic promise.
function uiHarness({ width, paddingLeft = '0px', paddingRight = '0px' } = {}) {
  const timers = new Map(), requests = [], documentListeners = new Map(), windowListeners = new Map();
  let timerId = 0;
  const doc = { activeElement: null,
    addEventListener(type, fn) { documentListeners.set(type, fn); },
    createElement(tag) { return new Element(tag); },
    createElementNS(_namespace, tag) { return new Element(tag); },
  };
  class Element {
    constructor(tag) {
      this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {};
      this.listeners = new Map(); this.className = ''; this.value = ''; this._text = '';
      this.replacements = 0; this.isConnected = true;
      this.style = { setProperty() {} };
      this.classList = { add: (...names) => { this.className += ' ' + names.join(' '); } };
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.replacements++; this._text = ''; this.children = children; }
    setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'class') this.className = String(value); }
    addEventListener(type, fn) { if (!this.listeners.has(type)) this.listeners.set(type, []); this.listeners.get(type).push(fn); }
    dispatch(type, values = {}) { for (const fn of this.listeners.get(type) || []) fn({ preventDefault() {}, ...values }); }
    contains(element) { return this === element || this.children.some(child => child.contains(element)); }
    querySelectorAll() { return this.all().filter(element => element.dataset.rtpcControl); }
    all() { return this.children.flatMap(child => [child, ...child.all()]); }
    focus() { doc.activeElement = this; }
    getBoundingClientRect() { return { left: 0, width: 940 }; }
  }
  const rootElement = new Element('section');
  rootElement.clientWidth = width; rootElement.testPaddingLeft = paddingLeft; rootElement.testPaddingRight = paddingRight;
  const uiContext = vm.createContext({
    window: { ETF_I18n: { language: 'zh' },
      addEventListener(type, fn) { windowListeners.set(type, fn); },
      getComputedStyle(element) { return { paddingLeft: element.testPaddingLeft, paddingRight: element.testPaddingRight }; },
    }, document: doc,
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  vm.runInContext(source, uiContext, { filename: 'realtime-paper-comparison.js' });
  const api = uiContext.window.RealtimePaperComparison;
  const load = id => new Promise((resolve, reject) => requests.push({ id, resolve, reject }));
  api.init({ root: rootElement, load });
  return { api, root: rootElement, timers, requests, context: uiContext,
    control(name) { return rootElement.all().find(element => element.dataset.rtpcControl === name); },
    emitLanguage() { documentListeners.get('etf-language-change')?.(); },
    emitResize() { windowListeners.get('resize')?.(); },
    setNow(value) { assert.ok(Number.isFinite(value)); vm.runInContext('Date.now = () => ' + value, uiContext); },
    fireTimer(delay) {
      const entry = [...timers].find(([, timer]) => timer.delay === delay);
      assert.ok(entry, 'Expected a synthetic ' + delay + 'ms timer');
      timers.delete(entry[0]); entry[1].fn();
    },
  };
}
async function asyncTest(name, body) {
  try { await body(); cases.push(name); }
  catch (error) { failures.push({ name, error }); }
}
async function pendingRequest(harness, accountValue = account) {
  harness.api.update(accountValue); harness.api.setActive(true);
  const pending = harness.api.refresh();
  await Promise.resolve();
  return { pending };
}
async function loadedUi(data = fixture(), accountValue = account, dimensions) {
  const h = uiHarness(dimensions);
  const { pending } = await pendingRequest(h, accountValue);
  same(h.requests.length, 1);
  h.requests[0].resolve(data); await pending;
  return h;
}

async function main() {
  await asyncTest('fresh retained points are awaiting verification even alongside fresh index quotes', async () => {
    const h = await loadedUi(retainedFixture());
    h.setNow(Date.parse('2026-10-27T07:00:35Z')); h.emitLanguage();
    const cards = h.root.all().filter(element => element.className.includes('rtpc-series-card'));
    for (const index of [0, 3]) {
      ok(cards[index].textContent.includes('上次暂估（等待核对）'));
      ok(!cards[index].textContent.includes('最新暂估'));
    }
    for (const index of [1, 2]) ok(cards[index].textContent.includes('最新暂估'));
    const title = h.root.all().find(element => element.className.includes('rtpc-selection-title')).textContent;
    ok(title.includes('含上次核验值')); ok(!title.includes('最新暂估'));
    ok(h.control('scrubber').attributes['aria-valuetext'].includes('含上次核验值'));
    ok(h.root.textContent.includes('历史缺口不补成零或沿用前值'));
    same(h.root.all().filter(element => element.tagName === 'path').length, 4);
    same(h.requests.length, 1);
  });

  await asyncTest('retained points remain explicitly unverified after expiry and translate in the data table', async () => {
    const h = await loadedUi(retainedFixture());
    h.setNow(Date.parse('2026-10-27T07:10:00Z')); h.emitLanguage();
    const disclosure = h.root.all().find(element => element.tagName === 'details');
    disclosure.open = true; disclosure.dispatch('toggle');
    ok(h.root.textContent.includes('上次暂估（等待核对）'));
    ok(h.root.textContent.includes('盘中保留上次真实暂估及原时间'));
    h.context.window.ETF_I18n.language = 'en'; h.emitLanguage();
    ok(h.root.textContent.includes('Previous estimate (awaiting verification)'));
    ok(h.root.textContent.includes('Estimates (includes previously verified values)'));
    ok(h.root.textContent.includes('retains its original time'));
    same(h.requests.length, 1);
  });

  await asyncTest('a new verified response replaces retained flags and returns to latest labels', async () => {
    const h = await loadedUi(retainedFixture());
    h.setNow(Date.parse('2026-10-27T07:00:35Z')); h.emitLanguage();
    const next = retainedFixture(); next.generated_at = '2026-10-27T07:00:36Z';
    for (const line of next.series) {
      const item = line.points.at(-1);
      delete item.retained; delete item.retained_reason;
      item.at = item.source_at = item.observed_at = line.as_of = '2026-10-27T07:00:35Z';
    }
    const pending = h.api.refresh(); await Promise.resolve();
    h.requests[1].resolve(next); await pending;
    ok(!h.root.textContent.includes('上次暂估（等待核对）'));
    const title = h.root.all().find(element => element.className.includes('rtpc-selection-title')).textContent;
    ok(title.includes('最新暂估')); ok(!title.includes('含上次核验值'));
    same(h.control('scrubber').max, '2');
    same(h.requests.length, 2);
  });

  await asyncTest('retained cash-only points do not claim a current cash valuation', async () => {
    const data = cashFixture();
    for (const id of ['account', 'd0']) Object.assign(data.series.find(line => line.id === id).points.at(-1),
      { retained: true, retained_reason: 'waiting_verified_quote' });
    const h = await loadedUi(data);
    h.setNow(Date.parse('2026-10-27T07:00:35Z')); h.emitLanguage();
    ok(h.root.textContent.includes('上次暂估（等待核对）'));
    ok(!h.root.textContent.includes('现金估值，无需持仓报价'));
    ok(h.root.all().find(element => element.className.includes('rtpc-selection-title')).textContent.includes('含上次核验值'));
    same(h.requests.length, 1);
  });

  await asyncTest('leaving before the initial microtask does not invoke the loader', async () => {
    const h = uiHarness();
    h.api.update(httpAccount); h.api.setActive(true);
    const pending = h.api.refresh();
    same(h.requests.length, 0);
    h.api.setActive(false);
    const renders = h.root.replacements;
    await pending;
    same(h.requests.length, 0); same(h.timers.size, 0);
    same(h.root.replacements, renders);
  });

  await asyncTest('real HTTP accounts load and initial_cash changes clear cached history', async () => {
    const h = await loadedUi(fixture(), httpAccount);
    ok(h.root.all().some(element => element.tagName === 'svg'));
    h.api.update({ ...httpAccount, initial_cash: '200000' }, { current: false });
    ok(!h.root.textContent.includes('本次资料生成时间'));
    ok(!h.root.textContent.includes('上次成功读取'));
    ok(h.root.textContent.includes('账户状态尚未核对'));
    same(h.timers.size, 0); same(h.requests.length, 1);
  });

  await asyncTest('changing only the shadowed legacy capital does not change HTTP identity', async () => {
    const h = await loadedUi(fixture(), { ...httpAccount, initial_capital: '100000' });
    h.api.update({ ...httpAccount, initial_capital: '200000' });
    await Promise.resolve();
    ok(h.root.textContent.includes('本次资料生成时间'));
    ok(h.root.all().some(element => element.tagName === 'svg'));
    same(h.requests.length, 1); same(h.timers.size, 1);
  });

  await asyncTest('an invalid HTTP primary capital clears cache and prevents reads', async () => {
    const h = await loadedUi(fixture(), { ...httpAccount, initial_capital: '100000' });
    h.api.update({ ...httpAccount, initial_cash: null, initial_capital: '100000' });
    await h.api.refresh();
    same(h.root.all().find(element => element.className === 'rtpc-empty')?.textContent, '尚未选择当前策略账户。');
    ok(!h.root.textContent.includes('本次资料生成时间'));
    same(h.requests.length, 1); same(h.timers.size, 0);
  });

  await asyncTest('leaving the page cancels polling and ignores a late GET response', async () => {
    const h = uiHarness();
    const { pending } = await pendingRequest(h);
    same(h.requests.length, 1);
    h.api.setActive(false);
    const before = h.root.textContent, renders = h.root.replacements;
    h.requests[0].resolve(fixture()); await pending;
    same(h.root.textContent, before); same(h.root.replacements, renders);
    same(h.timers.size, 0);
    ok(h.root.textContent.includes('离开此页已暂停刷新'));
  });

  await asyncTest('a late response from the prior account cannot replace the new account', async () => {
    const h = uiHarness();
    const { pending: first } = await pendingRequest(h);
    const secondAccount = { ...account, id: 'second-account', created_at: '2026-10-01T02:00:00Z' };
    h.api.update(secondAccount);
    const second = h.api.refresh(); await Promise.resolve();
    same(h.requests.length, 2); same(h.requests[1].id, secondAccount.id);
    const secondData = fixture();
    secondData.account_id = secondAccount.id; secondData.account_created_at = secondAccount.created_at;
    secondData.requested_start_at = secondAccount.created_at; secondData.segments[0].starts_at = secondAccount.created_at;
    h.requests[1].resolve(secondData); await second;
    const text = h.root.textContent, renders = h.root.replacements;
    const oldData = fixture(); oldData.generated_at = '2026-10-26T07:05:00Z';
    h.requests[0].resolve(oldData); await first;
    same(h.root.textContent, text); same(h.root.replacements, renders);
    same(h.timers.size, 1);
    same([...h.timers.values()][0].delay, 30000);
  });

  await asyncTest('account id, creation time, and capital changes clear a previous cache', async () => {
    for (const replacement of [
      { ...account, id: 'new-account' },
      { ...account, created_at: '2026-10-01T02:00:00Z' },
      { ...account, initial_capital: '200000' },
    ]) {
      const h = await loadedUi();
      ok(h.root.textContent.includes('本次资料生成时间'));
      h.api.update(replacement, { current: false });
      ok(!h.root.textContent.includes('本次资料生成时间'));
      ok(!h.root.textContent.includes('上次成功读取'));
      ok(h.root.textContent.includes('账户状态尚未核对'));
      same(h.timers.size, 0); same(h.requests.length, 1);
    }
  });

  await asyncTest('an unverified account snapshot stops polling and marks retained data as cache', async () => {
    const h = await loadedUi();
    h.api.update(account, { current: false });
    same(h.timers.size, 0);
    ok(h.root.textContent.includes('主账户状态尚未核对'));
    ok(h.root.textContent.includes('上次成功读取'));
    await h.api.refresh(); same(h.requests.length, 1);
  });

  await asyncTest('a failed GET keeps the prior graph with a cache timestamp', async () => {
    const h = await loadedUi();
    const pending = h.api.refresh(); await Promise.resolve();
    same(h.requests.length, 2);
    h.requests[1].reject(new Error('synthetic read error')); await pending;
    ok(h.root.textContent.includes('读取失败，正在显示上次成功读取的缓存'));
    ok(h.root.textContent.includes('上次成功读取'));
    ok(h.root.all().some(element => element.tagName === 'svg'));
    same(h.timers.size, 1);
  });

  await asyncTest('a retry keeps the failed-read cache warning until a GET succeeds', async () => {
    const h = await loadedUi();
    const failed = h.api.refresh(); await Promise.resolve();
    h.requests[1].reject(new Error('synthetic first read error')); await failed;
    ok(h.root.textContent.includes('读取失败，正在显示上次成功读取的缓存'));
    const retry = h.api.refresh();
    ok(h.root.textContent.includes('读取失败，正在显示上次成功读取的缓存'));
    ok(h.root.textContent.includes('上次成功读取'));
    ok(h.root.all().some(element => element.tagName === 'svg'));
    await Promise.resolve(); same(h.requests.length, 3);
    ok(h.root.textContent.includes('读取失败，正在显示上次成功读取的缓存'));
    h.requests[2].resolve(fixture()); await retry;
    ok(!h.root.textContent.includes('读取失败，正在显示上次成功读取的缓存'));
    ok(!h.root.textContent.includes('上次成功读取'));
    ok(h.root.all().some(element => element.tagName === 'svg'));
    same(h.timers.size, 1);
  });

  await asyncTest('a read timeout retains cached data, reports failure, and schedules another read', async () => {
    const h = await loadedUi();
    const pending = h.api.refresh(); await Promise.resolve();
    same(h.requests.length, 2); same(h.timers.size, 1);
    same([...h.timers.values()][0].delay, 25000);
    same(h.control('refresh').disabled, true);
    h.fireTimer(25000); await pending;
    ok(h.root.textContent.includes('读取失败，正在显示上次成功读取的缓存'));
    ok(h.root.textContent.includes('上次成功读取'));
    ok(h.root.all().some(element => element.tagName === 'svg'));
    same(h.control('refresh').disabled, false);
    same(h.timers.size, 1); same([...h.timers.values()][0].delay, 30000);
  });

  await asyncTest('a response arriving after its timeout cannot overwrite a newer successful read', async () => {
    const h = await loadedUi();
    const expired = h.api.refresh(); await Promise.resolve();
    h.fireTimer(25000); await expired;
    const newer = h.api.refresh(); await Promise.resolve();
    same(h.requests.length, 3);
    const fresh = fixture(); fresh.generated_at = '2026-10-27T07:06:00Z';
    fresh.series[0].points[1].equity = '102000'; fresh.series[0].points[1].return_ratio = 0.02;
    h.requests[2].resolve(fresh); await newer;
    const before = h.root.textContent, renders = h.root.replacements;
    h.requests[1].resolve(fixture());
    await Promise.resolve(); await Promise.resolve();
    same(h.root.textContent, before); same(h.root.replacements, renders);
    same(h.timers.size, 1); same([...h.timers.values()][0].delay, 30000);
    ok(!h.root.textContent.includes('读取失败，正在显示上次成功读取的缓存'));
  });

  await asyncTest('leaving the page clears the in-flight 25-second deadline', async () => {
    const h = await loadedUi();
    same([...h.timers.values()][0].delay, 30000);
    const pending = h.api.refresh(); await Promise.resolve();
    same(h.timers.size, 1); same([...h.timers.values()][0].delay, 25000);
    h.api.setActive(false); same(h.timers.size, 0);
    const before = h.root.textContent, renders = h.root.replacements;
    h.requests[1].resolve(fixture()); await pending;
    same(h.root.textContent, before); same(h.root.replacements, renders);
    same(h.timers.size, 0);
  });

  await asyncTest('range, legend, cursor, table, and translation controls are local', async () => {
    const h = await loadedUi();
    h.control('range-30').dispatch('click');
    h.control('legend-market').dispatch('click');
    let slider = h.control('scrubber');
    slider.value = '0'; slider.dispatch('input');
    slider.dispatch('keydown', { key: 'End' });
    same(slider.value, '1');
    slider.dispatch('keydown', { key: 'Home' }); same(slider.value, '0');
    const svg = h.control('chart');
    svg.dispatch('pointerdown', { clientX: 900, pointerId: 1 });
    same(slider.value, '1');
    const disclosure = h.root.all().find(element => element.tagName === 'details');
    disclosure.open = true; disclosure.dispatch('toggle');
    ok(h.root.all().some(element => element.tagName === 'table'));
    h.context.window.ETF_I18n.language = 'en'; h.emitLanguage();
    ok(h.root.textContent.includes('Account and benchmark returns'));
    same(h.control('legend-market').attributes['aria-pressed'], 'false');
    same(h.control('range-30').attributes['aria-pressed'], 'true');
    same(h.requests.length, 1);
  });

  await asyncTest('explicit cash estimates use observed time or record time and expire after 90 seconds', async () => {
    for (const options of [
      { observed: '2026-10-27T07:00:10Z', at: '2026-10-27T06:00:00Z' },
      { observed: null, at: '2026-10-27T07:00:10Z' },
    ]) {
      const h = await loadedUi(cashFixture(options));
      h.setNow(Date.parse('2026-10-27T07:01:40Z')); h.emitLanguage();
      ok(h.root.textContent.includes('现金估值，无需持仓报价'));
      ok(h.root.all().find(element => element.className.includes('rtpc-selection-title')).textContent.includes('最新暂估'));
      ok(!h.root.textContent.includes('上次现金估值（已过期）'));
      h.setNow(Date.parse('2026-10-27T07:01:40.001Z')); h.emitLanguage();
      ok(h.root.textContent.includes('上次现金估值（已过期）'));
      ok(h.root.all().find(element => element.className.includes('rtpc-selection-title')).textContent.includes('上次现金估值（已过期）'));
      h.context.window.ETF_I18n.language = 'en'; h.emitLanguage();
      ok(h.root.textContent.includes('Previous cash valuation (expired)'));
      same(h.requests.length, 1);
    }
  });

  await asyncTest('a missing quote source without cash_only remains unverified', async () => {
    const h = await loadedUi(cashFixture({ marked: false }));
    h.setNow(Date.parse('2026-10-27T07:00:30Z')); h.emitLanguage();
    ok(h.root.textContent.includes('上次暂估（时间待核对）'));
    ok(!h.root.textContent.includes('现金估值'));
    const title = h.root.all().find(element => element.className.includes('rtpc-selection-title')).textContent;
    ok(!title.includes('最新暂估'));
    same(h.requests.length, 1);
  });

  await asyncTest('future quote and cash times need verification beyond the five-second allowance', async () => {
    for (const mode of ['quote', 'cash-observed', 'cash-at']) {
      const data = cashFixture({ marked: mode !== 'quote',
        observed: mode === 'cash-at' ? null : '2026-10-27T07:00:10Z',
        at: mode === 'cash-observed' ? '2026-10-27T07:00:00Z' : '2026-10-27T07:00:10Z' });
      if (mode === 'quote') for (const line of data.series) {
        if (['account', 'd0'].includes(line.id)) line.points.at(-1).source_at = '2026-10-27T07:00:10Z';
      }
      const h = await loadedUi(data);
      h.setNow(Date.parse('2026-10-27T07:00:04.999Z')); h.emitLanguage();
      const title = () => h.root.all().find(element => element.className.includes('rtpc-selection-title')).textContent;
      ok(title().includes('时间待核对')); ok(!title().includes('最新暂估'));
      ok(h.root.textContent.includes(mode === 'quote' ? '上次暂估（时间待核对）' : '现金估值时间待核对'));
      h.setNow(Date.parse('2026-10-27T07:00:05Z')); h.emitLanguage();
      ok(title().includes('最新暂估'));
      ok(h.root.textContent.includes(mode === 'quote' ? '最新暂估' : '现金估值，无需持仓报价'));
      same(h.requests.length, 1);
    }
  });

  await asyncTest('mobile SVG sizing subtracts padding, limits date ticks, and keeps a compact height', async () => {
    const data = fixture();
    for (const line of data.series) {
      line.points[1] = point(line.id, '2026-10-27', { equity: '101000', return_ratio: 0.01 });
      line.as_of = iso('2026-10-27');
    }
    for (const [width, expected] of [[320, '0 0 280 250'], [360, '0 0 320 250'], [400, '0 0 360 260']]) {
      const h = await loadedUi(data, account, { width, paddingLeft: '20px', paddingRight: '20px' });
      const svg = h.control('chart'); same(svg.attributes.viewBox, expected);
      const dateTicks = svg.all().filter(element => element.tagName === 'text' && /^\d{2}-\d{2}$/.test(element.textContent));
      ok(dateTicks.length > 0); ok(dateTicks.length <= 3);
      ok(!svg.all().some(element => element.tagName === 'text' && /^\d{4}-\d{2}-\d{2}$/.test(element.textContent)));
      same(h.requests.length, 1);
    }
    const desktop = await loadedUi(data, account, { width: 1200, paddingLeft: '20px', paddingRight: '20px' });
    same(desktop.control('chart').attributes.viewBox, '0 0 960 350');
    const narrow = await loadedUi(data, account, { width: 200 });
    same(narrow.control('chart').attributes.viewBox, '0 0 240 250');
    const unknown = await loadedUi(data); same(unknown.control('chart').attributes.viewBox, '0 0 960 350');
  });

  await asyncTest('debounced resize preserves selections and never causes a GET', async () => {
    const h = await loadedUi(fixture(), account, { width: 1000, paddingLeft: '20px', paddingRight: '20px' });
    h.control('range-30').dispatch('click'); h.control('legend-market').dispatch('click');
    const slider = h.control('scrubber'); slider.value = '0'; slider.dispatch('input');
    const selected = h.root.dataset.selectedDate, renders = h.root.replacements;
    h.root.clientWidth = 360;
    h.emitResize(); h.emitResize(); h.emitResize();
    same(h.root.replacements, renders);
    same([...h.timers.values()].filter(timer => timer.delay === 100).length, 1);
    h.fireTimer(100);
    same(h.root.replacements, renders + 1);
    same(h.control('chart').attributes.viewBox, '0 0 320 250');
    same(h.root.dataset.selectedDate, selected); same(h.control('scrubber').value, '0');
    same(h.control('legend-market').attributes['aria-pressed'], 'false');
    same(h.control('range-30').attributes['aria-pressed'], 'true');
    same(h.requests.length, 1);
    const unchanged = h.root.replacements;
    h.emitResize(); h.fireTimer(100);
    same(h.root.replacements, unchanged); same(h.requests.length, 1);
    same(h.timers.size, 1); same([...h.timers.values()][0].delay, 30000);
  });

  await asyncTest('inactive and unverified pages clear queued resize work and ignore further resize events', async () => {
    for (const stop of [h => h.api.setActive(false), h => h.api.update(account, { current: false })]) {
      const h = await loadedUi(fixture(), account, { width: 960 });
      h.root.clientWidth = 320; h.emitResize();
      same([...h.timers.values()].filter(timer => timer.delay === 100).length, 1);
      stop(h); same(h.timers.size, 0);
      const renders = h.root.replacements;
      h.root.clientWidth = 400; h.emitResize();
      same(h.root.replacements, renders); same(h.timers.size, 0); same(h.requests.length, 1);
    }
  });

  await asyncTest('English index_anchor_missing explains the missing segment baseline quote', async () => {
    const data = fixture();
    const market = data.series.find(line => line.id === 'market');
    market.status = 'unavailable'; market.reason = 'index_anchor_missing'; market.points = []; market.as_of = null;
    const h = await loadedUi(data);
    h.context.window.ETF_I18n.language = 'en'; h.emitLanguage();
    const explanation = h.control('legend-market').textContent;
    ok(explanation.includes('The index quote at this segment’s shared baseline is missing.'));
    ok(!explanation.includes('Waiting for the first shared close'));
    same(h.requests.length, 1);
  });

  await asyncTest('single-point charts draw one marker per series without a connecting stroke', async () => {
    const data = fixture();
    for (const line of data.series) { line.points = [line.points[0]]; line.as_of = line.points[0].at; }
    const h = await loadedUi(data);
    const elements = h.root.all();
    same(elements.filter(element => element.tagName === 'circle').length, 4);
    const paths = elements.filter(element => element.tagName === 'path');
    same(paths.length, 4);
    for (const item of paths) { ok(item.attributes.d.startsWith('M')); ok(!item.attributes.d.includes('L')); }
  });

  await asyncTest('the SVG explicitly breaks each curve between capital segments', async () => {
    const h = await loadedUi(twoSegments());
    const paths = h.root.all().filter(element => element.tagName === 'path');
    same(paths.length, 4);
    for (const item of paths) {
      same((item.attributes.d.match(/M/g) || []).length, 2);
      same((item.attributes.d.match(/L/g) || []).length, 1);
    }
  });

  await asyncTest('reset clears data and rejects an in-flight response', async () => {
    const h = await loadedUi();
    const pending = h.api.refresh(); await Promise.resolve();
    h.api.reset();
    const before = h.root.textContent, renders = h.root.replacements;
    h.requests[1].resolve(fixture()); await pending;
    same(h.root.textContent, before); same(h.root.replacements, renders);
    same(h.root.all().find(element => element.className === 'rtpc-empty')?.textContent, '尚未选择当前策略账户。');
    same(h.timers.size, 0);
  });

  for (const failure of failures) console.error('FAIL: ' + failure.name + '\n' + failure.error.stack);
  console.log('D0 comparison frontend: ' + cases.length + ' cases passed, ' + failures.length + ' failed, ' + checks + ' checks.');
  if (failures.length) process.exitCode = 1;
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
