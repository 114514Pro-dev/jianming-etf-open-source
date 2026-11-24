(() => {
  'use strict';
  const $=(id)=>document.getElementById(id);
  const state={snapshot:null,history:null,asOf:'',code:'sh512800',limit:252,
    requested:{asOf:'',code:'sh512800',limit:252},filter:'all',sort:'pool',
    dates:[],busy:false,failed:false,sequence:0,controller:null,chart:null,cursor:null};
  const groups={all:'全部板块',both:'两项同时成立',trend_only:'仅趋势资格',relative_only:'仅相对领先',neither:'两项均未成立',unknown:'资料待齐'};
  const numeric=(value)=>typeof value==='number'&&Number.isFinite(value);
  const datePattern=/^\d{4}-\d{2}-\d{2}$/;
  const number=(value,digits=2)=>numeric(value)?value.toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—';
  const percent=(value,digits=2)=>numeric(value)?`${number(value*100,digits)}%`:'—';
  const signedPercent=(value,digits=2)=>numeric(value)?`${value>0?'+':''}${number(value*100,digits)}%`:'—';
  const valueClass=(value)=>!numeric(value)||value===0?'value-zero':value<0?'value-negative':'value-positive';
  const text=(value,fallback='—')=>value===null||value===undefined||value===''?fallback:String(value);
  const clear=(node)=>{while(node.firstChild)node.removeChild(node.firstChild);};
  const el=(tag,content,className)=>{const node=document.createElement(tag);if(content!==undefined)node.textContent=content;if(className)node.className=className;return node;};
  const set=(id,value)=>{$(id).textContent=value;};
  const human=(item)=>typeof item==='string'?item:!item||typeof item!=='object'?String(item??''):item.message||item.note||item.description||item.label||item.title||item.name||JSON.stringify(item);
  function timestamp(value){
    if(!value)return '—';if(typeof value!=='string'||datePattern.test(value))return text(value);
    const d=new Date(value);if(Number.isNaN(d.getTime()))return value;
    return `${new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(d)}（上海时间）`;
  }
  function paragraphs(node,items){clear(node);for(const item of items)node.append(el('p',human(item)));}
  function message(kind,content){const node=$('opRequest');node.className=`message ${kind}`;node.hidden=!content;node.setAttribute('role',kind==='error'?'alert':'status');node.textContent=content;}
  function currentSector(){return state.snapshot?.sectors.find((sector)=>sector.code===state.code)||null;}
  function oldLabel(){return state.failed?'旧结果 · 本次读取失败':state.busy&&state.snapshot?'旧结果 · 正在读取新请求':'';}
  function markRetained(){
    const retained=oldLabel();document.body.classList.toggle('op-stale',Boolean(retained));
    $('opSectorRows').setAttribute('aria-busy',String(state.busy));
    $('opExport').disabled=!state.snapshot;
    if(!state.snapshot)return;
    const f=state.snapshot.freshness;
    const isLastCheck=state.busy||state.failed;
    const current=['current','fresh','up_to_date'].includes(f.status)&&!isLastCheck;
    const historical=f.status==='historical'&&!isLastCheck;
    $('opTimeliness').classList.toggle('is-current',current);
    $('opTimeliness').classList.toggle('is-historical',historical);
    $('opTimeliness').classList.toggle('is-warning',!current&&!historical);
    set('opFreshness',`${isLastCheck?'上次检查 · ':''}${text(f.label,'时效未核验')}`);
    const mode=state.snapshot.mode==='historical'?'历史回看':state.snapshot.runtime?'最新已发布资料':'最新可用冻结资料';
    set('opMode',`${mode}${retained?` · ${retained}`:''}`);
    const count=visibleSectors().length;
    set('opTableState',`${retained?`${retained} / `:''}${state.snapshot.snapshot_date} · 当前显示${count} / ${state.snapshot.sectors.length}只 · ${groups[state.filter]}`);
    const rows=state.history?.rows||[];
    set('opChartDates',`${retained?`${retained} / `:''}${rows.length?`${rows[0].date}—${rows[rows.length-1].date} · ${rows.length}条交易记录`:'暂无可展示的历史窗口'}`);
    const selected=currentSector();
    set('opSelectedState',`${retained?`${retained}；图表仍为`:'正在观察'}${selected?`${selected.name}（${selected.code}）`:'所选板块'}。筛选或排序不会自动切换它。`);
  }
  function updateControls(){
    const shown=state.busy?state.requested:{asOf:state.asOf,code:state.code,limit:state.limit};
    const dateSelect=$('opDate');
    if(shown.asOf&&![...dateSelect.options].some((option)=>option.value===shown.asOf)){
      const option=el('option',shown.asOf);option.value=shown.asOf;dateSelect.append(option);
    }
    dateSelect.value=shown.asOf;
    if([...$('opSelectedCode').options].some((option)=>option.value===shown.code))$('opSelectedCode').value=shown.code;
    for(const button of document.querySelectorAll('[data-window]'))button.setAttribute('aria-pressed',String(Number(button.dataset.window)===shown.limit));
    for(const button of document.querySelectorAll('[data-group]'))button.setAttribute('aria-pressed',String(button.dataset.group===state.filter));
    $('opSort').value=state.sort;
    $('opReload').textContent=state.busy?'正在检查…':'重新检查时效';
  }
  async function fetchJson(url,signal){
    const response=await fetch(window.Research?.url(url)||url,{cache:'no-store',signal,headers:{Accept:'application/json'}});
    if(!response.ok){
      let reason='';try{const body=await response.json();const value=body.error||body.message||body.detail;reason=typeof value==='string'?value.slice(0,240):typeof value?.message==='string'?value.message.slice(0,240):'';}catch{}
      throw new Error(reason?`${reason}（HTTP ${response.status}）`:`资料服务返回 HTTP ${response.status}`);
    }
    return response.json();
  }
  function validateBatch(snapshot,history,requested){
    if(snapshot?.data_version&&history?.data_version&&snapshot.data_version!==history.data_version)throw new Error('读取期间资料版本已改变，快照与曲线不属于同一批；请重新读取');
    if(!snapshot||!datePattern.test(snapshot.snapshot_date||'')||!snapshot.freshness||!snapshot.summary||!snapshot.market_context||!Array.isArray(snapshot.sectors))throw new Error('机会快照字段不完整');
    const codes=snapshot.sectors.map((sector)=>sector?.code);
    if(snapshot.summary.total!==10||codes.length!==10||new Set(codes).size!==10||codes.some((code)=>typeof code!=='string'||!code))throw new Error('固定十ETF研究池明细不完整或重复');
    if(requested.asOf&&snapshot.snapshot_date!==requested.asOf)throw new Error('返回快照日期与所选观察日不一致');
    if(!snapshot.sectors.some((sector)=>sector.code===requested.code))throw new Error('所选ETF不在本次研究池资料中');
    if(!history||history.code!==requested.code||history.snapshot_date!==snapshot.snapshot_date||!Array.isArray(history.rows))throw new Error('所选ETF曲线与快照代码或日期不一致');
    let previous='';
    for(const row of history.rows){
      if(!row||!datePattern.test(row.date||'')||row.date<=previous||row.date>snapshot.snapshot_date)throw new Error('历史日期无法一致核对');
      for(const key of ['etf_normalized','benchmark_normalized'])if(row[key]!==null&&(!numeric(row[key])||row[key]<=0))throw new Error('归一化曲线值不合法');
      previous=row.date;
    }
    if(history.rows.length&&history.rows[history.rows.length-1].date!==snapshot.snapshot_date)throw new Error('历史曲线末日与观察快照不一致');
    if(history.base_date!==null&&history.base_date!==undefined&&(!datePattern.test(history.base_date)||history.base_date>snapshot.snapshot_date))throw new Error('曲线归一起点不合法');
  }
  async function loadView(asOf=state.asOf,code=state.code,limit=state.limit){
    const id=++state.sequence;state.controller?.abort();const controller=new AbortController();state.controller=controller;
    const requested={asOf,code,limit};state.requested=requested;state.busy=true;state.failed=false;
    updateControls();markRetained();
    message('loading',`正在读取${asOf||'最新可用冻结资料'}的板块比较与所选ETF曲线…${state.snapshot?'下方暂保留上次成功读取的完整结果。':''}`);
    const query=new URLSearchParams();if(asOf)query.set('as_of',asOf);
    const chartQuery=new URLSearchParams(query);chartQuery.set('code',code);chartQuery.set('limit',String(limit));
    try{
      const [snapshot,history]=await Promise.all([
        fetchJson(`/api/sector-opportunities${query.size?`?${query}`:''}`,controller.signal),
        fetchJson(`/api/sector-history?${chartQuery}`,controller.signal),
      ]);
      if(id!==state.sequence)return;
      validateBatch(snapshot,history,requested);
      state.snapshot=snapshot;state.history=history;state.asOf=asOf;state.code=code;state.limit=limit;state.busy=false;state.failed=false;
      renderSnapshot();renderTable();renderChart();message('','');
    }catch(error){
      if(id!==state.sequence||error.name==='AbortError')return;
      state.busy=false;state.failed=true;
      message('error',`读取${asOf||'最新资料'}失败：${error.message||'无法连接本机资料服务'}。${state.snapshot?`仍保留${state.snapshot.snapshot_date}的旧快照与旧曲线，本次检查没有成功。`:'尚未载入可用结果，请重新检查。'}`);
    }finally{if(id===state.sequence){updateControls();markRetained();}}
  }
  async function loadDates(){
    try{
      const payload=await fetchJson('/api/dates');
      if(!Array.isArray(payload.dates)||payload.dates.some((value)=>typeof value!=='string'||!datePattern.test(value)))throw new Error('历史日期清单格式不完整');
      state.dates=[...new Set(payload.dates)].sort().reverse();const select=$('opDate');clear(select);
      const latest=el('option','最新可用资料');latest.value='';select.append(latest);
      for(const d of state.dates){const option=el('option',d);option.value=d;select.append(option);}
      $('opDatesError').hidden=true;updateControls();
    }catch(error){set('opDatesError',`历史日期清单未能载入：${error.message}。仍可尝试读取最新资料。`);$('opDatesError').hidden=false;}
  }
  function renderSnapshot(){
    const s=state.snapshot,f=s.freshness;
    set('opSnapshotDate',s.snapshot_date);set('opExpectedDate',text(f.expected_date));
    set('opSourceDates',`${text(f.index_date)} / ${text(f.oldest_sector_date)}`);
    set('opCalendar',`日历核验范围至：${text(f.calendar_verified_until)}`);
    set('opFrozenAt',`指数来源冻结时间：${timestamp(f.source_frozen_at)}`);
    set('opCalculatedAt',`本次计算时间：${timestamp(s.calculated_at)}`);
    const notes=Array.isArray(f.notes)?f.notes:[];
    const displayNotes=s.runtime?notes.filter(v=>human(v)!=='行情日期与计算时间不同；数据包冻结读取，无自动联网更新。'&&!/不会自动|不联网|冻结模式|冻结数据模式/.test(human(v))).concat([`本页使用已发布版本 ${s.data_version?.slice(0,12)||'未知'}；后台另行核对与发布，数据日期不等于检查时间。`]):notes;
    paragraphs($('opFreshnessNotes'),displayNotes.length?displayNotes:['当前为冻结资料模式；时效检查没有下载新行情。']);
    const trend=s.market_context.trend;
    set('opMarketTrend',typeof trend==='object'?text(trend?.label,'未知'):text(trend,'未知'));
    const breadth=s.market_context.breadth;
    set('opMarketBreadth',breadth&&typeof breadth==='object'?`${text(breadth.eligible)}只入选 · 已知${text(breadth.known)} / ${text(breadth.total,10)}`:'未知');
    const warnings=Array.isArray(s.warnings)?s.warnings:[];
    paragraphs($('opWarningsBody'),warnings);set('opWarningsTitle',`资料与证据边界（${warnings.length}项，展开查看）`);$('opWarnings').hidden=!warnings.length;
    for(const node of document.querySelectorAll('[data-count]'))node.textContent=text(node.dataset.count==='all'?s.summary.total:s.summary.groups?.[node.dataset.count]);
    const known=text(s.summary.relative_known),rankKnown=s.summary.ranking_known,total=text(s.summary.total,10);
    set('opRankState',`60日相对指标可用 ${known} / ${total}；${rankKnown===s.summary.total&&rankKnown>0?'完整固定池相对排名已就绪，仅表示本次相对强弱':'完整排名条件未齐，不对剩余板块补排名'}。`);
    const select=$('opSelectedCode');clear(select);
    for(const sector of s.sectors){const option=el('option',`${sector.name} · ${sector.code}`);option.value=sector.code;select.append(option);}
    select.value=state.code;
    renderSelectedMetrics();renderSources(Array.isArray(s.sources)?s.sources:[]);
  }
  function visibleSectors(){
    if(!state.snapshot)return [];
    const original=state.snapshot.sectors;
    const rows=original.map((sector,index)=>({sector,index})).filter(({sector})=>state.filter==='all'||sector.status===state.filter);
    if(state.sort!=='pool'){
      const split=state.sort.lastIndexOf('_'),key=state.sort.slice(0,split),direction=state.sort.slice(split+1)==='desc'?-1:1;
      rows.sort((a,b)=>{
        const av=a.sector[key],bv=b.sector[key],ak=numeric(av),bk=numeric(bv);
        if(!ak&&!bk)return a.index-b.index;if(!ak)return 1;if(!bk)return -1;
        return direction*(av-bv)||a.index-b.index;
      });
    }
    return rows.map(({sector})=>sector);
  }
  function indicatorCell(ready,eligible,extra){
    const cell=el('td');const known=ready===true&&typeof eligible==='boolean';
    cell.append(el('span',!known?'未知':eligible?'资格成立':'资格未成立',`indicator-pill ${!known?'unknown':eligible?'':'inactive'}`));
    if(extra)cell.append(el('small',extra,'table-detail'));return cell;
  }
  function returnCell(value){return el('td',signedPercent(value),`numeric ${valueClass(value)}`);}
  function rankLabel(rank){return numeric(rank)?`相对名次 ${number(rank,Number.isInteger(rank)?0:1)} / 10`:'完整池名次未知';}
  function amountShort(value){if(!numeric(value))return '—';if(value>=1e8)return `${number(value/1e8)}亿元`;if(value>=1e4)return `${number(value/1e4)}万元`;return `${number(value)}元`;}
  function renderTable(){
    const body=$('opSectorRows');clear(body);
    const rows=visibleSectors();
    if(!rows.length){const row=el('tr'),cell=el('td',state.snapshot?'当前分组没有板块。可切回全部；所选ETF曲线仍保持不变。':'等待资料','empty-cell');cell.colSpan=11;row.append(cell);body.append(row);}
    for(const sector of rows){
      const row=el('tr');if(sector.code===state.code)row.className='selected-row';
      const nameCell=el('td'),button=el('button',undefined,'sector-link');button.type='button';button.dataset.code=sector.code;
      button.setAttribute('aria-label',`查看${sector.name}的历史曲线`);button.append(el('span',text(sector.name),'sector-name'),el('span',text(sector.code),'sector-code'));nameCell.append(button);row.append(nameCell);
      row.append(indicatorCell(sector.trix_ready,sector.trix_eligible),indicatorCell(sector.skdj_ready,sector.skdj_eligible,`K ${number(sector.skdj_k)} / D ${number(sector.skdj_d)}`));
      row.append(returnCell(sector.return20),returnCell(sector.return60));
      const relative=returnCell(sector.relative60);relative.append(el('small',rankLabel(sector.relative_rank60),'table-detail'));row.append(relative);
      row.append(el('td',percent(sector.volatility20),'numeric'),el('td',percent(sector.drawdown60),'numeric'));
      const amount=el('td',undefined,'numeric');
      if(numeric(sector.amount20)){const details=el('details',undefined,'amount-detail');details.append(el('summary',amountShort(sector.amount20)),el('p',`人民币 ${number(sector.amount20)} 元 / 日；近20个连续市场日总成交额的日均值，不是资金净流入，也不直接代表可成交容量。`));amount.append(details);}else amount.textContent='—';
      row.append(amount);
      const status=el('td',undefined,'status-description');status.append(el('strong',text(sector.status_label,groups[sector.status]||'未知')));
      if(Array.isArray(sector.reasons)&&sector.reasons.length)status.append(el('small',sector.reasons.map(human).join('；')));
      row.append(status,el('td',text(sector.data_date)));body.append(row);
    }
    const selected=currentSector(),included=rows.some((sector)=>sector.code===state.code);
    set('opFilterScope',`${selected&&!included?`当前图表的${selected.name}不在本次表格筛选中；图表仍保持原选择。`:'分组和排序只改变表格顺序，不会切换已选ETF或日期。'}${state.sort==='relative60_desc'&&state.snapshot?.summary.ranking_known!==10?'当前仅按可用数值调整显示顺序，不生成部分池名次。':''}`);
    updateControls();markRetained();
  }
  function setReturn(id,value){const node=$(id);node.textContent=signedPercent(value);node.className=valueClass(value);}
  function renderSelectedMetrics(){
    const sector=currentSector();
    setReturn('opSelectedReturn20',sector?.return20);setReturn('opSelectedReturn60',sector?.return60);
    setReturn('opBenchmarkReturn60',sector?.benchmark_return60);setReturn('opSelectedRelative60',sector?.relative60);
    set('opEtfLegend',sector?`${sector.name} · ${sector.code}`:'所选ETF');
  }
  function safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}}
  function renderSources(sources){
    const list=$('opSources');clear(list);if(!sources.length){list.append(el('li','本次接口未提供来源清单。'));return;}
    for(const source of sources){
      const li=el('li'),url=safeUrl(typeof source==='string'?source:source?.url||source?.link);
      const title=typeof source==='string'?source:source?.title||source?.name||source?.label||human(source);
      if(url){const link=el('a',title);link.href=url;link.target='_blank';link.rel='noopener noreferrer';li.append(link);}else li.append(el('span',title));
      const detail=source&&typeof source==='object'?(source.description||source.note||source.detail):null;
      if(detail&&human(detail)!==title)li.append(el('span',` — ${human(detail)}`));list.append(li);
    }
  }
  async function loadContract(){
    try{
      const contract=await fetchJson('/api/opportunity-contract');if(!contract.rules||typeof contract.rules!=='object')return;
      const names={etf_economic_series:'ETF经济总回报',action_constraints:'公司行动核验',return20:'20日总回报',return60:'60日总回报',benchmark:'比较基准',relative60:'60日相对表现',volatility20:'20日年化波动',drawdown60:'60日回落',trix:'TRIX状态',skdj:'SKDJ独立状态',missing:'资料缺失处理',ranking:'完整池相对排名',groups:'观察分组',history:'历史曲线'};
      const block=$('opCoreRules');clear(block);block.append(el('h3','核心规则原文'));
      for(const [key,value]of Object.entries(contract.rules))block.append(el('p',`${names[key]||key}：${human(value)}`));block.hidden=false;
    }catch{/* Supplementary rule lookup cannot overwrite the actual snapshot. */}
  }
  const svgNS='http://www.w3.org/2000/svg';
  function svgNode(tag,attrs={},content){const node=document.createElementNS(svgNS,tag);for(const[key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(content!==undefined)node.textContent=content;return node;}
  function renderChart(){
    const svg=$('opChart'),rows=state.history?.rows||[];clear(svg);$('opChartTooltip').hidden=true;state.cursor=null;
    const values=rows.flatMap((row)=>[row.etf_normalized,row.benchmark_normalized]).filter(numeric);
    const history=state.history;
    set('opBaseDate',history?.base_date?`归一起点 ${history.base_date}：ETF经济总回报与全指全收益各自从100开始。含分红理论再投资，不是账户净值或策略净收益。`:'尚无双方共同有效归一起点；不补造曲线。');
    const notes=Array.isArray(history?.notes)?history.notes:[];paragraphs($('opChartNotes'),notes);$('opChartNotes').hidden=!notes.length;
    if(!rows.length||!values.length){svg.setAttribute('hidden','');$('opChartEmpty').hidden=false;set('opChartEmpty','所选区间尚无可展示的归一化数据。资料缺失保留未知。');state.chart=null;markRetained();return;}
    svg.removeAttribute('hidden');$('opChartEmpty').hidden=true;
    const width=Math.max(280,Math.round($('opChartWrap').clientWidth)),height=width<620?270:315;
    const pad={left:46,right:12,top:15,bottom:34},plotW=width-pad.left-pad.right,plotH=height-pad.top-pad.bottom;
    let low=Math.min(...values,100),high=Math.max(...values,100);const cushion=(high-low)*.08||1;low-=cushion;high+=cushion;
    const x=(i)=>pad.left+(rows.length===1?plotW/2:i/(rows.length-1)*plotW),y=(value)=>pad.top+(high-value)/(high-low)*plotH;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('height',String(height));
    svg.append(svgNode('title',{},`${history.name}与中证全指全收益，归一起点为${history.base_date}，各自100。不计交易成本，不是策略净收益。`));
    for(let i=0;i<5;i++){const value=low+(high-low)*i/4,pos=y(value);svg.append(svgNode('line',{x1:pad.left,x2:width-pad.right,y1:pos,y2:pos,class:'chart-grid'}));svg.append(svgNode('text',{x:pad.left-7,y:pos+3,'text-anchor':'end',class:'chart-label'},number(value,0)));}
    svg.append(svgNode('line',{x1:pad.left,x2:width-pad.right,y1:y(100),y2:y(100),class:'normalization-axis'}));
    const ticks=width<620?3:6,used=new Set();
    for(let i=0;i<ticks;i++){const at=Math.round(i/(ticks-1)*(rows.length-1));if(used.has(at))continue;used.add(at);svg.append(svgNode('text',{x:x(at),y:height-12,'text-anchor':i===0?'start':i===ticks-1?'end':'middle',class:'chart-label'},rows[at].date.slice(0,7)));}
    for(const[key,className]of[['etf_normalized','etf'],['benchmark_normalized','benchmark']]){let path='',active=false;rows.forEach((row,i)=>{if(numeric(row[key])){path+=`${active?'L':'M'}${x(i).toFixed(2)},${y(row[key]).toFixed(2)} `;active=true;}else active=false;});svg.append(svgNode('path',{d:path,class:`chart-line ${className}`}));}
    const cross=svgNode('line',{y1:pad.top,y2:height-pad.bottom,class:'chart-crosshair',visibility:'hidden'}),dot=svgNode('circle',{r:3.5,class:'chart-dot',visibility:'hidden'});svg.append(cross,dot);
    state.chart={width,height,pad,x,y,cross,dot};markRetained();
  }
  function inspectChart(index){
    const c=state.chart,rows=state.history?.rows||[];if(!c||!rows.length)return;
    const at=Math.max(0,Math.min(rows.length-1,index)),row=rows[at],pos=c.x(at);state.cursor=at;
    c.cross.setAttribute('x1',pos);c.cross.setAttribute('x2',pos);c.cross.setAttribute('visibility','visible');
    if(numeric(row.etf_normalized)){c.dot.setAttribute('cx',pos);c.dot.setAttribute('cy',c.y(row.etf_normalized));c.dot.setAttribute('visibility','visible');}else c.dot.setAttribute('visibility','hidden');
    const tip=$('opChartTooltip');clear(tip);tip.append(el('strong',row.date));
    for(const[key,label]of[['etf_normalized','ETF归一值'],['benchmark_normalized','全指全收益归一值']]){const p=el('p');p.append(el('span',label),el('span',number(row[key])));tip.append(p);}
    tip.hidden=false;tip.style.left=`${Math.max(4,Math.min(c.width-tip.offsetWidth-4,pos+12))}px`;
    $('opChart').setAttribute('aria-label',`${row.date}，ETF归一值${number(row.etf_normalized)}，全指全收益归一值${number(row.benchmark_normalized)}。`);
  }
  function hideInspection(){$('opChartTooltip').hidden=true;if(state.chart){state.chart.cross.setAttribute('visibility','hidden');state.chart.dot.setAttribute('visibility','hidden');}}
  function exportVisible(){
    if(!state.snapshot)return;
    const payload={export_context:{exported_at:new Date().toISOString(),display_status:oldLabel()||'本次成功读取',selected_code:state.code,window_observations:state.limit,table_filter:state.filter,table_sort:state.sort,
      scope:'快照为完整十ETF池；selected_history为当前所选ETF与基准的图表窗口。筛选和排序仅用于页面显示，不产生新名次。',
      warning:'导出时间不是行情时间；保留当前屏幕最后成功读取的整批结果，不含后续发布的数据或交易指令。'},snapshot:state.snapshot,selected_history:state.history};
    const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),link=el('a');
    link.href=url;link.download=`板块机会_${state.snapshot.snapshot_date}_${state.code}${state.busy||state.failed?'_保留旧结果':''}.json`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  $('opDate').addEventListener('change',(event)=>{const pending=state.busy?state.requested:state;loadView(event.target.value,pending.code,pending.limit);});
  $('opLatest').addEventListener('click',()=>{const pending=state.busy?state.requested:state;loadView('',pending.code,pending.limit);});
  $('opReload').addEventListener('click',()=>{if(!state.dates.length)loadDates();const pending=state.busy?state.requested:state;loadView(pending.asOf,pending.code,pending.limit);});
  $('opExport').addEventListener('click',exportVisible);
  $('opSelectedCode').addEventListener('change',(event)=>{if(!event.target.value)return;const pending=state.busy?state.requested:state;loadView(pending.asOf,event.target.value,pending.limit);});
  $('opSectorRows').addEventListener('click',(event)=>{const button=event.target.closest('button[data-code]');if(!button)return;const pending=state.busy?state.requested:state;loadView(pending.asOf,button.dataset.code,pending.limit);});
  $('opSort').addEventListener('change',(event)=>{state.sort=event.target.value;renderTable();});
  for(const button of document.querySelectorAll('[data-group]'))button.addEventListener('click',()=>{state.filter=button.dataset.group;renderTable();});
  $('opReset').addEventListener('click',()=>{state.filter='all';state.sort='pool';renderTable();});
  for(const button of document.querySelectorAll('[data-window]'))button.addEventListener('click',()=>{const pending=state.busy?state.requested:state;loadView(pending.asOf,pending.code,Number(button.dataset.window));});
  $('opChart').addEventListener('pointermove',(event)=>{if(!state.chart)return;const rect=$('opChart').getBoundingClientRect(),c=state.chart,position=(event.clientX-rect.left)/rect.width*c.width;inspectChart(Math.round((position-c.pad.left)/(c.width-c.pad.left-c.pad.right)*((state.history?.rows.length||1)-1)));});
  $('opChart').addEventListener('pointerleave',hideInspection);$('opChart').addEventListener('blur',hideInspection);
  $('opChart').addEventListener('keydown',(event)=>{if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;event.preventDefault();if(event.key==='Escape'){hideInspection();return;}const last=(state.history?.rows.length||1)-1,current=state.cursor===null?last:state.cursor;inspectChart(event.key==='Home'?0:event.key==='End'?last:current+(event.key==='ArrowRight'?1:-1));});
  let frame=0;if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(state.snapshot)renderChart();});}).observe($('opChartWrap'));
  window.addEventListener('research-data-reload',()=>{loadDates();const pending=state.busy?state.requested:state;loadView(pending.asOf,pending.code,pending.limit);});
  loadDates();loadContract();loadView();
})();
