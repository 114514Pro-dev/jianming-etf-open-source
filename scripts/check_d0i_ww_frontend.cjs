#!/usr/bin/env node
'use strict';

// Disposable browser context with an in-memory transport only. Every network
// request is blocked. No profile, service, quote feed or real account is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'production/web_static');
const output = path.resolve(process.env.ETF_UI_OUTPUT || path.join(root, '../outputs/d0i-ww-ui-20261102'));
const source = fs.readFileSync(path.join(assets, 'realtime-paper.js'), 'utf8');
const marker = 'window.RealtimePaper={init,setActive,refresh,reset};';
assert.equal(source.split(marker).length, 2);
const testSource = source.replace(marker,
  'window.__wwUi={state,accept,switchStrategy,fields,renderWeeklyBondGate};' + marker);
const comparison = fs.readFileSync(path.join(assets, 'realtime-paper-comparison.js'), 'utf8');
const compareContext = vm.createContext({window:{addEventListener(){}},document:{addEventListener(){}}});
vm.runInContext(comparison.replace('window.RealtimePaperComparison =',
  'window.__wwCompare={identity,readComparison};window.RealtimePaperComparison ='), compareContext);
const {identity,readComparison} = compareContext.window.__wwCompare;
let runningBrowser;
const account = {id:'D0I-BOND-WW-forward-paper',strategy:'D0I-BOND-WW',created_at:'2026-11-02T01:00:00+08:00',initial_cash:'100000'};
assert.notEqual(identity(account), identity({...account,strategy:'D0'}));
const raw = {contract_version:'d0-performance-comparison-v1',status:'waiting',reason:'account_not_started',
  account_id:account.id,account_created_at:account.created_at,strategy:account.strategy,model_strategy:account.strategy,
  generated_at:'2026-11-02T02:00:00+08:00',requested_start_at:null,normalization:'first_shared_confirmed_close',segments:[],notes:[],
  series:['account','market','chinext','d0'].map(id=>({id,status:'unavailable',reason:'account_not_started',as_of:null,points:[],
    method:id==='d0'?'native_d0i_bond_ww_next_open':'fixture'}))};
assert.notEqual(readComparison(raw,account).status,'invalid');
assert.equal(readComparison({...raw,strategy:'D0'},account).status,'invalid');
assert.equal(readComparison({...raw,series:raw.series.map(s=>s.id==='d0'?{...s,method:'native_open_replay'}:s)},account).status,'invalid');

