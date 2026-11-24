'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  // Older cached HTML can load a newer unversioned script on its first visit.
  if(!$('ui-version')||!$('update-page')||!$('deleted-accounts')||!$('page-signals')||!$('page-research')||!$('page-featured')||!$('page-realtime-paper')||!$('more-links')||!$('create-confirm')){
    const fresh=new URL(location.href);fresh.searchParams.set('ui_reload',String(Date.now()));location.replace(fresh.href);return;
  }
  const loadedVersion = $('ui-version')?.content;
  function checkVersion(version) {
    if(loadedVersion && /^[a-f0-9]{20}$/.test(version||'') && version!==loadedVersion)$('update-notice').hidden=false;
  }
  $('update-page').addEventListener('click',()=>location.reload());
  const terminal = new Set(['succeeded', 'failed', 'cancelled', 'interrupted']);
  const accountActionNames = {delete:'删除账户',restore:'恢复已删除账户'};
  const actionNames = {create:'建立账户', advance:'接续模拟', attach:'接入最新日线', compare:'策略比较', switch:'更换后续策略', refresh:'刷新行情', quotes:'更新来源报价',auto_scan:'检查自动模拟账户',auto_advance:'自动接续模拟',reference:'计算参考配置', export:'导出账户', import:'恢复账户', history_export:'导出历史日线', quotes_export:'导出已采集报价',full_backup:'下载完整备份'};
  const statusNames = {queued:'排队中', running:'正在运行', succeeded:'已完成', failed:'未完成', cancelled:'已停止', interrupted:'运行已中断'};
  Object.assign(actionNames,accountActionNames);
  const groupNotes = {
    nasdaq:'纳指100 · 21策略，人民币跨境ETF；收盘确认后推进，期末市值结算。',
    hangseng:'恒生指数 · 21策略；多资产与纯ETF择时需区分，独立记账。',
    hangtech:'恒生科技 · 21策略；小时数据共同区间从2023年起，独立记账。',
    original:'四资产 9 策略 · D/F 支持 2013 起，L 系列最早 2017-08-03。此处账户与其他两组分别保存。',
    top5:'创业板 5 策略 · 使用真实完整 60 分钟 K 线。每个账户固定一种策略，独立保存。',
    seven:'七组合 · 从 2023-01-03 起模拟。A 类各份本金独立复利；B 类按日终信号、次日开盘切换。'
  };
  const state = {csrf:null, authenticated:false, catalog:{groups:[]}, overview:null, group:'original', accountId:null, accountDetail:null,
    accounts:[], comparisons:new Map(), jobs:new Map(), tracked:new Map(), busy:new Map(), attempts:new Map(), poll:null, polling:false,
    page:'overview', accountRequest:0, accountRead:null, accountDetailKey:null, accountDetailRevision:null, listRequest:0, compareSort:{key:'annualized', desc:true}, createPending:false, createJobId:null, createDraft:null, started:false,
    settings:null,settingsAt:0,settingsPoll:null,settingsPolling:false,settingsRequest:0,settingsSaving:false,dataRevision:null,revisionSyncing:false,
    pendingAccountDetail:null,detailTab:'positions',eventPage:0,referenceEdited:false,comparisonViews:new Map(),accountBenchmarks:new Map(),accountBenchmarkViews:new Map(),openJobId:null,jobDetailRequest:0,jobDetailSignature:null,jobDetailLoading:false};

  function el(tag, className, text) { const node=document.createElement(tag); if(className)node.className=className; if(text!==undefined && text!==null)node.textContent=String(text); return node; }
  function originalText(tag,className,text){const n=el(tag,className,text);n.setAttribute('data-i18n-skip','');return n;}
  function replace(node, ...children) { node.replaceChildren(...children.filter(Boolean)); }
  function number(value) { if(value===null || value===undefined || value==='')return null; const x=Number(value); return Number.isFinite(x)?x:null; }
  function money(value, digits=2) { const n=number(value); return n===null?'—':n.toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}); }
  function percent(value) { const n=number(value); return n===null?'不足一年':`${n>0?'+':''}${(n*100).toFixed(2)}%`; }
  function drawdown(value) { const n=number(value); return n===null?'—':`${n?'-':''}${(Math.abs(n)*100).toFixed(2)}%`; }
  function dateText(value) { return value?String(value).replace('T',' ').slice(0,19):'尚无记录'; }
  function groupBy(id) { return state.catalog.groups.find(g=>g.id===id) || state.catalog.groups[0] || {id,name:'策略组',strategies:[]}; }
  function strategyBy(group,code) { return (groupBy(group).strategies||[]).find(s=>s.code===code); }
  function errorMessage(error) { return error instanceof Error?error.message:String(error); }
  function uuid() { if(crypto.randomUUID)return crypto.randomUUID(); const a=crypto.getRandomValues(new Uint8Array(16)); a[6]=(a[6]&15)|64; a[8]=(a[8]&63)|128; const s=Array.from(a,x=>x.toString(16).padStart(2,'0')).join(''); return `${s.slice(0,8)}-${s.slice(8,12)}-${s.slice(12,16)}-${s.slice(16,20)}-${s.slice(20)}`; }
  function canonicalText(node) { return window.ETF_I18n?.sourceText(node)??node.textContent; }
  function showError(error) { $('global-error-text').textContent=errorMessage(error); $('global-error').hidden=false; }
  function toast(text, bad=false) { const n=el('div',`toast${bad?' error':''}`,text); $('toast-region').append(n); setTimeout(()=>n.remove(),6500); }
  function setConnection(ok,text) { $('connection-dot').classList.toggle('offline',!ok); $('connection-text').textContent=text || (ok?'已连接 · 模拟交易':'连接暂不可用'); }
  function button(text,fn,className='button secondary small-button') { const b=el('button',className,text); b.type='button'; b.addEventListener('click',()=>Promise.resolve().then(fn).catch(showError)); return b; }
  function empty(title,text,compact=false) { const n=el('div',`empty-state${compact?' compact':''}`); n.append(el('span','empty-symbol','◈'),el('h3','',title),el('p','',text)); return n; }
  function jsonDetails(title,data) { const d=el('details','raw-details'),pre=el('pre');d.append(el('summary','',title),pre);let loaded=false;d.addEventListener('toggle',()=>{if(d.open&&!loaded){pre.textContent=JSON.stringify(data,null,2);loaded=true;}});return d; }
  function signClass(value) { return number(value)===null?'':number(value)>0?'positive':number(value)<0?'negative':''; }
  function metric(label,value,note='',className='') { const n=el('div','metric'); n.append(el('div','metric-label',label),el('div',`metric-value ${className}`,value)); if(note)n.append(el('div','metric-note',note)); return n; }
  function safeDownload(url) { return typeof url==='string' && /^\/api\/download\/[A-Za-z0-9_-]+(?:\?[^#]*)?$/.test(url)?url:null; }
  function downloadLink(result,text='下载文件') { const url=safeDownload(result?.download_url); if(!url)return null; const a=el('a','button primary small-button',text); a.href=url; a.download=''; return a; }
  function downloadSection(result,fullBackup=false) {
    const section=el('div','download-section'),links=el('div','button-row'),seen=new Set();
    section.append(el('p','small muted',fullBackup?'完整业务备份用于恢复整套应用资料；它不是“导入账户”使用的单账户备份。':'主文件为这次操作的完整导出；账户备份可在对应账户组导入，CSV和报告用于查看。'));
    const main=downloadLink(result,fullBackup?'下载完整业务备份':'下载主文件');if(main){links.append(main);seen.add(result.download_url);}
    for(const file of Array.isArray(result.files)?result.files:[]){const url=safeDownload(file?.download_url);if(!url||seen.has(url))continue;const a=downloadLink(file,file.filename||'附加文件');if(file.filename)a.setAttribute('data-i18n-skip','');a.className='button secondary small-button';links.append(a);seen.add(url);}
    section.append(links);return section;
  }
  function localDownload(value,filename) { const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'}); const url=URL.createObjectURL(blob); const a=el('a'); a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000); }

  let overseasData=null, overseasResearch=null, overseasGroup='nasdaq', overseasLoading=false;
  async function loadOverseas(){
    if(overseasLoading)return;overseasLoading=true;
    try{overseasData=await api('/api/overseas');renderOverseasQuotes();if(!$('overseas-strategy').options.length)configureOverseas();renderOverseasReference();if(!overseasResearch){$('overseas-research-note').textContent='正在读取策略研究摘要…';overseasResearch=await api('/api/overseas/research');}renderOverseasResearch();}
    finally{overseasLoading=false;}
  }
  function overseasMarket(){return overseasData?.markets?.find(m=>m.id===overseasGroup);}
  function configureOverseas(){
    fillStrategies(overseasGroup,'overseas-strategy',overseasGroup==='nasdaq'?'T5WEEK':'B_D7');
    const ref=overseasMarket()?.reference;if(ref){fillStrategies(overseasGroup,'overseas-strategy',ref.strategy);$('overseas-capital').value=String(ref.capital);}
    for(const b of $('overseas-tabs').children)b.classList.toggle('active',b.dataset.group===overseasGroup);
  }
  function renderOverseasQuotes(){
    const root=$('overseas-quotes');replace(root);
    for(const market of overseasData.markets){
      const card=el('div','panel overseas-quote'),q=market.quote;
      card.append(el('span','eyebrow',`${market.symbol.slice(2)} · 人民币场内 ETF`),el('h3','',market.name));
      const price=el('div',`overseas-price ${signClass(q?.change)}`,q?money(q.price,3):'等待报价');price.append(el('small','',q?percent(q.change):''));card.append(price);
      card.append(el('p','small muted',`来源报价：${dateText(q?.quote_at)}`),el('p','small muted',`已确认历史：${market.end}`));
      if(q&&q.day!==new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date()))card.append(el('p','small','来源仍为此前交易日报价'));
      if(market.warning)card.append(el('p','inline-error',market.warning));
      card.append(button(`查看 ${market.name}`,()=>{overseasGroup=market.id;configureOverseas();renderOverseasResearch();renderOverseasReference();},'text-button'));
      root.append(card);
      const catalog=state.catalog.groups.find(g=>g.id===market.id);if(catalog)catalog.end=market.end;
    }
    $('overseas-update-note').textContent=`服务器采集 ${dateText(overseasData.received_at)} · 使用市场总览的后台开关；境内交易时段约30秒检查报价，网页约5秒同步。${overseasData.quote_warning?' 本次更新失败：'+overseasData.quote_warning:''}`;
  }
  function renderOverseasReference(){
    const market=overseasMarket(),ref=market?.reference,target=$('overseas-reference');
    if(ref&&ref.strategy===$('overseas-strategy').value&&number(ref.capital)===number($('overseas-capital').value)){
      renderReference(ref,target);
      if(ref.as_of.slice(0,10)<market.end)target.prepend(el('p','inline-error','参考尚未跟上最新确认日，请重新计算。'));
    }else replace(target,empty('为这个市场计算一份参考','选择策略与独立预算。计算成功后，后台会在新的收盘资料确认后更新。',true));
  }
  function renderOverseasResearch(){
    const market=overseasMarket();if(!market||!overseasResearch)return;
    $('overseas-market-title').textContent=market.name+' · 策略与模拟';
    const all=overseasResearch.markets[market.symbol]||[],variant=$('overseas-variant').value;
    const rows=all.filter(r=>r.variant===variant&&strategyBy(overseasGroup,r.strategy)).sort((a,b)=>(b.metrics.cagr??-Infinity)-(a.metrics.cagr??-Infinity));
    const best=Math.max(...rows.map(r=>r.metrics.cagr??-Infinity)),low=Math.min(...rows.map(r=>r.metrics.max_drawdown));
    const table=makeTable([
      {title:'策略 / 资产范围',render:r=>{const box=el('div');box.append(el('strong','',r.strategy+' '+(strategyBy(overseasGroup,r.strategy)?.label||'').replace(/^\S+\s/, '').replace(/ · 研究.*$/,'')));box.append(el('div','small muted',r.group));if(r.metrics.cagr===best)box.append(el('span','pill','本表年化最高'));if(r.metrics.max_drawdown===low)box.append(el('span','pill neutral','本表回撤最低'));return box;}},
      {title:'年化收益',render:r=>percent(r.metrics.cagr)},
      {title:'最大回撤',render:r=>drawdown(r.metrics.max_drawdown)},
      {title:'累计收益',render:r=>percent(r.metrics.total_return)},
      {title:'佣金 / 元',render:r=>money(r.metrics.fees)},
      {title:'查看与模拟',render:r=>{const box=el('div','button-row');box.append(button('曲线与贡献',()=>{const selectedGroup=overseasGroup;const body=el('div');body.append(el('p','small muted',`${r.start} — ${r.end} · 本金 ¥${money(r.capital)} · ${canonicalText($('overseas-variant').selectedOptions[0])}`));const chart=el('div');chart.append(el('p','small muted','正在读取这条策略的曲线…'));api('/api/overseas/curve?'+new URLSearchParams({group:selectedGroup,strategy:r.strategy,variant:r.variant})).then(curve=>{replace(chart);drawChart(chart,curve,r.capital);}).catch(error=>replace(chart,el('p','inline-error',error.message)));body.append(chart);if(r.attribution)body.append(makeTable([{title:'贡献资产',render:a=>assetName(a.symbol)},{title:'收益贡献 / 元',render:a=>money(a.pnl)},{title:'佣金 / 元',render:a=>money(a.fees)}],r.attribution));else body.append(el('p','small muted','此择时策略仅交易目标ETF与现金。'));body.append(el('p','small muted','收益为研究区间历史结果，不代表未来；黄金、银行等贡献不属于目标ETF收益。'));showDetail(market.name+' · '+r.strategy,body);}),button('建模拟账户',()=>openCreate({group:overseasGroup,strategy:r.strategy,capital:number($('overseas-capital').value)||100000})));return box;}}
    ],rows);replace($('overseas-research-table'),table);
    const bench=all.find(r=>r.strategy==='BENCH'&&r.variant===variant);
    $('overseas-research-note').textContent=`冻结研究：2023-01-03 — ${overseasResearch.as_of}，统一本金10万元、期末市值结算。${bench?'同口径目标ETF买入持有：年化 '+percent(bench.metrics.cagr)+'，最大回撤 '+drawdown(bench.metrics.max_drawdown)+'。':''} 标签只在本市场、本表情景内比较。`;
  }
  for(const [id,name] of [['nasdaq','纳指100'],['hangseng','恒生指数'],['hangtech','恒生科技']]){
    const b=button(name,()=>{overseasGroup=id;configureOverseas();renderOverseasResearch();renderOverseasReference();},'');b.dataset.group=id;$('overseas-tabs').append(b);
  }
  $('overseas-refresh').addEventListener('click',()=>submitJob('refresh',{},$('overseas-refresh')).catch(showError));
  $('overseas-form').addEventListener('submit',e=>{e.preventDefault();submitJob('reference',{group:overseasGroup,strategy:$('overseas-strategy').value,capital:Number($('overseas-capital').value)},e.submitter).catch(showError);});
  $('overseas-strategy').addEventListener('change',renderOverseasReference);$('overseas-capital').addEventListener('input',renderOverseasReference);
  $('overseas-variant').addEventListener('change',renderOverseasResearch);
  $('overseas-new').addEventListener('click',()=>openCreate({group:overseasGroup,strategy:$('overseas-strategy').value,capital:Number($('overseas-capital').value)}));
  $('overseas-accounts').addEventListener('click',()=>{changeAccountGroup(overseasGroup).then(()=>showPage('accounts')).catch(showError);});
  $('overseas-compare').addEventListener('click',()=>{$('compare-group').value=overseasGroup;applyCompareGroup();showPage('compare');});

  async function api(path,{method='GET',body,form=false}={}) {
    const headers={Accept:'application/json'}; if(method!=='GET' && state.csrf)headers['X-CSRF-Token']=state.csrf;
    if(body!==undefined && !form)headers['Content-Type']='application/json';
    let response;
    try { response=await fetch(path,{method,headers,body:body===undefined?undefined:form?body:JSON.stringify(body),credentials:'same-origin',cache:'no-store'}); }
    catch (_) { setConnection(false,'连接中断 · 正在等待恢复'); throw new Error('暂时连接不到服务，请检查网络与服务是否运行。任务提交若未收到确认，可先到任务记录核对。'); }
    checkVersion(response.headers?.get('X-UI-Version'));
    let data; try { data=await response.json(); } catch (problem) {
      const endpoint=String(path).split('?')[0],reason=problem?.name==='SyntaxError'?'响应不是有效的 JSON':'响应正文未能读取';
      throw new Error(`接口 ${endpoint} ${reason}（${response.status}）。请刷新后重试；若刚提交任务，先在任务记录核对。`);
    }
    if(!response.ok) {
      if(response.status===401 && path!=='/api/login')showLogin();
      const detail=typeof data.error==='object'?data.error.message:data.error;
      const message=detail||data.detail||data.message;
      const error=new Error(message?(typeof message==='string'?message:JSON.stringify(message)):`请求未完成（${response.status}）。`);
      error.status=response.status;
      if(typeof data.code==='string')error.code=data.code;
      throw error;
    }
    setConnection(true); return data;
  }

  function showLogin() {
    resetAccountRead();state.accountDetail=null;state.accountDetailKey=null;state.accountDetailRevision=null;
    restoreCleanup?.();navigationKey=null;state.settingsReadOk=false;
    window.RealtimePaper?.setActive(false);
    if(state.authenticated)window.RealtimePaper?.reset?.();
    window.ETFCompanyResearch?.setActive(false);
    state.accountBenchmarks.clear();state.accountBenchmarkViews.clear();
    state.authenticated=false;state.csrf=null;state.started=false;state.polling=false;clearTimeout(state.poll);clearTimeout(state.settingsPoll);state.settingsRequest++;state.settingsPolling=false;state.settings=null;state.dataRevision=null;state.pendingAccountDetail=null;state.referenceEdited=false;
    state.createDraft=null;setCreatePending(false);for(const d of document.querySelectorAll('dialog[open]'))d.close();
    $('app-shell').hidden=true;$('mobile-navigation').hidden=true;$('login-screen').hidden=false;$('initial-loading').hidden=true;
  }
  async function startApp(csrf) {
    state.csrf=csrf;state.authenticated=true;$('login-screen').hidden=true;$('initial-loading').hidden=true;$('app-shell').hidden=false;$('mobile-navigation').hidden=false;
    const paperBase='/api/realtime-paper';
    const paperPath=(path,strategy='D0')=>`${path}${path.includes('?')?'&':'?'}strategy=${encodeURIComponent(strategy)}`;
    const paperWrite=(path,body={},strategy='D0')=>api(paperPath(path,strategy),{method:'POST',body:{...body,idempotency_key:`paper-${uuid()}`}});
    const paperAccount=id=>`${paperBase}/accounts/${encodeURIComponent(id)}`;
    window.RealtimePaper?.init({root:$('page-realtime-paper'),toast,transport:{
      load:strategy=>api(paperPath(paperBase,strategy)),
      loadWechat:strategy=>api(paperPath(paperBase+'/wechat',strategy)),
      saveWechat:(body,strategy)=>api(paperPath(paperBase+'/wechat',strategy),{method:'POST',body}),
      testWechat:(body,strategy)=>api(paperPath(paperBase+'/wechat/test',strategy),{method:'POST',body}),
      comparison:(id,strategy)=>api(paperPath(`${paperBase}/comparison?account_id=${encodeURIComponent(id)}`,strategy)),
      loadEmailDraft:strategy=>api(paperPath(`${paperBase}/email-draft`,strategy)),
      saveEmailDraft:(body,strategy)=>api(paperPath(`${paperBase}/email-draft`,strategy),{method:'POST',body:{recipient:body.recipient,account_id:body.account_id}}),
      create:(body,strategy)=>paperWrite(`${paperBase}/accounts`,body,strategy),
      capital:(id,body,strategy)=>paperWrite(`${paperAccount(id)}/capital`,body,strategy),
      start:(id,strategy)=>paperWrite(`${paperAccount(id)}/start`,{},strategy),
      pause:(id,strategy)=>paperWrite(`${paperAccount(id)}/pause`,{},strategy),
      cancel:(id,orderId,strategy)=>paperWrite(`${paperAccount(id)}/orders/${encodeURIComponent(orderId)}/cancel`,{},strategy)
    }});
    await loadCatalog();state.started=true;showPage(location.hash.slice(1)||'overview');
    await Promise.all([loadOverview().catch(showError),loadAccounts().catch(showError),pollJobs(),pollSettings()]);
  }
  const pageTitles={overview:'市场总览',overseas:'海外专区',featured:'精选策略',signals:'策略信号总览',research:'AI选公司',accounts:'历史回放账户','realtime-paper':'D0 前瞻模拟',compare:'策略比较',tasks:'任务记录'};
  const navigationPositions=new Map();let navigationKey=null,restoreCleanup=null;
  history.scrollRestoration='manual';
  function rememberPosition(){
    if(!navigationKey||restoreCleanup)return;
    const position={x:window.scrollX,y:window.scrollY};navigationPositions.set(navigationKey,position);
    if(history.state?.etfKey===navigationKey)history.replaceState({...history.state,position},'');
  }
  function restorePosition(position){
    restoreCleanup?.();const key=navigationKey,target=position||{x:0,y:0};
    const apply=()=>{if(navigationKey===key)window.scrollTo({left:target.x,top:target.y,behavior:'instant'});};
    const observer=new ResizeObserver(apply),stop=()=>{observer.disconnect();clearTimeout(timer);for(const type of ['wheel','touchstart','keydown','pointerdown'])window.removeEventListener(type,stop);restoreCleanup=null;rememberPosition();};
    const timer=setTimeout(stop,2500);restoreCleanup=stop;
    for(const type of ['wheel','touchstart','keydown','pointerdown'])window.addEventListener(type,stop,{once:true,passive:true});
    observer.observe($('page-'+state.page));apply();requestAnimationFrame(apply);
  }
  window.addEventListener('scroll',rememberPosition,{passive:true});
  window.addEventListener('pagehide',rememberPosition);
  function showPage(page,{fromHistory=false}={}) {
    if(page==='paper')page='realtime-paper';if(!Object.hasOwn(pageTitles,page))page='overview';
    const initial=!navigationKey,same=state.page===page&&!initial;
    if(!fromHistory&&!initial&&same){if($('more-dialog').open)$('more-dialog').close();return;}
    if(!fromHistory)rememberPosition();restoreCleanup?.();
    let entry=history.state;
    if(fromHistory||initial){
      if(!entry?.etfKey||entry.page!==page){entry={etfKey:uuid(),page,position:{x:0,y:0}};history.replaceState(entry,'','#'+page);}
    }else{entry={etfKey:uuid(),page,position:{x:0,y:0}};history.pushState(entry,'','#'+page);}
    navigationKey=entry.etfKey;state.page=page;
    for(const n of document.querySelectorAll('.page'))n.hidden=n.id!==`page-${page}`;
    for(const n of document.querySelectorAll('.nav-item')){const active=n.dataset.page===page;n.classList.toggle('active',active);if(active)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');}
    const moreActive=!['overview','featured','accounts'].includes(page);$('mobile-more').classList.toggle('active',moreActive);$('mobile-more').setAttribute('aria-label',moreActive?'更多，当前：'+pageTitles[page]:'更多功能');
    $('page-title').textContent=pageTitles[page];$('more-location').textContent='当前所在：'+pageTitles[page];
    if($('more-dialog').open)$('more-dialog').close();
    if(page==='overseas')loadOverseas().catch(showError);if(page==='compare')renderComparison();if(page==='tasks')renderTasks();
    if(page==='featured')renderFeatured();if(page==='signals'||page==='featured')loadSignals();
    window.ETFCompanyResearch?.setActive(page==='research');window.RealtimePaper?.setActive(page==='realtime-paper');
    if(!fromHistory&&!initial){$('page-title').tabIndex=-1;$('page-title').focus({preventScroll:true});}
    restorePosition(navigationPositions.get(navigationKey)||entry.position);
  }
  function historyNavigation(){
    if(!state.authenticated)return;const page=location.hash.slice(1)||'overview';
    if(history.state?.etfKey===navigationKey&&state.page===page)return;
    showPage(page,{fromHistory:true});
  }
  function fillSelect(select,items,value,labelFn) {
    const previous=value ?? select.value;replace(select);
    for(const item of items){const option=el('option','',labelFn(item));option.value=item.id??item.code;select.append(option);}
    if(items.some(x=>(x.id??x.code)===previous))select.value=previous;
  }
  function fillStrategies(groupId,selectId,preferred) { fillSelect($(selectId),groupBy(groupId).strategies||[],preferred,s=>s.label||s.name||s.code); }
  async function loadCatalog() {
    const catalog=await api('/api/catalog');if(!Array.isArray(catalog.groups)||!catalog.groups.length)throw new Error('暂时没有可用的策略目录。');state.catalog=catalog;
    if(!catalog.groups.some(g=>g.id===state.group))state.group=catalog.groups[0].id;
    for(const id of ['reference-group','compare-group','create-group'])fillSelect($(id),id==='reference-group'?catalog.groups.filter(g=>!g.overseas):catalog.groups,undefined,g=>g.name||g.id);
    fillStrategies($('reference-group').value,'reference-strategy');fillStrategies($('create-group').value,'create-strategy');
    if(!state.started){applyCompareGroup();if(!state.referenceEdited){if(number(catalog.default_reference_capital)>0)$('reference-capital').value=String(catalog.default_reference_capital);const selected=catalog.default_reference_strategy;if(selected){const group=catalog.groups.find(g=>g.strategies.some(s=>s.code===selected));if(group){$('reference-group').value=group.id;fillStrategies(group.id,'reference-strategy',selected);}}}}renderGroupButtons();
  }
  function renderGroupButtons() {
    replace($('account-groups'));
    for(const g of state.catalog.groups){const b=button(g.name||g.id,()=>changeAccountGroup(g.id),'');b.classList.toggle('active',g.id===state.group);b.setAttribute('aria-pressed',String(g.id===state.group));$('account-groups').append(b);}
    $('account-group-note').textContent=groupNotes[state.group]||'每个模拟账户独立保存。';
  }
  async function changeAccountGroup(group) { if(state.group===group)return;resetAccountRead();state.group=group;state.accountId=null;state.accountDetail=null;state.accountDetailKey=null;state.accountDetailRevision=null;state.pendingAccountDetail=null;state.detailTab='positions';state.eventPage=0;$('account-sync-note').hidden=true;replace($('account-detail'),el('div','panel','正在读取账户及完整记录…'));renderGroupButtons();await loadAccounts(); }
  function applyCompareGroup() { const g=groupBy($('compare-group').value);$('compare-start').value=String(g.start||'2023-01-03').slice(0,10);$('compare-end').value=String(g.end||state.overview?.market?.daily_end||'').slice(0,10);$('compare-rule').textContent=(groupNotes[g.id]||'')+' '+((g.id==='original'||g.overseas)?'期末按持仓市值评价，不强制清仓。':'历史比较采用本组期末清算口径；持续账户不强制清仓。');state.compareSort={key:'annualized',desc:true};renderComparison(); }

  async function loadOverview() { const overview=await api('/api/overview');state.overview=overview;renderOverview(); }
  function renderOverview() {
    const data=state.overview||{}, m=data.market||{};
    if(data.server&&!state.settings)renderScheduler(data.server);
    replace($('market-stats'),metric('已确认收盘日线',dateText(m.daily_end||m.latest_daily||m.latest).slice(0,10),'公共行情库','date-value'),metric('完整 60 分钟柱',dateText(m.hourly_end||m.latest_bar),'未完成柱不计入','date-value'),metric('最近报价采集',dateText(m.quote_received_at||data.received_at),'报价源时间见下表','date-value'),metric('策略与市场','21 + 63','境内21种 · 海外3市场各21种','positive'));
    let quotes=data.quotes||[];if(!Array.isArray(quotes))quotes=Object.entries(quotes).map(([symbol,q])=>({...q,symbol}));
    if(!quotes.length)replace($('quotes-area'),empty('还没有有效报价','点击刷新行情获取最新可用资料。来源失败时不补造价格。',true));
    else replace($('quotes-area'),makeTable([{key:'name',title:'ETF',render:q=>{const n=el('div','asset-name',q.name||q.label||q.symbol||'ETF'),stamp=q.quote_at||q.time;n.append(el('span','subline',q.symbol||q.code||''),el('span','quote-near-time',stamp?`来源 ${dateText(stamp)}`:'来源时间未提供'));return n;}},{key:'price',title:'现价',render:q=>money(q.price,3)},{key:'change',title:'较昨收',render:q=>el('span',signClass(q.change),number(q.change)===null?'—':percent(q.change))},{key:'open',title:'当日开盘',render:q=>q.started===false?'未开盘':money(q.open,3)},{key:'range',title:'当日高 / 低',render:q=>q.started===false?'—':`${money(q.high,3)} / ${money(q.low,3)}`},{key:'quote_at',title:'来源报价时间',render:q=>dateText(q.quote_at||q.time)}],quotes));
    renderQuoteSession();
    replace($('market-warnings'));for(const warning of normalizeNotes(data.warnings))$('market-warnings').append(el('p','',warning));
    $('overview-raw').textContent=JSON.stringify(data,null,2);
    renderAccountWarnings();
    const signals=data.top5_signals?.rows||[];const box=$('confirmed-signals');box.hidden=!signals.length;replace(box);
    if(signals.length){const heading=el('div','panel-heading');heading.append(el('h3','','五策略 · 已确认信号'),el('span','pill neutral','只接受完整 K 线'));box.append(heading,makeTable([{key:'name',title:'策略'},{key:'timeframe',title:'周期'},{key:'signal',title:'已确认信号'},{key:'last_bar',title:'信号柱截至',render:r=>dateText(r.last_bar)},{key:'ready',title:'状态',render:r=>r.ready?'已就绪':'等待预热'},{key:'detail',title:'依据',render:r=>button('查看',()=>{const s=strategyBy('top5',r.id)||{};showDetail(r.name||r.id,el('p','advice-copy',s.description||''),el('pre','json-view',JSON.stringify({...r,parameters:s.parameters},null,2)));})}],signals));}
    followAutomaticReference(data.reference);
  }
  function intervalText(value){const n=number(value);if(n===null)return'按后台计划';return n<60?`每 ${n} 秒`:`每 ${money(n/60,0)} 分钟`;}
  function renderQuoteSession(){const session=state.settings?.market_session||state.overview?.server?.market_session;const quiet=['休市','午间休市','收盘核对'].includes(session);$('quote-session-note').textContent=(session?`${session} · `:'')+(quiet?'休市或收盘核对期间可能沿用最近报价；以每只 ETF 的来源时间为准。':'下方显示来源实际报价时间；交易期间也可能有延迟，不等同于实时成交。');}
  function renderScheduler(settings){
    state.settingsReadOk=true;state.settings=settings;updateCreateReview();state.settingsAt=Date.now();$('auto-refresh').checked=Boolean(settings.auto_refresh);$('auto-simulate').checked=Boolean(settings.auto_simulate);$('auto-refresh').disabled=state.settingsSaving;$('auto-simulate').disabled=state.settingsSaving;
    $('market-session').textContent=settings.market_session||'后台状态';$('refresh-frequency').textContent=`目标间隔：报价 ${intervalText(settings.quote_interval_seconds)} · 确认行情 ${intervalText(settings.history_interval_seconds)}`;
    const a=settings.automation||{};const parts=[a.current_action?`后台正在${actionNames[a.current_action]||a.current_action}`:'后台等待下一轮',`最近自动周期：${dateText(a.last_cycle)}`,`最近策略参考：${dateText(a.last_reference)}`];if(Array.isArray(a.last_accounts))parts.push(`最近核对 ${a.last_accounts.length} 个账户`);else if(typeof a.last_accounts==='number')parts.push(`最近核对 ${a.last_accounts} 个账户`);$('automation-summary').textContent=parts.join(' · ');
    const error=normalizeNotes(a.last_error).join('；');$('automation-error').textContent=error?`后台最近提示：${error}`:'';$('automation-error').hidden=!error;$('automation-details').textContent=JSON.stringify(a,null,2);
    schedulerTick();renderAccountAutomation();renderQuoteSession();
  }
  function schedulerTick(){if(!state.settings)return;const s=state.settings,elapsed=Math.floor((Date.now()-state.settingsAt)/1000);const countdown=(value,kind)=>{const raw=number(value);if(raw===null)return'等待安排';const seconds=Math.max(0,Math.floor(raw-elapsed));return seconds?`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`:s.automation?.current_action?`等待当前任务完成后${kind}`:'即将检查';};$('refresh-countdown').textContent=s.auto_refresh?`报价检查 ${countdown(s.next_refresh_seconds,'采集')}`:'行情与参考自动更新已暂停，仍可手动刷新';$('history-countdown').textContent=s.auto_refresh?`确认行情核对 ${countdown(s.next_history_seconds,'核对')}`:'';}
  function scheduleSettingsPoll(delay=5000){clearTimeout(state.settingsPoll);if(state.authenticated)state.settingsPoll=setTimeout(()=>pollSettings(),delay);}
  async function pollSettings(){
    if(!state.authenticated)return;if(state.settingsPolling||state.settingsSaving){scheduleSettingsPoll();return;}state.settingsPolling=true;const request=++state.settingsRequest;
    try{const settings=await api('/api/settings');if(request!==state.settingsRequest||!state.authenticated)return;renderScheduler(settings);if(settings.revision!=null&&settings.revision!==state.dataRevision)await refreshForRevision(settings.revision);}
    catch(error){state.settingsReadOk=false;updateCreateReview();if(state.authenticated)setConnection(false,'后台状态暂不可用 · 将重试');}
    finally{state.settingsPolling=false;scheduleSettingsPoll();refreshAccountBenchmark();if(['signals','featured'].includes(state.page)&&state.authenticated)loadSignals();}
  }
  async function changeSettings(patch,success){
    if(state.settingsSaving)return;state.settingsSaving=true;state.settingsRequest++;renderAccountAutomation();$('auto-refresh').disabled=true;$('auto-simulate').disabled=true;
    try{const settings=await api('/api/settings',{method:'POST',body:patch});state.settingsSaving=false;renderScheduler(settings);if(success)toast(success);scheduleSettingsPoll(100);return settings;}
    catch(error){state.settingsSaving=false;if(state.settings)renderScheduler(state.settings);state.settingsReadOk=false;updateCreateReview();showError(error);throw error;}
    finally{state.settingsSaving=false;renderAccountAutomation();$('auto-refresh').disabled=!state.settings;$('auto-simulate').disabled=!state.settings;}
  }
  function accountAutoText(group,id){if(!state.settings)return'正在读取自动状态';if((state.settings.paused_accounts||[]).includes(`${group}:${id}`))return'此账户已暂停';if(!state.settings.auto_simulate)return'等待全局自动模拟开启';const rows=state.settings.automation?.last_accounts,candidate=Array.isArray(rows)?rows.find(r=>r.group===group&&r.id===id):null;if(candidate?.can_advance===false&&candidate.reason){if(/尚无晚于账户日期的已确认完整数据|无新数据/.test(candidate.reason))return'自动模拟已开启 · 已跟上确认数据';if(!/^(paused|此账户已暂停)$/i.test(candidate.reason))return`等待核验：${candidate.reason}`;}return'自动模拟已开启';}
  function renderAccountAutomation(){
    const settings=state.settings;$('account-automation-summary').textContent=!settings?'正在读取后台模拟设置…':settings.auto_simulate?'后台自动模拟已开启：未暂停的账户按各自策略已确认周期持续推进，关闭网页仍运行。':'全局自动模拟已暂停：可以手动接续，行情和参考更新由另一个开关控制。';
    for(const node of document.querySelectorAll('[data-account-auto-state]')){const split=node.dataset.accountAutoState.indexOf(':');node.textContent=accountAutoText(node.dataset.accountAutoState.slice(0,split),node.dataset.accountAutoState.slice(split+1));}
    for(const input of document.querySelectorAll('[data-account-auto-key]')){if(!state.settingsSaving)input.checked=!(settings?.paused_accounts||[]).includes(input.dataset.accountAutoKey);input.disabled=!settings||state.settingsSaving;}
    for(const node of document.querySelectorAll('[data-daily-activity]')){if(state.accountDetail)renderDailyActivity(node,state.accountDetail);}
  }
  async function changeAccountAuto(key,allowed){
    if(state.settingsSaving)return;state.settingsSaving=true;state.settingsRequest++;renderAccountAutomation();$('auto-refresh').disabled=true;$('auto-simulate').disabled=true;
    try{const settings=await api('/api/settings',{method:'POST',body:{account_auto:{key,enabled:allowed}}});state.settingsSaving=false;renderScheduler(settings);toast(allowed?'此账户已允许自动模拟；是否运行由全局开关控制。':'此账户已暂停自动模拟，仍可手动接续。');scheduleSettingsPoll(100);}
    catch(error){showError(error);}
    finally{state.settingsSaving=false;if(state.settings)renderScheduler(state.settings);}
  }
  function editingInside(root){const active=document.activeElement;return Boolean(active&&root.contains(active)&&/^(INPUT|SELECT|TEXTAREA)$/.test(active.tagName));}
  function followAutomaticReference(reference){
    if(!reference||typeof reference!=='object')return;const matches=reference.strategy===$('reference-strategy').value&&number(reference.capital)===number($('reference-capital').value);
    if(matches&&!state.referenceEdited&&!editingInside($('reference-form'))){renderReference(reference);$('reference-auto-note').textContent='当前参考正在跟随后台结果；来源与判断时间见下方。';}
    else $('reference-auto-note').textContent='后台参考已更新。当前输入保持不变；点击“计算参考”查看所选策略和预算的结果。';
  }
  function preserveAccountInputs(){const values={};for(const input of $('account-detail').querySelectorAll('[data-preserve]'))if(input.dataset.edited==='1')values[input.dataset.preserve]=input.value;return values;}
  function applyPendingAccountUpdate(force=false){const pending=state.pendingAccountDetail;if(!pending)return;if(pending.group!==state.group||pending.id!==state.accountId){state.pendingAccountDetail=null;$('account-sync-note').hidden=true;return;}if(!force&&editingInside($('account-detail')))return;const values=preserveAccountInputs();state.accountDetail=pending.detail;state.accountDetailKey=JSON.stringify([pending.group,pending.id]);state.pendingAccountDetail=null;renderAccountDetail(values);$('account-sync-note').hidden=true;}
  async function refreshForRevision(revision){
    if(state.revisionSyncing)return;state.revisionSyncing=true;const group=state.group,id=state.accountId,accountRequest=state.accountRequest;
    try{const results=await Promise.allSettled([api('/api/overview'),api(`/api/accounts?group=${encodeURIComponent(group)}`),id?readCurrentAccount(revision):Promise.resolve(true)]);
      if(!state.authenticated)return;const [marketResult,listResult,detailResult]=results;if(marketResult.status==='fulfilled'){state.overview=marketResult.value;renderOverview();}else showError(marketResult.reason);
      if(group===state.group&&listResult.status==='fulfilled'){
        const list=listResult.value;state.accounts=Array.isArray(list)?list:(list.accounts||list.rows||[]);renderAccountList();renderAccountWarnings();
        const removed=id&&id===state.accountId&&accountRequest===state.accountRequest&&!state.accounts.some(a=>a.id===id);
        if(removed){resetAccountRead();state.accountId=null;state.accountDetail=null;state.accountDetailKey=null;state.accountDetailRevision=null;state.pendingAccountDetail=null;$('account-sync-note').hidden=true;if(state.accounts.length)await selectAccount(state.accounts[0].id);else replace($('account-detail'),empty('暂无可用账户','可在“已删除账户”恢复，或新建账户。'));}
        else if(!state.accountId&&state.accounts.length){await selectAccount(state.accounts[0].id);}
      }else if(listResult.status==='rejected')showError(listResult.reason);
      if(state.page==='overseas')await loadOverseas();if(marketResult.status==='fulfilled'&&listResult.status==='fulfilled'&&detailResult.status==='fulfilled'&&detailResult.value&&(!id||state.accountDetailRevision===revision)&&group===state.group&&id===state.accountId&&accountRequest===state.accountRequest)state.dataRevision=revision;
    }finally{state.revisionSyncing=false;}
  }
  function makeTable(columns,rows,{sort}={}) {
    const wrapper=el('div','table-wrap');const table=el('table');const head=el('thead'),tr=el('tr');
    for(const col of columns){const th=el('th');th.scope='col';if(sort){const b=button(col.title+(sort.key===col.key?(sort.desc?' ↓':' ↑'):''),()=>sort.onSort(col.key),'');th.append(b);if(sort.key===col.key)th.setAttribute('aria-sort',sort.desc?'descending':'ascending');}else th.textContent=col.title;tr.append(th);}head.append(tr);table.append(head);
    const tbody=el('tbody');for(const row of rows){const r=el('tr');for(const col of columns){const cell=el('td');const value=col.render?col.render(row):row[col.key];if(value instanceof Node)cell.append(value);else cell.textContent=value===null||value===undefined?'—':String(value);r.append(cell);}tbody.append(r);}table.append(tbody);wrapper.append(table);return wrapper;
  }
  function normalizeNotes(value) { if(!value)return[];if(Array.isArray(value))return value.map(v=>typeof v==='string'?v:JSON.stringify(v));if(typeof value==='object')return Object.entries(value).map(([k,v])=>`${k}：${typeof v==='object'?JSON.stringify(v):v}`);return[String(value)]; }
  function renderReference(result,target=$('reference-result')) {
    replace(target);target.className='';const head=el('div','reference-meta');head.append(el('strong','',result.label||result.name||result.strategy||'策略参考'),el('span','pill neutral',dateText(result.as_of||result.day)));target.append(head);const basis={provisional:'盘中临时参考（最多5分钟重算）',confirmed_daily:'确认收盘参考',confirmed_bars:'完整周期参考'}[result.basis];if(basis)target.append(el('p','reference-basis',basis));const times=[];if(result.computed_at)times.push(`参考计算：${dateText(result.computed_at)}`);if(result.quote_as_of)times.push(`使用报价截至：${dateText(result.quote_as_of)}`);if(times.length)target.append(el('p','small muted',times.join(' · ')));if(number(result.capital)!==null)target.append(el('p','small muted',`本次参考本金 ¥ ${money(result.capital)} · 配置不会改变模拟账户`));
    if(result.available===false){target.append(empty('当前没有可用参考',normalizeNotes(result.notes||result.reason).join('；')||'缺少有效行情，请检查来源日期后重试。',true));return;}
    const weights=result.weights||result.observation?.weights||{},budgets=result.budgets||{};
    for(const [symbol,value] of Object.entries(weights)){const weight=number(value);if(weight===null)continue;const row=el('div','allocation-row');const bar=el('div','allocation-bar');const fill=el('span');fill.style.width=`${Math.max(0,Math.min(100,weight*100))}%`;bar.append(fill);row.append(el('span','',assetName(symbol)),bar,el('span','allocation-weight',`${(weight*100).toFixed(1)}%`),el('span','allocation-money',money(budgets[symbol]??(number(result.capital)===null?null:weight*result.capital))));target.append(row);}
    if(number(result.cash)!==null){const row=el('div','allocation-row');row.append(el('span','','现金'),el('div'),el('span','allocation-weight',number(result.capital)>0?`${(result.cash/result.capital*100).toFixed(1)}%`:'—'),el('span','allocation-money',money(result.cash)));target.append(row);}
    const notes=el('div','notes');for(const note of normalizeNotes(result.notes||result.reason))notes.append(el('p','',note));target.append(notes,jsonDetails('查看完整策略依据',result));
    if(!Object.keys(weights).length)target.append(el('p','muted small','当前结果未提供配置比例，完整依据见上方详情。'));
  }
  function assetName(code) { return ({sh513100:'纳指100 ETF 513100',sz159920:'恒生ETF 159920',sh513180:'恒生科技ETF 513180',sz159915:'创业板 ETF 159915',sh512800:'银行 ETF 512800',sh518880:'黄金 ETF 518880',sh511010:'国债 ETF 511010',cash:'现金'})[code]||code; }

  async function loadAccounts(preferredId) {
    const request=++state.listRequest,group=state.group;const list=await api(`/api/accounts?group=${encodeURIComponent(group)}`);if(request!==state.listRequest||group!==state.group)return;
    state.accounts=Array.isArray(list)?list:(list.accounts||list.rows||[]);const wanted=preferredId||state.accountId;state.accountId=state.accounts.some(a=>a.id===wanted)?wanted:state.accounts[0]?.id||null;
    renderAccountList();if(list.warnings?.length)toast(normalizeNotes(list.warnings).join('；'),true);await loadOverview().catch(showError);if(request!==state.listRequest||group!==state.group)return;
    if(state.accountId)await selectAccount(state.accountId);else{resetAccountRead();state.accountDetail=null;state.accountDetailKey=null;state.accountDetailRevision=null;state.pendingAccountDetail=null;$('account-sync-note').hidden=true;replace($('account-detail'),empty('还没有这一组的模拟账户','点击“新建账户”开始，或导入这个模块的完整备份。'));}
  }
  function renderAccountWarnings(){const target=$('account-warnings');replace(target);const errors=state.overview?.account_warnings?.[state.group]||[];if(errors.length){target.append(el('p','small notes',`已跳过 ${errors.length} 个无法读取的账户，原文件保留。`),button('查看异常文件',()=>showDetail('账户读取异常 · 原文件保留',el('p','muted small','其他正常账户仍可使用。可用有效备份恢复为独立副本。'),el('pre','json-view',JSON.stringify(errors,null,2))),'text-button'));}}
  function confirmDeleteAccount() {
    const group=state.group,id=state.accountId,summary=state.accountDetail?.summary;
    if(!id||!summary)return;
    const body=el('div');body.append((()=>{const p=el('p');p.append(el('span','','确认删除'),originalText('strong','',` “${summary.name||'模拟账户'}”`),el('span','','?'));return p;})(),el('p','small muted',`${groupBy(group).name} · ${summary.strategy_label||summary.strategy||''} · 截至 ${dateText(summary.day)}`),el('p','','账户将移入“已删除账户”，停止后续自动模拟。历史和成交记录保留，可随时恢复。正在执行的任务会先完成。'));
    const row=el('div','button-row');let confirm;
    confirm=button('确认删除',async()=>{const job=await submitJob('delete',{group,id,expected_day:summary.day},confirm);if(job&&body.isConnected)$('detail-dialog').close();},'button danger');
    row.append(button('取消',()=>$('detail-dialog').close()),confirm);body.append(row);showDetail('删除账户',body);
  }
  async function showDeletedAccounts() {
    const group=state.group,body=el('div');showDetail(groupBy(group).name+' · 已删除账户',body);body.append(el('p','muted','正在读取…'));
    const rows=await api('/api/accounts/deleted?group='+encodeURIComponent(group));if(!body.isConnected)return;replace(body);
    body.append(el('p','small muted','这里的账户不会继续模拟。恢复后保留全部历史，并沿用原有自动模拟设置。'));
    if(!rows.length){body.append(empty('没有已删除账户','这个账户组的已删除账户会显示在这里。',true));return;}
    for(const row of rows){const s=row.summary||{},card=el('div','trash-account'),copy=el('div');copy.append(originalText('strong','',s.name||'模拟账户'),el('p','small muted',`${s.strategy_label||s.strategy||''} · 删除于 ${dateText(row.deleted_at)}`),el('p','small',`资产 ¥ ${money(s.equity)} · 截至 ${dateText(s.day)}`));let restore;
      restore=button('恢复账户',async()=>{const job=await submitJob('restore',{group,id:row.id},restore);if(job&&body.isConnected)$('detail-dialog').close();});card.append(copy,restore);body.append(card);}
  }
  function renderAccountList() {
    const list=$('account-list');replace(list);if(!state.accounts.length){list.append(el('p','small muted','暂无账户'));return;}
    for(const a of state.accounts){const b=button('',()=>selectAccount(a.id),'account-card');b.classList.toggle('active',a.id===state.accountId);const auto=el('span','account-auto-state',accountAutoText(state.group,a.id));auto.dataset.accountAutoState=`${state.group}:${a.id}`;b.append(originalText('strong','',a.name||'模拟账户'),el('span','account-strategy',a.strategy_label||a.strategy||''),el('span','account-equity',`¥ ${money(a.equity)}`),el('span','account-date',`截至 ${dateText(a.day||a.last_bar)}`),auto);list.append(b);}
  }
  function resetAccountRead(){clearTimeout(state.accountRead?.timer);state.accountRead=null;state.accountRequest++;}
  function accountReadIsCurrent(read){return state.authenticated&&state.accountRead===read&&read.request===state.accountRequest&&read.group===state.group&&read.id===state.accountId;}
  function renderAccountReadState(read){
    if(!accountReadIsCurrent(read))return;const root=$('account-detail');root.querySelector('[data-account-read-status]')?.remove();
    const retained=state.accountDetail&&state.accountDetailKey===JSON.stringify([read.group,read.id]);
    const box=el('div','panel');box.dataset.accountReadStatus='1';box.setAttribute('role','status');
    box.append(el('h3','',retained?'账户更新暂未完成':'账户暂未能读取'));
    if(retained)box.append(el('p','small muted','已保留上次读取的账户记录，日期以账户标题为准。'));
    if(read.error)box.append(el('p','small',errorMessage(read.error)));
    box.append(el('p','small muted',read.loading?'正在重新读取账户…':read.timer?'稍后将自动重试，也可查看后台任务进度。':'自动重试已暂停，可稍后手动重试。'));
    const actions=el('div','button-row'),retry=button('重试读取',()=>selectAccount(read.id));retry.disabled=read.loading;actions.append(retry,button('查看任务进度',()=>showPage('tasks')));box.append(actions);
    if(retained)root.prepend(box);else replace(root,box);
  }
  function readCurrentAccount(revision){
    // A failed detail keeps its revision pending; settings polling shares this
    // retry state instead of creating another request every five seconds.
    const group=state.group,id=state.accountId;if(!id||!state.authenticated)return Promise.resolve(false);
    if(revision!=null&&state.accountDetailRevision===revision&&(state.accountDetailKey===JSON.stringify([group,id])||state.pendingAccountDetail?.group===group&&state.pendingAccountDetail?.id===id))return Promise.resolve(true);
    let read=state.accountRead;
    if(read&&accountReadIsCurrent(read)){
      if(read.loading)return read.promise;
      if(read.timer||read.error&&read.revision===revision)return Promise.resolve(false);
    }
    read={group,id,request:state.accountRequest,revision,attempt:0,timer:null,loading:false,error:null,promise:null};state.accountRead=read;
    return fetchAccountDetail(read,revision);
  }
  function fetchAccountDetail(read,revision){
    if(!accountReadIsCurrent(read))return Promise.resolve(false);read.loading=true;read.revision=revision;
    if(read.error)renderAccountReadState(read);
    read.promise=(async()=>{
      try{
        const detail=await api(`/api/account?group=${encodeURIComponent(read.group)}&id=${encodeURIComponent(read.id)}`);if(!accountReadIsCurrent(read))return false;
        state.accountDetailRevision=revision;state.accountRead=null;$('account-detail').querySelector('[data-account-read-status]')?.remove();
        state.pendingAccountDetail={group:read.group,id:read.id,detail};
        if(editingInside($('account-detail')))$('account-sync-note').hidden=false;else applyPendingAccountUpdate();return true;
      }catch(error){
        if(!accountReadIsCurrent(read))return false;read.error=error;read.loading=false;
        const retryable=!error.status||error.status===408||error.status===429||error.status>=500,delays=[5000,15000,30000];
        if(retryable&&read.attempt<delays.length){read.timer=setTimeout(()=>{read.timer=null;if(accountReadIsCurrent(read))fetchAccountDetail(read,state.settings?.revision??read.revision);},delays[read.attempt++]);}
        renderAccountReadState(read);return false;
      }finally{read.loading=false;}
    })();return read.promise;
  }
  async function selectAccount(id) {
    if(state.accountRead?.loading&&state.accountRead.group===state.group&&state.accountRead.id===id)return state.accountRead.promise;
    resetAccountRead();if(id!==state.accountId){state.detailTab='positions';state.eventPage=0;}state.accountId=id;state.pendingAccountDetail=null;state.accountDetailRevision=null;$('account-sync-note').hidden=true;renderAccountList();
    if(state.accountDetailKey!==JSON.stringify([state.group,id])){state.accountDetail=null;state.accountDetailKey=null;replace($('account-detail'),el('div','panel','正在读取账户及完整记录…'));}
    else $('account-detail').querySelector('[data-account-read-status]')?.remove();
    return readCurrentAccount(state.settings?.revision);
  }
  function latestFor(group) { if(groupBy(group).overseas)return groupBy(group).end;const m=state.overview?.market||{};if(group==='top5'){const hourly=m.top5_hourly||m.hourly_end||m.latest_bar||groupBy(group).end;if(hourly)return String(hourly).replace(' ','T').slice(0,16);}return String((group==='original'?m.original_daily:m.seven_daily)||m.daily_end||groupBy(group).end||'').slice(0,10); }
  function renderAccountDetail(preserved={}) {
    const d=state.accountDetail;if(!d)return;const s=d.summary||{},m=d.metrics||s;const root=$('account-detail');replace(root);
    const heading=el('div','account-heading');const title=el('div');title.append(originalText('h2','',s.name||'模拟账户'),el('p','',`${s.strategy_label||s.strategy||''} · 账户截至 ${dateText(s.day||s.last_bar)}`));const actions=el('div','button-row');actions.append(button('导出完整账户',()=>submitJob('export',{group:state.group,id:state.accountId})),button('删除账户',confirmDeleteAccount,'button danger small-button'));heading.append(title,actions);root.append(heading);
    const annualized=m.annualized??m.cagr??s.annualized;
    const metrics=el('div','metric-grid account-metrics');metrics.append(metric('账户总资产 / 元',money(m.equity??m.final_equity??s.equity)),metric('累计收益',percent(m.return??m.total_return??s.return),'',signClass(m.return??m.total_return??s.return)),metric('年化收益',percent(annualized),'按账户历史区间复利折算',signClass(annualized)),metric('最大回撤',drawdown(m.drawdown??m.max_drawdown??s.drawdown)),metric('可用现金 / 元',money(m.cash??s.cash)));root.append(metrics,el('p','account-summary-note',`累计佣金 ¥ ${money(m.fees??s.fees)} · ${m.trade_unit||s.trade_unit||'交易记录'} ${money(m.trades??s.trades,0)}`));
    const daily=el('section','panel daily-activity');daily.dataset.dailyActivity='1';daily.setAttribute('aria-label','当日操作与原因');root.append(daily);renderDailyActivity(daily,d);
    const autoBox=el('div','account-auto-control'),autoLabel=el('label','automation-switch'),autoInput=el('input');autoInput.type='checkbox';autoInput.dataset.accountAutoKey=`${state.group}:${state.accountId}`;autoInput.addEventListener('change',()=>changeAccountAuto(autoInput.dataset.accountAutoKey,autoInput.checked));const autoCopy=el('span'),autoStatus=el('small','',accountAutoText(state.group,state.accountId));autoStatus.dataset.accountAutoState=autoInput.dataset.accountAutoKey;autoCopy.append(el('strong','','允许此账户自动模拟'),autoStatus);autoLabel.append(autoInput,autoCopy);autoBox.append(autoLabel,el('p','small muted','暂停只影响此账户的后续自动推进，已保存记录保留；仍可手动接续。'));root.append(autoBox);
    const actionBox=el('div','account-actions'),form=el('form','form-row'),label=el('label','','手动模拟至');const end=el('input');end.type=state.group==='top5'?'datetime-local':'date';end.required=true;end.value=latestFor(state.group);end.dataset.preserve='advance-end';end.addEventListener('input',()=>{end.dataset.edited='1';});end.addEventListener('change',()=>{end.dataset.edited='1';});end.setAttribute('aria-label','账户模拟终点');label.append(end);form.append(label);form.append(button('使用最新数据',()=>{end.value=latestFor(state.group);delete end.dataset.edited;},'button secondary small-button'));const advance=el('button','button primary','接续模拟');advance.type='submit';form.append(advance);form.addEventListener('submit',e=>{e.preventDefault();submitJob('advance',{group:state.group,id:state.accountId,end:end.value.replace('T',' '),expected_day:s.day},advance).catch(showError);});actionBox.append(form,el('p','small muted','手动接续和后台自动推进均按策略原规则产生模拟记录；重复同一终点不会重复交易。'));if(state.group==='original'){actionBox.append(button('接入最新已确认日线',()=>submitJob('attach',{group:'original',id:state.accountId,expected_day:s.day}),'text-button'),el('p','small muted',`账户行情至 ${dateText(s.market_end).slice(0,10)} · 后台自动运行也会核对可接入的已确认日线。`));}root.append(actionBox);
    const chartPanel=el('div','panel account-benchmark');root.append(chartPanel);mountAccountBenchmark(chartPanel,d);
    const detailPanel=el('div','panel'),tabs=el('div','detail-tabs'),body=el('div');const views=[['positions','持仓'],['events','成交与记录'],['advice','策略依据']];
    const render=(key)=>{state.detailTab=key;for(const b of tabs.children)b.classList.toggle('active',b.dataset.key===key);replace(body);if(key==='positions')renderPositions(body,d.positions||[]);else if(key==='events')renderEvents(body,d.events||[]);else renderAdvice(body,d.advice||{});};
    for(const [key,labelText] of views){const b=button(labelText,()=>render(key),'');b.dataset.key=key;tabs.append(b);}detailPanel.append(tabs,body);root.append(detailPanel);render(state.detailTab);
    if(state.group==='original'){const panel=el('div','panel');panel.append(el('h3','','更换后续策略'),el('p','small muted','已发生的持仓、成交和曲线保留，新策略只影响后续判断。'));const f=el('form','form-row'),l=el('label','grow','后续策略'),select=el('select');fillSelect(select,groupBy('original').strategies,s.strategy,x=>x.label||x.code);select.dataset.preserve='next-strategy';select.addEventListener('change',()=>{select.dataset.edited='1';});l.append(select);const b=el('button','button secondary','更换后续策略');b.type='submit';f.append(l,b);f.addEventListener('submit',e=>{e.preventDefault();submitJob('switch',{group:'original',id:state.accountId,strategy:select.value,expected_day:s.day},b).catch(showError);});panel.append(f);root.append(panel);}
    root.append(jsonDetails('查看完整账户资料',d));for(const input of root.querySelectorAll('[data-preserve]')){if(Object.hasOwn(preserved,input.dataset.preserve)){input.value=preserved[input.dataset.preserve];input.dataset.edited='1';}}renderAccountAutomation();
  }
  function renderPositions(target,positions) { let rows=positions;if(!Array.isArray(rows))rows=Object.entries(rows).map(([symbol,v])=>typeof v==='object'?{...v,symbol}:{symbol,qty:v});if(!rows.length){target.append(empty('当前没有持仓','资金以现金状态保留，下一步依据见“策略依据”。',true));return;}target.append(makeTable([{key:'name',title:'资产',render:r=>r.name||assetName(r.symbol||r.code||'—')},{key:'qty',title:'持有份数',render:r=>money(r.qty??r.quantity??r.shares,0)},{key:'price',title:'评价价格',render:r=>money(r.price,4)},{key:'market_value',title:'持仓市值 / 元',render:r=>money(r.market_value??r.value)}],rows)); }
  function eventFields(row){
    const sources=[row,row.data,row.native?.data,row.native].filter(value=>value&&typeof value==='object');
    const pick=(...keys)=>{for(const source of sources)for(const key of keys){const value=source[key];if(value!==null&&value!==undefined&&value!=='')return value;}return null;};
    const originalSide=pick('side','direction');const knownSide=value=>({BUY:'买入',SELL:'卖出','买入':'买入','卖出':'卖出','买':'买入','卖':'卖出'})[String(value).toUpperCase()];
    const kind=pick('type','kind')||'记录';const side=originalSide===null?(knownSide(kind)||null):(knownSide(originalSide)||String(originalSide));
    const symbol=pick('symbol','code'),name=pick('asset_name','asset');
    return{time:pick('time','day','datetime','date'),kind,side,symbol,asset:name?(symbol?`${name} · ${symbol}`:String(name)):(symbol?assetName(symbol):null),qty:pick('qty','quantity'),price:pick('price'),fee:pick('fee'),cashChange:pick('cash_change'),signalDay:pick('signal_day','signal'),barTime:pick('bar_time'),leg:pick('leg'),reason:pick('reason','reasons','action','note')};
  }
  function directionBadge(side){return el('span',`trade-direction ${side==='买入'?'trade-buy':side==='卖出'?'trade-sell':'trade-neutral'}`,side||'—');}
  function chinaDay(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
  function dailyAccountView(detail,today=chinaDay()){
    const cutoff=String(detail.summary?.day||''),day=cutoff.slice(0,10);
    const trades=(detail.events||[]).map(raw=>({raw,...eventFields(raw)})).filter(e=>['买入','卖出'].includes(e.side)&&number(e.qty)>0&&number(e.price)>0).sort((a,b)=>String(b.time||'').localeCompare(String(a.time||'')));
    const fills=trades.filter(e=>String(e.time||'').slice(0,10)===today);
    return{today,cutoff,current:day===today,future:day>today,fills,last:trades.find(e=>String(e.time||'').slice(0,10)<today),buys:fills.filter(e=>e.side==='买入').length,sells:fills.filter(e=>e.side==='卖出').length};
  }
  function renderDailyActivity(root,detail){
    const v=dailyAccountView(detail),decision=detail.decision||{},group=detail.group||state.group,id=detail.id||state.accountId;
    // Settings polling also handles a midnight rollover without a ledger write.
    // Do not replace focused controls on an unchanged five-second poll.
    const key=JSON.stringify([v.today,detail.summary?.day,detail.events?.length,decision,state.settings?.auto_simulate,state.settings?.paused_accounts,accountAutoText(group,id)]);
    if(root.dataset.activityRevision===key)return;root.dataset.activityRevision=key;replace(root);
    const heading=el('div','daily-heading');heading.append(el('h3','','当日操作与原因'),el('span','small muted',`${v.today} · 北京时间`));root.append(heading);
    root.append(el('p','daily-summary',v.fills.length?`今日已记录 ${v.fills.length} 笔模拟成交：买入 ${v.buys} 笔，卖出 ${v.sells} 笔。`:v.current?'截至账户确认时点，今日暂无模拟成交。':'今天尚未记录模拟成交。'));
    root.append(el('p','small '+(v.current?'muted':'warning-text'),v.current?`账户确认至 ${dateText(v.cutoff)}；此后操作等待后续完整数据。`:v.future?`账户截至 ${dateText(v.cutoff)}，晚于今天；下方判断属于该历史模拟终点，不能作为今天的判断。`:`账户仅确认至 ${dateText(v.cutoff)}；尚未覆盖今天，不能据此认定今天应买卖或继续持有。`));
    const tradeRow=(e)=>{const row=el('div','daily-trade'),line=el('div','daily-trade-heading');line.append(directionBadge(e.side),el('strong','',e.asset||'账户资产'),el('span','small muted',dateText(e.time)));row.append(line,el('p','small',`${money(e.qty,0)} 份 · 成交价 ¥ ${money(e.price,4)} · 佣金 ¥ ${money(e.fee)}`));const reason=normalizeNotes(e.reason);row.append(el('p','advice-copy',reason.length?'成交原因：'+reason.join('；'):'原记录未保存更细的成交原因；不以当前信号反推当时原因。'));if(e.signalDay)row.append(el('p','small muted',`依据的信号时点：${dateText(e.signalDay)}`));row.append(button('查看成交详情',()=>showDetail('模拟成交与依据',eventDetail(e.raw)),'text-button'));return row;};
    for(const fill of v.fills.slice(0,6))root.append(tradeRow(fill));
    if(v.fills.length>6)root.append(button(`查看今日全部 ${v.fills.length} 笔成交`,()=>{const body=el('div');renderEvents(body,v.fills.map(e=>e.raw));showDetail('今日模拟成交',body);},'button secondary small-button'));
    const judgment=el('div','daily-decision');judgment.append(el('h4','',`${v.current?'当前':'最近确认'}判断：${decision.title||detail.advice?.title||'暂无判断'}`),el('p','small muted',`依据截至 ${dateText(decision.as_of||v.cutoff)}${decision.signal_time?' · 策略信号周期 '+dateText(decision.signal_time):''}`));
    for(const reason of normalizeNotes(decision.reasons?.length?decision.reasons:[detail.advice?.text||'该账户没有保存更细的策略解释。']))judgment.append(el('p','advice-copy',reason));
    if(decision.rule)judgment.append(el('p','small muted',`策略规则：${decision.rule}`));
    if(decision.evidence){const evidence=el('details','daily-previous');evidence.append(el('summary','','查看具体指标依据'),el('p','advice-copy',decision.evidence));judgment.append(evidence);}
    if(decision.weights&&Object.keys(decision.weights).length){const targets=Object.entries(decision.weights).map(([symbol,weight])=>`${assetName(symbol)} ${money(Number(weight)*100,1)}%`);const cash=Math.max(0,1-Object.values(decision.weights).reduce((sum,w)=>sum+Number(w),0));judgment.append(el('p','small',`确认信号的参考目标：${targets.join(' · ')} · 现金 ${money(cash*100,1)}%。参考目标尚不等于成交仓位。`));}
    if(decision.execution)judgment.append(el('p','advice-copy',`后续执行：${decision.execution}`));
    const paused=state.settings?.paused_accounts?.includes(`${group}:${id}`)||state.settings?.auto_simulate===false;
    judgment.append(el('p',paused?'warning-text small':'small muted',`${accountAutoText(group,id)}。${paused?'后续计划不会自动成交，仍可手动接续。':'后台只有在已确认行情及执行条件满足后才记入模拟成交。'}`));root.append(judgment);
    if(!v.fills.length&&v.last){const history=el('details','daily-previous');history.append(el('summary','','最近一次成交（非今日）'),tradeRow(v.last));root.append(history);}
  }
  function eventDetail(row){
    const data=eventFields(row),body=el('div','event-detail'),summary=el('div','event-detail-heading');summary.append(directionBadge(data.side),el('strong','',data.asset||data.kind));body.append(summary);
    const fields=el('dl','event-fields'),add=(label,value)=>{const item=el('div');item.append(el('dt','',label),el('dd','',value===null||value===undefined||value===''?'—':value));fields.append(item);};
    add('发生时间',data.time?dateText(data.time):null);add('记录类型',data.kind);add('买卖方向',data.side);add('资产',data.asset);add('份数',money(data.qty,0));add('成交价 / 元',money(data.price,6));add('佣金 / 元',money(data.fee));const cash=number(data.cashChange);add('资金变化 / 元',cash===null?null:`${cash>0?'+':''}${money(cash)}`);add('信号日 / 时刻',data.signalDay?dateText(data.signalDay):null);if(data.barTime)add('对应完整 K 线',dateText(data.barTime));if(data.leg)add('组合分项',String(data.leg));body.append(fields,el('h3','','触发依据'));
    const reasons=normalizeNotes(data.reason);body.append(el('p','advice-copy',reasons.length?reasons.join('\n'):'这条记录未提供文字依据。'),el('p','small muted','“—”表示本条记录未提供该字段。资金变化和信号时间仅展示保存值，不用成交价或其他时间推算。'),jsonDetails('查看原始返回记录',row));return body;
  }
  function renderEvents(target,events) {
    if(!Array.isArray(events)||!events.length){target.append(empty('还没有成交与事件','接续模拟后，完整交易与触发依据会保留在这里。',true));return;}
    const rows=events.map(raw=>({raw,...eventFields(raw)})).sort((a,b)=>String(b.time||'').localeCompare(String(a.time||'')));const size=100;let page=Math.min(state.eventPage,Math.max(0,Math.ceil(rows.length/size)-1));
    const draw=()=>{
      replace(target);target.append(el('p','small muted',`共 ${events.length.toLocaleString('zh-CN')} 条记录 · 最新在前 · 每页 ${size} 条。完整内容随账户备份导出。`));
      target.append(makeTable([{key:'time',title:'发生时间',render:r=>r.time?dateText(r.time):'—'},{key:'side',title:'方向',render:r=>directionBadge(r.side)},{key:'kind',title:'类型'},{key:'asset',title:'资产'},{key:'qty',title:'份数',render:r=>money(r.qty,0)},{key:'price',title:'成交价',render:r=>money(r.price,4)},{key:'fee',title:'佣金',render:r=>money(r.fee)},{key:'detail',title:'依据',render:r=>button('查看',()=>showDetail(`${r.time?dateText(r.time)+' · ':''}${r.side||r.kind}`,eventDetail(r.raw)))}],rows.slice(page*size,(page+1)*size)));
      const controls=el('div','pagination');const prev=button('上一页',()=>{page--;state.eventPage=page;draw();}),next=button('下一页',()=>{page++;state.eventPage=page;draw();});prev.disabled=page===0;next.disabled=(page+1)*size>=rows.length;controls.append(prev,el('span','small muted',`${page+1} / ${Math.ceil(rows.length/size)} 页`),next);target.append(controls);
    };draw();
  }
  function renderAdvice(target,advice) { if(typeof advice==='string'){target.append(el('div','advice-copy',advice));return;}target.append(el('h3','',advice.title||'当前策略依据'));if(advice.text)target.append(el('div','advice-copy',advice.text));for(const n of normalizeNotes(advice.notes))target.append(el('p','small muted',n));if(advice.weights)target.append(jsonDetails('目标仓位',advice.weights));if(advice.pending)target.append(jsonDetails('待执行信号',advice.pending));if(!advice.text&&!advice.notes&&!advice.weights)target.append(el('p','muted','当前没有新的执行依据。')); }
  function drawChart(target,curve,capital,mode='asset') {
    const rows=curve.map(r=>({date:r.date||r.day||r.datetime,equity:number(r.equity)})).filter(r=>r.date&&r.equity!==null);if(!rows.length){target.append(empty('尚无资产曲线','接续模拟后显示每日或逐柱资产。',true));return;}
    if(mode==='drawdown'){let peak=number(capital)||rows[0].equity;for(const row of rows){peak=Math.max(peak,row.equity);row.equity=peak>0?(row.equity/peak-1)*100:0;}}
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 820 265');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${mode==='drawdown'?'距高点回撤':'资产'}曲线，${dateText(rows[0].date)}至${dateText(rows.at(-1).date)}，期末${money(rows.at(-1).equity)}${mode==='drawdown'?'%':'元'}`);
    const values=rows.map(r=>r.equity);if(mode==='drawdown')values.push(0);else if(number(capital)!==null)values.push(number(capital));let min=Math.min(...values),max=Math.max(...values);const pad=Math.max((max-min)*.12,Math.abs(max)*.005,mode==='drawdown'?.1:1);min-=pad;max+=pad;
    const x=i=>65+i/Math.max(1,rows.length-1)*735,y=v=>220-(v-min)/(max-min)*190;
    function node(tag,attrs,text){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=String(text);svg.append(n);return n;}
    for(let i=0;i<4;i++){const v=min+(max-min)*i/3,yy=y(v);node('line',{x1:65,x2:800,y1:yy,y2:yy,class:'chart-grid'});node('text',{x:55,y:yy+4,'text-anchor':'end',class:'chart-label'},mode==='drawdown'?`${v.toFixed(1)}%`:`${(v/10000).toFixed(1)}万`);}
    const stride=Math.max(1,Math.floor(rows.length/800));const points=rows.map((r,i)=>({r,i})).filter((v,i)=>i%stride===0||i===rows.length-1);const path=points.map(({r,i},j)=>`${j?'L':'M'} ${x(i)} ${y(r.equity)}`).join(' ');
    node('path',{d:`${path} L ${x(rows.length-1)} 220 L 65 220 Z`,class:'chart-fill'});node('path',{d:path,class:'chart-path'});
    if(rows.length===1)node('circle',{cx:x(0),cy:y(rows[0].equity),r:4,fill:'#6de1c2'});
    node('text',{x:65,y:249,class:'chart-label'},String(rows[0].date).slice(0,10));node('text',{x:800,y:249,'text-anchor':'end',class:'chart-label'},String(rows.at(-1).date).slice(0,10));target.append(svg);
    const note=el('div','chart-note');note.append(el('span','',`${rows.length.toLocaleString('zh-CN')} 个实际记录点`),el('span','',mode==='drawdown'?`期末距高点 ${rows.at(-1).equity.toFixed(2)}%`:`期末 ¥ ${money(rows.at(-1).equity)}`));target.append(note);
  }

  // BEGIN_ACCOUNT_BENCHMARK_UI
  function accountBenchmarkKey(detail) {
    const s=detail?.summary||{};
    // Include every recorded value so same-date account corrections invalidate the cache.
    return JSON.stringify([state.group,state.accountId,s.capital,s.start,s.day,s.last_bar,s.equity,detail?.curve||[]]);
  }
  function benchmarkPercent(value) {const n=number(value);return n===null?'—':`${n>0?'+':''}${(n*100).toFixed(2)}%`;}
  function benchmarkPoints(value) {const n=number(value);return n===null?'—':`${n>0?'+':''}${(n*100).toFixed(2)}`;}
  function benchmarkCaption(label,value) {const line=el('p','small muted benchmark-caption');line.append(el('span','',label),el('span','',value));return line;}
  function benchmarkRows(result) {
    const left=result?.account_curve,right=result?.benchmark_curve;
    if(!Array.isArray(left)||!Array.isArray(right)||!left.length||left.length!==right.length)return null;
    const rows=[];let previous='';
    for(let i=0;i<left.length;i++) {
      const date=left[i]?.date,a=number(left[i]?.equity),b=number(right[i]?.equity);
      if(typeof date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(date)||date!==right[i]?.date||date<=previous||a===null||b===null)return null;
      const time=Date.parse(date+'T00:00:00Z');if(!Number.isFinite(time)||new Date(time).toISOString().slice(0,10)!==date)return null;
      rows.push({date,account:a,benchmark:b});previous=date;
    }
    return rows;
  }
  function benchmarkIndices(result) {
    return (Array.isArray(result?.index_benchmarks)?result.index_benchmarks:[]).filter(r=>r&&typeof r==='object').map((result,i)=>({
      result,rows:result.status==='ok'?benchmarkRows(result):null,
      css:result.symbol==='sz399006'?'chinext':result.symbol==='sh000001'?'sse':i%2?'sse':'chinext'
    }));
  }
  function benchmarkChartModel(result) {
    const base=result?.status==='ok'?benchmarkRows(result):null,indices=benchmarkIndices(result);
    const available=indices.filter(r=>r.rows&&number(r.result.capital)>0);
    // An independent index can still be viewed when the ETF service is unavailable.
    const anchor=base?{rows:base,capital:result.capital}:available.sort((a,b)=>b.rows.length-a.rows.length)[0];
    if(!anchor)return null;
    const capital=number(base?result.capital:anchor.result.capital),eligible=indices.filter(r=>r.rows&&number(r.result.capital)===capital),conflicts=new Set();
    function disagrees(left,right){const values=new Map(left.map(r=>[r.date,r.account]));return right.some(r=>values.has(r.date)&&values.get(r.date)!==r.account);}
    if(base){for(const index of eligible)if(disagrees(base,index.rows))conflicts.add(index.result);}
    const coherent=eligible.filter(index=>!conflicts.has(index.result));
    for(let i=0;i<coherent.length;i++)for(let j=i+1;j<coherent.length;j++)if(disagrees(coherent[i].rows,coherent[j].rows)){conflicts.add(coherent[i].result);conflicts.add(coherent[j].result);}
    // Without a trusted ETF result, conflicting index account snapshots cannot be chosen arbitrarily.
    if(!base&&conflicts.size)return {rows:[],series:[],capital,conflicts};
    const account=new Map(anchor.rows.map(r=>[r.date,r.account]));
    for(const index of eligible)if(!conflicts.has(index.result))for(const row of index.rows)if(!account.has(row.date))account.set(row.date,row.account);
    const rows=[...account].sort(([a],[b])=>a.localeCompare(b)).map(([date,account])=>({date,account}));
    function series(key,label,css,points,field) {
      const values=new Map(),previous=new Map();let before=null;
      for(const row of points){values.set(row.date,row[field]);previous.set(row.date,before);before=row[field];}
      return {key,label,css,values,previous,capital,end:points.at(-1).date,equity:points.at(-1)[field]};
    }
    const curves=[series('account','账户','account',rows,'account')];
    if(base)curves.push(series('hold','持有ETF','hold',base,'benchmark'));
    for(const index of eligible)if(!conflicts.has(index.result))curves.push(series(index.result.symbol||index.css,String(index.result.name||'大盘指数'),index.css,index.rows,'benchmark'));
    return {rows,series:curves,capital,conflicts};
  }
  function benchmarkDayValues(series,date) {
    const equity=series.values.get(date),previous=series.previous.get(date),capital=number(series.capital);
    return {equity:number(equity),change:number(equity)!==null&&number(previous)>0?equity/previous-1:null,gain:number(equity)!==null&&capital>0?equity/capital-1:null};
  }
  function drawBenchmarkChart(target,result,model=benchmarkChartModel(result),onSelect=null) {
    if(!model?.rows?.length)return false;
    const {rows,series,capital}=model,ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 820 265');svg.setAttribute('role','group');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label','账户与大盘对照曲线；拖动或使用左右方向键查看当日数据');svg.setAttribute('class','benchmark-interactive-chart');
    const values=[capital,...rows.flatMap(r=>series.map(s=>s.values.get(r.date)))].filter(v=>number(v)!==null);
    let min=Math.min(...values),max=Math.max(...values);const pad=Math.max((max-min)*.12,Math.abs(max)*.005,1);min-=pad;max+=pad;
    const x=i=>rows.length===1?432.5:65+i/(rows.length-1)*735,y=v=>220-(v-min)/(max-min)*190;
    function node(tag,attrs,text){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=String(text);svg.append(n);return n;}
    for(let i=0;i<4;i++){const v=min+(max-min)*i/3,yy=y(v);node('line',{x1:65,x2:800,y1:yy,y2:yy,class:'chart-grid'});node('text',{x:55,y:yy+4,'text-anchor':'end',class:'chart-label'},`${(v/10000).toFixed(1)}万`);}
    for(const curve of series){
      // Join on dates, never on array offsets. Missing dates break a line; they are not filled.
      let path='',connected=false,segment=[];const isolated=[];
      function endSegment(){if(segment.length===1)isolated.push(segment[0]);segment=[];connected=false;}
      rows.forEach((r,i)=>{const value=curve.values.get(r.date);if(number(value)===null){endSegment();return;}path+=`${connected?'L':'M'} ${x(i)} ${y(value)} `;connected=true;segment.push({i,value});});endSegment();
      const css=`benchmark-${curve.css}-path`;node('path',{d:path.trim(),class:css});
      for(const point of isolated)node('circle',{cx:x(point.i),cy:y(point.value),r:4,class:css+' benchmark-point'});
    }
    node('text',{x:65,y:249,class:'chart-label'},rows[0].date);node('text',{x:800,y:249,'text-anchor':'end',class:'chart-label'},rows.at(-1).date);
    const crosshair=node('line',{x1:x(rows.length-1),x2:x(rows.length-1),y1:30,y2:220,class:'benchmark-crosshair','aria-hidden':'true'});
    const markers=series.map(s=>node('circle',{r:4,class:`benchmark-cursor-point ${s.css}`,'aria-hidden':'true'}));
    const hit=node('rect',{x:65,y:20,width:735,height:205,fill:'transparent',class:'benchmark-hit-area','aria-hidden':'true'});target.append(svg);
    const note=el('div','chart-note');note.append(el('span','','已确认日终记录'),el('span','',String(rows.length)));target.append(note);
    const controls=el('div','benchmark-scrubber'),label=el('label','small','拖动查看当日数据'),slider=el('input','benchmark-date-slider');
    slider.type='range';slider.min='0';slider.max=String(rows.length-1);slider.step='1';slider.value=slider.max;slider.disabled=rows.length===1;slider.setAttribute('aria-label','拖动查看当日数据');label.append(slider);
    let selected=rows.length-1;
    const previous=button('前一日',()=>select(selected-1)),next=button('后一日',()=>select(selected+1)),latest=button('最新',()=>select(rows.length-1));
    const buttons=el('div','button-row');buttons.append(previous,next,latest);controls.append(label,buttons);target.append(controls);
    const readout=el('div','benchmark-day-readout'),heading=el('div','benchmark-day-heading'),date=el('strong','benchmark-selected-date');date.setAttribute('aria-live','polite');
    heading.append(el('span','small muted','所选日期'),date,el('span','small muted','已确认收盘'));readout.append(heading);
    const table=el('table','benchmark-day-table'),thead=el('thead'),headrow=el('tr');
    for(const title of ['对照','资产 / 等值本金（元）','较上一记录','累计收益'])headrow.append(el('th','',title));thead.append(headrow);table.append(thead);
    const tbody=el('tbody'),cells=series.map(s=>{const row=el('tr'),name=el('th'),amount=el('td'),change=el('td'),gain=el('td');name.setAttribute('scope','row');name.append(el('i','benchmark-swatch '+s.css),el('span','',s.label));row.append(name,amount,change,gain);tbody.append(row);return {amount,change,gain};});table.append(tbody);readout.append(table,el('p','small muted','涨跌按上一条实际记录计算；首条无前值时显示 —。'));target.append(readout);
    function select(index) {
      selected=Math.max(0,Math.min(rows.length-1,Math.round(number(index)??selected)));const day=rows[selected].date,xx=x(selected);
      slider.value=String(selected);slider.setAttribute('aria-valuetext',day);date.textContent=day;crosshair.setAttribute('x1',String(xx));crosshair.setAttribute('x2',String(xx));
      previous.disabled=selected===0;next.disabled=selected===rows.length-1;latest.disabled=next.disabled;
      series.forEach((s,i)=>{const v=benchmarkDayValues(s,day),cell=cells[i],marker=markers[i];cell.amount.textContent=v.equity===null?'无当日记录':money(v.equity);cell.change.textContent=benchmarkPercent(v.change);cell.gain.textContent=benchmarkPercent(v.gain);cell.change.className=signClass(v.change);cell.gain.className=signClass(v.gain);marker.setAttribute('visibility',v.equity===null?'hidden':'visible');if(v.equity!==null){marker.setAttribute('cx',String(xx));marker.setAttribute('cy',String(y(v.equity)));}});
      if(onSelect)onSelect(day);
    }
    function pointerSelect(event) {
      if(rows.length===1){select(0);return;}
      let xx=null;
      // Screen CTM includes SVG viewBox scaling and responsive letterboxing.
      try{const matrix=svg.getScreenCTM?.();if(matrix&&svg.createSVGPoint){const p=svg.createSVGPoint();p.x=event.clientX;p.y=event.clientY;xx=p.matrixTransform(matrix.inverse()).x;}}catch(_){}
      if(xx===null){const rect=svg.getBoundingClientRect?.();if(rect?.width>0)xx=(event.clientX-rect.left)*820/rect.width;}
      if(Number.isFinite(xx))select((xx-65)/735*(rows.length-1));
    }
    let dragging=false;
    hit.addEventListener('pointerdown',event=>{if(event.button!==undefined&&event.button!==0)return;dragging=true;hit.setPointerCapture?.(event.pointerId);pointerSelect(event);});
    hit.addEventListener('pointermove',event=>{if(dragging||event.pointerType!=='touch')pointerSelect(event);});
    hit.addEventListener('pointerup',event=>{pointerSelect(event);dragging=false;if(hit.hasPointerCapture?.(event.pointerId))hit.releasePointerCapture?.(event.pointerId);});
    hit.addEventListener('pointercancel',()=>{dragging=false;});hit.addEventListener('lostpointercapture',()=>{dragging=false;});
    slider.addEventListener('input',()=>select(slider.value));
    svg.addEventListener('keydown',event=>{const step=event.key==='ArrowLeft'?-1:event.key==='ArrowRight'?1:0;if(step){event.preventDefault();select(selected+step);}else if(event.key==='Home'||event.key==='End'){event.preventDefault();select(event.key==='Home'?0:rows.length-1);}});
    select(selected);return true;
  }
  function renderIndexBenchmarkCards(panel,indices,capital,model=null) {
    if(!indices.length)return;
    const cards=el('div','benchmark-index-cards');
    for(const index of indices){
      const r=index.result,conflict=model?.conflicts?.has(r),valid=index.rows&&number(r.capital)===number(capital)&&!conflict,card=el('div','benchmark-index-card '+index.css),heading=el('h4');
      heading.append(el('i','benchmark-swatch '+index.css),el('span','',r.name||'大盘指数'));card.append(heading);
      if(valid){
        const metrics=el('div','benchmark-index-metrics');metrics.append(metric('指数收益',benchmarkPercent(r.benchmark_return),'',signClass(r.benchmark_return)),metric('领先 / 落后（百分点）',benchmarkPoints(r.excess_return),'',signClass(r.excess_return)));card.append(metrics);
        card.append(benchmarkCaption('同区间账户收益',benchmarkPercent(r.account_return)),benchmarkCaption('指数比较区间',`${r.start||index.rows[0].date} — ${r.end||index.rows.at(-1).date}`));
        card.append(benchmarkCaption('指数行情截至',String(r.benchmark_cutoff||r.end||index.rows.at(-1).date)));
      }else card.append(el('p','small muted','指数对照暂不可用'),el('p','small muted',conflict?'同日账户记录不一致，暂不叠加指数对照。':r.message||'暂无共同已确认日终记录'));
      cards.append(card);
    }
    panel.append(cards);
  }
  function appendBenchmarkMethodSource(target,result) {
    if(typeof result.methodology==='string')target.append(el('p','small muted',result.methodology));
    for(const note of Array.isArray(result.notes)?result.notes:[])if(typeof note==='string')target.append(el('p','small muted',note));
    const source=result.source;
    if(source&&typeof source==='object'){
      for(const [key,label] of [['name','行情来源'],['provider','行情供应方'],['price','价格来源'],['dividends','分红来源'],['fetched_at','资料取得时间'],['as_of','行情确认截至']])if(typeof source[key]==='string')target.append(benchmarkCaption(label,source[key]==='excluded_price_index'?'价格指数不含现金分红':source[key]));
      if(typeof source.official_dividends_url==='string'&&/^https:\/\/[^\s]+$/.test(source.official_dividends_url)){
        const line=el('p','small benchmark-caption'),link=el('a','','基金公司分红记录');link.href=source.official_dividends_url;link.target='_blank';link.rel='noopener noreferrer';line.append(el('span','','分红官方核对'),link);target.append(line);
        if(Number.isInteger(source.official_dividend_records)&&source.official_dividend_records>=0)target.append(benchmarkCaption('已核对分红记录',String(source.official_dividend_records)));
      }
    }
  }
  function renderAccountBenchmark(panel,detail,entry,context) {
    replace(panel,el('h3','','账户资产曲线'));
    const result=entry?.result,valid=result?.status==='ok'&&benchmarkRows(result),indices=benchmarkIndices(result),comparison=benchmarkChartModel(result),model=comparison?.rows?.length?comparison:null;
    const chart=el('div','chart-container');
    if(!valid){
      const notice=el('div','benchmark-status');notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');
      notice.append(el('p','small muted',entry?.loading?'正在读取持有大盘ETF的同期收益…':'持有大盘ETF对照暂不可用，原账户曲线保留。'));
      if(!entry?.loading){if(result?.message||entry?.error)notice.append(el('p','small muted',result?.message||entry.error));notice.append(button('重试ETF对照',()=>mountAccountBenchmark(panel,detail,true),'text-button'));}
      panel.append(notice);
      if(!model){renderIndexBenchmarkCards(panel,indices,detail.summary?.capital,comparison);drawChart(chart,detail.curve||[],detail.summary?.capital);panel.append(chart);return;}
    }
    const name=String(result.name||'大盘ETF'),code=String(result.symbol||'').replace(/^(sh|sz)/,'');
    if(valid)panel.append(benchmarkCaption('持有对照',name+(code&&!name.includes(code)?` (${code})`:'')));
    panel.append(benchmarkCaption('同一本金 / 元',money(model.capital)),benchmarkCaption('比较区间',`${valid?result.start||'—':model.rows[0].date} — ${valid?result.end||'—':model.rows.at(-1).date}`));
    if(entry.loading)panel.append(el('p','small muted','正在核对ETF对照数据，暂时保留上次结果。'));
    else if(entry.error)panel.append(el('p','small benchmark-cutoff-note','本次ETF对照更新未完成；仍显示上述日期的结果。'));
    if(result.end&&String(result.account_cutoff||'').slice(0,10)>result.end)panel.append(el('p','small benchmark-cutoff-note','ETF对照截至日期早于账户原始记录；下方收益仅比较上述共同区间，不代表账户最新总收益。'));
    if(valid){const metrics=el('div','benchmark-metrics');
    metrics.append(metric('账户收益',benchmarkPercent(result.account_return),'',signClass(result.account_return)),metric('持有ETF收益',benchmarkPercent(result.benchmark_return),'',signClass(result.benchmark_return)),metric('领先 / 落后（百分点）',benchmarkPoints(result.excess_return),'账户收益 − 持有ETF收益',signClass(result.excess_return)),metric('多赚 / 少赚（元）',number(result.excess_amount)===null?'—':`${number(result.excess_amount)>0?'+':''}${money(result.excess_amount)}`,'账户期末资产 − 持有ETF期末资产',signClass(result.excess_amount)));panel.append(metrics);
    }
    renderIndexBenchmarkCards(panel,indices,model.capital,model);
    if(indices.length)panel.append(el('p','small muted benchmark-alignment','指数按各自共同日终区间比较；缺失日期留空，曲线不延长。指数等值本金仅反映价格涨跌。'));
    const legend=el('div','benchmark-legend'),legendValues=[];
    for(const s of model.series){const item=el('span','benchmark-legend-item'),value=el('strong','',`¥ ${money(s.equity)}`);legendValues.push(value);item.append(el('i','benchmark-swatch '+s.css),el('span','',s.label),value);legend.append(item);}panel.append(legend);
    const original=state.accountBenchmarkViews.get(context.identity)==='original';
    const toggle=button(original?'查看同区间对照曲线':'查看原始账户曲线',()=>{state.accountBenchmarkViews.set(context.identity,original?'comparison':'original');renderAccountBenchmark(panel,detail,entry,context);},'text-button benchmark-toggle');toggle.setAttribute('aria-pressed',String(original));panel.append(toggle);
    if(original){drawChart(chart,detail.curve||[],detail.summary?.capital);panel.append(el('p','small muted','原始曲线保留每日或逐柱记录；上方收益比较仍使用共同日终区间。'));}
    else drawBenchmarkChart(chart,result,model,day=>model.series.forEach((s,i)=>{const value=s.values.get(day);legendValues[i].textContent=number(value)===null?'—':`¥ ${money(value)}`;}));
    panel.append(chart,el('p','small muted benchmark-alignment','对照按双方均有记录的日终对齐；小时账户仅取已确认收盘记录，未收盘末日不参与比较。'));
    if(result.account_cutoff)panel.append(benchmarkCaption('账户原始记录截至',dateText(result.account_cutoff)));
    const methodology=el('details','benchmark-method');methodology.append(el('summary','','比较口径与数据来源'));
    if(valid)appendBenchmarkMethodSource(methodology,result);
    if(result.benchmark_cutoff)methodology.append(benchmarkCaption('ETF行情截至',result.benchmark_cutoff));
    for(const index of indices){methodology.append(el('h4','',index.result.name||'大盘指数'));appendBenchmarkMethodSource(methodology,index.result);}
    panel.append(methodology);
  }
  function mountAccountBenchmark(panel,detail,force=false) {
    const identity=JSON.stringify([state.group,state.accountId]),key=accountBenchmarkKey(detail),context={identity,key,group:state.group,id:state.accountId};
    let entry=state.accountBenchmarks.get(identity);const ttl=entry?.result?.status==='ok'&&!entry?.error?300000:60000;
    if(!entry||entry.key!==key||(!entry.loading&&(force||Date.now()-entry.at>ttl))){
      entry={key,at:Date.now(),loading:true,result:entry?.key===key?entry.result:null,error:null};state.accountBenchmarks.set(identity,entry);
      if(state.accountBenchmarks.size>24)state.accountBenchmarks.delete(state.accountBenchmarks.keys().next().value);
      entry.promise=api('/api/account-benchmark?'+new URLSearchParams({group:context.group,id:context.id})).then(result=>{entry.result=result;}).catch(error=>{entry.error=errorMessage(error);}).finally(()=>{entry.loading=false;entry.at=Date.now();});
    }
    renderAccountBenchmark(panel,detail,entry,context);
    const current=()=>panel.isConnected&&state.authenticated&&state.group===context.group&&state.accountId===context.id&&accountBenchmarkKey(state.accountDetail)===key&&state.accountBenchmarks.get(identity)===entry;
    if(entry.loading)entry.promise.then(()=>{if(current())renderAccountBenchmark(panel,detail,entry,context);});
  }
  function refreshAccountBenchmark() {
    if(!state.authenticated||state.page!=='accounts'||!state.accountId||!state.accountDetail||document.hidden)return;
    const panel=$('account-detail').querySelector('.account-benchmark');if(!panel?.isConnected)return;
    const identity=JSON.stringify([state.group,state.accountId]),entry=state.accountBenchmarks.get(identity),ttl=entry?.result?.status==='ok'&&!entry?.error?300000:60000;
    if(entry?.loading)return;
    if(entry&&entry.key===accountBenchmarkKey(state.accountDetail)&&Date.now()-entry.at<=ttl)return;
    mountAccountBenchmark(panel,state.accountDetail);
  }
  // END_ACCOUNT_BENCHMARK_UI

  function openCreate(prefill) {
    const fromComparison=!!(prefill?.group&&prefill?.strategy);
    if(state.createPending){if(fromComparison)toast('已有建户任务在进行，先查看当前任务；本次选择尚未替换。');}
    else if(fromComparison&&state.createDraft){toast('已保留未提交的建户输入。若要换用刚才的策略，请先放弃本次输入，再从该策略重新进入。');}
    else if(fromComparison){
      const group=state.catalog.groups.find(g=>g.id===prefill.group),strategy=group?.strategies.find(s=>s.code===prefill.strategy);if(!strategy)throw new Error('这项策略当前不在可建户目录中，请更新策略目录后重试。');
      $('create-group').value=group.id;configureCreate();fillStrategies(group.id,'create-strategy',strategy.code);$('create-capital').value=number(prefill.capital)===null?'100000':String(prefill.capital);$('create-start').value='';adjustCreateEarliest();
      $('create-note').textContent=canonicalText($('create-note'))+` 已按所选策略预填 ${strategy.code} ；请确认本金并选择账户起点。历史排名不是自动推荐。`;$('create-error').hidden=true;state.createDraft={...prefill};
    }else if(!state.createDraft){$('create-group').value=state.group;configureCreate();$('create-error').hidden=true;}
    updateCreateReview();setCreatePending(state.createPending);if($('detail-dialog').open)$('detail-dialog').close();if(!$('create-dialog').open)$('create-dialog').showModal();if(!state.createPending)$(fromComparison?'create-start':'create-name').focus();
  }
  function configureCreate() { const g=groupBy($('create-group').value);fillStrategies(g.id,'create-strategy');$('create-start').value='';$('create-note').textContent=(groupNotes[g.id]||'')+' 全局自动模拟开启时，新账户会自动追赶已有确认行情；可在账户详情暂停。';adjustCreateEarliest(); }
  function adjustCreateEarliest() { const s=strategyBy($('create-group').value,$('create-strategy').value);if(s?.earliest){$('create-start').min=String(s.earliest).slice(0,10);if($('create-start').value&&$('create-start').value<$('create-start').min)$('create-start').value=$('create-start').min;}else $('create-start').removeAttribute('min'); }
  let createReviewSignature='';
  function updateCreateReview(){
    const start=$('create-start').value,group=$('create-group').value,strategy=$('create-strategy').value,capital=$('create-capital').value;
    const signature=JSON.stringify([start,group,strategy,capital,state.settingsReadOk,state.settings?.auto_simulate]);
    if(signature!==createReviewSignature){$('create-confirm').checked=false;createReviewSignature=signature;}
    const mode=!state.settingsReadOk?'自动设置读取未成功，暂不能建户；请等待恢复。':state.settings.auto_simulate?'全局自动模拟已开启：建户后会从所选起点补跑已有确认行情，并继续按原策略自动推进；可在账户详情暂停。':'全局自动模拟已暂停：建户后不会自动补跑历史；可手动接续指定区间，后续仍按全局与逐账户设置运行。';
    $('create-review-text').textContent=`历史回放 · ${strategy||'待选策略'} · 本金 ${capital||'待确认'} 元 · 起点 ${start||'尚未选择'}。${mode}`;
    $('create-submit').disabled=state.createPending||!state.settingsReadOk;
  }
  function setCreatePending(value) {
    state.createPending=value;if(!value)state.createJobId=null;const accepted=value&&!!state.createJobId;
    $('create-submit').disabled=value||!state.settingsReadOk;$('create-submit').textContent=accepted?'已提交后台':value?'正在提交…':'建立账户';$('create-background').hidden=!accepted;
    for(const id of ['create-name','create-group','create-start','create-strategy','create-capital','create-confirm','create-discard'])$(id).disabled=value;
    for(const b of $('create-dialog').querySelectorAll('[data-close]'))b.disabled=value&&!accepted;
    $('new-account').textContent=value?'查看建户进度':state.createDraft?'继续编辑建户':'＋ 建立历史回放账户';$('create-status').hidden=!value;
    const job=state.jobs.get(state.createJobId),progress=typeof job?.progress==='string'?job.progress:job?.progress?.message;
    $('create-status').textContent=accepted?`${statusNames[job?.status]||'后台处理中'}${progress?' · '+progress:''}。收起或关闭窗口不会停止任务；如需停止，请到任务记录。`:'正在等待服务确认，请勿重复提交。收到任务编号后可以收起窗口。';
  }
  function syncCreateTask(){
    if(state.createPending){setCreatePending(true);return;}
    const job=Array.from(state.jobs.values()).find(j=>j.action==='create'&&!terminal.has(j.status));if(!job)return;const params=jobParams(job);if(!params.group||!params.strategy)return;
    state.createDraft={...params};state.createJobId=job.id;$('create-group').value=params.group;configureCreate();fillStrategies(params.group,'create-strategy',params.strategy);$('create-name').value=params.name||'';$('create-start').value=String(params.start||'').slice(0,10);$('create-capital').value=params.capital??'';$('create-error').hidden=true;
    const key=jobKey('create',params);if(!state.tracked.has(job.id))state.tracked.set(job.id,{action:'create',params,key});state.busy.set(key,job.id);setCreatePending(true);
  }
  function isBenchmark(row){return !!row.benchmark||/BENCH|BUY_HOLD|买入持有/i.test(`${row.code} ${row.label}`);}

  function renderComparison(result=state.comparisons.get($('compare-group').value),target=$('comparison-result')) {
    if(!result){replace(target,empty('还没有这一组的比较结果','设置区间和本金后运行比较。完成的任务也可在“任务记录”中回看。'));target.className='panel';return;}
    target.className='panel';replace(target);const rows=Array.isArray(result)?result:(result.rows||result.results||[]);const params=result._params||{};
    const heading=el('div','result-heading'),title=el('div');title.append(el('h3','','本次历史比较'),el('p','',`${result.start||params.start||'—'} → ${result.end||params.end||'—'} · 本金 ¥ ${money(result.capital??params.capital)} · ${rows.length} 项结果`));heading.append(title,button('导出结果',()=>localDownload(result,'策略比较结果.json')));target.append(heading);
    if(!rows.length){target.append(empty('没有返回可用结果','请检查区间与策略的历史起点。',true),jsonDetails('完整返回信息',result));return;}
    const normalized=rows.map(r=>({...r,code:r.code||r.id||r.strategy,label:r.label||r.name||r.strategy_name||r.code||r.id||r.strategy,return:r.return??r.total_return??r.metrics?.total_return,annualized:r.annualized??r.cagr??r.metrics?.cagr,drawdown:Math.abs(r.drawdown??r.max_drawdown??r.metrics?.max_drawdown??NaN),fees:r.fees??r.metrics?.fees,trades:r.trades??r.fills??r.metrics?.fills}));
    const candidates=result.completed===false?[]:normalized.filter(r=>!isBenchmark(r));const annuals=candidates.map(r=>number(r.annualized)).filter(v=>v!==null),dds=candidates.map(r=>number(r.drawdown)).filter(v=>v!==null);const best=annuals.length?Math.max(...annuals):null,low=dds.length?Math.min(...dds):null;
    const sorted=[...normalized].sort((a,b)=>{const key=state.compareSort.key;const aa=key==='label'?a.label:number(a[key]),bb=key==='label'?b.label:number(b[key]);if(aa===null)return bb===null?0:1;if(bb===null)return-1;const n=typeof aa==='string'?aa.localeCompare(bb,'zh-CN'):aa-bb;return state.compareSort.desc?-n:n;});
    const columns=[{key:'label',title:'策略',render:r=>{const n=el('div','asset-name',String(r.label).replace(/【[^】]*】/g,'')),badges=el('div','badge-group');const isCandidate=result.completed!==false&&!isBenchmark(r);if(isCandidate&&best!==null&&number(r.annualized)!==null&&Math.abs(r.annualized-best)<1e-10)badges.append(el('span','rank-badge','本次年化最高'));if(isCandidate&&low!==null&&number(r.drawdown)!==null&&Math.abs(r.drawdown-low)<1e-10)badges.append(el('span','rank-badge low','本次回撤最低'));if(badges.children.length)n.append(badges);
      if(!isBenchmark(r)){const group=result.group||params.group||state.catalog.groups.find(g=>g.strategies.some(s=>s.code===r.code))?.id;const available=state.catalog.groups.some(g=>g.id===group&&g.strategies.some(s=>s.code===r.code));const create=button('用此策略建账户',()=>openCreate({group,strategy:r.code,capital:result.capital??params.capital}),'text-button compare-create');create.disabled=!available;if(!available)create.title='此策略当前不在可建户目录中';n.append(create);}return n;}},{key:'return',title:'累计收益',render:r=>el('span',signClass(r.return),percent(r.return))},{key:'annualized',title:'年化收益',render:r=>percent(r.annualized)},{key:'drawdown',title:'最大回撤',render:r=>drawdown(r.drawdown)},{key:'fees',title:'累计佣金 / 元',render:r=>money(r.fees)},{key:'trades',title:'交易统计',render:r=>{const n=el('div','',money(r.trades,0));n.append(el('span','subline',r.trade_unit||'交易数（见完整口径）'));return n;}}];
    target.append(makeTable(columns,sorted,{sort:{...state.compareSort,onSort:key=>{state.compareSort={key,desc:state.compareSort.key===key?!state.compareSort.desc:false};renderComparison(result,target);}}}));
    if(result.curves&&Object.keys(result.curves).length){
      const chartPanel=el('div','comparison-chart'),controls=el('div','form-row'),label=el('label','grow','查看策略曲线'),choice=el('select'),mode=el('select'),modeLabel=el('label','','曲线类型'),chart=el('div','chart-container');
      const viewKey=JSON.stringify([result.group||params.group||normalized.map(r=>r.code).join(','),result.start||params.start,result.end||params.end,result.capital??params.capital]),saved=state.comparisonViews.get(viewKey)||{};
      fillSelect(choice,normalized.filter(r=>Array.isArray(result.curves[r.code])),saved.code||sorted[0]?.code,r=>r.label);label.append(choice);fillSelect(mode,[{id:'asset',label:'资产曲线'},{id:'drawdown',label:'距高点回撤'}],saved.mode||'asset',r=>r.label);modeLabel.append(mode);controls.append(label,modeLabel);chartPanel.append(controls,chart);target.append(chartPanel);
      const redraw=()=>{state.comparisonViews.set(viewKey,{code:choice.value,mode:mode.value});replace(chart);drawChart(chart,result.curves[choice.value]||[],result.capital??params.capital,mode.value);};choice.addEventListener('change',redraw);mode.addEventListener('change',redraw);redraw();
    }
    target.append(el('p','small muted','标签仅适用于本次同区间、同本金的组内比较；不足一年不显示年化。基准不参与策略标签排名。不同账户组的结算口径不能直接混排。'));
    if(result.completed===false)target.append(el('p','notes','本次比较未全部完成，只保留已完整跑完区间的策略，不生成本次排名。'));for(const item of result.skipped||[])target.append(el('p','notes',`${item.code||item.strategy||''} 未纳入：${item.reason||'此区间没有足够历史数据'}`));for(const note of normalizeNotes(result.notes||result.warnings))target.append(el('p','notes',note));target.append(jsonDetails('完整结果与执行口径',result));
  }

  function jobKey(action,params) { return `${action}:${params.group||''}:${params.id||''}:${action==='reference'?params.strategy||'':''}`; }
  async function submitJob(action,params,trigger) {
    const key=jobKey(action,params);if(state.busy.has(key)){toast('同一操作已经在后台进行，可到任务记录查看。');return null;}
    if(trigger)trigger.disabled=true;state.busy.set(key,'submitting');const signature=JSON.stringify({action,params});let idempotency=state.attempts.get(signature);if(!idempotency){idempotency=uuid();state.attempts.set(signature,idempotency);}
    try{
      const response=await api('/api/jobs',{method:'POST',body:{action,params,idempotency_key:idempotency}});const job=response.job||response;if(!job.id)throw new Error('服务没有返回任务编号，请到任务记录核对后再提交。');
      const merged={action,params,...job};state.busy.set(key,job.id);state.tracked.set(job.id,{action,params,key,trigger});state.jobs.set(job.id,merged);state.attempts.delete(signature);if(action==='create'){state.createJobId=job.id;state.createDraft={...params};setCreatePending(true);}renderTasks();toast(`${actionNames[action]||'任务'}已提交，可在后台继续运行。`);
      if(terminal.has(job.status))await completeJob(merged);else schedulePoll(500);return job;
    }catch(error){state.busy.delete(key);if(trigger)trigger.disabled=false;throw error;}
  }
  function schedulePoll(delay=5000) { clearTimeout(state.poll);if(state.authenticated)state.poll=setTimeout(()=>pollJobs(),delay); }
  async function pollJobs() {
    if(!state.authenticated||state.polling)return;state.polling=true;
    try { const response=await api('/api/jobs');const jobs=Array.isArray(response)?response:(response.jobs||[]);
      for(const item of jobs){const previous=state.jobs.get(item.id)||{};const job={...previous,...item};state.jobs.set(job.id,job);if(terminal.has(job.status)&&state.tracked.has(job.id))await completeJob(job);else if(job.action==='refresh'&&job.status==='succeeded'&&previous.status&&!terminal.has(previous.status))await loadOverview();}
      syncCreateTask();renderTasks();await refreshOpenJob();
    }catch(error){setConnection(false,'连接暂不可用 · 将重试');if(state.page==='tasks')showError(error);}
    finally{state.polling=false;schedulePoll(document.hidden?15000:5000);}
  }
  async function completeJob(job) {
    const meta=state.tracked.get(job.id);if(!meta)return;
    if(job.status==='succeeded' && job.result==null){job={...job,...await api(`/api/jobs/${encodeURIComponent(job.id)}`)};state.jobs.set(job.id,job);}
    state.tracked.delete(job.id);state.busy.delete(meta.key);if(meta.trigger?.isConnected)meta.trigger.disabled=false;
    if(job.status!=='succeeded'){
      const message=job.error||({cancelled:'已停止，已完成记录保留。',interrupted:'服务重启或任务被中断，请核对账户后再接续。'})[job.status]||'任务未能完成。';toast(message,job.status==='failed');
      if(meta.action==='create'){setCreatePending(false);$('create-error').textContent=message;$('create-error').hidden=false;}
      if(meta.action==='reference'&&$('reference-strategy').value===meta.params.strategy)replace($('reference-result'),empty('参考未能生成',message,true));return;
    }
    const result=job.result||{};toast(`${actionNames[meta.action]||'任务'}已完成。`);
    try{
      if(meta.action==='create'){state.createDraft=null;setCreatePending(false);if($('create-dialog').open)$('create-dialog').close();}
      if(['create','advance','switch','attach','import','delete','restore'].includes(meta.action)){if(['create','import'].includes(meta.action)){state.group=meta.params.group;renderGroupButtons();}
        if(state.group===meta.params.group){const id=result.id||result.account?.id||result.summary?.id||meta.params.id;await loadAccounts(id);}
        if(meta.action==='create'||meta.action==='import')showPage('accounts');
      }else if(meta.action==='compare'){const value=Array.isArray(result)?{rows:result,_params:meta.params}:{...result,_params:meta.params};state.comparisons.set(meta.params.group,value);if($('compare-group').value===meta.params.group)renderComparison(value);}
      else if(meta.action==='reference'){if(groupBy(meta.params.group).overseas){await loadOverseas();}else if($('reference-group').value===meta.params.group&&$('reference-strategy').value===meta.params.strategy&&number($('reference-capital').value)===number(meta.params.capital)){state.referenceEdited=false;renderReference(result);$('reference-auto-note').textContent='输入与后台结果一致时，将自动跟随更新。';}else toast('参考已完成；输入已变化，可在任务记录查看刚才的结果。');}
      else if(meta.action==='refresh'){await Promise.all([loadOverview(),loadCatalog(),state.page==='overseas'?loadOverseas():Promise.resolve()]);}
      const link=downloadLink(result);if(link){showDetail('文件已准备好',downloadSection(result,meta.action==='full_backup'));}
    }catch(error){showError(error);}
  }
  function jobStatusClass(status) { return status==='failed'?'danger':status==='cancelled'||status==='interrupted'?'warning':status==='succeeded'?'':'neutral'; }
  function jobParams(job) { return job.params||job.request?.params||{}; }
  function renderTasks() {
    const jobs=Array.from(state.jobs.values()).sort((a,b)=>String(b.created_at||b.created||b.id).localeCompare(String(a.created_at||a.created||a.id)));
    const running=jobs.filter(j=>!terminal.has(j.status)).length;$('running-count').textContent=String(running);$('running-count').hidden=!running;
    const list=$('task-list');replace(list);if(!jobs.length){list.append(empty('暂时没有运行记录','创建账户、刷新行情或比较策略后，任务会在这里显示。'));return;}
    for(const job of jobs){const card=el('div','task-card'),copy=el('div'),title=el('div','task-title'),params=jobParams(job);title.append(el('strong','',actionNames[job.action]||job.action||'后台任务'),el('span',`pill ${jobStatusClass(job.status)}`,statusNames[job.status]||job.status));copy.append(title,el('div','task-meta',`${params.group?groupBy(params.group).name+' · ':''}${params.name||params.strategy||''}${job.created_at||job.created?' · '+dateText(job.created_at||job.created):''}`));
      let progress=job.error||job.progress;if(progress&&typeof progress==='object')progress=progress.message||JSON.stringify(progress);if(progress)copy.append(el('p',`task-progress${job.status==='failed'?' task-error':''}`,progress));
      if(!terminal.has(job.status)){const line=el('div','progress-line');line.append(el('span'));copy.append(line);}
      const actions=el('div','task-actions');if(!terminal.has(job.status))actions.append(button('停止',async()=>{await api(`/api/jobs/${encodeURIComponent(job.id)}/cancel`,{method:'POST',body:{}});toast('已请求停止，将在安全步骤结束；自动任务对应的开关或账户暂停状态会同步更新。');schedulePoll(500);scheduleSettingsPoll(100);}));
      if(job.result?.download_url){const link=downloadLink(job.result);if(link)actions.append(link);}actions.append(button('查看详情',()=>viewJob(job.id)));card.append(copy,actions);list.append(card);}
  }
  function clearOpenJob(){state.openJobId=null;state.jobDetailSignature=null;state.jobDetailLoading=false;state.jobDetailRequest++;}
  let signalsData=null,signalsBusy=false,signalsSignature=null,signalsReadAt=null,signalsError=null,featuredSignature=null,openSignalRow=null;
  function signalView(row){return signalsError?{...row,current:false,status:'wait',label:'等待确认',source_warning:'最新状态读取失败，当前内容可能过期。旧信号仅供回看。'}:row;}
  function renderFeatured(){
    const signature=JSON.stringify([signalsData?.rows,!!signalsData,signalsError,window.ETF_I18n?.language]);
    if(signature===featuredSignature)return;featuredSignature=signature;
    window.ETFFeaturedStrategies?.render({root:$('featured-list'),rows:signalsData?.rows||[],loaded:!!signalsData,error:signalsError,onCreate:selection=>openCreate({group:selection.group,strategy:selection.code}),onDetail:row=>signalDetail(signalsError?{...row,current:false,status:'wait',label:'等待确认',source_warning:'最新状态读取失败，当前内容可能过期。'}:row)});
  }
  const signalLabels={buy:'待买入',sell:'待卖出',rebalance:'待调仓',hold:'继续持有',cash:'保持空仓',wait:'等待确认'};
  function signalMatches(row,group,status,query=''){
    if(group!=='all'&&row.group!==group)return false;
    const match=status==='all'||row.status===status||(['buy','sell'].includes(status)&&row.current&&!['stale','unknown'].includes(row.source_status)&&(row.intents||[]).some(i=>i.action===status));
    const names=`${row.code} ${row.name} ${row.group_name}`;return match&&(names+' '+(window.ETF_I18n?.translate(names,'en')||'')).toLowerCase().includes(query.trim().toLowerCase());
  }
  async function loadSignals(){
    if(signalsBusy||!state.authenticated)return;const previouslyFailed=!!signalsError;signalsBusy=true;$('signals-refresh').disabled=true;$('featured-refresh').disabled=true;
    try{const data=await api('/api/signals');if(!state.authenticated)return;signalsData=data;signalsError=null;signalsReadAt=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium'}).format(new Date());$('signals-error').hidden=true;$('featured-error').hidden=true;
      $('featured-progress').textContent='上次成功读取（北京时间）：'+signalsReadAt+' · 每个模型的确认时间见卡片';
      $('signals-note').textContent=data.note;$('signals-progress').textContent=`${data.ready} / ${data.total||84} 个模型已完成现有快照${data.stale?' · '+data.stale+' 个模型行情待补齐':''} · ${data.active?'正在计算 '+groupBy(data.active).name:'后台等待新的确认行情'} · 快照检查 ${dateText(data.checked_at)}（北京时间）${state.settings?.auto_refresh===false?' · 行情自动更新已暂停':''}`;
      const signature=JSON.stringify([data.rows,data.groups]);if(signature!==signalsSignature||previouslyFailed){signalsSignature=signature;const g=$('signals-group').value||'all';fillSelect($('signals-group'),[{id:'all',name:'全部市场 · 84 个模型'},...data.groups],g,x=>x.name);renderSignals();}
    }catch(error){signalsError=errorMessage(error);$('signals-error').textContent='最新状态读取失败，当前内容可能过期：'+signalsError;$('signals-error').hidden=false;$('featured-error').textContent=$('signals-error').textContent;$('featured-error').hidden=false;if(!signalsReadAt)$('featured-progress').textContent='尚未成功读取最新信号';}
    finally{signalsBusy=false;$('signals-refresh').disabled=false;$('featured-refresh').disabled=false;renderFeatured();if(signalsError){renderSignals();if(!previouslyFailed&&openSignalRow&&$('detail-dialog').open){const top=$('detail-dialog').scrollTop;signalDetail(openSignalRow);$('detail-dialog').scrollTop=top;}}}
  }
  function signalBadge(row){return el('span',`signal-badge signal-${row.status}`,row.label||signalLabels[row.status]||'等待确认');}
  function signalActivity(row,detail=false){
    const box=el('section','signal-activity'),a=row.activity;
    box.append(el('h4','','最新动态 · 模型模拟成交'));
    if(!a){box.append(el('p','small muted','成交动态尚未生成，等待该模型计算完成。'));return box;}
    box.append(el('p','small muted',`最近确认日 ${a.day}`));
    if(!row.current||row.source_status==='stale'||row.source_status==='unknown')box.append(el('p','warning-text','以下是旧快照的成交记录，最新动态待更新。'));
    const trades=a.day_trades||[];
    box.append(el('p','activity-summary',a.summary));
    const grouped=new Map();for(const e of trades){const key=e.symbol+'|'+e.side,old=grouped.get(key)||{symbol:e.symbol,side:e.side,quantity:0,count:0};old.quantity+=e.quantity;old.count++;grouped.set(key,old);}
    for(const e of grouped.values())box.append(el('p',`activity-fill activity-${e.side}`,`已${e.side==='buy'?'买入':'卖出'} ${assetName(e.symbol)} · ${money(e.quantity,0)} 份${e.count>1?'（'+e.count+'笔合计）':''}`));
    if(!trades.length){const held=Object.entries(row.positions||{}).filter(([,q])=>q>0);if(held.length)box.append(el('p','small muted','仍持有：'+held.map(([s,q])=>`${assetName(s)} ${money(q,0)}份`).join('；')));}
    const last=a.latest_trades||[];
    box.append(el('h4','','最近一次模拟成交'));
    if(!last.length)box.append(el('p','small muted','从参考组合起点至上述确认日，尚无模拟成交。'));
    else{box.append(el('p','small muted',dateText(a.latest_time)+(a.latest_time.slice(0,10)!==a.day?' · 非该确认日成交':'')));
      for(const e of last)box.append(el('p',`activity-fill activity-${e.side}`,`${e.side==='buy'?'买入':'卖出'} ${assetName(e.symbol)} · ${money(e.quantity,0)} 份 · ${Number(e.price).toFixed(6)} 元/份`));}
    if(detail){
      const columns=[{title:'成交时间',render:e=>dateText(e.time)},{title:'资产',render:e=>assetName(e.symbol)},{title:'操作',render:e=>e.side==='buy'?'买入':'卖出'},{title:'份数',render:e=>money(e.quantity,0)},{title:'成交价 / 元',render:e=>Number(e.price).toFixed(6)},{title:'成交金额 / 元',render:e=>money(e.amount)},{title:'佣金 / 元',render:e=>money(e.fee)},{title:'执行原因',render:e=>e.reason}];
      if(trades.length)box.append(el('h4','','该确认日全部成交明细'),makeTable(columns,trades));
      if(last.length&&!trades.length)box.append(el('h4','','最近一次成交明细'),makeTable(columns,last));
      box.append(el('p','notes',a.source+' 成交价含原策略滑点，成交金额不含佣金。'));
    }
    return box;
  }
  function signalDetail(row){
    const snapshot=row;row=signalView(row);
    const body=el('div','signal-detail');body.append(signalBadge(row),el('p','small muted',`${row.group_name} · 信号截至 ${dateText(row.as_of)} · 计算于 ${dateText(row.computed_at)}`));
    if(!row.current)body.append(el('p','warning-text','此模型正在更新，下方旧信号只供回看；不能视为当前指令。'));
    if(row.source_warning)body.append(el('p','warning-text',row.source_warning+' 下方为旧信号依据。'));
    if(row.error)body.append(el('p','inline-error',row.error));
    body.append(signalActivity(row,true));
    body.append(el('h3','','为什么这样操作'));for(const reason of row.reasons||[])body.append(el('p','advice-copy',reason));
    if(row.intents?.length){body.append(el('h3','','各资产的下一步意向'));for(const i of row.intents)body.append(el('p','advice-copy',`${assetName(i.symbol)}：${signalLabels[i.action]}。${i.reason}`));}
    if(row.rule)body.append(el('h3','','策略规则'),el('p','advice-copy',row.rule));
    if(row.execution)body.append(el('h3','','什么时候执行'),el('p','advice-copy',row.execution));
    if(row.signal_time)body.append(el('p','small muted','最后确认的指标周期：'+dateText(row.signal_time)));
    if(row.daily_as_of)body.append(el('p','small muted','银行 / 黄金日线参考截至：'+row.daily_as_of));
    const assets=Object.keys(row.weights||{});
    if(assets.length){body.append(el('h3','','参考仓位与目标配置'),makeTable([{title:'资产',render:r=>assetName(r.symbol)},{title:'参考持仓 / 份',render:r=>money(row.positions?.[r.symbol],0)},{title:'条件目标比例',render:r=>(100*row.weights[r.symbol]).toFixed(1)+'%'}],assets.map(symbol=>({symbol}))),el('p','small muted',`条件目标现金比例：${(100*(row.cash_weight||0)).toFixed(1)}%。目标配置须满足策略确认与执行条件；是否已安排买卖，以“下一步意向”为准。份数表示模型参考持仓。`));}
    body.append(el('p','notes',signalsData?.note||'模型意向与实际账户成交分别记录。'),el('p','small muted','详情保留本次打开时的信号快照；关闭后重新打开可查看新的结果。'));
    if(row.evidence)body.append(jsonDetails('查看完整模型依据',row.evidence));
    if(state.catalog?.groups?.some(g=>g.id===row.group&&g.strategies.some(s=>s.code===row.code)))body.prepend(button('用此策略建立模拟账户',()=>openCreate({group:row.group,strategy:row.code}),'button primary'));
    showDetail(row.name,body);openSignalRow=snapshot;
  }
  function renderSignals(){
    if(!signalsData)return;const all=(signalsData.rows||[]).map(signalView),group=$('signals-group').value||'all',status=$('signals-status').value||'all',query=$('signals-search').value||'';
    const selected=all.filter(r=>group==='all'||r.group===group),counts=$('signals-counts');replace(counts);
    for(const [key,name] of Object.entries(signalLabels)){const count=selected.filter(r=>signalMatches(r,'all',key)).length;const b=button(`${key==='buy'?'包含买入':key==='sell'?'包含卖出':name} ${count}`,()=>{$('signals-status').value=key;renderSignals();},`signal-count ${status===key?'selected':''}`);counts.append(b);}
    const rows=all.filter(r=>signalMatches(r,group,status,query)),list=$('signals-list');replace(list);$('signals-matched').textContent=`显示 ${rows.length} / ${selected.length} 个模型 · 买入、卖出数量包含同时买卖的调仓模型`;
    if(!rows.length){list.append(empty('没有符合筛选的模型','可切换市场、意向或清空搜索。',true));return;}
    for(const row of rows){const card=el('article','panel signal-card'),head=el('div','signal-card-head');head.append(el('span','small muted',row.group_name),signalBadge(row));card.append(head,el('h3','',row.name),el('p','small muted',`信号截至 ${dateText(row.as_of)}`));
      card.append(signalActivity(row));
      const reason=(row.reasons||[]).join(' ');card.append(el('p','signal-reason',reason));
      if(row.intents?.length)card.append(el('p','signal-intents','下一步意向（尚未成交）：'+row.intents.map(i=>`${assetName(i.symbol)} · ${signalLabels[i.action]}`).join(' / ')));
      if(row.error)card.append(el('p','warning-text','该组计算暂未完成，后台会重试。'));
      if(row.source_warning)card.append(el('p','warning-text',row.source_warning));
      if(!row.current&&row.as_of)card.append(el('p','warning-text','旧结果，等待新快照计算。'));
      card.append(button('查看操作依据',()=>signalDetail(row),'button secondary small-button'));list.append(card);
    }
  }
  function showDetail(title,...content) { openSignalRow=null;clearOpenJob();$('detail-title').textContent=title;replace($('detail-body'),...content);if(!$('detail-dialog').open)$('detail-dialog').showModal(); }
  function jobDetailSignature(job){return JSON.stringify([job.status,job.updated_at||job.updated,job.progress,job.error,!!(job.result||job.result_available)]);}
  function renderJobDetail(job){
    const params=jobParams(job),body=el('div');body.append(el('p','small muted',`${statusNames[job.status]||job.status} · ${dateText(job.created_at||job.created)}`));
    if(job.error)body.append(el('p','inline-error',job.error));const result=job.result;
    if(result){if(job.action==='compare'){const resultBox=el('div');renderComparison(Array.isArray(result)?{rows:result,_params:params}:{...result,_params:params},resultBox);body.append(resultBox);}else if(job.action==='reference'){const resultBox=el('div');renderReference(result,resultBox);body.append(resultBox);}else{const link=downloadLink(result);if(link)body.append(downloadSection(result,job.action==='full_backup'));const text=result.message||result.note;if(text)body.append(el('p','advice-copy',text));body.append(jsonDetails('查看本次完整结果',result));}}
    else{const progress=typeof job.progress==='string'?job.progress:job.progress?.message;body.append(el('p','muted',progress||'任务尚未产生完成结果。'));}
    if(!terminal.has(job.status))body.append(el('p','small muted','此窗口会随任务记录自动更新；关闭窗口后任务仍在后台运行。'));
    $('detail-title').textContent=actionNames[job.action]||'任务详情';replace($('detail-body'),body);state.jobDetailSignature=jobDetailSignature(job);
  }
  async function viewJob(id) {
    showDetail('任务详情',el('p','muted','正在读取任务详情…'));state.openJobId=id;state.jobDetailLoading=true;const request=state.jobDetailRequest;
    try{const job=await api(`/api/jobs/${encodeURIComponent(id)}`);if(request!==state.jobDetailRequest||state.openJobId!==id||!$('detail-dialog').open)return;state.jobs.set(id,{...state.jobs.get(id),...job});renderJobDetail(job);}
    catch(error){if(request===state.jobDetailRequest&&state.openJobId===id&&$('detail-dialog').open){replace($('detail-body'),el('p','inline-error',errorMessage(error)));throw error;}}
    finally{if(request===state.jobDetailRequest)state.jobDetailLoading=false;}
  }
  async function refreshOpenJob(){
    const id=state.openJobId;if(!id||state.jobDetailLoading||!$('detail-dialog').open)return;let job=state.jobs.get(id);if(!job||jobDetailSignature(job)===state.jobDetailSignature)return;
    const request=state.jobDetailRequest;
    try{if(terminal.has(job.status)&&job.result==null){state.jobDetailLoading=true;job={...job,...await api(`/api/jobs/${encodeURIComponent(id)}`)};state.jobs.set(id,job);}
      if(request===state.jobDetailRequest&&state.openJobId===id&&$('detail-dialog').open)renderJobDetail(job);
    }finally{if(request===state.jobDetailRequest)state.jobDetailLoading=false;}
  }

  $('login-form').addEventListener('submit',async e=>{e.preventDefault();$('login-error').hidden=true;$('login-submit').disabled=true;try{const session=await api('/api/login',{method:'POST',body:{password:$('password').value,remember_device:$('login-remember-device').checked===true}});$('password').value='';await startApp(session.csrf);}catch(error){showLogin();$('login-error').textContent=errorMessage(error);$('login-error').hidden=false;}finally{$('login-submit').disabled=false;}});
  $('logout-button').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST',body:{}});state.jobs.clear();state.tracked.clear();state.busy.clear();showLogin();}catch(error){showError(error);}});
  $('mobile-logout').addEventListener('click',()=>$('logout-button').click());
  for(const original of document.querySelectorAll('.sidebar nav > *')){const item=original.cloneNode(true);item.removeAttribute('id');for(const child of item.querySelectorAll('[id]'))child.removeAttribute('id');$('more-links').append(item);}
  $('mobile-more').addEventListener('click',()=>{$('more-dialog').showModal();});

  for(const b of document.querySelectorAll('[data-page]'))b.addEventListener('click',e=>{e.preventDefault();showPage(b.dataset.page);});for(const b of document.querySelectorAll('[data-goto]'))b.addEventListener('click',()=>showPage(b.dataset.goto));
  window.addEventListener('popstate',historyNavigation);window.addEventListener('hashchange',historyNavigation);
  $('dismiss-error').addEventListener('click',()=>{$('global-error').hidden=true;});
  $('refresh-market').addEventListener('click',()=>submitJob('refresh',{},$('refresh-market')).catch(showError));
  $('auto-refresh').addEventListener('change',()=>{const enabled=$('auto-refresh').checked;changeSettings({auto_refresh:enabled},enabled?'已开启行情与策略参考自动更新。':'已暂停行情与参考自动更新；自动模拟开关保持原设置。').catch(()=>{});});
  $('auto-simulate').addEventListener('change',()=>{const enabled=$('auto-simulate').checked;changeSettings({auto_simulate:enabled},enabled?'已开启全部未暂停账户的后台自动模拟。':'已暂停全局自动模拟；行情与参考仍按各自开关运行。').catch(()=>{});});
  setInterval(()=>{if(state.authenticated)schedulerTick();},1000);
  $('reference-group').addEventListener('change',()=>{state.referenceEdited=true;fillStrategies($('reference-group').value,'reference-strategy');replace($('reference-result'),empty('参考策略已切换','点击计算参考，获取这个策略对应的配置。',true));});
  $('reference-strategy').addEventListener('change',()=>{state.referenceEdited=true;replace($('reference-result'),empty('参考策略已切换','点击计算参考，获取这个策略对应的配置。',true));});
  $('reference-capital').addEventListener('input',()=>{state.referenceEdited=true;replace($('reference-result'),empty('参考本金已修改','点击计算参考，以当前预算重新计算配置。',true));});
  $('reference-form').addEventListener('submit',e=>{e.preventDefault();const capital=number($('reference-capital').value);if(capital===null||capital<1000){showError('请输入不少于1,000元的有效本金。');return;}state.referenceEdited=true;replace($('reference-result'),empty('正在计算参考','使用已知行情计算，在任务记录中可查看进度。',true));submitJob('reference',{group:$('reference-group').value,strategy:$('reference-strategy').value,capital},e.submitter).catch(error=>{replace($('reference-result'),empty('参考未能生成',errorMessage(error),true));showError(error);});});
  $('export-history').addEventListener('click',()=>submitJob('history_export',{},$('export-history')).catch(showError));$('export-quotes').addEventListener('click',()=>submitJob('quotes_export',{},$('export-quotes')).catch(showError));
  $('full-backup').addEventListener('click',()=>submitJob('full_backup',{},$('full-backup')).catch(showError));
  $('new-account').addEventListener('click',openCreate);$('create-group').addEventListener('change',configureCreate);$('create-strategy').addEventListener('change',adjustCreateEarliest);
  $('create-form').addEventListener('submit',async e=>{e.preventDefault();if(state.createPending||!state.settingsReadOk||!$('create-confirm').checked)return;$('create-error').hidden=true;const params={group:$('create-group').value,name:$('create-name').value.trim(),strategy:$('create-strategy').value,capital:number($('create-capital').value),start:$('create-start').value};state.createDraft={...params};if(!params.name||params.capital===null||params.capital<1000||!params.start){$('create-error').textContent='请填写账户名称、不少于1,000元的有效本金，并选择起始日期。';$('create-error').hidden=false;setCreatePending(false);return;}setCreatePending(true);try{const job=await submitJob('create',params);if(!job)setCreatePending(false);}catch(error){$('create-error').hidden=false;if(state.createJobId){$('create-error').textContent=`任务已接收，读取结果暂未完成：${errorMessage(error)} 可收起查看任务，系统会继续核对。`;state.busy.set(jobKey('create',params),state.createJobId);setCreatePending(true);schedulePoll(500);}else{$('create-error').textContent=errorMessage(error);setCreatePending(false);}}});
  for(const event of ['input','change'])$('create-form').addEventListener(event,e=>{if(e.target.id==='create-confirm'||state.createPending)return;state.createDraft={group:$('create-group').value,strategy:$('create-strategy').value};updateCreateReview();setCreatePending(false);});
  $('create-discard').addEventListener('click',()=>{if(state.createPending)return;state.createDraft=null;$('create-form').reset();$('create-group').value=state.group;configureCreate();updateCreateReview();setCreatePending(false);});
  $('create-background').addEventListener('click',()=>{if(!state.createJobId)return;$('create-dialog').close();showPage('tasks');});
  $('create-dialog').addEventListener('cancel',e=>{if(state.createPending&&!state.createJobId)e.preventDefault();});
  $('detail-dialog').addEventListener('close',()=>{openSignalRow=null;clearOpenJob();});
  for(const b of document.querySelectorAll('[data-close]'))b.addEventListener('click',()=>{if(b.dataset.close==='create-dialog'&&state.createPending&&!state.createJobId)return;$(b.dataset.close).close();});
  $('reload-accounts').addEventListener('click',()=>loadAccounts().catch(showError));$('reload-tasks').addEventListener('click',()=>pollJobs());
  $('deleted-accounts').addEventListener('click',()=>showDeletedAccounts().catch(showError));
  $('featured-refresh').addEventListener('click',loadSignals);
  $('featured-all').addEventListener('click',()=>showPage('signals'));
  document.addEventListener('etf-language-change',renderFeatured);
  $('signals-refresh').addEventListener('click',loadSignals);
  $('signals-clear').addEventListener('click',()=>{$('signals-group').value='all';$('signals-status').value='all';$('signals-search').value='';renderSignals();});
  $('signals-group').addEventListener('change',renderSignals);$('signals-status').addEventListener('change',renderSignals);$('signals-search').addEventListener('input',renderSignals);
  $('apply-account-update').addEventListener('click',()=>applyPendingAccountUpdate(true));$('account-detail').addEventListener('focusout',()=>setTimeout(()=>applyPendingAccountUpdate(),0));$('reference-form').addEventListener('focusout',()=>setTimeout(()=>followAutomaticReference(state.overview?.reference),0));
  $('compare-group').addEventListener('change',applyCompareGroup);
  $('compare-form').addEventListener('submit',e=>{e.preventDefault();const params={group:$('compare-group').value,start:$('compare-start').value,end:$('compare-end').value,capital:number($('compare-capital').value)};if(params.end<=params.start){showError('结束日期需要晚于开始日期。');return;}submitJob('compare',params,e.submitter).catch(showError);});
  $('import-account').addEventListener('click',()=>{$('import-file').accept=state.group==='seven'?'.json':'.zip';$('import-file').value='';$('import-file').click();});
  $('import-file').addEventListener('change',async()=>{const file=$('import-file').files[0];if(!file)return;if(file.size>25*1024*1024){showError('备份超过25 MiB，请选择较小的完整备份或使用本机程序恢复。');return;}const group=state.group,form=new FormData();form.append('file',file);$('import-account').disabled=true;try{const upload=await api('/api/upload',{method:'POST',body:form,form:true});await submitJob('import',{group,upload_id:upload.upload_id});}catch(error){showError(error);}finally{$('import-account').disabled=false;}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.authenticated){schedulePoll(100);scheduleSettingsPoll(100);}});
  window.ETFResearchHost={api,toast,isAuthenticated:()=>state.authenticated,page:()=>state.page};
  (async()=>{try{const session=await api('/api/session');if(session.authenticated)await startApp(session.csrf);else showLogin();}catch(error){showLogin();$('login-error').textContent=errorMessage(error);$('login-error').hidden=false;}})();
})();
