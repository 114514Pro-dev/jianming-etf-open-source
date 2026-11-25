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
const summary = {id: 'sample', name: 'Synthetic D0 account', day: '2026-11-25', equity: 870000, cash: 870000, return: .12};
const json = {
  '/api/session': {authenticated: true, csrf: 'synthetic'},
  '/api/catalog': {groups: [{id: 'original', name: 'Synthetic', strategies: [{code: 'D0', name: 'D0'}]}]},
  '/api/overview': {market: {daily_end: '2026-11-23'}, quotes: [{symbol: 'sz159915', price: 1, quote_at: '2026-11-24T09:30:04+08:00'}]},
  '/api/accounts': [summary],
  '/api/account': {summary, events: [], positions: [], decision: {state: 'cash', title: '保持现金', note: 'Synthetic portfolio'}},
  '/api/settings': {auto_refresh: false},
  '/api/jobs': {jobs: []},
  '/api/d0-control/status': {mode: 'preview_only', broker_state: 'disabled', live_orders_enabled: false, market_state: 'open', source_status: 'ready', historical_seed: false},
  '/api/d0-control/preview': {mode: 'preview_only', stage: 'buy', equity: '870000.00', allocation, sell_remainder: [],
    orders: [{symbol: 'sz159915', side: 'buy', quantity: 435000, limit_price: '1.002'}]},
};

function luminance(color) {
  const rgb = color.match(/\d+(?:\.\d+)?/g).slice(0, 3).map(value => Number(value) / 255);
  return rgb.map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4)
    .reduce((sum, x, i) => sum + x * [.2126, .7152, .0722][i], 0);
}
function assertColors(foreground, background, name) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  assert.ok((values[0] + .05) / (values[1] + .05) >= 4.5, `${name}: ${foreground} on ${background}`);
}
async function checkContrast(page, text, surface = text) {
  const foreground = await page.locator(text).first().evaluate(el => getComputedStyle(el).color);
  const background = await page.locator(surface).first().evaluate(el => getComputedStyle(el).backgroundColor);
  assertColors(foreground, background, text);
}

