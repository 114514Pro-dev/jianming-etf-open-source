(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = {
    snapshot: null, history: [], currentAsOf: '', limit: 252,
    requestAsOf: '', requestLimit: 252, sequence: 0, controller: null,
    busy: false, failed: false, dates: [], chart: null, cursor: null,
  };
  const numeric = (v) => typeof v === 'number' && Number.isFinite(v);
  const number = (v, digits = 2) => numeric(v) ? v.toLocaleString('zh-CN', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '—';
  const percent = (v, digits = 1) => numeric(v) ? `${number(v * 100, digits)}%` : '—';
  const signed = (v, digits = 1) => numeric(v) ? `${v > 0 ? '+' : ''}${number(v, digits)}` : '—';
  const text = (v, fallback = '—') => v === null || v === undefined || v === '' ? fallback : String(v);
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  const dateText = (v) => typeof v === 'string' && datePattern.test(v) ? v : text(v);
  const set = (id, value) => { $(id).textContent = value; };
  const clear = (element) => { while (element.firstChild) element.removeChild(element.firstChild); };
  const element = (tag, content, className) => {
    const el = document.createElement(tag);
    if (content !== undefined) el.textContent = content;
    if (className) el.className = className;
    return el;
  };
  function timestamp(v) {
    if (!v) return '—';
    if (typeof v !== 'string' || datePattern.test(v)) return text(v);
    const parsed = new Date(v);
    if (Number.isNaN(parsed.getTime())) return text(v);
    return `${new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}).format(parsed)}（上海时间）`;
  }
  function humanItem(item) {
    if (typeof item === 'string') return item;
    if (!item || typeof item !== 'object') return String(item ?? '');
    return item.message || item.note || item.description || item.label || item.title || item.name || JSON.stringify(item);
  }
  function paragraphs(container, values) {
    clear(container);
    for (const value of values) container.append(element('p', humanItem(value)));
  }
  function showMessage(kind, message) {
    const el = $('requestMessage');
    el.className = `message ${kind}`;
    el.hidden = !message;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    el.textContent = message;
  }
  function visibleStateLabel() {
    return state.failed ? '旧结果 · 本次读取失败' : state.busy && state.snapshot ? '旧结果 · 正在读取新请求' : '';
  }
  function markRetainedContent() {
    document.body.classList.toggle('content-stale', Boolean(state.snapshot && (state.busy || state.failed)));
    $('metrics').setAttribute('aria-busy', String(state.busy));
    const retained = visibleStateLabel();
    if (state.snapshot) {
      const freshness = state.snapshot.freshness;
      const lastCheck = state.busy || state.failed;
      const current = ['fresh','current','up_to_date','historical_current','current_as_of'].includes(freshness.status);
      const historical = freshness.status === 'historical' && !lastCheck;
      set('freshnessLabel', `${lastCheck ? '上次检查 · ' : ''}${text(freshness.label, '时效尚未核验')}`);
      $('timeliness').classList.toggle('is-current', current && !lastCheck);
      $('timeliness').classList.toggle('is-historical', historical);
      $('timeliness').classList.toggle('is-warning', (!current && !historical) || lastCheck);
      const mode = state.snapshot.mode === 'historical' ? '历史回看' : state.snapshot.runtime ? '最新已发布资料' : '最新可用冻结资料';
      set('snapshotMode', retained ? `${mode} · ${retained}` : mode);
      set('tableDate', `${retained ? '旧结果 / ' : ''}${state.snapshot.snapshot_date}`);
      const first = state.history[0]?.date;
      const last = state.history[state.history.length - 1]?.date;
      set('chartDateLabel', `${retained ? `${retained} · ` : ''}${first && last ? `${first}—${last} · ${state.history.length}个交易记录` : '该日暂无可用图表资料'}`);
    }
    $('exportButton').disabled = !state.snapshot;
  }
  function updateControls() {
    const selected = state.busy ? state.requestAsOf : state.currentAsOf;
    if (selected && ![...$('dateSelect').options].some((o) => o.value === selected)) {
      const option = element('option', selected); option.value = selected; $('dateSelect').append(option);
    }
    $('dateSelect').value = selected;
    for (const button of document.querySelectorAll('[data-limit]')) {
      button.setAttribute('aria-pressed', String(Number(button.dataset.limit) === (state.busy ? state.requestLimit : state.limit)));
    }
    $('refreshButton').textContent = state.busy ? '正在检查…' : '重新检查时效';
  }
  async function fetchJson(url, signal) {
    const response = await fetch(window.Research?.url(url) || url, {cache: 'no-store', signal, headers: {'Accept':'application/json'}});
    if (!response.ok) {
      let message = '';
      try {
        const body = await response.json();
        const value = body.error || body.message || body.detail;
        if (typeof value === 'string') message = value.slice(0,240);
        else if (value && typeof value.message === 'string') message = value.message.slice(0,240);
      } catch { /* HTTP status remains usable when the error body is not JSON. */ }
      throw new Error(message ? `${message}（HTTP ${response.status}）` : `资料服务返回 HTTP ${response.status}`);
    }
    return response.json();
  }
  function validSnapshot(snapshot, history, requested) {
    if (!snapshot || typeof snapshot !== 'object' || !datePattern.test(snapshot.snapshot_date || '') ||
        !snapshot.trend || !snapshot.risk || !snapshot.breadth || !snapshot.freshness || !Array.isArray(snapshot.sectors)) {
      throw new Error('快照字段不完整，暂不展示本次资料');
    }
    if (!history || !Array.isArray(history.rows)) throw new Error('历史行情格式不完整');
    if (snapshot.data_version && history.data_version && snapshot.data_version !== history.data_version) throw new Error('读取期间资料版本已改变，快照与曲线不属于同一批；请重新读取');
    if (requested && snapshot.snapshot_date !== requested) throw new Error('快照日期与所选观察日不一致');
    let previous = '';
    for (const row of history.rows) {
      if (!row || !datePattern.test(row.date || '') || row.date > snapshot.snapshot_date || row.date <= previous || !numeric(row.close)) {
        throw new Error('快照与历史行情日期无法一致核对');
      }
      previous = row.date;
    }
    if (history.rows.length && history.rows[history.rows.length - 1].date !== snapshot.snapshot_date) {
      throw new Error('历史曲线末日与快照日期不一致');
    }
  }
  async function loadView(asOf = state.currentAsOf, limit = state.limit) {
    const requestId = ++state.sequence;
    state.controller?.abort();
    const controller = new AbortController();
    state.controller = controller;
    state.requestAsOf = asOf;
    state.requestLimit = limit;
    state.busy = true;
    state.failed = false;
    updateControls(); markRetainedContent();
    showMessage('loading', `正在读取${asOf ? `${asOf}的历史回看资料` : '最新可用冻结资料'}…${state.snapshot ? '下面暂时保留上次成功读取的内容。' : ''}`);
    const query = new URLSearchParams();
    if (asOf) query.set('as_of', asOf);
    const historyQuery = new URLSearchParams(query); historyQuery.set('limit', String(limit));
    try {
      const [snapshot, history] = await Promise.all([
        fetchJson(`/api/market-regime${query.size ? `?${query}` : ''}`, controller.signal),
        fetchJson(`/api/history?${historyQuery}`, controller.signal),
      ]);
      if (requestId !== state.sequence) return;
      validSnapshot(snapshot, history, asOf);
      state.snapshot = snapshot; state.history = history.rows;
      state.currentAsOf = asOf; state.limit = limit; state.busy = false; state.failed = false;
      renderSnapshot(snapshot); renderChart();
      showMessage('', '');
    } catch (error) {
      if (requestId !== state.sequence || error.name === 'AbortError') return;
      state.busy = false; state.failed = true;
      showMessage('error', `本次读取${asOf || '最新资料'}失败：${error.message || '无法连接本机资料服务'}。${state.snapshot ? `保留${state.snapshot.snapshot_date}的旧结果，不能把它当作本次检查成功。` : '还没有成功载入的资料，请重新检查。'}`);
    } finally {
      if (requestId === state.sequence) { updateControls(); markRetainedContent(); }
    }
  }
  async function loadDates() {
    try {
      const result = await fetchJson('/api/dates');
      if (!Array.isArray(result.dates) || result.dates.some((d) => typeof d !== 'string' || !datePattern.test(d))) throw new Error('日期清单格式不完整');
      state.dates = [...new Set(result.dates)].sort().reverse();
      const select = $('dateSelect'); clear(select);
      const latest = element('option', '最新可用资料'); latest.value = ''; select.append(latest);
      for (const d of state.dates) { const option = element('option', d); option.value = d; select.append(option); }
      $('datesError').hidden = true; updateControls();
    } catch (error) {
      $('datesError').textContent = `历史日期清单未能载入：${error.message}。仍可尝试读取最新资料。`;
      $('datesError').hidden = false;
    }
  }
  function renderSnapshot(snapshot) {
    const f = snapshot.freshness;
    const readyStatus = ['fresh','current','up_to_date','historical_current','current_as_of'].includes(f.status);
    $('timeliness').classList.toggle('is-current', readyStatus && !state.failed);
    $('timeliness').classList.toggle('is-warning', !readyStatus);
    set('freshnessLabel', text(f.label, '时效尚未核验'));
    set('snapshotDate', dateText(snapshot.snapshot_date));
    set('expectedDateLabel', '当前应完成日期');
    set('expectedDate', dateText(f.expected_date));
    set('sourceDates', `${dateText(f.index_date)} / ${dateText(f.oldest_sector_date)}`);
    set('calendarUntil', `日历核验范围至：${dateText(f.calendar_verified_until)}`);
    set('frozenAt', `指数来源冻结时间：${timestamp(f.source_frozen_at)}`);
    set('calculatedAt', `本次计算时间：${timestamp(snapshot.calculated_at)}`);
    const notes = Array.isArray(f.notes) ? f.notes : [];
    const displayNotes = snapshot.runtime ? notes.filter(v => humanItem(v) !== '行情日期与计算时间不同；数据包冻结读取，无自动联网更新。' && !/不会自动|不联网|冻结模式|冻结数据模式/.test(humanItem(v))).concat([`本页使用已发布版本 ${snapshot.data_version?.slice(0,12) || '未知'}；后台另行核对与发布，数据日期不等于检查时间。`]) : notes;
    paragraphs($('freshnessNotes'), displayNotes.length ? displayNotes : ['当前为冻结数据模式；即使日历检查未发现缺口，也不代表已联网更新。']);
    const warnings = Array.isArray(snapshot.warnings) ? snapshot.warnings : [];
    paragraphs($('warnings'), warnings); $('warnings').hidden = !warnings.length;
    const t = snapshot.trend;
    set('trendLabel', text(t.label, '资料不足'));
    set('indexClose', number(t.close));
    set('movingAverages', [t.ma20,t.ma60,t.ma120].map((v) => number(v, 1)).join(' / '));
    set('maChange', numeric(t.ma20_change_5) ? `${signed(t.ma20_change_5, 2)}点` : '—');
    const b = snapshot.breadth;
    const total = Number.isInteger(b.total) ? b.total : 10;
    const known = Number.isInteger(b.known) ? b.known : null;
    const complete = known === total && numeric(b.ratio);
    set('breadthValue', complete ? `${text(b.eligible)} / ${total}` : `${text(b.eligible)}只已入选`);
    set('breadthDescription', complete ? `原 TRIX 状态入选 · 参与度 ${percent(b.ratio,0)}` : `已知状态 ${text(known)} / ${total} · 完整参与度待齐`);
    $('breadthFill').style.width = complete ? `${Math.min(100,Math.max(0,b.ratio*100))}%` : '0%';
    set('breadthDelta', numeric(b.delta_count) && numeric(b.delta_pp) ? `${signed(b.delta_count,0)}只 / ${signed(b.delta_pp,1)}个百分点` : '不可完整比较');
    set('breadthPrevious', dateText(b.previous_date));
    const r = snapshot.risk;
    set('volatilityValue', percent(r.volatility20));
    set('volatilityLabel', text(r.volatility_label, '波动资料不足'));
    set('volatilityPercentile', numeric(r.percentile) ? percent(r.percentile,0) : '样本不足 / 未知');
    set('volatilitySamples', numeric(r.percentile_samples) ? `${number(r.percentile_samples,0)}个` : '—');
    set('drawdownValue', percent(r.drawdown60));
    renderSectors(snapshot.sectors);
    renderSources(Array.isArray(snapshot.sources) ? snapshot.sources : []);
  }
  function renderSectors(sectors) {
    const body = $('sectorRows'); clear(body);
    if (!sectors.length) { const row = element('tr'); const cell = element('td','本次没有可展示的板块明细','empty-cell'); cell.colSpan=7; row.append(cell); body.append(row); return; }
    for (const s of sectors) {
      const row = element('tr');
      const name = element('td'); name.append(element('span',text(s.name),'sector-name'),element('span',text(s.code),'sector-code')); row.append(name);
      row.append(element('td',number(s.close,3),'numeric'),element('td',number(s.trix,4),'numeric'),element('td',number(s.signal,4),'numeric'));
      const ready = s.ready === true && typeof s.eligible === 'boolean';
      const status = !ready ? '资料不足 / 未知' : s.eligible ? '指标状态入选' : '指标状态未入选';
      const cell = element('td'); cell.append(element('span',status,`indicator-pill ${!ready ? 'unknown' : s.eligible ? '' : 'inactive'}`)); row.append(cell);
      row.append(element('td',dateText(s.data_date)),element('td',text(s.reason,''),'reason-cell')); body.append(row);
    }
  }
  function safeUrl(value) {
    try { const url = new URL(value); return ['https:','http:'].includes(url.protocol) ? url.href : null; }
    catch { return null; }
  }
  function renderSources(sources) {
    const list = $('sourcesList'); clear(list);
    if (!sources.length) { list.append(element('li','本次接口尚未提供来源清单。')); return; }
    for (const source of sources) {
      const li = element('li');
      const rawUrl = typeof source === 'object' && source ? source.url || source.link : typeof source === 'string' ? source : null;
      const url = safeUrl(rawUrl);
      const title = typeof source === 'string' ? source : text(source?.title || source?.name || source?.label, humanItem(source));
      if (url) { const a = element('a',title); a.href=url; a.target='_blank'; a.rel='noopener noreferrer'; li.append(a); }
      else li.append(element('span',title));
      if (source && typeof source === 'object') {
        const detail = source.note || source.description || source.detail;
        if (detail && detail !== title) li.append(element('span',` — ${humanItem(detail)}`));
      }
      list.append(li);
    }
  }
  const svgNS = 'http://www.w3.org/2000/svg';
  function svgNode(tag, attrs = {}, content) {
    const node = document.createElementNS(svgNS,tag);
    for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,String(value));
    if (content !== undefined) node.textContent = content;
    return node;
  }
  function renderChart() {
    const svg = $('priceChart'), rows = state.history;
    clear(svg); $('chartTooltip').hidden=true; state.cursor=null;
    if (!rows.length) { svg.setAttribute('hidden',''); $('chartEmpty').hidden=false; state.chart=null; return; }
    svg.removeAttribute('hidden'); $('chartEmpty').hidden=true;
    const width = Math.max(280,Math.round($('chartWrap').clientWidth));
    const height = width < 620 ? 260 : 305;
    const pad = {left:51,right:12,top:15,bottom:34};
    const plotW = width-pad.left-pad.right, plotH=height-pad.top-pad.bottom;
    const keys=['close','ma20','ma60','ma120'];
    const values=rows.flatMap((r) => keys.map((k) => r[k])).filter(numeric);
    let low=Math.min(...values), high=Math.max(...values);
    const cushion=(high-low)*.08 || Math.max(Math.abs(high)*.01,1);
    low-=cushion; high+=cushion;
    const x=(i) => pad.left+(rows.length===1 ? plotW/2 : i/(rows.length-1)*plotW);
    const y=(value) => pad.top+(high-value)/(high-low)*plotH;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`); svg.setAttribute('height',String(height));
    svg.append(svgNode('title',{},`中证全指价格指数与均线，${rows[0].date}至${rows[rows.length-1].date}。指数价格，不是策略收益。`));
    for(let i=0;i<5;i++) {
      const value=low+(high-low)*i/4, pos=y(value);
      svg.append(svgNode('line',{x1:pad.left,x2:width-pad.right,y1:pos,y2:pos,class:'chart-grid'}));
      svg.append(svgNode('text',{x:pad.left-7,y:pos+3,'text-anchor':'end',class:'chart-label'},number(value,0)));
    }
    const ticks=width<620 ? 3 : 6;
    const drawn=new Set();
    for(let i=0;i<ticks;i++) {
      const at=Math.round(i/(ticks-1)*(rows.length-1));
      if(drawn.has(at)) continue; drawn.add(at);
      svg.append(svgNode('text',{x:x(at),y:height-12,'text-anchor':i===0?'start':i===ticks-1?'end':'middle',class:'chart-label'},rows[at].date.slice(0,7)));
    }
    for(const key of keys) {
      let path='', active=false;
      rows.forEach((row,i)=>{ if(numeric(row[key])) { path+=`${active?'L':'M'}${x(i).toFixed(2)},${y(row[key]).toFixed(2)} `; active=true; } else active=false; });
      svg.append(svgNode('path',{d:path,class:`chart-line ${key}`}));
    }
    const cross=svgNode('line',{y1:pad.top,y2:height-pad.bottom,class:'chart-crosshair',visibility:'hidden'});
    const dot=svgNode('circle',{r:3.5,class:'chart-dot',visibility:'hidden'});
    svg.append(cross,dot);
    state.chart={width,height,pad,x,y,cross,dot};
    markRetainedContent();
  }
  function inspectChart(index) {
    const c=state.chart;if(!c||!state.history.length)return;
    const at=Math.max(0,Math.min(state.history.length-1,index));
    state.cursor=at;const row=state.history[at],x=c.x(at);
    c.cross.setAttribute('x1',x);c.cross.setAttribute('x2',x);c.cross.setAttribute('visibility','visible');
    c.dot.setAttribute('cx',x);c.dot.setAttribute('cy',c.y(row.close));c.dot.setAttribute('visibility','visible');
    const tooltip=$('chartTooltip'); clear(tooltip); tooltip.append(element('strong',row.date));
    for(const [key,label] of [['close','收盘'],['ma20','MA20'],['ma60','MA60'],['ma120','MA120']]) {
      const p=element('p');p.append(element('span',label),element('span',number(row[key])));tooltip.append(p);
    }
    tooltip.hidden=false;
    const realWidth=tooltip.offsetWidth;
    tooltip.style.left=`${Math.max(4,Math.min(c.width-realWidth-4,x+12))}px`;
    $('priceChart').setAttribute('aria-label',`${row.date}，收盘${number(row.close)}，20日均线${number(row.ma20)}，60日均线${number(row.ma60)}，120日均线${number(row.ma120)}。`);
  }
  function hideInspection() {
    $('chartTooltip').hidden=true;
    if(state.chart) {state.chart.cross.setAttribute('visibility','hidden');state.chart.dot.setAttribute('visibility','hidden');}
  }
  function exportSnapshot() {
    if(!state.snapshot)return;
    const payload={
      export_context:{exported_at:new Date().toISOString(),display_status:visibleStateLabel()||'本次成功读取',
        warning:'导出的是当前屏幕最后成功读取的资料快照。导出时间不是行情时间；后台后续发布不改变这份导出。'},
      snapshot:state.snapshot,
    };
    const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'});
    const url=URL.createObjectURL(blob), a=element('a');
    a.href=url;a.download=`市场环境_${state.snapshot.snapshot_date}${state.failed||state.busy?'_保留旧结果':''}.json`;
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function loadContract() {
    try {
      const contract=await fetchJson('/api/contract');
      if(!contract.rules||typeof contract.rules!=='object')return;
      const names={index:'指数',trend:'趋势规则',breadth:'参与度规则',volatility20:'20日年化波动',volatility_percentile:'历史分位',drawdown60:'60日回落',history:'历史资料边界'};
      const block=$('coreRules');clear(block);block.className='sources-block';block.append(element('h3','核心计算规则'));
      for(const [key,value] of Object.entries(contract.rules))block.append(element('p',`${names[key]||key}：${humanItem(value)}`));
      block.hidden=false;
    } catch { /* Optional details do not invalidate a successfully loaded snapshot. */ }
  }
  $('dateSelect').addEventListener('change',(event)=>loadView(event.target.value,state.busy?state.requestLimit:state.limit));
  $('latestButton').addEventListener('click',()=>loadView('',state.busy?state.requestLimit:state.limit));
  $('refreshButton').addEventListener('click',()=>{ if(!state.dates.length)loadDates();loadView(state.busy?state.requestAsOf:state.currentAsOf,state.busy?state.requestLimit:state.limit); });
  $('exportButton').addEventListener('click',exportSnapshot);
  for(const button of document.querySelectorAll('[data-limit]'))button.addEventListener('click',()=>loadView(state.busy?state.requestAsOf:state.currentAsOf,Number(button.dataset.limit)));
  $('priceChart').addEventListener('pointermove',(event)=>{
    if(!state.chart)return;
    const rect=$('priceChart').getBoundingClientRect(),c=state.chart;
    const point=(event.clientX-rect.left)/rect.width*c.width;
    inspectChart(Math.round((point-c.pad.left)/(c.width-c.pad.left-c.pad.right)*(state.history.length-1)));
  });
  $('priceChart').addEventListener('pointerleave',hideInspection);
  $('priceChart').addEventListener('blur',hideInspection);
  $('priceChart').addEventListener('keydown',(event)=>{
    if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;
    event.preventDefault();
    if(event.key==='Escape'){hideInspection();return;}
    const last=state.history.length-1;
    const current=state.cursor===null?last:state.cursor;
    inspectChart(event.key==='Home'?0:event.key==='End'?last:current+(event.key==='ArrowRight'?1:-1));
  });
  let resizeFrame=0;
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>{
    cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{if(state.snapshot)renderChart();});
  }).observe($('chartWrap'));
  window.addEventListener('research-data-reload',()=>{loadDates();loadView(state.currentAsOf,state.limit);});
  loadDates();loadContract();loadView();
})();
