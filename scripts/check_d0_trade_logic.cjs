#!/usr/bin/env node
'use strict';

// Exercise the production explanation function without a browser, market or ledger.
// The export below is injected into VM memory only; production bytes are untouched.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'production/web_static/realtime-paper.js'), 'utf8');
const marker = 'window.RealtimePaper={init,setActive,refresh,reset};';
assert.equal(source.split(marker).length, 2, 'Expected one production public export');
const context = vm.createContext({
  window: { ETF_I18n: { language: 'zh' } },
  document: { addEventListener() {} },
});
vm.runInContext(fs.readFileSync(path.join(root, 'production/web_static/locale-en.js'), 'utf8'), context,
  { filename: 'locale-en.js' });
vm.runInContext(source.replace(marker, 'window.__tradeLogicTest={signalTradeExplanation};' + marker), context,
  { filename: 'realtime-paper.js' });
const explain = context.window.__tradeLogicTest.signalTradeExplanation;

let checks = 0;
const cases = [];
function same(actual, expected, message) { checks++; assert.equal(actual, expected, message); }
function has(text, fragment, message) { checks++; assert.ok(text.includes(fragment), message || fragment); }
function lacks(text, fragment, message) { checks++; assert.ok(!text.includes(fragment), message || fragment); }
function test(name, body) { body(); cases.push(name); }
function fixture(options = {}) {
  const actual = options.actual ?? 0;
  const target = options.target ?? 100;
  return {
    summary: { signal_status: 'confirmed', reference_status: 'current', plan_status: 'current',
      reason_code: 'ready', ...options.summary },
    row: { symbol: 'sh511010', action: options.action || 'buy',
      target_weight: options.weight ?? '0.5', actual_quantity: actual, target_quantity: target,
      difference_quantity: target - actual, progress: options.progress || 'awaiting_submission',
      trigger: { eligible: options.eligible === undefined ? true : options.eligible,
        score_ready: true, note: options.note ?? '保存的筛选依据' }, ...options.row },
  };
}
function output(input, current = true, reason = null) {
  const result = explain(input.summary, input.row, current, reason);
  return { result, text: [String(result.heading), ...result.lines.map(String)].join('\n') };
}
function freeze(value) {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

test('zero actual holdings plan a purchase, not a completed fill', () => {
  const { result, text } = output(fixture());
  same(result.kind, 'buy_open'); has(text, '实际尚未持有'); has(text, '100');
  has(text, '计划买入'); lacks(text, '已经买入'); has(text, '50%');
});
test('existing holdings explain only the remaining addition', () => {
  const { result, text } = output(fixture({ actual: 300, target: 500 }));
  same(result.kind, 'buy_add'); has(text, '已有 300 份'); has(text, '目标为 500 份');
  has(text, '补足 200 份'); lacks(text, '评分上升');
});
test('ineligible zero target explains liquidation using saved evidence', () => {
  const { result, text } = output(fixture({ actual: 400, target: 0, action: 'sell', weight: '0', eligible: false }));
  same(result.kind, 'sell_exit'); has(text, '目标为0份'); has(text, '400');
  has(text, '配置资格未通过'); lacks(text, '死叉'); same(result.note, '保存的筛选依据');
});
test('eligible reduction retains the planned holding', () => {
  const { result, text } = output(fixture({ actual: 500, target: 300, action: 'sell' }));
  same(result.kind, 'sell_reduce'); has(text, '保留 300 份'); has(text, '超出 200 份');
  has(text, '仍通过配置资格'); lacks(text, '评分下降'); lacks(text, '清空');
});
test('equal actual and target holdings explain continuing to hold', () => {
  const { result, text } = output(fixture({ actual: 500, target: 500, action: 'hold', progress: 'target_reached' }));
  same(result.kind, 'hold'); has(text, '均为 500 份'); has(text, '没有剩余买卖差额');
  lacks(text, '未来上涨'); lacks(text, '尚未提交');
});
test('ineligible zero targets explain no holding without inventing a crossover', () => {
  const { result, text } = output(fixture({ target: 0, action: 'cash', weight: '0', eligible: false, progress: 'target_reached' }));
  same(result.kind, 'cash_ineligible'); has(text, '配置资格未通过'); has(text, '保持空仓');
  lacks(text, '死叉'); lacks(text, '卖出');
});
test('positive model weight with zero planned shares does not invent a funding cause', () => {
  const { result, text } = output(fixture({ target: 0, action: 'cash', progress: 'target_reached' }));
  same(result.kind, 'cash_no_shares'); has(text, '50%'); has(text, '计划目标与实际份额均为0');
  has(text, '保存的计划记录核对'); lacks(text, '因为资金不足'); lacks(text, '不足一手所以');
});
test('unknown eligibility and zero targets remain a saved plan explanation', () => {
  const { result, text } = output(fixture({ target: 0, action: 'cash', weight: '0', eligible: null, progress: 'target_reached' }));
  same(result.kind, 'cash_target_zero'); has(text, '详细依据未记录'); lacks(text, '配置资格未通过');
});
test('missing plans cannot turn a positive model weight into a buy claim', () => {
  const input = fixture({ action: 'wait', row: { target_quantity: null, difference_quantity: null },
    summary: { plan_status: 'missing', reason_code: 'no_plan' } });
  const { result, text } = output(input, true, '目标已确认，等待建立执行计划。');
  same(result.kind, 'no_plan'); has(text, '缺少与信号匹配的执行计划');
  has(text, '等待建立执行计划'); lacks(text, '因此计划买入');
});
test('historical plans cannot establish current buying or selling', () => {
  const input = fixture({ action: 'wait', summary: { plan_status: 'historical', reason_code: 'old_plan' } });
  const { result, text } = output(input, true, '已保存计划不属于当前信号或运行轮次。');
  same(result.kind, 'no_plan'); has(text, '不属于当前信号'); lacks(text, '因此计划买入');
});
test('stale reads suppress current causes and do not echo execution-ready text', () => {
  const { result, text } = output(fixture(), false, '条件已就绪，可以执行');
  same(result.kind, 'stale'); same(result.note, null); has(text, '当前账户状态尚未核对');
  lacks(text, '条件已就绪'); lacks(text, '因此计划买入'); lacks(text, '配置资格已通过');
});
test('invalid signals and associations produce no current trading explanation', () => {
  for (const options of [{ summary: { signal_status: 'invalid' } },
    { summary: { reference_status: 'invalid' } }, { progress: 'needs_review' }]) {
    const { result, text } = output(fixture(options));
    same(result.kind, 'needs_review'); has(text, '需要核对'); lacks(text, '因此计划买入');
  }
});
test('qualification and positive-weight contradictions are explicitly unresolved', () => {
  const { result, text } = output(fixture({ eligible: false }));
  same(result.kind, 'needs_review'); has(text, '记录存在不一致'); lacks(text, '因此计划买入');
});
test('explicitly unready scores cannot coexist with passed eligibility', () => {
  const input = fixture(); input.row.trigger.score_ready = false;
  const { result, text } = output(input);
  same(result.kind, 'needs_review'); same(result.note, null);
  has(text, '记录存在不一致'); lacks(text, '因此计划买入');
});
test('unknown score readiness is not treated as an explicit scoring failure', () => {
  for (const readiness of [null, undefined]) {
    const input = fixture(); input.row.trigger.score_ready = readiness;
    const { result, text } = output(input);
    same(result.kind, 'buy_open'); has(text, '因此计划买入'); lacks(text, '记录存在不一致');
  }
});
test('zero weight cannot explain a positive planned buy as qualified allocation', () => {
  const { result, text } = output(fixture({ weight: '0' }));
  same(result.kind, 'needs_review'); lacks(text, '配置资格已通过'); lacks(text, '因此计划买入');
});
test('a stated action must agree with the frozen target and actual quantities', () => {
  for (const input of [fixture({ actual: 0, target: 100, action: 'hold' }),
    fixture({ actual: 100, target: 0, action: 'buy' }),
    fixture({ actual: 100, target: 200, action: 'sell' })]) {
    const { result, text } = output(input);
    same(result.kind, 'needs_review'); same(result.note, null);
    lacks(text, '因此计划买入'); lacks(text, '因此计划减持');
  }
});
test('zero model weight with positive retained shares is also inconsistent', () => {
  const { result, text } = output(fixture({ actual: 100, target: 100, action: 'hold', weight: '0' }));
  same(result.kind, 'needs_review'); same(result.note, null); lacks(text, '因此按计划持有');
});
test('paused accounts retain plan intent but clearly stop execution', () => {
  const { result, text } = output(fixture({ summary: { reason_code: 'account_stopped', execution_status: 'stopped' } }),
    true, '账户已暂停或停止，保留已保存的信号与计划。');
  same(result.kind, 'buy_open'); has(text, '计划买入'); has(text, '账户已暂停或停止'); lacks(text, '已经买入');
});
test('unready market data explains waiting without rewriting the frozen allocation cause', () => {
  const { result, text } = output(fixture({ summary: { reason_code: 'source_not_ready' } }),
    true, '行情资料尚未就绪，等待新鲜报价。');
  same(result.kind, 'buy_open'); has(text, '计划买入'); has(text, '等待新鲜报价');
  lacks(text, '行情下跌所以买入');
});
test('pending simulated orders remain unfilled plans', () => {
  const { text } = output(fixture({ progress: 'pending_order' }));
  has(text, '已经提交模拟委托'); has(text, '委托尚未计为成交'); lacks(text, '已经买入');
});
test('sell-first sequencing is an execution wait, not failed eligibility', () => {
  const { text } = output(fixture({ progress: 'waiting_sell' }));
  has(text, '先卖后买'); has(text, '等待卖出步骤完成'); lacks(text, '配置资格未通过');
});
test('sellable limits explain waiting for rules without claiming completion', () => {
  const { text } = output(fixture({ actual: 500, target: 300, action: 'sell', progress: 'sellable_limited' }));
  has(text, '可卖份额不足'); has(text, '等待规则允许'); lacks(text, '已经卖出');
});
test('terminated orders never imply automatic retries', () => {
  const { text } = output(fixture({ progress: 'terminal_order' }));
  has(text, '本轮委托已经结束'); has(text, '不会自动重试'); lacks(text, '将自动重试');
});
test('unrecorded eligibility is not converted to a bullish claim', () => {
  const { result, text } = output(fixture({ eligible: null }));
  same(result.kind, 'buy_open'); has(text, '详细依据未记录'); lacks(text, '配置资格已通过');
});
test('raw saved notes remain data and cannot execute markup', () => {
  const payload = '<img src=x onerror="window.__tradePayloadRan=true">账户原文';
  const { result } = output(fixture({ note: payload }));
  same(result.note, payload); same(context.window.__tradePayloadRan, undefined);
  context.window.ETF_I18n.language = 'en';
  same(String(result.note), payload); context.window.ETF_I18n.language = 'zh';
});
test('the actual function leaves its inputs unchanged', () => {
  const input = freeze(fixture({ actual: 100, target: 500 }));
  const before = JSON.stringify(input);
  const { result } = output(input);
  same(JSON.stringify(input), before); result.lines.push('test-only result mutation');
  same(JSON.stringify(input), before);
});
test('historical fills cannot supply a new cause for the current remaining plan', () => {
  const input = fixture({ actual: 500, target: 500, action: 'hold', progress: 'target_reached' });
  const baseline = output(input).text;
  input.summary.latest_fill = { side: 'sell', quantity: 999900, current_signal: false,
    current_plan: false, matched_at: '2020-01-01T10:00:00+08:00', reason: '旧信号的原因' };
  const { result, text } = output(input);
  same(result.kind, 'hold'); same(text, baseline); lacks(text, '999900'); lacks(text, '旧信号的原因');
});
test('translated fixed explanations preserve quantities without unresolved placeholders', () => {
  context.window.ETF_I18n.language = 'en';
  const { text } = output(fixture({ actual: 300, target: 500 }));
  checks++; assert.ok(!/[\u3400-\u9fff]/.test(text), 'English explanation must not retain Chinese fixed text');
  has(text, '300'); has(text, '500'); has(text, '200'); has(text, '50%');
  checks++; assert.ok(!/\{[a-z_]+\}/.test(text), 'No unresolved quantity placeholders');
  context.window.ETF_I18n.language = 'zh';
});

console.log(JSON.stringify({ passed: true, cases: cases.length, checks, caseNames: cases }, null, 2));