async function checkWechatPanel(page) {
  const panel = page.locator('details[data-detail-key="rtp-wechat"]');
  const enabled = panel.locator('#rtp-wechat-enabled');
  const orders = panel.locator('#rtp-wechat-orders');
  const lastDelivery = panel.locator('#rtp-wechat-delivery');
  const test = panel.locator('#rtp-wechat-test');
  const refresh = panel.locator('#rtp-wechat-refresh');
  const openPanel = async () => {
    await panel.evaluate(element => { element.open = true; });
    await page.waitForFunction(() => document.querySelector('#rtp-wechat-test:enabled'));
  };
  const selectStrategy = async strategy => {
    await page.locator(`[data-paper-strategy="${strategy}"]`).click();
    await page.waitForFunction(s => window.__wwUi.state.ready && window.__wwUi.state.strategy === s, strategy);
    await openPanel();
  };

  // Both synthetic accounts already exist. The WW account can send an explicit test
  // while automatic signal and order notifications are still off.
  await openPanel();
  assert.equal(await enabled.isChecked(), false);
  assert.equal(await orders.isChecked(), false);
  await test.click();
  await page.waitForFunction(() => window.__fixture.wechat.writes.length === 1);
  const first = await page.evaluate(() => window.__fixture.wechat.writes[0]);
  const ww = await page.evaluate(() => window.__fixture.store['D0I-BOND-WW'].accounts[0]);
  assert.deepEqual(first, {kind:'test', strategy:ww.strategy, body:{account_id:ww.id, account_created_at:ww.created_at}});
  await page.waitForFunction(() => !document.querySelector('#rtp-wechat-enabled').disabled);
  assert.match(await lastDelivery.innerText(), /受理/);
  assert.equal(await enabled.isChecked(), false);
  await enabled.check();
  await page.waitForFunction(() => !document.querySelector('#rtp-wechat-orders').disabled);
  assert.equal(await orders.isChecked(), false);
  await orders.check();
  await page.waitForFunction(() => window.__fixture.wechat.preferences['D0I-BOND-WW'].orders_enabled && !document.querySelector('#rtp-wechat-refresh').disabled);
  const saved = await page.evaluate(() => window.__fixture.wechat.writes.filter(item => item.kind === 'save'));
  assert.deepEqual(saved, [false,true].map(orders_enabled => ({
    kind:'save', strategy:ww.strategy, body:{account_id:ww.id, account_created_at:ww.created_at, enabled:true, orders_enabled},
  })));
  await panel.screenshot({path:path.join(output,'ww-wechat-mobile.png')});

  // Return the WW settings after D0 is already visible. The late response must not
  // show WW's enabled toggles or test receipt in D0.
  await page.evaluate(() => { window.__fixture.wechat.holdNext = 'D0I-BOND-WW'; });
  await refresh.click();
  await page.waitForFunction(() => typeof window.__fixture.wechat.release === 'function');
  await selectStrategy('D0');
  await page.evaluate(async () => {
    window.__fixture.wechat.release();
    await new Promise(requestAnimationFrame);
  });
  assert.equal(await enabled.isChecked(), false);
  assert.equal(await orders.isChecked(), false);
  assert.equal(await lastDelivery.isVisible(), false);
  assert.equal(await page.evaluate(() => window.__fixture.wechat.writes.length), 3);
  await enabled.check();
  await page.waitForFunction(() => window.__fixture.wechat.preferences.D0.enabled && !document.querySelector('#rtp-wechat-orders').disabled);
  assert.equal(await orders.isChecked(), false);
  const d0 = await page.evaluate(() => window.__fixture.store.D0.accounts[0]);
  assert.deepEqual(await page.evaluate(() => window.__fixture.wechat.writes.at(-1)), {
    kind:'save', strategy:'D0', body:{account_id:d0.id, account_created_at:d0.created_at, enabled:true, orders_enabled:false},
  });
  await selectStrategy('D0I-BOND-WW');
  assert.equal(await enabled.isChecked(), true);
  assert.equal(await orders.isChecked(), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2), false);

  // Removing the server credential must still allow an existing subscriber to turn off.
  await page.evaluate(() => {
    const wechat = window.__fixture.wechat;
    wechat.configured = false;
    Object.assign(wechat.preferences['D0I-BOND-WW'].last_delivery, {status:'failed', reason:'verification_required'});
  });
  await refresh.click();
  await page.waitForFunction(() => document.querySelector('#rtp-wechat-test:disabled') && document.querySelector('#rtp-wechat-enabled:enabled'));
  assert.match(await lastDelivery.innerText(), /实名认证/);
  assert.equal(await orders.isDisabled(), true);
  await enabled.uncheck();
  await page.waitForFunction(() => !window.__fixture.wechat.preferences['D0I-BOND-WW'].enabled && document.querySelector('#rtp-wechat-enabled:disabled'));
  assert.equal(await orders.isChecked(), false);
  assert.equal(await page.evaluate(() => window.__fixture.wechat.writes.filter(item => item.kind === 'test').length), 1);
}

