#!/usr/bin/env node
'use strict';

// Exercise production account loading with synthetic responses and a virtual clock.
// No browser, network connection, production account or command submission is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../production/web_static/app.js'), 'utf8');
function section(start, end) {
  assert.equal(source.split(start).length, 2, `Unique source marker: ${start}`);
  return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
}
const production = [
  section('  function resetAccountRead()', '  function latestFor('),
  section('  function applyPendingAccountUpdate(', '  function makeTable('),
  section('  async function changeAccountGroup(', '  async function loadOverview('),
  section('  function showLogin()', '  async function startApp('),
].join('\n');

class Element {
  constructor(tag = 'div', text = '') { this.tagName = tag.toUpperCase(); this.textContent = text; this.children = []; this.dataset = {}; this.hidden = false; }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  prepend(node) { node.parent = this; this.children.unshift(node); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); }
  setAttribute() {}
  querySelector(selector) {
    for (const child of this.children) {
      if (selector === '[data-account-read-status]' && child.dataset.accountReadStatus) return child;
      const found = child.querySelector(selector); if (found) return found;
    }
    return null;
  }
  get text() { return [this.textContent, ...this.children.map(n => n.text)].join(' '); }
}
const error = (status = 503) => Object.assign(new Error('synthetic account temporarily unavailable'), { status });
const detail = id => ({ summary: { id, name: `Synthetic ${id}`, day: '2026-11-11' }, events: [] });
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

function fixture() {
  const nodes = new Map(), timers = new Map(), calls = [], errors = [], renders = [];
  let timerId = 0;
  const state = { authenticated: true, group: 'seven', accountId: null, accountRequest: 0, accountRead: null,
    accountDetail: null, accountDetailKey: null, accountDetailRevision: null, pendingAccountDetail: null,
    accounts: [{ id: 'A' }, { id: 'B' }], dataRevision: null, revisionSyncing: false, page: 'accounts',
    settings: { revision: 'r1' }, accountBenchmarks: new Map(), accountBenchmarkViews: new Map() };
  const ctx = vm.createContext({
    state, JSON, Promise, Error, encodeURIComponent, console,
    $: id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); },
    el: (tag, klass, text) => new Element(tag, text),
    empty: (title, text) => new Element('div', title + ' ' + text),
    button: (label, action) => Object.assign(new Element('button', label), { action }),
    replace: (node, ...children) => node.replaceChildren(...children),
    errorMessage: e => e.message,
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id),
    api: async route => {
      calls.push(route);
      if (route.startsWith('/api/account?')) return ctx.respond(new URL('https://synthetic.invalid' + route).searchParams);
      if (route.startsWith('/api/accounts?')) return state.accounts;
      if (route === '/api/overview') return { market: {} };
      throw new Error('Unexpected route: ' + route);
    },
    respond: query => detail(query.get('id')),
    renderAccountDetail: values => {
      renders.push({ detail: state.accountDetail, values });
      ctx.$('account-detail').replaceChildren(new Element('div', state.accountDetail.summary.name));
    },
    renderAccountList() {}, renderAccountWarnings() {}, renderOverview() {}, renderGroupButtons() {},
    loadAccounts: async () => {}, loadOverseas: async () => {},
    showError: value => errors.push(value), showPage: page => { state.page = page; },
    editingInside: () => false, preserveAccountInputs: () => ({ draft: 'user input' }),
    window: {}, document: { querySelectorAll: () => [] }, restoreCleanup: null, navigationKey: null,
    setCreatePending() {},
  });
  vm.runInContext(production, ctx, { filename: 'app-account-loading.js' });
  return { ctx, state, calls, timers, renders, errors, root: ctx.$('account-detail'),
    accountCalls: () => calls.filter(route => route.startsWith('/api/account?')).length,
    async nextTimer(expected) {
      assert.equal(timers.size, 1, 'Only one account retry may be pending');
      const [id, timer] = timers.entries().next().value; assert.equal(timer.delay, expected);
      timers.delete(id); timer.fn(); await state.accountRead?.promise;
    },
  };
}

