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
      const ready = status.source_status === 'ready' && status.historical_seed === false;
      const when = status.eligible_at ? ` · 最早可执行：${status.eligible_at}` : '';
      byId('signal').textContent = (ready ? 'D0 来源已就绪，算单时仍会重新校验行情。' : '当前没有可用盘中资料；不会算单。') + when;
      byId('inputs').disabled = !ready;
      return ready;
    } catch (error) {
      byId('signal').textContent = error.message;
      byId('inputs').disabled = true;
      return false;
    } finally {
      byId('refresh-signal').disabled = false;
    }
  }

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
    byId('notice').textContent = '已登录。此版本不会发出真实委托。';
    byId('workspace').hidden = false;
    return refresh();
  }).catch((error) => { byId('notice').textContent = error.message; });
})();
