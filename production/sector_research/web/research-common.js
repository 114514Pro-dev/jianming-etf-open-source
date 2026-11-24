(() => {
  'use strict';
  const base = String(window.RESEARCH_BASE || '').replace(/\/$/, '');
  const url = path => `${base}${path}`;
  let runtimePromise;
  async function request(path, options = {}) {
    const response = await fetch(url(path), {cache:'no-store', ...options, headers:{Accept:'application/json', ...(options.headers || {})}});
    let body; try { body = await response.json(); } catch { throw new Error(`服务返回无法读取的资料（HTTP ${response.status}）`); }
    if (!response.ok) throw new Error(typeof body.error === 'string' ? body.error : body.error?.message || body.message || (typeof body.detail==='string'?body.detail:null) || `服务返回 HTTP ${response.status}`);
    return body;
  }
  const runtime = () => runtimePromise ||= request('/api/runtime').catch(error => {runtimePromise = null; throw error;});
  async function post(path, body, signal) {
    const config = await runtime();
    if (!config.csrf_token) throw new Error('运行时安全令牌缺失，请重新打开页面。');
    return request(path, {method:'POST', signal, headers:{'Content-Type':'application/json','X-Research-Token':config.csrf_token}, body:JSON.stringify(body)});
  }
  function download(name, data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json;charset=utf-8'});
    const objectUrl = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = objectUrl; a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
  function time(v) { if (!v) return '尚无记录'; const d = new Date(v); return Number.isNaN(d.getTime()) ? String(v) : new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(d) + ' 上海时间'; }
  function verificationNotice(s) {
    const pending=Array.isArray(s?.pending_review)?s.pending_review.length:0;
    return pending?`待核验（${pending}项）：相关资料核验尚未完成。本页仍使用已发布的资料版本；计算完成不表示待核验事项已经解决。请展开下方记录查看具体原因。`:'';
  }
  window.Research = {url, request, post, runtime, download, time, verificationNotice, dataStatus:null};
  const mount = document.querySelector('[data-update-widget]');
  document.querySelectorAll('.module-nav a').forEach(a => {const path = a.getAttribute('href'); if (path?.startsWith('/') && base) a.href = url(path);});
  if (!mount) return;
  const el = (tag, text, cls) => {const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const heading=el('div',undefined,'update-heading'), title=el('strong','行情资料管理'), label=el('span','正在读取状态…','status-pill');heading.append(title,label);
  const description=el('p','页面计算使用同一已发布资料版本。行情日期、联网检查时间与策略计算时间分别显示。','update-description');
  const dates=el('div',undefined,'update-dates'), through=el('span'), expected=el('span'), checked=el('span'), success=el('span');dates.append(through,expected,checked,success);
  const actions=el('div',undefined,'update-actions'), check=el('button','检查并更新行情'), toggle=el('button','自动检查：读取中'), reload=el('button','读取已发布资料');
  for(const b of [check,toggle,reload])b.type='button';actions.append(check,toggle,reload);
  const note=el('p','更新可用行情需同时通过数据与公司行动核验；自动检查开关与历史模拟相互独立。','update-note'), error=el('p',undefined,'message error');error.hidden=true;
  const review=el('details'), reviewTitle=el('summary','待核验事项与资料来源'), reviewBody=el('div');review.append(reviewTitle,reviewBody);review.hidden=true;
  const reviewWarning=el('p',undefined,'message warning');reviewWarning.hidden=true;reviewWarning.setAttribute('role','status');
  mount.append(heading,description,reviewWarning,dates,actions,note,error,review);
  let status=null, serial=0, timer, mutation=false, renderedVersion=null;
  function render(s) {
    status=s;const verification=verificationNotice(s);label.textContent=`${verification?'待核验 · ':''}${s.message || s.state || '状态未知'}`;
    reviewWarning.textContent=verification;reviewWarning.hidden=!verification;
    mount.classList.toggle('update-warning', Boolean(verification) || !s.fully_usable || ['failed','store_invalid'].includes(s.state));
    through.textContent=`已发布行情至：${s.data_through || '未知'}`;expected.textContent=`当前应完成日：${s.expected_date || '未知'}`;
    checked.textContent=`最近检查：${time(s.last_attempt_at)}`;success.textContent=`最近成功检查：${time(s.last_success_at)}`;
    toggle.textContent=`自动检查：${s.automatic_enabled ? '已开启（约30分钟）' : '已暂停'}`;toggle.setAttribute('aria-pressed',String(Boolean(s.automatic_enabled)));
    check.textContent=s.running?'行情核对中…':'检查并更新行情';check.disabled=Boolean(s.running||mutation);toggle.disabled=mutation;
    const items=[...(s.pending_review || []),...(s.sources || []).map(v=>typeof v==='string'?v:JSON.stringify(v))];
    reviewBody.replaceChildren(...items.map(v=>el('p',typeof v==='string'?v:JSON.stringify(v))));review.hidden=!items.length;
    note.textContent=`公司行动核验至 ${s.action_verified_through || '未知'}；交易日历至 ${s.calendar_verified_through || '未知'}。暂停自动检查不打断已经开始的一次核对。${s.error ? ` 最近错误：${s.error}` : ''}`;
    const published=s.data_version || s.generation;
    if(renderedVersion && published && published!==renderedVersion) {reload.classList.add('button-primary');reload.textContent='新资料已发布 · 点击重读';}
    if(!renderedVersion)renderedVersion=published;
    window.Research.dataStatus=s;window.dispatchEvent(new CustomEvent('research-data-status',{detail:s}));
  }
  function schedule() {clearTimeout(timer);timer=setTimeout(refresh,status?.running?2000:30000);}
  async function refresh() {const id=++serial;try {const s=await request('/api/data-status');if(id!==serial)return;render(s);error.hidden=true;}catch(e){if(id!==serial)return;mount.classList.add('update-warning');label.textContent=status?'旧状态 · 本次读取失败':'行情状态读取失败';error.textContent=e.message;error.hidden=false;}finally{if(id===serial)schedule();}}
  async function mutate(path,body) {++serial;clearTimeout(timer);mutation=true;check.disabled=true;toggle.disabled=true;try{const s=await post(path,body);render(s);error.hidden=true;}catch(e){error.textContent=`设置或更新请求失败：${e.message}`;error.hidden=false;}finally{mutation=false;await refresh();}}
  check.addEventListener('click',()=>mutate('/api/data-update',{}));
  toggle.addEventListener('click',()=>{if(status)mutate('/api/data-settings',{enabled:!status.automatic_enabled});});
  reload.addEventListener('click',()=>{window.dispatchEvent(new CustomEvent('research-data-reload'));reload.classList.remove('button-primary');reload.textContent='读取已发布资料';renderedVersion=status?.data_version || status?.generation;});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!mutation)refresh();});
  refresh();
})();
