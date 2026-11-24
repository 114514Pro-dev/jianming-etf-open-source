(function () {
  'use strict';

  const VERSION = 'd0-performance-comparison-v1';
  const SERIES = ['account', 'market', 'chinext', 'd0'];
  const LABELS = {account: '模拟账户', market: '上证指数', chinext: '创业板指数', d0: 'D0模型组合'};
  const COLORS = {account: '#6de1c2', market: '#77b9ff', chinext: '#e5b86b', d0: '#c9a2ff'};
  const EN = {
    '尚未选择当前策略账户。': 'Select an account for the current strategy.',
    'D0I-BOND-WW 周线择债模型': 'D0I-BOND-WW weekly bond model',
    '账户含实际已发生模拟费用；周线择债模型按固定WW规则以次日开盘回放（万3、最低5元、滑点2bp，含公司行动）。指数不含分红；模型不是本账户成交记录。': 'The account includes incurred simulation costs. The weekly bond model replays fixed WW rules at the next open (0.03% commission, CNY 5 minimum, 2 bp slippage, including corporate actions). Indices exclude dividends. The model is not this account’s trade history.',
    '账户与基准收益对比': 'Account and benchmark returns',
    '从首次启动后的首个共同收盘点归零；首个不完整交易日不纳入累计对比。账户日终按已记录成交重建，今天接最新可核对暂估；原账户盈亏记录保留。': 'Returns start at zero at the first shared confirmed close after the account first started. The initial partial trading day is excluded. Account closes are reconstructed from recorded fills, with the latest verifiable estimate appended. The original account P&L records are retained.',
    '模拟账户': 'Paper account', '上证指数': 'SSE Composite', '创业板指数': 'ChiNext Index', 'D0模型组合': 'D0 model portfolio',
    '全部': 'All', '最近30天': 'Last 30 days', '最近90天': 'Last 90 days', '刷新对比': 'Refresh comparison', '正在读取…': 'Loading…',
    '比较范围': 'Comparison range', '显示或隐藏曲线': 'Show or hide series', '收益率': 'Return', '时间（北京时间）': 'Time (China Standard Time)',
    '首次启动时间': 'First started', '实际共同归零点': 'Actual shared baseline', '尚待首个共同收盘': 'Waiting for the first shared close',
    '本次资料生成时间': 'Data generated', '数据表': 'Data table', '查看对比数据表': 'View comparison data', '选择日期或暂估记录': 'Choose a date or estimate',
    '记录时间': 'Record time', '本段本金': 'Segment capital', '本段归零点': 'Segment baseline', '本段归零估值': 'Segment baseline equity',
    '分段说明': 'Capital segments', '本金变化后各段重新归零，段与段之间不连接。': 'Each capital segment has its own zero baseline. Lines do not connect across segments.',
    '最新暂估': 'Latest estimate', '上次暂估（报价已过期）': 'Previous estimate (quote expired)', '上次暂估（时间待核对）': 'Previous estimate (time unverified)',
    '上次暂估（等待核对）': 'Previous estimate (awaiting verification)', '暂估记录（含上次核验值）': 'Estimates (includes previously verified values)',
    '已确认日终': 'Confirmed daily close', '账户日终重建': 'Reconstructed account close', '指数收盘': 'Index close', '模型日终回放': 'Model replay close',
    '估值': 'Equity', '报价源时间': 'Source time', '接收时间': 'Observed time', '该日无可比记录': 'No comparable record for this date',
    '本条之前有缺口，曲线不连接。': 'There is a gap before this point; the line is broken.', '已隐藏': 'Hidden', '尚无资料': 'No data yet',
    '最近资料时间': 'Latest data time', '暂不可用': 'Unavailable', '读取失败，正在显示上次成功读取的缓存。': 'The read failed. The last successfully read data is shown from cache.',
    '主账户状态尚未核对，正在显示上次成功读取的缓存。': 'The main account state has not been verified. The last successfully read data is shown from cache.',
    '账户状态尚未核对，待重新读取后显示对比。': 'The account state has not been verified. Reload the account to view the comparison.',
    '离开此页已暂停刷新；返回后会重新核对。': 'Refresh is paused while this page is inactive and resumes when you return.',
    '上次成功读取': 'Last successful read', '等待对比资料': 'Waiting for comparison data', '尚未选择D0账户。': 'Select a D0 account to view its comparison.',
    '此账户尚未首次启动；首次启动后将等待共同收盘点。': 'This account has not started yet. The comparison will wait for a shared close after it first starts.',
    '正在等待首次启动后的首个共同收盘点，暂不计算累计对比。': 'Waiting for the first shared confirmed close after the account first started. Cumulative comparison is not available yet.',
    '账户历史暂未通过成交与余额核对，暂不显示重建收益。': 'Recorded fills and account balances have not reconciled. Reconstructed returns are not available.',
    'D0模型组合低于最低回放本金，暂不提供该线。': 'The D0 model segment is below the minimum replay capital. This series is unavailable.',
    '该指数缺少所需历史收盘资料，其他可用曲线仍可查看。': 'Required historical index closes are missing. Other available series remain visible.',
    '最新报价尚不齐全或已过期，保留已确认收盘及上次已核验暂估，时间不变。': 'Latest quotes are incomplete or expired. Confirmed closes and previously verified estimates retain their original times.',
    '正在等待可核对的有效资料，请稍后刷新。': 'Waiting for verifiable data. Please refresh later.',
    '当前页面无法读取对比资料，请刷新页面后重试。': 'Comparison data cannot be loaded on this page. Reload the page and try again.',
    '对比资料未通过完整性核对，暂不显示。': 'Comparison data did not pass validation and cannot be shown.',
    '读取对比资料失败，请稍后刷新。': 'Could not read comparison data. Please refresh later.',
    '此范围尚无可比记录。': 'There are no comparable records in this range.', '选择至少一条曲线以查看图表。': 'Select at least one series to view the chart.',
    '各线暂估时间可能不同；请查看各自报价源时间，不按错时数据计算超额收益。': 'Estimate times may differ between series. Check each source time; excess returns are not calculated from mismatched times.',
    '账户含其已发生模拟费用；D0参考为原生日开盘回放（万3、最低5元、滑点2bp，含模型公司行动）；指数为不含分红的价格指数。模型不是本账户成交记录。': 'The account includes its incurred paper-trading costs. D0 uses native daily-open replay (0.03% commission, CNY 5 minimum, 2 bp slippage, including model corporate actions). Indices are price indices excluding dividends. The model is not this account’s trade history.',
    '旧账户不能回补首次启动分钟的指数行情，统一以共同收盘点为比较起点。': 'For older accounts, index quotes at the original start minute cannot be recovered. A shared confirmed close is used as the common baseline.',
    '全部四条曲线的日终及盘中暂估。历史缺口不补成零；盘中保留上次真实暂估及原时间，并标注等待核对。': 'Daily closes and intraday estimates for all four series. Historical gaps are not zero-filled. A previously verified intraday estimate retains its original time and is marked as awaiting verification.',
    '起点': 'Start', '终点': 'End', '段': 'Segment', '元': 'CNY', '—': '—'
  };
  Object.assign(EN, {
    '尚有本金分段等待共同收盘点，已有可比资料仍可查看。': 'Some capital segments are waiting for a shared close. Existing comparable data remains available.',
    '部分本金分段暂缺D0模型回放；缺少的时点留空。': 'D0 model replay is unavailable for some capital segments. Missing points are left blank.',
    '部分本金分段暂缺指数基准；缺少的时点留空。': 'Index baselines are unavailable for some capital segments. Missing points are left blank.',
    '历史记录较多，保留各段归零点及最近可用记录；省略区间不连接。': 'The history is long, so each segment’s baseline and the latest available records are retained. Lines do not connect across omitted intervals.',
    '历史缺口不补成零或沿用前值；盘中暂无新估值时，保留上次真实暂估及原时间，并标注等待核对。': 'Historical gaps are neither zero-filled nor carried forward. While a new intraday valuation is unavailable, the previously verified estimate retains its original time and is marked as awaiting verification.',
    '首次共同收盘权益为零，无法计算百分比收益；不会把归零点移到后续日期。': 'Equity at the first shared close is zero, so percentage returns cannot be calculated. The baseline is not moved to a later date.',
    '指数缺少本段共同起点行情，本段暂不显示该线。': 'The index quote at this segment’s shared baseline is missing. This series is unavailable for this segment.',
    'D0模型回放资料尚未就绪，其他可用曲线仍可查看。': 'D0 model replay data is not ready. Other available series remain visible.',
    '行情历史尚未准备好，待资料齐全后再显示对比。': 'Historical market data is not ready. The comparison will appear when the required data is available.',
    '策略资料与当前行情尚未核对一致，正在等待有效对比资料。': 'Strategy data and market data have not yet been verified together. Waiting for valid comparison data.',
    '账户资料已变化，正在等待重新核对后的对比。': 'Account details have changed. Waiting for the comparison to be verified again.',
    '尚无已创建的D0账户，创建并启动后才能建立对比。': 'There is no D0 account yet. Create and start one to build its comparison.',
    '对比资料与当前账户不一致，请重新读取账户后重试。': 'Comparison data does not match the current account. Reload the account and try again.',
    '交易日历资料尚未通过核对，暂不显示历史对比。': 'The trading calendar has not passed validation. Historical comparison is unavailable.',
    '现金估值，无需持仓报价': 'Cash valuation; no holding quotes required', '上次现金估值（已过期）': 'Previous cash valuation (expired)', '现金估值时间待核对': 'Cash valuation time unverified', '无需持仓报价': 'No holding quotes required',
    '上一页': 'Previous page', '下一页': 'Next page', '数据表页码': 'Data table pages', '第': 'Page', '页，共': 'of', '页': 'pages'
  });
  const state = {root: null, load: null, active: false, account: null, identity: null, current: false, epoch: 0,
    timer: null, deadline: null, resizeTimer: null, renderedWidth: null, pending: null, data: null, loadedAt: null, error: null, loading: false,
    range: 'all', visible: new Set(SERIES), selected: null, follow: true, tableOpen: false, tableTop: 0, tableLeft: 0, tablePage: null};

  function tr(text) {return window.ETF_I18n?.language === 'en' && Object.hasOwn(EN, text) ? EN[text] : text;}
  function text(value, max = 200) {return typeof value === 'string' && value.length > 0 && value.length <= max;}
  function record(value) {return !!value && typeof value === 'object' && !Array.isArray(value);}
  function dayTime(value) {
    if (typeof value !== 'string' || !/^(?:19|20|21|22|23|24|25|26|27|28|29)\d{2}-\d{2}-\d{2}$/.test(value)) return null;
    const at = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(at) && new Date(at).toISOString().slice(0, 10) === value ? at : null;
  }
  function timestamp(value) {
    if (typeof value !== 'string' || value.length > 50) return null;
    const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
    if (!match || dayTime(match[1]) === null || +match[2] > 23 || +match[3] > 59 || +match[4] > 59 || match[5] !== 'Z' && (+match[7] > 14 || +match[8] > 59 || +match[7] === 14 && +match[8] !== 0)) return null;
    const at = Date.parse(value);
    return Number.isFinite(at) ? at : null;
  }
  function decimal(value, positive = false) {
    if (typeof value !== 'string' || value.length > 80 || !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)) return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 && (!positive || number > 0) ? number : null;
  }
  function localDay(at) {return new Date(at + 8 * 3600000).toISOString().slice(0, 10);}
  function identity(account) {
    if (!record(account) || !text(account.id, 200) || timestamp(account.created_at) === null || account.strategy !== undefined && !['D0','D0I-BOND-WW'].includes(account.strategy)) return null;
    const rawCapital = Object.hasOwn(account, 'initial_cash') ? account.initial_cash : account.initial_capital;
    const capital = typeof rawCapital === 'number' ? rawCapital : decimal(rawCapital, true);
    if (!Number.isFinite(capital) || capital <= 0) return null;
    return JSON.stringify([account.id, account.created_at, capital, account.strategy || 'D0']);
  }

  // This boundary validates and copies the GET response before any value reaches the chart.
  function readComparison(raw, account) {
    const invalid = {status: 'invalid', data: null};
    const strategy = account?.strategy || 'D0';
    if (record(raw) && ((raw.strategy !== undefined && raw.strategy !== strategy) ||
        (strategy === 'D0I-BOND-WW' && (raw.strategy !== strategy || raw.model_strategy !== strategy)))) return invalid;
    if (!identity(account) || !record(raw) || raw.contract_version !== VERSION ||
      !['available', 'waiting', 'unavailable', 'invalid'].includes(raw.status) || raw.normalization !== 'first_shared_confirmed_close' ||
      raw.account_id !== account.id || raw.account_created_at !== account.created_at ||
      !(raw.reason === null || text(raw.reason, 120)) || !Array.isArray(raw.notes) || raw.notes.length > 100 ||
      raw.notes.some(note => !text(note, 120))) return invalid;
    const generated = timestamp(raw.generated_at), requested = raw.requested_start_at === null ? null : timestamp(raw.requested_start_at);
    if (generated === null || raw.requested_start_at !== null && (requested === null || requested > generated) ||
      !Array.isArray(raw.segments) || raw.segments.length > 1000 || !Array.isArray(raw.series) || raw.series.length !== 4) return invalid;
    const segments = [], bySegment = new Map();
    let prior = null;
    for (const item of raw.segments) {
      if (!record(item) || !text(item.id) || bySegment.has(item.id)) return invalid;
      const capital = decimal(item.capital, true), start = timestamp(item.starts_at), end = item.ends_at === null ? null : timestamp(item.ends_at),
        baseline = item.baseline_at === null ? null : timestamp(item.baseline_at), baseEquity = item.baseline_equity === null ? null : decimal(item.baseline_equity, true);
      if (capital === null || start === null || start > generated || item.ends_at !== null && (end === null || end < start || end > generated) ||
        (item.baseline_at === null) !== (item.baseline_equity === null) || item.baseline_at !== null &&
        (baseline === null || baseEquity === null || baseline < start || baseline > generated || end !== null && baseline > end) ||
        prior && (start < prior._start || prior._end === null || start < prior._end)) return invalid;
      const segment = {...item, _capital: capital, _start: start, _end: end, _baseline: baseline, _baseEquity: baseEquity, _index: segments.length};
      segments.push(segment); bySegment.set(item.id, segment); prior = segment;
    }
    const known = new Set(), series = [];
    for (const item of raw.series) {
      if (!record(item) || !SERIES.includes(item.id) || known.has(item.id) || !['available', 'unavailable'].includes(item.status) ||
        !(item.reason === null || text(item.reason, 120)) || !text(item.method, 300) ||
        !Array.isArray(item.points) || item.points.length > 5000) return invalid;
      if (strategy === 'D0I-BOND-WW' && item.id === 'd0' && item.method !== 'native_d0i_bond_ww_next_open') return invalid;
      const asOf = item.as_of === null ? null : timestamp(item.as_of);
      if (item.as_of !== null && (asOf === null || asOf > generated)) return invalid;
      known.add(item.id);
      const points = [], keys = new Set(), positions = new Set(); let previous = null;
      for (const point of item.points) {
        if (!record(point) || !text(point.key, 300) || keys.has(point.key) || typeof point.break_before !== 'boolean' ||
          !['reconstructed_close', 'index_close', 'model_close', 'intraday_estimate'].includes(point.phase)) return invalid;
        if (Object.hasOwn(point, 'retained') && (typeof point.retained !== 'boolean' ||
            point.phase !== 'intraday_estimate' || !['account', 'd0'].includes(item.id)) ||
          point.retained === true && point.retained_reason !== 'waiting_verified_quote' ||
          Object.hasOwn(point, 'retained_reason') && (point.retained !== true || point.retained_reason !== 'waiting_verified_quote')) return invalid;
        const segment = bySegment.get(point.segment_id), at = timestamp(point.at), date = dayTime(point.date),
          equity = point.equity === null ? null : decimal(point.equity), ratio = point.return_ratio,
          source = point.source_at === null ? null : timestamp(point.source_at), observed = point.observed_at === null ? null : timestamp(point.observed_at);
        const position = JSON.stringify([point.segment_id, point.phase === 'intraday_estimate' ? 'latest' : point.date, point.phase === 'intraday_estimate' ? 'live' : 'daily']);
        if (!segment || segment._baseline === null || at === null || date === null || localDay(at) !== point.date ||
          at > generated || at < segment._baseline || segment._end !== null && at > segment._end || positions.has(position) ||
          point.retained === true && (point.date !== localDay(generated) || segment._end !== null || segment.id !== segments.at(-1)?.id || equity === null) ||
          point.equity !== null && equity === null || !(ratio === null || typeof ratio === 'number' && Number.isFinite(ratio) && ratio >= -1) ||
          (equity === null) !== (ratio === null) || equity !== null && (Math.abs(equity / segment._baseEquity - 1 - ratio) > 1e-8 || at === segment._baseline && Math.abs(ratio) > 1e-8) ||
          point.source_at !== null && (source === null || source > generated) || point.observed_at !== null && (observed === null || observed > generated) ||
          source !== null && observed !== null && source > observed ||
          Object.hasOwn(point, 'cash_only') && typeof point.cash_only !== 'boolean' || point.cash_only === true &&
            (!['account', 'd0'].includes(item.id) || point.phase !== 'intraday_estimate' || point.source_at !== null) ||
          previous && (at < previous._at || segment._index < bySegment.get(previous.segment_id)._index ||
            point.segment_id !== previous.segment_id && !point.break_before)) return invalid;
        if (point.phase !== 'intraday_estimate' && point.phase !== (item.id === 'account' ? 'reconstructed_close' : item.id === 'd0' ? 'model_close' : 'index_close')) return invalid;
        const copy = {...point, _at: at, _equity: equity, _source: source, _observed: observed};
        points.push(copy); keys.add(point.key); positions.add(position); previous = copy;
      }
      series.push({...item, _asOf: asOf, points});
    }
    const data = {...raw, _generated: generated, _requested: requested, segments, series: SERIES.map(id => series.find(item => item.id === id))};
    return {status: raw.status === 'available' ? 'available' : 'waiting', data};
  }
  function seriesLabel(id) {return id==='d0'&&state.account?.strategy==='D0I-BOND-WW'?tr('D0I-BOND-WW 周线择债模型'):tr(LABELS[id]);}

  function comparisonRows(data) {
    if (!data) return [];
    const rows = new Map(), index = new Map(data.segments.map((segment, i) => [segment.id, i]));
    for (const series of data.series) {
      if (series.status !== 'available') continue;
      for (const point of series.points) {
        const phase = point.phase === 'intraday_estimate' ? 'live' : 'daily',
          key = JSON.stringify([point.segment_id, phase, phase === 'daily' ? point.date : 'latest']),
          at = phase === 'live' ? point._observed ?? point._at : point._at;
        let row = rows.get(key);
        if (!row) {row = {key, at, date: point.date, segment_id: point.segment_id, phase, points: {}}; rows.set(key, row);}
        row.at = Math.max(row.at, at); if (phase === 'live') row.date = localDay(row.at); row.points[series.id] = point;
      }
    }
    return [...rows.values()].sort((a, b) => a.at - b.at || index.get(a.segment_id) - index.get(b.segment_id) || (a.phase === 'live' ? 1 : -1));
  }
  function comparisonRangeRows(rows, range) {
    if (!rows.length || range === 'all') return rows.slice();
    const days = range === 30 || range === '30' ? 30 : range === 90 || range === '90' ? 90 : null;
    if (days === null) return rows.slice();
    const firstDate = dayTime(localDay(rows[rows.length - 1].at)) - (days - 1) * 86400000;
    return rows.filter(row => dayTime(row.date) >= firstDate);
  }

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  }
  function svgNode(tag, attributes = {}, value) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, val] of Object.entries(attributes)) element.setAttribute(name, String(val));
    if (value !== undefined) element.textContent = value;
    return element;
  }
  function number(value, digits = 2) {
    return Number.isFinite(value) ? new Intl.NumberFormat(window.ETF_I18n?.language === 'en' ? 'en-US' : 'zh-CN', {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(value) : '—';
  }
  function percent(value) {return value === null || !Number.isFinite(value) ? '—' : number(Math.abs(value) < .0000005 ? 0 : value * 100) + '%';}
  function money(value) {return Number.isFinite(value) ? number(value) + ' ' + tr('元') : '—';}
  function time(value) {
    const at = typeof value === 'number' ? value : timestamp(value);
    if (at === null || !Number.isFinite(at)) return '—';
    return new Intl.DateTimeFormat(window.ETF_I18n?.language === 'en' ? 'en-GB' : 'zh-CN', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false}).format(new Date(at));
  }
  function line(parent, name, value) {
    const pair = node('div', 'rtpc-pair'); pair.append(node('dt', '', name), node('dd', '', value)); parent.append(pair);
  }
  function reasonMessage(reason) {
    const code = typeof reason === 'string' ? reason : '';
    if (code === 'zero_baseline') return tr('首次共同收盘权益为零，无法计算百分比收益；不会把归零点移到后续日期。');
    if (code === 'index_anchor_missing') return tr('指数缺少本段共同起点行情，本段暂不显示该线。');
    if (code === 'model_unavailable') return tr('D0模型回放资料尚未就绪，其他可用曲线仍可查看。');
    if (code === 'market_cache_unavailable') return tr('行情历史尚未准备好，待资料齐全后再显示对比。');
    if (['signal_cache_mismatch', 'spec_mismatch'].includes(code)) return tr('策略资料与当前行情尚未核对一致，正在等待有效对比资料。');
    if (code === 'account_changed') return tr('账户资料已变化，正在等待重新核对后的对比。');
    if (code === 'account_not_created') return tr('尚无已创建的D0账户，创建并启动后才能建立对比。');
    if (code === 'account_mismatch') return tr('对比资料与当前账户不一致，请重新读取账户后重试。');
    if (code === 'invalid_sessions') return tr('交易日历资料尚未通过核对，暂不显示历史对比。');
    if (['not_started', 'account_not_started', 'no_start_event', 'first_start_missing'].includes(code)) return tr('此账户尚未首次启动；首次启动后将等待共同收盘点。');
    if (['waiting_for_baseline', 'no_shared_close', 'waiting_shared_close', 'baseline_unavailable', 'no_baseline', 'waiting_first_close', 'waiting_first_confirmed_close', 'no_confirmed_close', 'no_shared_confirmed_close'].includes(code)) return tr('正在等待首次启动后的首个共同收盘点，暂不计算累计对比。');
    if (['reconciliation_failed', 'history_reconciliation_failed', 'account_reconstruction_failed', 'invalid_ledger', 'invalid_history', 'history_invalid', 'ledger_reconciliation_failed'].includes(code)) return tr('账户历史暂未通过成交与余额核对，暂不显示重建收益。');
    if (['capital_below_minimum', 'insufficient_capital', 'model_capital_below_minimum', 'below_minimum_capital', 'capital_below_minimum_replay'].includes(code)) return tr('D0模型组合低于最低回放本金，暂不提供该线。');
    if (['index_history_unavailable', 'missing_index_history', 'index_no_history', 'missing_history', 'index_history_incomplete'].includes(code)) return tr('该指数缺少所需历史收盘资料，其他可用曲线仍可查看。');
    if (['quotes_unavailable', 'quote_unavailable', 'stale_quotes', 'quote_stale', 'live_unavailable', 'quotes_incomplete', 'live_quote_unavailable', 'live_quotes_unavailable'].includes(code)) return tr('最新报价尚不齐全或已过期，保留已确认收盘及上次已核验暂估，时间不变。');
    return tr('正在等待可核对的有效资料，请稍后刷新。');
  }
  function noteMessage(code) {
    const messages = {account_reconstructed_from_fills: null, index_price_excludes_dividends: null, model_native_fees: null,
      gaps_not_filled: '历史缺口不补成零或沿用前值；盘中暂无新估值时，保留上次真实暂估及原时间，并标注等待核对。', independent_live_times: null, first_partial_day_excluded: null,
      segments_waiting: '尚有本金分段等待共同收盘点，已有可比资料仍可查看。', history_truncated: '历史记录较多，保留各段归零点及最近可用记录；省略区间不连接。',
      model_segments_unavailable: '部分本金分段暂缺D0模型回放；缺少的时点留空。', index_segments_unavailable: '部分本金分段暂缺指数基准；缺少的时点留空。'};
    return Object.hasOwn(messages, code) ? messages[code] === null ? null : tr(messages[code]) : reasonMessage(code);
  }
  function missingMessage(series, segment) {
    if (series.id === 'd0' && segment && segment._capital < 1000) return tr('D0模型组合低于最低回放本金，暂不提供该线。');
    if (series.status !== 'available') return reasonMessage(series.reason);
    if (['market', 'chinext'].includes(series.id) && segment && !series.points.some(point => point.segment_id === segment.id)) return tr('该指数缺少所需历史收盘资料，其他可用曲线仍可查看。');
    return tr('该日无可比记录');
  }
  function pointPhase(point) {
    if (!point) return tr('该日无可比记录');
    if (point.phase === 'intraday_estimate') {
      if (point.retained === true) return tr('上次暂估（等待核对）');
      if (point.cash_only === true) {
        const age = Date.now() - (point._observed ?? point._at);
        return tr(age < -5000 ? '现金估值时间待核对' : age > 90000 ? '上次现金估值（已过期）' : '现金估值，无需持仓报价');
      }
      if (point._source === null) return tr('上次暂估（时间待核对）');
      const age = Date.now() - point._source;
      return tr(age < -5000 ? '上次暂估（时间待核对）' : age > 90000 ? '上次暂估（报价已过期）' : '最新暂估');
    }
    return tr({reconstructed_close: '账户日终重建', index_close: '指数收盘', model_close: '模型日终回放'}[point.phase] || '已确认日终');
  }
  function rowLabel(row) {
    if (row.phase !== 'live') return row.date;
    if (Object.values(row.points).some(point => point.retained === true)) return tr('暂估记录（含上次核验值）') + ' · ' + time(row.at);
    const points = Object.values(row.points), ages = points.map(point => {
      const at = point.cash_only === true ? point._observed ?? point._at : point._source;
      return at === null ? null : Date.now() - at;
    }), fresh = ages.some(age => age !== null && age >= -5000 && age <= 90000), future = ages.some(age => age !== null && age < -5000);
    return tr(fresh ? '最新暂估' : future ? '上次暂估（时间待核对）' : points.every(point => point.cash_only === true) ? '上次现金估值（已过期）' : points.some(point => point._source !== null) ? '上次暂估（报价已过期）' : '上次暂估（时间待核对）') + ' · ' + time(row.at);
  }
  function button(value, control, action) {
    const element = node('button', 'rtpc-button', value); element.type = 'button'; element.dataset.rtpcControl = control; element.addEventListener('click', action); return element;
  }
  function chartWidth(root) {
    let width = Number(root.clientWidth);
    if (!Number.isFinite(width) || width <= 0) return 960;
    if (typeof window.getComputedStyle === 'function') {
      const style = window.getComputedStyle(root), before = Number.parseFloat(style.paddingLeft), after = Number.parseFloat(style.paddingRight);
      width -= (Number.isFinite(before) ? before : 0) + (Number.isFinite(after) ? after : 0);
    }
    return Math.max(240, Math.min(960, Math.floor(width)));
  }
  function render() {
    if (!state.root) return;
    const focused = state.root.contains(document.activeElement) ? document.activeElement?.dataset?.rtpcControl : null;
    const root = state.root; state.renderedWidth = chartWidth(root); root.classList.add('rtp-performance-comparison'); root.replaceChildren(); delete root.dataset.selectedDate; delete root.dataset.selectedSegment;
    root.append(node('h3', '', tr('账户与基准收益对比')),
      node('p', 'rtpc-intro', tr('从首次启动后的首个共同收盘点归零；首个不完整交易日不纳入累计对比。账户日终按已记录成交重建，今天接最新可核对暂估；原账户盈亏记录保留。')));
    const top = node('div', 'rtpc-toolbar'), ranges = node('div', 'rtpc-ranges'); ranges.setAttribute('role', 'group'); ranges.setAttribute('aria-label', tr('比较范围'));
    for (const [range, label] of [['all', '全部'], [30, '最近30天'], [90, '最近90天']]) {
      const item = button(tr(label), 'range-' + range, () => {state.range = range; state.tablePage = null; render();}); item.setAttribute('aria-pressed', String(state.range === range)); ranges.append(item);
    }
    const refreshButton = button(tr(state.loading ? '正在读取…' : '刷新对比'), 'refresh', refresh);
    refreshButton.disabled = state.loading || !state.active || !state.current || !state.identity || typeof state.load !== 'function'; top.append(ranges, refreshButton); root.append(top);
    if (!state.identity) {root.append(node('p', 'rtpc-empty', tr('尚未选择当前策略账户。'))); finish(); return;}
    const banners = node('div', 'rtpc-banners'); banners.setAttribute('aria-live', 'polite');
    if (state.data && (!state.current || state.error)) {
      const message = !state.current ? '主账户状态尚未核对，正在显示上次成功读取的缓存。' : '读取失败，正在显示上次成功读取的缓存。';
      banners.append(node('p', 'rtpc-cache', tr(message) + ' ' + tr('上次成功读取') + '：' + time(state.loadedAt)));
    } else if (!state.current) banners.append(node('p', 'rtpc-empty', tr('账户状态尚未核对，待重新读取后显示对比。')));
    else if (state.error) banners.append(node('p', 'rtpc-empty', tr(state.error === 'loader' ? '当前页面无法读取对比资料，请刷新页面后重试。' : state.error === 'invalid' ? '对比资料未通过完整性核对，暂不显示。' : '读取对比资料失败，请稍后刷新。')));
    else if (state.loading && !state.data) banners.append(node('p', 'rtpc-empty', tr('正在读取…')));
    if (!state.active) banners.append(node('p', 'rtpc-note', tr('离开此页已暂停刷新；返回后会重新核对。')));
    root.append(banners);
    const data = state.data;
    if (!data) {finish(); return;}
    const meta = node('dl', 'rtpc-meta'); line(meta, tr('首次启动时间'), time(data._requested));
    const firstBaseline = data.segments.find(segment => segment._baseline !== null);
    line(meta, tr('实际共同归零点'), firstBaseline ? time(firstBaseline._baseline) : tr('尚待首个共同收盘'));
    line(meta, tr('本次资料生成时间'), time(data._generated)); root.append(meta);
    if (data.status !== 'available') root.append(node('p', 'rtpc-empty', reasonMessage(data.reason)));
    if (data.segments.length > 1) root.append(node('p', 'rtpc-segments', tr('本金变化后各段重新归零，段与段之间不连接。')));
    const legend = node('div', 'rtpc-legend'); legend.setAttribute('role', 'group'); legend.setAttribute('aria-label', tr('显示或隐藏曲线'));
    for (const series of data.series) {
      const item = button('', 'legend-' + series.id, () => {if (state.visible.has(series.id)) state.visible.delete(series.id); else state.visible.add(series.id); render();});
      item.style.setProperty('--rtpc-color', COLORS[series.id]); item.classList.add('rtpc-legend-button'); item.setAttribute('aria-pressed', String(state.visible.has(series.id)));
      const dot = node('span', 'rtpc-dot'); dot.setAttribute('aria-hidden', 'true'); item.append(dot, node('strong', '', seriesLabel(series.id)));
      const status = series.status === 'available' ? tr('最近资料时间') + '：' + time(series._asOf) : tr('暂不可用'); item.append(node('span', 'rtpc-series-time', status));
      if (series.status !== 'available') item.append(node('span', 'rtpc-series-reason', missingMessage(series, data.segments.at(-1))));
      legend.append(item);
    }
    root.append(legend);
    const noteCodes = [...new Set(data.notes)];
    for (const code of noteCodes) {const message = noteMessage(code); if (message) root.append(node('p', 'rtpc-note', message));}
    const rows = comparisonRangeRows(comparisonRows(data), state.range);
    if (!rows.length) root.append(node('p', 'rtpc-empty', tr('此范围尚无可比记录。')));
    else renderChart(root, data, rows);
    root.append(node('p', 'rtpc-note', tr('各线暂估时间可能不同；请查看各自报价源时间，不按错时数据计算超额收益。')),
      node('p', 'rtpc-note', tr('旧账户不能回补首次启动分钟的指数行情，统一以共同收盘点为比较起点。')),
      node('p', 'rtpc-note rtpc-method', tr(state.account?.strategy==='D0I-BOND-WW'?'账户含实际已发生模拟费用；周线择债模型按固定WW规则以次日开盘回放（万3、最低5元、滑点2bp，含公司行动）。指数不含分红；模型不是本账户成交记录。':'账户含其已发生模拟费用；D0参考为原生日开盘回放（万3、最低5元、滑点2bp，含模型公司行动）；指数为不含分红的价格指数。模型不是本账户成交记录。')));
    finish();
    function finish() {
      if (focused) {
        const target = [...root.querySelectorAll('[data-rtpc-control]')].find(item => item.dataset.rtpcControl === focused);
        if (target) target.focus({preventScroll: true});
      }
    }
  }

  function renderChart(root, data, rows) {
    const visible = data.series.filter(series => series.status === 'available' && state.visible.has(series.id));
    const chart = node('div', 'rtpc-chart'), width = state.renderedWidth || 960, compact = width < 600,
      height = compact ? width < 330 ? 250 : 260 : 350, left = compact ? 62 : 66, right = compact ? 12 : 22, top = compact ? 20 : 24, bottom = compact ? 40 : 46;
    const values = rows.flatMap(row => visible.map(series => row.points[series.id]?.return_ratio).filter(value => typeof value === 'number' && Number.isFinite(value)));
    let low = Math.min(0, ...values), high = Math.max(0, ...values), padding = Math.max((high - low) * .12, .005);
    low -= padding; high += padding;
    const start = rows[0].at, end = rows[rows.length - 1].at, span = end - start,
      x = at => span ? left + (at - start) / span * (width - left - right) : (left + width - right) / 2,
      y = ratio => top + (high - ratio) / (high - low) * (height - top - bottom);
    const svg = svgNode('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': tr('账户与基准收益对比')});
    svg.append(svgNode('title', {}, tr('账户与基准收益对比')));
    for (let i = 0; i <= 4; i++) {
      const value = low + (high - low) * i / 4, atY = y(value);
      svg.append(svgNode('line', {x1: left, x2: width - right, y1: atY, y2: atY, class: 'rtpc-grid'}),
        svgNode('text', {x: left - 8, y: atY + 4, 'text-anchor': 'end', class: 'rtpc-axis'}, percent(value)));
    }
    svg.append(svgNode('line', {x1: left, x2: width - right, y1: y(0), y2: y(0), class: 'rtpc-zero'}));
    const dateLabels = [];
    for (const ratio of compact ? [0, .5, 1] : [0, .25, .5, .75, 1]) {
      const at = start + span * ratio, label = localDay(at);
      if (dateLabels.includes(label)) continue;
      dateLabels.push(label); svg.append(svgNode('text', {x: x(at), y: height - 20, 'text-anchor': ratio === 0 ? 'start' : ratio === 1 ? 'end' : 'middle', class: 'rtpc-axis'}, compact ? label.slice(5) : label));
    }
    for (const series of visible) {
      let path = '', previous = null;
      for (const row of rows) {
        const point = row.points[series.id], ratio = point?.return_ratio;
        if (!point || ratio === null) {previous = null; continue;}
        const connect = previous && previous.segment_id === row.segment_id && !point.break_before;
        path += `${connect ? 'L' : 'M'}${x(row.at).toFixed(3)},${y(ratio).toFixed(3)} `;
        const dot = svgNode('circle', {cx: x(row.at), cy: y(ratio), r: point.phase === 'intraday_estimate' ? 4.5 : 2.7,
          fill: point.phase === 'intraday_estimate' ? 'var(--surface, #111d2d)' : COLORS[series.id], stroke: COLORS[series.id], 'stroke-width': 1.8});
        dot.append(svgNode('title', {}, seriesLabel(series.id) + ' · ' + rowLabel(row) + ' · ' + percent(ratio) + ' · ' + pointPhase(point))); svg.append(dot); previous = row;
      }
      svg.append(svgNode('path', {d: path.trim(), fill: 'none', stroke: COLORS[series.id], 'stroke-width': 2.3, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', class: 'rtpc-line'}));
    }
    const cursor = svgNode('line', {x1: left, x2: left, y1: top, y2: height - bottom, class: 'rtpc-cursor'}); svg.append(cursor);
    if (visible.length) chart.append(svg); else chart.append(node('p', 'rtpc-empty', tr('选择至少一条曲线以查看图表。')));
    root.append(chart);
    const range = node('input', 'rtpc-scrubber'); range.type = 'range'; range.min = '0'; range.max = String(rows.length - 1); range.step = '1'; range.dataset.rtpcControl = 'scrubber';
    range.setAttribute('aria-label', tr('选择日期或暂估记录')); range.disabled = rows.length < 2; root.append(range);
    const selection = node('div', 'rtpc-selection'), title = node('h4', 'rtpc-selection-title'), meta = node('dl', 'rtpc-selection-meta'), readout = node('div', 'rtpc-readout');
    const live = node('p', 'rtpc-sr'); live.setAttribute('aria-live', 'polite'); live.setAttribute('aria-atomic', 'true'); selection.append(title, meta, readout, live); root.append(selection);
    function inspect(index, user = false) {
      const bounded = Math.max(0, Math.min(rows.length - 1, index)), row = rows[bounded], segment = data.segments.find(item => item.id === row.segment_id);
      state.selected = row.key; if (user) state.follow = bounded === rows.length - 1;
      range.value = String(bounded); cursor.setAttribute('x1', x(row.at)); cursor.setAttribute('x2', x(row.at));
      root.dataset.selectedDate = row.date; root.dataset.selectedSegment = row.segment_id;
      title.textContent = rowLabel(row); meta.replaceChildren(); readout.replaceChildren();
      line(meta, tr('本段本金'), money(segment._capital)); line(meta, tr('本段归零点'), time(segment._baseline)); line(meta, tr('本段归零估值'), money(segment._baseEquity));
      const summary = [rowLabel(row)];
      for (const series of data.series) {
        const point = row.points[series.id], card = node('section', 'rtpc-series-card'); card.style.setProperty('--rtpc-color', COLORS[series.id]);
        card.append(node('h5', '', seriesLabel(series.id) + (state.visible.has(series.id) ? '' : ' · ' + tr('已隐藏'))));
        const value = node('strong', 'rtpc-return', point ? percent(point.return_ratio) : '—'); card.append(value);
        const details = node('dl', 'rtpc-point-meta');
        if (point) {
          card.append(node('p', 'rtpc-phase', pointPhase(point))); line(details, tr('估值'), money(point._equity)); line(details, tr('记录时间'), time(point._at));
          line(details, tr('报价源时间'), point.cash_only === true ? tr('无需持仓报价') : time(point._source)); line(details, tr('接收时间'), time(point._observed));
          if (point.break_before) card.append(node('p', 'rtpc-note', tr('本条之前有缺口，曲线不连接。')));
        } else card.append(node('p', 'rtpc-phase', missingMessage(series, segment)));
        card.append(details); readout.append(card); summary.push(seriesLabel(series.id) + ': ' + value.textContent);
      }
      const accessible = summary.join(' · '); range.setAttribute('aria-valuetext', accessible); if (user) live.textContent = accessible;
    }
    range.addEventListener('input', () => inspect(Number(range.value), true));
    const keyboard = event => {
      const at = Number(range.value); let next = null;
      if (event.key === 'Home') next = 0; else if (event.key === 'End') next = rows.length - 1;
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') next = at - 1;
      else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') next = at + 1;
      if (next !== null) {event.preventDefault(); inspect(next, true);}
    };
    range.addEventListener('keydown', keyboard); svg.tabIndex = 0; svg.dataset.rtpcControl = 'chart'; svg.addEventListener('keydown', keyboard);
    const pointer = event => {
      const rectangle = svg.getBoundingClientRect(); if (!rectangle.width) return;
      const position = (event.clientX - rectangle.left) / rectangle.width * width,
        at = span ? start + Math.max(0, Math.min(1, (position - left) / (width - left - right))) * span : start;
      let index = 0; for (let i = 1; i < rows.length; i++) if (Math.abs(rows[i].at - at) < Math.abs(rows[index].at - at)) index = i;
      inspect(index, true);
    };
    svg.addEventListener('pointermove', event => {if (event.pointerType !== 'touch' || event.buttons) pointer(event);});
    svg.addEventListener('pointerdown', event => {pointer(event); if (typeof svg.setPointerCapture === 'function') svg.setPointerCapture(event.pointerId);});
    const selected = state.follow ? rows.length - 1 : rows.findIndex(row => row.key === state.selected); inspect(selected < 0 ? rows.length - 1 : selected);
    renderTable(root, data, rows);
  }
  function renderTable(root, data, rows) {
    const disclosure = node('details', 'rtpc-table-details'), summary = node('summary', '', tr('查看对比数据表'));
    summary.dataset.rtpcControl = 'table'; disclosure.open = state.tableOpen; disclosure.append(summary); root.append(disclosure);
    let built = false;
    function buildTable() {
      if (built || !disclosure.open) return; built = true;
      const wrap = node('div', 'rtpc-table-wrap'); wrap.tabIndex = 0; wrap.dataset.rtpcControl = 'table-wrap'; wrap.setAttribute('aria-label', tr('数据表'));
      const table = node('table', 'rtpc-table'), head = node('thead'), header = node('tr'), body = node('tbody');
      table.append(node('caption', '', tr('全部四条曲线的日终及盘中暂估。历史缺口不补成零；盘中保留上次真实暂估及原时间，并标注等待核对。')));
      for (const label of ['时间（北京时间）', '段', '本段本金', '本段归零点', '模拟账户', '上证指数', '创业板指数', (state.account?.strategy==='D0I-BOND-WW'?'D0I-BOND-WW 周线择债模型':'D0模型组合')]) {const th = node('th', '', tr(label)); th.scope = 'col'; header.append(th);}
      head.append(header);
      const segmentMap = new Map(data.segments.map(segment => [segment.id, segment])), pageSize = 100, total = Math.ceil(rows.length / pageSize);
      const controls = node('div', 'rtpc-table-pages'), pageLabel = node('span'); controls.setAttribute('role', 'group'); controls.setAttribute('aria-label', tr('数据表页码'));
      if (state.tablePage === null) state.tablePage = total - 1;
      state.tablePage = Math.max(0, Math.min(total - 1, state.tablePage));
      const previous = button(tr('上一页'), 'table-previous', () => changePage(state.tablePage - 1)), next = button(tr('下一页'), 'table-next', () => changePage(state.tablePage + 1));
      controls.append(previous, pageLabel, next); disclosure.append(controls);
      function changePage(page) {state.tablePage = Math.max(0, Math.min(total - 1, page)); state.tableTop = 0; paintPage(); wrap.scrollTop = 0;}
      function paintPage() {
      previous.disabled = state.tablePage === 0; next.disabled = state.tablePage === total - 1;
      pageLabel.textContent = window.ETF_I18n?.language === 'en' ? `Page ${state.tablePage + 1} of ${total}` : `第 ${state.tablePage + 1} 页，共 ${total} 页`;
      body.replaceChildren();
      for (const row of rows.slice(state.tablePage * pageSize, (state.tablePage + 1) * pageSize)) {
        const segment = segmentMap.get(row.segment_id), lineRow = node('tr'), date = node('th', '', rowLabel(row)); date.scope = 'row';
        lineRow.append(date, node('td', '', String(segment._index + 1)), node('td', '', money(segment._capital)), node('td', '', time(segment._baseline)));
        for (const id of SERIES) {
          const point = row.points[id], cell = node('td');
          if (point) {
            cell.append(node('strong', '', percent(point.return_ratio)), node('span', '', tr('估值') + '：' + money(point._equity)), node('span', '', pointPhase(point)),
              node('span', '', tr('记录时间') + '：' + time(point._at)), node('span', '', tr('报价源时间') + '：' + (point.cash_only === true ? tr('无需持仓报价') : time(point._source))), node('span', '', tr('接收时间') + '：' + time(point._observed)));
          } else cell.textContent = '—';
          lineRow.append(cell);
        }
        body.append(lineRow);
      }
      }
      paintPage();
      table.append(head, body); wrap.append(table); disclosure.append(wrap);
      wrap.scrollTop = state.tableTop; wrap.scrollLeft = state.tableLeft;
      wrap.addEventListener('scroll', () => {if (wrap.isConnected) {state.tableTop = wrap.scrollTop; state.tableLeft = wrap.scrollLeft;}});
    }
    disclosure.addEventListener('toggle', () => {if (disclosure.isConnected) {state.tableOpen = disclosure.open; buildTable();}}); buildTable();
  }

  function stopTimer() {if (state.timer !== null) clearTimeout(state.timer); state.timer = null;}
  function schedule() {
    stopTimer();
    if (state.active && state.current && state.identity && typeof state.load === 'function') state.timer = setTimeout(() => {state.timer = null; refresh();}, 30000);
  }
  function invalidate() {
    state.epoch++; state.pending = null; state.loading = false; stopTimer();
    if (state.deadline !== null) clearTimeout(state.deadline); state.deadline = null;
    if (state.resizeTimer !== null) clearTimeout(state.resizeTimer); state.resizeTimer = null;
  }
  function clearData() {state.data = null; state.loadedAt = null; state.error = null; state.selected = null; state.follow = true; state.tableOpen = false; state.tableTop = 0; state.tableLeft = 0; state.tablePage = null;}
  function refresh() {
    if (!state.root || !state.active || !state.current || !state.identity) return Promise.resolve();
    if (state.pending) return state.pending;
    stopTimer();
    if (typeof state.load !== 'function') {state.error = 'loader'; render(); return Promise.resolve();}
    const epoch = state.epoch, binding = state.identity, account = {...state.account}, loader = state.load;
    let deadline = null;
    state.loading = true; render();
    const pending = Promise.resolve().then(() => {
      if (epoch !== state.epoch || binding !== state.identity || !state.active || !state.current) return null;
      return new Promise((resolve, reject) => {
        deadline = setTimeout(() => reject(new Error('Comparison read timeout')), 25000); state.deadline = deadline;
        Promise.resolve(loader(account.id,account.strategy||'D0')).then(resolve, reject);
      });
    }).then(raw => {
      if (epoch !== state.epoch || binding !== state.identity || !state.active || !state.current) return;
      const result = readComparison(raw, account);
      if (result.status === 'invalid') {state.error = 'invalid'; return;}
      state.data = result.data; state.loadedAt = Date.now(); state.error = null;
    }).catch(() => {
      if (epoch === state.epoch && binding === state.identity && state.active && state.current) state.error = 'read';
    }).finally(() => {
      if (deadline !== null) clearTimeout(deadline);
      if (state.deadline === deadline) state.deadline = null;
      if (epoch !== state.epoch || binding !== state.identity || !state.active || !state.current) return;
      state.pending = null; state.loading = false; render(); schedule();
    });
    state.pending = pending; return pending;
  }
  function init({root, load} = {}) {
    const target = typeof root === 'string' ? document.getElementById(root) : root;
    if (!target || typeof target.replaceChildren !== 'function') return;
    if (state.root && state.root !== target) {invalidate(); state.root.replaceChildren();}
    state.root = target; state.load = typeof load === 'function' ? load : null; render();
    if (state.active && state.current && state.identity) refresh();
  }
  function update(account, {current = true} = {}) {
    const next = identity(account), changed = next !== state.identity;
    if (changed) {invalidate(); clearData(); state.account = next ? {...account} : null; state.identity = next;}
    else if (next) state.account = {...account};
    const wasCurrent = state.current; state.current = !!current && !!next;
    if (!state.current && wasCurrent) invalidate();
    render();
    if (state.active && state.current && (changed || !wasCurrent || !state.data && !state.pending)) refresh();
    else if (state.active && state.current && state.timer === null && !state.pending) schedule();
  }
  function setActive(active) {
    const next = !!active, changed = next !== state.active; state.active = next;
    if (!next) {invalidate(); render(); return;}
    if (changed) {render(); refresh();}
  }
  function reset() {invalidate(); clearData(); state.account = null; state.identity = null; state.current = false; render();}
  document.addEventListener('etf-language-change', () => {if (state.root) render();});
  if (typeof window.addEventListener === 'function') window.addEventListener('resize', () => {
    if (!state.active || !state.current || !state.root) return;
    if (state.resizeTimer !== null) clearTimeout(state.resizeTimer);
    state.resizeTimer = setTimeout(() => {
      state.resizeTimer = null;
      if (state.active && state.current && state.root && chartWidth(state.root) !== state.renderedWidth) render();
    }, 100);
  });
  window.RealtimePaperComparison = {init, update, setActive, refresh, reset};
})();
