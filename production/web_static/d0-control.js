'use strict';

(() => {
  const byId = (id) => document.getElementById(id);
  const form = byId('balances');
  const symbols = ['sz159915', 'sh512800', 'sh518880', 'sh511010'];
  const names = {sz159915: '创业板 ETF', sh512800: '银行 ETF', sh518880: '黄金 ETF', sh511010: '国债 ETF'};
  const yuan = new Intl.NumberFormat('zh-CN', {style: 'currency', currency: 'CNY'});
  const percentage = new Intl.NumberFormat('zh-CN', {style: 'percent', maximumFractionDigits: 2});
  let csrf = null;
  let verifiedAt = null;
  let marketReady = false;
  let brokerConnected = false;
  let orderToken = null;
  const clock = new Intl.DateTimeFormat('zh-CN', {timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short'});

  for (const symbol of symbols) {
    const row = byId('positions').insertRow();
    row.insertCell().textContent = `${names[symbol]} ${symbol.slice(2)}`;
    for (const [field, label] of [['held', '持有份额'], ['sellable', '可卖份额']]) {
      const input = document.createElement('input');
      input.name = `${symbol}_${field}`;
      input.type = 'number';
      input.min = '0';
      input.step = '1';
      input.required = true;
      input.setAttribute('aria-label', `${names[symbol]} ${label}`);
      row.insertCell().append(input);
    }
  }

  async function call(path, options) {
    const res = await fetch(path, {cache: 'no-store', redirect: 'error', ...options});
    let value;
    try { value = await res.json(); } catch { throw new Error('服务器未返回预期结果。'); }
    if (res.status === 401) {
      byId('workspace').hidden = true;
      byId('login').hidden = false;
      byId('notice').textContent = '登录已失效，请重新登录。';
    }
    if (!res.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '请求未成功。');
    return value;
  }

  async function refresh() {
    byId('refresh-signal').disabled = true;
    byId('signal').textContent = '正在读取…';
    try {
      const status = await call('/api/d0-control/status');
      const earliest = status.eligible_at ? new Date(status.eligible_at) : null;
      const when = earliest && Number.isFinite(+earliest) ? ` 最早可执行：${clock.format(earliest)}（北京时间）。` : '';
      marketReady = status.market_state === 'open' && !(earliest && +earliest > Date.now()) && status.source_status === 'ready' && status.historical_seed === false;
      const closed = {closed: '当前为非连续交易时段。', unknown: '交易日历未覆盖当前日期。'};
      byId('signal').textContent = (marketReady ? 'D0 行情已就绪；提交时会重新核对。' : closed[status.market_state] || (earliest && +earliest > Date.now() ? '信号尚未到执行时间。' : '交易时段内正在等待新鲜行情或确认信号。')) + when;
      byId('inputs').disabled = !marketReady;
      byId('broker-order-fields').disabled = !marketReady || !brokerConnected;
      byId('broker').hidden = !status.live_orders_enabled;
      byId('trading-mode').textContent = status.live_orders_enabled ? '手动实盘已启用 · 不自动下单' : '仅拟单 · 真实委托未启用';
      if (status.live_orders_enabled) setBroker(await call('/api/d0-control/broker'));
      return marketReady;
    } catch (error) {
      byId('signal').textContent = error.message;
      marketReady = false;
      byId('inputs').disabled = true;
      byId('broker-order-fields').disabled = true;
      return false;
    } finally {
      byId('refresh-signal').disabled = false;
    }
  }

  function brokerCall(action, payload) {
    return call(`/api/d0-control/broker/${action}`, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(payload)});
  }

  function clearDraft() {
    orderToken = null;
    byId('broker-confirm').hidden = true;
    byId('broker-phrase').value = '';
  }

  function setBroker(state) {
    brokerConnected = state.connected === true;
    byId('broker-connect').hidden = brokerConnected;
    byId('broker-session').hidden = !brokerConnected;
    byId('broker-order-fields').disabled = !brokerConnected || !marketReady;
    const cash = state.available_cash == null ? '' : ` · 登录时可用 ${yuan.format(Number(state.available_cash))}`;
    byId('broker-status').textContent = brokerConnected ? `已连接 · 尾号 ${state.account_tail}${cash}` : '尚未连接。';
    if (!brokerConnected) clearDraft();
  }

  byId('broker-connect').addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = event.submitter;
    submit.disabled = true;
    const password = byId('broker-password');
    const payload = {username: byId('broker-account').value.trim(), password: password.value};
    password.value = '';
    byId('broker-status').textContent = '正在登录并只读核对…';
    try { setBroker(await brokerCall('connect', payload)); }
    catch (error) { byId('broker-status').textContent = error.message; }
    finally { submit.disabled = false; }
  });

  byId('broker-disconnect').addEventListener('click', async (event) => {
    event.currentTarget.disabled = true;
    try { setBroker(await brokerCall('disconnect', {})); }
    catch (error) { byId('broker-status').textContent = error.message; }
    finally { byId('broker-disconnect').disabled = false; }
  });

  byId('broker-order').addEventListener('input', clearDraft);
  byId('broker-order').addEventListener('submit', async (event) => {
    event.preventDefault();
    clearDraft();
    const submit = event.submitter;
    submit.disabled = true;
    try {
      const draft = await brokerCall('draft', {symbol: byId('broker-symbol').value, side: byId('broker-side').value,
        price: byId('broker-price').value, quantity: Number(byId('broker-quantity').value)});
      orderToken = draft.order_token;
      byId('broker-draft').textContent = `${names[draft.symbol]} ${draft.side === 'buy' ? '买入' : '卖出'} ${draft.quantity} 份 · 限价 ${draft.price} 元 · ${yuan.format(Number(draft.notional))}（不含费用）。${draft.expires_in} 秒内有效。`;
      byId('broker-result').textContent = '';
      byId('broker-confirm').hidden = false;
    } catch (error) { byId('broker-result').textContent = error.message; }
    finally { submit.disabled = false; }
  });

  byId('broker-confirm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!orderToken) return;
    const payload = {order_token: orderToken, confirmation: byId('broker-phrase').value};
    clearDraft();
    byId('broker-order-fields').disabled = true;
    byId('broker-result').textContent = '正在向券商提交，请勿重复操作…';
    try {
      const result = await brokerCall('submit', payload);
      byId('broker-result').textContent = result.state === 'submitted'
        ? `收到委托编号 ${result.broker_receipt}，不是成交确认。请在券商端核对。`
        : '结果未能核实。不要重新提交，请到券商端核对委托和成交。';
    } catch (error) {
      byId('broker-result').textContent = `${error.message} 如未确认结果，先查券商，不要重发。`;
    }
    await refresh();
  });

  function clearOrders(message) {
    byId('orders').replaceChildren();
    byId('orders-table').hidden = true;
    byId('allocation-bars').replaceChildren();
    byId('allocation').hidden = true;
    byId('result').textContent = message;
  }

  function showAllocation(result) {
    byId('allocation-equity').textContent = yuan.format(Number(result.equity));
    for (const symbol of [...symbols, 'cash']) {
      const row = document.createElement('div');
      row.className = 'allocation-row';
      const label = document.createElement('span');
      label.textContent = names[symbol] || '目标现金';
      const figure = document.createElement('span');
      figure.className = 'allocation-number';
      const {weight, target_value: value} = result.allocation[symbol];
      const fraction = Number(weight);
      figure.textContent = `${percentage.format(fraction)} · ${yuan.format(Number(value))}`;
      const bar = document.createElement('progress');
      bar.max = 1;
      bar.value = fraction;
      bar.setAttribute('aria-label', `${label.textContent}目标权重`);
      row.append(label, figure, bar);
      byId('allocation-bars').append(row);
    }
    byId('allocation').hidden = false;
  }

  form.addEventListener('input', (event) => {
    const verified = byId('verified');
    if (event.target !== verified) verified.checked = false;
    verifiedAt = verified.checked ? new Date().toISOString() : null;
    clearOrders('请在核对后重新生成拟单。');
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!verifiedAt || !csrf) return;
    const data = new FormData(form);
    const balances = {observed_at: verifiedAt, pending_orders: false, positions: {}};
    for (const key of ['cash', 'available_cash', 'commission_rate', 'min_fee']) balances[key] = data.get(key);
    for (const s of symbols) balances.positions[s] = {held: data.get(`${s}_held`), sellable: data.get(`${s}_sellable`)};
    byId('inputs').disabled = true;
    byId('refresh-signal').disabled = true;
    clearOrders('正在用当前信号算单…');
    try {
      const result = await call('/api/d0-control/preview', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(balances)});
      if (result.mode !== 'preview_only') throw new Error('返回结果不是拟单。');
      const stage = {sell_first: '先卖出，实际卖出后再核对资金', sell_blocked: '缺少可卖份额，暂不买入', buy: '买入拟单', no_affordable_lot: '可用资金不足一手', at_target: '暂无整手调仓拟单'};
      const remainder = result.sell_remainder.map((row) => `${row.symbol.slice(2)} 待卖 ${row.shares_not_in_preview} 份`).join('；');
      byId('result').textContent = `${stage[result.stage] || '生成拟单'} · 尚未委托${remainder ? ` · ${remainder}` : ''}`;
      showAllocation(result);
      for (const order of result.orders) {
        const row = byId('orders').insertRow();
        for (const value of [order.symbol.slice(2), order.side === 'buy' ? '买入' : '卖出', order.quantity, order.limit_price]) row.insertCell().textContent = value;
      }
      byId('orders-table').hidden = !result.orders.length;
    } catch (error) {
      clearOrders(`没有生成拟单：${error.message}`);
    } finally {
      verifiedAt = null;
      byId('verified').checked = false;
      byId('inputs').disabled = false;
      byId('refresh-signal').disabled = false;
    }
  });

  byId('refresh-signal').addEventListener('click', () => {
    clearOrders('已清除旧拟单，核对后请重新生成。');
    refresh();
  });
  call('/api/session').then((session) => {
    if (!session.authenticated || !session.csrf) {
      byId('notice').textContent = '此页面需要先登录。';
      byId('login').hidden = false;
      return;
    }
    csrf = session.csrf;
    byId('notice').textContent = '已登录简明 ETF。';
    byId('workspace').hidden = false;
    return refresh();
  }).catch((error) => { byId('notice').textContent = error.message; });
})();
