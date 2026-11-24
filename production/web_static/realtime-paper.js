'use strict';
(() => {
  // The host owns authentication and CSRF. Transport methods never hold credentials.
  const state={root:null,transport:null,toast:null,strategy:'D0',active:false,ready:false,busy:false,loading:false,dirty:false,creating:false,timer:null,epoch:0,data:null,id:'',revision:null,uncertain:null,readAt:null,pnlFromCommand:false};
  const strategies=['D0','D0I-BOND-WW'];
  function weeklyStrategy(){return state.strategy==='D0I-BOND-WW';}
  function strategyName(){return weeklyStrategy()?'D0I-BOND-WW 周线择债':'D0 前瞻模拟';}
  const fields={};
  const decisionSelections=new Map(),historyViews=new Map(),priceViews=new Map(),pnlHistoryViews=new Map();
  const emailDraft={generation:0,request:0,loading:false,saving:false,ready:false,data:null,dirty:false,preview:false};
  // Explicit opt-in fixed UI text. Account/security names and historical data stay raw.
  const FIXED=Symbol('rtp-fixed-text'),fixedNodes=new Map();let building=false;
  function fixedSource(value){return value&&typeof value==='object'&&value[FIXED]?value[FIXED].source:value;}
  function fixed(source,values={},englishKey=null){source=String(fixedSource(source));return {[FIXED]:{source,values,englishKey},toString(){const english=window.ETF_I18n?.language==='en',key=english&&englishKey?englishKey:source,local=window.ETF_PAPER_EN||{},global=window.ETF_EN||{};const text=english?(Object.hasOwn(local,key)?local[key]:Object.hasOwn(global,key)?global[key]:source):source;return text.replace(/\{([a-z_]+)\}/g,(match,key)=>Object.hasOwn(values,key)?String(values[key]):match);}};}
  function displayText(target,value,remember=false){target.textContent=String(value);if(building||remember){if(value&&typeof value==='object'&&value[FIXED])fixedNodes.set(target,value);else fixedNodes.delete(target);}}
  function uiError(value){const error=new Error(String(value));if(value&&typeof value==='object'&&value[FIXED])error[FIXED]=value;return error;}
  const pending=new Set(['pending','waiting','open']);
  const statusLabels={pending:fixed('待执行'),waiting:fixed('等待报价'),open:fixed('待执行'),filled:fixed('整单模拟估计成交'),cancelled:fixed('已撤销'),canceled:fixed('已撤销'),rejected:fixed('已拒绝'),expired:fixed('已到期')};
  const reasons={quote_missing:fixed('等待报价'),quote_stale:fixed('行情过期，等待新鲜报价'),quote_before_submission:fixed('等待提交后的报价'),quote_future:fixed('行情时间在未来，等待核对'),quote_out_of_order:fixed('行情乱序，等待有效报价'),same_second:fixed('行情与提交同秒，等待下一秒报价'),activity_pending:fixed('等待连续两份有效报价及量额推进'),market_closed:fixed('非连续竞价时段，等待'),rules_unknown:fixed('交易规则待核对'),suspended:fixed('明确停牌，等待'),signal_stale:fixed('收盘目标过旧，等待确认'),clock_anomaly:fixed('时钟异常，等待核对')};
  const collectionReasons={"quotes_collection_failed":"报价采集失败，连续报价计数已清除；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。","quotes_collection_state_invalid":"报价采集状态无效，等待核对与恢复；恢复后须重新取得故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。","quote_precedes_collection_failure":"当前报价的行情源时间或接收时间不晚于采集故障时点，不能用于恢复；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。"};
  const collectionRecoveryNote="采集故障会清除连续报价计数。恢复后须重新取得同标的、同来源的两份新鲜有效报价：行情源时间和接收时间均须晚于故障时点并递增，累计成交量和成交额均须推进，委托提交后的时间要求与连续竞价窗口仍适用。历史报价或过去已通过的活动门槛不能证明当前已恢复；满足条件仅允许报价驱动的整单模拟估计，不代表真实成交、可成交数量或券商执行。";
  const rejectedCodes=new Set(['INVALID_REQUEST','INVALID_CAPITAL','ACCOUNT_NOT_FOUND','ORDER_NOT_FOUND','IDEMPOTENCY_CONFLICT','CAPITAL_LOCKED','INVALID_STATE']);
  function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)displayText(n,text);return n;}
  function str(value,fallback=fixed('未记录')){return value===undefined||value===null||value===''?fallback:String(value);}
  const sourceReasons={"quotes_collection_failed":"报价采集失败，连续报价计数已清除；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。","quotes_collection_state_invalid":"报价采集状态无效，等待核对与恢复；恢复后须重新取得故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。","quote_precedes_collection_failure":"当前报价的行情源时间或接收时间不晚于采集故障时点，不能用于恢复；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。","not_observed":"尚未观察到有效资料","context_missing":"尚未记录来源观察状态，等待核对","quotes_missing":"等待当日新鲜报价","quotes_stale":"报价过期，等待后续新鲜报价","quotes_invalid":"报价无效，等待有效资料","quote_queue_delay":"报价接收后的处理延迟过大","daily_data_missing":"缺少确认日线资料","daily_data_invalid":"确认日线资料无效","confirmed_daily_data_missing":"缺少应有确认日资料","calendar_unavailable":"交易日历不在已核验范围","historical_data_revision":"历史资料修订，等待核对","corporate_action_review_required":"公司行动资料需要核对","holdings_history_unverified":"持仓历史资料需要核对","source_unavailable":"数据来源暂不可用","source_read_failed":"读取资料失败，等待重试","worker_iteration_failed":"观察服务异常，等待恢复"};
  Object.assign(sourceReasons,{"history_baseline_missing": "找不到与原信号一致的可信历史快照，保留账本并等待核对", "history_anchor_invalid": "原信号历史凭据无效，等待核对", "history_checkpoint_invalid": "D0 历史留存凭据校验失败，等待核对", "history_checkpoint_write_failed": "D0 历史留存凭据保存失败，等待恢复", "history_continuity_gap": "历史行情日期存在缺失或插入，等待核对"});
  function isCollectionText(value){value=fixedSource(value);return Object.hasOwn(collectionReasons,value)||Object.values(collectionReasons).includes(value);}
  function knownReason(code){return typeof code==='string'&&(Object.hasOwn(collectionReasons,code)||Object.hasOwn(sourceReasons,code)||Object.hasOwn(reasons,code));}
  function reasonText(code){return Object.hasOwn(collectionReasons,code)?fixed(collectionReasons[code]):Object.hasOwn(sourceReasons,code)?fixed(sourceReasons[code]):reasons[code];}
  function waitingReason(value,code,fallback=fixed('未提供'),allowIdentifier=false){
    if(typeof code==='string'&&code){if(!knownReason(code))return str(value,fallback);const expected=reasonText(code),source=fixedSource(expected);return value===undefined||value===null||value===''||value===code||value===source?expected:str(value,fallback);}
    return allowIdentifier&&knownReason(value)?reasonText(value):str(value,fallback);
  }
  function accountWaitingReason(a){
    if(typeof a.reason_code==='string'&&a.reason_code)return waitingReason(a.waiting_reason,a.reason_code,'');
    const service=state.data?.service||{};
    if(service.status!=='ready'&&knownReason(service.reason_code)&&typeof a.waiting_reason==='string'&&a.waiting_reason===service.waiting_reason)return waitingReason(a.waiting_reason,service.reason_code,'');
    return str(a.waiting_reason,'');
  }
  function decimal(value,min=0){
    const raw=str(value,'');if(!/^-?\d+(\.\d+)?$/.test(raw))return fixed('待核对');
    const [integer,fraction='']=raw.split('.');return integer.replace(/\B(?=(\d{3})+(?!\d))/g,',')+(fraction||min?'.'+fraction.padEnd(min,'0'):'');
  }
  function time(value){
    if(!value)return fixed('未记录');const raw=String(value);
    if(!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(raw))return raw+fixed('（时区未标明，待核对）');
    const at=new Date(raw);if(!Number.isFinite(at.valueOf()))return fixed('时间无效，待核对');
    const fraction=raw.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1];
    return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(at)+(fraction?'.'+fraction:'')+fixed(' 北京时间')+(fraction?fixed('（小数秒 {digits} 位）',{digits:fraction.length}):fixed('（秒级）'));
  }
  function age(value){
    if(!value||!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(String(value)))return fixed('无法计算');
    const delta=Date.now()-new Date(value).valueOf();if(!Number.isFinite(delta))return fixed('无法计算');
    if(delta<0)return fixed('未来时间，等待核对');return fixed('{seconds} 秒（本机显示年龄）',{seconds:(delta/1000).toFixed(1)});
  }
  function line(parent,label,value){const row=node('div','rtp-line');row.append(node('dt','',label),node('dd','',value));parent.append(row);}
  function dates(parent,data,keys){const list=node('dl','rtp-times');const labels={signal_at:fixed('信号确认'),submitted_at:fixed('委托提交'),eligible_at:fixed('撮合资格起点'),quote_at:fixed('行情源时间'),received_at:fixed('行情接收'),matched_at:fixed('估计成交记账'),expires_at:fixed('委托到期'),started_at:fixed('本轮启动')};for(const key of keys)line(list,`${labels[key]} · ${key}`,time(data[key]));parent.append(list);}
  function button(label,handler,cls='button secondary'){const b=node('button',cls,label);b.type='button';b.addEventListener('click',()=>Promise.resolve().then(handler).catch(showError));return b;}
  function message(text){displayText(fields.result,text,true);fields.result.hidden=false;state.toast?.(String(text));}
  function showError(error){if(!state.active)return;displayText(fields.error,error instanceof Error?(error[FIXED]??error.message):String(error),true);fields.error.hidden=false;}
  function account(){return state.data?.accounts?.find(a=>String(a.id)===state.id);}
  function knownAccount(){return ['running','paused','stopped'].includes(account()?.status);}
  function compareInteger(a,b){a=a.replace(/^0+(?=\d)/,'');b=b.replace(/^0+(?=\d)/,'');return a.length===b.length?(a===b?0:a>b?1:-1):a.length>b.length?1:-1;}
  function sameCash(a,b){const normalize=v=>String(v).replace(/^0+(?=\d)/,'').replace(/\.0+$/,'').replace(/(\.\d*?[1-9])0+$/,'$1');return normalize(a)===normalize(b);}
  function positiveCash(raw){if(!/^\d{1,10}(\.\d{1,2})?$/.test(raw)||!/[1-9]/.test(raw))return false;const [whole,fraction='']=raw.split('.');return compareInteger(whole+fraction.padEnd(2,'0'),'100000000000')<=0;}
  function controls(){
    if(!state.root)return;const a=account(),blocked=!state.active||state.busy||!state.ready||!!state.uncertain||!['ready','degraded'].includes(state.data?.service?.status),create=state.creating||!a;
    const switchingBlocked=!state.active||state.busy||!!state.uncertain||state.dirty||emailDraft.dirty||emailDraft.saving;
    for(const item of fields.strategyButtons||[]){item.button.disabled=switchingBlocked;item.button.setAttribute('aria-pressed',String(item.strategy===state.strategy));item.button.classList.toggle('active',item.strategy===state.strategy);}
    if(fields.strategyHint)fields.strategyHint.textContent=state.busy||emailDraft.saving?fixed('操作正在返回，完成后可切换策略。'):state.uncertain?fixed('上次操作结果待核对，请先刷新当前策略。'):state.dirty||emailDraft.dirty?fixed('有未保存草稿，请先保存，或放弃草稿后切换。'):fixed('两种策略独立记账；切换仅查看，不创建或启动账户。');
    if(fields.discardDraft){fields.discardDraft.hidden=!(state.dirty||emailDraft.dirty);fields.discardDraft.disabled=state.busy||emailDraft.saving||!!state.uncertain;}
    fields.selector.disabled=!state.active||state.busy||state.loading;
    fields.new.disabled=blocked||!!state.data?.accounts?.length;
    fields.refresh.disabled=!state.active||state.busy||state.loading;
    fields.name.disabled=blocked||!create;
    const capitalAllowed=a?.can_edit_capital===true&&['stopped','paused'].includes(a?.status)&&!(a?.fills?.length);
    fields.cash.disabled=blocked||(!create&&!capitalAllowed);
    fields.save.disabled=blocked||(create&&!!state.data?.accounts?.length)||(!create&&!capitalAllowed);
    fields.save.textContent=state.busy?fixed('正在核对…'):create?fixed('创建账户（默认停止）'):fixed('保存本金');
    fields.start.disabled=blocked||create||!knownAccount()||a.status==='running'||a.can_start!==true||state.dirty;
    fields.pause.disabled=blocked||create||!knownAccount()||a.status!=='running'||a.can_pause!==true;
    fields.dirty.hidden=!state.dirty;fields.start.hidden=create;fields.pause.hidden=create;fields.createConfirmation.hidden=!create;fields.confirm.required=create;fields.confirm.disabled=blocked;fields.settingsShortcut.textContent=create?fixed('设置本金与起点'):fixed('修改账户设置');
    fields.readWarning.hidden=state.ready||!state.data;fields.readWarning.textContent=fixed('当前状态待核对，以下为上次成功读取的记录；写操作已禁用。');
    fields.actionHint.textContent=state.uncertain?fixed('上次操作结果仍不明，写入暂锁定；请刷新核对，避免用新请求重复操作。'):!state.ready?(state.loading?fixed('正在读取账户状态，请稍候。'):fixed('当前状态读取未成功，写操作已禁用；请刷新状态核对。')):!['ready','degraded'].includes(state.data?.service?.status)?fixed('模拟服务状态待核对；暂不能写入，请刷新状态。'):state.dirty?fixed('有未保存草稿，请先保存本金或重新选择账户再启动。'):create?fixed('创建后默认停止，确认状态后可手动启动。'):!knownAccount()?fixed('账户状态待核对，暂不能操作。'):a.status==='running'?fixed('暂停会撤销剩余委托并释放冻结，已记账的模拟估计成交保留。'):str(a.action_reason,fixed('启动后从当前时刻向前运行，等待委托提交后的有效报价。'));
    for(const item of fields.cancelButtons||[])item.button.disabled=blocked||!pending.has(item.status)||item.canCancel!==true;
    if(fields.alertSnapshot){fields.alertSnapshot.hidden=!a||!state.data?.trade_alerts;fields.alertSnapshot.textContent=state.busy||state.uncertain||!state.ready?fixed('提醒记录来自最近一次快照；当前状态待核对。'):state.loading?fixed('正在刷新提醒状态；以下为最近一次快照记录。'):fixed('提醒状态以本次账户快照为准，请核对状态生成时间。');}
    emailDraftControls();
    fields.wechatView?.update({
      strategy:state.strategy, account:a, active:state.active,
      verified:!blocked && !state.loading && knownAccount(),
      snapshotReady:state.ready
    });
    for(const item of [...(fields.alertReferences||[]),...(fields.emailPreviewReferences||[])]){const temporary=item.reference==='current_reference'&&(!state.active||!state.ready||state.busy||state.loading||state.uncertain),reference=temporary?'needs_review':item.reference;item.badge.textContent=alertReferenceLabel(reference);item.badge.className='pill rtp-alert-state rtp-alert-'+reference;item.description.textContent=alertExplanation(item,reference,temporary);}
    if(fields.signalSummary&&fields.signalSummaryReadState!==signalSummaryReadState())renderSignalSummary(a);
    if(fields.holdingLogic&&fields.holdingReadState!==holdingReadState())renderHoldingLogic(a);
    if(fields.accountPnl&&fields.pnlReadState!==holdingReadState())renderAccountPnl(fields.accountPnl,a);
    if(fields.pnlHistory&&fields.pnlHistoryReadState!==pnlHistoryReadState())renderAccountPnlHistory(fields.pnlHistory,a);
    window.RealtimePaperComparison?.update(a,{current:holdingSnapshotCurrent()});
  }
  function build(){building=true;fixedNodes.clear();
    const root=state.root;root.classList.add('realtime-paper');root.replaceChildren();
    const heading=node('div','section-heading'),copy=node('div');fields.heading=node('h2','',fixed('D0 前瞻模拟账户'));fields.strategyDescription=node('p');copy.append(fields.heading,fields.strategyDescription);fields.refresh=button(fixed('刷新状态'),()=>refresh());heading.append(copy,fields.refresh);root.append(heading);
    const strategyChooser=node('section','panel rtp-strategy-chooser');strategyChooser.setAttribute('aria-label',String(fixed('选择前瞻策略')));const strategyRow=node('div','button-row');fields.strategyButtons=strategies.map(strategy=>{const b=button(strategy==='D0'?fixed('D0 · 四资产'):fixed('D0I-BOND-WW · 周线择债'),()=>switchStrategy(strategy));b.dataset.paperStrategy=strategy;b.setAttribute('aria-pressed',String(strategy===state.strategy));strategyRow.append(b);return {strategy,button:b};});fields.strategyHint=node('p','small muted');fields.discardDraft=button(fixed('放弃未保存草稿'),()=>{if(state.busy||state.uncertain||emailDraft.saving)return;state.dirty=false;state.creating=false;emailDraft.dirty=false;emailDraft.preview=false;fields.confirm.checked=false;render();controls();},'text-button');strategyChooser.append(strategyRow,fields.strategyHint,fields.discardDraft);
    const notice=node('aside','rtp-notice');notice.append(node('strong','',fixed('第一阶段 · 报价驱动整单估计')),node('p','',fixed('公共报价没有盘口，停牌与可交易状态未核验。连续两份提交后有效报价及量额推进只是估计活动门槛，不能证明真实流动性；整单估计隐含整单流动性假设。')),node('p','',fixed('账户从启动时刻向前运行：09:35 启动不会补记 09:30 开盘成交。费用和滑点为模拟假设。')),(fields.recoveryNote=node('p','',fixed(collectionRecoveryNote))));root.append(notice);
    fields.error=node('p','inline-error rtp-error');fields.error.hidden=true;fields.error.setAttribute('role','alert');fields.result=node('p','rtp-result');fields.result.hidden=true;fields.result.setAttribute('role','status');fields.result.setAttribute('aria-live','polite');root.append(fields.error,fields.result);
    const layout=node('div','rtp-layout'),form=node('form','panel rtp-form');fields.form=form;form.autocomplete='off';form.append(node('h3','',fixed('独立账户设置')));
    const chooser=node('div','rtp-chooser');fields.selector=node('select');fields.selector.id='rtp-account';const caption=node('label','',fixed('选择前瞻模拟账户'));caption.htmlFor='rtp-account';chooser.append(caption,fields.selector);fields.new=button(fixed('新建账户'),()=>{if(state.busy||!state.ready||state.uncertain||state.data?.accounts?.length)return;state.creating=true;state.dirty=false;fields.name.value=strategyName();fields.cash.value='100000.00';fields.confirm.checked=false;controls();});fields.new.setAttribute('aria-describedby','rtp-account-limit');chooser.append(fields.new);form.append(chooser);const accountLimit=node('p','small muted',fixed('每种策略最多一个独立账户，已有账户后不再新建。'));accountLimit.id='rtp-account-limit';form.append(accountLimit);
    for(const [key,label,type,value] of [['name',fixed('账户名称'),'text','D0 前瞻模拟'],['cash',fixed('本金（元）'),'text','100000.00']]){const wrap=node('div','rtp-field'),caption=node('label','',label),input=node('input');input.id='rtp-'+key;input.name=key;input.type=type;input.value=value;input.required=true;input.maxLength=key==='name'?80:13;input.autocomplete='off';caption.htmlFor=input.id;fields[key]=input;wrap.append(caption,input);form.append(wrap);}
    fields.createConfirmation=node('label','confirm-choice');fields.confirm=node('input');fields.confirm.type='checkbox';fields.confirm.id='rtp-confirm-start';fields.createConfirmation.append(fields.confirm,node('span','',fixed('我已确认当前所选策略与本金；从手动启动时刻开始，不补跑历史。创建后默认停止，启动后按所选规则向前模拟。')));form.append(fields.createConfirmation);
    fields.cash.inputMode='decimal';fields.cash.setAttribute('aria-describedby','rtp-capital-hint');const hint=node('p','small muted',fixed('本金仅在停止、尚无模拟估计成交且后端允许时可配置。金额最多两位小数，上限10亿元。'));hint.id='rtp-capital-hint';form.append(hint);
    fields.dirty=node('p','rtp-dirty small',fixed('有未保存的修改；状态展示仍按已保存账户。'));fields.dirty.hidden=true;form.append(fields.dirty);
    const actions=node('div','button-row rtp-actions');fields.save=node('button','button primary',fixed('创建账户（默认停止）'));fields.save.id='rtp-save';fields.save.type='submit';fields.start=button(fixed('启动模拟'),()=>mutate('start'));fields.pause=button(fixed('暂停并撤余单'),()=>mutate('pause'));actions.append(fields.save,fields.start,fields.pause);form.append(actions);fields.actionHint=node('p','small muted');form.append(fields.actionHint);
    form.addEventListener('submit',e=>{e.preventDefault();save().catch(showError);});
    for(const key of ['name','cash'])fields[key].addEventListener('input',()=>{state.dirty=true;fields.confirm.checked=false;controls();});
    fields.selector.addEventListener('change',()=>{if(state.busy)return;if(state.data?.accounts?.length&&!state.data.accounts.some(a=>String(a.id)===fields.selector.value)){fields.selector.value=state.id;return;}state.id=fields.selector.value;state.creating=false;state.dirty=false;render();refresh();});
    const summary=node('section','panel rtp-summary');summary.append(node('h3','',fixed('资产与运行状态')));fields.readWarning=node('p','rtp-wait');fields.readWarning.setAttribute('role','status');fields.summary=node('div');summary.append(fields.readWarning,fields.summary);layout.append(form,summary);root.append(layout);
    const alerts=node('section','panel rtp-section rtp-alerts');alerts.id='rtp-trade-alerts';alerts.append(node('h3','',fixed('当前策略站内交易提醒')),node('p','small muted',fixed('提醒记录来自已提交且可追溯的模拟委托，供核对模拟计划与历史状态。数量、限价和方向均为模拟委托记录。')));fields.alertEmail=node('p','small muted',fixed('邮件推送尚未接入此账户'));fields.alertSnapshot=node('p','small rtp-wait');fields.tradeAlerts=node('div','rtp-cards');alerts.append(fields.alertEmail,fields.alertSnapshot,fields.tradeAlerts);root.append(alerts);
    buildEmailDraft(root);
    for(const [key,title,help] of [['signal',fixed('当前收盘信号与执行计划'),fixed('收盘确认时间、首次可知时间与委托提交时间各自记录。报价不生成新的盘中策略。')],['positions',fixed('持仓与可卖份额'),fixed('缺少有效报价的持仓估值显示待核对，不按零估值。')],['quotes',fixed('账户已接纳报价与数据年龄'),fixed('这是账户最后接纳的报价，用于记录估值与核对成交依据；历史核验阻塞时可能早于最新市场报价。')],['orders',fixed('限价委托'),fixed('买单冻结现金，卖单冻结可卖份额；已撤销或到期的订单不会因迟到报价恢复。')],['fills',fixed('模拟估计成交明细'),fixed('本期整单估计不证明真实排队、市场冲击或可成交数量。')],['events',fixed('模拟事件记录'),fixed('仅显示独立模拟账户事件。')],['rules',fixed('逐标的规则与模拟费率'),fixed('委托冻结时保存规则和费用版本；这里显示响应中的规则和模拟假设。')]]){const section=node('section','panel rtp-section');section.append(node('h3','',title),node('p','small muted',help));fields[key]=node('div','rtp-cards');section.append(fields[key]);root.append(section);}
    // Keep account operations and portfolio records ahead of optional evidence/settings.
    const sections={};for(const key of ['signal','positions','quotes','orders','fills','events','rules']){sections[key]=fields[key].parentElement;sections[key].id='rtp-section-'+key;}
    const mechanics=disclosure(fixed('机制与采集恢复细则'),'rtp-mechanics');while(notice.children.length)mechanics.append(notice.firstElementChild);
    notice.append(node('strong','',fixed('仅模拟估计 · D0与周线择债独立记账')),node('p','',fixed('公共报价无盘口，停牌与可交易状态未核验；整单估计不证明真实流动性。费用与滑点为模拟假设。')));
    const settings=disclosure(fixed('账户设置与邮件草稿（发送未启用）'),'rtp-settings');settings.classList.add('panel');fields.settings=settings;settings.append(form,fields.emailForm.closest('.rtp-email-draft'));
    const operations=node('div','rtp-operation-bar');fields.operations=operations;operations.append(fields.actionHint,fields.start,fields.pause);fields.settingsShortcut=button(fixed('修改账户设置'),()=>{settings.open=true;settings.scrollIntoView({block:'start'});});operations.append(fields.settingsShortcut);
    const evidence=disclosure(fixed('详细依据：信号、报价、事件与规则'),'rtp-evidence');evidence.classList.add('panel');evidence.append(mechanics,sections.signal,sections.quotes,sections.events,sections.rules);
    const alertDetails=disclosure(fixed('站内交易提醒与历史参考'),'rtp-alert-details');alertDetails.classList.add('panel');alertDetails.append(alerts);
    summary.append(operations);layout.remove();
    fields.marketQuotes=node('section','panel rtp-market-quotes');fields.marketQuotes.id='rtp-market-quotes';
    evidence.insertBefore(fields.marketQuotes,sections.quotes);
    fields.signalSummary=node('section','panel rtp-signal-summary');fields.signalSummary.id='rtp-signal-summary';
    fields.pnlHistory=node('section','panel rtp-pnl-history');fields.pnlHistory.id='rtp-pnl-history';
    fields.comparison=node('section','panel rtp-comparison');fields.comparison.id='rtp-comparison';
    fields.holdingLogic=node('section','panel rtp-holding-logic');fields.holdingLogic.id='rtp-holding-logic';
    const wechat=disclosure(fixed('微信提醒'),'rtp-wechat');wechat.classList.add('panel','rtp-wechat');
    fields.wechatView=window.RealtimePaperWechat?.create({panel:wechat,transport:state.transport,node,fixed,compactTime});
    root.replaceChildren(heading,strategyChooser,notice,fields.error,fields.result,summary,fields.signalSummary,fields.pnlHistory,fields.comparison,fields.holdingLogic,sections.positions,sections.fills,sections.orders,alertDetails,settings,evidence);
    if(fields.wechatView)summary.after(wechat);
    window.RealtimePaperComparison?.init({root:fields.comparison,load:(id,strategy)=>state.transport?.comparison?.(id,strategy)});
    building=false;render();controls();
  }
  function disclosure(label,key){const d=node('details','rtp-details');d.dataset.detailKey=key;d.append(node('summary','',label));return d;}
  function compactTime(value){if(!value)return fixed('未记录');if(!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(String(value)))return time(value);const date=new Date(value);return Number.isFinite(date.valueOf())?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium'}).format(date)+fixed(' 北京时间'):time(value);}
  function rationaleNumber(value){if(!['number','string'].includes(typeof value)||typeof value==='string'&&!value.trim())return null;const number=Number(value);return Number.isFinite(number)?number:null;}
  function rationalePercent(value){const number=rationaleNumber(value);return number===null?fixed('待核对'):new Intl.NumberFormat(window.ETF_I18n?.language==='en'?'en-US':'zh-CN',{style:'percent',maximumFractionDigits:2}).format(number);}
  function holdingReadState(){return [state.active,state.ready,state.busy,state.loading,Boolean(state.uncertain)].join(':');}
  function holdingSnapshotCurrent(){return state.active&&state.ready&&!state.loading&&!state.busy&&!state.uncertain;}
  function verifiedHoldings(a){
    if(!Array.isArray(a.holdings))return null;const seen=new Set();
    for(const row of a.holdings){const quantity=rationaleNumber(row?.quantity);if(!row||typeof row.symbol!=='string'||!row.symbol||seen.has(row.symbol)||quantity===null||!Number.isSafeInteger(quantity)||quantity<0)return null;seen.add(row.symbol);}
    return a.holdings;
  }
  function actualHoldingRatio(a,row){
    const equity=rationaleNumber(a.equity),value=row.holding?rationaleNumber(row.holding.value):0,ratio=value!==null&&equity!==null&&equity>0?value/equity:null;
    return holdingSnapshotCurrent()&&a.valuation_status==='fresh'&&row.holdingsKnown&&(!row.holding||row.holding.valuation_status==='fresh')&&ratio!==null&&Number.isFinite(ratio)&&ratio>=0?ratio:null;
  }
  function savedScore(row){const score=rationaleNumber(row.effective_score);return score!==null&&score>=0?new Intl.NumberFormat('en-US',{maximumFractionDigits:3}).format(score):fixed('未记录');}
  function originalNumber(value,digits=3){const number=rationaleNumber(value);return number===null?fixed('未记录'):new Intl.NumberFormat(window.ETF_I18n?.language==='en'?'en-US':'zh-CN',{maximumFractionDigits:digits}).format(number);}
  function originalFlag(value,yes=fixed('是'),no=fixed('否'),unknown=fixed('未记录')){return value===true?yes:value===false?no:unknown;}
  function originalTimingLabel(status){return status==='confirmed'?fixed('保存时序已核对'):status==='invalid'?fixed('保存时序无效，待核对'):fixed('保存时序未完整记录');}
  function historyDay(value){
    if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;
    const timestamp=Date.parse(value+'T00:00:00Z');return Number.isFinite(timestamp)&&new Date(timestamp).toISOString().slice(0,10)===value?timestamp/86400000:null;
  }
  function historySeries(selected,signal,id,frequency,unit,rows){
    const h=selected.indicator_history,none={points:[],status:'unavailable'};
    if(!h)return none;
    if(h.contract_version!=='d0-indicator-history-v1'||h.source!=='confirmed_input_history'||typeof signal.id!=='string'||h.signal_key!==signal.id||h.confirmed_day!==signal.confirmed_day||historyDay(signal.confirmed_day)===null)return {...none,status:'invalid'};
    if(h.status!=='available')return {...none,status:h.status==='unavailable'?'unavailable':'invalid'};
    if(!Array.isArray(h.charts)||h.charts.length>5)return {...none,status:'invalid'};
    const matches=h.charts.filter(c=>c?.id===id);if(!matches.length)return none;if(matches.length!==1)return {...none,status:'invalid'};
    const c=matches[0],basis=id==='trend'?(selected.symbol==='sz159915'?'weekly_adjusted_close_ma50':selected.symbol==='sh518880'?'total_return_ma120':'total_return_ma60'):id==='momentum'||id==='volatility'?'dynamic_total_return':frequency==='weekly'?'confirmed_weekly_indicator':'daily_indicator';
    if(c.frequency!==frequency||c.unit!==unit||c.basis!==basis||!Array.isArray(c.points)||c.points.length>(frequency==='weekly'?104:120))return {...none,status:'invalid'};
    const points=[];let previous=-Infinity;
    for(const p of c.points){
      const day=historyDay(p?.date),available=historyDay(p?.available_on),period=frequency==='weekly'?historyDay(p?.period_end):null;
      if(day===null||available!==day||day<=previous||day>historyDay(signal.confirmed_day)||frequency==='weekly'&&(period===null||period>day)||typeof p.break_before!=='boolean'||!p.values||typeof p.values!=='object'||Array.isArray(p.values))return {...none,status:'invalid'};
      const values={};for(const row of rows){const value=p.values[row.key];values[row.key]=typeof value==='number'&&Number.isFinite(value)&&(id!=='skdj'||value>=0&&value<=100)&&(id!=='volatility'||value>=0)&&(id!=='trend'||value>0)?value:null;}
      points.push({...p,day,values});previous=day;
    }
    return {points,status:'available'};
  }
  function historySvg(tag,attributes={}){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attributes))n.setAttribute(key,String(value));return n;}
  function originalPair(target,{title,rows,className='',selected,signal,id,frequency='daily',unit='indicator',reference=null}){
    const chart=node('section','rtp-original-chart rtp-history-chart '+className);chart.dataset.chartId=id;chart.dataset.frequency=frequency;chart.dataset.asset=selected.symbol;chart.append(node('h6','',title));target.append(chart);
    const key=JSON.stringify([state.id,selected.symbol,id]),identity=JSON.stringify([signal.id,signal.confirmed_day]),ranges=frequency==='weekly'?[26,52,104]:[60,120];
    let view=historyViews.get(key);if(!view||view.identity!==identity){view={identity,range:frequency==='weekly'?52:120,date:null};historyViews.set(key,view);}
    const history=historySeries(selected,signal,id,frequency,unit,rows),points=history.points.slice(-view.range),format=value=>value===null?String(fixed('未记录')):unit==='ratio'?String(rationalePercent(value)):String(originalNumber(value,unit==='percent_points'?4:3))+(unit==='percent_points'?'%':'');
    chart.dataset.historyStatus=history.status;
    const description=node('p','small muted rtp-history-description',fixed('曲线来自该确认信号对应的历史行情指标，不代表逐日保存的交易决定。'));chart.append(description);
    const snapshot=()=>{chart.append(node('p','small muted',fixed('信号保存的确认值')));const list=node('dl','rtp-history-snapshot');for(const row of rows)line(list,row.label,row.value===null?fixed('未记录'):row.format?row.format(row.value):format(row.value));chart.append(list);};
    if(history.status!=='available'||!points.length){chart.append(node('p','rtp-wait rtp-history-empty',fixed('历史指标暂不可用；只展示信号保存的确认值，不补造趋势。')));snapshot();return chart;}
    const controls=node('div','rtp-history-controls'),rangeGroup=node('div','rtp-history-ranges');rangeGroup.setAttribute('role','group');rangeGroup.setAttribute('aria-label',String(fixed('历史显示范围')));
    const markControl=(control,name)=>{control.dataset.historyKey=key;control.dataset.historySignal=identity;control.dataset.historyControl=name;};
    for(const range of ranges){const b=button(fixed(frequency==='weekly'?'{count}周':'{count}日',{count:range}),()=>{view.range=range;renderHoldingLogic(account());},'rtp-history-range');b.dataset.range=String(range);b.setAttribute('aria-pressed',String(range===view.range));markControl(b,'range-'+range);rangeGroup.append(b);}controls.append(rangeGroup,node('span','small muted',fixed(frequency==='weekly'?'周线 · {count} 个观测日':'日线 · {count} 个观测日',{count:points.length})));chart.append(controls);
    const appendTable=()=>{const detail=disclosure(fixed('查看历史数据表'),'history-'+selected.symbol+'-'+id+'-'+identity),wrap=node('div','rtp-history-table-wrap'),table=node('table','rtp-history-table'),caption=node('caption','',String(title)+' · '+String(fixed('历史行情指标'))),head=node('thead'),header=node('tr');header.append(node('th','',fixed('可知日期')));if(frequency==='weekly')header.append(node('th','',fixed('指标周期截至')));for(const row of rows)header.append(node('th','',row.label));header.append(node('th','',fixed('连续性')));for(const th of header.children)th.scope='col';head.append(header);const body=node('tbody');for(const point of points){const tr=node('tr');tr.append(node('th','',point.date));tr.firstChild.scope='row';if(frequency==='weekly')tr.append(node('td','',point.period_end));for(const row of rows)tr.append(node('td','',format(point.values[row.key])));tr.append(node('td','',point.break_before?fixed('缺口后首点'):fixed('—')));body.append(tr);}table.append(caption,head,body);wrap.append(table);wrap.tabIndex=0;markControl(wrap,'table');wrap.setAttribute('aria-label',String(fixed('历史行情指标')));detail.open=Boolean(view.tableOpen);detail.addEventListener('toggle',()=>{if(detail.isConnected)view.tableOpen=detail.open;});wrap.addEventListener('scroll',()=>{if(wrap.isConnected){view.tableTop=wrap.scrollTop;view.tableLeft=wrap.scrollLeft;}});detail.append(wrap);chart.append(detail,node('p','small muted',fixed('横轴按真实可知日期间距排列；缺失值保留空档，不插值、不推算买卖点。')));wrap.scrollTop=view.tableTop||0;wrap.scrollLeft=view.tableLeft||0;};
    if(!points.some(p=>rows.some(row=>p.values[row.key]!==null))){chart.append(node('p','rtp-wait rtp-history-empty',fixed('此范围内缺少有效指标值，可切换范围或查看数据表。')));snapshot();appendTable();return chart;}
    const all=points.flatMap(p=>rows.map(row=>p.values[row.key])).filter(value=>value!==null);if(reference!==null)all.push(reference);
    let low=Math.min(...all),high=Math.max(...all);
    if(id==='skdj'){low=0;high=100;}
    else{if(id==='trix'||id==='momentum'||id==='volatility'){low=Math.min(0,low);high=Math.max(0,high);}const pad=(high-low||Math.max(Math.abs(high),.01))*.1;low=id==='volatility'?0:low-pad;high+=pad;}
    if(!Number.isFinite(low)||!Number.isFinite(high)||!Number.isFinite(high-low)||high<=low){chart.append(node('p','rtp-wait rtp-history-empty',fixed('历史指标暂不可用；只展示信号保存的确认值，不补造趋势。')));snapshot();return chart;}
    const confirmed=historyDay(signal.confirmed_day),start=points[0].day,end=Math.max(confirmed,points.at(-1).day),span=end-start||1,x=day=>12+(day-start)/span*616,y=value=>212-(value-low)/(high-low)*204;
    const figure=node('div','rtp-history-figure'),yAxis=node('div','rtp-history-y-axis'),plot=node('div','rtp-history-plot'),svg=historySvg('svg',{viewBox:'0 0 640 220',preserveAspectRatio:'none',role:'img','aria-label':String(title)});svg.classList.add('rtp-history-svg');plot.append(svg);figure.append(yAxis,plot);chart.append(figure);
    const grid=historySvg('g',{'aria-hidden':'true'});svg.append(grid);
    for(let i=0;i<5;i++){const value=low+(high-low)*i/4,at=y(value),label=node('span','',format(value));label.style.top=at/220*100+'%';yAxis.append(label);grid.append(historySvg('line',{x1:12,x2:628,y1:at,y2:at,class:'rtp-history-grid'}));}
    if(low<0&&high>0)grid.append(historySvg('line',{x1:12,x2:628,y1:y(0),y2:y(0),class:'rtp-history-zero'}));
    if(reference!==null)grid.append(historySvg('line',{x1:12,x2:628,y1:y(reference),y2:y(reference),class:'rtp-history-reference'}));
    const lines=historySvg('g',{'aria-hidden':'true'});svg.append(lines);
    rows.forEach((row,series)=>{let path='',pen=false;const color='rtp-history-series-'+series;points.forEach((point,index)=>{const value=point.values[row.key];if(value===null){pen=false;return;}if(point.break_before)pen=false;path+=(pen?'L':'M')+x(point.day).toFixed(3)+','+y(value).toFixed(3)+' ';const before=points[index-1],after=points[index+1];if((!before||point.break_before||before.values[row.key]===null)&&(!after||after.break_before||after.values[row.key]===null))lines.append(historySvg('circle',{cx:x(point.day),cy:y(value),r:3.5,class:color+' rtp-history-isolated'}));pen=true;});lines.append(historySvg('path',{d:path.trim(),class:color+' rtp-history-line','data-series':row.key}));});
    svg.append(historySvg('line',{x1:x(confirmed),x2:x(confirmed),y1:8,y2:212,class:'rtp-history-confirmation','aria-hidden':'true'}));
    const cursor=historySvg('line',{x1:0,x2:0,y1:8,y2:212,class:'rtp-history-cursor','aria-hidden':'true'}),markers=rows.map((row,index)=>historySvg('circle',{cx:0,cy:0,r:4,class:'rtp-history-series-'+index+' rtp-history-marker','aria-hidden':'true'}));svg.append(cursor,...markers);
    const xAxis=node('div','rtp-history-x-axis');for(const day of [start,Math.round((start+end)/2),end])xAxis.append(node('span','',new Date(day*86400000).toISOString().slice(0,10)));figure.append(xAxis);
    const legend=node('div','rtp-history-legend');rows.forEach((row,index)=>{const entry=node('span','rtp-history-legend-entry'),swatch=node('i','rtp-history-swatch rtp-history-series-'+index);swatch.setAttribute('aria-hidden','true');entry.append(swatch,node('span','',row.label));legend.append(entry);});chart.append(legend,node('p','small muted rtp-history-confirmation-label',fixed('竖虚线：信号确认日 {day}',{day:signal.confirmed_day})));
    if(points.length===1)chart.append(node('p','small muted',fixed('只有一个历史观测点，不构成趋势。')));
    const controlId='rtp-history-'+selected.symbol+'-'+id,readoutId=controlId+'-readout',label=node('label','rtp-history-date-label',fixed('查看日期（方向键切换，Home / End 到首尾）')),input=node('input','rtp-history-date-control');input.type='range';input.min='0';input.max=String(points.length-1);input.step='1';input.id=controlId;input.disabled=points.length===1;markControl(input,'date');label.htmlFor=controlId;chart.append(label,input);
    const readout=node('dl','rtp-history-readout');readout.id=readoutId;svg.setAttribute('aria-describedby',readoutId);input.setAttribute('aria-describedby',readoutId);const announcer=node('p','rtp-history-announcement');announcer.setAttribute('aria-live','polite');announcer.setAttribute('aria-atomic','true');chart.append(readout,announcer);
    const inspect=(index,announce=false)=>{const point=points[Math.max(0,Math.min(points.length-1,index))];view.date=point.date;chart.dataset.selectedDate=point.date;input.value=String(points.indexOf(point));cursor.setAttribute('x1',x(point.day));cursor.setAttribute('x2',x(point.day));readout.replaceChildren();line(readout,fixed('可知日期'),point.date);if(frequency==='weekly')line(readout,fixed('指标周期截至'),point.period_end);rows.forEach((row,n)=>{const value=point.values[row.key];line(readout,row.label,format(value));markers[n].style.display=value===null?'none':'';if(value!==null){markers[n].setAttribute('cx',x(point.day));markers[n].setAttribute('cy',y(value));}});if(point.break_before)line(readout,fixed('连续性'),fixed('此前存在数据缺口；曲线已断开'));const summary=point.date+' · '+rows.map(row=>String(row.label)+': '+format(point.values[row.key])).join(' · ');input.setAttribute('aria-valuetext',summary);if(announce)announcer.textContent=summary;};
    input.addEventListener('input',()=>inspect(Number(input.value),true));
    const pointer=e=>{const rect=svg.getBoundingClientRect();if(!rect.width)return;const at=start+Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width*640/616-12/616))*span;let nearest=0;for(let i=1;i<points.length;i++)if(Math.abs(points[i].day-at)<Math.abs(points[nearest].day-at))nearest=i;inspect(nearest);};svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
    const selectedIndex=points.findIndex(p=>p.date===view.date);inspect(selectedIndex<0?points.length-1:selectedIndex);
    appendTable();
    return chart;
  }
  function priceTimestamp(value){
    if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)||historyDay(value.slice(0,10))===null)return null;
    const timestamp=Date.parse(value);return Number.isFinite(timestamp)?timestamp:null;
  }
  function priceLocalDay(timestamp){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(timestamp));}
  function intradayTradingTime(timestamp){
    if(!Number.isFinite(timestamp))return null;
    const minute=(((timestamp+8*3600000)%86400000+86400000)%86400000)/60000;
    if(minute>=570&&minute<=690)return (minute-570)*60000;
    if(minute>=780&&minute<=900)return (minute-660)*60000;
    return null;
  }
  function intradayTradingAxisLabel(value,seconds=false){
    if(Math.abs(value-120*60000)<.001)return '11:30 / 13:00';
    const total=Math.round(value/1000)+(value<120*60000?570:660)*60,hour=Math.floor(total/3600),minute=Math.floor(total%3600/60),second=total%60;
    return String(hour).padStart(2,'0')+':'+String(minute).padStart(2,'0')+(seconds?':'+String(second).padStart(2,'0'):'');
  }
  function priceMoney(value){return value===null?String(fixed('未记录')):String(originalNumber(value,4));}
  function priceHistorySeries(selected,signal,mode){
    const empty=status=>({status,points:[]}),contract=state.data?.price_histories;
    if(!contract)return empty('unavailable');
    if(contract.contract_version!=='d0-price-history-v1'||!Array.isArray(contract.assets)||contract.assets.length>4)return empty('invalid');
    const matches=contract.assets.filter(row=>row?.symbol===selected.symbol);if(!matches.length)return empty('unavailable');if(matches.length!==1)return empty('invalid');
    const data=matches[0][mode];if(!data)return empty('unavailable');if(data.status!=='available')return {...empty(data.status==='unavailable'?'unavailable':'invalid'),reason:typeof data.reason==='string'?data.reason:null};
    const intraday=mode==='intraday',confirmed=historyDay(signal.confirmed_day),session=historyDay(data.session_day);
    if(intraday?(data.source!=='recorded_public_quotes'||data.coverage!=='recorded_samples_only'||session===null):(data.source!=='confirmed_daily_history'||data.basis!=='unadjusted_close'||data.signal_key!==signal.id||typeof signal.id!=='string'||data.confirmed_day!==signal.confirmed_day||confirmed===null))return empty('invalid');
    if(typeof data.truncated!=='boolean'||!Array.isArray(data.points)||data.points.length>(intraday?600:120))return empty('invalid');
    const points=[],generated=priceTimestamp(state.data?.generated_at);let last=-Infinity,excludedClosed=0;
    for(const raw of data.points){
      const at=intraday?priceTimestamp(raw?.at):historyDay(raw?.date),received=intraday?priceTimestamp(raw?.received_at):null,value=intraday?raw?.price:raw?.close,previous=raw?.previous_close,ratio=raw?.change_ratio;
      if(at===null||at<=last||typeof raw?.break_before!=='boolean'||intraday&&(received===null||received<at||priceLocalDay(at)!==data.session_day||generated!==null&&(at>generated||received>generated))||!intraday&&at>confirmed)return empty('invalid');
      if([value,previous].some(number=>number!==null&&(typeof number!=='number'||!Number.isFinite(number)||number<=0))||ratio!==null&&(typeof ratio!=='number'||!Number.isFinite(ratio)))return empty('invalid');
      if(!intraday&&(raw.previous_date!==null&&(historyDay(raw.previous_date)===null||historyDay(raw.previous_date)>=at)||ratio!==null&&raw.previous_date===null))return empty('invalid');
      if(ratio!==null&&(value===null||previous===null||Math.abs(ratio-(value/previous-1))>1e-9))return empty('invalid');
      last=at;if(intraday&&intradayTradingTime(at)===null){excludedClosed++;continue;}
      const previousPoint=points.at(-1);
      points.push({...raw,key:intraday?raw.at:raw.date,x:at,price:value,ratio,break_before:raw.break_before||Boolean(intraday&&previousPoint&&at-previousPoint.x>90000)});
    }
    return {...data,points,status:intraday&&!points.length?'unavailable':'available',reason:intraday&&!points.length&&excludedClosed?'no_trading_samples':data.reason,excluded_closed_count:excludedClosed};
  }
  function priceGraph(target,{title,field,points,mode,readoutId,inspect}){
    const chart=node('section','rtp-original-chart rtp-history-chart rtp-price-chart');chart.dataset.priceChart=field;chart.append(node('h6','',title));target.append(chart);
    const ratio=field==='ratio',format=value=>value===null?String(fixed('未记录')):ratio?String(rationalePercent(value)):priceMoney(value),valid=points.map(point=>point[field]).filter(value=>value!==null);
    if(!valid.length){chart.append(node('p','rtp-wait',fixed('此范围内没有可核对的数值；缺失值不会当作零。')));return ()=>{};}
    let low=Math.min(...valid),high=Math.max(...valid);if(ratio){low=Math.min(0,low);high=Math.max(0,high);}const padding=(high-low||Math.max(Math.abs(high),.001))*.1;low-=padding;high+=padding;
    if(!Number.isFinite(high-low)||high<=low){chart.append(node('p','rtp-wait',fixed('价格曲线资料待核对，暂不绘制。')));return ()=>{};}
    const coordinate=value=>mode==='intraday'?intradayTradingTime(value):value,start=coordinate(points[0].x),end=coordinate(points.at(-1).x),span=end-start,x=value=>span?12+(coordinate(value)-start)/span*616:320,y=value=>212-(value-low)/(high-low)*204;chart.dataset.tradingAxis=mode==='intraday'?'compressed':'calendar';
    const figure=node('div','rtp-history-figure'),axis=node('div','rtp-history-y-axis'),plot=node('div','rtp-history-plot'),svg=historySvg('svg',{viewBox:'0 0 640 220',preserveAspectRatio:'none',role:'img','aria-label':String(title),'aria-describedby':readoutId});svg.classList.add('rtp-history-svg');plot.append(svg);figure.append(axis,plot);chart.append(figure);
    for(let index=0;index<5;index++){const value=low+(high-low)*index/4,label=node('span','',format(value)),position=y(value);label.style.top=position/220*100+'%';axis.append(label);svg.append(historySvg('line',{x1:12,x2:628,y1:position,y2:position,class:'rtp-history-grid','aria-hidden':'true'}));}
    if(ratio)svg.append(historySvg('line',{x1:12,x2:628,y1:y(0),y2:y(0),class:'rtp-history-zero','aria-hidden':'true'}));
    const color='rtp-history-series-'+(ratio?1:0),lines=historySvg('g',{'aria-hidden':'true'});let segment=[];
    const finish=()=>{if(segment.length===1){const point=segment[0];lines.append(historySvg('circle',{cx:x(point.x),cy:y(point[field]),r:3.5,class:color+' rtp-history-isolated'}));}else if(segment.length>1)lines.append(historySvg('path',{d:segment.map((point,index)=>(index?'L':'M')+x(point.x).toFixed(3)+','+y(point[field]).toFixed(3)).join(' '),class:color+' rtp-history-line','data-series':field}));segment=[];};
    for(const point of points){if(point[field]===null){finish();continue;}if(point.break_before)finish();segment.push(point);}finish();svg.append(lines);
    const cursor=historySvg('line',{x1:0,x2:0,y1:8,y2:212,class:'rtp-history-cursor','aria-hidden':'true'}),marker=historySvg('circle',{cx:0,cy:0,r:4,class:color+' rtp-history-marker','aria-hidden':'true'});svg.append(cursor,marker);
    const xAxis=node('div','rtp-history-x-axis'+(span?'':' rtp-pnl-single-axis')),clock=value=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(value)),axisLabel=value=>mode==='intraday'?(span===0&&points[0].x!==points.at(-1).x?'11:30 / 13:00':value===start?clock(points[0].x):value===end?clock(points.at(-1).x):intradayTradingAxisLabel(value,true)):new Date(value*86400000).toISOString().slice(0,10);
    for(const at of span?[start,(start+end)/2,end]:[start])xAxis.append(node('span','',axisLabel(at)));figure.append(xAxis);
    const pointer=event=>{const rect=svg.getBoundingClientRect();if(!rect.width||!rect.height)return;const at=start+Math.max(0,Math.min(1,((event.clientX-rect.left)/rect.width*640-12)/616))*span,pointerY=(event.clientY-rect.top)/rect.height*220;let index=0,nearestX=Infinity,nearestY=Infinity;for(let n=0;n<points.length;n++){const distanceX=Math.abs(coordinate(points[n].x)-at),value=points[n][field],distanceY=value===null?Infinity:Math.abs(y(value)-pointerY);if(distanceX<nearestX-.001||Math.abs(distanceX-nearestX)<=.001&&distanceY<=nearestY){index=n;nearestX=distanceX;nearestY=distanceY;}}inspect(index);};svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
    return point=>{chart.dataset.selectedDate=point.key;cursor.setAttribute('x1',x(point.x));cursor.setAttribute('x2',x(point.x));marker.style.display=point[field]===null?'none':'';if(point[field]!==null){marker.setAttribute('cx',x(point.x));marker.setAttribute('cy',y(point[field]));}};
  }
  function renderPriceHistory(panel,selected,signal){
    const key=JSON.stringify(['price',state.id,selected.symbol]);let settings=priceViews.get(key);
    if(!settings){settings={mode:'intraday',intraday:{date:null,follow:true},daily:{range:120,date:null,follow:true}};priceViews.set(key,settings);}
    const mode=settings.mode,intraday=mode==='intraday',view=settings[mode],identity=JSON.stringify(['price',selected.symbol]),history=priceHistorySeries(selected,signal,mode),points=intraday?history.points:history.points.slice(-view.range),section=node('section','rtp-price-history');section.dataset.priceMode=mode;section.dataset.historyStatus=history.status;section.dataset.excludedClosedCount=String(history.excluded_closed_count||0);section.dataset.asset=selected.symbol;section.append(node('h5','',fixed('价格与涨跌幅')));panel.append(section);
    const markControl=(control,name)=>{control.dataset.historyKey=key;control.dataset.historySignal=identity;control.dataset.historyControl=name;};
    const quoteRows=Array.isArray(state.data?.market_quotes)?state.data.market_quotes.filter(row=>row?.symbol===selected.symbol):[],quote=quoteRows.length===1?quoteRows[0]:null,number=value=>{const n=rationaleNumber(value);return n!==null&&n>0?n:null;},price=number(quote?.price),previous=number(quote?.previous_close),change=quote&&typeof quote.change_ratio==='number'&&Number.isFinite(quote.change_ratio)&&price!==null&&previous!==null&&Math.abs(quote.change_ratio-(price/previous-1))<=1e-9?quote.change_ratio:null;
    const latest=node('dl','rtp-price-latest');line(latest,fixed('最近市场价（元）'),priceMoney(price));line(latest,fixed('行情源昨收（元）'),priceMoney(previous));line(latest,fixed('较昨收涨跌幅'),change===null?fixed('未记录'):rationalePercent(change));section.append(latest);
    const current=holdingSnapshotCurrent(),sourceAt=priceTimestamp(quote?.quote_at),receivedAt=priceTimestamp(quote?.received_at),generatedAt=priceTimestamp(state.data?.generated_at),fresh=current&&price!==null&&quote?.fresh===true&&sourceAt!==null&&receivedAt!==null&&generatedAt!==null&&sourceAt<=receivedAt&&receivedAt<=generatedAt;
    section.append(node('p','small '+(fresh?'muted':'rtp-wait'),!current?fixed('当前状态待核对；价格与曲线来自上次成功快照，不能视为实时。'):fresh?fixed('本次快照报价近期采集 · 仅供查看'):fixed('报价已过期、尚未采集或时间待核对；不能视为实时。')));
    const times=node('dl','rtp-price-times');line(times,fixed('行情源时间'),compactTime(quote?.quote_at));line(times,fixed('采集接收时间'),compactTime(quote?.received_at));line(times,fixed('行情来源'),str(quote?.source));section.append(times);
    const tabs=node('div','rtp-price-modes');tabs.setAttribute('role','group');tabs.setAttribute('aria-label',String(fixed('价格曲线类型')));
    for(const [value,label] of [['intraday',fixed('盘中采样')],['daily',fixed('历史日线')]]){const control=button(label,()=>{settings.mode=value;renderHoldingLogic(account());},'rtp-history-range');control.dataset.priceMode=value;control.setAttribute('aria-pressed',String(mode===value));markControl(control,'mode-'+value);tabs.append(control);}section.append(tabs);
    section.append(node('p','small muted',intraday?fixed('本系统采样记录，不是交易所完整分时。横轴已压缩午休；读数保留真实行情源时间，两张图共用选点。'):fixed('未复权收盘价；每日涨跌幅按前一交易日收盘价计算，不含分红，也不采用历史除权参考昨收。缺少前一交易日时涨跌幅留空，参考列保留上一条实际记录。两张图共用日期，分别使用各自刻度。')));
    if(intraday&&history.excluded_closed_count)section.append(node('p','small muted',fixed('已略去 {count} 条休市、盘前或盘后采样；曲线仅显示交易时段，最新报价卡仍按原始时间展示。',{count:history.excluded_closed_count})));
    if(intraday&&historyDay(history.session_day)!==null)section.append(node('p','rtp-price-period',fixed('最近报价日 {day}',{day:history.session_day})));
    if(!intraday&&history.status==='available')section.append(node('p','rtp-price-period',fixed('已确认日线截至 {day}',{day:history.confirmed_day})));
    const samplingReasons={invalid_samples:fixed('部分采样无效，已跳过并断开曲线。'),collection_state_unavailable:fixed('采集状态记录不完整，曲线按独立采样展示。'),collection_failed:fixed('最近报价采集失败，等待下一次正常采集。')};
    if(intraday&&Object.hasOwn(samplingReasons,history.reason))section.append(node('p','small rtp-wait',samplingReasons[history.reason]));
    if(history.truncated)section.append(node('p','small rtp-wait',intraday?fixed('仅保留最近采样，报价日的覆盖不完整。'):fixed('仅展示最近一段历史，所列范围不代表全部上市历史。')));
    if(!intraday){const ranges=node('div','rtp-history-ranges');ranges.setAttribute('role','group');ranges.setAttribute('aria-label',String(fixed('历史显示范围')));for(const range of [60,120]){const control=button(fixed('{count}日',{count:range}),()=>{view.range=range;renderHoldingLogic(account());},'rtp-history-range');control.dataset.priceRange=String(range);control.setAttribute('aria-pressed',String(view.range===range));markControl(control,'price-range-'+range);ranges.append(control);}section.append(ranges);}
    if(history.status!=='available'||!points.length){section.append(node('p','rtp-wait rtp-price-empty',history.status==='invalid'?fixed('价格曲线资料待核对，暂不绘制。'):intraday?(history.reason==='reader_busy'?fixed('正在读取采样，请稍候。'):history.reason==='no_trading_samples'?fixed('现有采样均在非交易时段，暂不绘制；等待交易时段的有效行情。'):fixed('尚无已保存的盘中采样；等待正常行情采集，不补造分时线。')):fixed('尚无与确认信号一致的日线价格记录，暂不绘制。')));return;}
    section.append(node('p','small muted',fixed('{count} 个已记录观测点',{count:points.length})));
    const controlId='rtp-price-'+selected.symbol,readoutId=controlId+'-readout',charts=node('div','rtp-price-charts'),label=node('label','rtp-history-date-label',fixed('查看日期（方向键切换，Home / End 到首尾）')),input=node('input','rtp-history-date-control'),readout=node('dl','rtp-history-readout rtp-price-readout'),announcer=node('p','rtp-history-announcement');
    readout.id=readoutId;input.type='range';input.id=controlId;input.min='0';input.max=String(points.length-1);input.step='1';input.disabled=points.length===1;input.setAttribute('aria-describedby',readoutId);markControl(input,'price-date');label.htmlFor=controlId;announcer.setAttribute('aria-live','polite');announcer.setAttribute('aria-atomic','true');
    const pointTime=point=>intraday?String(compactTime(point.at)):point.date,paint=[];
    const inspect=(index,announce=false,user=false)=>{const bounded=Math.max(0,Math.min(points.length-1,index)),point=points[bounded];view.date=point.key;if(user)view.follow=bounded===points.length-1;section.dataset.selectedDate=point.key;input.value=String(bounded);for(const update of paint)update(point);readout.replaceChildren();line(readout,intraday?fixed('行情源时间'):fixed('收盘日期'),pointTime(point));line(readout,intraday?fixed('市场价（元）'):fixed('未复权收盘价（元）'),priceMoney(point.price));line(readout,intraday?fixed('行情源昨收（元）'):fixed('上一记录收盘价（元）'),priceMoney(point.previous_close));if(!intraday)line(readout,fixed('上一记录日'),str(point.previous_date));line(readout,intraday?fixed('较昨收涨跌幅'):fixed('每日涨跌幅'),point.ratio===null?fixed('未记录'):rationalePercent(point.ratio));if(intraday)line(readout,fixed('采集接收时间'),compactTime(point.received_at));if(point.break_before)line(readout,fixed('连续性'),intraday?fixed('此处采样不连续；曲线已断开'):fixed('此前存在数据缺口；曲线已断开'));const summary=pointTime(point)+' · '+priceMoney(point.price)+' · '+(point.ratio===null?String(fixed('未记录')):String(rationalePercent(point.ratio)));input.setAttribute('aria-valuetext',summary);if(announce)announcer.textContent=summary;};
    section.append(charts);paint.push(priceGraph(charts,{title:intraday?fixed('市场价格（元）'):fixed('每日收盘价（元，未复权）'),field:'price',points,mode,readoutId,inspect:index=>inspect(index,false,true)}),priceGraph(charts,{title:intraday?fixed('较行情源昨收涨跌幅（%）'):fixed('每日涨跌幅（%）'),field:'ratio',points,mode,readoutId,inspect:index=>inspect(index,false,true)}));section.append(label,input,readout,announcer);
    input.addEventListener('input',()=>inspect(Number(input.value),true,true));input.addEventListener('keydown',event=>{let index=Number(input.value);if(event.key==='Home')index=0;else if(event.key==='End')index=points.length-1;else if(event.key==='ArrowLeft'||event.key==='ArrowDown')index--;else if(event.key==='ArrowRight'||event.key==='ArrowUp')index++;else return;event.preventDefault();inspect(index,true,true);});
    const found=points.findIndex(point=>point.key===view.date);inspect(view.follow||view.date===null?points.length-1:found>=0?found:intraday?points.length-1:0);
    if(points.length===1)section.append(node('p','small muted',fixed('只有一个历史观测点，不构成趋势。')));
    section.append(node('p','small muted',fixed('缺失值和采集间断保留空档；不插值。行情变化用于查看，不会直接生成 D0 信号或改变实际持仓。')));
    const detail=disclosure(fixed('查看价格与涨跌幅数据表'),'price-'+selected.symbol+'-'+mode),wrap=node('div','rtp-history-table-wrap'),table=node('table','rtp-history-table'),head=node('thead'),header=node('tr'),body=node('tbody');
    const labels=[intraday?fixed('行情源时间'):fixed('收盘日期'),intraday?fixed('市场价（元）'):fixed('未复权收盘价（元）'),intraday?fixed('行情源昨收（元）'):fixed('上一记录收盘价（元）'),intraday?fixed('较昨收涨跌幅'):fixed('每日涨跌幅'),intraday?fixed('采集接收时间'):fixed('上一记录日'),fixed('连续性')];for(const text of labels){const th=node('th','',text);th.scope='col';header.append(th);}head.append(header);
    for(const point of points){const tr=node('tr'),first=node('th','',pointTime(point));first.scope='row';tr.append(first,node('td','',priceMoney(point.price)),node('td','',priceMoney(point.previous_close)),node('td','',point.ratio===null?fixed('未记录'):rationalePercent(point.ratio)),node('td','',intraday?compactTime(point.received_at):str(point.previous_date)),node('td','',point.break_before?(intraday?fixed('分段首点'):fixed('缺口后首点')):fixed('—')));body.append(tr);}table.append(node('caption','',intraday?fixed('已记录的盘中价格与涨跌幅'):fixed('已确认的每日收盘价与涨跌幅')),head,body);wrap.tabIndex=0;wrap.setAttribute('aria-label',String(fixed('价格与涨跌幅数据表')));markControl(wrap,'price-table');wrap.append(table);detail.append(wrap);detail.open=Boolean(view.tableOpen);detail.addEventListener('toggle',()=>{if(detail.isConnected)view.tableOpen=detail.open;});wrap.addEventListener('scroll',()=>{if(wrap.isConnected){view.tableTop=wrap.scrollTop;view.tableLeft=wrap.scrollLeft;}});section.append(detail);wrap.scrollTop=view.tableTop||0;wrap.scrollLeft=view.tableLeft||0;
  }
  function originalDates(target,timing,group,daily=false){
    const dates=node('dl','rtp-original-dates'),market=group==='market';
    line(dates,fixed('时序核对'),originalTimingLabel(timing[group+'_status']));
    if(group==='state')line(dates,fixed('原策略状态日'),str(timing.state_day));
    else if(daily)line(dates,fixed('日线指标日期'),str(timing.period_end));
    else{line(dates,fixed('指标周期截至'),str(market?timing.market_period_end:timing.period_end));line(dates,fixed('该周期首次可知日'),str(market?timing.market_available_on:timing.available_on));}
    target.append(dates);
  }
  function bankRule(owner,confirmedDay){
    const rule=owner?.bank_rule;
    if(weeklyStrategy())return {mode:'legacy',limit:40,rule:{}};
    const valid=rule?.contract_version==='d0-bank-entry-rule-v1'&&rule.source==='saved_signal';
    if(valid&&rule.mode==='legacy'&&rule.status==='legacy'&&rule.entry_k_limit===40)return {mode:'legacy',limit:40,rule};
    const current=valid&&rule.mode==='conditional'&&rule.status==='confirmed'&&historyDay(confirmedDay)!==null&&rule.day===confirmedDay;
    const limit=current&&((rule.active===true&&rule.entry_k_limit===50)||(rule.active===false&&rule.entry_k_limit===40))?rule.entry_k_limit:null;
    return {mode:'conditional',limit,rule:valid?rule:{}};
  }
  function renderBankRuleEvidence(target,bank){
    if(bank.mode==='legacy')return;
    const r=bank.rule,list=node('dl');
    line(list,fixed('本次银行新建参考仓位上限'),bank.limit===null?fixed('待核对'):'K≤'+bank.limit);
    line(list,fixed('创业板50周条件放宽'),bank.limit===null?fixed('待核对'):bank.limit===50?fixed('已启用'):fixed('未启用'));
    const weekly=bank.limit!==null&&r.weekly_status==='confirmed';
    line(list,fixed('已确认创业板周收盘'),weekly?originalNumber(rationaleNumber(r.weekly_close),4):fixed('待核对'));
    line(list,fixed('50周均线'),weekly?originalNumber(rationaleNumber(r.ma),4):fixed('待核对'));
    line(list,fixed('已完成周结束日'),weekly?str(r.week_end):fixed('待核对'));
    line(list,fixed('首次可用确认日'),weekly?str(r.available):fixed('待核对'));
    target.append(list,node('p','small muted',fixed('仅当已确认的创业板周收盘严格低于50周均线，且指标、评分与当日行情资料就绪时，银行新金叉入场上限由K≤40放宽至K≤50；相等不放宽。此处读取本次保存的规则与证据。')));
    if(bank.limit===null)target.append(node('p','rtp-wait',fixed('本次银行入场上限的保存证据缺失或未通过核对，不能确定采用40还是50；不使用当前行情补算历史规则。')));
  }
  function renderOriginalGate(panel,selected,signal){
    if(weeklyStrategy()&&selected.symbol==='sh518880'){const section=node('section','rtp-original-gate');section.dataset.kind='excluded';section.append(node('h5','',fixed('黄金不参与本策略')),node('p','small muted',fixed('D0I-BOND-WW 的黄金目标固定为0，不使用黄金资格或评分。')));panel.append(section);return;}
    if(weeklyStrategy()&&selected.symbol==='sh511010'){renderWeeklyBondGate(panel,selected,signal);return;}
    const kind=selected.symbol==='sz159915'?'chi_weekly':selected.symbol==='sh512800'?'bank_daily':'defense_daily',saved=selected.original_gate,valid=saved?.contract_version==='d0-original-gate-v1'&&saved.source==='saved_signal'&&saved.kind===kind,gate=valid?saved:{},timing={...(gate.timing&&typeof gate.timing==='object'?gate.timing:{})},metrics=gate.metrics&&typeof gate.metrics==='object'?gate.metrics:{},sourceState=gate.state&&typeof gate.state==='object'?gate.state:{},section=node('section','rtp-original-gate');section.dataset.kind=kind;section.append(node('h5','',fixed('① 先看原策略筛选')));panel.append(section);
    const sameDay=typeof signal.confirmed_day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(signal.confirmed_day)&&timing.confirmed_day===signal.confirmed_day;
    if(valid&&!sameDay){timing.status='invalid';for(const group of ['indicator','market','state'])if(timing[group+'_status']!==null)timing[group+'_status']='invalid';}
    const confirmed=group=>valid&&sameDay&&timing[group+'_status']==='confirmed';
    const metric=(key,group='indicator',range=null)=>{const value=confirmed(group)?rationaleNumber(metrics[key]):null;return value!==null&&(!range||value>=range[0]&&value<=range[1])?value:null;},stateValue=key=>confirmed('state')?sourceState[key]:null;
    section.append(node('p','small muted',fixed('原策略筛选决定是否具备多头资格；下方动量与波动用于通过资格后的 D0 权重分配。')));
    if(!valid)section.append(node('p','rtp-wait',fixed('此信号未保存可识别的原策略指标；不使用当前行情补算历史依据。')));
    else if(timing.status!=='confirmed'||timing.confirmed_day!==signal.confirmed_day)section.append(node('p','rtp-wait',fixed('部分原策略记录的日期缺失、冲突或晚于信号确认日；仅展示时序已核对的部分，不能视为完整确认。')));
    const badges=node('div','rtp-original-badges');badges.append(node('span','pill '+(stateValue('long')===true?'rtp-logic-qualified':'neutral'),originalFlag(stateValue('long'),fixed('已保存原策略多头：是'),fixed('已保存原策略多头：否'),fixed('原策略多头未记录'))),node('span','pill neutral',originalFlag(stateValue('ready'),fixed('原策略指标已就绪'),fixed('原策略指标尚未就绪'),fixed('原策略就绪状态未记录'))));section.append(badges);
    const charts=node('div','rtp-original-charts');section.append(charts);
    if(kind==='chi_weekly'||kind==='bank_daily'){
      const kd=originalPair(charts,{selected,signal,id:'skdj',frequency:kind==='chi_weekly'?'weekly':'daily',unit:'indicator',title:kind==='chi_weekly'?fixed('周线 SKDJ：K 与 D'):fixed('日线 SKDJ：K 与 D'),mode:'kdj',className:'rtp-original-kdj',rows:[{key:'k',label:fixed('K值'),value:metric('k','indicator',[0,100])},{key:'d',label:fixed('D值'),value:metric('d','indicator',[0,100])}]});
      kd.append(node('p','small muted',fixed('K、D 共用0–100刻度。即使 K 高于 D，也不能仅凭两线当前位置认定发生了新的金叉。')));
      if(kind==='chi_weekly'){
        originalDates(kd,timing,'indicator');
        const trix=originalPair(charts,{selected,signal,id:'trix',frequency:'weekly',unit:'percent_points',title:fixed('周线 TRIX 与信号线（%）'),mode:'signed',className:'rtp-original-trix',rows:[{key:'trix',label:'TRIX',value:metric('trix_pct'),format:value=>originalNumber(value,4)+'%'},{key:'signal',label:fixed('TRIX信号线'),value:metric('signal_pct'),format:value=>originalNumber(value,4)+'%'}]});trix.append(node('p','small muted',fixed('横线标出零值；TRIX 直接显示原始百分点，不额外乘以100。两线的位置比较不代表刚刚发生交叉。')));
        const trend=originalPair(charts,{selected,signal,id:'trend',frequency:'weekly',unit:'price',title:fixed('周线趋势：指标价与50周均线'),className:'rtp-original-trend',rows:[{key:'value',label:fixed('原策略周收盘指标价'),value:metric('market_close','market',[Number.MIN_VALUE,Number.MAX_VALUE])},{key:'ma',label:fixed('50周均线'),value:metric('market_ma','market',[Number.MIN_VALUE,Number.MAX_VALUE])}]});originalDates(trend,timing,'market');trend.append(node('p','small muted',fixed('此处使用原策略保存的周线价格口径；50周趋势记录与 SKDJ、TRIX 的周期分别核对。')));
        const stateCard=node('section','rtp-original-state');stateCard.append(node('h6','',fixed('原策略保存的状态')));const list=node('dl'),marketState=stateValue('close_market');line(list,fixed('周线市场状态'),({bull:fixed('牛市'),bear:fixed('熊市'),warmup:fixed('预热中')})[marketState]||fixed('未记录'));line(list,fixed('价格保护阻断'),originalFlag(stateValue('blocked'),fixed('已阻断'),fixed('未阻断')));stateCard.append(list);charts.append(stateCard);
      }else{
        const events=node('section','rtp-original-state');events.append(node('h6','',fixed('保存的当日条件与参考状态')));const list=node('dl');line(list,fixed('当日入场条件'),originalFlag(stateValue('entry'),fixed('已触发'),fixed('未触发')));line(list,fixed('当日指标退出条件'),originalFlag(stateValue('exit'),fixed('已触发'),fixed('未触发')));line(list,fixed('原策略正向条件'),originalFlag(stateValue('positive'),fixed('成立'),fixed('不成立')));events.append(list,node('p','small muted',fixed('入场条件未触发，仍可能延续原策略持仓；指标退出条件也不涵盖持有期等全部退出规则。')));charts.append(events);
        const bank=bankRule(gate,signal.confirmed_day);renderBankRuleEvidence(section,bank);
        if(bank.limit!==null)section.append(node('p','small muted',fixed('银行原入场条件包含前日 K≤D、当日 K>D 且 K≤{limit}；当日指标退出条件包含 K≥70 或 K≤D。这里显示保存的条件结果，不用当前 K、D 重新判定。',{limit:bank.limit})));
      }
    }else{
      const window=metric('ma_window'),maLabel=window===60?fixed('60日均线'):window===120?fixed('120日均线'):fixed('均线（窗口未记录）'),trend=originalPair(charts,{selected,signal,id:'trend',frequency:'daily',unit:'index_points',title:fixed('含息收益指数与均线'),className:'rtp-original-trend',rows:[{key:'value',label:fixed('含息收益指数'),value:metric('value','indicator',[Number.MIN_VALUE,Number.MAX_VALUE])},{key:'ma',label:maLabel,value:metric('ma','indicator',[Number.MIN_VALUE,Number.MAX_VALUE])}]});trend.append(node('p','small muted',fixed('数值是含息收益指数及其均线，单位为指数点，不是 ETF 的交易价格。')));originalDates(trend,timing,'indicator',true);
      const momentum=node('section','rtp-original-state'),list=node('dl');momentum.append(node('h6','',fixed('原策略动量条件')));line(list,fixed('20日动量'),rationalePercent(metric('momentum20')));line(list,fixed('原策略保存的多头'),originalFlag(stateValue('long'),fixed('是'),fixed('否')));momentum.append(list,node('p','small muted',fixed('原策略要求资料就绪、含息收益指数高于对应均线且20日动量大于0；是否多头读取保存结果。')));charts.append(momentum);
    }
    const reference=node('div','rtp-original-reference'),list=node('dl');
    if(kind!=='defense_daily'){
      const risk=rationaleNumber(stateValue('next_risk')),days=rationaleNumber(stateValue('holding_days'));line(list,fixed('原策略下一期参考仓位'),risk!==null&&risk>=0&&risk<=1?rationalePercent(risk):fixed('未记录'));line(list,fixed('原策略已持有交易日'),days!==null&&Number.isSafeInteger(days)&&days>=0?originalNumber(days,0):fixed('未记录'));reference.append(list,node('p','small muted',fixed('原策略参考仓位和持有天数不等于 D0 模型目标，也不等于本账户实际持仓。')));originalDates(reference,timing,'state');const reason=stateValue('reason');if(typeof reason==='string'&&reason.trim())reference.append(node('p','rtp-original-reason',reason));section.append(reference);
    }
  }
  function renderWeeklyBondGate(panel,selected,signal){
    const saved=selected.original_gate,gate=saved?.contract_version==='d0-original-gate-v1'&&saved.source==='saved_signal'&&saved.kind==='bond_weekly'?saved:null;
    const t=gate?.timing||{},m=gate?.metrics||{},s=gate?.state||{},datesValid=[t.confirmed_day,t.period_end,t.available_on,t.state_day].every(value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)),valid=!!gate&&datesValid&&t.status==='confirmed'&&t.confirmed_day===signal.confirmed_day&&t.period_end<=t.available_on&&t.available_on<=signal.confirmed_day&&t.state_day===signal.confirmed_day&&m.ma_unit==='weeks'&&m.momentum_unit==='weeks'&&m.ma_window===60&&rationaleNumber(m.value)>0&&rationaleNumber(m.ma)>0&&rationaleNumber(m.momentum20)!==null&&typeof s.ready==='boolean'&&typeof s.long==='boolean';
    const section=node('section','rtp-original-gate rtp-weekly-bond-gate');section.dataset.kind='bond_weekly';section.dataset.evidenceStatus=valid?'confirmed':'unknown';section.append(node('h5','',fixed('国债资格 · 已完成周')));panel.append(section);
    section.append(node('p','small muted',fixed('仅在银行与创业板均不合格时启用：国债含息周收盘高于60周均线，且20周动量大于0；周内冻结趋势，仍核对当日资料。')));
    const list=node('dl');line(list,fixed('已完成周结束日'),valid?t.period_end:fixed('待核对'));line(list,fixed('首次可用确认日'),valid?t.available_on:fixed('待核对'));line(list,fixed('含息周收盘指标值'),valid?originalNumber(rationaleNumber(m.value),4):fixed('待核对'));line(list,fixed('60周均线'),valid?originalNumber(rationaleNumber(m.ma),4):fixed('待核对'));line(list,fixed('20周动量'),valid?rationalePercent(m.momentum20):fixed('待核对'));line(list,fixed('周指标就绪'),valid?originalFlag(s.ready,fixed('是'),fixed('否')):fixed('待核对'));line(list,fixed('周趋势资格'),valid?originalFlag(s.long,fixed('通过'),fixed('未通过')):fixed('待核对'));line(list,fixed('本次国债配置资格'),selected.eligible===true?fixed('通过配置资格'):selected.eligible===false?fixed('未通过配置资格'):fixed('待核对'));section.append(list,node('p','small muted',fixed('以上是保存的周线资格证据，含息指标值不是ETF成交价格。国债使用防守资格，不参与股票的日线动量评分归一。')));
    if(!valid)section.append(node('p','rtp-wait',fixed('周线证据缺失或时序未通过核对；不使用当前行情补算或猜测历史资格。')));
  }
  function renderIndicatorTradingRules(target,selected,c){
    const section=node('section','rtp-trading-rules'),columns=node('div','rtp-trading-rule-columns'),buy=node('div'),sell=node('div'),say=(parent,text,values={})=>parent.append(node('p','rtp-commentary-line',fixed(text,values)));
    section.append(node('h6','',fixed('什么时候买入、什么时候退出')));target.append(section);buy.append(node('strong','',fixed('原策略如何允许持有')));sell.append(node('strong','',fixed('原策略何时退出或取消资格')));columns.append(buy,sell);section.append(columns);
    const saved=c.state||{},pairs=Array.isArray(c.pairs)?c.pairs:[],skdj=pairs.find(p=>p?.id==='skdj'),trix=pairs.find(p=>p?.id==='trix'),trend=c.trend,bank=bankRule(c,c.confirmed_day);
    if(selected.symbol==='sz159915'){
      say(buy,'创业板：已完成周线 SKDJ(3,5) 的K>D，且 TRIX(4,8)>信号线，用于建立或恢复原策略进攻仓位。D0还要求50周牛市状态、原策略保持完整进攻仓位，以及指标资料就绪。');
      say(buy,'创业板采用双多头状态，持续满足也可参与；每次D0增配无需重新出现一笔金叉。价格保护退出后，要先等双多头失效解除阻断，再等后续双多头恢复。');
      say(sell,'原策略参考持仓达到20个交易日退出；50周趋势转弱或原策略不再保持完整进攻仓位时，D0目标变为0%。单次SKDJ或TRIX死叉本身不会立即退出已有原策略仓位。');
      say(sell,'回撤保护：原策略参考持仓先从入场价上涨至少15%，再按日收盘相对峰值回撤达到8%时减半、12%时退出并阻断。原策略减半会使D0失去完整进攻资格，D0目标为0%，并非跟着减半。');
    }else if(selected.symbol==='sh512800'){
      if(bank.limit!==null)say(buy,'银行：日线 SKDJ(9,5) 前一周期K≤D，本期K>D形成向上金叉，且本期K≤{limit}；指标就绪、原策略参考空仓且允许入场时，新建参考仓位。银行未使用TRIX。',{limit:bank.limit});
      else say(buy,'本次银行入场上限的保存证据缺失或未通过核对，不能确定采用40还是50；不使用当前行情补算历史规则。');
      if(bank.mode==='conditional'){
        say(buy,'仅当已确认的创业板周收盘严格低于50周均线，且指标、评分与当日行情资料就绪时，银行新金叉入场上限由K≤40放宽至K≤50；相等不放宽。此处读取本次保存的规则与证据。');
        say(buy,'放宽区间结束时恢复原K40参考状态；再次进入时继承原参考仓位与持有天数，并按当日规则评估。20日退出后的再入场阻断只在连续放宽区间内延续，等待K≤D解除后再等新金叉。');
      }
      say(buy,'原策略已有有效多头时，D0可以按目标增配；本期没有新金叉或K已高于入场上限，都不单独表示必须退出。');
      say(sell,'原策略持仓时，K≥70、K≤D（包括死叉或相等），或参考持有达到20个交易日，会触发退出；D0随原策略多头资格失效取消配置。');
    }else{
      const window=selected.symbol==='sh518880'?120:60;
      say(buy,'{window}日均线规则：已确认的含息收益指数严格高于{window}日均线，且原策略20日动量大于0、指标就绪，才允许配置。',{window});
      say(sell,'含息收益指数回落至均线或下方、原策略20日动量不再大于0，或指标资料未就绪时，取消该资产配置资格，目标为0%。');
    }
    const detail=disclosure(fixed('逐项查看本次条件'),'rtp-trading-check-'+selected.symbol),list=node('dl'),flag=value=>originalFlag(value,fixed('满足'),fixed('未满足'),fixed('待核对')),above=pair=>pair&&['above','below','equal'].includes(pair.position)?pair.position==='above':null;
    say(detail,'以下观察用于理解原策略的建仓与持有条件；已有仓位可以延续，最终配置资格读取已保存结果。');
    if(selected.symbol==='sz159915'){
      line(list,fixed('周线SKDJ：K>D'),flag(above(skdj)));line(list,fixed('周线TRIX：高于信号线'),flag(above(trix)));line(list,fixed('周线指标价：高于50周均线'),flag(above(trend)));
      const risk=rationaleNumber(saved.next_risk);line(list,fixed('原策略下一期为完整进攻仓位'),flag(risk===null?null:risk>=.999999));line(list,fixed('价格保护阻断已解除'),flag(typeof saved.blocked==='boolean'?!saved.blocked:null));
    }else if(selected.symbol==='sh512800'){
      const k=rationaleNumber(skdj?.left);line(list,fixed('日线SKDJ：K>D'),flag(above(skdj)));line(list,bank.limit===null?fixed('新建参考仓位的K值上限'):fixed('新建参考仓位要求K≤{limit}',{limit:bank.limit}),flag(k===null||bank.limit===null?null:k<=bank.limit));line(list,fixed('原策略保存的当日低位入场信号'),flag(saved.entry));line(list,fixed('原策略保存的当日退出信号'),flag(saved.exit));
    }else{
      line(list,fixed('含息收益指数高于对应均线'),flag(above(trend)));const m=rationaleNumber(trend?.momentum20);line(list,fixed('原策略20日动量>0'),flag(m===null?null:m>0));
    }
    line(list,fixed('原策略指标已就绪'),flag(saved.ready));line(list,fixed('原策略保存的多头资格'),flag(saved.long));line(list,fixed('D0评分资料已就绪'),flag(c.momentum?.score_ready));line(list,fixed('D0最终配置资格'),flag(saved.eligible));
    if(['sz159915','sh512800'].includes(selected.symbol)){const days=rationaleNumber(saved.holding_days);line(list,fixed('原策略参考持有天数'),days===null?fixed('未记录'):fixed('{days}个交易日（上限20日）',{days:originalNumber(days,0)}));}
    detail.append(list);section.append(detail);
    say(section,'D0还要求至少61个交易日的评分资料，并有同一确认日行情；20日和60日动量用于合格资产之间的评分分配。');
    say(section,'D0何时模拟买卖：先按合格资产的动量／波动评分形成目标；目标份额高于实际份额时计划买入，低于实际份额时计划卖出。新确认信号最早下一交易日参与模拟。');
    say(section,'实际模拟成交还需账户已启动、处于执行交易时段，并满足新鲜报价、限价、整手、资金及可卖份额等条件。查看指标和文字说明不会提交委托。');
  }
  function renderIndicatorCommentary(target,selected,signal){
    const section=node('section','rtp-indicator-commentary');section.dataset.symbol=selected.symbol;section.append(node('h5','',fixed('当前策略解读')));target.append(section);
    const c=selected.commentary,valid=c?.contract_version==='d0-indicator-commentary-v1'&&c.source==='saved_signal'&&c.signal_key===signal.id&&c.symbol===selected.symbol&&c.confirmed_day===signal.confirmed_day&&historyDay(c.confirmed_day)!==null;
    if(!valid){section.append(node('p','small rtp-wait',fixed('文字解读资料尚未就绪，等待正常刷新。')));return;}
    section.append(node('p','small muted',fixed('依据 {day} 已确认信号；以下说明不随盘中报价变化。',{day:c.confirmed_day})));
    if(!holdingSnapshotCurrent())section.append(node('p','small rtp-wait',fixed('当前展示上次成功快照的指标解读，等待状态刷新。')));
    const number=(value,digits=4)=>{const n=rationaleNumber(value);return n===null?String(fixed('未记录')):String(originalNumber(n,digits));},say=(parent,text,values={})=>parent.append(node('p','rtp-commentary-line',fixed(text,values)));
    if(!Array.isArray(c.pairs)||c.pairs.length>2){say(section,'指标解读资料待核对。');return;}
    for(const pair of c.pairs){
      if(!['skdj','trix'].includes(pair?.id)||!['daily','weekly'].includes(pair.frequency))continue;
      const block=node('div','rtp-commentary-block'),skdj=pair.id==='skdj',leftName=skdj?'K':'TRIX',rightName=skdj?'D':String(fixed('信号线')),digits=skdj?4:6,unit=skdj?'':String(fixed('个百分点'));
      block.dataset.indicator=pair.id;block.append(node('h6','',fixed(skdj?(pair.frequency==='weekly'?'周线 SKDJ 解读':'日线 SKDJ 解读'):'周线 TRIX 解读')));section.append(block);
      const left=rationaleNumber(pair.left),right=rationaleNumber(pair.right),values={left_name:leftName,right_name:rightName,left:number(left,digits)+(skdj?'':'%'),right:number(right,digits)+(skdj?'':'%')};
      if(left===null||right===null||!['above','below','equal'].includes(pair.position)){say(block,'本期指标数值或时序资料不足，暂不判断两线关系。');continue;}
      say(block,'{left_name}={left}，{right_name}={right}。',values);
      const relations={above:'{left_name}在{right_name}上方，当前为上方排列。',below:'{left_name}在{right_name}下方，当前为下方排列。',equal:'{left_name}与{right_name}当前相等，尚未形成新的交叉。'};
      say(block,relations[pair.position],values);
      if(left!==right&&number(left,digits)===number(right,digits))say(block,'显示值经过舍入，两线关系按原始精度比较。');
      if(historyDay(pair.period_end)!==null)say(block,'指标周期截至 {day}；可知日 {available}。',{day:pair.period_end,available:pair.available_on||String(fixed('未记录'))});
      const previous=pair.previous,pl=rationaleNumber(previous?.left),pr=rationaleNumber(previous?.right),comparable=pl!==null&&pr!==null&&historyDay(previous?.available_on)!==null&&historyDay(pair.available_on)!==null&&previous.available_on<pair.available_on;
      if(!comparable){say(block,'缺少可连续比较的前值，暂不判断交叉或靠拢方向。');continue;}
      if(pair.movement==='unknown')continue;
      const movementValues={...values,before:previous.available_on,after:pair.available_on,before_gap:number(Math.abs(pl-pr),digits)+unit,after_gap:number(Math.abs(left-right),digits)+unit};
      const movements={cross_up:'从 {before} 到 {after}，{left_name}由不高于{right_name}转为高于（金叉）；这是两次观测之间的变化。',cross_down:'从 {before} 到 {after}，{left_name}由不低于{right_name}转为低于（死叉）；这是两次观测之间的变化。',converging_up:'从 {before} 到 {after}，差距由 {before_gap} 缩小至 {after_gap}；正在向金叉方向靠拢，本次观测尚未上穿。',converging_down:'从 {before} 到 {after}，差距由 {before_gap} 缩小至 {after_gap}；正在向死叉方向靠拢，本次观测尚未下穿。',widening_above:'从 {before} 到 {after}，上方差距由 {before_gap} 扩大至 {after_gap}。',widening_below:'从 {before} 到 {after}，下方差距由 {before_gap} 扩大至 {after_gap}。',unchanged:'从 {before} 到 {after}，两线差值未变。'};
      if(movements[pair.movement])say(block,movements[pair.movement],movementValues);
    }
    const trend=c.trend;
    if(trend){
      const block=node('div','rtp-commentary-block'),weekly=trend.frequency==='weekly',value=rationaleNumber(trend.value),ma=rationaleNumber(trend.ma),window=trend.window;
      block.dataset.indicator='trend';block.append(node('h6','',fixed('趋势与均线解读')));section.append(block);
      if(value!==null&&ma!==null&&Number.isInteger(window)&&['above','below','equal'].includes(trend.position)){
        say(block,weekly?'原策略周收盘指标价 {value}，{window}周均线 {ma}。':'含息收益指数 {value}，{window}日均线 {ma}。',{value:number(value),window,ma:number(ma)});
        say(block,{above:'指标值高于均线，当前处于均线上方。',below:'指标值低于均线，当前处于均线下方。',equal:'指标值等于均线，尚未满足严格高于均线的条件。'}[trend.position]);
        if(historyDay(trend.period_end)!==null)say(block,'指标周期截至 {day}；可知日 {available}。',{day:trend.period_end,available:trend.available_on||String(fixed('未记录'))});
      }else say(block,'均线数值、窗口或时序资料不足，暂不判断趋势位置。');
      if(!weekly){const originalMomentum=rationaleNumber(trend.momentum20);if(originalMomentum!==null)say(block,originalMomentum>0?'原策略20日动量 {value}，满足大于0的筛选条件。':'原策略20日动量 {value}，未满足大于0的筛选条件。',{value:rationalePercent(originalMomentum)});else say(block,'原策略20日动量未记录，暂不判断此项筛选条件。');}
    }
    const momentum=c.momentum||{},m20=rationaleNumber(momentum.momentum20),m60=rationaleNumber(momentum.momentum60),vol=rationaleNumber(momentum.volatility20),strength=node('div','rtp-commentary-block');strength.dataset.indicator='momentum';strength.append(node('h6','',fixed('动量与波动解读')));section.append(strength);
    say(strength,'20日动量 {short}，60日动量 {medium}。',{short:rationalePercent(m20),medium:rationalePercent(m60)});
    if(m20===null||m60===null)say(strength,'动量资料不完整，暂不比较短中期强弱。');
    else if(m20>0&&m60>0)say(strength,'两项动量均为正，短中期累计收益均为正。');
    else if(m20<0&&m60<0)say(strength,'两项动量均为负，短中期累计收益均为负。');
    else if(m20*m60<0)say(strength,'两项动量一正一负，短中期表现分化。');
    else say(strength,'至少一项动量为零，需结合其他条件观察。');
    if(vol!==null&&vol>=0)say(strength,vol<.08?'20日年化波动 {value}，低于8%下限；评分分母按8%计算。':'20日年化波动 {value}；评分分母按实测波动计算。',{value:rationalePercent(vol)});
    else say(strength,'波动率资料不足，暂不解释风险调整。');
    const saved=c.state||{},conclusion=node('div','rtp-commentary-conclusion');conclusion.append(node('h6','',fixed('对当前策略的意义')));section.append(conclusion);
    if(selected.symbol==='sh512800'){
      say(conclusion,'该资产仅使用日线SKDJ，未使用TRIX。');
      say(conclusion,'原策略保存的入场条件：{entry}；退出条件：{exit}。',{entry:originalFlag(saved.entry,fixed('已触发'),fixed('未触发')),exit:originalFlag(saved.exit,fixed('已触发'),fixed('未触发'))});
    }else if(selected.symbol==='sz159915')say(conclusion,'SKDJ、TRIX与50周趋势参与准入；持有期限和回撤保护也会影响原策略状态。');
    else say(conclusion,'该资产使用均线与20日动量筛选，未使用SKDJ或TRIX。');
    say(conclusion,'原策略保存的多头状态：{status}。',{status:originalFlag(saved.long,fixed('多头有效'),fixed('未确认多头'))});
    say(conclusion,'D0配置资格：{status}；已保存模型目标 {weight}，有效评分 {score}。',{status:originalFlag(saved.eligible,fixed('通过'),fixed('未通过')),weight:rationalePercent(saved.target_weight),score:number(momentum.effective_score,3)});
    say(conclusion,'靠拢描述只反映两次已确认观测的差值变化，不预测下一周期交叉，也不会生成交易指令。');
    renderIndicatorTradingRules(section,selected,c);
  }
  function renderDecisionPath(target,a,assets){
    const id=String(a.id),signal=a.signal;
    if(!assets.some(row=>row.symbol===decisionSelections.get(id)))decisionSelections.set(id,(assets.find(row=>row.holdingsKnown&&rationaleNumber(row.holding?.quantity)>0)||assets.find(row=>row.weight>0)||assets[0]).symbol);
    const selected=assets.find(row=>row.symbol===decisionSelections.get(id)),group=node('div','rtp-decision-selectors');group.setAttribute('role','group');group.setAttribute('aria-label',String(fixed('选择 ETF，查看指标怎样变成持仓')));
    for(const row of assets){const b=button('',()=>{decisionSelections.set(id,row.symbol);renderHoldingLogic(account());},'rtp-decision-select');b.dataset.symbol=row.symbol;b.setAttribute('aria-pressed',String(row===selected));b.setAttribute('aria-controls','rtp-decision-panel');b.append(node('span','rtp-decision-name',row.shortName),node('span','rtp-decision-code',row.symbol.slice(2)),node('span','rtp-decision-target',fixed('目标 {weight}',{weight:rationalePercent(row.weight)})));group.append(b);}
    target.append(node('h4','rtp-decision-heading',fixed('指标怎样变成持仓')),node('p','small muted',fixed('选择一只 ETF，沿着已保存的确认信号查看配置过程。')),group);
    const panel=node('div','rtp-decision-panel');panel.id='rtp-decision-panel';panel.dataset.symbol=selected.symbol;panel.setAttribute('role','region');panel.setAttribute('aria-labelledby','rtp-decision-title');const title=node('h4','rtp-decision-title',str(selected.name)+' · '+selected.symbol.slice(2));title.id='rtp-decision-title';panel.append(title);target.append(panel);
    if(!weeklyStrategy()||['sz159915','sh512800'].includes(selected.symbol))renderIndicatorCommentary(panel,selected,signal);
    renderPriceHistory(panel,selected,signal);
    renderOriginalGate(panel,selected,signal);
    if(!weeklyStrategy()||['sz159915','sh512800'].includes(selected.symbol)){
    panel.append(node('h5','rtp-decision-scoring-title',fixed('② 再看 D0 权重评分')));
    const charts=node('div','rtp-decision-charts rtp-history-scoring');panel.append(charts);
    const momentum=originalPair(charts,{selected,signal,id:'momentum',frequency:'daily',unit:'ratio',title:fixed('强弱：20日与60日动量'),rows:[{key:'m20',label:fixed('20日动量'),value:rationaleNumber(selected.momentum20),format:rationalePercent},{key:'m60',label:fixed('60日动量'),value:rationaleNumber(selected.momentum60),format:rationalePercent}]});momentum.append(node('p','small muted',fixed('横线标出零值。动量为正，不等于通过配置资格。')));
    const volatility=originalPair(charts,{selected,signal,id:'volatility',frequency:'daily',unit:'ratio',reference:.08,title:fixed('波动：实际指标与计算下限'),rows:[{key:'vol',label:fixed('20日年化波动'),value:rationaleNumber(selected.volatility20),format:rationalePercent}]});volatility.append(node('p','rtp-decision-floor-label',fixed('横虚线：8% 评分计算下限')),node('p','small muted',fixed('评分的波动分母至少取8%；这不改变实测波动，也不是风险上限。')));
    const pipeline=node('ol','rtp-decision-pipeline');
    for(const [label,value,help] of [[fixed('配置资格'),selected.eligible===true?fixed('通过配置资格'):selected.eligible===false?fixed('未通过配置资格'):fixed('资格依据未记录'),fixed('原策略多头资格、指标完整性、同一确认日共同决定。')],[fixed('有效评分'),savedScore(selected),fixed('直接读取已保存评分；未通过资格的资产不参与权重分配。')],[fixed('模型目标'),rationalePercent(selected.weight),fixed('合格资产按有效评分占比分配；这里显示已保存目标。')]]){const step=node('li','');step.append(node('span','rtp-decision-step-label',label),node('strong','rtp-decision-step-value',value),node('p','small muted',help));pipeline.append(step);}panel.append(pipeline);
    if(selected.score_ready!==true)panel.append(node('p','rtp-wait small',selected.score_ready===false?fixed('评分指标尚未就绪；以已保存资格和目标记录为准。'):fixed('评分完整性状态未记录，不能把缺失指标当作零。')));
    panel.append(node('p','rtp-decision-reason',typeof selected.note==='string'&&selected.note.trim()?selected.note:fixed('未保存此资产的具体判断依据，不能仅凭目标比例推断原因。')));
    }
    const weights=node('div','rtp-decision-weights');weights.append(node('h5','',fixed('四只 ETF 的已保存目标')));for(const row of assets){const item=node('div','rtp-decision-weight'),label=node('div','rtp-decision-metric-label');label.append(node('span','',row.shortName),node('strong','',rationalePercent(row.weight)));const track=node('div','rtp-decision-weight-track');track.setAttribute('aria-hidden','true');if(row.weight!==null){const fill=node('span','rtp-decision-bar rtp-decision-positive');fill.style.width=row.weight*100+'%';track.append(fill);}item.append(label,track);weights.append(item);}panel.append(weights);
    const actual=node('section','rtp-decision-actual'),list=node('dl'),quantity=selected.holdingsKnown?selected.holding?.quantity??0:null,ratio=actualHoldingRatio(a,selected),orders=Array.isArray(a.orders)&&a.orders.every(row=>row&&typeof row.symbol==='string'&&typeof row.status==='string')?a.orders:null;
    actual.append(node('h5','',fixed('目标之后：实际账户记录')));line(list,fixed('实际持有'),quantity===null?fixed('待核对'):decimal(quantity)+fixed(' 份'));line(list,fixed('实际资产占比'),ratio===null?fixed('估值待核对'):rationalePercent(ratio));line(list,fixed('此 ETF 待执行委托'),orders===null?fixed('待核对'):fixed('{count} 笔',{count:orders.filter(row=>row.symbol===selected.symbol&&pending.has(row.status)).length}));actual.append(list);
    if(ratio===null)actual.append(node('p','small rtp-wait',fixed('实际占比仅在账户与持仓估值均新鲜、且本次状态已核对时显示；保留的份额不代表当前估值。')));
    const quoteTimes=node('dl','rtp-decision-quote-times'),quoteRows=Array.isArray(state.data?.quotes)?state.data.quotes.filter(row=>row?.symbol===selected.symbol):[],marketRows=Array.isArray(state.data?.market_quotes)?state.data.market_quotes.filter(row=>row?.symbol===selected.symbol):[];
    line(quoteTimes,fixed('市场报价时间（仅展示）'),compactTime(marketRows.length===1?marketRows[0].quote_at:null));line(quoteTimes,fixed('账户接纳报价时间'),compactTime(quoteRows.length===1?quoteRows[0].quote_at:null));if(selected.holding)line(quoteTimes,fixed('持仓估值引用时间'),compactTime(selected.holding.quote_at));actual.append(quoteTimes,node('p','small muted',fixed('市场报价与账户接纳报价分别展示；市场报价更新不会直接改写账户估值。')));panel.append(actual);
    const timeline=node('ol','rtp-decision-timeline');
    for(const [label,value,help] of [[fixed('确认日与数据截止'),str(signal.confirmed_day),compactTime(signal.data_cutoff)],[fixed('信号首次可知'),compactTime(signal.known_at),fixed('信号记录时间：{time}',{time:compactTime(signal.signal_at)})],[fixed('最早执行日'),str(signal.execution_day),fixed('最早从执行日的连续竞价窗口参与模拟；仍须满足账户状态、报价和委托条件。')]]){const step=node('li','');step.append(node('span','rtp-decision-step-label',label),node('strong','',value),node('p','small muted',help));timeline.append(step);}panel.append(node('h5','rtp-decision-timing-title',fixed('何时确认，何时改变持仓')),timeline);
    const windows=Array.isArray(state.data?.model?.windows)?state.data.model.windows.filter(value=>typeof value==='string'&&/^\d{2}:\d{2}-\d{2}:\d{2}$/.test(value)):[];if(windows.length)panel.append(node('p','small muted',fixed('模拟连续竞价窗口（北京时间）：{windows}',{windows:windows.join(' / ')})));
    const status=node('div','rtp-decision-status'),statusList=node('dl'),service=state.data?.service||{};line(statusList,fixed('账户运行状态'),holdingSnapshotCurrent()?({running:fixed('运行中 · 模拟估计'),paused:fixed('已暂停'),stopped:fixed('已停止')}[a.status]||fixed('状态待核对')):fixed('状态待核对'));line(statusList,fixed('后台观察状态'),holdingSnapshotCurrent()?({running:fixed('观察中'),stopped:fixed('已停止'),waiting:fixed('等待'),error:fixed('异常')}[service.observer_status]||fixed('状态待核对')):fixed('状态待核对'));line(statusList,fixed('执行状态'),holdingSnapshotCurrent()?({active:fixed('估计执行中'),waiting:fixed('等待'),stopped:fixed('已停止'),needs_review:fixed('状态待核对')}[a.execution_state]||fixed('状态待核对')):fixed('状态待核对'));status.append(statusList);const wait=accountWaitingReason(a);if(wait)status.append(node('p','rtp-wait small',wait));status.append(node('p','small muted',fixed('信号更新先改变目标；实际份额在后续模拟估计成交记账后改变。页面切换与查看指标不会提交委托。')));panel.append(status);
  }
  function signalSummaryCurrent(){
    const generated=Date.parse(state.data?.generated_at),elapsed=state.readAt===null?Infinity:performance.now()-state.readAt;
    return holdingSnapshotCurrent()&&!state.pnlFromCommand&&elapsed>=0&&elapsed<=65000&&Number.isFinite(generated)&&Date.now()-generated>=-5000&&Date.now()-generated<=65000;
  }
  function signalSummaryReadState(){return holdingReadState()+':'+signalSummaryCurrent()+':'+Boolean(state.pnlFromCommand);}
  function signalSummaryView(a){
    const s=a?.signal_summary,fail={status:'invalid',summary:null},symbols=['sz159915','sh512800','sh518880','sh511010'];
    if(!s)return {status:'missing',summary:null};
    const identifier=v=>typeof v==='string'&&v.length>0&&v.length<=200&&!/[\u0000-\u001f]/.test(v),nullableId=v=>v===null||identifier(v),quantity=v=>Number.isSafeInteger(v)&&v>=0&&v<=1000000000000,day=v=>v===null||typeof v==='string'&&historyDay(v)!==null,stamp=v=>v===null||typeof v==='string'&&/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v)),text=v=>v===null||typeof v==='string'&&v.length<=4096,weight=v=>v===null||typeof v==='string'&&/^\d+(?:\.\d+)?$/.test(v)&&v.length<=64&&Number(v)>=0&&Number(v)<=1;
    if(s.contract_version!=='d0-signal-summary-v1'||s.is_trade_instruction!==false||s.account_id!==a.id||s.generated_at!==state.data?.generated_at||!stamp(s.generated_at)||!s.generated_at||!nullableId(s.signal_id)||!nullableId(s.plan_id)||s.signal_id!==(a.signal?.id??null)||s.plan_id!==(a.plan_id??null))return fail;
    const enums={signal_status:['confirmed','missing','invalid'],plan_status:['current','missing','historical','invalid'],reference_status:['current','saved','unavailable','invalid'],action:['buy','sell','rebalance','hold','cash','wait'],execution_status:['ready','waiting','stopped','needs_review'],reason_code:['ready','account_stopped','no_signal','invalid_signal','no_plan','old_plan','invalid_plan','invalid_positions','invalid_orders','command_snapshot','before_eligible','outside_session','source_not_ready','observer_not_running','unknown_account']};
    if(Object.entries(enums).some(([key,values])=>!values.includes(s[key]))||!day(s.confirmed_day)||!day(s.execution_day)||!['eligible_at','signal_at','known_at','data_cutoff','plan_created_at'].every(key=>stamp(s[key]))||!text(s.saved_reason)||!Array.isArray(s.assets)||s.assets.length!==4)return fail;
    if(s.signal_status==='confirmed'&&(!s.signal_id||a.signal?.valid!==true||s.confirmed_day!==a.signal.confirmed_day||s.execution_day!==a.signal.execution_day)||s.plan_status==='current'&&(s.signal_status!=='confirmed'||!s.plan_id)||s.reference_status==='current'&&(s.plan_status!=='current'||s.execution_status!=='ready'))return fail;
    const progress=['no_plan','needs_review','pending_order','terminal_order','target_reached','awaiting_submission','waiting_sell','sellable_limited'],seen=new Set(),holdings=verifiedHoldings(a),orders=Array.isArray(a.orders)?a.orders:[];
    for(const row of s.assets){
      if(!row||!symbols.includes(row.symbol)||seen.has(row.symbol)||!weight(row.target_weight)||!(row.actual_quantity===null||quantity(row.actual_quantity))||!(row.target_quantity===null||quantity(row.target_quantity))||!(row.difference_quantity===null||Number.isSafeInteger(row.difference_quantity)&&Math.abs(row.difference_quantity)<=1000000000000)||!['buy','sell','hold','cash','wait'].includes(row.action)||!progress.includes(row.progress)||!identifier(row.reason_code)||!quantity(row.pending_quantity)||![null,'buy','sell'].includes(row.pending_side)||![null,'cancelled','canceled','rejected','expired'].includes(row.terminal_status)||!Array.isArray(row.order_ids)||row.order_ids.length>1000||new Set(row.order_ids).size!==row.order_ids.length||!row.order_ids.every(identifier))return fail;
      seen.add(row.symbol);const t=row.trigger;
      if(s.signal_status==='confirmed'&&(row.target_weight===null||!weight(a.signal?.weights?.[row.symbol])||a.signal.weights[row.symbol]===null||Number(row.target_weight)!==Number(a.signal.weights[row.symbol])))return fail;
      if(!t||![true,false,null].includes(t.eligible)||![true,false,null].includes(t.score_ready)||!(t.effective_score===null||typeof t.effective_score==='number'&&Number.isFinite(t.effective_score))||!text(t.note))return fail;
      if(row.actual_quantity!==null&&(!holdings||row.actual_quantity!==(holdings.find(h=>h.symbol===row.symbol)?.quantity??0)))return fail;
      if(s.plan_status==='current'&&!(s.reference_status==='invalid'&&s.execution_status==='needs_review'&&row.action==='wait'&&row.progress==='needs_review')){
        if(!quantity(row.actual_quantity)||!quantity(row.target_quantity)||row.difference_quantity!==row.target_quantity-row.actual_quantity||row.action!==(row.difference_quantity>0?'buy':row.difference_quantity<0?'sell':row.actual_quantity>0?'hold':'cash'))return fail;
      }else if(row.action!=='wait'||(row.target_quantity!==null||row.difference_quantity!==null)&&!(s.plan_status==='current'&&quantity(row.actual_quantity)&&quantity(row.target_quantity)&&row.difference_quantity===row.target_quantity-row.actual_quantity))return fail;
      if(row.pending_quantity>0){
        if(row.progress!=='pending_order'||!['buy','sell'].includes(row.pending_side)||row.action!==row.pending_side||!row.order_ids.length||row.pending_quantity>Math.abs(row.difference_quantity))return fail;
        const matched=row.order_ids.map(id=>orders.filter(o=>o?.id===id));
        if(matched.some(items=>items.length!==1)||matched.some(([o])=>o.symbol!==row.symbol||o.signal_id!==s.signal_id||o.plan_id!==s.plan_id||o.side!==row.pending_side||!pending.has(o.status)||!quantity(o.remaining_quantity))||matched.reduce((sum,[o])=>sum+o.remaining_quantity,0)!==row.pending_quantity)return fail;
      }else if(row.pending_side!==null||row.progress==='pending_order')return fail;
      if(row.progress==='terminal_order'){
        if(!row.terminal_status||!row.order_ids.length||!['buy','sell'].includes(row.action))return fail;
        for(const id of row.order_ids){const matches=orders.filter(o=>o?.id===id);if(matches.length!==1)return fail;const o=matches[0],expiredPending=row.terminal_status==='expired'&&pending.has(o.status)&&stamp(o.expires_at)&&o.expires_at!==null&&Date.parse(o.expires_at)<=Date.parse(s.generated_at);if(o.symbol!==row.symbol||o.signal_id!==s.signal_id||o.plan_id!==s.plan_id||o.side!==row.action||o.status!==row.terminal_status&&!expiredPending)return fail;}
      }else if(row.terminal_status!==null||row.progress!=='pending_order'&&row.order_ids.length)return fail;
    }
    if(s.plan_status==='current'){
      const buy=s.assets.some(row=>row.action==='buy'),sell=s.assets.some(row=>row.action==='sell'),action=s.assets.some(row=>row.action==='wait')?'wait':buy&&sell?'rebalance':buy?'buy':sell?'sell':s.assets.some(row=>row.action==='hold')?'hold':'cash';
      if(s.action!==action)return fail;
    }else if(s.action!=='wait')return fail;
    if(s.latest_fill!==null){
      const f=s.latest_fill,match=Array.isArray(a.fills)?a.fills.filter(row=>row?.id===f?.id):[];
      if(!f||!['id','order_id','signal_id','plan_id'].every(key=>identifier(f[key]))||!symbols.includes(f.symbol)||!['buy','sell'].includes(f.side)||!quantity(f.quantity)||f.quantity===0||typeof f.price!=='string'||!/^\d+(?:\.\d+)?$/.test(f.price)||f.price.length>64||!Number.isFinite(Number(f.price))||Number(f.price)<=0||!stamp(f.matched_at)||!f.matched_at||Date.parse(f.matched_at)>Date.parse(s.generated_at)||typeof f.current_signal!=='boolean'||typeof f.current_plan!=='boolean'||f.current_signal!==(s.signal_status==='confirmed'&&f.signal_id===s.signal_id)||f.current_plan!==(s.plan_status==='current'&&f.plan_id===s.plan_id&&f.signal_id===s.signal_id)||match.length!==1)return fail;
      if(['order_id','signal_id','plan_id','symbol','side','quantity','matched_at'].some(key=>f[key]!==match[0][key])||Number(f.price)!==Number(match[0].price))return fail;
    }
    return {status:'available',summary:s};
  }
  function signalSummaryAction(action){return ({buy:fixed('计划增持'),sell:fixed('计划减持'),rebalance:fixed('计划调仓'),hold:fixed('按计划持有'),cash:fixed('按计划空仓'),wait:fixed('等待计划确认')})[action]||fixed('状态待核对');}
  function signalSummaryReason(code,a){
    if(code==='source_not_ready'){const detail=accountWaitingReason(a);if(detail)return detail;const service=state.data?.service||{};return waitingReason(service.waiting_reason,service.reason_code,fixed('资料尚未就绪，等待更新'));}
    return ({ready:fixed('当前快照条件已核对，成交以委托记录为准。'),account_stopped:fixed('账户已暂停或停止，保留已保存的信号与计划。'),no_signal:fixed('尚无确认信号，等待收盘资料。'),invalid_signal:fixed('信号资料待核对，暂不展示计划动作。'),no_plan:fixed('目标已确认，等待建立执行计划。'),old_plan:fixed('已保存计划不属于当前信号或运行轮次，等待新计划。'),invalid_plan:fixed('执行计划资料待核对，暂不展示计划动作。'),invalid_positions:fixed('实际份额资料待核对，暂不展示计划动作。'),invalid_orders:fixed('委托关联资料待核对，暂不展示计划动作。'),command_snapshot:fixed('操作后的状态仍待下一次账户读取核对。'),before_eligible:fixed('尚未到达计划最早执行时间。'),outside_session:fixed('当前不在模拟连续竞价窗口，等待下个交易时段。'),observer_not_running:fixed('后台观察尚未就绪，等待状态恢复。'),unknown_account:fixed('账户资料待核对。')})[code]||fixed('状态待核对');
  }
  function signalSummaryProgress(row){
    if(row.progress==='terminal_order')return fixed('本轮委托已结束，剩余计划差额不会自动重试。');
    return ({no_plan:fixed('尚无当前执行计划'),needs_review:fixed('计划或记录待核对'),pending_order:fixed('已有模拟委托，等待满足成交条件'),target_reached:fixed('实际份额已达到计划目标'),awaiting_submission:fixed('仍有计划差额，尚未提交委托'),waiting_sell:fixed('先卖后买，等待卖出步骤'),sellable_limited:fixed('可卖份额不足，等待规则允许')})[row.progress]||fixed('状态待核对');
  }
  function signalTradeExplanation(summary,row,current,globalReason=null){
    const result={kind:'wait',heading:fixed('为什么还在等待'),lines:[],note:null},say=(text,values={})=>result.lines.push(fixed(text,values));
    if(!current){result.kind='stale';result.heading=fixed('交易逻辑待刷新');say('当前账户状态尚未核对，买卖原因等待刷新后说明；上次计划不能代表当前动作。');return result;}
    if(!summary||!row||summary.signal_status!=='confirmed'||summary.reference_status==='invalid'||row.progress==='needs_review'){
      result.kind='needs_review';result.heading=fixed('交易依据需要核对');say('信号、计划或持仓资料需要核对，暂不补写当前买卖原因。');return result;
    }
    const trigger=row.trigger||{},weight=rationaleNumber(row.target_weight),actual=row.actual_quantity,target=row.target_quantity,gap=row.difference_quantity;
    if(typeof trigger.note==='string'&&trigger.note.trim())result.note=trigger.note;
    if(summary.plan_status!=='current'||row.action==='wait'){
      result.kind='no_plan';say('本次已确认目标比例为 {weight}，当前缺少与信号匹配的执行计划，等待计划建立后再判断买卖份额。',{weight:rationalePercent(weight)});
      if(actual===0)say('账户当前没有这只ETF；目标比例尚未转成可核对的买入计划。');
      if(globalReason)result.lines.push(globalReason);return result;
    }
    const quantity=value=>Number.isSafeInteger(value)&&value>=0&&value<=1000000000000;
    if(weight===null||!quantity(actual)||!quantity(target)||!Number.isSafeInteger(gap)||gap!==target-actual||row.action!==(gap>0?'buy':gap<0?'sell':actual>0?'hold':'cash')||trigger.eligible===false&&weight>0||trigger.eligible===true&&trigger.score_ready===false||target>0&&weight===0){
      result.kind='needs_review';result.heading=fixed('交易依据需要核对');result.note=null;say('配置资格、目标或份额记录存在不一致，需要核对后才能解释交易原因。');return result;
    }
    const values={actual:decimal(actual),target:decimal(target),gap:decimal(Math.abs(gap)),weight:rationalePercent(weight)};
    if(row.action==='buy'){
      result.kind=actual===0?'buy_open':'buy_add';result.heading=fixed('为什么计划买入');
      say(actual===0?'本次计划目标为 {target} 份，实际尚未持有，仍差 {gap} 份，因此计划买入。':'当前已有 {actual} 份，计划目标为 {target} 份，还需补足 {gap} 份，因此计划增持。',values);
      if(trigger.eligible===true)say('本次配置资格已通过，按合格资产的动量／波动评分分配到 {weight} 的模型目标。',values);
    }else if(row.action==='sell'){
      result.kind=target===0?'sell_exit':'sell_reduce';result.heading=fixed('为什么计划卖出');
      say(target===0?'本轮计划目标为0份，当前仍有 {actual} 份，因此计划退出已有仓位。':'本轮计划保留 {target} 份，当前持有 {actual} 份，超出 {gap} 份，因此计划减持差额。',values);
      if(trigger.eligible===false)say('本次配置资格未通过；具体失效条件以保存的筛选依据为准。');
      else if(trigger.eligible===true&&target>0)say('这只ETF仍通过配置资格，本轮按计划减少份额并保留其余仓位。');
      else if(trigger.eligible===true&&target===0)say('模型目标比例为 {weight}，本轮计划目标份额为0；具体份额以保存的计划为准。',values);
    }else if(row.action==='hold'){
      result.kind='hold';result.heading=fixed('为什么继续持有');say('实际持仓与计划目标均为 {actual} 份，本轮没有剩余买卖差额，因此按计划持有。',values);
    }else if(row.action==='cash'){
      result.kind=weight>0?'cash_no_shares':trigger.eligible===false?'cash_ineligible':'cash_target_zero';result.heading=fixed('为什么当前不持仓');
      if(weight>0){say('模型目标比例为 {weight}，但本轮计划目标与实际份额均为0，目前没有可执行的买入差额。',values);say('具体未形成目标份额的约束需结合保存的计划记录核对。');}
      else if(trigger.eligible===false)say('本次配置资格未通过，模型目标为0%，计划目标和实际份额也都是0，因此保持空仓。');
      else say('本次模型目标、计划目标份额和实际份额均为0，本轮计划保持空仓。');
    }
    if(trigger.eligible===null||trigger.eligible===undefined)say('配置资格的详细依据未记录，这里只解释已保存的计划差额。');
    if(gap!==0&&summary.reason_code!=='ready'&&globalReason)result.lines.push(globalReason);
    const progress={pending_order:'已经提交模拟委托，正在等待成交条件；委托尚未计为成交。',waiting_sell:'本轮按先卖后买顺序执行，买入步骤正在等待卖出步骤完成。',sellable_limited:'当前可卖份额不足，剩余卖出计划等待规则允许。',terminal_order:'本轮委托已经结束，剩余计划差额不会自动重试；原目标与已结束委托分开保留。',awaiting_submission:'计划仍有份额差额，委托尚未提交。'};
    if(progress[row.progress])say(progress[row.progress]);
    return result;
  }
  function renderSignalSummary(a){
    const target=fields.signalSummary;if(!target)return;const focused=target.contains(document.activeElement)?document.activeElement:null,focusKey=focused?.dataset?.signalControl,focusDetail=focused?.tagName==='SUMMARY'?focused.parentElement.dataset.detailKey:null,open=new Set([...target.querySelectorAll('details[open][data-detail-key]')].map(d=>d.dataset.detailKey));
    fields.signalSummaryReadState=signalSummaryReadState();target.replaceChildren();target.hidden=!a;target.dataset.signalId='';target.dataset.planId='';target.dataset.action='wait';target.dataset.execution='needs_review';if(!a)return;
    target.append(node('h3','',weeklyStrategy()?fixed('D0I-BOND-WW 策略信号'):fixed('D0 策略信号')),node('p','small muted',fixed('查看当前账户的确认目标、计划动作和执行进度。')));
    const view=signalSummaryView(a),current=signalSummaryCurrent();target.dataset.snapshotCurrent=String(current);target.dataset.summaryStatus=view.status;
    if(view.status!=='available'){
      target.dataset.action='wait';target.dataset.execution='needs_review';target.append(node('p','rtp-wait',view.status==='missing'?fixed('当前快照尚无策略信号摘要，请刷新状态。'):fixed('策略信号摘要与账户记录未通过核对，暂不展示买卖方向。')));return;
    }
    const s=view.summary,directions=current&&s.reference_status!=='invalid';target.dataset.signalId=s.signal_id||'';target.dataset.planId=s.plan_id||'';target.dataset.action=current?s.action:'wait';target.dataset.execution=current?s.execution_status:'needs_review';
    const banner=node('div','rtp-signal-banner'),intent=node('div','rtp-signal-headline'),execution=node('div','rtp-signal-execution');
    intent.append(node('span','small muted',current&&s.reference_status==='current'?fixed('计划动作'):fixed('已保存的计划')),node('strong','rtp-signal-action',current?signalSummaryAction(s.action):fixed('当前状态待核对')));
    execution.append(node('span','small muted',fixed('执行进度')),node('strong','',current?({ready:fixed('条件已就绪'),waiting:fixed('等待执行条件'),stopped:fixed('账户已暂停或停止'),needs_review:fixed('需要核对')})[s.execution_status]:fixed('等待刷新确认')));banner.append(intent,execution);target.append(banner);
    if(!current)target.append(node('p','rtp-wait',fixed('当前状态正在读取或尚未核对；以下仅保留上次确认目标，买卖方向暂不展示。')));
    else target.append(node('p','rtp-signal-reason',signalSummaryReason(s.reason_code,a)));
    const dates=node('dl','rtp-signal-meta');line(dates,fixed('信号确认日'),str(s.confirmed_day));line(dates,fixed('最早执行日'),str(s.execution_day));line(dates,fixed('账户快照时间'),compactTime(s.generated_at));target.append(dates);
    target.append(node('p','rtp-trade-primer',fixed('交易逻辑分三步：先确认配置资格，再给合格资产分配目标，最后比较计划目标份额与实际持仓。每只ETF的配置原因和执行等待原因分开说明。')));
    if(s.saved_reason){const reason=disclosure(fixed('查看整体配置依据'),'rtp-signal-saved-reason');reason.append(node('p','rtp-signal-saved-reason',s.saved_reason));target.append(reason);}
    const cards=node('div','rtp-signal-grid');target.append(cards);
    const names=['创业板ETF','银行ETF','黄金ETF','5年国债ETF'],symbols=['sz159915','sh512800','sh518880','sh511010'];
    for(const symbol of symbols){
      const row=s.assets.find(item=>item.symbol===symbol),rule=unique(state.data?.rules).find(item=>item.symbol===symbol),name=rule?.name||fixed(names[symbols.indexOf(symbol)]),card=node('article','rtp-signal-asset');card.dataset.signalSymbol=symbol;card.dataset.action=directions?row.action:'wait';
      const title=node('div','rtp-signal-asset-heading');title.append(node('h4','',str(name)),node('span','small muted',symbol.slice(2)));card.append(title,node('strong','rtp-signal-direction',directions?signalSummaryAction(row.action):fixed('当前状态待核对')));
      const values=node('dl','rtp-signal-values');line(values,fixed('确认目标比例'),row.target_weight===null?fixed('待核对'):rationalePercent(row.target_weight));line(values,fixed('实际份额'),row.actual_quantity===null?fixed('待核对'):decimal(row.actual_quantity)+fixed(' 份'));line(values,fixed('计划目标份额'),row.target_quantity===null?fixed('尚未确认'):decimal(row.target_quantity)+fixed(' 份'));card.append(values);
      const explanation=signalTradeExplanation(s,row,current,signalSummaryReason(s.reason_code,a)),logic=node('section','rtp-trade-explanation');logic.dataset.logicKind=explanation.kind;logic.append(node('h5','',explanation.heading));for(const text of explanation.lines)logic.append(node('p','',text));if(explanation.note){const evidence=node('p','rtp-trade-saved-note');evidence.append(node('strong','',fixed('保存的筛选依据：')),node('span','',explanation.note));logic.append(evidence);}card.append(logic);
      if(current){card.append(node('p','rtp-signal-progress small',signalSummaryProgress(row)));if(row.progress==='terminal_order')card.append(node('p','small rtp-wait',fixed('委托状态：{status}',{status:statusLabels[row.terminal_status]||fixed('已结束')})));if(row.pending_quantity>0)card.append(node('p','small',fixed('已提交{side}委托：{quantity}份',{side:row.pending_side==='buy'?fixed('买入'):fixed('卖出'),quantity:decimal(row.pending_quantity)})));}
      const detail=disclosure(fixed('触发依据与指标'),'rtp-signal-reason-'+symbol),trigger=node('dl');line(trigger,fixed('配置资格'),row.trigger.eligible===true?fixed('通过配置资格'):row.trigger.eligible===false?fixed('未通过配置资格'):fixed('资格依据未记录'));if(weeklyStrategy()&&['sh511010','sh518880'].includes(symbol)){line(trigger,fixed('配置方式'),symbol==='sh511010'?fixed('已完成周资格防守，不参与股票评分'):fixed('本策略排除黄金'));}else{line(trigger,fixed('评分资料'),row.trigger.score_ready===true?fixed('已就绪'):row.trigger.score_ready===false?fixed('尚未就绪'):fixed('未记录'));line(trigger,fixed('已保存有效评分'),row.trigger.effective_score===null?fixed('未记录'):new Intl.NumberFormat(window.ETF_I18n?.language==='en'?'en-US':'zh-CN',{maximumFractionDigits:4}).format(row.trigger.effective_score));}detail.append(trigger,node('p','small',row.trigger.note||fixed('未保存具体触发说明，可查看已有指标依据。')));
      const chart=button(fixed('查看此 ETF 的指标曲线'),()=>{const live=account();if(live?.id!==a.id||live.signal?.id!==s.signal_id)return;decisionSelections.set(String(a.id),symbol);renderHoldingLogic(live);const heading=fields.holdingLogic.querySelector('#rtp-decision-title');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});heading.scrollIntoView({block:'start'});}});chart.disabled=!s.signal_id||!a.signal;chart.dataset.signalControl='chart-'+symbol;chart.setAttribute('aria-label',String(fixed('查看{asset}的指标曲线',{asset:name})));detail.append(chart);card.append(detail);cards.append(card);
    }
    const fill=s.latest_fill,fillBox=node('div','rtp-signal-fill');fillBox.append(node('h4','',fixed('最近一笔已记录模拟成交')));
    if(fill){const rule=unique(state.data?.rules).find(item=>item.symbol===fill.symbol);fillBox.append(node('p','',str(rule?.name,fill.symbol.slice(2))+' · '+(fill.side==='buy'?fixed('买入'):fixed('卖出'))+' '+decimal(fill.quantity)+fixed(' 份')+' × '+decimal(fill.price)+fixed(' 元')),node('p','small muted',compactTime(fill.matched_at)+(fill.current_signal&&fill.current_plan?'':fixed(' · 历史信号或计划的成交记录'))),node('p','small muted',fill.current_signal&&fill.current_plan?fixed('这笔模拟成交用于执行本轮信号对应的委托计划；上方文字说明当前剩余计划。'):fixed('这笔成交属于历史信号或计划；当前指标不用于补写它当时的交易原因。')));}
    else fillBox.append(node('p','small muted',fixed('暂无可核对的最近成交摘要，可在成交明细中查看记录。')));target.append(fillBox);
    target.append(node('p','small muted rtp-signal-note',fixed('计划动作根据已保存的目标份额显示；新信号先改变目标，实际持仓在模拟成交记账后更新。盘中行情用于估值，不直接生成新的策略信号。')));
    for(const detail of target.querySelectorAll('details[data-detail-key]')){if(open.has(detail.dataset.detailKey))detail.open=true;if(detail.dataset.detailKey===focusDetail)detail.querySelector('summary')?.focus({preventScroll:true});}
    if(focusKey)for(const control of target.querySelectorAll('[data-signal-control]'))if(control.dataset.signalControl===focusKey)control.focus({preventScroll:true});
  }

  function pnlDecimal(value,ratio=false){
    const pattern=ratio?/^-?\d+\.\d{8}$/:/^-?\d+\.\d{2}$/;
    if(typeof value!=='string'||value.length>120||!pattern.test(value))return null;
    const negative=value.startsWith('-'),unsigned=negative?value.slice(1):value,[integer,fraction]=unsigned.split('.'),zero=!/[1-9]/.test(unsigned);
    let whole=integer.replace(/^0+(?=\d)/,''),decimalPart=fraction;
    // This only formats a backend Decimal ratio as percent; no account arithmetic runs here.
    if(ratio){whole=(whole+fraction.slice(0,2)).replace(/^0+(?=\d)/,'');decimalPart=fraction.slice(2).replace(/0+$/,'').padEnd(2,'0');}
    const direction=zero?'flat':negative?'loss':'gain';
    return {raw:value,direction,text:(direction==='loss'?'−':direction==='gain'?'+':'')+whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+'.'+decimalPart+(ratio?'%':''),unsigned:whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+'.'+decimalPart};
  }
  function pnlFreshRemaining(a,pnl){
    if(pnl.status!=='fresh'||pnl.cash_only)return Infinity;
    const limits=state.data?.model?.freshness,source=priceTimestamp(pnl.valuation_at),snapshot=priceTimestamp(pnl.snapshot_at),generated=priceTimestamp(state.data?.generated_at),receipts=Array.isArray(a.holdings)?a.holdings.map(row=>priceTimestamp(row?.received_at)):[],match=limits?.match_age_max_seconds,queue=limits?.queue_delay_max_seconds;
    if(source===null||snapshot===null||generated===null||state.readAt===null||!receipts.length||receipts.some(value=>value===null)||typeof match!=='number'||typeof queue!=='number'||!Number.isFinite(match)||!Number.isFinite(queue)||match<=0||queue<=0||match>86400||queue>86400)return null;
    // Expire only the display badge; amounts and account state stay untouched.
    return Math.min(source+match*1000,...receipts.map(value=>value+queue*1000))-Math.max(snapshot,generated)-Math.max(0,performance.now()-state.readAt);
  }
  function renderAccountPnl(target,a){
    clearTimeout(fields.pnlExpiry);fields.pnlExpiry=null;fields.pnlReadState=holdingReadState();target.replaceChildren();if(!a)return;
    const raw=a.pnl,valid=raw?.contract_version==='d0-account-pnl-v1'&&raw.basis==='account_equity_and_remaining_cost'&&['fresh','stale','missing'].includes(raw.status)&&typeof raw.cash_only==='boolean'&&raw.fees_included===true&&raw.frozen_cash_included===true,pnl=valid?raw:{status:'missing'},remaining=pnlFreshRemaining(a,pnl),expired=remaining!==null&&remaining<0,current=holdingSnapshotCurrent()&&!state.pnlFromCommand&&remaining!==null&&!expired,effectiveStatus=expired?'stale':pnl.status;
    target.dataset.pnlStatus=effectiveStatus;target.dataset.snapshotCurrent=String(current);target.setAttribute('aria-labelledby','rtp-account-pnl-title');
    const title=node('h3','',current?fixed('账户当前盈亏'):fixed('账户盈亏（缓存估值）'));title.id='rtp-account-pnl-title';target.append(title,node('p','small muted rtp-pnl-basis',fixed('从账户本金起累计，非今日盈亏；与本账户总资产估值使用同一份报价。')));
    if(!current)target.append(node('p','rtp-wait rtp-pnl-cache',fixed('缓存估值 · 状态待刷新：以下金额来自上次成功快照，不能视为当前最新盈亏。')));
    const metric=(parent,key,label,ratio=false,fee=false)=>{let value=pnlDecimal(pnl[key],ratio);if(fee&&value?.direction==='loss')value=null;const card=node('div','rtp-pnl-metric');card.dataset.pnlField=key;card.dataset.pnlDirection=fee?'neutral':value?.direction||'unknown';const amount=node('dd','rtp-pnl-value',value?(fee?value.unsigned:value.text)+(ratio?'':String(fixed(' 元'))):'—');card.append(node('dt','',label),amount);if(!fee){const direction=value?({gain:fixed('盈利'),loss:fixed('亏损'),flat:fixed('持平')}[value.direction]):fixed('待核对');card.append(node('dd','rtp-pnl-direction',direction));}parent.append(card);};
    const main=node('dl','rtp-pnl-main');metric(main,'total_pnl',current?fixed('当前累计盈亏'):fixed('累计盈亏（缓存）'));metric(main,'return_ratio',fixed('累计收益率'),true);target.append(main);
    const detail=node('dl','rtp-pnl-breakdown');metric(detail,'realized_pnl',fixed('已实现盈亏'));metric(detail,'unrealized_pnl',fixed('持仓浮动盈亏'));metric(detail,'fees_paid',fixed('已付模拟费用'),false,true);target.append(detail);
    const valuation=effectiveStatus==='stale'?fixed('估值已过期；以上为保留报价下的累计盈亏估算。'):pnl.status==='missing'?fixed('盈亏资料不完整；无法核对的项目显示 —。'):pnl.cash_only?fixed('无持仓；盈亏按本账户现金余额核算。'):fixed('按账户已接纳报价估算；市场报价更新不会直接改写此处盈亏。');target.append(node('p',effectiveStatus==='fresh'?'small muted':'small rtp-wait',valuation));
    const reasons={missing_valuation:fixed('部分持仓缺少估值报价，累计及浮动盈亏暂不可用。'),incomplete_cost:fixed('持仓成本记录不完整，部分盈亏待核对。'),invalid_account:fixed('账户金额记录待核对。'),inconsistent_valuation:fixed('账户估值与持仓记录不一致，部分盈亏暂不可用。'),invalid_fee_evidence:fixed('已付费用记录待核对。'),missing_quote_time:fixed('估值源时间未完整记录，请先核对。')};
    if(valid&&Object.hasOwn(reasons,pnl.reason))target.append(node('p','small rtp-wait',reasons[pnl.reason]));
    if(pnl.cash_only){if(priceTimestamp(pnl.snapshot_at)!==null)target.append(node('p','small muted rtp-pnl-asof',fixed('账户快照时间：{time}',{time:compactTime(pnl.snapshot_at)})));}
    else if(priceTimestamp(pnl.valuation_at)!==null){const latest=priceTimestamp(pnl.latest_quote_at),first=priceTimestamp(pnl.valuation_at);target.append(node('p','small muted rtp-pnl-asof',latest!==null&&latest!==first?fixed('估值引用源时间：{first} 至 {last}',{first:compactTime(pnl.valuation_at),last:compactTime(pnl.latest_quote_at)}):fixed('估值引用源时间：{time}',{time:compactTime(pnl.valuation_at)})));}
    target.append(node('p','small muted rtp-pnl-fees-note',fixed('已付模拟费用已计入盈亏，不再重复扣除；冻结现金仍包含在账户资产中。')));
    if(current&&Number.isFinite(remaining))fields.pnlExpiry=setTimeout(()=>{if(state.active&&fields.accountPnl===target)renderAccountPnl(target,account());},Math.max(1,remaining+1));
  }
  function pnlHistoryReadState(){return holdingReadState()+':'+Boolean(state.pnlFromCommand);}
  function pnlHistorySeries(a){
    const h=a?.pnl_history,none=reason=>({status:'unavailable',reason,points:[]});
    if(!h)return none('history_unavailable');
    if(h.contract_version!=='d0-account-pnl-history-v1'||h.source!=='recorded_account_valuation'||h.basis!=='daily_last_observation'||h.retention_limit!==366||typeof h.truncated!=='boolean'||h.current_segment!==null&&(typeof h.current_segment!=='string'||!h.current_segment||h.current_segment.length>200))return none('invalid_history');
    if(h.status!=='available')return none(h.status==='unavailable'&&['no_recorded_valuations','history_unavailable','invalid_history'].includes(h.reason)?h.reason:'invalid_history');
    if(!Array.isArray(h.points)||h.points.length>366)return none('invalid_history');
    const points=[],identities=new Set(),capitalBySegment=new Map(),generated=priceTimestamp(state.data?.generated_at);let previous=null;
    for(const raw of h.points){
      const day=historyDay(raw?.date),observed=priceTimestamp(raw?.observed_at),valuation=raw?.valuation_at===null?null:priceTimestamp(raw?.valuation_at),latest=raw?.latest_quote_at===null?null:priceTimestamp(raw?.latest_quote_at),capital=pnlDecimal(raw?.initial_capital),equity=pnlDecimal(raw?.equity),cumulative=pnlDecimal(raw?.cumulative_pnl),daily=raw?.daily_pnl===null?null:pnlDecimal(raw?.daily_pnl),ratio=pnlDecimal(raw?.return_ratio,true),base=raw?.daily_base_date===null?null:historyDay(raw?.daily_base_date);
      if(!raw||day===null||observed===null||generated!==null&&observed>generated||priceLocalDay(observed)!==raw.date||typeof raw.segment_id!=='string'||!raw.segment_id||raw.segment_id.length>200||raw.record_type!=='daily_last_observation'||!['intraday_estimate','last_recorded'].includes(raw.phase)||typeof raw.break_before!=='boolean'||typeof raw.cash_only!=='boolean'||typeof raw.ledger_revision!=='string'||!/^\d{1,100}$/.test(raw.ledger_revision)||!capital||capital.direction!=='gain'||!equity||equity.direction==='loss'||!cumulative||!ratio||raw.daily_pnl!==null&&!daily||raw.daily_base_date!==null&&(base===null||base>=day)||daily&&base===null||!daily&&base!==null)return none('invalid_history');
      if(raw.cash_only?(raw.valuation_at!==null||raw.latest_quote_at!==null):(valuation===null||latest===null||valuation>latest||latest>observed))return none('invalid_history');
      const identity=JSON.stringify([raw.segment_id,raw.date]),segmentStart=previous!==null&&previous.segment_id!==raw.segment_id;
      if(identities.has(identity)||previous&&(day<previous.x||segmentStart&&(!raw.break_before||daily!==null))||capitalBySegment.has(raw.segment_id)&&capitalBySegment.get(raw.segment_id)!==raw.initial_capital)return none('invalid_history');
      const coordinates={daily_pnl:daily===null?null:Number(raw.daily_pnl),cumulative_pnl:Number(raw.cumulative_pnl)};
      if(Object.values(coordinates).some(value=>value!==null&&!Number.isFinite(value)))return none('invalid_history');
      const point={...raw,key:identity,x:day,coordinates,segmentStart};points.push(point);identities.add(identity);capitalBySegment.set(raw.segment_id,raw.initial_capital);previous=point;
    }
    return {...h,points};
  }
  function pnlHistoryGraph(target,{field,title,points,readoutId,inspect,intraday=false}){
    const chart=node('section','rtp-original-chart rtp-history-chart rtp-pnl-history-chart');chart.dataset.pnlHistoryChart=field;chart.append(node('h4','',title));target.append(chart);
    const valid=points.map(point=>point.coordinates[field]).filter(value=>value!==null);
    if(!valid.length){chart.append(node('p','rtp-wait',fixed('尚无连续可比记录；每日盈亏保持空白，不按零处理。')));return ()=>{};}
    chart.dataset.tradingAxis=intraday?'compressed':'calendar';
    const min=Math.min(0,...valid),max=Math.max(0,...valid),pad=(max-min||1)*.1,low=min-pad,high=max+pad;
    if(!Number.isFinite(high-low)||high<=low){chart.append(node('p','rtp-wait',fixed('历史记录待核对，暂不绘制盈亏曲线。')));return ()=>{};}
    const coordinate=value=>intraday?intradayTradingTime(value):value,start=coordinate(points[0].x),end=coordinate(points.at(-1).x),span=end-start,x=value=>span?12+(coordinate(value)-start)/span*616:320,y=value=>212-(value-low)/(high-low)*204,format=value=>new Intl.NumberFormat(window.ETF_I18n?.language==='en'?'en-US':'zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(value)<.005?0:value);
    const figure=node('div','rtp-history-figure'),axis=node('div','rtp-history-y-axis'),plot=node('div','rtp-history-plot'),svg=historySvg('svg',{viewBox:'0 0 640 220',preserveAspectRatio:'none',role:'img','aria-label':String(title),'aria-describedby':readoutId});svg.classList.add('rtp-history-svg');plot.append(svg);figure.append(axis,plot);chart.append(figure);
    for(let index=0;index<5;index++){const value=low+(high-low)*index/4,position=y(value),label=node('span','',format(value));label.style.top=position/220*100+'%';axis.append(label);svg.append(historySvg('line',{x1:12,x2:628,y1:position,y2:position,class:'rtp-history-grid','aria-hidden':'true'}));}
    svg.append(historySvg('line',{x1:12,x2:628,y1:y(0),y2:y(0),class:'rtp-history-zero','aria-hidden':'true'}));
    const color='rtp-history-series-'+(field==='cumulative_pnl'?1:0),lines=historySvg('g',{'aria-hidden':'true'});let segment=[];
    const finish=()=>{if(segment.length===1){const point=segment[0];lines.append(historySvg('circle',{cx:x(point.x),cy:y(point.coordinates[field]),r:3.5,class:color+' rtp-history-isolated'}));}else if(segment.length>1)lines.append(historySvg('path',{d:segment.map((point,index)=>(index?'L':'M')+x(point.x).toFixed(3)+','+y(point.coordinates[field]).toFixed(3)).join(' '),class:color+' rtp-history-line','data-series':field}));segment=[];};
    for(const point of points){if(point.coordinates[field]===null){finish();continue;}if(point.break_before)finish();segment.push(point);}finish();
    for(const point of points)if(point.phase==='intraday_estimate'&&point.coordinates[field]!==null&&(!intraday||point===points.at(-1)))lines.append(historySvg('circle',{cx:x(point.x),cy:y(point.coordinates[field]),r:5,class:color+' rtp-pnl-history-provisional'}));svg.append(lines);
    const cursor=historySvg('line',{x1:0,x2:0,y1:8,y2:212,class:'rtp-history-cursor','aria-hidden':'true'}),marker=historySvg('circle',{cx:0,cy:0,r:3.5,class:color+' rtp-history-marker','aria-hidden':'true'});svg.append(cursor,marker);
    const xAxis=node('div','rtp-history-x-axis'+(span?'':' rtp-pnl-single-axis')),axisLabel=at=>intraday?(span===0&&points[0].x!==points.at(-1).x?'11:30 / 13:00':at===start?pnlIntradayClock(points[0].x):at===end?pnlIntradayClock(points.at(-1).x):intradayTradingAxisLabel(at)):new Date(at*86400000).toISOString().slice(0,10);for(const at of span?[start,(start+end)/2,end]:[start])xAxis.append(node('span','',axisLabel(at)));figure.append(xAxis);
    const pointer=event=>{const rect=svg.getBoundingClientRect();if(!rect.width||!rect.height)return;const at=start+Math.max(0,Math.min(1,((event.clientX-rect.left)/rect.width*640-12)/616))*span,pointerY=(event.clientY-rect.top)/rect.height*220;let index=0,nearestX=Infinity,nearestY=Infinity;for(let n=0;n<points.length;n++){const distanceX=Math.abs(coordinate(points[n].x)-at),value=points[n].coordinates[field],distanceY=value===null?Infinity:Math.abs(y(value)-pointerY);if(distanceX<nearestX-1e-9||Math.abs(distanceX-nearestX)<=1e-9&&distanceY<=nearestY){index=n;nearestX=distanceX;nearestY=distanceY;}}inspect(index);};svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
    return point=>{chart.dataset.selectedDate=point.date;chart.dataset.selectedTime=point.observed_at;chart.dataset.selectedSegment=point.segment_id;cursor.setAttribute('x1',x(point.x));cursor.setAttribute('x2',x(point.x));marker.style.display=point.coordinates[field]===null?'none':'';if(point.coordinates[field]!==null){marker.setAttribute('cx',x(point.x));marker.setAttribute('cy',y(point.coordinates[field]));}};
  }
  function pnlIntradaySeries(a){
    const h=a?.pnl_history?.intraday,none=(reason,date=null)=>({status:'unavailable',reason,date,points:[]}),generated=priceTimestamp(state.data?.generated_at),today=generated===null?null:priceLocalDay(generated);
    if(!h)return none('history_unavailable',today);
    if(a.pnl_history.contract_version!=='d0-account-pnl-history-v1'||a.pnl_history.source!=='recorded_account_valuation'||h.contract_version!=='d0-account-pnl-intraday-v1'||h.basis!=='minute_last_observation'||historyDay(h.date)===null||today===null||h.date!==today||h.sampling_seconds!==60||h.retention_days!==5||h.retention_limit!==1500||typeof h.truncated!=='boolean'||!Array.isArray(h.available_dates)||h.available_dates.some(day=>historyDay(day)===null||day>h.date)||h.current_segment!==null&&(typeof h.current_segment!=='string'||!h.current_segment||h.current_segment.length>200))return none('invalid_history',today);
    if(h.status!=='available')return {...h,...none(h.status==='unavailable'&&['no_recorded_valuations_today','history_unavailable','invalid_history'].includes(h.reason)?h.reason:'invalid_history',today)};
    if(!Array.isArray(h.points)||h.points.length>1500)return none('invalid_history',today);
    const points=[],identities=new Set(),segments=new Map();let previous=null;
    for(const raw of h.points){
      const observed=priceTimestamp(raw?.observed_at),valuation=raw?.valuation_at===null?null:priceTimestamp(raw?.valuation_at),latest=raw?.latest_quote_at===null?null:priceTimestamp(raw?.latest_quote_at),first=priceTimestamp(raw?.first_observed_at),capital=pnlDecimal(raw?.initial_capital),equity=pnlDecimal(raw?.equity),cumulative=pnlDecimal(raw?.cumulative_pnl),daily=raw?.daily_pnl===null?null:pnlDecimal(raw?.daily_pnl),change=pnlDecimal(raw?.since_first_observation_pnl),firstPnl=pnlDecimal(raw?.first_observation_cumulative_pnl),ratio=pnlDecimal(raw?.return_ratio,true),base=raw?.daily_base_date===null?null:historyDay(raw?.daily_base_date);
      if(!raw||raw.date!==today||observed===null||observed>generated||priceLocalDay(observed)!==today||intradayTradingTime(observed)===null||first===null||first>observed||priceLocalDay(first)!==today||typeof raw.segment_id!=='string'||!raw.segment_id||raw.segment_id.length>200||raw.record_type!=='minute_last_observation'||!['intraday_estimate','last_recorded'].includes(raw.phase)||typeof raw.break_before!=='boolean'||typeof raw.cash_only!=='boolean'||typeof raw.ledger_revision!=='string'||!/^\d{1,100}$/.test(raw.ledger_revision)||!capital||capital.direction!=='gain'||!equity||equity.direction==='loss'||!cumulative||!ratio||!change||!firstPnl||raw.daily_pnl!==null&&!daily||raw.daily_base_date!==null&&(base===null||base>=historyDay(today))||daily&&base===null||!daily&&base!==null)return none('invalid_history',today);
      if(raw.cash_only?(raw.valuation_at!==null||raw.latest_quote_at!==null):(valuation===null||latest===null||valuation>latest||latest>observed))return none('invalid_history',today);
      const identity=JSON.stringify([raw.segment_id,Math.floor(observed/60000)]),segmentStart=previous!==null&&previous.segment_id!==raw.segment_id,segmentBasis=JSON.stringify([raw.initial_capital,raw.first_observed_at,raw.first_observation_cumulative_pnl,raw.daily_base_date]);
      const localMinute=at=>Math.floor((at+8*3600000)%86400000/60000),session=at=>localMinute(at)<690?'am':'pm';
      if(identities.has(identity)||previous&&(observed<previous.x||((segmentStart||observed-previous.x>120000||session(observed)!==session(previous.x))&&!raw.break_before))||segments.has(raw.segment_id)&&segments.get(raw.segment_id)!==segmentBasis)return none('invalid_history',today);
      const coordinates={daily_pnl:daily===null?null:Number(raw.daily_pnl),cumulative_pnl:Number(raw.cumulative_pnl),since_first_observation_pnl:Number(raw.since_first_observation_pnl)};if(Object.values(coordinates).some(value=>value!==null&&!Number.isFinite(value)))return none('invalid_history',today);
      const point={...raw,key:identity,x:observed,coordinates,segmentStart};points.push(point);identities.add(identity);segments.set(raw.segment_id,segmentBasis);previous=point;
    }
    return {...h,points};
  }
  function pnlIntradayClock(at){return new Intl.DateTimeFormat(window.ETF_I18n?.language==='en'?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(at));}
  function renderAccountPnlHistory(target,a){
    const modeFocus=target.contains(document.activeElement)?document.activeElement?.dataset?.pnlHistoryMode:null,key=a?JSON.stringify([a.id,a.created_at||'']):null;let view=key?pnlHistoryViews.get(key):null;
    if(a&&!view){view={mode:'intraday',range:60,point:null,follow:true};pnlHistoryViews.set(key,view);}if(view&&!view.mode)view.mode='intraday';
    if(view?.mode==='daily')renderDailyPnlHistory(target,a);else renderIntradayPnlHistory(target,a,view);
    if(!a)return;target.dataset.mode=view.mode;
    const modes=node('div','rtp-pnl-history-modes'),buttons=[];modes.setAttribute('role','group');modes.setAttribute('aria-label',String(fixed('盈亏走势周期')));
    for(const [mode,label] of [['intraday',fixed('盘中')],['daily',fixed('每日')]]){const control=button(label,()=>{view.mode=mode;renderAccountPnlHistory(target,account());},'rtp-history-range');control.dataset.pnlHistoryMode=mode;control.dataset.pnlHistoryControl='mode-'+mode;control.setAttribute('aria-pressed',String(view.mode===mode));control.setAttribute('aria-controls','rtp-pnl-history');modes.append(control);buttons.push(control);}target.insertBefore(modes,target.children[1]||null);if(modeFocus)buttons.find(control=>control.dataset.pnlHistoryMode===modeFocus)?.focus({preventScroll:true});
  }
  function renderIntradayPnlHistory(target,a,view){
    const focused=target.contains(document.activeElement)?document.activeElement:null,focusControl=focused?.dataset?.pnlHistoryControl,focusTableSummary=focused?.tagName==='SUMMARY';fields.pnlHistoryReadState=pnlHistoryReadState();target.replaceChildren();target.hidden=!a;if(!a)return;
    const history=pnlIntradaySeries(a),points=history.points,current=holdingSnapshotCurrent()&&!state.pnlFromCommand;if(!view.intraday||view.intraday.date!==history.date)view.intraday={date:history.date,point:null,follow:true};const selection=view.intraday;
    target.dataset.historyStatus=history.status;target.dataset.historyReason=history.reason||'';target.dataset.snapshotCurrent=String(current);target.dataset.account=String(a.id);target.dataset.intradayDate=history.date||'';
    const title=node('h3','',fixed('账户盈亏走势'));title.id='rtp-pnl-history-title';target.setAttribute('aria-labelledby',title.id);target.append(title,node('p','small muted',fixed('盘中按分钟保存本账户的有效估值，随账户更新；每日保留每天最后一条有效记录。费用已包含。')));
    if(!current)target.append(node('p','rtp-wait rtp-pnl-history-cache',fixed('历史快照待刷新：当前展示上次读取的记录，不能据此认定最新账户状态。')));
    target.append(node('p','rtp-pnl-intraday-period',fixed('{date} 北京时间 · 已记录 {count} 个盘中点',{date:history.date||'—',count:points.length})));
    const restoreFocus=()=>{if(focusTableSummary)target.querySelector('details>summary')?.focus({preventScroll:true});if(focusControl)for(const control of target.querySelectorAll('[data-pnl-history-control]'))if(control.dataset.pnlHistoryControl===focusControl)control.focus({preventScroll:true});};
    if(history.status!=='available'||!points.length){target.append(node('p','rtp-wait rtp-pnl-history-empty',history.reason==='invalid_history'?fixed('历史记录待核对，暂不绘制盈亏曲线。'):history.reason==='history_unavailable'?fixed('暂时无法读取账户盈亏历史，请等待正常刷新。'):fixed('今天尚无有效盘中记录；开市后随账户有效估值积累。历史日线可切换到“每日”查看。')));if(priceTimestamp(history.latest_recorded_at)!==null)target.append(node('p','small muted',fixed('此前最近盘中记录：{time}，未作为今天的数据展示。',{time:compactTime(history.latest_recorded_at)})));restoreFocus();return;}
    const latest=points.at(-1),fallback=points.some(point=>point.daily_pnl===null),field=fallback?'since_first_observation_pnl':'daily_pnl',fieldLabel=fallback?fixed('从今日首条记录起变化'):fixed('今日盈亏'),fieldTitle=fallback?fixed('从今日首条记录起变化（元）'):fixed('今日盈亏（元）'),amount=value=>value===null?'—':pnlDecimal(value).text+String(fixed(' 元')),phase=point=>point.phase==='intraday_estimate'?fixed('盘中暂估'):fixed('已记录估值（非收盘）');target.dataset.intradayPnlBasis=fallback?'first_observation':'previous_trading_day';
    const summary=node('dl','rtp-pnl-intraday-summary');line(summary,fieldLabel,amount(latest[field]));line(summary,fixed('累计盈亏'),amount(latest.cumulative_pnl));target.append(summary,node('p','small muted rtp-pnl-history-asof',fixed('最近账户记录：{time}',{time:compactTime(latest.observed_at)})));
    target.append(node('p','small muted rtp-pnl-intraday-basis',fallback?fixed('缺少可比的上一交易日估值；左图显示各本金段从今日首条真实记录起的变化，不等于完整今日盈亏。'):fixed('今日盈亏以同一本金基准的上一交易日最后有效记录为基准；累计盈亏相对该段初始本金。')));
    if(fallback)target.append(node('p','small muted',fixed('当前本金段首条记录：{time}，当时累计盈亏 {value}。',{time:compactTime(latest.first_observed_at),value:amount(latest.first_observation_cumulative_pnl)})));
    if(history.truncated)target.append(node('p','small muted',fixed('盘中历史已达到保存上限；未展示的早期记录不会补造。')));
    const readoutId='rtp-pnl-history-readout',charts=node('div','rtp-pnl-history-charts'),input=node('input','rtp-history-date-control'),label=node('label','rtp-history-date-label',fixed('查看记录（方向键切换，Home / End 到首尾）')),readout=node('dl','rtp-history-readout rtp-pnl-history-readout'),announcer=node('p','rtp-history-announcement'),paint=[];
    input.id='rtp-pnl-history-date';input.type='range';input.min='0';input.max=String(points.length-1);input.step='1';input.disabled=points.length===1;input.dataset.pnlHistoryControl='date';label.htmlFor=input.id;readout.id=readoutId;input.setAttribute('aria-describedby',readoutId);announcer.setAttribute('aria-live','polite');announcer.setAttribute('aria-atomic','true');
    const inspect=(index,announce=false,user=false)=>{const bounded=Math.max(0,Math.min(points.length-1,index)),point=points[bounded];selection.point=point.key;if(user)selection.follow=bounded===points.length-1;input.value=String(bounded);target.dataset.selectedDate=point.date;target.dataset.selectedTime=point.observed_at;target.dataset.selectedSegment=point.segment_id;for(const update of paint)update(point);readout.replaceChildren();line(readout,fixed('观察记录时间'),compactTime(point.observed_at));line(readout,fixed('记录状态'),phase(point));line(readout,fixed('今日盈亏'),amount(point.daily_pnl));line(readout,fixed('累计盈亏'),amount(point.cumulative_pnl));line(readout,fixed('每日比较基准日'),point.daily_base_date||fixed('尚无连续可比记录'));if(fallback){line(readout,fixed('从今日首条记录起变化'),amount(point.since_first_observation_pnl));line(readout,fixed('该段今日首条记录'),compactTime(point.first_observed_at));line(readout,fixed('首条记录累计盈亏'),amount(point.first_observation_cumulative_pnl));}line(readout,fixed('该段本金基准'),pnlDecimal(point.initial_capital).unsigned+fixed(' 元'));line(readout,fixed('记录时账户估值'),pnlDecimal(point.equity).unsigned+fixed(' 元'));line(readout,fixed('估值引用源时间'),point.cash_only?fixed('现金账户，无持仓报价'):compactTime(point.valuation_at));if(point.segmentStart)line(readout,fixed('本金基准变化'),fixed('与上一段分开记录；不跨本金基准计算每日盈亏。'));if(point.break_before)line(readout,fixed('连续性'),fixed('本条之前不连接曲线，未补算缺失记录。'));const value=compactTime(point.observed_at)+' · '+String(fieldLabel)+': '+amount(point[field])+' · '+String(fixed('累计盈亏'))+': '+amount(point.cumulative_pnl);input.setAttribute('aria-valuetext',value);if(announce)announcer.textContent=value;};
    target.append(charts);paint.push(pnlHistoryGraph(charts,{field,title:fieldTitle,points,readoutId,intraday:true,inspect:index=>inspect(index,false,true)}),pnlHistoryGraph(charts,{field:'cumulative_pnl',title:fixed('累计盈亏（元）'),points,readoutId,intraday:true,inspect:index=>inspect(index,false,true)}));target.append(node('p','small muted rtp-pnl-history-legend',fixed('横轴按北京时间压缩午休，读数保留真实记录时间；采集间断与本金变化仍断线。横线为零，最新空心点为盘中暂估。')),label,input,readout,announcer);
    input.addEventListener('input',()=>inspect(Number(input.value),true,true));input.addEventListener('keydown',event=>{let index=Number(input.value);if(event.key==='Home')index=0;else if(event.key==='End')index=points.length-1;else if(event.key==='ArrowLeft'||event.key==='ArrowDown')index--;else if(event.key==='ArrowRight'||event.key==='ArrowUp')index++;else return;event.preventDefault();inspect(index,true,true);});
    const found=points.findIndex(point=>point.key===selection.point);inspect(selection.follow||selection.point===null?points.length-1:found>=0?found:0);if(points.length===1)target.append(node('p','small muted',fixed('目前只有一个盘中点；后续有效估值会逐分钟形成折线，同一分钟更新已有点。')));
    const detail=disclosure(fixed('查看账户盈亏数据表'),'rtp-pnl-intraday-table'),wrap=node('div','rtp-history-table-wrap'),table=node('table','rtp-history-table'),head=node('thead'),header=node('tr'),body=node('tbody');
    for(const label of [fixed('观察记录时间'),fixed('今日盈亏（元）'),fixed('累计盈亏（元）'),fixed('从今日首条记录起变化（元）'),fixed('每日比较基准日'),fixed('该段今日首条记录'),fixed('该段本金基准'),fixed('记录时账户估值'),fixed('连续性')]){const th=node('th','',label);th.scope='col';header.append(th);}head.append(header);
    for(const point of points){const row=node('tr'),time=node('th','',compactTime(point.observed_at));time.scope='row';row.append(time,node('td','',amount(point.daily_pnl)),node('td','',amount(point.cumulative_pnl)),node('td','',amount(point.since_first_observation_pnl)),node('td','',point.daily_base_date||'—'),node('td','',compactTime(point.first_observed_at)),node('td','',pnlDecimal(point.initial_capital).unsigned),node('td','',pnlDecimal(point.equity).unsigned),node('td','',point.break_before?fixed('分段首点'):fixed('—')));body.append(row);}table.append(node('caption','',fixed('账户盘中有效估值记录；每分钟保留最新有效观测，盈亏已包含模拟费用。')),head,body);wrap.append(table);wrap.tabIndex=0;wrap.dataset.pnlHistoryControl='table';wrap.setAttribute('aria-label',String(fixed('账户盈亏数据表')));detail.open=Boolean(selection.tableOpen);detail.addEventListener('toggle',()=>{if(detail.isConnected)selection.tableOpen=detail.open;});wrap.addEventListener('scroll',()=>{if(wrap.isConnected){selection.tableTop=wrap.scrollTop;selection.tableLeft=wrap.scrollLeft;}});detail.append(wrap);target.append(detail);wrap.scrollTop=selection.tableTop||0;wrap.scrollLeft=selection.tableLeft||0;restoreFocus();
  }

  function renderDailyPnlHistory(target,a){
    const focused=target.contains(document.activeElement)?document.activeElement:null,focusControl=focused?.dataset?.pnlHistoryControl,focusTableSummary=focused?.tagName==='SUMMARY';fields.pnlHistoryReadState=pnlHistoryReadState();target.replaceChildren();target.hidden=!a;if(!a)return;
    const key=JSON.stringify([a.id,a.created_at||'']),history=pnlHistorySeries(a);let view=pnlHistoryViews.get(key);if(!view){view={range:60,point:null,follow:true};pnlHistoryViews.set(key,view);}
    const points=history.points.slice(-view.range),current=holdingSnapshotCurrent()&&!state.pnlFromCommand;target.dataset.historyStatus=history.status;target.dataset.historyReason=history.reason||'';target.dataset.snapshotCurrent=String(current);target.dataset.account=String(a.id);
    const title=node('h3','',fixed('账户盈亏走势'));title.id='rtp-pnl-history-title';target.setAttribute('aria-labelledby',title.id);target.append(title,node('p','small muted',fixed('每日盈亏与累计盈亏来自本账户每天最后一次有效估值记录，不是收盘结算。费用已包含，不重复扣除。')));
    if(!current)target.append(node('p','rtp-wait rtp-pnl-history-cache',fixed('历史快照待刷新：当前展示上次读取的记录，不能据此认定最新账户状态。')));
    const controls=node('div','rtp-history-controls'),ranges=node('div','rtp-history-ranges');ranges.setAttribute('role','group');ranges.setAttribute('aria-label',String(fixed('盈亏记录显示范围')));
    for(const range of [30,60,120]){const control=button(fixed('最近{count}条记录',{count:range}),()=>{view.range=range;renderAccountPnlHistory(target,account());},'rtp-history-range');control.dataset.pnlHistoryRange=String(range);control.dataset.pnlHistoryControl='range-'+range;control.setAttribute('aria-pressed',String(view.range===range));ranges.append(control);}controls.append(ranges,node('span','small muted',fixed('当前显示 {count} 条记录',{count:points.length})));target.append(controls);
    const restoreFocus=()=>{if(focusTableSummary)target.querySelector('details>summary')?.focus({preventScroll:true});if(focusControl)for(const control of target.querySelectorAll('[data-pnl-history-control]'))if(control.dataset.pnlHistoryControl===focusControl)control.focus({preventScroll:true});};
    if(history.status!=='available'||!points.length){target.append(node('p','rtp-wait rtp-pnl-history-empty',history.reason==='invalid_history'?fixed('历史记录待核对，暂不绘制盈亏曲线。'):history.reason==='history_unavailable'?fixed('暂时无法读取账户盈亏历史，请等待正常刷新。'):fixed('尚无账户盈亏历史；等待后续有效估值积累，不补造过去记录。')));restoreFocus();return;}
    if(priceTimestamp(history.last_recorded_at)!==null)target.append(node('p','small muted rtp-pnl-history-asof',fixed('最近账户记录：{time}',{time:compactTime(history.last_recorded_at)})));
    if(history.truncated)target.append(node('p','small muted',fixed('历史最多保留366条记录；当前曲线只显示所选范围，不代表全部账户历史。')));
    target.append(node('p','small muted',fixed('每日盈亏按同一本金基准内连续交易日的已记录估值比较；缺日或本金变更时留空。横轴按实际日期排列，同日本金变更可有多条记录。')));
    const readoutId='rtp-pnl-history-readout',charts=node('div','rtp-pnl-history-charts'),input=node('input','rtp-history-date-control'),label=node('label','rtp-history-date-label',fixed('查看记录（方向键切换，Home / End 到首尾）')),readout=node('dl','rtp-history-readout rtp-pnl-history-readout'),announcer=node('p','rtp-history-announcement'),paint=[];
    input.id='rtp-pnl-history-date';input.type='range';input.min='0';input.max=String(points.length-1);input.step='1';input.disabled=points.length===1;input.dataset.pnlHistoryControl='date';label.htmlFor=input.id;readout.id=readoutId;input.setAttribute('aria-describedby',readoutId);announcer.setAttribute('aria-live','polite');announcer.setAttribute('aria-atomic','true');
    const amount=value=>value===null?'—':pnlDecimal(value).text+String(fixed(' 元')),phase=point=>point.phase==='intraday_estimate'?fixed('当日暂估'):fixed('当日最后记录（非收盘）');
    const inspect=(index,announce=false,user=false)=>{const bounded=Math.max(0,Math.min(points.length-1,index)),point=points[bounded];view.point=point.key;if(user)view.follow=bounded===points.length-1;input.value=String(bounded);target.dataset.selectedDate=point.date;target.dataset.selectedSegment=point.segment_id;for(const update of paint)update(point);readout.replaceChildren();line(readout,fixed('记录日期'),point.date);line(readout,fixed('记录状态'),phase(point));line(readout,fixed('每日盈亏'),amount(point.daily_pnl));line(readout,fixed('累计盈亏'),amount(point.cumulative_pnl));line(readout,fixed('每日比较基准日'),point.daily_base_date||fixed('尚无连续可比记录'));line(readout,fixed('该段本金基准'),pnlDecimal(point.initial_capital).unsigned+fixed(' 元'));line(readout,fixed('记录时账户估值'),pnlDecimal(point.equity).unsigned+fixed(' 元'));line(readout,fixed('观察记录时间'),compactTime(point.observed_at));line(readout,fixed('估值引用源时间'),point.cash_only?fixed('现金账户，无持仓报价'):compactTime(point.valuation_at));if(!point.cash_only&&point.latest_quote_at!==point.valuation_at)line(readout,fixed('最新持仓报价源时间'),compactTime(point.latest_quote_at));if(point.segmentStart)line(readout,fixed('本金基准变化'),fixed('与上一段分开记录；不跨本金基准计算每日盈亏。'));if(point.break_before)line(readout,fixed('连续性'),fixed('本条之前不连接曲线，未补算缺失记录。'));const summary=point.date+' · '+String(phase(point))+' · '+String(fixed('每日盈亏'))+': '+amount(point.daily_pnl)+' · '+String(fixed('累计盈亏'))+': '+amount(point.cumulative_pnl);input.setAttribute('aria-valuetext',summary);if(announce)announcer.textContent=summary;};
    target.append(charts);paint.push(pnlHistoryGraph(charts,{field:'daily_pnl',title:fixed('每日盈亏（元）'),points,readoutId,inspect:index=>inspect(index,false,true)}),pnlHistoryGraph(charts,{field:'cumulative_pnl',title:fixed('累计盈亏（元）'),points,readoutId,inspect:index=>inspect(index,false,true)}));target.append(node('p','small muted rtp-pnl-history-legend',fixed('横线为零；空心点为当日暂估。所有点都是已记录观测，不表示收盘结算；缺口与本金段之间不连线。')),label,input,readout,announcer);
    input.addEventListener('input',()=>inspect(Number(input.value),true,true));input.addEventListener('keydown',event=>{let index=Number(input.value);if(event.key==='Home')index=0;else if(event.key==='End')index=points.length-1;else if(event.key==='ArrowLeft'||event.key==='ArrowDown')index--;else if(event.key==='ArrowRight'||event.key==='ArrowUp')index++;else return;event.preventDefault();inspect(index,true,true);});
    const found=points.findIndex(point=>point.key===view.point);inspect(view.follow||view.point===null?points.length-1:found>=0?found:0);
    if(points.length===1)target.append(node('p','small muted',fixed('目前只有一条账户记录，只显示观测点；需要后续记录才能形成曲线。')));
    const detail=disclosure(fixed('查看账户盈亏数据表'),'rtp-pnl-history-table'),wrap=node('div','rtp-history-table-wrap'),table=node('table','rtp-history-table'),head=node('thead'),header=node('tr'),body=node('tbody');
    for(const label of [fixed('记录日期'),fixed('记录状态'),fixed('每日盈亏（元）'),fixed('累计盈亏（元）'),fixed('每日比较基准日'),fixed('该段本金基准'),fixed('记录时账户估值'),fixed('观察记录时间'),fixed('估值引用源时间'),fixed('连续性')]){const th=node('th','',label);th.scope='col';header.append(th);}head.append(header);
    for(const point of points){const row=node('tr'),date=node('th','',point.date);date.scope='row';row.append(date,node('td','',phase(point)),node('td','',point.daily_pnl===null?'—':pnlDecimal(point.daily_pnl).text),node('td','',pnlDecimal(point.cumulative_pnl).text),node('td','',point.daily_base_date||'—'),node('td','',pnlDecimal(point.initial_capital).unsigned),node('td','',pnlDecimal(point.equity).unsigned),node('td','',compactTime(point.observed_at)),node('td','',point.cash_only?fixed('现金账户，无持仓报价'):compactTime(point.valuation_at)),node('td','',point.break_before?fixed('分段首点'):fixed('—')));body.append(row);}table.append(node('caption','',fixed('账户每日有效估值记录；每日及累计盈亏均已包含模拟费用。')),head,body);wrap.append(table);wrap.tabIndex=0;wrap.dataset.pnlHistoryControl='table';wrap.setAttribute('aria-label',String(fixed('账户盈亏数据表')));detail.open=Boolean(view.tableOpen);detail.addEventListener('toggle',()=>{if(detail.isConnected)view.tableOpen=detail.open;});wrap.addEventListener('scroll',()=>{if(wrap.isConnected){view.tableTop=wrap.scrollTop;view.tableLeft=wrap.scrollLeft;}});detail.append(wrap);target.append(detail);wrap.scrollTop=view.tableTop||0;wrap.scrollLeft=view.tableLeft||0;restoreFocus();
  }
  function renderHoldingLogic(a){
    const target=fields.holdingLogic,focused=target.contains(document.activeElement)?document.activeElement:null,historyFocus=focused?.dataset?.historyControl?{key:focused.dataset.historyKey,signal:focused.dataset.historySignal,control:focused.dataset.historyControl}:null,focusSymbol=focused?.dataset?.symbol,focusDetail=focused?.tagName==='SUMMARY'?focused.parentElement.dataset.detailKey:null,openDetails=new Set([...target.querySelectorAll('details[open][data-detail-key]')].map(d=>d.dataset.detailKey));fields.holdingReadState=holdingReadState();target.replaceChildren();target.hidden=!a;if(!a)return;
    target.append(node('h3','',fixed('为什么这样持仓')));
    const signal=a.signal,rationale=signal?.rationale;
    if(!holdingSnapshotCurrent())target.append(node('p','rtp-wait',state.loading||state.busy?fixed('正在核对当前状态；以下为最近一次快照，实际占比暂不展示。'):fixed('当前状态待核对，以下持仓逻辑来自上次成功快照。')));
    if(!signal){empty(target,fixed('尚无当前策略已确认信号，暂不能说明目标配置。'));return;}
    target.append(node('p','small muted',fixed('依据确认日 {day} 的已保存信号 · 执行日 {execution_day}',{day:str(signal.confirmed_day),execution_day:str(signal.execution_day)})));
    if(signal.valid!==true||a.execution_state==='needs_review')target.append(node('p','rtp-wait',fixed('此信号或来源需要核对；以下是已保存的配置依据，不表示当前可以执行。')));
    const symbols=['sz159915','sh512800','sh518880','sh511010'],fallbackNames=['创业板ETF','银行ETF','黄金ETF','5年国债ETF'],holdings=verifiedHoldings(a);
    const assets=symbols.map((symbol,index)=>{
      const saved=rationale?.contract_version==='d0-holding-logic-v1'&&Array.isArray(rationale.assets)?rationale.assets.filter(row=>row?.symbol===symbol):[];
      const row=saved.length===1?saved[0]:{},weight=rationaleNumber(signal.weights?.[symbol]),holding=holdings?.find(p=>p.symbol===symbol),rule=unique(state.data?.rules).find(r=>r.symbol===symbol);
      return {...row,symbol,weight:weight!==null&&weight>=0&&weight<=1?weight:null,holding,holdingsKnown:holdings!==null,shortName:fixed(fallbackNames[index]),name:rule?.name||holding?.name||fixed(fallbackNames[index])};
    });
    const total=assets.reduce((sum,row)=>sum+(row.weight??0),0),complete=assets.every(row=>row.weight!==null)&&total<=1.00000001;
    const qualified=assets.filter(row=>row.eligible===true),known=assets.every(row=>typeof row.eligible==='boolean');
    let overview=fixed('按已确认的资产资格和强弱／波动评分分配目标。');
    if(complete&&known&&qualified.length===1&&qualified[0].weight===1)overview=fixed('只有{asset}通过配置资格，因此本次目标为该资产 100%。',{asset:qualified[0].name});
    else if(complete&&known&&!qualified.length&&total===0)overview=weeklyStrategy()?fixed('两只股票与周线国债均未通过配置资格，本次目标为现金100%。'):fixed('四只 ETF 均未通过配置资格，本次目标为现金 100%。');
    else if(!complete||!known||rationale?.contract_version!=='d0-holding-logic-v1')overview=fixed('已保存信号的持仓逻辑资料不完整；仅展示可核对的目标和实际持仓。');
    target.append(node('p','rtp-logic-overview',overview));
    renderDecisionPath(target,a,assets);
    const details=disclosure(fixed('查看四只 ETF 的完整持仓依据'),'rtp-logic-assets'),cards=node('div','rtp-logic-grid');details.append(cards);target.append(details);
    for(const row of assets){
      const c=card(cards,str(row.name)+' · '+row.symbol.slice(2)),list=node('dl'),quantity=row.holdingsKnown?row.holding?.quantity??0:null;
      c.setAttribute('data-rationale-symbol',row.symbol);
      line(list,fixed('模型目标'),rationalePercent(row.weight));line(list,fixed('实际持有'),quantity===null?fixed('待核对'):decimal(quantity)+fixed(' 份'));
      const actual=actualHoldingRatio(a,row);
      line(list,fixed('实际资产占比'),actual===null?fixed('估值待核对'):rationalePercent(actual));c.append(list);
      c.append(node('span','pill '+(row.eligible===true?'rtp-logic-qualified':'neutral'),row.eligible===true?fixed('通过配置资格'):row.eligible===false?fixed('未通过配置资格'):fixed('资格依据未记录')));
      const note=typeof row.note==='string'&&row.note.trim()?row.note:fixed('未保存此资产的具体判断依据，不能仅凭目标比例推断原因。');
      c.append(node('p','rtp-logic-note',note));
      if(weeklyStrategy()&&['sh511010','sh518880'].includes(row.symbol)){renderOriginalGate(c,row,signal);continue;}
      const detail=disclosure(fixed('查看评分指标'),'rtp-logic-'+row.symbol),metrics=node('dl');
      for(const [key,label] of [['momentum20',fixed('20日动量')],['momentum60',fixed('60日动量')],['volatility20',fixed('20日年化波动')]])line(metrics,label,rationalePercent(row[key]));
      line(metrics,fixed('有效评分'),savedScore(row));
      line(metrics,fixed('20日动量权重'),'60%');line(metrics,fixed('60日动量权重'),'40%');
      const gateOnly=fixed('无评分权重；用于准入判断'),unused=fixed('无评分权重；本资产未使用');
      line(metrics,fixed('SKDJ评分权重'),['sz159915','sh512800'].includes(row.symbol)?gateOnly:unused);
      line(metrics,fixed('TRIX评分权重'),row.symbol==='sz159915'?gateOnly:unused);
      line(metrics,fixed('波动率作用'),fixed('风险调整分母，最低按8%计算'));
      detail.append(metrics,node('p','small muted',fixed('60%／40%是动量项的公式权重，不是目标仓位或当期得分贡献占比。未通过配置资格时，有效评分为0。')),node('p','small muted',fixed('评分用于合格资产间的相对分配，不是收益预测或成功概率。')));c.append(detail);
    }
    const cash=node('p','rtp-logic-cash');cash.append(node('strong','',fixed('现金：')),node('span','',fixed('模型目标 {target} · 实际余额 {amount} 元',{target:complete?rationalePercent(Math.max(0,1-total)):fixed('待核对'),amount:decimal(a.cash,2)})));target.append(cash);
    target.append(node('p','small muted',fixed('目标比例与实际持仓分开列示。100份整手、费用与限价资金预留、待执行委托及价格变化，都可能留下现金或造成比例偏差。')));
    const rules=disclosure(fixed('如何分配，什么时候调仓'),'rtp-logic-rules');
    for(const text of [weeklyStrategy()?'股票优先：银行沿用原日线SKDJ，创业板沿用原周线SKDJ/TRIX资格；合格股票按原评分归一。两股均不合格时，国债通过已完成周的60周均线与20周动量资格才配置，否则现金。黄金不参与。':'先筛选，再评分：各资产须通过原策略多头资格、指标完整性和同一确认日数据检查；合格资产按20日、60日动量相对20日波动的评分分配。只有一只合格时目标为100%，全部不合格时保留现金。','交易日16:10后核对当日确认日线，新信号最早从下一交易日参与模拟。每次盘中报价更新用于估值与模拟估计，不直接生成新的择时信号。','执行计划建立后按计划份额处理，先卖后买；账户运行状态、资料有效性、交易时段、可卖份额及资金都会影响执行。暂停后重新启动会建立新计划。','委托提交后仍需两份同源、新鲜且成交量额递增的报价，并满足限价与规则，才可记入整单模拟估计成交。'])rules.append(node('p','small',fixed(text)));
    target.append(rules);
    for(const detail of target.querySelectorAll('details[data-detail-key]')){if(openDetails.has(detail.dataset.detailKey))detail.open=true;if(detail.dataset.detailKey===focusDetail)detail.querySelector('summary')?.focus({preventScroll:true});}
    if(focusSymbol)for(const b of target.querySelectorAll('.rtp-decision-select'))if(b.dataset.symbol===focusSymbol)b.focus({preventScroll:true});
    if(historyFocus)for(const control of target.querySelectorAll('[data-history-control]'))if(control.dataset.historyKey===historyFocus.key&&control.dataset.historySignal===historyFocus.signal&&control.dataset.historyControl===historyFocus.control)control.focus({preventScroll:true});
  }
  function compactCards(target,rows,keep,kind){
    [...target.children].forEach((card,index)=>{if(!card.classList.contains('rtp-card'))return;const data=rows[index],details=disclosure(fixed('查看完整依据与字段'),kind+'-'+str(data?.id,data?.code||index)),list=card.querySelector('dl');if(!list)return;const technical=node('dl');[...list.children].forEach((row,i)=>{if(!keep.includes(i))technical.append(row);});details.append(technical);for(const times of card.querySelectorAll('.rtp-times'))details.append(times);if(kind==='fill')card.append(node('p','small muted',fixed('估计记账时间：')+compactTime(data.matched_at)));card.append(details);});
  }
  function unique(rows){const seen=new Set();return (Array.isArray(rows)?rows:[]).filter(row=>{if(!row||typeof row!=='object')return false;if(row.id===undefined||row.id===null)return true;const id=String(row.id);if(seen.has(id))return false;seen.add(id);return true;});}
  function card(target,title){const c=node('article','rtp-card');c.append(node('h4','',title));target.append(c);return c;}
  function empty(target,text){target.append(node('p','muted rtp-empty',text));}
  function alertIdentifier(value){return typeof value==='string'&&value.trim()!==''&&value.length<=4096;}
  function alertMoment(value){if(typeof value!=='string'||!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value))return null;const at=new Date(value).valueOf();return Number.isFinite(at)?at:null;}
  function alertDecimal(value){if(typeof value==='number'&&!Number.isSafeInteger(value))return null;const raw=String(value);if(!/^\d+(?:\.\d+)?$/.test(raw)||!/[1-9]/.test(raw))return null;return raw.replace(/^0+(?=\d)/,'').replace(/(\.\d*?)0+$/,'$1').replace(/\.$/,'');}
  function alertPrice(value){return typeof value==='string'&&/^\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?$/.test(value)&&/[1-9]/.test(value.split(/[Ee]/)[0])?value:null;}
  function alertReferenceLabel(reference){return reference==='current_reference'?fixed('当前模拟委托参考'):reference==='historical'?fixed('历史提醒'):fixed('资料待核对');}
  const alertReasonDescriptions={
    current_reference:['current_reference','此模拟委托可供当前核对，仍以本次快照为准。'],
    command_snapshot:['historical','这是操作返回时保存的模拟委托记录，仅供历史核对。'],
    account_stopped:['historical','账户已停止，此模拟委托仅保留历史参考。'],
    order_cancelled:['historical','模拟委托已撤销，仅保留历史记录。'],
    order_expired:['historical','模拟委托已到期，仅保留历史记录。'],
    order_filled:['historical','已记录模拟估计成交，仅供历史核对，不代表真实成交。'],
    order_not_pending:['needs_review','委托状态需要核对，暂不能作为当前模拟委托参考。'],
    expired_by_time:['historical','已超过模拟委托的到期时刻，仅保留历史参考。'],
    missing_association:['needs_review','缺少订单、信号或计划的关联资料，请核对。'],
    ambiguous_submission:['needs_review','提交事件存在冲突，触发时间和事件归属需要核对。'],
    missing_timestamp:['needs_review','缺少必要时间记录，请核对。'],
    invalid_timestamp:['needs_review','时间记录或时区无效，请核对。'],
    invalid_order_fields:['needs_review','模拟委托资料不完整或无效，请核对。'],
    future_timestamp:['needs_review','记录中存在晚于当前快照的时间，请核对。'],
    inconsistent_timestamps:['needs_review','信号、计划或委托的时间顺序不一致，请核对。'],
    old_signal:['historical','此委托关联历史信号，仅保留历史参考。'],
    old_plan:['historical','此委托关联历史执行计划，仅保留历史参考。'],
    generation_mismatch:['historical','此委托属于较早的模拟启动批次，仅保留历史参考。'],
    source_not_ready:['needs_review','数据来源尚未就绪，模拟委托资料需要核对。'],
    observer_not_running:['needs_review','观察服务尚未运行，模拟委托资料需要核对。'],
    before_eligible:['historical','尚未到模拟委托的可执行时刻，此记录仅供核对。'],
    outside_session:['historical','当前不在连续竞价参考时段，此记录仅供历史核对。'],
    unknown_state:['needs_review','模拟账户或信号状态不明确，请刷新核对。']
  };
  function alertExplanation(item,reference,temporary=false){
    if(temporary)return fixed('最近快照资料待核对，请刷新确认。');
    const reason=Object.hasOwn(alertReasonDescriptions,item.reasonCode)?alertReasonDescriptions[item.reasonCode]:null;
    if(reference===item.sourceReference&&reason?.[0]===reference)return fixed(reason[1]);
    if(reference==='historical'&&item.reference!==item.sourceReference)return fixed('此模拟委托已结束或账户已停止，仅保留历史参考。');
    return fixed('提醒状态资料待核对，请刷新确认。');
  }
  function alertReference(a,item,order){
    if(!['current_reference','historical'].includes(item.reference_status))return 'needs_review';
    if(['filled','cancelled','canceled','expired','rejected'].includes(order?.status)||['filled','cancelled','canceled','expired','rejected'].includes(item.order_status)||['paused','stopped'].includes(a.status))return 'historical';
    if(item.reference_status==='historical')return 'historical';
    if(item.reference_status!=='current_reference'||item.reason_code!=='current_reference'||!alertIdentifier(item.event_id)||item.source_event_ids.length!==1||item.source_event_ids[0]!==item.event_id)return 'needs_review';
    const at=alertMoment(item.triggered_at),generated=alertMoment(state.data?.generated_at),submitted=alertMoment(order?.submitted_at),eligible=alertMoment(order?.eligible_at),expires=alertMoment(order?.expires_at);
    if(a.status!=='running'||!order||!pending.has(order.status)||!pending.has(item.order_status)||order.status!==item.order_status||a.signal?.valid!==true||a.signal?.id!==item.signal_id||a.plan_id!==item.plan_id||!['signal_id','plan_id','intent_id','symbol'].every(key=>alertIdentifier(item[key])&&item[key]===order[key])||order.side!==item.side||!['buy','sell'].includes(item.side)||typeof item.quantity!=='number'||!Number.isSafeInteger(item.quantity)||alertDecimal(item.quantity)===null||alertDecimal(item.quantity)!==alertDecimal(order.quantity)||alertPrice(item.limit_price)===null||(item.limit_price!==order.limit_price&&(alertDecimal(item.limit_price)===null||alertDecimal(item.limit_price)!==alertDecimal(order.limit_price)))||[at,generated,submitted,eligible,expires].some(value=>value===null)||!(submitted<=at&&at<=generated&&eligible<=generated&&generated<expires)||state.data?.service?.status!=='ready'||state.data?.service?.observer_status!=='running')return 'needs_review';
    return 'current_reference';
  }
  function renderTradeAlerts(a,{target=fields.tradeAlerts,preview=false}={}){
    target.replaceChildren();const references=[];if(preview)fields.emailPreviewReferences=references;else{fields.alertReferences=references;fields.alertEmail.hidden=!a;}
    if(!a){empty(target,fixed('尚无独立模拟账户，创建账户后可查看站内提醒。'));return;}
    const projection=state.data?.trade_alerts;
    if(projection===undefined){empty(target,fixed('此账户尚未接入提醒'));return;}
    if(!projection||projection.contract_version!=='paper-trade-alerts-v1'||projection.channel!=='in_app'||projection.email_status!=='not_integrated'||projection.account_id!==a.id||!Array.isArray(projection.items)){empty(target,fixed('提醒资料待核对，请刷新账户状态。'));return;}
    if(!projection.items.length){empty(target,fixed('暂无站内交易提醒；已提交并可追溯的模拟委托会显示在这里。'));return;}
    const keys=['id','kind','account_id','event_id','source_event_ids','order_id','signal_id','plan_id','intent_id','triggered_at','signal_at','submitted_at','eligible_at','expires_at','side','symbol','code','name','quantity','limit_price','order_status','reference_status','reason_code','is_trade_instruction'],records=new Map(),conflicts=new Set(),orders=new Map();let invalid=false;
    for(const item of projection.items){
      if(!item||typeof item!=='object'||item.kind!=='submitted_order'||item.account_id!==a.id||item.is_trade_instruction!==false||!['id','order_id'].every(key=>alertIdentifier(item[key]))||!(item.event_id===null||alertIdentifier(item.event_id))||!Array.isArray(item.source_event_ids)||!item.source_event_ids.length||!item.source_event_ids.every(alertIdentifier)||(item.event_id!==null&&!item.source_event_ids.includes(item.event_id))){invalid=true;continue;}
      const signature=JSON.stringify(keys.map(key=>item[key]??null)),old=records.get(item.id);
      if(old){if(old.signature!==signature)conflicts.add(item.id);continue;}
      if(orders.has(item.order_id)&&orders.get(item.order_id)!==item.id){conflicts.add(orders.get(item.order_id));conflicts.add(item.id);}else orders.set(item.order_id,item.id);
      records.set(item.id,{item,signature});
    }
    for(const [id,{item}] of records){
      if(conflicts.has(id)){invalid=true;continue;}
      const matching=(Array.isArray(a.orders)?a.orders:[]).filter(order=>order?.id===item.order_id&&(!Object.hasOwn(order,'account_id')||order.account_id===a.id)),order=matching.length===1?matching[0]:null,reference=alertReference(a,item,order),security=str(item.name)+' · '+str(item.code)+' · '+str(item.symbol),c=card(target,security),badge=node('span','pill rtp-alert-state',alertReferenceLabel(reference));
      c.setAttribute('data-alert-id',id);c.append(badge);
      const list=node('dl');
      const status=order?.status??item.order_status;
      for(const [label,value] of [[fixed('模拟委托方向'),item.side==='buy'?fixed('买入'):item.side==='sell'?fixed('卖出'):fixed('方向待核对')],[fixed('模拟委托数量'),decimal(item.quantity)],[fixed('模拟委托限价'),alertPrice(item.limit_price)??fixed('待核对')],[fixed('提醒触发时间 · triggered_at'),time(item.triggered_at)],[fixed('当前快照订单状态'),Object.hasOwn(statusLabels,status)?statusLabels[status]:fixed('状态待核对')+' · '+str(status)],[fixed('提醒 ID'),id],[fixed('事件 ID'),str(item.event_id)],[fixed('来源事件 ID'),item.source_event_ids.join(' / ')],[fixed('订单 ID'),item.order_id],[fixed('计划 / 意图 / 信号 ID'),str(item.plan_id)+' / '+str(item.intent_id)+' / '+str(item.signal_id)]])line(list,label,value);
      const explanation=node('div','rtp-line'),description=node('dd','rtp-alert-description');explanation.append(node('dt','',fixed('提醒状态说明')),description);list.append(explanation);references.push({badge,description,reference,sourceReference:item.reference_status,reasonCode:item.reason_code});
      c.append(list,node('p','small muted',fixed('此记录仅用于核对模拟委托，不表示真实成交或券商执行。')));
    }
    if(invalid||!records.size)target.append(node('p','rtp-wait',fixed('部分提醒资料不完整或存在冲突，未展示；请刷新核对。')));
  }
  function buildEmailDraft(root){
    const section=node('section','panel rtp-section rtp-email-draft');section.id='rtp-email-draft';section.append(node('h3','',fixed('D0 邮件提醒配置草稿')),node('p','rtp-wait',fixed('配置草稿 / 拟订阅，通道待配置，发送关闭')),node('p','small muted',fixed('这里只保存收件地址与 D0 账户的配置草稿，邮件推送尚未接入此账户。')));
    fields.emailForm=node('form','rtp-form');fields.emailForm.id='rtp-email-form';fields.emailForm.autocomplete='off';
    const recipientLabel=node('label','',fixed('收件地址（草稿）'));recipientLabel.htmlFor='rtp-email-recipient';fields.emailRecipient=node('input');fields.emailRecipient.id='rtp-email-recipient';fields.emailRecipient.type='text';fields.emailRecipient.autocomplete='off';fields.emailRecipient.inputMode='email';fields.emailRecipient.maxLength=254;
    const accountLabel=node('label','',fixed('拟订阅的 D0 账户'));accountLabel.htmlFor='rtp-email-account';fields.emailAccount=node('select');fields.emailAccount.id='rtp-email-account';
    fields.emailSave=node('button','button secondary',fixed('保存配置草稿'));fields.emailSave.type='submit';fields.emailReload=button(fixed('重新读取配置草稿'),()=>loadEmailDraft());fields.emailPreview=button(fixed('查看内容预览'),()=>{if(!emailCanPreview())return;emailDraft.preview=true;controls();});
    const actions=node('div','button-row rtp-actions');actions.append(fields.emailSave,fields.emailReload,fields.emailPreview);fields.emailForm.append(recipientLabel,fields.emailRecipient,accountLabel,fields.emailAccount,actions);
    fields.emailForm.addEventListener('submit',event=>{event.preventDefault();return saveEmailDraft();});
    for(const [field,event] of [[fields.emailRecipient,'input'],[fields.emailAccount,'change']])field.addEventListener(event,()=>{emailDraft.dirty=true;controls();});
    fields.emailStatus=node('p','small rtp-wait');fields.emailStatus.setAttribute('role','status');fields.emailError=node('p','inline-error');fields.emailError.setAttribute('role','alert');fields.emailError.hidden=true;fields.emailSaved=node('div','small');fields.emailPreviewPanel=node('section','rtp-email-preview');fields.emailPreviewPanel.hidden=true;fields.emailPreviewMeta=node('div');fields.emailPreviewCards=node('div','rtp-cards');fields.emailPreviewPanel.append(node('h4','',fixed('邮件内容预览')),node('p','rtp-wait',fixed('预览，未发送')),fields.emailPreviewMeta,fields.emailPreviewCards);section.append(fields.emailForm,fields.emailStatus,fields.emailError,fields.emailSaved,fields.emailPreviewPanel);root.append(section);
  }
  function emailDraftControls(){
    if(!fields.emailForm)return;const blocked=!state.active||weeklyStrategy()||emailDraft.loading||emailDraft.saving;
    fields.emailForm.closest('.rtp-email-draft').hidden=weeklyStrategy();
    fields.emailRecipient.disabled=blocked||!emailDraft.ready;fields.emailAccount.disabled=blocked||!emailDraft.ready;fields.emailSave.disabled=blocked||!emailDraft.ready||!emailSelectedAccount();fields.emailReload.disabled=blocked;fields.emailPreview.disabled=!emailCanPreview();
    fields.emailStatus.textContent=emailDraft.saving?fixed('正在保存配置草稿；发送仍关闭。'):emailDraft.loading?fixed('正在读取配置草稿；发送仍关闭。'):!emailDraft.ready?fixed('配置草稿尚未核对，请重新读取；发送仍关闭。'):emailDraft.data?.draft_status==='empty'?fixed('尚未保存邮件配置草稿；发送关闭。'):emailDraft.data?.binding?.status==='unavailable'?fixed('草稿绑定目前不可用，请核对；发送仍关闭。'):emailDraft.dirty?fixed('有未保存的邮件配置输入；下方已保存草稿仍为原值。'):fixed('配置草稿已核对；通道待配置，发送关闭。');
    renderEmailSaved();renderEmailPreview();
  }
  function renderEmailDraft(){
    const selected=fields.emailAccount.value;fields.emailAccount.replaceChildren();const option=node('option','',fixed('请选择拟订阅的 D0 账户'));option.value='';fields.emailAccount.append(option);
    for(const a of state.data?.accounts||[]){const unavailable=emailDraft.data?.draft?.account_id===a.id&&emailDraft.data?.binding?.status==='unavailable',item=node('option','',str(a.name)+' · '+str(a.id)+(unavailable?' · '+fixed('原绑定不可用，需核对'):''));item.value=String(a.id);item.disabled=unavailable;fields.emailAccount.append(item);}
    const bound=emailDraft.data?.draft?.account_id,retained=selected||bound;
    if(retained&&!(state.data?.accounts||[]).some(a=>a.id===retained)){const old=node('option','',str(retained)+' · '+fixed('原绑定目前不可用，保留原值'));old.value=retained;old.disabled=true;fields.emailAccount.append(old);}
    fields.emailAccount.value=selected;
    if(!emailDraft.dirty){fields.emailRecipient.value=emailDraft.data?.draft?.recipient||'';fields.emailAccount.value=bound||'';}
  }
  function emailSelectedAccount(){
    if(!emailDraft.ready||!state.ready||!['ready','degraded'].includes(state.data?.service?.status))return null;
    const id=fields.emailAccount.value,a=(state.data?.accounts||[]).find(a=>a.id===id&&a.strategy==='D0'&&['running','paused','stopped'].includes(a.status)&&alertMoment(a.created_at)!==null);if(!a)return null;
    const data=emailDraft.data,binding=data?.binding;
    if(!data?.draft&&(data?.draft_status!=='empty'||binding?.status!=='not_configured'||binding?.reason_code!=='no_draft'))return null;
    if(binding?.reason_code==='service_unavailable'||data?.draft_status==='invalid')return null;
    if(data?.draft?.account_id===id&&binding?.status==='unavailable')return null;
    if(data?.draft?.account_id===id&&a.created_at!==binding.account_created_at)return null;
    return a;
  }
  function emailCanPreview(){return state.active&&emailDraft.ready&&!emailDraft.loading&&!emailDraft.saving&&!!emailSelectedAccount()&&fields.emailAccount.value===state.id&&(!emailDraft.data?.draft||emailDraft.data.binding.status==='available'&&emailDraft.data.draft.account_id===fields.emailAccount.value);}
  const emailBindingReasons={no_draft:'尚未保存邮件配置草稿。',account_available:'草稿接口已核对原绑定账户身份。',service_unavailable:'账户服务暂不可用，原绑定未替换。',account_missing:'原绑定账户目前不存在，原值已保留。',account_invalid:'账户身份资料待核对，原绑定未替换。',account_changed:'账户身份已变化，原绑定不可用且未自动替换。',invalid_saved_draft:'保存的草稿资料无效，未回显异常内容。'};
  function renderEmailSaved(){
    const target=fields.emailSaved;target.replaceChildren();const data=emailDraft.data;
    if(!data){empty(target,fixed('尚未读取已保存的配置草稿。'));return;}
    target.append(node('strong','',!emailDraft.ready?fixed('上次读取的草稿（待核对）'):data.draft_status==='empty'?fixed('尚未保存配置草稿'):data.draft_status==='invalid'?fixed('保存的草稿待核对'):fixed('已保存的配置草稿')));
    if(data.draft){const list=node('dl');line(list,fixed('已保存收件地址'),data.draft.recipient);line(list,fixed('已保存账户 ID'),data.draft.account_id);line(list,fixed('绑定账户创建时间'),time(data.binding.account_created_at));target.append(list);}
    const a=(state.data?.accounts||[]).find(a=>a.id===data.draft?.account_id);
    const localMismatch=!!data.draft&&(!state.ready||!a||a.created_at!==data.binding.account_created_at);
    target.append(node('p','rtp-wait',emailDraft.ready?fixed(emailBindingReasons[data.draft_status==='empty'&&!data.draft?'no_draft':data.binding.reason_code]||'草稿状态待核对。'):fixed('最近读取的草稿状态待核对，请重新读取确认。')));
    if(localMismatch)target.append(node('p','rtp-wait',fixed('原绑定与当前账户快照不一致或尚未核对，未自动替换账户。')));
  }
  function renderEmailPreview(){
    fields.emailPreviewPanel.hidden=!emailDraft.preview;fields.emailPreviewMeta.replaceChildren();fields.emailPreviewCards.replaceChildren();fields.emailPreviewReferences=[];
    if(!emailDraft.preview)return;
    if(!emailCanPreview()){empty(fields.emailPreviewCards,fixed('草稿绑定或账户快照尚未核对，暂不能预览；不会改用其他账户。'));return;}
    const list=node('dl');line(list,emailDraft.dirty?fixed('拟收件地址（未保存输入）'):fixed('草稿收件地址'),str(fields.emailRecipient.value));line(list,fixed('预览账户 ID'),fields.emailAccount.value);line(list,fixed('数据时点'),time(state.data?.generated_at));fields.emailPreviewMeta.append(list,node('p','small muted',!emailDraft.data?.draft?fixed('未绑定配置草稿，预览未发送'):emailDraft.dirty?fixed('本预览采用未保存输入；不会保存配置或发送邮件。'):fixed('本预览仅核对已有模拟委托记录；不会保存配置或发送邮件。')));
    renderTradeAlerts(emailSelectedAccount(),{target:fields.emailPreviewCards,preview:true});
  }
  function emailRecipientValid(value){
    if(typeof value!=='string'||!value.length||value.length>254||/[^\x21-\x7e]/.test(value))return false;
    const parts=value.split('@');if(parts.length!==2)return false;const [local,domain]=parts;
    if(!local.length||local.length>64||!local.split('.').every(part=>/^[A-Za-z0-9!#$%&'*+\/=?^_`{|}~-]+$/.test(part)))return false;
    const labels=domain.split('.');return labels.length>=2&&labels.every(label=>label.length<=63&&/^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/.test(label))&&/^[A-Za-z]{2,63}$/.test(labels[labels.length-1]);
  }
  function acceptEmailDraft(data,{saved=false}={}){
    const binding=data?.binding,draft=data?.draft;
    const knownBinding=!!binding&&['not_configured','available','unavailable'].includes(binding.status)&&Object.hasOwn(emailBindingReasons,binding.reason_code)&&(binding.account_id===null||typeof binding.account_id==='string'&&/^[-A-Za-z0-9_]{1,100}$/.test(binding.account_id));
    const available=binding?.status==='available'&&binding?.reason_code==='account_available';
    const unavailable=binding?.status==='unavailable'&&['service_unavailable','account_missing','account_invalid','account_changed'].includes(binding?.reason_code);
    const validSaved=data?.draft_status==='saved'&&!!draft&&emailRecipientValid(draft.recipient)&&typeof draft.account_id==='string'&&/^[-A-Za-z0-9_]{1,100}$/.test(draft.account_id)&&binding?.account_id===draft.account_id&&typeof binding.account_created_at==='string'&&binding.account_created_at.length<=80&&alertMoment(binding.account_created_at)!==null&&(available||unavailable);
    const validEmpty=data?.draft_status==='empty'&&draft===null&&binding?.account_id===null&&binding?.account_created_at===null&&(binding?.status==='not_configured'&&binding?.reason_code==='no_draft'||unavailable&&binding?.reason_code!=='account_changed');
    const validInvalid=data?.draft_status==='invalid'&&draft===null&&binding?.account_id===null&&binding?.account_created_at===null&&binding?.status==='unavailable'&&binding?.reason_code==='invalid_saved_draft';
    const validDraft=validSaved||validEmpty||validInvalid;
    if(data?.contract_version!=='paper-email-draft-v1'||data.preparation_status!=='draft_only'||data.sending_enabled!==false||data.email_status!=='not_integrated'||!knownBinding||!validDraft)throw uiError(fixed('邮件配置草稿响应不完整，请重新读取核对。'));
    emailDraft.data=data;emailDraft.ready=true;
    if(saved)emailDraft.dirty=false;renderEmailDraft();
  }
  function emailDraftError(error){
    const errors={EMAIL_DRAFT_INVALID:'草稿格式未通过校验，请核对收件地址与账户后重新读取配置。',EMAIL_DRAFT_ACCOUNT_UNAVAILABLE:'账户绑定已不可用，请重新读取配置；原绑定不会自动替换。',EMAIL_DRAFT_UNAVAILABLE:'草稿服务暂不可用，请稍后重新读取配置。',EMAIL_DRAFT_SAVE_FAILED:'配置草稿保存未确认，请重新读取核对后再保存。'};
    const text=error?.[FIXED]||fixed(Object.hasOwn(errors,error?.code)?errors[error.code]:'配置草稿请求未确认，请重新读取核对；发送仍关闭。');fields.emailError.hidden=false;displayText(fields.emailError,text,true);
  }
  async function loadEmailDraft(){
    if(!state.active||weeklyStrategy()||emailDraft.loading||emailDraft.saving)return;
    if(!state.transport?.loadEmailDraft){emailDraft.ready=false;emailDraftError(uiError(fixed('邮件配置草稿接口尚未接入。')));controls();return;}
    const generation=emailDraft.generation,request=++emailDraft.request;emailDraft.loading=true;emailDraft.ready=false;fields.emailError.hidden=true;controls();
    try{const data=await state.transport.loadEmailDraft(state.strategy);if(!state.active||generation!==emailDraft.generation||request!==emailDraft.request)return;acceptEmailDraft(data);}
    catch(error){if(state.active&&generation===emailDraft.generation&&request===emailDraft.request){emailDraft.ready=false;emailDraftError(error);}}
    finally{if(generation===emailDraft.generation&&request===emailDraft.request){emailDraft.loading=false;controls();}}
  }
  async function saveEmailDraft(){
    if(!state.active||weeklyStrategy()||!emailDraft.ready||emailDraft.loading||emailDraft.saving||!state.transport?.saveEmailDraft)return;
    if(!emailRecipientValid(fields.emailRecipient.value)){emailDraftError(uiError(fixed('请输入 1 至 254 个 ASCII 字符的有效收件地址；不能含空白、换行或控制字符。')));return;}
    const a=emailSelectedAccount();if(!a){emailDraftError(uiError(fixed('请选择当前可核对的 D0 账户；原绑定不会自动替换。')));return;}
    const generation=emailDraft.generation,request=++emailDraft.request,body={recipient:fields.emailRecipient.value,account_id:a.id};emailDraft.saving=true;emailDraft.ready=false;fields.emailError.hidden=true;controls();
    try{const data=await state.transport.saveEmailDraft(body,state.strategy);if(!state.active||generation!==emailDraft.generation||request!==emailDraft.request)return;if(data?.draft_status!=='saved'||data?.draft?.recipient!==body.recipient||data?.draft?.account_id!==body.account_id)throw uiError(fixed('邮件配置草稿响应不完整，请重新读取核对。'));acceptEmailDraft(data,{saved:true});}
    catch(error){if(state.active&&generation===emailDraft.generation&&request===emailDraft.request){emailDraft.ready=false;emailDraftError(error);}}
    finally{emailDraft.saving=false;if(generation===emailDraft.generation&&request===emailDraft.request)controls();else if(state.active){controls();loadEmailDraft();}}
  }
  function suspendEmailDraft({clear=false}={}){
    emailDraft.generation++;emailDraft.request++;emailDraft.loading=false;emailDraft.ready=false;
    if(clear){emailDraft.data=null;emailDraft.dirty=false;emailDraft.preview=false;fields.emailRecipient.value='';fields.emailAccount.value='';fields.emailError.hidden=true;fields.emailError.textContent='';fixedNodes.delete(fields.emailError);}
  }
  function render(){
    displayText(fields.heading,weeklyStrategy()?fixed('D0I-BOND-WW · 周线择债'):fixed('D0 前瞻模拟账户'),true);
    displayText(fields.strategyDescription,weeklyStrategy()?fixed('股票优先；两股均不合格时，国债通过60周均线与20周动量资格才持有，否则现金。黄金不参与。'):fixed('D0四资产：按资格与评分分配；创业板已确认周收盘低于50周均线且资料就绪时，银行新金叉入场上限放宽至K≤50，其余时段为K≤40。'),true);
    displayText(fields.settings.querySelector('summary'),weeklyStrategy()?fixed('账户设置'):fixed('账户设置与邮件草稿（发送未启用）'),true);
    if(fields.recoveryNote)fields.recoveryNote.textContent=fixed(collectionRecoveryNote);
    const openDetails=new Set([...state.root.querySelectorAll('details[open][data-detail-key]')].map(d=>d.dataset.detailKey));
    const a=account();for(const key of ['positions','fills','orders'])fields[key].parentElement.hidden=!a;if(fields.shownAccount!==state.id){fields.settings.open=!a;openDetails.delete('rtp-settings');fields.shownAccount=state.id;}fields.selector.replaceChildren();const placeholder=node('option','',state.data?.accounts?.length?fixed('选择账户'):fixed('暂无前瞻模拟账户'));placeholder.value='';placeholder.disabled=!!state.data?.accounts?.length;fields.selector.append(placeholder);
    renderTradeAlerts(a);
    renderSignalSummary(a);
    renderHoldingLogic(a);
    renderAccountPnlHistory(fields.pnlHistory,a);
    renderEmailDraft();
    for(const item of state.data?.accounts||[]){const o=node('option','',str(item.name,strategyName())+' · '+str(item.id));o.value=String(item.id);fields.selector.append(o);}fields.selector.value=state.id;
    if(!state.dirty){fields.name.value=state.creating?strategyName():str(a?.name,strategyName());fields.cash.value=state.creating?'100000.00':str(a?.initial_cash,'100000.00');}
    fields.summary.replaceChildren();fields.accountPnl=null;const summary=fields.summary;
    const service=state.data?.service||{},collectionCode=Object.hasOwn(collectionReasons,service.reason_code)?service.reason_code:null,collectionWait=service.status!=='ready'&&collectionCode?fixed(collectionReasons[collectionCode]):null,sourceWait=service.status!=='ready'?waitingReason(service.waiting_reason,service.reason_code,''):null;
    if(!a){summary.append(node('p','muted',state.ready?fixed('尚未建立当前策略的独立账户。请在下方设置中确认本金；创建后默认停止。'):fixed('账户状态尚未核对，读取成功后显示建户或运行操作。')));}
    else{
      summary.append(node('span','pill rtp-status',({running:fixed('运行中 · 模拟估计'),paused:fixed('已暂停'),stopped:fixed('已停止')})[a.status]||fixed('状态待核对')));
      summary.append(node('p','rtp-wait',fixed('执行状态：')+({stopped:fixed('停止',{},'已停止'),waiting:fixed('等待'),active:fixed('估计执行中'),needs_review:fixed('待核对')}[a.execution_state]||fixed('待核对'))+(a.waiting_reason||a.reason_code?' · '+accountWaitingReason(a):'')));
      summary.append(fields.operations);
      fields.accountPnl=node('section','rtp-account-pnl');summary.append(fields.accountPnl);renderAccountPnl(fields.accountPnl,a);
      const values=node('dl','rtp-assets');for(const [key,label] of [['equity',fixed('总资产估值')],['available_cash',fixed('可用现金')],['holdings_value',fixed('持仓估值')],['frozen_cash',fixed('冻结现金')]])line(values,label,decimal(a[key],2)+(a[key]===undefined||a[key]===null?'':fixed(' 元')));summary.append(values);
      summary.append(node('p','small muted',a.valuation_status==='fresh'?fixed('估值按后端返回的报价记录。'):fixed('估值过期 / 待核对')));
      const orders=unique(a.orders).filter(o=>pending.has(o.status)),fills=unique(a.fills).sort((x,y)=>Date.parse(y.matched_at)-Date.parse(x.matched_at)||0),last=fills[0];
      summary.append(node('p','rtp-pending',fixed('待执行委托：')+orders.length+(orders.length?' · '+orders.map(o=>str(o.name,o.code)+' '+(o.side==='buy'?fixed('买入'):fixed('卖出'))+' '+decimal(o.remaining_quantity)+fixed(' 份')).join('；'):'')));
      summary.append(node('p','rtp-latest-fill',fixed('最新模拟估计成交：')+(last?str(last.name,last.code)+' · '+(last.side==='buy'?fixed('买入'):fixed('卖出'))+' '+decimal(last.quantity)+fixed(' 份')+' × '+decimal(last.price)+fixed(' 元')+' · '+compactTime(last.matched_at):fixed('暂无；不会补记启动前的成交。'))));
      const links=node('div','button-row');links.append(button(fixed('查看持仓'),()=>fields.positions.parentElement.scrollIntoView({block:'start'})),button(fixed('查看成交'),()=>fields.fills.parentElement.scrollIntoView({block:'start'})),button(fixed('查看委托'),()=>fields.orders.parentElement.scrollIntoView({block:'start'})));summary.append(links);
    }
    if(sourceWait)summary.append(node('p','rtp-wait',sourceWait));const lastError=waitingReason(service.last_error,undefined,'');if(service.last_error&&service.last_error!==service.waiting_reason&&(service.status!=='ready'||!(service.reason_code==='ready'&&isCollectionText(service.last_error))))summary.append(node('p','rtp-wait',lastError));
    const metadata=disclosure(fixed('资产与运行详细依据'),'rtp-summary-evidence');
    if(a){const values=node('dl');line(values,fixed('已保存本金'),decimal(a.initial_cash,2)+fixed(' 元'));line(values,fixed('现金总额'),decimal(a.cash,2)+fixed(' 元'));metadata.append(values);dates(metadata,a,['started_at']);}
    metadata.append(node('p','small muted',fixed('状态生成：')+time(state.data?.generated_at)+' · revision '+str(state.data?.revision)),node('p','small muted',fixed('观察服务：')+({ready:fixed('可用'),degraded:fixed('部分异常'),unavailable:fixed('暂不可用')}[service.status]||fixed('待核对'))+' / '+({stopped:fixed('停止',{},'已停止'),running:fixed('观察中'),waiting:fixed('等待'),error:fixed('异常')}[service.observer_status]||fixed('待核对'))+fixed(' · 最近观察 ')+time(service.last_observed_at)));summary.append(metadata);
    const sourceTimes=unique(state.data?.market_quotes).map(q=>q.quote_at).filter(Boolean).sort(),acceptedTimes=unique(state.data?.quotes).map(q=>q.quote_at).filter(Boolean).sort();
    const quoteSummary=node('p','small rtp-quote-summary');quoteSummary.append(node('span','',fixed('最新市场报价：')+compactTime(sourceTimes[0])),node('span','',fixed('账户已接纳报价：')+compactTime(acceptedTimes[0])));summary.append(quoteSummary);
    if(service.status!=='ready'&&sourceTimes.length)summary.append(node('p','small rtp-wait',unique(state.data?.market_quotes).every(q=>q.fresh)?fixed('市场报价继续采集；账户因上述原因等待，旧报价不代表当前价格。'):fixed('部分或全部市场报价已过期或时间待核对，请等待采集恢复。')));
    fields.marketQuotes.replaceChildren(node('h3','',fixed('最新市场报价（仅展示）')),node('p','small muted',fixed('盘中报价目标每30秒采集，确认行情每5分钟核对；当前页面每30秒读取状态。最新报价不代表账户已接纳，也不代表可成交。')));
    const marketRows=node('div','rtp-cards');fields.marketQuotes.append(marketRows);
    for(const q of unique(state.data?.market_quotes)){const c=card(marketRows,str(q.name,q.code)+' · '+str(q.code));c.append(node('p','',decimal(q.price)),node('p','small muted',fixed('行情源时间：')+compactTime(q.quote_at)),node('p','small muted',fixed('采集接收时间：')+compactTime(q.received_at)),node('p',q.fresh?'small muted':'small rtp-wait',q.fresh?fixed('近期采集 · 仅供查看'):fixed('报价过期或时间待核对 · 仅供查看')));}
    if(!marketRows.children.length)empty(marketRows,fixed('尚无可展示的市场报价，等待采集；账户旧报价见详细依据。'));
    if(service.history_continuity?.retained)fields.marketQuotes.append(node('p','small rtp-wait',fixed('已保留原信号历史并接续后续完整日线，旧成交不重算；未来信号可能与全量修订行情不同。')));
    for(const key of ['signal','positions','quotes','orders','fills','events','rules'])fields[key].replaceChildren();fields.cancelButtons=[];
    if(a?.signal){const s=a.signal,c=card(fields.signal,fixed('当前策略收盘确认信号')),list=node('dl');for(const [label,value] of [[fixed('信号 / 计划 ID'),str(s.id)+' / '+str(a.plan_id)],[fixed('确认日 / 执行日'),str(s.confirmed_day)+' / '+str(s.execution_day)],[fixed('信号版本 / 来源'),str(s.version)+' / '+str(s.source)],[fixed('信号确认 · signal_at'),time(s.signal_at)],[fixed('首次可知 · known_at'),time(s.known_at)],[fixed('数据截止 · data_cutoff'),time(s.data_cutoff)],[fixed('信号状态'),s.valid===true?fixed('有效收盘目标'):str(s.waiting_reason,fixed('待核对'))]])line(list,label,value);for(const [symbol,weight] of Object.entries(s.weights||{}))line(list,symbol+fixed(' 目标权重'),decimal(weight));c.append(list);}else empty(fields.signal,fixed('尚无已确认信号，等待收盘目标。'));
    for(const p of unique(a?.holdings)){const c=card(fields.positions,str(p.name,p.code)+' · '+str(p.code)),list=node('dl');for(const [key,label,min] of [['quantity',fixed('持有份额'),0],['frozen_quantity',fixed('冻结份额'),0],['sellable_quantity',fixed('可卖份额'),0],['locked_quantity',fixed('锁定份额'),0],['price',fixed('估值报价'),0],['value',fixed('持仓估值'),2]])line(list,label,decimal(p[key],min));c.append(list);c.append(node('p','small rtp-wait',p.valuation_status==='fresh'?fixed('按记录报价估值'):fixed('估值过期 / 待核对')));line(list,fixed('来源 / 报价ID'),str(p.source)+' / '+str(p.quote_id));dates(c,p,['quote_at','received_at']);}
    if(!fields.positions.children.length)empty(fields.positions,a?fixed('暂无持仓'):fixed('等待账户数据'));
    for(const q of unique(state.data?.quotes)){const c=card(fields.quotes,str(q.name,q.code)+' · '+str(q.code)),list=node('dl');line(list,fixed('报价 / 报价ID'),decimal(q.price)+' / '+str(q.id));line(list,fixed('来源 / 时间精度'),str(q.source)+' / '+str(q.time_precision));line(list,fixed('行情源年龄'),age(q.quote_at));line(list,fixed('接收后年龄'),age(q.received_at));line(list,fixed('快照源年龄（后端）'),str(q.age_seconds,fixed('未提供'))+fixed(' 秒'));line(list,fixed('源延迟（后端）'),str(q.source_delay_seconds,fixed('未提供'))+fixed(' 秒'));line(list,fixed('队列延迟（后端）'),str(q.queue_delay_seconds,fixed('未提供'))+fixed(' 秒'));line(list,fixed('累计量 / 额'),decimal(q.cumulative_volume)+' / '+decimal(q.cumulative_amount));line(list,fixed('估计活动门槛'),({passed:fixed('已达估计活动门槛，仍无流动性证明'),waiting:fixed('等待连续两份有效报价及量额推进'),invalid:fixed('行情无效，等待')}[q.activity_gate]||fixed('等待后端核验'))+(q.waiting_reason||q.reason_code?' · '+waitingReason(q.waiting_reason,q.reason_code,''):''));line(list,fixed('停牌 / 可交易状态'),q.market_status==='suspended'?fixed('明确停牌，等待'):q.market_status==='invalid'?fixed('行情无效，等待'):q.market_status==='unverified'?fixed('公共报价未核验'):fixed('状态待核对，本期公共适配器无官方可交易证明'));c.append(list);if(collectionWait)c.append(node('p','rtp-wait',collectionWait));dates(c,q,['quote_at','received_at']);}
    if(!fields.quotes.children.length)empty(fields.quotes,fixed('尚无报价；等待后续有效行情。'));
    for(const o of unique(a?.orders)){const c=card(fields.orders,str(o.name,o.code)+' · '+str(o.code)+' · '+({buy:fixed('买入'),sell:fixed('卖出')}[o.side]||fixed('方向待核对')));c.append(node('span','pill neutral',statusLabels[o.status]||fixed('状态待核对（本期不支持部分成交）')));const list=node('dl');for(const [label,value] of [[fixed('订单 ID'),str(o.id)],[fixed('计划 / 意图 / 信号 ID'),str(o.plan_id)+' / '+str(o.intent_id)+' / '+str(o.signal_id)],[fixed('限价'),decimal(o.limit_price)],[fixed('委托数量 / 剩余'),decimal(o.quantity)+' / '+decimal(o.remaining_quantity)],[fixed('冻结资金 / 份额'),decimal(o.frozen_cash,2)+fixed(' 元 / ')+decimal(o.frozen_quantity)],[fixed('等待 / 处理原因'),pending.has(o.status)?waitingReason(o.waiting_reason,o.reason_code,fixed('未提供'),true):str(o.waiting_reason,reasons[o.reason_code]||fixed('未提供'))],[fixed('规则 / 费率版本'),str(o.rule_version)+' / '+str(o.fee_version)]])line(list,label,value);c.append(list);if(collectionWait&&pending.has(o.status))c.append(node('p','rtp-wait',collectionWait));dates(c,o,['signal_at','submitted_at','eligible_at','expires_at']);const cancel=button(fixed('撤销此委托'),()=>mutate('cancel',o.id));cancel.setAttribute('aria-label',fixed('撤销委托 ')+str(o.id));fields.cancelButtons.push({button:cancel,status:o.status,canCancel:o.cancelable});cancel.hidden=!pending.has(o.status);c.append(cancel);}
    if(!fields.orders.children.length)empty(fields.orders,fixed('暂无委托。启动后由当前策略已确认的目标生成执行计划。'));
    for(const f of unique(a?.fills).sort((x,y)=>Date.parse(y.matched_at)-Date.parse(x.matched_at)||0)){const c=card(fields.fills,str(f.name,f.code)+' · '+str(f.code)+fixed(' · 模拟估计成交')),list=node('dl');for(const [label,value] of [[fixed('估计成交 ID'),str(f.id)],[fixed('订单 / 计划 / 意图 ID'),str(f.order_id)+' / '+str(f.plan_id)+' / '+str(f.intent_id)],[fixed('信号 / 报价 ID'),str(f.signal_id)+' / '+str(f.quote_id)],[fixed('方向'),({buy:fixed('买入'),sell:fixed('卖出')}[f.side]||fixed('待核对'))],[fixed('估计价格 / 数量'),decimal(f.price)+' / '+decimal(f.quantity)],[fixed('估计成交金额'),decimal(f.gross_amount,2)+fixed(' 元')],[fixed('模拟费用'),decimal(f.fee,2)+fixed(' 元')],[fixed('滑点假设（基点）'),decimal(f.slippage_bps)],[fixed('报价来源'),str(f.source)],[fixed('模型 / 规则 / 费率版本'),str(f.model_version)+' / '+str(f.rule_version)+' / '+str(f.fee_version)]])line(list,label,value);c.append(list);dates(c,f,['signal_at','submitted_at','eligible_at','quote_at','received_at','matched_at']);}
    if(!fields.fills.children.length)empty(fields.fills,fixed('尚无模拟估计成交；不会补记启动前的成交。'));
    for(const e of unique(a?.events)){const c=card(fields.events,str(e.type,fixed('模拟事件'))),list=node('dl');for(const [label,value] of [[fixed('事件 ID'),str(e.id)],[fixed('关联订单 / 成交 / 计划'),str(e.order_id)+' / '+str(e.fill_id)+' / '+str(e.plan_id)],[fixed('事件时间 · at'),time(e.at)]])line(list,label,value);c.append(list,node('p','',str(e.message)));}if(!fields.events.children.length)empty(fields.events,fixed('暂无独立模拟事件。'));
    for(const r of unique(state.data?.rules)){const c=card(fields.rules,str(r.name,r.code)+' · '+str(r.code)),list=node('dl');for(const [key,label] of [['version',fixed('规则版本')],['effective_from',fixed('生效日期')],['effective_to',fixed('有效截止')],['lot_size',fixed('交易单位（份）')],['price_tick',fixed('价格档位')],['settlement',fixed('可卖规则')],['price_limit_ratio',fixed('价格限制比例')]])line(list,label,str(r[key],fixed('未提供，待核对')));line(list,fixed('规则核验来源'),Array.isArray(r.sources)?r.sources.join('；'):fixed('未提供，待核对'));line(list,fixed('规则状态'),r.verified===true?fixed('规则已核验'):str(r.waiting_reason,fixed('规则待核对')));c.append(list);}
    const fee=a?.fee_config||{},model=state.data?.model||{},c=card(fields.rules,fixed('模拟费率与估计条件')),list=node('dl');for(const [label,value] of [[fixed('费率版本'),str(fee.version)],[fixed('模拟费率'),str(fee.rate,fixed('未提供'))],[fixed('模拟最低费用'),str(fee.min_fee,fixed('未提供'))+fixed(' 元')],[fixed('滑点假设（基点）'),str(fee.slippage_bps,fixed('未提供'))],[fixed('模型版本 / 参数说明'),str(model.version)+' / '+str(fee.label)],[fixed('源延迟上限（秒）'),str(model.freshness?.source_delay_max_seconds)],[fixed('撮合年龄上限（秒）'),str(model.freshness?.match_age_max_seconds)],[fixed('队列延迟上限（秒）'),str(model.freshness?.queue_delay_max_seconds)],[fixed('阈值边界'),model.freshness?.boundary==='inclusive'?fixed('等于上限允许'):fixed('未提供，待核对')],[fixed('连续报价要求'),str(model.activity_quotes_required)],[fixed('交易窗口'),Array.isArray(model.windows)?model.windows.join('、')+fixed('（左闭右开）'):fixed('待核对')],[fixed('日内到期时间'),str(model.expiry_time)]])line(list,label,value);c.append(list,node('p','small muted',fixed('费率与最低费用是模拟假设，不代表实际券商收费。当前无盘口，整单估计不能证明真实可成交数量。')));for(const limitation of model.limitations||[])c.append(node('p','small rtp-wait',limitation));
    compactCards(fields.positions,unique(a?.holdings),[0,2,4,5],'holding');compactCards(fields.orders,unique(a?.orders),[2,3,4,5],'order');compactCards(fields.fills,unique(a?.fills).sort((x,y)=>Date.parse(y.matched_at)-Date.parse(x.matched_at)||0),[3,4,5,6],'fill');
    for(const d of state.root.querySelectorAll('details[data-detail-key]'))if(openDetails.has(d.dataset.detailKey))d.open=true;controls();
  }
  function schedule(){clearTimeout(state.timer);state.timer=null;if(state.active&&!state.busy)state.timer=setTimeout(()=>refresh(),30000);}
  function reconcile(data){
    const u=state.uncertain;if(!u||compareInteger(data.revision,u.revision||'0')<=0)return;
    const a=data.accounts.find(a=>String(a.id)===u.id);let confirmed=false;
    if(u.kind==='create'){const matches=data.accounts.filter(a=>!u.previousIds.has(String(a.id))&&a.name===u.body.name&&sameCash(a.initial_cash,u.body.initial_cash));if(matches.length===1){state.id=String(matches[0].id);confirmed=true;}}
    if(u.kind==='capital')confirmed=!!a&&sameCash(a.initial_cash,u.body.initial_cash);
    if(u.kind==='start')confirmed=a?.status==='running';
    if(u.kind==='pause')confirmed=!!a&&['paused','stopped'].includes(a.status)&&!(a.orders||[]).some(o=>pending.has(o.status));
    if(u.kind==='cancel')confirmed=['cancelled','filled','expired','rejected'].includes(a?.orders?.find(o=>String(o.id)===String(u.body))?.status);
    if(confirmed){state.uncertain=null;if(['create','capital'].includes(u.kind)&&sameCash(fields.cash.value,u.body.initial_cash)){state.dirty=false;state.creating=false;}message(fixed('上次操作已通过更新后的快照核对，请查看当前状态。'));}
  }
  function accept(data,{resetDraft=false,fromCommand=false}={}){
    if(!data||data.contract_version!=='realtime-paper-v1'||(data.strategy!==undefined&&data.strategy!==state.strategy)||(weeklyStrategy()&&data.strategy!==state.strategy)||!Array.isArray(data.accounts)||data.accounts.length>1||data.accounts.some(a=>!a||a.strategy!==state.strategy||!/^[-A-Za-z0-9_]{1,100}$/.test(a.id))||typeof data.revision!=='string'||!/^\d+$/.test(data.revision))throw uiError(fixed('账户响应不完整，请刷新核对。'));
    if(state.revision!==null&&compareInteger(data.revision,state.revision)<0)throw uiError(fixed('收到较旧的账户响应，已保留当前状态。'));
    reconcile(data);
    if(resetDraft){state.dirty=false;state.creating=false;}
    state.data=data;state.revision=data.revision;state.readAt=performance.now();state.pnlFromCommand=fromCommand;
    if(!data.accounts.some(a=>String(a.id)===state.id)){state.id=data.accounts[0]?String(data.accounts[0].id):'';if(state.id)state.creating=false;}
    state.ready=true;render();
  }
  async function refresh(){
    if(!state.active||!state.transport||state.loading||state.busy)return;
    const epoch=state.epoch,strategy=state.strategy;state.loading=true;controls();
    try{const data=await state.transport.load(strategy);if(!state.active||epoch!==state.epoch||strategy!==state.strategy)return;accept(data);fields.error.hidden=true;}
    catch(e){if(state.active&&epoch===state.epoch){state.ready=false;showError(e);renderHoldingLogic(account());}}
    finally{if(epoch===state.epoch){state.loading=false;controls();fields.wechatView?.refresh();schedule();}}
  }
  async function save(){
    if(!state.active||state.busy||!state.ready||state.uncertain||!['ready','degraded'].includes(state.data?.service?.status)||!fields.form.reportValidity())return;
    const a=account(),create=state.creating||!a,initial_cash=fields.cash.value.trim();
    if(create&&(state.data?.accounts?.length||!fields.confirm.checked))return;
    if(!positiveCash(initial_cash))throw uiError(fixed('本金须为大于零且不超过10亿元的金额，最多两位小数。'));
    if(!create&&(a.can_edit_capital!==true||!['stopped','paused'].includes(a.status)||a.fills?.length))return;
    const name=fields.name.value.trim();if(create&&(!name||name.length>80))throw uiError(fixed('账户名称须为1至80个字符。'));
    await write(create?'create':'capital',create?{name,initial_cash}:{initial_cash});
  }
  async function mutate(kind,orderId){
    if(!state.active||state.busy||!state.ready||state.uncertain||!['ready','degraded'].includes(state.data?.service?.status))return;const a=account();if(!a||!knownAccount())return;
    if(kind==='start'&&(state.creating||state.dirty||a.status==='running'||a.can_start!==true))return;
    if(kind==='pause'&&(state.creating||a.status!=='running'||a.can_pause!==true))return;
    if(kind==='cancel'){const o=a.orders?.find(o=>String(o.id)===String(orderId));if(!o||!pending.has(o.status)||o.cancelable!==true)return;}
    await write(kind,orderId);
  }
  async function write(kind,body){
    const epoch=++state.epoch,strategy=state.strategy,id=state.id,revision=state.revision,previousIds=new Set((state.data?.accounts||[]).map(a=>String(a.id))),operation={kind,id,body,previousIds,revision,strategy};state.uncertain=operation;clearTimeout(state.timer);state.loading=false;state.busy=true;fields.error.hidden=true;fields.result.hidden=true;controls();
    try{
      const result=kind==='create'?await state.transport.create(body,strategy):kind==='capital'?await state.transport.capital(id,body,strategy):kind==='cancel'?await state.transport.cancel(id,body,strategy):await state.transport[kind](id,strategy);
      if(!state.active||epoch!==state.epoch||strategy!==state.strategy)return;
      if(result?.ok===false){const rejected=uiError(str(result.message,fixed('操作未完成，请核对当前状态。')));rejected.code='INVALID_STATE';throw rejected;}
      accept(result,{resetDraft:kind==='create'||kind==='capital',fromCommand:true});state.uncertain=null;
      const a=account();let text=fixed('操作已返回，当前状态已刷新。');
      if(kind==='create')text=a?.status==='stopped'?fixed('账户已创建，默认停止；确认后可手动启动。'):fixed('账户已返回，请核对运行状态。');
      if(kind==='capital')text=fixed('本金保存请求已返回，请核对已保存本金与当前资产。');
      if(kind==='start')text=a?.status==='running'?fixed('模拟已启动，从本轮启动时刻向前等待有效报价。'):fixed('启动请求已返回，请查看当前状态与等待原因。');
      if(kind==='pause')text=['paused','stopped'].includes(a?.status)?fixed('账户已暂停；请在委托与冻结资金中核对撤销结果。'):fixed('暂停请求已返回，当前状态仍需核对。');
      if(kind==='cancel')text=fixed('撤单请求已返回，请查看委托的实际状态。');message(text);
    }catch(e){const rejected=rejectedCodes.has(e?.code)||[400,401,403,404,405,409,413].includes(e?.status);if(rejected&&state.uncertain===operation)state.uncertain=null;if(epoch===state.epoch){state.ready=false;if(state.active)showError(uiError(fixed('{prefix}{reason}{suffix}',{prefix:rejected?fixed('操作已拒绝：'):fixed('操作结果需核对：'),reason:e[FIXED]??str(e.message,e),suffix:rejected?fixed('。请刷新状态后再操作。'):fixed('。请刷新状态，避免重复提交。')})));}}
    finally{state.busy=false;if(epoch===state.epoch){controls();schedule();}else if(state.active){controls();refresh();}}
  }
  function switchStrategy(strategy){
    if(!strategies.includes(strategy)||strategy===state.strategy||!state.active||state.busy||state.uncertain||state.dirty||emailDraft.dirty||emailDraft.saving)return;
    state.epoch++;clearTimeout(state.timer);state.timer=null;state.strategy=strategy;state.loading=false;state.ready=false;state.data=null;state.id='';state.revision=null;state.readAt=null;state.pnlFromCommand=false;state.creating=false;
    window.RealtimePaperComparison?.reset();suspendEmailDraft({clear:true});decisionSelections.clear();historyViews.clear();priceViews.clear();pnlHistoryViews.clear();fields.confirm.checked=false;fields.error.hidden=true;fields.result.hidden=true;fields.error.textContent='';fields.result.textContent='';fixedNodes.delete(fields.error);fixedNodes.delete(fields.result);render();refresh();if(!weeklyStrategy())loadEmailDraft();
  }
  function init({root='page-realtime-paper',transport,toast}={}){if(state.root)return;const target=typeof root==='string'?document.getElementById(root):root;if(!target)return;state.root=target;state.transport=transport;state.toast=toast;build();}
  function setActive(active){active=Boolean(active);if(!state.root||active===state.active)return;state.active=active;window.RealtimePaperComparison?.setActive(active);state.epoch++;clearTimeout(state.timer);state.loading=false;state.ready=false;suspendEmailDraft();controls();if(active){if(!state.transport?.load)showError(uiError(fixed('接口契约尚未接入；此页面暂不能读取或操作账户。')));else if(!state.busy)refresh();if(!emailDraft.saving)loadEmailDraft();}}
  function reset(){setActive(false);window.RealtimePaperComparison?.reset();suspendEmailDraft({clear:true});state.strategy='D0';state.data=null;state.id='';state.revision=null;state.uncertain=null;state.dirty=false;state.creating=false;decisionSelections.clear();historyViews.clear();priceViews.clear();pnlHistoryViews.clear();fields.error.hidden=true;fields.result.hidden=true;fields.error.textContent='';fields.result.textContent='';fixedNodes.delete(fields.error);fixedNodes.delete(fields.result);render();}
  document.addEventListener('etf-language-change',()=>{if(state.root){for(const [target,value] of fixedNodes)target.textContent=String(value);render();}});
  window.RealtimePaper={init,setActive,refresh,reset};
})();
