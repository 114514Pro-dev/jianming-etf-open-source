'use strict';

(() => {
  const kinds = {signal:'调仓信号', order:'模拟委托', test:'测试提醒'};
  const deliveryStates = {
    pending:'等待发送', sending:'正在发送', retry:'等待重试', accepted:'推送加已受理，请在微信核对',
    sent:'已发送', failed:'发送失败', uncertain:'发送结果待核对', cancelled:'已取消'
  };
  const failureHints = {
    invalid_token:'请核对服务器上的推送密钥',
    verification_required:'请先在推送加完成实名认证',
    provider_restricted:'请在推送加查看账户限制',
    quota_exhausted:'请在推送加查看发送额度'
  };
  const errors = {
    NOTIFICATION_ACCOUNT:'请先创建当前策略的模拟账户。',
    NOTIFICATION_BINDING:'账户已变化，请刷新账户状态。',
    NOTIFICATION_UNCONFIGURED:'请先在服务器配置微信推送密钥。',
    NOTIFICATION_RATE_LIMIT:'测试提醒过于频繁，请稍后再试。'
  };

  function create({panel, transport, node, fixed, compactTime}) {
    let context = {}, binding = '', generation = 0, operation = '', data = null, errorText = '';
    const pendingWrites = new Map();
    const text = (key, values) => String(fixed(key, values));

    function checkbox(id, caption) {
      const input = node('input');
      input.type = 'checkbox';
      input.id = id;
      const label = node('label', 'confirm-choice');
      label.append(input, node('span', '', fixed(caption)));
      panel.append(label);
      return input;
    }

    const enabled = checkbox('rtp-wechat-enabled', '接收调仓信号（每次调仓一条）');
    const orders = checkbox('rtp-wechat-orders', '同时接收每笔已提交的模拟委托');
    const actions = node('div', 'button-row rtp-actions');
    function addButton(id, caption, handler) {
      const button = node('button', 'button secondary', fixed(caption));
      button.type = 'button';
      button.id = id;
      button.addEventListener('click', handler);
      actions.append(button);
      return button;
    }
    const test = addButton('rtp-wechat-test', '发送测试提醒', () => write('test'));
    const reload = addButton('rtp-wechat-refresh', '刷新提醒状态', refresh);
    const status = node('p', 'small rtp-wechat-status');
    status.id = 'rtp-wechat-status';
    status.setAttribute('role', 'status');
    const delivery = node('p', 'small muted');
    delivery.id = 'rtp-wechat-delivery';
    delivery.setAttribute('aria-live', 'polite');
    panel.append(actions, status, delivery);
    enabled.addEventListener('change', () => write('save'));
    orders.addEventListener('change', () => write('save'));
    panel.addEventListener('toggle', () => { if (panel.open) refresh(); });

    function statusText() {
      if (!context.snapshotReady) return text('请先刷新模拟账户状态。');
      if (!context.account) return text('创建当前策略的模拟账户后可设置微信提醒。');
      if (!binding) return text('账户身份待核对，请刷新账户状态。');
      const pending = pendingWrites.get(binding);
      if (pending === 'save') return text('正在保存微信提醒设置…');
      if (pending === 'test') return text('正在提交测试提醒…');
      if (operation === 'read') return text('正在读取微信提醒设置…');
      if (errorText) return text(errorText);
      if (!data) return text('请刷新提醒状态。');
      if (!data.configured) return text('微信推送通道尚未配置，请联系管理员。');
      if (!context.verified) return text('正在核对模拟账户状态。');
      return data.enabled ? text('已订阅 {strategy} 的调仓信号。', {strategy:data.strategy})
                          : text('微信提醒已关闭，可先发送一条测试提醒。');
    }

    function render() {
      const editable = context.verified && binding && data && !operation && !pendingWrites.has(binding);
      if (operation !== 'save') {
        enabled.checked = Boolean(data?.enabled);
        orders.checked = Boolean(data?.enabled && data.orders_enabled);
      }
      enabled.disabled = !(editable && (data.configured || data.enabled));
      orders.disabled = !(editable && data.configured && data.enabled);
      test.disabled = !(editable && data.configured);
      reload.disabled = !context.verified || !binding || Boolean(operation) || pendingWrites.has(binding);
      status.textContent = statusText();
      const last = data?.last_delivery;
      delivery.hidden = !last;
      if (last) {
        const hint = last.status === 'failed' && Object.hasOwn(failureHints, last.reason) ? text(failureHints[last.reason]) : '';
        delivery.textContent = text('最近提醒 · {kind} · {status} · {time}', {
          kind:text(kinds[last.kind]), status:text(deliveryStates[last.status]),
          time:compactTime(last.updated_at)
        }) + (hint ? ' · ' + hint : '');
      } else {
        delivery.textContent = '';
      }
    }

    function valid(data) {
      if (!data || data.contract_version !== 'paper-wechat-v1' || data.strategy !== context.strategy ||
          data.account_id !== context.account.id || data.account_created_at !== context.account.created_at ||
          typeof data.configured !== 'boolean' || typeof data.enabled !== 'boolean' ||
          typeof data.orders_enabled !== 'boolean' || (data.orders_enabled && !data.enabled)) return false;
      const last = data.last_delivery;
      return last === null || (last && Object.hasOwn(kinds, last.kind) && Object.hasOwn(deliveryStates, last.status) &&
        typeof last.updated_at === 'string' && Number.isFinite(Date.parse(last.updated_at)));
    }

    async function request(kind, send, matches) {
      const started = generation;
      const target = binding;
      if (kind !== 'read') pendingWrites.set(target, kind);
      operation = kind;
      errorText = '';
      render();
      try {
        const result = await send();
        if (started !== generation) return;
        if (!valid(result) || (matches && !matches(result))) throw new Error('invalid response');
        data = result;
      } catch (error) {
        if (started !== generation) return;
        data = null;
        errorText = Object.hasOwn(errors, error?.code) ? errors[error.code] :
          kind === 'test' ? '测试提醒结果待核对，请先刷新状态并查看微信。' :
          '微信提醒设置未能核对，请刷新提醒状态。';
      } finally {
        if (kind !== 'read') pendingWrites.delete(target);
        if (started === generation) {
          operation = '';
          render();
        } else if (kind !== 'read' && binding === target) {
          render();
          refresh();
        }
      }
    }

    function refresh() {
      if (!panel.open || !context.verified || !binding || operation || pendingWrites.has(binding)) return;
      return request('read', () => transport.loadWechat(context.strategy));
    }

    function write(kind) {
      if (!context.verified || !binding || !data || operation || pendingWrites.has(binding)) return render();
      const body = {account_id:data.account_id, account_created_at:data.account_created_at};
      const strategy = context.strategy;
      if (kind === 'test') {
        if (!data.configured) return;
        return request(kind, () => transport.testWechat(body, strategy));
      }
      body.enabled = enabled.checked;
      body.orders_enabled = body.enabled && orders.checked;
      if (!body.enabled) orders.checked = false;
      if (body.enabled && !data.configured) return render();
      return request(kind, () => transport.saveWechat(body, strategy),
        result => result.enabled === body.enabled && result.orders_enabled === body.orders_enabled);
    }

    function update(next) {
      const account = next.account;
      const nextBinding = next.active && account && account.strategy === next.strategy &&
        typeof account.created_at === 'string' && Number.isFinite(Date.parse(account.created_at))
        ? JSON.stringify([next.strategy, account.id, account.created_at]) : '';
      const wasVerified = context.verified;
      const changed = nextBinding !== binding;
      context = next;
      if (changed) {
        generation++;
        binding = nextBinding;
        operation = '';
        data = null;
        errorText = '';
      }
      render();
      if (changed || (!wasVerified && !data && !errorText)) refresh();
    }

    return {update, refresh};
  }

  window.RealtimePaperWechat = {create};
})();