const cases = [];
async function test(name, run) { await run(); cases.push(name); }
(async () => {
  await test('first read recovers and completes the same revision', async () => {
    const f = fixture(); let first = true;
    f.ctx.respond = query => { if (first) { first = false; throw error(); } return detail(query.get('id')); };
    await f.ctx.selectAccount('A');
    assert.equal(f.state.accountDetail, null); assert.match(f.root.text, /自动重试/);
    await f.ctx.refreshForRevision('r1');
    assert.equal(f.state.dataRevision, null, 'A failed detail must not consume the revision');
    assert.equal(f.accountCalls(), 1, 'Settings polling must honor retry backoff');
    await f.nextTimer(5000);
    assert.equal(f.state.accountDetail.summary.id, 'A'); assert.equal(f.timers.size, 0);
    await f.ctx.refreshForRevision('r1');
    assert.equal(f.state.dataRevision, 'r1'); assert.equal(f.accountCalls(), 2);
    assert.equal(f.errors.length, 0, 'Recoverable errors stay inside the account pane');
  });

  await test('existing records stay visible; retries are bounded and manually resumable', async () => {
    const f = fixture(); await f.ctx.selectAccount('A'); const saved = f.state.accountDetail;
    f.state.settings.revision = 'r2'; f.ctx.respond = () => { throw error(); };
    await f.ctx.refreshForRevision('r2');
    assert.equal(f.state.accountDetail, saved); assert.match(f.root.text, /Synthetic A/); assert.match(f.root.text, /保留上次/);
    for (const delay of [5000, 15000, 30000]) await f.nextTimer(delay);
    assert.equal(f.timers.size, 0); assert.match(f.root.text, /自动重试已暂停/);
    for (let i = 0; i < 6; i++) await f.ctx.refreshForRevision('r2');
    assert.equal(f.accountCalls(), 5, 'Initial successful request plus four attempts in this failure episode');
    assert.notEqual(f.state.dataRevision, 'r2');
    f.ctx.respond = query => detail(query.get('id'));
    const retry = f.root.querySelector('[data-account-read-status]').children.at(-1).children[0];
    await retry.action(); assert.equal(f.state.accountRead, null); assert.doesNotMatch(f.root.text, /自动重试/);
    await f.ctx.refreshForRevision('r2'); assert.equal(f.state.dataRevision, 'r2');
  });

  await test('switching accounts cannot retain or overwrite another account', async () => {
    const f = fixture(); await f.ctx.selectAccount('A');
    const pending = deferred(); f.ctx.respond = query => query.get('id') === 'B' ? pending.promise : detail('A');
    const oldRequest = f.ctx.selectAccount('B');
    assert.equal(f.state.accountDetail, null); assert.doesNotMatch(f.root.text, /Synthetic A/);
    await f.ctx.selectAccount('A'); pending.reject(error()); await oldRequest;
    assert.equal(f.state.accountDetail.summary.id, 'A'); assert.equal(f.timers.size, 0);
    assert.doesNotMatch(f.root.text, /暂未能读取/);
  });

  await test('same-account clicks and revision polling share one in-flight request', async () => {
    const f = fixture(), pending = deferred(); f.ctx.respond = () => pending.promise;
    const a = f.ctx.selectAccount('A'), b = f.ctx.selectAccount('A'), c = f.ctx.refreshForRevision('r1');
    assert.equal(f.accountCalls(), 1); pending.resolve(detail('A')); await Promise.all([a, b, c]);
    assert.equal(f.accountCalls(), 1); assert.equal(f.state.dataRevision, 'r1');
  });

  await test('editing preserves input while successful detail waits to be applied', async () => {
    const f = fixture(); await f.ctx.selectAccount('A');
    f.ctx.editingInside = () => true; f.state.settings.revision = 'r2';
    await f.ctx.refreshForRevision('r2'); const count = f.accountCalls();
    assert.equal(f.state.pendingAccountDetail.id, 'A'); assert.equal(f.ctx.$('account-sync-note').hidden, false);
    await f.ctx.readCurrentAccount('r2'); assert.equal(f.accountCalls(), count);
    f.ctx.editingInside = () => false; f.ctx.applyPendingAccountUpdate();
    assert.equal(f.renders.at(-1).values.draft, 'user input'); assert.equal(f.state.pendingAccountDetail, null);
  });

  await test('an older in-flight read cannot acknowledge a newer revision', async () => {
    const f = fixture(), pending = deferred(); f.ctx.respond = () => pending.promise;
    const first = f.ctx.selectAccount('A'); f.state.settings.revision = 'r2';
    const refresh = f.ctx.refreshForRevision('r2'); pending.resolve(detail('A')); await Promise.all([first, refresh]);
    assert.equal(f.state.accountDetailRevision, 'r1'); assert.equal(f.state.dataRevision, null);
    f.ctx.respond = query => detail(query.get('id')); await f.ctx.refreshForRevision('r2');
    assert.equal(f.state.dataRevision, 'r2'); assert.equal(f.accountCalls(), 2);
  });

  await test('a new revision can recover after the previous retry budget is exhausted', async () => {
    const f = fixture(); f.ctx.respond = () => { throw error(); }; await f.ctx.selectAccount('A');
    for (const delay of [5000, 15000, 30000]) await f.nextTimer(delay);
    f.ctx.respond = query => detail(query.get('id')); f.state.settings.revision = 'r2';
    await f.ctx.refreshForRevision('r2'); assert.equal(f.state.accountDetail.summary.id, 'A');
    assert.equal(f.state.dataRevision, 'r2'); assert.equal(f.accountCalls(), 5);
  });

  await test('permanent errors do not start automatic retries', async () => {
    const f = fixture(); f.ctx.respond = () => { throw error(404); }; await f.ctx.selectAccount('A');
    assert.equal(f.timers.size, 0); await f.ctx.refreshForRevision('r1'); assert.equal(f.accountCalls(), 1);
    assert.match(f.root.text, /重试读取/); assert.match(f.root.text, /查看任务进度/);
  });

  await test('group changes invalidate a pending response even for an equal account id', async () => {
    const f = fixture(), pending = deferred(); f.ctx.respond = () => pending.promise;
    const oldRequest = f.ctx.selectAccount('A'); await f.ctx.changeAccountGroup('original');
    pending.resolve(detail('A')); await oldRequest;
    assert.equal(f.state.accountDetail, null); assert.equal(f.state.accountDetailKey, null);
    assert.equal(f.state.group, 'original'); assert.equal(f.timers.size, 0);
  });

  await test('logout cancels retry timers and ignores outstanding responses', async () => {
    const f = fixture(); f.ctx.respond = () => { throw error(); }; await f.ctx.selectAccount('A');
    f.ctx.showLogin(); assert.equal(f.timers.size, 0); assert.equal(f.state.accountDetail, null);
    const g = fixture(), pending = deferred(); g.ctx.respond = () => pending.promise;
    const request = g.ctx.selectAccount('A'); g.ctx.showLogin(); pending.resolve(detail('A')); await request;
    assert.equal(g.state.accountDetail, null); assert.equal(g.state.authenticated, false);
  });

  console.log(JSON.stringify({ status: 'passed', cases: cases.length, scenarios: cases, network: 'unused' }));
})().catch(error => { console.error(error); process.exitCode = 1; });
