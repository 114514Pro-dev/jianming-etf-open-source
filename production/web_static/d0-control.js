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
  let brokerAvailable = false;
  let liveOrders = false;
  let ordersConfigured = false;
  let accountBound = false;
  let orderToken = null;
  let autoToken = null;
  let autoActive = false;
  let autoTimer = null;
  let diagnosticsRequest = 0;
  let diagnosticsToken = null;
  let syncTimer = null;
  let syncRequest = 0;
  let syncNetwork = false;
  const syncDownload = byId('sync-download');
  const downloadKey = `etf-connector-download:${syncDownload.getAttribute('href')}`;
  let downloadRequested = false;
  try { downloadRequested = localStorage.getItem(downloadKey) === 'yes'; } catch { /* optional */ }
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

  const syncMessages = {
    not_linked: '未连接，或上次连接已过期。',
    waiting: '等待本机同步工具连接…',
    linked: '已接收到本机工具的连接。尚未收到只读核对结果。',
    verified: '已接收到工具报告：东方财富只读核对成功。不代表可以下单。',
    failed: '已接收到工具报告：只读核对未通过。请在本机查看原因。',
  };

  function clearSyncCode() {
    byId('sync-code').value = '';
    byId('sync-code-box').hidden = true;
  }

  async function readSyncStatus() {
    const id = ++syncRequest;
    clearTimeout(syncTimer);
    try {
      const result = await call('/api/d0-control/sync/status');
      if (id !== syncRequest) return;
      if (result.state !== 'waiting') clearSyncCode();
      const network = result.broker_network_authorized === true;
      const networkMessage = network ? ' 网页券商网络已临时授权。' : result.broker_network_mismatch
        ? ' 网页和工具的公网网络不一致，请使用同一网络重新配对。' : '';
      byId('sync-status').textContent = (syncMessages[result.state] || '同步状态不可用。') + networkMessage;
      if (network !== syncNetwork) {
        syncNetwork = network;
        void refresh();
      }
      if (network || result.state === 'waiting' || result.state === 'linked') {
        syncTimer = setTimeout(readSyncStatus, 2500);
      }
    } catch (error) {
      if (id === syncRequest) {
        clearSyncCode();
        byId('sync-status').textContent = error.message;
      }
    }
  }

  syncDownload.addEventListener('click', () => {
    downloadRequested = true;
    try { localStorage.setItem(downloadKey, 'yes'); } catch { /* optional */ }
  });
  byId('sync-start').addEventListener('click', async () => {
    // Browsers cannot detect installed software; request each new ZIP version once on a user gesture.
    if (!downloadRequested) syncDownload.click();
    const button = byId('sync-start');
    button.disabled = true;
    byId('sync-refresh').disabled = true;
    ++syncRequest;
    clearTimeout(syncTimer);
    clearSyncCode();
    try {
      const result = await call('/api/d0-control/sync/pair', {method: 'POST', headers: {'X-CSRF-Token': csrf}});
      byId('sync-code').value = result.code;
      byId('sync-code-box').hidden = false;
      await readSyncStatus();
    } catch (error) { byId('sync-status').textContent = error.message; }
    finally {
      button.disabled = false;
      byId('sync-refresh').disabled = false;
    }
  });
  byId('sync-refresh').addEventListener('click', readSyncStatus);
  byId('sync-copy').addEventListener('click', async () => {
    const code = byId('sync-code');
    try { await navigator.clipboard.writeText(code.value); }
    catch { code.select(); }
  });

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
      setAvailability(status.broker_state, status.broker_orders_configured === true, status.account_bound === true);
      if (brokerAvailable) {
        try { setBroker(await call('/api/d0-control/broker')); }
        catch { setAvailability('unavailable'); }
      }
      return marketReady;
    } catch (error) {
      byId('signal').textContent = error.message;
      marketReady = false;
      byId('inputs').disabled = true;
      setAvailability('unavailable');
      return false;
    } finally {
      byId('refresh-signal').disabled = false;
    }
  }

  function setAvailability(state, orders = false, bound = false) {
    brokerAvailable = state === 'available';
    ordersConfigured = brokerAvailable && orders;
    accountBound = brokerAvailable && bound;
    const messages = {
      disabled: '网页实盘尚未开启。本机工具可配对和收信；这不会开启真实委托。',
      private_origin_required: '当前地址或网络未获券商访问授权；本站不会收取证券凭据。',
      connector_pairing_required: '请在当前网络点击「开始配对」，并在本机工具输入配对码。配对成功后，网站会自动授权此网页会话的网络，无需填公网 IP。',
    };
    const badge = byId('broker-badge');
    if (!brokerAvailable) {
      badge.textContent = state === 'disabled' ? '网页实盘未开启' : state === 'connector_pairing_required' ? '等待网络授权' : '网页实盘暂不可用';
    }
    const message = byId('broker-unavailable');
    message.hidden = brokerAvailable;
    message.textContent = messages[state] || '无法确认券商连接状态。请刷新 D0 状态后重试。';
    byId('broker-status').hidden = !brokerAvailable;
    if (!brokerAvailable) {
      clearRebindCode();
      byId('broker-password').value = '';
      setBroker({connected: false});
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

  function clearRebindCode() {
    byId('broker-rebind-box').hidden = true;
    byId('broker-rebind-code').value = '';
    byId('broker-rebind-code').type = 'password';
    byId('broker-copy-rebind').textContent = '复制';
  }

  function setBroker(state) {
    brokerConnected = brokerAvailable && state.connected === true;
    const liveActive = brokerConnected && state.live_active === true;
    liveOrders = ordersConfigured && liveActive && state.orders_armed === true;
    autoActive = brokerConnected && state.auto?.active === true;
    const badge = byId('broker-badge');
    const autoArmed = brokerConnected && state.auto?.armed === true;
    const mode = autoActive ? `${state.auto.strategy} 自动实盘运行中` : autoArmed ? '自动实盘已授权 · 未启动' : '手动实盘';
    if (brokerAvailable) badge.textContent = liveOrders || autoArmed ? mode : !accountBound ? '待首次授权' : '网页仅只读核对';
    badge.className = `pill ${liveOrders || autoArmed ? 'danger' : 'neutral'}`;
    byId('trading-mode').textContent = autoArmed ? mode : liveOrders ? '手动实盘已启用 · 不自动下单' : '不发送真实委托';
    byId('broker-order').hidden = !liveOrders || autoActive;
    if (autoActive) clearDraft();
    byId('broker-diagnostics-panel').hidden = autoActive;
    if (autoActive) clearDiagnostics();
    setAuto(state.auto);
    byId('broker-live').hidden = !brokerConnected || liveActive || autoArmed;
    byId('broker-arm').hidden = !liveActive || !ordersConfigured || liveOrders || autoArmed;
    byId('broker-stop').hidden = !liveActive;
    byId('broker-control-state').textContent = autoArmed ? '自动模式已授权；停止自动实盘后才能开启手动委托。' : liveOrders ? '已允许手动委托。每笔订单仍须确认。'
      : !liveActive ? '默认只读。开启实盘不会下单。'
      : ordersConfigured ? '实盘已开启，仍未授权真实委托。' : '实盘已开启，此部署尚未开放真实委托权限。';
    if (!liveOrders) clearDraft();
    byId('broker-connect').hidden = !brokerAvailable || brokerConnected;
    const enrolling = brokerAvailable && !accountBound && !brokerConnected;
    byId('broker-enrollment').hidden = !enrolling;
    byId('broker-enrollment').disabled = !enrolling;
    byId('broker-connect-submit').textContent = enrolling ? '授权并绑定唯一资金账号' : '登录东方财富证券';
    byId('broker-session').hidden = !brokerConnected;
    const unbind = byId('broker-unbind-panel');
    unbind.hidden = !brokerConnected || state.can_unbind !== true;
    if (unbind.hidden) {
      unbind.open = false;
      byId('broker-unbind-confirm').value = '';
      byId('broker-unbind-result').textContent = '';
    }
    if (accountBound) clearRebindCode();
    byId('broker-order-fields').disabled = !liveOrders || !brokerConnected || !marketReady || autoActive;
    byId('broker-settings').hidden = !brokerConnected || !state.limits;
    if (state.limits) showLimits(state.limits);
    const holdings = byId('broker-holdings');
    if (brokerConnected && state.positions) {
      holdings.textContent = '登录时持有／可卖：' + symbols.map(s => `${names[s]} ${state.positions[s].held}／${state.positions[s].sellable} 份`).join(' · ');
      holdings.hidden = false;
    }
    const cash = state.available_cash == null ? '' : ` · 登录时可用 ${yuan.format(Number(state.available_cash))}`;
    byId('broker-status').textContent = brokerConnected ? `已连接 · 尾号 ${state.account_tail}${cash}` : '尚未连接。';
    if (!brokerConnected) {
      clearDiagnostics();
      clearDraft();
      byId('broker-result').textContent = '';
      byId('broker-arm-account').value = '';
      byId('broker-arm-password').value = '';
      byId('broker-control-result').textContent = '';
      holdings.textContent = '';
      holdings.hidden = true;
      byId('broker-settings').open = false;
      byId('broker-limit-result').textContent = '';
    }
  }

  function clearDiagnostics() {
    ++diagnosticsRequest;
    byId('broker-diagnostics-result').replaceChildren();
    byId('broker-diagnostics-receipt').value = '';
    diagnosticsToken = null;
    byId('broker-field-verify').hidden = true;
    byId('broker-field-verify').reset();
    byId('broker-field-result').textContent = '';
  }

  window.addEventListener('pagehide', clearDiagnostics);
  byId('broker-diagnostics-panel').addEventListener('toggle', (event) => {
    if (!event.currentTarget.open) clearDiagnostics();
  });
  byId('broker-diagnostics').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!brokerConnected || autoActive) return;
    const receipt = byId('broker-diagnostics-receipt').value.trim();
    clearDiagnostics();
    const query = diagnosticsRequest;
    const output = byId('broker-diagnostics-result');
    const button = event.submitter;
    button.disabled = true;
    output.textContent = '正在只读查询券商…';
    try {
      const result = await brokerCall('diagnostics', {receipt});
      if (query !== diagnosticsRequest || !brokerConnected || autoActive) return;
      output.replaceChildren();
      const row = (text) => {
        const p = document.createElement('p');
        p.textContent = text;
        output.append(p);
      };
      const sampled = new Date(result.observed_at);
      if (Number.isFinite(+sampled)) row(`查询时间：${clock.format(sampled)}（北京时间）`);
      row(`可用资金：${yuan.format(Number(result.available_cash_cny))}（不是总资产）`);
      if (result.equity_candidates.length) {
        for (const {field, amount_cny} of result.equity_candidates) row(`总资产候选 ${field}：${yuan.format(Number(amount_cny))}`);
        row('候选字段不会自动采纳；请与官方客户端的总资产核对。');
      } else row('未识别到受支持的总资产候选字段，不能据此开放自动委托。');
      if (result.order?.state === 'found') {
        row(`当日委托：${result.order.status ?? '状态未知'}；委托份额 Wtsl：${result.order.submitted_shares ?? '未核实'}；实际成交 Cjsl：${result.order.filled_shares ?? '未核实'}。`);
        row(result.order.full_fill_candidate ? '这是整笔成交候选样本，请与官方客户端核对。' : '不是可用的整笔成交样本。');
      } else if (receipt) row('未找到唯一、完整的当日委托记录。请核对委托编号，或选一笔当日已成交的委托。');
      else row('未填写委托编号，本次只核对资金字段。');
      if (result.verification_token) {
        diagnosticsToken = result.verification_token;
        byId('broker-field-name').replaceChildren(...result.verifiable_fields.map(field => new Option(field, field)));
        byId('broker-field-verify').hidden = false;
      }
    } catch (error) {
      if (query === diagnosticsRequest) output.textContent = error.message;
    } finally { button.disabled = false; }
  });

  byId('broker-field-verify').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!diagnosticsToken) return;
    const query = diagnosticsRequest;
    const button = event.submitter;
    const result = byId('broker-field-result');
    button.disabled = true;
    try {
      const state = await brokerCall('auto-verify', {
        token: diagnosticsToken, field: byId('broker-field-name').value,
        total_cny: byId('broker-field-total').value.trim(), filled_shares: byId('broker-field-filled').value.trim(),
        confirmation: byId('broker-field-phrase').value.trim(),
      });
      clearDiagnostics();
      byId('broker-diagnostics-panel').open = false;
      setBroker(state);
    } catch (error) { if (query === diagnosticsRequest) result.textContent = error.message; }
    finally { button.disabled = false; }
  });

  byId('broker-auto-arm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const passwordInput = byId('broker-auto-password');
    const payload = {username: byId('broker-auto-account').value.trim(), password: passwordInput.value,
      confirmation: byId('broker-auto-arm-phrase').value.trim()};
    event.currentTarget.reset();
    const button = event.submitter;
    button.disabled = true;
    clearAutoPlan();
    try { setBroker(await brokerCall('auto-arm', payload)); }
    catch (error) { byId('broker-auto-result').textContent = error.message; }
    finally { button.disabled = false; }
  });

  function clearAutoPlan(clearResult = true) {
    autoToken = null;
    byId('broker-auto-start').hidden = true;
    byId('broker-auto-phrase').value = '';
    if (clearResult) byId('broker-auto-result').textContent = '';
  }

  function setAuto(state) {
    clearTimeout(autoTimer);
    const configured = brokerConnected && state?.configured === true;
    byId('broker-auto-preview').hidden = !configured || autoActive;
    byId('broker-auto-stop').hidden = !(autoActive || state?.armed);
    byId('broker-auto-arm').hidden = !brokerConnected || !state?.verified || !state?.enabled || state.armed || autoActive;
    if (byId('broker-auto-arm').hidden) byId('broker-auto-arm').reset();
    byId('broker-auto-state').textContent = !state?.verified ? '完成下方只读字段核对后，可在网页单独授权自动实盘。'
      : !state.enabled ? '字段已核对；站点交易权限关闭。'
      : !state.armed && !autoActive ? '字段已核对；自动实盘未授权。'
      : `${state.strategy ? `${state.strategy} · ` : ''}${state.message} 周期上限 ¥${state.budget_cny}。`;
    if (!brokerConnected || autoActive) clearAutoPlan(!brokerConnected);
    if (autoActive) autoTimer = setTimeout(async () => {
      try { setBroker(await call('/api/d0-control/broker')); }
      catch { setAvailability('unavailable'); }
    }, 2500);
  }

  byId('broker-auto-strategy').addEventListener('change', () => clearAutoPlan());
  byId('broker-auto-preview').addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAutoPlan();
    const select = byId('broker-auto-strategy');
    const strategy = select.value;
    const output = byId('broker-auto-result');
    event.submitter.disabled = true;
    try {
      const plan = await brokerCall('auto-preview', {strategy});
      if (strategy !== select.value || !brokerConnected) return;
      const summary = plan.orders.map(row => `${row.side === 'sell' ? '卖' : '买'} ${names[row.symbol]} ${row.quantity} 份，限价 ${row.price_limit} 元`).join('；');
      output.textContent = `${strategy} · ${summary || '无待调仓'} · 保留现金 ¥${Number(plan.cash_reserve_cny).toFixed(2)}。${plan.message}`;
      if (plan.token && plan.auto_enabled && !autoActive) {
        autoToken = plan.token;
        byId('broker-auto-start').hidden = false;
      }
    } catch (error) { output.textContent = error.message; }
    finally { event.submitter.disabled = false; }
  });
  byId('broker-auto-start').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!autoToken) return;
    const token = autoToken;
    const confirmation = byId('broker-auto-phrase').value.trim();
    clearAutoPlan(false);
    try {
      await brokerCall('auto-start', {token, confirmation});
      setBroker(await call('/api/d0-control/broker'));
    } catch (error) { byId('broker-auto-result').textContent = error.message; }
  });
  byId('broker-auto-stop').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await brokerCall('auto-stop', {});
      setBroker(await call('/api/d0-control/broker'));
      clearAutoPlan();
    } catch (error) { byId('broker-auto-result').textContent = error.message; }
    finally { button.disabled = false; }
  });

  function showLimits(limits) {
    byId('broker-single').value = limits.single_cny;
    byId('broker-daily').value = limits.daily_cny;
  }

  byId('broker-limits').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!brokerConnected) return;
    const submit = event.submitter;
    const output = byId('broker-limit-result');
    submit.disabled = true;
    clearDraft();
    try {
      showLimits(await brokerCall('limits', {single_cny: byId('broker-single').value, daily_cny: byId('broker-daily').value}));
      output.textContent = '限额已保存，今日已提交金额不变。';
    } catch (error) { output.textContent = error.message; }
    finally { submit.disabled = false; }
  });

  byId('broker-connect').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!brokerAvailable) return;
    const submit = event.submitter;
    submit.disabled = true;
    const password = byId('broker-password');
    const payload = {username: byId('broker-account').value.trim(), password: password.value};
    password.value = '';
    const enroll = !accountBound;
    if (enroll) {
      const code = byId('broker-enrollment-code');
      const confirmation = byId('broker-enrollment-confirm');
      payload.enrollment_code = code.value.trim();
      payload.confirmation = confirmation.value.trim();
      code.value = '';
      confirmation.value = '';
    }
    byId('broker-status').textContent = '正在登录并只读核对…';
    try {
      const state = await brokerCall(enroll ? 'enroll' : 'connect', payload);
      if (enroll && state.connected === true && state.account_bound === true) setAvailability('available', ordersConfigured, true);
      setBroker(state);
    }
    catch (error) { byId('broker-status').textContent = error.message; }
    finally { submit.disabled = false; }
  });

  byId('broker-disconnect').addEventListener('click', async (event) => {
    event.currentTarget.disabled = true;
    try { setBroker(await brokerCall('disconnect', {})); }
    catch (error) { byId('broker-status').textContent = error.message; }
    finally { byId('broker-disconnect').disabled = false; }
  });

  // The one-time code is kept only on this page, never in browser storage.
  window.addEventListener('pagehide', clearRebindCode);
  byId('broker-copy-rebind').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    const code = byId('broker-rebind-code');
    try {
      await navigator.clipboard.writeText(code.value);
      button.textContent = '已复制';
    } catch {
      code.type = 'text';
      code.select();
      button.textContent = '请手动复制';
    }
  });

  byId('broker-unbind').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!brokerConnected) return;
    const submit = event.submitter;
    const confirmation = byId('broker-unbind-confirm');
    const output = byId('broker-unbind-result');
    submit.disabled = true;
    byId('broker-disconnect').disabled = true;
    output.textContent = '正在核对委托记录…';
    try {
      const state = await brokerCall('unbind', {confirmation: confirmation.value.trim()});
      setAvailability('available', ordersConfigured, false);
      setBroker(state);
      byId('broker-account').value = '';
      byId('broker-rebind-code').value = state.rebind_code;
      byId('broker-rebind-box').hidden = false;
      byId('broker-copy-rebind').focus();
    } catch (error) { output.textContent = error.message; }
    finally {
      confirmation.value = '';
      submit.disabled = false;
      byId('broker-disconnect').disabled = false;
    }
  });

  async function updateBrokerControl(button, action, payload) {
    button.disabled = true;
    const output = byId('broker-control-result');
    output.textContent = action === 'arm' ? '正在向券商重新验证…' : '';
    if (action === 'stop') {
      clearDraft();
      byId('broker-order-fields').disabled = true;
    }
    try {
      setBroker(await brokerCall(action, payload));
      output.textContent = action === 'stop' ? '已停止新委托。已送达券商的委托不会撤销。' : '';
    } catch (error) {
      try { setBroker(await call('/api/d0-control/broker')); }
      catch { setAvailability('unavailable'); }
      (brokerConnected ? output : byId('broker-status')).textContent = error.message;
    } finally { button.disabled = false; }
  }

  byId('broker-live').addEventListener('submit', (event) => {
    event.preventDefault();
    const confirmation = byId('broker-live-phrase');
    void updateBrokerControl(event.submitter, 'live', {confirmation: confirmation.value.trim()});
    confirmation.value = '';
  });
  byId('broker-arm').addEventListener('submit', (event) => {
    event.preventDefault();
    const confirmation = byId('broker-arm-phrase');
    const password = byId('broker-arm-password');
    const payload = {username: byId('broker-arm-account').value.trim(), password: password.value,
      confirmation: confirmation.value.trim()};
    confirmation.value = '';
    password.value = '';
    void updateBrokerControl(event.submitter, 'arm', payload);
  });
  byId('broker-stop').addEventListener('click', (event) => {
    void updateBrokerControl(event.currentTarget, 'stop', {});
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
    if (location.hash === '#broker') byId('broker').scrollIntoView({behavior: 'instant'});
    readSyncStatus();
    return refresh();
  }).catch((error) => { byId('notice').textContent = error.message; });
})();