async function run() {
  const executablePath = process.env.ETF_TEST_BROWSER || undefined;
  const browser = await chromium.launch({executablePath});
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({viewport: {width, height: 850}});
      const writes = [];
      let live = false;
      let connected = false;
      let accountBound = false;
      let syncState = 'not_linked';
      let brokerNetwork = false;
      let limits = {single_cny: '800000', daily_cny: '5000000', maximum_cny: '5000000'};
      let brokerState = 'disabled';
      let marketState = 'open';
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== origin) return route.abort();
        if (url.pathname === '/' || url.pathname === '/d0-control') {
          const pageFile = url.pathname === '/' ? 'index.html' : 'd0-control.html';
          const body = fs.readFileSync(path.join(root, pageFile), 'utf8')
            .replace('__D0_CONTROL_LINK__', '<a class="button secondary" href="/d0-control#broker">东方财富证券</a>')
            .replace('__BROKER_NAV__', '<a class="nav-item" href="/d0-control#broker"><span>↗</span><span>东方财富证券</span></a>');
          return route.fulfill({body, contentType: 'text/html; charset=utf-8'});
        }
        if (url.pathname.startsWith('/static/')) {
          const file = path.join(root, path.basename(url.pathname));
          return fs.existsSync(file) ? route.fulfill({path: file}) : route.abort();
        }
        if (request.method() !== 'GET') writes.push([url.pathname, request.postDataJSON(), request.headers()]);
        const prefix = '/api/d0-control';
        if (url.pathname === `${prefix}/sync/download`) return route.fulfill({body: 'synthetic',
          contentType: 'application/zip', headers: {'Content-Disposition': 'attachment; filename="Jianming-ETF-Sync-Windows-v3.zip"'}});
        if (url.pathname === `${prefix}/sync/status`) return route.fulfill({json: {state: syncState, broker_network_authorized: brokerNetwork}});
        if (url.pathname === `${prefix}/sync/pair`) {
          syncState = 'waiting';
          return route.fulfill({json: {code: 'A'.repeat(32), expires_in: 300}});
        }
        if (url.pathname === `${prefix}/status`) return route.fulfill({json: {...json[url.pathname], live_orders_enabled: live && accountBound, broker_orders_configured: live, account_bound: accountBound, broker_state: brokerState, market_state: marketState}});
        if (url.pathname === `${prefix}/broker/enroll`) accountBound = connected = true;
        if (url.pathname === `${prefix}/broker/connect`) connected = true;
        if ([`${prefix}/broker`, `${prefix}/broker/connect`, `${prefix}/broker/enroll`].includes(url.pathname))
          return route.fulfill({json: {connected, account_bound: accountBound, can_unbind: connected, account_tail: '1234', limits}});
        if (url.pathname === `${prefix}/broker/unbind`) {
          if (request.postDataJSON().confirmation !== '确认解绑') return route.fulfill({status: 409, json: {detail: '请输入「确认解绑」。'}});
          accountBound = connected = false;
          return route.fulfill({json: {connected, account_bound: accountBound, rebind_code: 'N'.repeat(43)}});
        }
        if (url.pathname === `${prefix}/broker/limits`) {
          limits = {...limits, ...request.postDataJSON()};
          return route.fulfill({json: limits});
        }
        if (url.pathname === `${prefix}/broker/draft`) return route.fulfill({json: {symbol: 'sz159915', side: 'buy', quantity: 100, price: '1.001', notional: '100.10', order_token: 'fixture', expires_in: 30}});
        if (url.pathname === `${prefix}/broker/submit`) return route.fulfill({json: {state: 'submitted', broker_receipt: '999'}});
        return route.fulfill({json: json[url.pathname] || {}});
      });
      const noOverflow = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);
      await page.goto(origin);
      await page.locator('#market-stats .metric').first().waitFor();
      assert.equal(await page.locator('#market-stats .metric').count(), 4);
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), 'light');
      for (const mode of ['light', 'dark']) {
        await page.waitForFunction(theme => getComputedStyle(document.documentElement).colorScheme === theme, mode);
        const quoteRow = page.locator('.dashboard-market tbody tr').first();
        await quoteRow.hover();
        await checkContrast(page, '.dashboard-market .asset-name', '.dashboard-market tbody tr');
        await checkContrast(page, '.dashboard-market th');
        await checkContrast(page, '.automation-switch strong', '.automation-panel');
        if (width > 720) await checkContrast(page, '.sidebar .nav-item:not(.active)', '.sidebar');
        if (mode === 'light') await page.locator('.topbar [data-theme-toggle]').click();
      }
      assert.equal(await page.locator('.topbar [data-theme-toggle]').getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('.dashboard-grid').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length), width >= 1100 ? 2 : 1);
      assert.equal(await noOverflow(), true, `market overflow at ${width}`);
      const nav = width > 720 ? '.sidebar' : '.mobile-navigation';
      await page.locator(`${nav} [data-page="accounts"]`).click();
      await page.locator('.account-card.active').waitFor();
      await page.locator('.daily-activity').waitFor();
      for (const mode of ['dark', 'light']) {
        await page.waitForFunction(theme => getComputedStyle(document.documentElement).colorScheme === theme, mode);
        await checkContrast(page, '.account-card.active .account-strategy', '.account-card.active');
        await checkContrast(page, '.account-auto-state', '.account-card.active');
        await checkContrast(page, '.account-actions label', '.account-actions');
        await checkContrast(page, '.daily-summary', '.daily-activity');
        await page.locator('.topbar [data-theme-toggle]').click();
      }
      await page.waitForFunction(() => getComputedStyle(document.documentElement).colorScheme === 'dark');
      await page.locator(`${nav} .nav-item[data-page="overview"]`).click();
      await page.locator('.dashboard-hero [data-goto="realtime-paper"]').click();
      await page.locator('#page-realtime-paper').waitFor();

      if (width <= 720) {
        await page.locator('#mobile-more').click();
        await page.locator('#more-links a[href="/d0-control#broker"]').click();
      } else await page.locator('.sidebar a[href="/d0-control#broker"]').click();
      await page.locator('#inputs:enabled').waitFor();
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), 'dark');
      await checkContrast(page, '#broker-unavailable');
      await checkContrast(page, '[name=cash]');
      await page.locator('[data-theme-toggle]').click();
      await page.waitForFunction(() => getComputedStyle(document.documentElement).colorScheme === 'light');
      await checkContrast(page, '#broker-unavailable');
      await checkContrast(page, '[name=cash]');
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

      assert.equal(await page.locator('#broker').isVisible(), true);
      assert.match(await page.locator('#broker-unavailable').innerText(), /网页实盘尚未开启/);
      assert.equal(await page.locator('#broker-connect').isVisible(), false);
      const downloadPath = '/api/d0-control/sync/download?v=3';
      assert.equal(await page.getByRole('link', {name: '下载同步工具'}).getAttribute('href'), downloadPath);
      await page.evaluate(() => localStorage.setItem('etf-connector-bootstrap-v2-requested', 'yes'));
      await page.reload();
      const download = page.waitForEvent('download');
      await page.getByRole('button', {name: '开始配对'}).click();
      const newBundle = await download;
      assert.equal(newBundle.url(), origin + downloadPath);
      assert.equal(newBundle.suggestedFilename(), 'Jianming-ETF-Sync-Windows-v3.zip');
      await page.locator('#sync-code-box').waitFor();
      assert.equal(await page.evaluate(path => localStorage.getItem(`etf-connector-download:${path}`), downloadPath), 'yes');
      assert.equal(await page.locator('#sync-code').inputValue(), 'A'.repeat(32));
      syncState = 'linked';
      await page.getByRole('button', {name: '刷新连接状态'}).click();
      await page.getByText(/已接收到本机工具的连接/).waitFor();
      assert.equal(await page.locator('#sync-code-box').isVisible(), false);
      syncState = 'verified';
      await page.getByText(/工具报告：东方财富只读核对成功/).waitFor({timeout: 8000});
      brokerState = 'private_origin_required';
      await page.locator('#refresh-signal').click();
      await page.getByText(/当前地址或网络未获券商访问授权/).waitFor();
      assert.equal(await page.locator('#broker-password').isVisible(), false);
      await page.emulateMedia({reducedMotion: 'reduce'});
      assert.equal(await page.locator('#workspace').evaluate(el => getComputedStyle(el).animationName), 'none');
      brokerState = 'connector_pairing_required';
      syncState = 'not_linked';
      marketState = 'closed';
      await page.goto(origin + '/d0-control');
      await page.getByText('等待网络授权', {exact: true}).waitFor();
      assert.equal(await page.locator('#broker-password').isVisible(), false);
      await page.getByRole('button', {name: '开始配对'}).click();
      await page.locator('#sync-code-box').waitFor();
      brokerState = 'available';
      brokerNetwork = true;
      syncState = 'linked';
      await page.getByText(/网页券商网络已临时授权/).waitFor();
      await page.locator('#broker-connect').waitFor();
      assert.match(await page.locator('#signal').innerText(), /非连续交易时段/);
      await page.locator('#broker-enrollment').waitFor();
      await page.locator('#broker-enrollment-code').fill('E'.repeat(43));
      await page.locator('#broker-enrollment-confirm').fill('同意绑定');
      await page.locator('#broker-account').fill('000001234');
      await page.locator('#broker-password').fill('synthetic-password');
      await page.getByRole('button', {name: '授权并绑定唯一资金账号'}).click();
      await page.locator('#broker-session').waitFor();
      assert.equal(await page.locator('#broker-password').inputValue(), '');
      assert.equal(await page.locator('#broker-enrollment-code').inputValue(), '');
      assert.equal(writes.filter(([path]) => path.endsWith('/enroll')).length, 1);
      assert.equal(await page.locator('#broker-order').isVisible(), false);
      await page.locator('#broker-settings summary').click();
      assert.equal(await page.locator('#broker-single').inputValue(), '800000');
      assert.equal(await page.locator('#broker-daily').inputValue(), '5000000');
      await page.locator('#broker-single').fill('10000');
      await page.getByRole('button', {name: '保存委托限额'}).click();
      await page.getByText('限额已保存，今日已提交金额不变。').waitFor();
      assert.equal(writes.find(([path]) => path.endsWith('/limits'))[1].single_cny, '10000');
      live = true;
      await page.locator('#refresh-signal').click();
      await page.locator('#broker-order').waitFor();
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
      await page.getByText('解绑当前账户').click();
      await page.locator('#broker-unbind-confirm').fill('确认解绑');
      await page.getByRole('button', {name: '确认解绑账户'}).click();
      await page.locator('#broker-rebind-box').waitFor();
      assert.equal(await page.locator('#broker-rebind-code').inputValue(), 'N'.repeat(43));
      assert.equal(await page.locator('#broker-order').isVisible(), false);
      assert.deepEqual(writes.find(([path]) => path.endsWith('/unbind'))[1], {confirmation: '确认解绑'});
      assert.equal(await noOverflow(), true, `rebind overflow at ${width}`);
      await page.locator('#broker-enrollment-code').fill('N'.repeat(43));
      await page.locator('#broker-enrollment-confirm').fill('同意绑定');
      await page.locator('#broker-account').fill('000008765');
      await page.locator('#broker-password').fill('synthetic-password');
      await page.getByRole('button', {name: '授权并绑定唯一资金账号'}).click();
      await page.locator('#broker-session').waitFor();
      assert.equal(await page.locator('#broker-rebind-code').inputValue(), '');
      brokerState = 'connector_pairing_required';
      brokerNetwork = false;
      syncState = 'not_linked';
      await page.getByText('等待网络授权', {exact: true}).waitFor();
      assert.equal(await page.locator('#broker-order').isVisible(), false);
      assert.equal(await noOverflow(), true, `broker overflow at ${width}`);
      await page.close();
      console.log(`Dashboard and D0 preview passed at ${width}px`);
    }
  } finally {
    await browser.close();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
