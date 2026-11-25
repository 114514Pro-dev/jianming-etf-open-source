'use strict';

// Synthetic responses only. The browser never connects to a site or a broker.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.join(__dirname, '../production/web_static');
const origin = 'https://dashboard-test.invalid';
const allocation = Object.fromEntries(['sz159915', 'sh512800', 'sh518880', 'sh511010', 'cash'].map(symbol => {
  const active = symbol === 'sz159915' || symbol === 'cash';
  return [symbol, {weight: active ? '0.5' : '0', target_value: active ? '435000.00' : '0.00'}];
}));
const json = {
  '/api/session': {authenticated: true, csrf: 'synthetic'},
  '/api/catalog': {groups: [{id: 'original', name: 'Synthetic', strategies: [{code: 'D0', name: 'D0'}]}]},
  '/api/overview': {market: {daily_end: '2026-11-23'}, quotes: [{symbol: 'sz159915', price: 1, quote_at: '2026-11-24T09:30:04+08:00'}]},
  '/api/accounts': {accounts: []},
  '/api/settings': {auto_refresh: false},
  '/api/jobs': {jobs: []},
  '/api/d0-control/status': {mode: 'preview_only', live_orders_enabled: false, market_state: 'open', source_status: 'ready', historical_seed: false},
  '/api/d0-control/preview': {mode: 'preview_only', stage: 'buy', equity: '870000.00', allocation, sell_remainder: [],
    orders: [{symbol: 'sz159915', side: 'buy', quantity: 435000, limit_price: '1.002'}]},
};

async function run() {
  const executablePath = process.env.ETF_TEST_BROWSER || undefined;
  const browser = await chromium.launch({executablePath});
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({viewport: {width, height: 850}});
      const writes = [];
      let live = false;
      let connected = false;
      let marketState = 'open';
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== origin) return route.abort();
        if (url.pathname === '/' || url.pathname === '/d0-control') {
          const pageFile = url.pathname === '/' ? 'index.html' : 'd0-control.html';
          return route.fulfill({path: path.join(root, pageFile), contentType: 'text/html; charset=utf-8'});
        }
        if (url.pathname.startsWith('/static/')) {
          const file = path.join(root, path.basename(url.pathname));
          return fs.existsSync(file) ? route.fulfill({path: file}) : route.abort();
        }
        if (request.method() !== 'GET') writes.push([url.pathname, request.postDataJSON(), request.headers()]);
        const prefix = '/api/d0-control';
        if (url.pathname === `${prefix}/status`) return route.fulfill({json: {...json[url.pathname], live_orders_enabled: live, market_state: marketState}});
        if (url.pathname === `${prefix}/broker/connect`) connected = true;
        if ([`${prefix}/broker`, `${prefix}/broker/connect`].includes(url.pathname)) return route.fulfill({json: {connected, account_tail: '1234'}});
        if (url.pathname === `${prefix}/broker/draft`) return route.fulfill({json: {symbol: 'sz159915', side: 'buy', quantity: 100, price: '1.001', notional: '100.10', order_token: 'fixture', expires_in: 30}});
        if (url.pathname === `${prefix}/broker/submit`) return route.fulfill({json: {state: 'submitted', broker_receipt: '999'}});
        return route.fulfill({json: json[url.pathname] || {}});
      });
      const noOverflow = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);
      await page.goto(origin);
      await page.locator('#market-stats .metric').first().waitFor();
      assert.equal(await page.locator('#market-stats .metric').count(), 4);
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), 'light');
      assert.equal(await page.locator('.dashboard-grid').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length), width >= 1100 ? 2 : 1);
      assert.equal(await noOverflow(), true, `market overflow at ${width}`);
      await page.locator('.dashboard-hero [data-goto="realtime-paper"]').click();
      await page.locator('#page-realtime-paper').waitFor();

      await page.goto(origin + '/d0-control');
      await page.locator('#inputs:enabled').waitFor();
      await page.locator('[name=cash]').fill('870000');
      await page.locator('[name=available_cash]').fill('870000');
      await page.locator('[name=commission_rate]').fill('0.0003');
      await page.locator('[name=min_fee]').fill('5');
      for (const field of await page.locator('#positions input').all()) await field.fill('0');
      await page.locator('#verified').check();
      await page.locator('#balances button[type=submit]').click();
      await page.locator('#allocation').waitFor();
      assert.equal(await page.locator('#allocation progress').count(), 5);
      assert.match(await page.locator('#allocation-bars').innerText(), /50%.*435,000/);
      assert.equal(await page.locator('#orders tr').count(), 1);
      assert.equal(await noOverflow(), true, `control overflow at ${width}`);
      assert.equal(writes.length, 1);
      assert.equal(writes[0][0], '/api/d0-control/preview');
      assert.equal(writes[0][1].cash, '870000');
      assert.equal(writes[0][2]['x-csrf-token'], 'synthetic');
      await page.locator('[name=cash]').fill('900000');
      assert.equal(await page.locator('#allocation').isVisible(), false);

      assert.equal(await page.locator('#broker').isVisible(), false);
      live = true;
      marketState = 'closed';
      await page.goto(origin + '/d0-control');
      await page.locator('#broker-connect').waitFor();
      assert.match(await page.locator('#signal').innerText(), /非连续交易时段/);
      await page.locator('#broker-account').fill('000001234');
      await page.locator('#broker-password').fill('synthetic-password');
      await page.locator('#broker-connect button').click();
      await page.locator('#broker-session').waitFor();
      assert.equal(await page.locator('#broker-password').inputValue(), '');
      assert.equal(await page.locator('#broker-order button').isDisabled(), true);
      marketState = 'open';
      await page.locator('#refresh-signal').click();
      await page.locator('#broker-order button:enabled').waitFor();
      await page.locator('#broker-price').fill('1.001');
      await page.locator('#broker-quantity').fill('100');
      await page.locator('#broker-order button').click();
      await page.locator('#broker-confirm').waitFor();
      assert.equal(writes.filter(([path]) => path.endsWith('/submit')).length, 0);
      await page.locator('#broker-phrase').fill('确认实盘');
      await page.locator('#broker-confirm button').click();
      await page.getByText(/收到委托编号 999/).waitFor();
      assert.equal(writes.filter(([path]) => path.endsWith('/submit')).length, 1);
      assert.equal(await noOverflow(), true, `broker overflow at ${width}`);
      await page.close();
      console.log(`Dashboard and D0 preview passed at ${width}px`);
    }
  } finally {
    await browser.close();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