(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const options={headless:true};
  if(process.env.ETF_TEST_BROWSER)options.executablePath=process.env.ETF_TEST_BROWSER;
  const browser=await chromium.launch(options);
  runningBrowser=browser;
  const context=await browser.newContext({viewport:{width:1280,height:1100},locale:'zh-CN'});
  const blocked=[];await context.route('**/*',route=>{blocked.push(route.request().url());return route.abort();});
  const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.setContent('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><body><main style="max-width:1120px;margin:auto;padding:24px"><section id="page-realtime-paper"></section></main></body></html>');
  for(const name of ['style.css','realtime-paper.css','realtime-paper-comparison.css'])await page.addStyleTag({content:fs.readFileSync(path.join(assets,name),'utf8')});
  await page.addScriptTag({content:fs.readFileSync(path.join(assets,'locale-en.js'),'utf8')});
  await page.addScriptTag({content:comparison});
  await page.addScriptTag({content:fs.readFileSync(path.join(assets,'realtime-paper-wechat.js'),'utf8')});
  await page.addScriptTag({content:testSource});
  await page.evaluate(()=>{
    const copy=value=>JSON.parse(JSON.stringify(value)),now=new Date().toISOString();
    const makeAccount=(strategy,name='Synthetic account')=>({id:strategy==='D0'?'D0-forward-paper':'D0I-BOND-WW-forward-paper',strategy,name,created_at:now,initial_cash:'100000.00',cash:'100000.00',available_cash:'100000.00',equity:'100000.00',holdings_value:'0.00',frozen_cash:'0.00',status:'stopped',execution_state:'stopped',can_start:true,can_pause:false,can_edit_capital:true,valuation_status:'fresh',holdings:[],orders:[],fills:[],events:[]});
    const store={D0:{revision:1,accounts:[makeAccount('D0','Synthetic original retained')]},'D0I-BOND-WW':{revision:0,accounts:[]}};
    const response=strategy=>({contract_version:'realtime-paper-v1',strategy,revision:String(store[strategy].revision),generated_at:new Date().toISOString(),service:{status:'ready',observer_status:'running'},accounts:copy(store[strategy].accounts),quotes:[],market_quotes:[],rules:[],model:{}});
    const wechat = {
      preferences:Object.fromEntries(Object.keys(store).map(strategy => [strategy, {enabled:false, orders_enabled:false, last_delivery:null}])),
      writes:[], holdNext:null, release:null, configured:true,
    };
    const wechatResponse = strategy => {
      const current = store[strategy].accounts[0];
      return {contract_version:'paper-wechat-v1', configured:wechat.configured, strategy, account_id:current?.id || null,
        account_created_at:current?.created_at || null, ...copy(wechat.preferences[strategy])};
    };
    window.__fixture={store,response,calls:[],hold:false,resolve:null,wechat};
    window.RealtimePaper.init({root:'page-realtime-paper',transport:{
      load:strategy=>{window.__fixture.calls.push({kind:'load',strategy});return window.__fixture.hold&&strategy==='D0I-BOND-WW'?new Promise(resolve=>window.__fixture.resolve=resolve):Promise.resolve(response(strategy));},
      create:(body,strategy)=>{window.__fixture.calls.push({kind:'create',body,strategy});store[strategy].accounts=[makeAccount(strategy,body.name)];store[strategy].revision++;return Promise.resolve(response(strategy));},
      start:(id,strategy)=>{window.__fixture.calls.push({kind:'start',id,strategy});store[strategy].accounts[0].status='running';store[strategy].accounts[0].execution_state='waiting';store[strategy].revision++;return Promise.resolve(response(strategy));},
      comparison:()=>Promise.reject(new Error('Synthetic comparison has no recorded closes yet')),
      loadWechat:async strategy => {
        const result = wechatResponse(strategy);
        if (wechat.holdNext === strategy) {
          wechat.holdNext = null;
          await new Promise(resolve => { wechat.release = resolve; });
        }
        return result;
      },
      saveWechat:async (body,strategy) => {
        wechat.writes.push({kind:'save', body:copy(body), strategy});
        Object.assign(wechat.preferences[strategy], {enabled:body.enabled, orders_enabled:body.orders_enabled});
        return wechatResponse(strategy);
      },
      testWechat:async (body,strategy) => {
        wechat.writes.push({kind:'test', body:copy(body), strategy});
        wechat.preferences[strategy].last_delivery = {kind:'test', status:'accepted', reason:null, created_at:now, updated_at:now};
        return wechatResponse(strategy);
      },
    }});window.RealtimePaper.setActive(true);
  });
  await page.waitForFunction(()=>window.__wwUi.state.ready);
  assert.equal(await page.evaluate(()=>window.__wwUi.state.id),'D0-forward-paper');
  await page.locator('[data-paper-strategy="D0I-BOND-WW"]').click();
  await page.waitForFunction(()=>window.__wwUi.state.ready&&window.__wwUi.state.strategy==='D0I-BOND-WW');
  assert.equal(await page.locator('.section-heading h2').innerText(),'D0I-BOND-WW · 周线择债');
  assert.equal(await page.evaluate(()=>window.__wwUi.state.id),'');
  assert.equal(await page.evaluate(()=>window.__fixture.calls.filter(c=>c.kind==='create'||c.kind==='start').length),0);
  assert.equal(await page.locator('#rtp-email-draft').isVisible(),false);
  await page.screenshot({path:path.join(output,'ww-before-create.png'),fullPage:true});
  await page.locator('details[data-detail-key="rtp-settings"]').evaluate(e=>e.open=true);
  await page.locator('#rtp-name').fill('Synthetic WW draft');
  assert.equal(await page.locator('[data-paper-strategy="D0"]').isDisabled(),true);
  await page.getByRole('button',{name:'放弃未保存草稿',exact:true}).click();
  assert.equal(await page.locator('[data-paper-strategy="D0"]').isDisabled(),false);
  await page.evaluate(()=>{window.__fixture.hold=true;window.RealtimePaper.refresh();});
  await page.waitForFunction(()=>typeof window.__fixture.resolve==='function');
  await page.locator('[data-paper-strategy="D0"]').click();
  await page.waitForFunction(()=>window.__wwUi.state.ready&&window.__wwUi.state.strategy==='D0');
  await page.evaluate(()=>{const data=window.__fixture.response('D0I-BOND-WW');data.revision='999';window.__fixture.hold=false;window.__fixture.resolve(data);});
  await page.waitForTimeout(30);
  assert.equal(await page.evaluate(()=>window.__wwUi.state.id),'D0-forward-paper');
  assert.equal(await page.evaluate(()=>window.__wwUi.state.revision),'1');
  await page.locator('[data-paper-strategy="D0I-BOND-WW"]').click();
  await page.waitForFunction(()=>window.__wwUi.state.ready&&window.__wwUi.state.strategy==='D0I-BOND-WW');
  await page.locator('details[data-detail-key="rtp-settings"]').evaluate(e=>e.open=true);
  await page.locator('#rtp-confirm-start').check();
  await page.locator('#rtp-save').click();
  await page.waitForFunction(()=>window.__wwUi.state.ready&&window.__wwUi.state.id==='D0I-BOND-WW-forward-paper'&&!window.__wwUi.state.busy);
  assert.equal(await page.evaluate(()=>window.__fixture.store['D0I-BOND-WW'].accounts[0].status),'stopped');
  assert.equal(await page.evaluate(()=>window.__fixture.store.D0.accounts[0].name),'Synthetic original retained');
  assert.deepEqual(await page.evaluate(()=>window.__fixture.calls.filter(c=>c.kind==='create'||c.kind==='start').map(c=>[c.kind,c.strategy])),[['create','D0I-BOND-WW']]);
  await page.evaluate(()=>{
    const a=window.__fixture.store['D0I-BOND-WW'].accounts[0];
    const day='2026-10-30';a.signal={id:'synthetic-ww-signal',valid:true,confirmed_day:day,execution_day:'2026-11-02',weights:{sz159915:0,sh512800:0,sh518880:0,sh511010:1},rationale:{contract_version:'d0-holding-logic-v1',strategy:'D0I-BOND-WW',assets:['sz159915','sh512800','sh518880','sh511010'].map(symbol=>({symbol,eligible:symbol==='sh511010',score_ready:true,original_gate:symbol==='sh511010'?{contract_version:'d0-original-gate-v1',source:'saved_signal',kind:'bond_weekly',timing:{status:'confirmed',confirmed_day:day,period_end:day,available_on:day,state_day:day},metrics:{value:145.5,ma:143.5,ma_window:60,momentum20:.02,ma_unit:'weeks',momentum_unit:'weeks'},state:{ready:true,long:true}}:null}))}};
    window.__fixture.store['D0I-BOND-WW'].revision++;window.RealtimePaper.refresh();
  });
  await page.waitForFunction(()=>window.__wwUi.state.ready&&window.__wwUi.state.revision==='2');
  const bond=page.locator('#rtp-decision-panel[data-symbol="sh511010"]');
  assert.equal(await bond.locator('.rtp-weekly-bond-gate[data-evidence-status="confirmed"]').count(),1);
  assert.equal(await bond.locator('.rtp-decision-scoring-title').count(),0);
  assert.ok((await bond.innerText()).includes('60周均线'));
  assert.ok(!(await bond.innerText()).includes('20日动量'));
  await page.screenshot({path:path.join(output,'ww-weekly-evidence.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(output,'ww-mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2);
  assert.equal(overflow,false,'Mobile view must not overflow horizontally');
  await page.evaluate(()=>{const target=window.__wwUi.fields.holdingLogic;const a=window.__fixture.store['D0I-BOND-WW'].accounts[0];const asset=a.signal.rationale.assets.find(z=>z.symbol==='sh511010');asset.original_gate.timing.available_on='2026-11-06';window.__wwUi.renderWeeklyBondGate(target,asset,a.signal);});
  assert.equal(await page.locator('.rtp-weekly-bond-gate[data-evidence-status="unknown"]').count(),1);
  assert.equal(await page.evaluate(()=>{try{window.__wwUi.accept({...window.__fixture.response('D0I-BOND-WW'),strategy:'D0'});return false;}catch(_){return true;}}),true);
  await checkWechatPanel(page);
  assert.deepEqual(errors,[]);
  assert.deepEqual(blocked,[]);
  const result={passed:true,synthetic_only:true,network_requests:blocked.length,page_errors:errors,checks:['separate strategy and account views','no automatic creation or activation','draft prevents switching','old asynchronous strategy response rejected','new account starts stopped','original account retained','WW weekly evidence without daily score labels','future weekly evidence rejected','wrong-strategy snapshot rejected','WW model identity/method verified','mobile layout has no horizontal overflow'],screenshots:['ww-before-create.png','ww-weekly-evidence.png','ww-mobile.png']};
  result.checks.push('explicit test while unsubscribed', 'signals and opt-in orders save separately', 'late WeChat settings ignored after switching', 'D0 and WW subscriptions stay isolated', 'missing channel blocks sends but allows unsubscribing');
  result.screenshots.push('ww-wechat-mobile.png');
  fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  await browser.close();
})().catch(async error=>{console.error(error);if(runningBrowser)await runningBrowser.close();process.exitCode=1;});
