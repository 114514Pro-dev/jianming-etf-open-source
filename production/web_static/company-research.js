// BEGIN_DYNAMIC_EVALUATION_UI
'use strict';
(() => {
  const rows=value=>Array.isArray(value)?value:[];
  const number=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
  const format=value=>number(value)===null?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:2});
  const labels={roe:'净资产收益率 ROE',net_margin:'合并净利率',revenue_yoy:'收入同比',cash_conversion:'利润现金含量',debt_ratio:'资产负债率',recurring_profit:'扣非盈利占比'};
  const statuses={ready:'同行参考可用',specialist:'需行业专项研究',risk_review:'风险事项待核查',insufficient:'资料不足'};
  const financialSources={current_detail:'当前详情中的财务资料',saved_deep_report:'已保存深研报告中的财务资料',verified_deep_cache_supplement:'从已核对的深研缓存补算',unavailable:'尚无可用的多年财务来源'};
  function el(tag,cls,value){const node=document.createElement(tag);if(cls)node.className=cls;if(value!==undefined)node.textContent=String(value);return node;}
  function raw(tag,cls,value){const node=el(tag,cls,value);node.setAttribute('data-i18n-skip','');return node;}
  function valid(data,code){return data?.version==='dynamic-financial-1.0'&&String(data.code)===String(code);}
  function score(data){const value=number(data?.relative_score);return data?.status==='ready'&&value!==null&&value>=0&&value<=100&&data.coverage?.available_metrics===6&&data.coverage?.total_metrics===6&&data.risk?.status!=='identified_high_risk'?value:null;}
  function statusText(data){return data?.status==='ready'&&score(data)===null?'资料不足':statuses[data?.status]||'资料不足';}
  function date(value){if(typeof value!=='string'||!value)return '—';const parsed=new Date(value);return /[TZ]|[+-]\d\d:\d\d$/.test(value)&&Number.isFinite(parsed.valueOf())?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(parsed):value;}
  function line(parent,label,value){const row=el('p','research-dynamic-line');row.append(el('span','muted',label),raw('span','',value??'—'));parent.append(row);}
  function text(value){if(typeof value==='string')return value;return value&&typeof value==='object'?[value.message,value.text,value.label,value.reason].find(item=>typeof item==='string')||'核查事项尚待补充说明。':'';}
  function list(parent,values,fallback){const items=rows(values).map(text).filter(Boolean);if(!items.length){if(fallback)parent.append(el('p','small muted',fallback));return;}const ul=el('ul','research-notes');for(const item of items)ul.append(el('li','',item));parent.append(ul);}
  function value(item){const n=number(item?.value);return n===null?'—':item.unit==='multiple'||item.unit==='decimal'&&item.key==='cash_conversion'?`${format(n)}×`:['ratio','decimal'].includes(item.unit)?`${format(n*100)}%`:format(n);}
  function longTerm(parent,data,compact=false){const block=el('div','research-dynamic-long-term');block.append(el(compact?'span':'h4','',compact?'多年财务':'多年财务表现'));block.append(el('p',compact?'small muted':'',typeof data?.label==='string'&&data.label?data.label:'尚无可用的多年财务观察。'));line(block,'完整年度覆盖',`${format(data?.complete_years)} / ${format(data?.target_years)}`);if(!compact){line(block,'连续完整年度',format(data?.consecutive_years));line(block,'财务研究截止',date(data?.as_of));block.append(el('p','small muted',financialSources[data?.source]||financialSources.unavailable),el('p','small muted','年度覆盖只表示取得的财务资料范围，不代表经营质量已获确认。'));}parent.append(block);}
  function card(data,{companyCode}={}){const block=el('div','research-dynamic-card');block.append(el('span','small muted','同行财务参考'));const good=valid(data,companyCode),rating=good?score(data):null;block.append(raw('strong','research-dynamic-rating',format(rating)));block.append(el('span','small muted',good?statusText(data):'尚无同行参考'));if(good){block.append(el('p','small muted','50 为同业中位附近，非胜率或合格线。'));line(block,'可用财务项',`${format(data.coverage?.available_metrics)} / ${format(data.coverage?.total_metrics)}`);if(data.long_term&&typeof data.long_term==='object')longTerm(block,data.long_term,true);else block.append(el('p','small muted','查看详情了解多年财务覆盖'));if(rows(data.risk?.flags).length)block.append(el('p','research-dynamic-risk-note','存在需核查的绝对风险事项。'));}return block;}
  function render(data,{companyCode,savedReport=false}={}){
    const root=el('section','research-detail-section research-dynamic');root.setAttribute('aria-label','动态财务评价');root.append(el('h3','','动态财务评价'));
    if(!valid(data,companyCode)){root.append(el('p','small muted',!data?'尚无动态评价资料，原财务初筛仍可查看。':data.version!=='dynamic-financial-1.0'?'动态评价版本待更新，暂不展示。':'动态评价主体与当前公司不一致，已停止展示。'));return root;}
    if(savedReport)root.append(el('p','small muted','当前动态评价来自最新财务快照，独立于下方已保存的 AI 报告。'));
    const overview=el('div','research-dynamic-overview'),relative=el('div','research-dynamic-reference');relative.append(el('h4','','同行财务参考'),raw('strong','research-dynamic-rating',format(score(data))),el('span','pill neutral',statusText(data)));
    relative.append(el('p','small muted','50 表示接近同行中位水平，不是及格线、胜率或安全概率。'));line(relative,'原财务初筛',format(data.legacy_score));line(relative,'可比同行数',format(data.peer_count));line(relative,'可用财务项',`${format(data.coverage?.available_metrics)} / ${format(data.coverage?.total_metrics)}`);overview.append(relative);longTerm(overview,data.long_term);root.append(overview);
    const meta=el('div','research-dynamic-meta');line(meta,'同行行业',data.industry||'—');line(meta,'财务报告期',date(data.report_date));line(meta,'公告日期',date(data.announced_at));line(meta,'当前评价截止',date(data.as_of));root.append(meta);
    root.append(el('p','small muted','同行参考与原财务初筛并列展示；价格与估值单独判断。两种财务参考都不是完整公司质量结论。'));list(root,data.gaps);
    const absolute=el('section','research-dynamic-risk');absolute.append(el('h4','','绝对风险与核查事项'));list(absolute,data.risk?.flags,'当前未列出风险事项，不代表已经排除风险。');absolute.append(el('p','small muted','相对财务表现不能抵消债务、审计或治理问题，仍需核对绝对数值与原文。'));root.append(absolute);
    const metrics=el('div','research-dynamic-metrics');for(const [key,label] of Object.entries(labels)){const item=rows(data.metrics).find(row=>row&&row.key===key),box=el('details','research-dynamic-metric'),head=el('summary');head.append(el('span','',label),raw('strong','',value(item)));box.append(head);line(box,'本公司绝对值',value(item));line(box,'同行中位数',value({...item,value:item?.peer_median}));line(box,'可比同行数',format(item?.peer_count));line(box,'连续同行参考',format(item?.score));line(box,'固定权重',number(item?.weight)===null?'—':`${format(item.weight)}%`);line(box,'同行下四分位数',value({...item,value:item?.p25}));line(box,'同行上四分位数',value({...item,value:item?.p75}));line(box,'同行换算尺度',value({...item,value:item?.scale}));line(box,'加权贡献',format(item?.contribution));if(rows(item?.gaps).length)list(box,item.gaps);else if(!item)box.append(el('p','small muted','该财务项尚无可用资料。'));metrics.append(box);}root.append(metrics);
    const evidence=el('section','research-dynamic-evidence');evidence.append(el('h4','','数据与证据状态'),el('p','','基于供应商财务快照，尚未完成官方逐值核验。'),el('p','small muted','当前评价及观察记录尚未认证严格历史时点可用，不能直接作为无前视偏差回测数据。'));root.append(evidence);
    const tracking=data.tracking||{},changes=el('section','research-dynamic-changes');changes.append(el('h4','','变化与实际观察记录'));line(changes,'本次观察时间',date(tracking.observed_at));line(changes,'上次观察时间',date(tracking.previous_observed_at));const delta=number(tracking.delta);line(changes,'较上次记录变化',tracking.status==='recorded'&&delta!==null?`${delta>0?'+':''}${format(delta)}`:'—');if(tracking.status==='pending')changes.append(el('p','small muted','当前评价尚待后台记录；历史仅展示已保存的实际观察。'));else if(tracking.status==='first_record')changes.append(el('p','small muted','这是首次实际观察，没有可比的前次记录。'));else if(tracking.status==='unavailable')changes.append(el('p','small muted','变化记录暂不可用，当前财务参考仍可查看。'));list(changes,tracking.reasons,'尚无可用的变化原因。');changes.append(el('p','small muted','同行构成、覆盖范围或评价方法改变，不等于公司经营改善或恶化。'));
    const history=el('details','research-dynamic-history');history.append(el('summary','','查看已保存的观察历史'));history.append(el('p','small muted','历史从本功能启用后的实际观察开始记录，不回填过去，也不是历史收益。'));if(!rows(data.history).length)history.append(el('p','small muted','尚无已保存的观察历史。'));for(const record of rows(data.history).slice(0,20)){if(!record||typeof record!=='object')continue;const row=el('article','research-dynamic-history-row');line(row,'观察时间',date(record.observed_at));line(row,'财务报告期',date(record.report_date));const value=number(record.relative_score);line(row,'同行财务参考',value!==null&&value>=0&&value<=100?format(value):'—');line(row,'原财务初筛',format(record.legacy_score));const delta=number(record.delta);line(row,'较上次记录变化',delta===null?'—':`${delta>0?'+':''}${format(delta)}`);list(row,record.reasons);history.append(row);}changes.append(history);root.append(changes);
    const method=el('details','research-dynamic-method');method.append(el('summary','','查看比较方法与适用范围'),el('p','','只在同细行业、同报告期及可确认财务口径的同行中比较，每项至少需要 5 家其他公司。'),el('p','','分项根据公司数值与同行中位数的差距平滑换算，再按固定权重合并；缺项不重新分配权重。'),el('p','','参考值采用 0–100 连续刻度，不是精确百分位；负债率较低的方向较优，其他项目较高的方向较优。'));
    if(typeof data.method==='string')method.append(el('p','small muted',data.method));else if(Array.isArray(data.method))list(method,data.method);root.append(method);return root;
  }
  window.ETFResearchDynamic={render,card,valid,score};
})();
// END_DYNAMIC_EVALUATION_UI
// BEGIN_INDUSTRY_UI
'use strict';
// Isolated display component: consumes the phase4 contract; never changes scores.
(() => {
  const list=x=>Array.isArray(x)?x:[], obj=x=>x&&typeof x==='object'&&!Array.isArray(x)?x:{}, number=x=>typeof x==='number'&&Number.isFinite(x);
  const models={general:'普通非金融',bank:'银行',insurance:'保险',securities:'证券公司',property:'房地产开发',cyclical:'周期行业候选',financial_unresolved:'金融业务类型待核实',unknown:'行业待核实'};
  const earnings={positive:'合并及归母利润均为正',loss_making:'至少一项利润非正（含零）',unknown:'盈利状态待核实'};
  const modules={general_screen:'普通六指标初筛',long_term:'多年经营观察',debt_liquidity:'债务与流动性',cash_conversion:'利润与现金关系',gross_margin:'毛利率观察',capital_allocation:'资本使用',governance:'治理核查',valuation:'估值方法',pe:'市盈率'};
  const states={conditional:'有条件适用',not_applicable:'普通方法不适用',raw_trends_only:'保留原始趋势',specialist_required:'需要专项行业方法',context_only:'仅作背景观察',applicable_with_evidence:'须结合具体证据',missing_field:'缺少专项字段',missing_metadata:'来源口径缺失',missing_value_key:'未提供数值',disclosed_null:'披露值为空',invalid_number:'数值无效',unusable_basis:'口径不可用',subtype_required:'业务类型待确认',segment_required:'分部口径待确认',observed:'已提供数值',zero:'明确为零'};
  const facts={npl_ratio:'不良贷款率',provision_coverage:'拨备覆盖率',capital_adequacy:'资本充足率',cet1_ratio:'核心一级资本充足率',net_interest_margin:'净息差',core_solvency:'核心偿付能力充足率',comprehensive_solvency:'综合偿付能力充足率',nbv_growth:'新业务价值增速',combined_ratio:'综合成本率',investment_yield:'投资收益率',net_capital:'净资本',risk_coverage:'风险覆盖率',liquidity_coverage:'流动性覆盖率',net_stable_funding:'净稳定资金率',restricted_cash:'受限货币资金',contract_liabilities:'合同负债（不能替代债务或收入）',inventory_impairment:'存货减值（余额或计提须区分）',sales_collections:'销售回款（不能替代收入）',project_guarantees:'项目担保披露额',capacity_utilization:'产能利用率',unit_selling_price:'产品单位售价',unit_cash_cost:'产品单位现金成本',maintenance_capex:'已区分的维持性资本开支'};
  function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;}
  function raw(tag,cls,text){const n=el(tag,cls,text??'—');n.setAttribute('data-i18n-skip','');return n;}
  function para(node,text,cls='small muted'){if(text)node.append(el('p',cls,text));}
  function field(node,label,value){const n=el('p','research-ind-meta');n.append(el('span','',label),document.createTextNode(' '),raw('span','',value===null||value===undefined||value===''?'—':value));node.append(n);}
  function detail(label){const n=el('details','research-ind-details');n.append(el('summary','',label));return n;}
  function safeURL(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u:null;}catch(_){return null;}}
  function source(node,ref,sources){ref=obj(ref);const id=ref.source_id,match=id?list(sources).find(x=>obj(x).id===id):null;
    const direct=Object.hasOwn(ref,'source_url')?ref.source_url:ref.url,url=safeURL(direct||(obj(match).url));
    if(url){const a=el('a','','查看供应来源');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';node.append(a);}else para(node,'来源链接待补齐。');
    field(node,'来源编号',id);if(ref.sha256)field(node,'原文件 SHA256',ref.sha256);
    if(ref.raw_field||ref.field)field(node,'供应商原字段',ref.raw_field||ref.field);if(Object.hasOwn(ref,'raw_value'))field(node,'供应商原标签',ref.raw_value);
    if(ref.observed_at)field(node,'供应商观测时间',ref.observed_at);field(node,'字段公告日期',ref.announced_at);
    if(ref.report_date)field(node,'字段报告期',ref.report_date);
  }
  function codes(node,items){const values=list(items).filter(x=>typeof x==='string');if(!values.length)return;const d=detail('查看原始缺口代码');for(const x of values)d.append(raw('p','small',x));node.append(d);}
  function valid(data,companyCode){return data&&data.version==='industry-policy-1.0'&&(!companyCode||data.code===companyCode);}
  function canUse(data,screen){const gate=obj(obj(screen).industry_applicability);return valid(data)&&obj(data.classification).model==='general'&&data.earnings_status==='positive'&&obj(obj(data.modules).general_screen).status==='conditional'&&gate.version==='industry-applicability-gate-1.0'&&gate.general_ranking_allowed===true;}
  function renderBadge(data,{screen={},companyCode=null}={}){const n=el('span','research-ind-badge');
    if(!valid(data,companyCode)){n.append(el('span','','行业适用性待核查'));return n;}
    n.append(el('span','',models[obj(data.classification).model]||models.unknown),document.createTextNode(' · '),el('span','',canUse(data,screen)?'普通初筛方法可用':'暂不进入普通排名'));return n;
  }
  function render(data,{sources=[],companyCode=null,screen={},stale=false,currentContext=null}={}){
    const area=el('section','research-section research-industry');area.append(el('h3','','行业与方法适用性'));
    para(area,'先确认行业和盈利口径，再说明哪些方法可用；本模块不形成行业评级或买卖建议。');
    if(!valid(data,companyCode)){para(area,!data?'尚无行业适用性资料。':data.version!=='industry-policy-1.0'?'行业资料版本待更新。':'行业资料主体不匹配。','notice warning-text');return area;}
    if(stale)para(area,'这是旧报告的只读行业视图，保留原研究截止。','notice warning-text');
    if(currentContext?.version==='price-industry-context-1.0'&&currentContext.company_code===companyCode)para(area,'本段保留原报告截止；当前行业资料见下方「公司质量与价格参考」。','notice');
    area.append(renderBadge(data,{screen,companyCode}));para(area,earnings[data.earnings_status]||earnings.unknown,'research-ind-lead');
    field(area,'研究截止',data.as_of);field(area,'财务报告期',data.report_date);
    const current=data.temporal_visibility==='current_snapshot_only_not_historical_pit';
    para(area,current?'行业采用供应商当前观测；采集时间不是行业分类公告日期。':'分类及财务日期按研究截止检查，仍不能证明严格历史时点可得。','research-ind-caveat');
    para(area,'严格历史 PIT：未验证，不能用于宣称无前视偏差的历史回测。','research-ind-caveat');
    para(area,'来源匹配与文件哈希检查不等于官方逐值核验；本模块官方逐值核验为零。');
    const cls=detail('行业来源与时间');
    for(const ref of list(obj(data.classification).evidence)){const row=el('div','research-ind-source');source(row,ref,sources);cls.append(row);}
    if(!list(obj(data.classification).evidence).length)para(cls,'尚无可用于行业判断的来源，未知行业不回退到普通企业。');
    codes(cls,obj(data.classification).issues);area.append(cls);
    const profit=detail('盈利字段、期间与来源');
    for(const [key,label] of [['net_profit','合并净利润'],['parent_profit','归母净利润']]){const item=obj(obj(data.earnings_basis)[key]),ref=obj(obj(data.earnings_sources)[key]),card=el('article','research-ind-card');card.setAttribute('data-profit',key);card.append(el('h4','',label));
      const value=number(item.value)&&!list(item.issues).length?item.value:null;field(card,'可用利润原值',value);if(value!==null)para(card,ref.currency==='CNY'||ref.unit_basis==='declared_supplier_endpoint_CNY_yuan'?'人民币元；报告期累计，不做年化。':'金额单位需按来源核实；不做年化。');
      field(card,'字段报告期',item.report_date);field(card,'字段公告日期',item.announced_at);source(card,ref,sources);codes(card,item.issues);profit.append(card);}
    area.append(profit);
    const grid=el('div','research-ind-grid');for(const [key,value] of Object.entries(obj(data.modules))){const item=obj(value),card=el('article','research-ind-card');card.setAttribute('data-module',key);const valuePanel=key==='valuation'&&obj(data.classification).model==='general';card.append(el('h4','',modules[key]||'方法待归类'),el('strong','research-ind-state',valuePanel?'见价格参考面板':states[item.status]||'状态待核查'));para(card,key==='valuation'?'下方分别列出供应商参考和完整口径要求；资料不足时不作价格结论。':item.reason);grid.append(card);}area.append(grid);
    if(list(data.specialist_observations).length){const d=detail('专项字段与缺口');para(d,'专项字段不代表监管达标或风险已排除；实体、期间与口径必须匹配。');
      for(const value of list(data.specialist_observations)){const item=obj(value),card=el('article','research-ind-card'),ref=obj(item.provenance);card.setAttribute('data-specialist',item.key||'');card.append(el('h4','',facts[item.key]||'专项观察'),el('span','',states[item.status]||'状态待核查'));
        const usable=['observed','zero'].includes(item.status)&&number(item.value)&&!list(item.issues).length;
        field(card,'披露原值',usable?item.value:null);field(card,'原单位',ref.unit);field(card,'币种',ref.currency);field(card,'主体与报表范围',[ref.subject_id,ref.scope].filter(Boolean).join(' / '));
        if(usable&&ref.unit==='decimal')para(card,'比例保留小数原值，未转换为百分数。');source(card,ref,sources);codes(card,item.issues);d.append(card);}area.append(d);}
    const gaps=detail('来源恢复与适用边界');para(gaps,obj(data.data_recovery).status==='recovered'?'本地来源已恢复，数值语义仍待核验。':'本地来源存在缺口，缺失值不补零。');
    for(const value of list(obj(data.data_recovery).gaps)){const gap=obj(value),row=el('p','small');row.append(el('span','','来源缺口'),document.createTextNode(' '),raw('span','',[gap.code,gap.source_id,gap.field].filter(x=>typeof x==='string').join(' · ')));gaps.append(row);}
    for(const value of list(data.limitations))if(typeof value==='string')para(gaps,value);area.append(gaps);return area;
  }
  function renderCoverage(coverage){const data=obj(coverage),area=el('section','research-ind-coverage');area.append(el('h3','','当前普通初筛覆盖'));
    const keys=['general_ranking_allowed_count','assessable_count','candidate_count','industry_unresolved_count','current_supplier_classification_count','historical_pit_usable_count'];
    const total=data.universe_total,integer=x=>Number.isSafeInteger(x)&&x>=0;
    const good=data.industry_gate_version==='industry-applicability-gate-1.0'&&integer(total)&&keys.every(k=>integer(data[k])&&data[k]<=total)&&data.assessable_count<=data.general_ranking_allowed_count&&data.candidate_count<=data.assessable_count&&data.historical_pit_usable_count===0;
    if(!good){para(area,'行业覆盖统计尚不可用，不能把缺项当零。');return area;}
    const grid=el('div','research-ind-grid');for(const [key,label] of [['universe_total','当前公司数'],['general_ranking_allowed_count','普通方法适用数'],['assessable_count','原六指标可评分数'],['candidate_count','原规则候选数'],['industry_unresolved_count','行业类型待核实数'],['current_supplier_classification_count','当前供应商分类数'],['historical_pit_usable_count','已验证历史 PIT 数']]){const card=el('div','research-ind-card');card.setAttribute('data-coverage',key);card.append(el('span','',label),raw('strong','research-ind-count',data[key]));grid.append(card);}area.append(grid);
    para(area,'未进入普通排名可能因为专项行业、盈利非正或资料不足；不能全部解释为财报缺失。');
    para(area,'候选沿用原六指标门槛，不是完整好公司结论或买入建议。');return area;
  }
  window.ETFResearchIndustry={render,renderBadge,renderCoverage};
})();

// END_INDUSTRY_UI
// BEGIN_HK_REFERENCES_UI
'use strict';
(() => {
  const DATA = {"version":"hk-reference-cards-1.0","title_zh":"港股官方资料参考","title_en":"Hong Kong official source references","reviewed_on":"2026-09-21","mode":"official_metadata_reference_only","integrated_analysis":false,"a_share_ranking_included":false,"scoring_admitted_fact_count":0,"numeric_semantics_verified":false,"cards":[{"id":"hk-ref-alibaba-fy2025","display_name_zh":"阿里巴巴集团","display_name_en":"Alibaba Group","issuer_name":{"value":"Alibaba Group Holding Limited","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 1, cover"},"securities":[{"market":"HKEX","code":{"value":"9988","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 1, cover"},"quote_currency":{"value":"HKD","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 1, HKD Counter"}},{"market":"HKEX","code":{"value":"89988","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 1, cover"},"quote_currency":{"value":"CNY","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 1, RMB Counter"}}],"report_title":{"value":"Fiscal Year 2025 Annual Report","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 1, cover"},"fiscal_year_end":{"value":"03-31","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 241, auditor report reporting period"},"period_end":{"value":"2025-03-31","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 241, annual consolidated statements"},"period_start":{"value":null,"verification":"not_checked","reason_zh":"本参考卡只核对年度结束日，未将期初日期纳入已核验字段。","reason_en":"Only the annual end date was checked for this card; the start date was not admitted as verified metadata."},"reporting_currency":{"value":"CNY","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 101, reporting currency of financial statements"},"accounting_standard":{"value":"US_GAAP","verification":"official_metadata_checked","source_id":"ali-fy2025","location":"PDF page 256, note 2(a) basis of presentation"},"report_source_id":"ali-fy2025","announcement_at":null,"price":null,"score":null,"financial_facts":[],"gaps_zh":["只有年度报告元数据和原文入口，财务数值尚未获准进入评分。","港币与人民币柜台不等于财报币种，未连接价格或做汇率换算。","公告精确时间未核对；报告全文未在本样本冻结，不能用于严格历史PIT。"],"gaps_en":["This card provides annual-report metadata and a source link. No financial values are admitted to scoring.","HKD and RMB trading counters are distinct from the reporting currency. No prices or FX conversion are connected.","The publication timestamp is unverified and the full filing is not frozen in this sample. Strict historical PIT is not established."]},{"id":"hk-ref-new-world-fy2025","display_name_zh":"新世界发展","display_name_en":"New World Development","issuer_name":{"value":"New World Development Company Limited","verification":"official_metadata_checked","source_id":"nwd-faq","location":"Issuer FAQ and investor relations identity"},"securities":[{"market":"HKEX","code":{"value":"0017","verification":"official_metadata_checked","source_id":"nwd-faq","location":"Stock code and ticker question"},"quote_currency":{"value":null,"verification":"not_checked","reason_zh":"本次来源只核对证券代码，未核对交易币种。","reason_en":"The security code was checked; its trading currency was not verified in this review."}}],"report_title":{"value":"Annual Report 2025 / full results announcement","verification":"official_metadata_checked","source_id":"nwd-fy2025","location":"Official issuer PDF indexed excerpt, printed page 221"},"fiscal_year_end":{"value":"06-30","verification":"official_metadata_checked","source_id":"nwd-faq","location":"Fiscal year question: annual cycle July to June"},"period_end":{"value":"2025-06-30","verification":"official_metadata_checked","source_id":"nwd-fy2025","location":"Official issuer PDF indexed excerpt, year-ended table heading, printed page 221"},"period_start":{"value":null,"verification":"not_checked","reason_zh":"已核对7月至6月的财年惯例，未把推算的期初日期当成报告直接核验值。","reason_en":"The July-to-June fiscal cycle was checked. An inferred start date is not presented as directly verified filing metadata."},"reporting_currency":{"value":"HKD","verification":"official_metadata_checked","source_id":"nwd-fy2025","location":"Official issuer PDF indexed excerpt, HK$m consolidated table, printed page 221"},"accounting_standard":{"value":null,"verification":"not_checked","reason_zh":"本次未核对会计准则说明。","reason_en":"The accounting-standard statement was not checked in this review."},"report_source_id":"nwd-fy2025","announcement_at":null,"price":null,"score":null,"financial_facts":[],"gaps_zh":["原PDF体积超过浏览工具读取上限，本次仅核对官方PDF已索引节选与发行人FAQ。","受限现金、净债务定义及财务数值未完成逐项核验，不显示金额或评分。","未核对交易币种、准则及公告精确时间，不能把港股上市地推断成这些字段。"],"gaps_en":["The original PDF exceeded the browser tool’s size limit. This review checked the indexed official-PDF excerpt and issuer FAQ only.","Restricted cash, the issuer’s net-debt definition and financial values remain unverified. No amounts or scores are shown.","Trading currency, accounting standards and the publication timestamp are unverified. They are not inferred from the Hong Kong listing."]}],"sources":[{"id":"ali-fy2025","url":"https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0626/2025062601064.pdf","publisher":"HKEXnews issuer filing","reviewed_on":"2026-09-21","access":"official_pdf_text_read","full_document_frozen":false,"sha256":null},{"id":"nwd-faq","url":"https://www.nwd.com.hk/investor-relations/column/faq","publisher":"New World Development","reviewed_on":"2026-09-21","access":"official_page_read","full_document_frozen":false,"sha256":null},{"id":"nwd-fy2025","url":"https://cms.nwd.com.hk/downloadIR/1393/e-FY2025%20final%20results%20annoucement_0.pdf","publisher":"New World Development","reviewed_on":"2026-09-21","access":"official_indexed_excerpt_only","direct_read_error":"content_length_exceeds_tool_limit","observed_content_length":21483207,"full_document_frozen":false,"sha256":null}]};
  const arr=x=>Array.isArray(x)?x:[],obj=x=>x&&typeof x==='object'&&!Array.isArray(x)?x:{};
  function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;}
  function raw(tag,cls,text){const n=el(tag,cls,text);n.setAttribute('data-i18n-skip','');return n;}
  function checked(field){return obj(field).verification==='official_metadata_checked'&&typeof field.value==='string'&&field.value?field.value:null;}
  function field(node,label,value){const p=el('p','research-ind-meta');p.append(el('span','',label),document.createTextNode(' '),value===null?el('span','','未核对'):raw('span','',value));node.append(p);}
  function safeURL(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&['www1.hkexnews.hk','www.nwd.com.hk','cms.nwd.com.hk'].includes(u.hostname)?u:null;}catch(_){return null;}}
  function render(data=DATA){
    const area=el('details','research-hk-references research-industry');area.append(el('summary','','港股官方资料参考'));
    if(!data||data.version!=='hk-reference-cards-1.0'||data.mode!=='official_metadata_reference_only'||data.a_share_ranking_included!==false||data.scoring_admitted_fact_count!==0){area.append(el('p','','港股参考资料版本待核查。'));return area;}
    area.append(el('p','research-ind-caveat','官方报告和元数据入口；本参考入口尚无可评分的港股财务资料，未加入 A 股排名。'));
    const count=el('p','small muted');count.append(el('span','','参考公司数'),document.createTextNode(' '),raw('strong','',arr(data.cards).length),document.createTextNode(' · '),el('span','','纳入评分的财务事实'),document.createTextNode(' '),raw('strong','',0));area.append(count);
    field(area,'资料核对日',typeof data.reviewed_on==='string'?data.reviewed_on:null);
    const grid=el('div','research-ind-grid');for(const value of arr(data.cards)){
      const card=obj(value),node=el('article','research-ind-card');node.setAttribute('data-hk-reference',card.id||'');node.append(el('h4','',card.display_name_zh||'港股资料参考'));
      field(node,'发行人原名',checked(card.issuer_name));
      for(const security of arr(card.securities)){field(node,'港交所证券代码',checked(obj(security).code));field(node,'交易柜台币种',checked(obj(security).quote_currency));}
      field(node,'报告标题',checked(card.report_title));field(node,'会计年度结束日',checked(card.fiscal_year_end));field(node,'报告覆盖截止',checked(card.period_end));field(node,'财报币种',checked(card.reporting_currency));field(node,'会计准则',checked(card.accounting_standard));
      const source=arr(data.sources).find(x=>obj(x).id===card.report_source_id),url=safeURL(obj(source).url);
      if(url){const link=el('a','','打开官方报告');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';node.append(link);}else node.append(el('p','','官方报告链接待核对。'));
      const gaps=el('details','research-ind-details');gaps.append(el('summary','','覆盖边界与未核对事项'));
      for(const text of arr(card.gaps_zh))if(typeof text==='string')gaps.append(el('p','small muted',text));
      for(const item of arr(data.sources).filter(x=>[card.report_source_id,...Object.values(card).filter(x=>x&&typeof x==='object').map(x=>x.source_id)].includes(obj(x).id))){const u=safeURL(item.url);if(u){const a=el('a','','查看元数据来源');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';gaps.append(a);field(gaps,'来源编号',item.id);}}
      node.append(gaps);grid.append(node);
    }area.append(grid);return area;
  }
  window.ETFResearchHKReferences={render,version:'hk-reference-cards-1.0'};
})();

// END_HK_REFERENCES_UI
// BEGIN_DEBT_GOVERNANCE_UI
'use strict';
// Deterministic debt/governance view; arithmetic and evidence arrive from the server.
// It formats the supplied contract only; it performs no arithmetic or requests.
(() => {
  const rows=value=>Array.isArray(value)?value:[];
  const numeric=value=>typeof value==='number'&&Number.isFinite(value);
  const string=value=>value===null||value===undefined?'':typeof value==='object'?JSON.stringify(value):String(value);
  const states={reported_value:'已提供数值',reported_zero:'明确为零',null:'数值为空',not_provided:'未提供',invalid:'数值无效',conflict:'数据冲突',period_mismatch:'报告期不一致',currency_unverified:'币种待核验',unit_unverified:'单位待核验',scope_mismatch:'报表范围不一致',publication_unverified:'公告日期待核验',future_disclosure:'晚于研究截止',calculated:'仅算术可计算',insufficient:'资料不足',not_reviewed:'尚未核查',evidence_candidates:'定位到候选原文',pending_review:'待人工核查'};
  const metricLabels={known_interest_debt_subtotal:'已识别有息债务部分合计',total_interest_debt:'有息债务总额（含租赁）',interest_debt_due_within_12_months:'未来12个月到期有息债务账面额',expensed_interest_coverage:'利润对费用化融资利息的覆盖',cash_less_disclosed_restrictions:'货币资金扣已披露受限部分',net_cash_after_interest_debt:'经期限核查现金减有息债务',cash_to_12month_interest_debt:'经期限核查现金/12个月到期有息债务'};
  const ratioKeys=new Set(['expensed_interest_coverage','cash_to_12month_interest_debt']);
  const auditLabels={unqualified:'财务报表审计：无保留意见',qualified:'财务报表审计：保留意见',adverse:'财务报表审计：否定意见',disclaimer:'财务报表审计：无法表示意见',unqualified_with_emphasis:'财务报表审计：无保留意见附强调事项',unqualified_with_going_concern:'财务报表审计：无保留意见附持续经营重大不确定性',unaudited:'本期未经审计',reviewed_not_audited:'本期已审阅，未经审计',conflict:'同报告期审计信息冲突',unrecognized_requires_review:'审计表述尚未分类，需核查',not_provided:'尚未取得该期审计信息'};
  const auditConcerns=new Set(['qualified','adverse','disclaimer','unqualified_with_going_concern','conflict']);
  function el(tag,cls,value){const node=document.createElement(tag);if(cls)node.className=cls;if(value!==undefined)node.textContent=string(value);return node;}
  function raw(tag,cls,value){const node=el(tag,cls,value);node.setAttribute('data-i18n-skip','');return node;}
  function paragraph(node,value,cls='small muted'){if(value)node.append(el('p',cls,value));}
  function status(value,extra=''){const special={not_applicable_zero_interest:'费用化利息为零，覆盖倍数不适用',not_applicable_zero_debt:'到期债务为零，覆盖倍数不适用',needs_review:'待核查',incomplete:'口径未完整核查',basis_mismatch:'计量口径不一致'};return el('span','research-dg-status '+extra,states[value]||special[value]||'状态待核验');}
  function safeURL(value){try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url:null;}catch(_){return null;}}
  function exact(value,unit){const node=el('span','research-dg-value');if(!numeric(value)){node.textContent='—';return node;}node.append(raw('span','',String(value)),document.createTextNode(' '),el('span','research-dg-unit',({CNY:'人民币元',multiple:'倍',ratio:'小数比例',years:'年'})[unit]||'单位待核对'));return node;}
  function list(node,items){if(!rows(items).length)return;const ul=el('ul','research-notes');for(const item of items)ul.append(el('li','',typeof item==='object'?item.message||item.note||item.label||item.reason||string(item):item));node.append(ul);}
  function refs(node,references,sources){const list=rows(references);if(!list.length){paragraph(node,'尚无可跳转来源，数值出处仍需补齐。');return;}const box=el('div','research-dg-source');for(const reference of list){if(reference===null||reference===undefined)continue;const id=typeof reference==='string'?reference:reference.source_id||reference.document_id||reference.id;const source=id?sources.find(source=>string(source.id)===string(id))||{}:{};const entry=typeof reference==='object'?reference:{};const url=safeURL(entry.url||source.url),page=entry.page;const title=entry.title||source.title||id||'来源';const line=el('p');if(url){if(Number.isInteger(page)&&page>0)url.hash='page='+page;const link=raw('a','',title);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';line.append(link);if(Number.isInteger(page)&&page>0)line.append(el('span','',` · PDF 第 ${page} 页`));}else line.append(raw('span','',title),el('span','small muted',' · 来源链接待补齐'));box.append(line);if(entry.report_date||source.report_date||source.report_period){paragraph(box,'来源报告期');box.append(raw('p','small muted',entry.report_date||source.report_date||source.report_period));}if(entry.published_at||source.published_at){paragraph(box,'披露日期');box.append(raw('p','small muted',entry.published_at||source.published_at));}}
    node.append(box);
  }
  function evidence(node,entries,sources){if(!rows(entries).length){paragraph(node,'尚未取得这一项的原文；不能据此认定没有风险。');return;}for(const entry of entries){const box=el('div','research-dg-evidence');box.append(status('pending_review'));paragraph(box,'原文片段只完成文本匹配，主体、金额、范围和上下文仍需核查。');if(entry.quote)box.append(raw('blockquote','',entry.quote));refs(box,[entry],sources);node.append(box);}}
  function period(node,label,date){const p=el('p','small muted');p.append(el('span','',label),document.createTextNode(' '),raw('span','',date||'—'));node.append(p);}
  function makeMetric(metric,data,facts,sources){const box=el('article','research-dg-metric');box.append(el('h5','',metricLabels[metric.key]||metric.label||'财务核查项目'));const ratio=ratioKeys.has(metric.key);const allowMetric=data.applicability?.general_metrics_enabled===true;const debtRequired=['total_interest_debt','interest_debt_due_within_12_months','net_cash_after_interest_debt','cash_to_12month_interest_debt'].includes(metric.key);const cashRequired=['net_cash_after_interest_debt','cash_to_12month_interest_debt'].includes(metric.key);const scopeAllowed=allowMetric&&(!debtRequired||data.debt?.complete===true)&&(!cashRequired||data.liquidity?.complete===true);const allowed=scopeAllowed&&metric.status==='calculated'&&numeric(metric.value);const zeroDenominator=scopeAllowed&&['not_applicable_zero_interest','not_applicable_zero_debt'].includes(metric.status);box.append(exact(allowed?metric.value:null,ratio?'multiple':'CNY'),status(allowed?'calculated':zeroDenominator?metric.status:'insufficient'));
    if(metric.key==='known_interest_debt_subtotal')paragraph(box,'部分合计不是债务总额，未识别的债务仍可能存在。','research-dg-caveat');
    if(metric.key==='cash_less_disclosed_restrictions')paragraph(box,'扣除已披露受限部分后，仍不能当作随时可用现金。','research-dg-caveat');
    if(metric.note)paragraph(box,metric.note,'research-dg-caveat');
    const detail=el('details','research-dg-details');detail.append(el('summary','','查看公式、组件和数值来源'));period(detail,'计算报告期',data.report_date);paragraph(detail,'只核对算术关系，尚未独立验证来源语义。');if(metric.formula){paragraph(detail,'公式');paragraph(detail,metric.formula,'research-dg-formula');}
    for(const key of rows(metric.components)){const fact=facts.find(item=>item.key===key),line=el('div','research-dg-component');line.append(el('span','',fact?.label||metricLabels[key]||key));if(fact){line.append(exact(fact.value,fact.unit||fact.currency),status(fact.state));period(line,'报告期',fact.report_date);refs(line,fact.source_refs,sources);}else paragraph(line,'派生指标，依据见对应卡片；不重复累计其组件。');detail.append(line);}box.append(detail);return box;
  }
  function auditCard(label,record,sources){const card=el('article','research-dg-audit');card.append(el('h5','',label));if(!record){paragraph(card,'尚未取得该期审计信息，不能沿用其他期间的意见。');return card;}period(card,'报告期',record.report_date);period(card,'公告日期',record.announced_at);card.append(el('span','research-dg-status '+(auditConcerns.has(record.status)?'concern':''),auditLabels[record.status]||'审计状态待核验'));
    if(record.status==='not_reported')paragraph(card,'尚未取得该期审计信息，不能沿用其他期间的意见。');
    if(record.status==='unaudited')paragraph(card,'未经审计表示保证范围，不等于负面审计意见或发现造假。');
    if(record.status==='reviewed_not_audited')paragraph(card,'审阅与审计提供的保证程度不同，不将审阅意见称为年度审计意见。');
    if(record.raw_opinion){paragraph(card,'供应商原始审计表述');card.append(raw('p','',record.raw_opinion));}
    if(record.source==='supplied_structured_opinion'||record.verification==='supplier_only')paragraph(card,'供应商结构化记录，需核对原始财务报表审计报告。');
    if(rows(record.conflicting_opinions).length){paragraph(card,'同日冲突表述');for(const value of record.conflicting_opinions)card.append(raw('p','',value));}
    if(rows(record.source_refs).length||!rows(record.evidence).length)refs(card,record.source_refs,sources);if(rows(record.evidence).length){const original=el('details','research-dg-details');original.append(el('summary','','查看审计原文与页码'));evidence(original,record.evidence,sources);card.append(original);}return card;
  }
  function render(data,{sources=[],companyCode=null,stale=false,synthetic=false}={}){
    const root=el('section','research-detail-section research-debt-governance');root.setAttribute('aria-label','债务、流动性与治理核查');root.append(el('h3','','债务、流动性与治理核查'));
    paragraph(root,'分别核对负债期限、现金限制、审计期间和治理披露；不形成完整公司结论或买入建议。');
    if(!data){paragraph(root,'当前报告尚无债务与治理核查资料。');return root;}
    if(data.schema_version!==1){paragraph(root,'债务与治理数据版本待更新，暂不展示旧结构。','notice warning-text');return root;}
    if(companyCode&&string(data.company_code)!==string(companyCode)){paragraph(root,'资料主体与当前公司不一致，已停止展示。','notice warning-text');return root;}
    if(synthetic||/^SYNTHETIC/.test(string(data.company_code)))paragraph(root,'合成验收样本，不是真实公司事实。','notice warning-text');
    if(stale)paragraph(root,'这是旧报告中的债务与治理资料，尚未按最新数据重新核验。','notice warning-text');
    period(root,'财务报告期',data.report_date);period(root,'研究截止',data.as_of);
    if(data.applicability?.general_metrics_enabled!==true)paragraph(root,'本公司需要行业或盈利阶段专项判断，一般企业债务与覆盖指标不适用。','notice warning-text');
    const overview=el('div','research-dg-coverage');const coverage=data.coverage||{};paragraph(overview,`已提供数值 ${numeric(coverage.provided_numeric_fields)?coverage.provided_numeric_fields:'—'} / ${numeric(coverage.numeric_field_count)?coverage.numeric_field_count:'—'} 项`);paragraph(overview,'有数据或有 PDF 不等于数值语义已核验。');root.append(overview);
    const financial=el('div','research-dg-financial');for(const [key,label] of [['debt','债务与到期结构'],['liquidity','现金限制与流动性']]){const block=el('section','research-dg-panel');block.append(el('h4','',label));paragraph(block,data[key]?.complete===true?'上游已提供该项完整口径声明，仍需核对原文。':'完整口径尚未确认；只展示已取得数据与缺口。');for(const metric of rows(data[key]?.metrics))block.append(makeMetric(metric,data,rows(data.facts),rows(sources)));if(!rows(data[key]?.metrics).length)paragraph(block,'尚无可用指标。');financial.append(block);}root.append(financial);
    const original=el('details','research-dg-details');original.append(el('summary','','已取得的原始财务字段'));for(const fact of rows(data.facts)){const card=el('article','research-dg-fact');card.append(el('h5','',fact.label||fact.key),exact(fact.value,fact.unit||fact.currency),status(fact.state));if(numeric(fact.value)&&fact.value<0)paragraph(card,'这是负值，不能当作缺失或零。');period(card,'报告期',fact.report_date);period(card,'公告日期',fact.announced_at);list(card,fact.issues);refs(card,fact.source_refs,rows(sources));original.append(card);}root.append(original);
    const auditing=el('section','research-dg-panel');auditing.append(el('h4','','按报告期查看审计与审阅'));paragraph(auditing,'财务报表审计、审阅与内部控制意见分别理解；年度意见不沿用到中期。');const auditGrid=el('div','research-dg-audits');auditGrid.append(auditCard('当前报告期',data.audit?.latest_report,rows(sources)),auditCard('最近年度报告',data.audit?.latest_annual,rows(sources)));auditing.append(auditGrid);if(rows(data.audit?.history).length){const history=el('details','research-dg-details');history.append(el('summary','','历史审计期间记录'));for(const item of data.audit.history)history.append(auditCard('历史报告期',item,rows(sources)));auditing.append(history);}if(data.audit?.note)paragraph(auditing,data.audit.note);root.append(auditing);
    const governance=el('section','research-dg-panel');governance.append(el('h4','','治理披露与尚未核查事项'));paragraph(governance,'这里只整理定期报告披露；监管机关和交易所的独立公告尚未核查。','notice warning-text');paragraph(governance,'没有检索结果或没有定位到原文，都不能认定无风险。');for(const topic of rows(data.governance?.topics)){const box=el('details','research-dg-details research-dg-topic'),head=el('summary');head.append(el('span','',topic.label||topic.topic),document.createTextNode(' '),status(topic.status));box.append(head);evidence(box,topic.evidence,rows(sources));if(rows(topic.evidence).length&&topic.note)paragraph(box,topic.note);governance.append(box);}root.append(governance);
    const concerns=el('section','research-dg-panel');concerns.append(el('h4','','优先核查与资料缺口'));if(rows(data.priority_risks).length){for(const risk of data.priority_risks){const item=el('article','research-dg-priority');paragraph(item,risk.message||risk.code,'research-dg-caveat');refs(item,risk.evidence_refs,rows(sources));concerns.append(item);}}else paragraph(concerns,'尚未形成优先核查清单，不代表低风险或已排除风险。');for(const gap of rows(data.gaps)){const line=el('p');line.append(el('span','',gap.label||gap.key),document.createTextNode(' · '),status(gap.state));concerns.append(line);}list(concerns,data.limitations);root.append(concerns);return root;
  }
  window.ETFResearchDebtGovernance={render,version:'debt-governance-ui-1.0'};
})();
// END_DEBT_GOVERNANCE_UI
// BEGIN_BUSINESS_CAPITAL_UI
'use strict';
// Business and capital evidence view; data and arithmetic arrive from the server.
(() => {
  const rows=value=>Array.isArray(value)?value:[];
  const numeric=value=>typeof value==='number'&&Number.isFinite(value);
  const string=value=>value===null||value===undefined?'':typeof value==='object'?JSON.stringify(value):String(value);
  const states={reported_value:'已提供数值',reported_zero:'明确为零',null:'数值为空',not_provided:'未提供',invalid:'数值无效',metadata_invalid:'来源口径待核查',conflict:'数据冲突',calculated:'仅算术可计算',insufficient:'资料不足',specialist_required:'需要专项行业判断',nonpositive_denominator:'分母非正，不计算',negative_component_requires_review:'负支出待核查',invalid_arithmetic:'计算结果无效',review_material_only:'待核查材料',unusable_evidence:'未纳入有效材料',reported_event_only:'已披露事件，语义待核查',unusable_event:'事件口径待核查',duplicate_event_requires_review:'重复事件待核查'};
  const metrics={gross_margin:'报告毛利率',rd_expense_to_revenue:'费用化研发/营业收入',capex_to_cfo:'购建现金/经营现金流',simplified_cash_surplus:'经营现金减购建现金',gross_margin_range:'年度毛利率极差',sum_rd_expense:'窗口费用化研发合计',sum_capex_cash:'窗口购建现金合计',sum_parent_profit:'窗口归母净利润合计'};
  const eventTypes={bonus_issue:'送股',capitalization_issue:'资本公积转增',stock_split:'拆股',share_consolidation:'并股',cancellation:'股份注销',cash_equity_issue:'现金发行融资',repurchase:'股份回购',cash_dividend:'普通股现金分红',acquisition:'并购'};
  const stages={proposed:'方案提出，尚未实现',approved:'已批准，尚未实现',completed:'已披露完成'};
  const treatments={reported_non_cash_share_change:'非现金股本事件，不认定为融资',reported_cash_financing:'披露融资现金，仍需核对口径',reported_common_dividend_payment:'披露普通股现金支付',reported_acquisition_cash_or_consideration:'并购现金与对价按披露口径分别展示',reported_share_repurchase_not_necessarily_cancelled:'披露回购，不代表已注销',proposal_or_authorization_not_realized:'方案或授权，不记为实际现金支付',requires_review:'资料存在缺口，不确认事件金额',unclassified:'事件类型待核查'};
  const cashBasis={ordinary_common_dividend_paid:'普通股股东实际现金分红',net_issuance_proceeds:'发行募集现金净额',gross_issuance_proceeds:'发行募集现金总额',repurchase_cash_paid:'实际回购支付现金',net_acquisition_cash_paid:'取得子公司等支付现金净额',total_consideration:'收购总对价'};
  const topics={competitive_position:'竞争地位材料',customer_retention:'客户留存材料',competitive_position_candidate:'竞争地位关键词候选',capital_use_candidate:'资本使用关键词候选',unspecified:'主题待归类'};
  const gaps={competitive_advantage:'缺少已核验的独立竞争证据，不能判断护城河。',rd_outcomes:'研发费用不是研发总投入，缺少资本化流量和成果归因。',capex_outcomes:'购建现金未区分维持与扩张，缺少投产和回报归因。',dividend_payout:'股利、利润和利息混合现金项不能用于普通股分红率。',repurchase_issuance:'库存股和合并吸收投资不能替代实际回购、注销及发行。',per_share_results:'拆并股、送转及追溯口径未核实，不计算跨年EPS增速。',acquisition_outcomes:'收购现金不能证明整合成功，仍缺后续利润与承诺兑现证据。',customer_supplier_concentration:'客户和供应商集中度、留存及表格语境仍需正文核查。'};
  const units={CNY:'人民币元','CNY/share':'人民币元/股',HKD:'港元',USD:'美元',EUR:'欧元',GBP:'英镑',JPY:'日元',percent:'%',percentage_points:'个百分点',shares:'股'};
  function el(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=string(value);return n;}
  function raw(tag,cls,value){const n=el(tag,cls,value);n.setAttribute('data-i18n-skip','');return n;}
  function p(node,value,cls='small muted'){if(value)node.append(el('p',cls,value));}
  function field(node,label,value){const n=el('p','research-bc-meta');n.append(el('span','',label),document.createTextNode(' '),raw('span','',value===null||value===undefined||value===''?'—':value));node.append(n);}
  function state(value){return el('span','research-bc-status',states[value]||'状态待核查');}
  function exact(value,unit){const n=el('span','research-bc-value');if(!numeric(value)){n.textContent='—';return n;}n.append(raw('span','',String(value)),document.createTextNode(' '),el('span','research-bc-unit',units[unit]||'单位待核查'));return n;}
  function headline(value,unit){const n=el('span','research-bc-value');if(!numeric(value)){n.textContent='—';return n;}let divisor=1,label=units[unit]||'单位待核查';if(unit==='CNY'&&Math.abs(value)>=1e8){divisor=1e8;label='亿元';}else if(unit==='CNY'&&Math.abs(value)>=1e4){divisor=1e4;label='万元';}const rounded=Number((value/divisor).toFixed(2));n.append(raw('span','',rounded===0&&value!==0?(value/divisor).toPrecision(2):String(rounded)),document.createTextNode(' '),el('span','research-bc-unit',label));return n;}
  function detail(label,cls=''){const n=el('details','research-bc-details '+cls);n.append(el('summary','',label));return n;}
  function safeURL(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u:null;}catch(_){return null;}}
  function refs(node,references,sources,{original=false}={}){
    if(!rows(references).length){p(node,'来源链接尚待补齐。');return;}
    const box=el('div','research-bc-sources');
    for(const r of rows(references)){
      if(!r||typeof r!=='object')continue;
      const source=r.source_id?sources.find(s=>s&&string(s.id)===string(r.source_id))||{}:{};
      const direct=Object.hasOwn(r,'source_url')?r.source_url:r.url;
      const u=safeURL(direct||source.url),line=el('p');
      if(u){if(Number.isInteger(r.page)&&r.page>0)u.hash='page='+r.page;const a=el('a','','查看来源');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';line.append(a);}
      else line.append(el('span','','来源链接尚待补齐。'));
      if(r.source_id)line.append(document.createTextNode(' · '),raw('span','',r.source_id));
      box.append(line);
      if(Number.isInteger(r.page)&&r.page>0)field(box,'原文页码',r.page);
      if(r.report_date)field(box,'报告期',r.report_date);
      if(r.announced_at)field(box,'公告日期',r.announced_at);
      if(original){
        field(box,'原字段',r.raw_field);field(box,'原始输入',Object.hasOwn(r,'raw_value')?r.raw_value:'—');
        field(box,'原单位',r.raw_unit);field(box,'金额换算倍率',r.unit_factor);
        field(box,'单位来源规则',r.unit_basis);field(box,'币种',r.currency);field(box,'报表范围',r.scope);
      }
    }
    node.append(box);
  }
  function issues(node,items){if(!rows(items).length)return;const list=detail('查看待核查原因');for(const item of items)list.append(raw('p','small muted',item));node.append(list);}
  function metric(item,sources,{specialist=false,windowValid=true}={}){
    const card=el('article','research-bc-metric');card.setAttribute('data-metric-key',item.key||'');card.append(el('h5','',metrics[item.key]||'财务观察'));
    const industrial=['gross_margin','rd_expense_to_revenue','capex_to_cfo','simplified_cash_surplus','gross_margin_range'].includes(item.key);
    const allowed=item.status==='calculated'&&windowValid&&!(specialist&&industrial);
    card.append(headline(allowed?item.value:null,item.unit),state(!windowValid?'insufficient':specialist&&industrial?'specialist_required':item.status));
    const d=detail('查看公式与原始输入');p(d,'仅复算财务关系，不代表来源数字已核验。');
    if(allowed&&numeric(item.value)){p(d,'计算结果原值（未缩写）');d.append(exact(item.value,item.unit));}
    if(item.formula)d.append(raw('p','research-bc-formula',item.formula));
    field(d,'覆盖期次',rows(item.periods).join(' / '));refs(d,item.source_refs,sources,{original:true});card.append(d);return card;
  }
  function evidenceCard(item,sources){
    const card=el('article','research-bc-evidence');card.setAttribute('data-evidence-id',item.id||'');
    card.append(el('h5','',topics[item.topic]||'待核查证据主题'),state(item.status));
    if(!topics[item.topic])field(card,'原始主题标签',item.topic);
    field(card,'材料报告期',item.report_date);field(card,'材料公告日期',item.announced_at);
    p(card,'原文尚未自动匹配来源，主体、上下文和数值语义仍待核查。');
    refs(card,[item.source_ref||{}],sources);
    const d=detail('展开原文（保留原语言）','research-bc-quote');
    if(typeof item.text==='string'&&item.text.trim())d.append(raw('blockquote','',item.text));else p(d,'尚无可审阅原文。');
    card.append(d);issues(card,item.issues);return card;
  }
  function evidenceGroups(data,sources){
    const section=el('section','research-bc-panel');section.append(el('h4','','竞争证据：自述、独立材料与反证'));
    p(section,'毛利率、研发费用和EPS不能自动证明护城河；独立来源标签本身也未获外部核验。','research-bc-caveat');
    p(section,'反证按材料立场分类，可能同时出现在来源组；重复显示不增加证据强度。');
    const all=rows(data.evidence),groups=data.evidence_groups||{},shown=new Set();
    const count=id=>all.filter(x=>string(x.id)===string(id)).length;
    for(const [key,label] of [['company_claims','企业自述'],['independent_material','独立来源待核查材料'],['counterevidence','反证与质疑材料']]){
      const block=el('section','research-bc-evidence-group');block.setAttribute('data-evidence-group',key);block.append(el('h5','',label));
      const ids=new Set(rows(groups[key]).map(string));
      const material=all.filter(x=>ids.has(string(x.id))&&count(x.id)===1&&x.status==='review_material_only'&&typeof x.text==='string'&&x.text.trim()&&(key==='company_claims'?x.origin==='issuer_disclosure':key==='independent_material'?x.origin==='independent_material':x.perspective==='challenge'));
      if(!material.length)p(block,'尚无符合本组条件的材料，不能据此给高分或排除风险。');
      for(const item of material){shown.add(item.id);block.append(evidenceCard(item,sources));}section.append(block);
    }
    const other=all.filter(x=>!shown.has(x.id));
    if(other.length){const d=detail('待归类与未纳入的材料','research-bc-rejected');for(const item of other)d.append(evidenceCard(item,sources));section.append(d);}
    return section;
  }
  function eventCard(item,sources){
    const card=el('article','research-bc-event');card.setAttribute('data-event-id',item.id||'');card.append(el('h5','',eventTypes[item.event_type]||'资本事件待归类'),state(item.status));
    const noncash=['bonus_issue','capitalization_issue','stock_split','share_consolidation','cancellation'].includes(item.event_type);
    const valid=item.status==='reported_event_only'&&item.event_stage==='completed'&&typeof item.text==='string'&&item.text.trim();
    p(card,item.event_stage==='completed'&&!valid?'完成状态待核查':stages[item.event_stage]||'事件阶段待核查');
    p(card,item.event_stage!=='completed'?'方案或授权，不记为实际现金支付':treatments[item.treatment]||'资料存在缺口，不确认事件金额','research-bc-caveat');
    if(noncash)p(card,'股数增加不等于现金融资，未评估稀释或每股价值影响。','research-bc-caveat');
    field(card,item.event_stage==='completed'?'披露发生日期':'方案所列日期（未确认发生）',item.event_date);field(card,'经济归属年度',item.event_stage==='completed'?item.economic_annual_period:null);field(card,'方案对应年度',item.scheme_fiscal_year);
    field(card,'来源报告期',item.report_date);field(card,'公告日期',item.announced_at);
    if(item.subsequent_to_report_period===true)p(card,'这是报告期后的事件，不回填为报告期内已实现。');
    if(item.in_fixed_annual_window!==true)p(card,'未计入当前固定年度窗口。');
    if(noncash)p(card,'该事件为非现金股本变化，不适用现金支付金额。');
    else {p(card,'披露现金口径');p(card,cashBasis[item.cash_basis]||'没有可确认的现金口径');}
    const bases={cash_dividend:['ordinary_common_dividend_paid'],cash_equity_issue:['net_issuance_proceeds','gross_issuance_proceeds'],repurchase:['repurchase_cash_paid'],acquisition:['net_acquisition_cash_paid','total_consideration']};
    const cashAllowed=valid&&!noncash&&item.cash_unit==='currency_units'&&['CNY','HKD','USD','EUR','GBP','JPY'].includes(item.currency)&&rows(bases[item.event_type]).includes(item.cash_basis);
    const cash=el('div','research-bc-event-cash');cash.append(exact(cashAllowed?item.reported_cash_value:null,item.currency));card.append(cash);
    if(item.event_type==='acquisition')p(card,'净现金支付与总对价不能合并；金额不代表收购成功。','research-bc-caveat');
    const d=detail('查看股数、原文和口径');
    field(d,'披露事件前股数',item.reported_shares_before);field(d,'披露事件后股数',item.reported_shares_after);
    const change=el('p','research-bc-share-change');change.append(el('span','','披露股数差额'),document.createTextNode(' '),exact(valid&&(noncash||item.event_type==='cash_equity_issue')&&item.shares_unit==='shares'?item.reported_share_change:null,'shares'));d.append(change);
    if(item.share_change_formula)d.append(raw('p','research-bc-formula',item.share_change_formula));
    p(d,'原文尚未自动匹配来源，主体、上下文和数值语义仍待核查。');
    if(typeof item.text==='string'&&item.text.trim())d.append(raw('blockquote','',item.text));else p(d,'尚无可审阅原文。');
    card.append(d);refs(card,[item.source_ref||{}],sources);issues(card,item.issues);return card;
  }
  function render(data,{sources=[],companyCode=null,stale=false,synthetic=false}={}){
    sources=rows(sources);const root=el('section','research-detail-section research-business-capital');root.setAttribute('aria-label','生意与资本使用观察');root.append(el('h3','','生意与资本使用观察'));
    p(root,'展示固定3年、5年的经营与资金使用事实，以及待核查证据；不形成护城河、资本配置评分或买卖建议。');
    if(!data){p(root,'当前报告尚无生意与资本使用资料。');return root;}
    if(data.version!=='business-capital-1.0'){p(root,'生意与资本数据版本待更新，暂不展示旧结构。','notice warning-text');return root;}
    if(companyCode&&string(data.code)!==string(companyCode)){p(root,'资料主体与当前公司不一致，已停止展示。','notice warning-text');return root;}
    if(synthetic)p(root,'合成验收样本，不是真实公司事实。','notice warning-text');
    if(stale)p(root,'这是旧报告中的经营与资本资料，尚未按最新数据重新核验。','notice warning-text');
    field(root,'研究截止',data.as_of);field(root,'固定年度末年',data.anchor_year);
    p(root,'来源和元数据匹配不等于官方逐值验证；本模块尚未完成官方逐值核验。','research-bc-caveat');
    p(root,'竞争优势：证据不足，尚未形成判断。');p(root,'资本配置质量：证据不足，尚未形成判断。');
    const specialist=data.status==='specialist_required';if(specialist)p(root,'本公司需要行业专项分析，普通企业效率指标不适用。','notice warning-text');
    if(data.data_recovery){p(root,data.data_recovery.status==='recovered'?'已从通过文件哈希检查的本地缓存整理，尚未完成原文数字核验。':'本地缓存恢复不完整或不可用，缺失资料不自动补零。');}
    const windows=el('div','research-bc-windows');
    for(const width of [3,5]){
      const found=rows(data.windows).filter(w=>w.years===width),w=found.length===1?found[0]:{};
      const expected=Number.isInteger(data.anchor_year)?Array.from({length:width},(_,i)=>`${data.anchor_year-width+1+i}-12-31`):[];
      const valid=expected.length===width&&JSON.stringify(rows(w.periods))===JSON.stringify(expected);
      const card=el('section','research-bc-panel research-bc-window');card.setAttribute('data-window',width);card.append(el('h4','',width===3?'最近3个固定年度':'最近5个固定年度'));
      field(card,'覆盖期次',rows(w.periods).join(' / '));
      p(card,'缺年保留缺口，不用更早年度补位，也不把季报年化。');
      if(!valid)p(card,'固定窗口期次不完整或不一致，暂不显示窗口数值。','research-bc-caveat');
      for(const item of rows(w.metrics))card.append(metric(item,sources,{specialist,windowValid:valid}));
      p(card,'毛利率极差只描述区间波动，支出规模不等于投资回报。');windows.append(card);
    }root.append(windows);
    const annual=detail('逐年经营观察与原始财务输入','research-bc-years');
    for(const year of rows(data.years)){
      const card=detail(string(year.report_date),'research-bc-year');const grid=el('div','research-bc-year-metrics');
      for(const item of rows(year.metrics))grid.append(metric(item,sources,{specialist}));card.append(grid);
      const original=detail('已取得的原始财务字段');
      for(const f of Object.values(year.fields||{})){
        if(!f||typeof f!=='object')continue;
        const c=el('article','research-bc-field');c.setAttribute('data-field-key',f.key||'');c.append(el('h5','',f.label||'原始财务字段'),exact(['reported_value','reported_zero'].includes(f.status)?f.value:null,f.unit),state(f.status));
        field(c,'报告期',f.report_date||year.report_date);field(c,'公告日期',f.announced_at);refs(c,f.source_refs,sources,{original:true});issues(c,f.issues);
        if(rows(f.superseded_source_refs).length){const old=detail('被后续版本替代的来源（不计入本次值）');refs(old,f.superseded_source_refs,sources,{original:true});c.append(old);}original.append(c);
      }card.append(original);annual.append(card);
    }root.append(annual,evidenceGroups(data,sources));
    const events=el('section','research-bc-panel');events.append(el('h4','','股本、分红、融资与并购事件'));
    p(events,'区分方案、完成日期和现金口径；不从股本金额变化推断融资，也不把混合派息项当普通股分红。');
    if(!rows(data.capital_events).length)p(events,'尚无可用结构化事件；财报字段变化不能自动补成资本事件。');
    for(const item of rows(data.capital_events))events.append(eventCard(item,sources));root.append(events);
    const missing=el('section','research-bc-panel');missing.append(el('h4','','尚待补齐的证据与范围'));
    const grouped=new Map();for(const gap of rows(data.gaps)){const key=string(gap.key)||'unspecified';grouped.set(key,(grouped.get(key)||0)+1);}
    const recoveryLabels={'source_recovery:document_subject_time_or_text_unbound':'部分原文尚未与公司、披露时间或完整文本对应，需要核对来源。','source_recovery:saved_document_hash_not_frozen':'部分旧文档缺少保存时的文件校验记录，需要重新核对来源。'};
    const identifiers=detail('查看资料缺口明细');let extra=0;
    for(const [key,count] of grouped){const label=gaps[key]||recoveryLabels[key]||'另有资料缺口，需要补齐来源后核查。';p(missing,label);if(count>1)field(missing,'涉及记录数',count);if(!gaps[key]){field(identifiers,'缺口标识',key);field(identifiers,'涉及记录数',count);extra++;}}
    if(extra)missing.append(identifiers);
    p(missing,'缺少资料不能给高分；企业自述、独立材料和反证仍需分别核查。');
    p(missing,'固定年度数字的公告筛选不代表已完成严格历史时点验证。');
    if(rows(data.excluded_records).length){const excluded=detail('未纳入本次计算的记录');for(const r of data.excluded_records){field(excluded,'未纳入原因',r.reason);if(r.report_date)field(excluded,'报告期',r.report_date);}missing.append(excluded);}
    root.append(missing);return root;
  }
  window.ETFResearchBusinessCapital={render,version:'business-capital-ui-1.0'};
})();
// END_BUSINESS_CAPITAL_UI
// BEGIN_PRICE_QUALITY_UI
'use strict';
// Isolated view only. Values and eligibility come from the reviewed price-quality contract.
(() => {
  const list=x=>Array.isArray(x)?x:[],obj=x=>x&&typeof x==='object'&&!Array.isArray(x)?x:{};
  const text=x=>x===null||x===undefined?'':typeof x==='object'?JSON.stringify(x):String(x);
  const decimal=x=>typeof x==='string'&&/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(x)||typeof x==='number'&&Number.isFinite(x);
  const positive=x=>decimal(x)&&!String(x).startsWith('-')&&/[1-9]/.test(String(x));
  const titles={financial_persistence:'多年财务持续性',debt_liquidity:'债务与流动性',governance:'治理与审计',competitive_position:'竞争地位证据',capital_use:'资本使用证据',industry_applicability:'行业适用性',refresh_price:'核对报价',review_comparable_peers:'核对同行口径'};
  const statuses={reported_value:'供应商已提供',zero:'明确为零',null:'数值为空',absent:'未提供',invalid:'数值无效',not_provided:'未提供',conflict:'数据冲突',calculated:'仅算术可计算',insufficient:'资料不足',not_assessed:'尚未评估',module_output_present:'模块资料已接入',module_missing_or_unusable:'模块缺失或不可用',partial:'部分资料，研究未完成',pending:'待补证据',observed_under_calendar_policy:'自然日窗口内已观察',conditional_reference_available:'条件参考可用',risk_review_required:'优先风险待核查',specialist_or_identity_review_required:'行业专项或主体待核查',evidence_incomplete:'证据待补',high_priority_review:'存在高优先级待核查风险',review_pending:'风险待核查',not_cleared:'尚未排除风险',recent_by_calendar_policy:'报价在自然日参考窗口内',unavailable:'当前不可用',unaudited:'未经审计',reviewed_not_audited:'已审阅，未经审计',unqualified:'无保留审计意见',not_reviewed:'尚未核查',general:'一般企业',bank:'银行专项',insurance:'保险专项',securities:'证券专项',property:'地产专项',cyclical:'周期行业专项',unknown:'行业未知',positive:'已提供正盈利口径',loss_making:'非正盈利',high:'高优先级',medium:'中优先级',low:'低优先级'};
  const coveredLabels={provided_numeric_fields:'已提供数值字段数',numeric_field_count:'字段总数',debt_scope_complete:'债务范围完整',liquidity_scope_complete:'现金范围完整',latest_audit_status:'最新报告鉴证状态',annual_audit_status:'年度报告鉴证状态',authority_announcements:'监管独立公告',company_claims:'公司自述条数',independent_material:'独立待核查材料条数',counterevidence:'反证条数',reported_events:'元数据可用事件数（含方案）',window_count:'固定窗口数',model:'行业模型',earnings_status:'盈利适用状态'};
  const unitLabels={CNY:'人民币元',HKD:'港元',USD:'美元',times:'倍',relative:'原始比值'};
  statuses.reported_zero='明确为零';
  statuses.supplier_reference_available_rebuild_pending='供应商参考可用，完整分母待复算';
  function el(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=text(value);return n;}
  function raw(tag,cls,value){const n=el(tag,cls,value);n.setAttribute('data-i18n-skip','');return n;}
  function p(n,value,cls='small muted'){if(value)n.append(el('p',cls,value));}
  function meta(n,label,value,{original=true}={}){const line=el('p','research-pq-meta');line.append(el('span','',label),document.createTextNode(' '),(original?raw:el)('span','',value===null||value===undefined||value===''?'—':value));n.append(line);}
  function state(value){return el('span','research-pq-status',statuses[value]||'状态仍需核查');}
  function exact(value,unit){
    const n=el('span','research-pq-value');if(!decimal(value)){n.textContent='—';return n;}
    let display=text(value),label=unitLabels[unit]||'单位待核查',number=Number(value);
    // Display rounding only; the exact source string is always retained below.
    if(unit&&Number.isFinite(number)){
      if(unit==='relative'){number*=100;label='%';}
      else if(['CNY','HKD','USD'].includes(unit)&&Math.abs(number)>=1e8){number/=1e8;label={CNY:'亿元人民币',HKD:'亿港元',USD:'亿美元'}[unit];}
      else if(['CNY','HKD','USD'].includes(unit)&&Math.abs(number)>=1e4){number/=1e4;label={CNY:'万元人民币',HKD:'万港元',USD:'万美元'}[unit];}
      display=number.toLocaleString('en-US',{maximumFractionDigits:2,useGrouping:false});
    }
    n.append(raw('span','',display));if(unit)n.append(document.createTextNode(' '),el('span','research-pq-unit',label));
    if(display!==text(value)||label!==(unitLabels[unit]||'单位待核查')){const d=detail('查看完整原值','research-pq-exact');d.append(raw('span','',value));if(unit)d.append(document.createTextNode(' '),el('span','research-pq-unit',unitLabels[unit]||'单位待核查'));n.append(d);}
    return n;
  }
  function detail(label,cls=''){const n=el('details','research-pq-details '+cls);n.append(el('summary','',label));return n;}
  function safeURL(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u:null;}catch(_){return null;}}
  function refs(n,refs,sources){
    const seen=new Set();
    for(const r of list(refs)){
      const x=obj(r),source=x.source_id?sources.find(s=>s&&text(s.id)===text(x.source_id))||{}:{};
      const u=safeURL(x.source_url||x.url||source.url),line=el('p','research-pq-source');
      const key=JSON.stringify([x.source_id||'',u?u.href:'',Number.isInteger(x.page)?x.page:null]);if(seen.has(key))continue;seen.add(key);
      if(u){if(Number.isInteger(x.page)&&x.page>0)u.hash='page='+x.page;const a=el('a','','查看来源');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';line.append(a);}else line.append(el('span','','来源链接尚待补齐。'));
      if(x.source_id)line.append(document.createTextNode(' · '),raw('span','',x.source_id));n.append(line);
    }
  }
  function originals(n,refs){const d=detail('展开原字段与来源口径','research-pq-originals');for(const r of list(refs)){const x=obj(r);for(const [k,label] of [['raw_field','原字段'],['field','原字段'],['raw_value','原始输入'],['value','来源数值'],['raw_unit','原单位'],['currency','币种'],['scope','报表范围'],['report_date','报告期'],['announced_at','公告日期'],['valuation_as_of','实际报价日'],['period_start','期间起点'],['period_end','期间终点'],['unit_factor','金额倍率'],['source_id','来源编号']])if(Object.hasOwn(x,k))meta(d,label,x[k]);}n.append(d);}
  function issues(n,items,label='查看尚缺的口径'){if(!list(items).length)return;const d=detail(label,'research-pq-issues');for(const x of items)d.append(raw('p','small muted',x));n.append(d);}
  function observation(n,item,unit,sources){const x=obj(item),available=['reported_value','zero'].includes(x.state);n.append(exact(available?x.value:null,unit),state(x.state));refs(n,[obj(x.source_ref)],sources);originals(n,[obj(x.source_ref)]);}
  function comparison(item,{supplier,gate,fresh,minimum,sources}){
    const x=obj(item),card=el('article','research-pq-comparison');card.setAttribute('data-comparison-key',x.key||'');
    card.append(el('h5','',x.key==='pe_ttm'?'供应商市盈率 PE TTM':x.key==='pb'?'供应商市净率 PB':'比率待归类'));
    observation(card,x.observed,'times',sources);
    const allowed=gate&&fresh&&x.status===(supplier?'supplier_peer_reference':'conditional_peer_reference')&&Number.isInteger(x.comparable_peers)&&x.comparable_peers>=minimum&&list(x.issues).length===0&&positive(obj(x.observed).value)&&positive(x.peer_median)&&decimal(x.relative_to_median);
    const summary=el('div','research-pq-relative');summary.setAttribute('data-reference-available',allowed?'true':'false');
    p(summary,allowed?(supplier?'供应商同行参考可用，完整分母仍需核查':'完整口径层条件参考，不是价值结论'):'口径或适用条件未满足，暂不显示相对位置');
    meta(summary,'纳入同行数',x.comparable_peers);p(summary,'同行中位数');summary.append(exact(allowed?x.peer_median:null,'times'));
    p(summary,'相对同行中位数的差幅');summary.append(exact(allowed?x.relative_to_median:null,'relative'));
    const relations={below_peer_median:'低于该样本中位数，不代表低估',equal_peer_median:'等于该样本中位数，不代表合理价值',above_peer_median:'高于该样本中位数，不代表高估'};
    if(allowed)p(summary,relations[x.relation]||'相对位置尚未确认');card.append(summary);
    p(card,supplier?'仅同供应商原始比率匹配；未认证每家会计政策或普通股分母。':'独立完整口径要求仍单列，供应商参考不会补齐这些缺口。','research-pq-caveat');
    p(card,'样本数量达标不证明业务或周期相同；中位数不是目标价或买入条件。','research-pq-caveat');
    issues(card,x.issues);issues(card,x.limits,'查看参考限制');
    const peers=detail('查看纳入与排除的同行','research-pq-peers');
    for(const [key,label] of [['included_peers','纳入样本'],['excluded_peers','排除样本']]){p(peers,label);for(const peer of list(x[key])){const row=el('article','research-pq-peer');meta(row,'公司代码',peer.company_code);row.append(exact(peer.value,'times'));refs(row,peer.source_ref?[peer.source_ref]:[],sources);issues(row,peer.reasons,'查看排除原因');peers.append(row);}}
    card.append(peers);return card;
  }
  function diagnostics(data,condition,sources){
    const d=obj(condition.recalculation_diagnostics),section=el('section','research-pq-panel research-pq-diagnostics');section.append(el('h4','','复算诊断与权益候选'));
    p(section,'数值吻合仅表示供应商缓存的算术一致；不认证普通股权益完整，也不解除行业门禁。','research-pq-caveat');
    if(!Object.keys(d).length){p(section,'尚无可用复算资料；缺失值不补零。');return section;}
    const valid=d.status==='numeric_consistency_only',ttm=obj(d.ttm_profit),card=el('article','research-pq-diagnostic');card.setAttribute('data-diagnostic','ttm_profit');card.append(el('h5','','归母利润 TTM 复算诊断'));
    meta(card,'期间起点',ttm.period_start);meta(card,'期间终点',ttm.period_end);card.append(exact(valid&&ttm.status==='calculated'?ttm.value:null,obj(condition.reference_basis).financial_currency),state(ttm.status));
    p(card,'复算比率');card.append(exact(valid&&ttm.status==='calculated'?ttm.ratio:null,'times'));p(card,ttm.matches_supplier===true&&valid?'在供应商匹配容差内，语义仍未核验':ttm.matches_supplier===false&&valid?'数值未在供应商匹配容差内':'数值匹配尚不能判断');
    const trefs=list(ttm.source_refs).concat(list(ttm.components).flatMap(c=>list(obj(c.fact).source_refs)));refs(card,trefs,sources);
    const components=detail('展开 TTM 组成，不以半年利润乘二');for(const c of list(ttm.components)){const f=obj(c.fact),row=el('article');meta(row,'算术符号',c.operation);row.append(exact(f.value,obj(condition.reference_basis).financial_currency),state(f.status));originals(row,f.source_refs);components.append(row);}card.append(components);section.append(card);
    for(const candidate of list(d.pb_candidates)){
      const c=obj(candidate),row=el('article','research-pq-diagnostic');row.setAttribute('data-pb-basis',c.basis||'');
      const labels={reported_parent_equity:'披露归母权益候选',parent_equity_less_reported_other_equity_total_once:'归母权益减其他权益总项一次的候选'};row.append(el('h5','',labels[c.basis]||'权益口径候选待归类'));
      p(row,'候选权益金额');row.append(exact(valid?c.value:null,obj(condition.reference_basis).financial_currency));p(row,'复算比率');row.append(exact(valid?c.ratio:null,'times'));
      p(row,c.matches_supplier===true&&valid?'在供应商匹配容差内，语义仍未核验':c.matches_supplier===false&&valid?'数值未在供应商匹配容差内':'数值匹配尚不能判断');
      p(row,'这不是已认证的普通股权益；优先股和永续债可能已含在其他权益总项内，不重复扣除。','research-pq-caveat');refs(row,c.source_refs,sources);originals(row,c.source_refs);issues(row,c.limits,'查看候选限制');section.append(row);
    }
    if(d.market_cap_source){p(section,'复算使用的市值');section.append(exact(valid?d.market_cap:null,obj(condition.reference_basis).quote_currency));refs(section,[d.market_cap_source],sources);originals(section,[d.market_cap_source]);}
    issues(section,d.gaps);issues(section,d.limits,'查看诊断限制');return section;
  }
  function dimension(d){const card=el('article','research-pq-dimension');card.setAttribute('data-quality-dimension',d.key||'');card.append(el('h5','',titles[d.key]||'质量资料维度'),state(d.implementation_status));p(card,d.implementation_status==='module_output_present'?'部分资料，研究未完成':'模块缺失或不可用');
    const covered=obj(d.covered);for(const [key,label] of Object.entries(coveredLabels))if(Object.hasOwn(covered,key)){const value=covered[key];meta(card,label,typeof value==='boolean'?(value?'范围已声明完整，仍待核验':'范围尚未完整'):statuses[value]||value,{original:typeof value!=='boolean'&&!statuses[value]});}
    for(const w of list(covered.windows)){const row=el('div','research-pq-window');row.append(el('span','',w.years===3?'固定三年窗口':w.years===5?'固定五年窗口':'期次待核查'));meta(row,'已覆盖年度数',w.complete_years);meta(row,'固定期次',list(w.periods).join(' / '));p(row,w.complete===true?'年度槽位齐全，不代表研究完成':'年度槽位存在缺口');card.append(row);}
    issues(card,d.gaps);issues(card,d.next_evidence,'下一步所需证据');return card;
  }
  function render(input,{companyCode=null,sources=[],stale=false,synthetic=false}={}){
    const root=el('section','research-detail-section research-price-quality');root.setAttribute('aria-label','公司质量与价格参考');root.append(el('h3','','公司质量与价格参考'));
    p(root,'质量证据、供应商价格参考和复算缺口分别展示；不生成综合分、目标价或买卖建议。');
    if(!input){p(root,'当前报告尚无价格与综合证据资料。');return root;}const data=obj(input);sources=list(sources);
    if(data.version!=='price-quality-1.0'){p(root,'价格证据版本待更新，暂不展示旧结构。');return root;}
    if(companyCode&&text(data.company_code)!==text(companyCode)){p(root,'资料主体与当前公司不一致，已停止展示。');return root;}
    if(synthetic)p(root,'合成验收样本，不是真实公司事实。','notice warning-text');if(stale)p(root,'这是旧报告资料，尚未按最新信息重新核验。','notice warning-text');
    meta(root,'研究截止',data.as_of);p(root,data.research_purpose==='current_research'?'当前研究快照，不能用于证明历史可得信息。':'按声明截止筛选，仍未认证严格历史时点可用。');
    const context=obj(data.current_industry_context),hasContext=Object.keys(context).length>0;
    const contextValid=context.version==='price-industry-context-1.0'&&context.company_code===data.company_code&&context.historical_pit_usable===false&&context.modifies_saved_report===false&&context.use==='current_price_applicability_only';
    if(hasContext){
      const card=el('section','research-pq-panel research-pq-current-industry');card.append(el('h4','','当前行业资料与原报告日期'));
      const currentProfile=obj(context.profile),previous=obj(context.previous_report);
      if(contextValid&&context.status==='available'){
        meta(card,'当前行业资料',statuses[obj(currentProfile.classification).model]||'行业未知',{original:false});
        meta(card,'当前适用性评估日',context.classification_as_of);meta(card,'来源观察时间',context.observed_at);
        refs(card,[obj(context.source_ref)],sources);
      }else p(card,'当前行业来源不足，今日价格适用性待核查。','notice warning-text');
      meta(card,'原报告截止',context.financial_as_of);meta(card,'原报告行业状态',statuses[previous.model]||'行业未知',{original:false});
      p(card,'当前资料仅用于本页价格适用性和行业维度，不追溯补齐原报告，也不改变旧评分、AI或财务日期。','research-pq-caveat');
      issues(card,context.gaps,'查看来源缺口');root.append(card);
    }
    p(root,'模块已接入不等于公司质量已确认；本面板尚未完成官方逐值核验。','research-pq-caveat');root.append(state(obj(data.company_quality).status));
    const industryDimensions=list(data.quality_dimensions).filter(d=>d.key==='industry_applicability');
    const model=industryDimensions.length===1?obj(industryDimensions[0].covered):{};
    const currentGate=!hasContext||(contextValid&&context.status==='available'&&obj(obj(context.profile).classification).model==='general'&&obj(context.profile).earnings_status==='positive');
    const gate=data.ordinary_ranking_allowed_by_industry_profile===true&&model.model==='general'&&model.earnings_status==='positive'&&currentGate;
    if(!gate)p(root,'行业或盈利门禁关闭；保留原始比率与复算资料，不开放普通企业相对判断。','notice warning-text');
    const quality=el('div','research-pq-dimensions');for(const key of ['financial_persistence','debt_liquidity','governance','competitive_position','capital_use','industry_applicability']){const found=list(data.quality_dimensions).filter(x=>x.key===key);quality.append(dimension(found.length===1?found[0]:{key}));}root.append(quality);
    const condition=obj(data.price_condition),fresh=obj(condition.freshness),quote=el('section','research-pq-panel');quote.append(el('h4','','报价参考与时间'));
    meta(quote,'实际报价日',fresh.quote_date);meta(quote,'抓取时间',fresh.observed_at);meta(quote,'相距自然日数',fresh.calendar_age_days);quote.append(state(fresh.status));observation(quote,condition.reference_price,obj(condition.reference_basis).quote_currency,sources);
    p(quote,'抓取时间不替代实际报价日；自然日阈值不代表交易日历认证。','research-pq-caveat');issues(quote,fresh.issues);root.append(quote);
    const options={gate,fresh:fresh.status==='recent_by_calendar_policy'&&list(fresh.issues).length===0,minimum:Number.isInteger(obj(data.policy).minimum_comparable_peers)?Math.max(5,data.policy.minimum_comparable_peers):5,sources};
    for(const [key,label,supplier] of [['supplier_comparisons','供应商比率参考',true],['comparisons','完整口径的独立比较',false]]){const section=el('section','research-pq-panel');section.setAttribute('data-comparison-layer',key);section.append(el('h4','',label));if(!list(condition[key]).length)p(section,'尚无该层参考资料。');const grid=el('div','research-pq-comparisons');for(const c of list(condition[key]))grid.append(comparison(c,{...options,supplier}));section.append(grid);root.append(section);}root.append(diagnostics(data,condition,sources));
    const risk=obj(data.risk_state),risks=el('section','research-pq-panel');risks.append(el('h4','','风险仍需核查'),state(risk.status));p(risks,'未列出风险不表示没有风险；较低倍数不能抵消高优先级风险。','research-pq-caveat');for(const item of list(risk.items)){const row=el('article','research-pq-risk');row.append(state(item.level));if(item.message)row.append(raw('p','',item.message));meta(row,'原风险来源',item.origin);p(row,'这是待核查线索，不在此认定违规事实。');risks.append(row);}root.append(risks);
    const triggers={new_disclosure_or_verified_material:'有新公告或补齐核实资料时',new_quote_or_age_limit:'行情更新或现有报价过期时',new_earnings_equity_or_peer_basis:'盈利、权益或同行资料更新时'};
    const tasks=el('section','research-pq-panel');tasks.append(el('h4','','后续观察清单'));p(tasks,'观察项是资料任务，不是交易指令，也不会自动发起付费研究。');for(const task of list(data.observation_checklist)){const row=el('article','research-pq-task');row.setAttribute('data-observation-id',task.id||'');row.append(el('h5','',titles[text(task.id).replace(/^review_/,'')]||titles[task.id]||'资料观察项'),state(task.state));meta(row,'何时更新',triggers[task.trigger]||'更新条件待核查',{original:false});issues(row,task.requirements,'所需资料（保留原文）');tasks.append(row);}root.append(tasks);
    const legacy=detail('原六项初筛记录（未重算）','research-pq-legacy');p(legacy,'仅保留原记录参考；不是本面板的公司质量总分，也不绕过当前行业门禁。');legacy.append(raw('pre','',JSON.stringify(obj(data.legacy_screen),null,2)));root.append(legacy);
    issues(root,data.assumptions,'查看假设');issues(root,data.limits,'查看面板范围');return root;
  }
  window.ETFResearchPriceQuality={render,version:'price-quality-ui-1.0'};
})();
// END_PRICE_QUALITY_UI
'use strict';
// Company research is read-only with respect to every trading account.
(() => {
  const host=window.ETFResearchHost,$=id=>document.getElementById(id);
  if(!host||!$('page-research'))return;
  const terminal=new Set(['succeeded','partial','failed','cancelled','interrupted']);
  const providerDefaults={deepseek:{provider:'openai_compatible',base_url:'https://api.deepseek.com/v1',model:'deepseek-v4-pro'},openai:{provider:'openai',base_url:'https://api.openai.com/v1',model:'gpt-5.4-mini'}};
  const statusNames={queued:'排队中',running:'正在运行',succeeded:'已完成',partial:'部分完成',failed:'未完成',cancelled:'已停止',interrupted:'运行已中断',idle:'等待扫描'};
  const fieldNames={revenue:'营业收入',net_profit:'合并净利润',parent_profit:'归母净利润',adjusted_profit:'扣非归母净利润',op_cashflow:'经营现金流',roe:'净资产收益率',gross_margin:'毛利率',debt_ratio:'资产负债率',revenue_yoy:'收入同比',profit_yoy:'利润同比',total_assets:'总资产',total_liabilities:'总负债',announced_at:'公告日期',report_date:'报告期',cash_conversion:'利润现金含量',recurring_profit:'扣非盈利占比',net_margin:'合并净利率',npl_ratio:'不良贷款率',provision_coverage:'拨备覆盖率',capital_adequacy:'资本充足率',net_interest_margin:'净息差',core_solvency:'核心偿付能力',comprehensive_solvency:'综合偿付能力',nbv_growth:'新业务价值增速',investment_yield:'投资收益率',restricted_cash:'受限现金',short_debt:'短期有息债务',contract_liabilities:'合同负债',inventory_impairment:'存货减值',net_capital:'净资本',risk_coverage:'风险覆盖率',liquidity_coverage:'流动性覆盖率',cash:'货币资金',interest_debt:'有息债务',capex:'资本开支'};
  const state={active:false,epoch:0,timer:null,summaryRequest:0,listRequest:0,detailRequest:0,summary:null,rows:[],total:0,signature:null,detailCode:null,detail:null,job:null,settingsDirty:false,settingsRevision:0,saving:false,scanSubmitting:false,queryTimer:null,refreshing:false,refreshCycle:null,moreLoading:false,listMode:'all',libraryTotal:null,libraryRequest:0,librarySignature:null,libraryIndustries:[]};
  const n=value=>value===null||value===undefined||value===''?null:Number.isFinite(Number(value))?Number(value):null;
  const arr=value=>Array.isArray(value)?value:[];
  const fmt=value=>n(value)===null?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:1});
  const ratio=value=>n(value)===null?'—':`${fmt(Number(value)*100)}%`;
  const time=value=>!value?'尚无记录':/[TZ]|[+-]\d\d:\d\d$/.test(String(value))&&Number.isFinite(new Date(value).valueOf())?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value)):String(value).slice(0,19);
  const text=value=>value===null||value===undefined?'':typeof value==='object'?JSON.stringify(value):String(value);
  function el(tag,className,value){const node=document.createElement(tag);if(className)node.className=className;if(value!==undefined)node.textContent=text(value);return node;}
  function raw(tag,className,value){const node=el(tag,className,value);node.setAttribute('data-i18n-skip','');return node;}
  function replace(node,...children){node.replaceChildren(...children.filter(Boolean));}
  function message(error){return error instanceof Error?error.message:text(error);}
  function error(error){$('research-error').textContent=message(error);$('research-error').hidden=false;}
  function button(label,handler,className='button secondary small-button'){const node=el('button',className,label);node.type='button';node.addEventListener('click',()=>Promise.resolve().then(handler).catch(error));return node;}
  function empty(title,description){const node=el('div','panel empty-state research-empty');node.append(el('span','empty-symbol','◇'),el('h3','',title),el('p','',description));return node;}
  function running(job){return !!job?.id&&!terminal.has(job.status)&&['queued','running','cancelling'].includes(job.status);}
  function safeURL(value){try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch(_){return null;}}
  function scoreOf(company){const screen=company?.screen||company||{},score=n(screen.quality_score);if(score===null||score<0||score>100||['missing','insufficient','incomplete','unavailable','unsupported','error','failed','pending','not_applicable'].includes(screen.status)||screen.assessable===false||screen.industry_applicability?.general_ranking_allowed===false)return null;return score;}
  function riskOf(company){const screen=company?.screen||company||{};return screen.risk_level||'unknown';}
  function riskText(value){return ({low:'较低',medium:'中等',high:'较高',critical:'高风险',unknown:'待核实',unavailable:'待核实'})[value]||text(value)||'待核实';}
  function shortMoney(value){const number=n(value);if(number===null)return '—';const magnitude=Math.abs(number);return magnitude>=1e8?`${(number/1e8).toLocaleString('zh-CN',{maximumFractionDigits:2})} 亿`:magnitude>=1e4?`${(number/1e4).toLocaleString('zh-CN',{maximumFractionDigits:1})} 万`:fmt(number);}
  function metric(label,value,note){const node=el('div','research-metric');node.append(el('span','small muted',label),el('strong','',value));if(note)node.append(el('small','muted',note));return node;}
  function current(epoch){return state.active&&state.epoch===epoch&&host.isAuthenticated();}
  function reset(){clearTimeout(state.timer);clearTimeout(state.queryTimer);state.epoch++;state.summaryRequest++;state.listRequest++;state.detailRequest++;state.libraryRequest++;state.refreshing=false;state.refreshCycle=null;setRefreshFeedback('idle','');state.detailCode=null;state.detail=null;state.job=null;state.summary=null;state.signature=null;state.rows=[];state.total=0;state.listMode='all';state.libraryTotal=null;state.librarySignature=null;state.libraryIndustries=[];state.settingsDirty=false;state.saving=false;state.moreLoading=false;state.scanSubmitting=false;$('research-save').disabled=false;$('research-api-key').value='';if($('research-dialog').open)$('research-dialog').close();closeDeep();replace($('research-companies'));replace($('research-coverage'));renderResearchTabs();}
  function setActive(active){if(active===state.active)return;state.active=active;if(!active){reset();return;}refresh(true);}
  function schedule(){clearTimeout(state.timer);if(state.active)state.timer=setTimeout(()=>refresh(false),document.hidden?15000:5000);}
  function setRefreshFeedback(status,label){$('research-refresh-state').textContent=label;$('research-refresh-state').hidden=!label;$('research-refresh-state').setAttribute('data-state',status);$('research-refresh').setAttribute('aria-busy',String(status==='loading'));}
  function resultSignature(){return JSON.stringify([state.summary,state.rows,state.total,state.listMode,filters().toString()]);}
  function refresh(force=false,manual=false){
    if(!state.active)return Promise.resolve();
    if(state.refreshCycle){const cycle=state.refreshCycle;if(manual){if(!cycle.manualRunning&&!cycle.manualPending){cycle.manualPending=true;cycle.baseline=resultSignature();cycle.queuedForce=true;}setRefreshFeedback('loading','正在读取服务器已有结果…');}else if(force)cycle.queuedForce=true;return cycle.promise;}
    clearTimeout(state.timer);state.refreshing=true;const cycle={epoch:state.epoch,queuedForce:false,manualPending:false,manualRunning:manual,baseline:manual?resultSignature():null,promise:null};state.refreshCycle=cycle;
    if(manual)setRefreshFeedback('loading','正在读取服务器已有结果…');cycle.promise=runRefresh(cycle,force||manual,manual);return cycle.promise;
  }
  async function runRefresh(cycle,force,manual){
    const epoch=cycle.epoch;
    try{while(current(epoch)&&state.refreshCycle===cycle){
      cycle.manualRunning=manual;const request=++state.summaryRequest;let outcome='applied';
      try{
        const result=await host.api('/api/research/summary');if(!current(epoch)||request!==state.summaryRequest)return;
        state.summary=result;renderSummary(result);$('research-error').hidden=true;
        const signature=JSON.stringify([result.updated_at,result.coverage]),libraryChanged=await loadLibraryCount();
        if(!current(epoch)||request!==state.summaryRequest)return;
        if(force||state.listMode==='library'&&libraryChanged||signature!==state.signature){const loaded=await loadCompanies();outcome=loaded?.status||'stale';if(outcome==='failed')throw loaded.problem;if(outcome==='applied')state.signature=signature;}
        if(state.job&&running(state.job))await pollDetailJob(epoch);
      }catch(problem){outcome='failed';if(current(epoch)){error(problem);if(manual)setRefreshFeedback('failed','读取失败，请重试；页面保留上次成功读取的结果。');}}
      if(!current(epoch)||state.refreshCycle!==cycle)return;
      if(manual&&outcome==='applied')setRefreshFeedback('succeeded',cycle.baseline===resultSignature()?'读取成功，服务器已有结果未变化。':'读取成功，已显示服务器已有结果。');
      // If filters changed while reading, finish the user's request against the current list.
      if(manual&&outcome==='stale'){cycle.manualPending=true;cycle.queuedForce=true;}
      if(!cycle.queuedForce&&!cycle.manualPending)break;
      force=true;manual=cycle.manualPending;cycle.queuedForce=false;cycle.manualPending=false;
    }}finally{if(current(epoch)&&state.refreshCycle===cycle){state.refreshCycle=null;state.refreshing=false;schedule();}}
  }
  function renderSummary(data){
    const coverage=data.coverage||{},scan=data.scan||{},verified=coverage.universe_verified===true;
    replace($('research-coverage'),metric('A 股公司总数',verified?fmt(coverage.universe_total):'待核验',verified?'公司名单已核验':'名单覆盖尚未确认'),metric('已取得财务资料',fmt(coverage.financial_count),'不等于已完成判断'),metric('可进行财务初筛',fmt(coverage.assessable_count),'关键资料达到要求'),metric('暂未参与通用评分',fmt(coverage.missing_count),'缺资料、专项行业或重大事项待核查'),metric('待深入研究候选',fmt(coverage.candidate_count),'按当前规则筛选'),metric('已取得估值行情',fmt(coverage.quote_total),'缺行情时不判断价格'));
    const industryExtra=el('div','research-industry-extras');industryExtra.append(window.ETFResearchIndustry.renderCoverage(coverage),state.hkReferenceNode||(state.hkReferenceNode=window.ETFResearchHKReferences.render()));$('research-coverage').append(industryExtra);
    const isRunning=running(scan);$('research-scan-state').textContent=statusNames[scan.status]||'等待扫描';$('research-scan').disabled=isRunning||state.scanSubmitting;$('research-cancel').hidden=!isRunning;$('research-cancel').disabled=scan.cancel_requested===true||scan.status==='cancelling';
    $('research-progress-text').textContent=scan.message||(!verified?'先扫描并核验 A 股公司名单，再按可取得的财务资料筛查。':isRunning?'正在更新公司财务资料…':'已有结果会保留，扫描只更新公司研究资料。');
    const processed=n(scan.processed),total=n(scan.total);const progress=n(scan.progress)??(total>0&&processed!==null?processed/total*100:null);$('research-progress').hidden=!isRunning;if(progress===null)$('research-progress').removeAttribute('value');else $('research-progress').value=Math.max(0,Math.min(100,progress));
    const date=coverage.as_of||coverage.report_period||data.updated_at;$('research-data-time').textContent=`资料日期：${time(date)}${processed!==null&&total!==null?` · 本次已处理 ${fmt(processed)} / ${fmt(total)}`:''}`;
    const ai=data.ai_status||{},configured=ai.configured===true||ai.available===true;$('research-ai-state').textContent=ai.status==='limit_reached'?'本网站每日 AI 调用次数已用尽或上限设为 0；这不表示 DeepSeek 余额不足。':ai.message||(configured?'AI 服务已配置；证据整理是否完成，以实际任务结果为准。':'AI 尚未配置：目前只有财务规则筛查，尚无 AI 证据整理。');if(n(ai.used_today)!==null&&n(ai.daily_limit)!==null)$('research-ai-state').append(el('span','',` · 今日 AI 调用 ${fmt(ai.used_today)} / ${fmt(ai.daily_limit)}`));
    if(scan.error)$('research-progress-text').append(el('span','research-inline-warning',` ${scan.error}`));
    renderSourceRefresh(scan.source_refresh,scan.status);
    if(!state.settingsDirty&&!state.saving)fillSettings(data.settings||{});
    updateResearchIndustries();
  }
  function renderSourceRefresh(refresh,jobStatus){const status=['failed','cancelled','interrupted'].includes(jobStatus)?jobStatus:refresh?.status;const node=$('research-source-refresh');replace(node);node.hidden=!refresh||typeof refresh!=='object';if(node.hidden)return;node.append(el('span','',refresh.requested_fresh===true?'本次更新要求重新获取来源资料。':'本次后台扫描可复用有效来源缓存。'));if(refresh.measurement_available===true){for(const [label,value] of [['来源网络请求',refresh.network_requests],['来源缓存命中',refresh.cache_hits]]){if(n(value)!==null)node.append(document.createTextNode(' '),el('span','',label),raw('span','',` ${fmt(value)} · `));}node.append(el('span','','请求数不等于财务数据变更数。'));}if(refresh.source_fetched_at_min||refresh.source_fetched_at_max)node.append(document.createTextNode(' '),el('span','','来源资料实际取得时间'),raw('span','',` ${time(refresh.source_fetched_at_min)} — ${time(refresh.source_fetched_at_max)}`));if(status==='complete')node.append(document.createTextNode(' '),el('span','','来源获取已完成；没有新的披露或行情时，分数可能不变。'));else if(['partial','failed','cancelled','interrupted'].includes(status))node.append(document.createTextNode(' '),el('span','','本次来源获取未完整完成，未取得新资料的项目保留原有数据。'));}
  function renderSortBasis(){const labels={dynamic:'当前排序：同行财务参考，从高到低；暂不可比较的公司排在后面。',quality:'当前排序：原财务初筛，从高到低；卡片上的同行参考不参与此排序。',risk:'当前排序：按原财务风险优先；不按同行参考值排列。',valuation:'当前排序：市盈率 PE 从低到高；不按同行参考值排列。',code:'当前排序：证券代码；不按分数排列。'};$('research-sort-description').textContent=state.listMode==='library'?'当前排序：深研报告时间，从新到旧。':labels[$('research-sort').value]||labels.dynamic;}
  function updateResearchIndustries(){const select=$('research-industry'),previous=select.value,industries=arr(state.listMode==='library'?state.libraryIndustries:state.summary?.coverage?.industries||state.summary?.industries).map(row=>typeof row==='string'?row:row.name||row.industry).filter(Boolean);replace(select,el('option','','全部行业'));select.firstChild.value='';for(const name of [...new Set(industries)].sort()){const option=raw('option','',name);option.value=name;select.append(option);}select.value=[...select.options].some(option=>option.value===previous)?previous:'';}
  function renderResearchTabs(){const library=state.listMode==='library';for(const [id,selected] of [['research-tab-all',!library],['research-tab-library',library]]){const tab=$(id);tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;}if($('research-library-count'))$('research-library-count').textContent=`（${state.libraryTotal===null?'—':fmt(state.libraryTotal)}）`;$('research-list-panel').setAttribute('aria-labelledby',library?'research-tab-library':'research-tab-all');$('research-sort-control').hidden=library;$('research-candidate-control').hidden=library;$('research-list-hint').textContent=library?'只收录已有 AI 深研结果的公司，按最近研究时间排列；仍有缺口的报告也会保留。':'缺资料与专项行业暂不参与通用评分';renderSortBasis();}
  async function loadLibraryCount(){const epoch=state.epoch,request=++state.libraryRequest;try{const result=await host.api('/api/research/deep-library?offset=0&limit=1');if(!current(epoch)||request!==state.libraryRequest)return false;const signature=JSON.stringify([result.total,arr(result.companies)[0]]),changed=signature!==state.librarySignature,previousIndustry=$('research-industry').value;state.libraryTotal=n(result.total);state.librarySignature=signature;state.libraryIndustries=arr(result.industries);renderResearchTabs();if(state.listMode==='library')updateResearchIndustries();return changed||previousIndustry!==$('research-industry').value;}catch(problem){if(current(epoch)&&request===state.libraryRequest){state.libraryTotal=null;renderResearchTabs();if(state.listMode==='library')error(problem);}return false;}}
  function selectResearchList(mode){if(!['all','library'].includes(mode)||mode===state.listMode)return;clearTimeout(state.queryTimer);state.listRequest++;state.moreLoading=false;state.listMode=mode;state.rows=[];state.total=0;$('research-query').value='';$('research-industry').value='';$('research-candidate').checked=false;$('research-more').hidden=true;$('research-more').disabled=false;$('research-matched').textContent='正在读取清单…';$('research-error').hidden=true;renderResearchTabs();updateResearchIndustries();replace($('research-companies'),empty('正在读取清单…','切换清单后已清空关键词和行业筛选。'));loadCompanies();}
  function endpointHost(value){try{return new URL(value).host.toLowerCase();}catch(_){return '';}}
  function selectedDefaults(){return providerDefaults[$('research-provider').value]||providerDefaults.deepseek;}
  function configuredRounds(value){return n(value)===3?3:6;}
  function savedRounds(value){return value===undefined||value===null?3:[3,6].includes(n(value))?n(value):null;}
  function renderKeyState(){const changed=state.settingsHost!==undefined&&endpointHost($('research-base-url').value)!==state.settingsHost;$('research-key-state').textContent=changed&&state.settingsHasKey?'服务地址已更换。保存后会清除原服务密钥；请填写新服务的 API 密钥。':state.settingsHasKey?'密钥已保存。留空会继续使用原密钥。':'尚未保存 API 密钥。';$('research-api-key').placeholder=changed?'填写新服务的 API 密钥':'留空保留已保存的密钥';}
  function guardEndpointKey(){const currentHost=endpointHost($('research-base-url').value);if(state.formHost!==undefined&&currentHost!==state.formHost){$('research-api-key').value='';$('research-settings-message').textContent='服务地址已更换，尚未提交的密钥已清空。请填写新服务的 API 密钥。';}state.formHost=currentHost;renderKeyState();}
  function fillSettings(settings){const existing=Boolean(settings.provider||settings.base_url||settings.model),base=settings.base_url||(settings.provider==='openai'?providerDefaults.openai.base_url:providerDefaults.deepseek.base_url),provider=endpointHost(base)==='api.deepseek.com'?'deepseek':settings.provider||'deepseek';$('research-auto').checked=settings.auto_scan===true;$('research-auto-ai').checked=settings.auto_ai===true;$('research-daily-limit').value=String(settings.ai_daily_limit??0);$('research-deep-rounds').value=String(configuredRounds(settings.deep_research_rounds));$('research-model').value=existing?(settings.model||''):providerDefaults.deepseek.model;$('research-provider').value=provider;$('research-base-url').value=base;state.settingsHost=endpointHost(base);state.settingsHasKey=Boolean(settings.key_configured||settings.has_api_key||settings.api_key_configured);guardEndpointKey();}
  function providerChanged(){const defaults=providerDefaults[$('research-provider').value];if(defaults){$('research-base-url').value=defaults.base_url;$('research-model').value=defaults.model;}state.settingsDirty=true;state.settingsRevision++;guardEndpointKey();}
  async function saveSettings(event){
    event.preventDefault();if(state.saving)return;const limit=n($('research-daily-limit').value),rounds=n($('research-deep-rounds').value);
    if(limit===null||!Number.isInteger(limit)||limit<0||limit>100){$('research-settings-message').textContent='每日 AI 调用上限必须是 0 到 100 的整数。';return;}
    if(![3,6].includes(rounds)){$('research-settings-message').textContent='单次深度研究轮数只能选择 3 轮或 6 轮。';return;}
    if(!$('research-base-url').value.trim())$('research-base-url').value=selectedDefaults().base_url;guardEndpointKey();const payload={auto_scan:$('research-auto').checked,auto_ai:$('research-auto-ai').checked,ai_daily_limit:limit,deep_research_rounds:rounds,model:$('research-model').value.trim(),provider:$('research-provider').value==='deepseek'?'openai_compatible':$('research-provider').value,base_url:$('research-base-url').value.trim()};
    if(payload.base_url&&!safeURL(payload.base_url)){$('research-settings-message').textContent='服务地址需要使用 HTTPS，且不能包含用户名或密码。';return;}
    const key=$('research-api-key').value.trim();if(key)payload.api_key=key;
    state.saving=true;$('research-save').disabled=true;$('research-settings-message').textContent='正在保存…';const epoch=state.epoch,revision=state.settingsRevision;
    try{const settings=await host.api('/api/research/settings',{method:'POST',body:payload});if(!current(epoch))return;if(revision===state.settingsRevision){state.settingsDirty=false;fillSettings(settings.settings||settings);$('research-settings-message').textContent='研究设置已保存。';}else $('research-settings-message').textContent='先前设置已保存，新的修改尚未保存。';if($('research-api-key').value.trim()===key)$('research-api-key').value='';host.toast('研究设置已保存。');await refresh(true);}
    catch(problem){if(current(epoch))$('research-settings-message').textContent=message(problem);}
    finally{if(current(epoch)){state.saving=false;$('research-save').disabled=false;}}
  }
  function filters(){const values={query:$('research-query').value.trim(),industry:$('research-industry').value};if(state.listMode==='all'){values.candidate=$('research-candidate').checked?'true':'false';values.sort=$('research-sort').value;}return new URLSearchParams(values);}
  async function loadCompanies(append=false){
    if(!state.active||append&&state.moreLoading)return;const epoch=state.epoch,request=++state.listRequest,mode=state.listMode,query=filters().toString(),offset=append?state.rows.length:0;state.moreLoading=append;if(append)$('research-more').disabled=true;
    try{const result=await host.api((mode==='library'?'/api/research/deep-library?':'/api/research/companies?')+query+'&offset='+offset+'&limit=30');if(!current(epoch)||request!==state.listRequest||mode!==state.listMode||query!==filters().toString())return{status:'stale'};state.rows=append?state.rows.concat(arr(result.companies)):arr(result.companies);state.total=n(result.total)??state.rows.length;renderCompanies();$('research-error').hidden=true;return{status:'applied'};}
    catch(problem){if(current(epoch)&&request===state.listRequest){error(problem);return{status:'failed',problem};}return{status:'stale'};}
    finally{if(current(epoch)&&request===state.listRequest){state.moreLoading=false;$('research-more').disabled=false;}}
  }
  function renderCompanies(){
    const root=$('research-companies');replace(root);$('research-matched').textContent=`当前符合条件：${fmt(state.total)} 家`;
    if(!state.rows.length){root.append(state.listMode==='library'?empty($('research-query').value.trim()||$('research-industry').value?'当前筛选没有深研结果':'尚无已保存的 AI 深研结果',$('research-query').value.trim()||$('research-industry').value?'可以清空关键词或改选全部行业。':'完成至少一轮 AI 阅读并保存报告后，公司会出现在这里。仅下载资料或因调用次数不足未开始的报告不会收录。'):empty(state.summary?.coverage?.financial_count?'当前筛选没有结果':'研究清单正在建立',state.summary?.coverage?.financial_count?'可以调整行业、关键词，或取消“只看候选公司”。':'点击“更新全市场资料”开始，真实资料取得后会出现在这里。资料不足不会生成好公司结论。'));$('research-more').hidden=true;return;}
    for(const company of state.rows)root.append(state.listMode==='library'?deepLibraryCard(company):companyCard(company));
    $('research-more').hidden=state.rows.length>=state.total;$('research-more').textContent=`显示更多公司（已显示 ${state.rows.length} / ${state.total}）`;
  }
  function deepLibraryCard(company){const card=el('article','panel research-company research-library-company'),head=el('div','research-company-head'),identity=el('div');identity.append(raw('span','eyebrow',`${company.code||'—'} · ${company.industry||'行业待确认'}`),raw('h3','',company.name||company.code));const planned=savedRounds(company.ai_rounds_planned),complete=company.deep_status==='completed'&&planned!==null&&n(company.ai_rounds_completed)===planned&&n(company.evidence_topics)===6;head.append(identity,el('span','pill neutral',complete?'已整理':'仍有缺口'));card.append(head);const metrics=el('div','research-card-metrics');metrics.append(metric('已完成 AI 轮次',`${fmt(company.ai_rounds_completed)} / ${fmt(planned)}`),metric('有证据的主题',`${fmt(company.evidence_topics)} / 6`),metric('来源文档',fmt(company.documents)));card.append(metrics);const date=el('p','small research-library-date');date.append(el('span','muted','研究日期'),document.createTextNode(' '),raw('span','',time(company.generated_at)));card.append(date,el('p','research-company-summary',complete?'六类主题已整理，结论仍需结合原文与资料范围核查。':'已有部分 AI 深研结果，可查看已保存证据并继续未完成主题。'));const foot=el('div','research-company-foot');foot.append(button('查看深研报告',()=>openDeep(company.code),'button secondary small-button'));card.append(foot);return card;}
  function companyCard(company){
    const screen=company.screen||{},quality=scoreOf(company),risk=riskOf(company),valuation=screen.valuation||company.valuation||{};
    const card=el('article','panel research-company'),head=el('div','research-company-head'),identity=el('div');identity.append(raw('span','eyebrow',`${company.code||'—'} · ${company.industry||'行业待确认'}`),raw('h3','',company.name||company.code));
    head.append(identity,el('span',`pill ${quality===null?'neutral':''}`,quality===null?'暂不评分':screen.candidate?'研究候选':'继续观察'));card.append(head);
    card.append(window.ETFResearchIndustry.renderBadge(company.industry_profile,{screen,companyCode:company.code}));
    card.append(window.ETFResearchDynamic.card(company.dynamic_evaluation,{companyCode:company.code}));
    const metrics=el('div','research-card-metrics');metrics.append(metric('原财务初筛',quality===null?'—':`${fmt(quality)} / 100`,n(screen.coverage_weight)!==null?`资料覆盖 ${fmt(screen.coverage_weight)} / ${fmt(screen.total_weight??100)}`:''),metric('财务风险',quality===null&&risk==='low'?'待核实':riskText(risk)),metric('估值',n(valuation.pe)>0?`PE ${fmt(valuation.pe)}`:n(valuation.pb)>0?`PB ${fmt(valuation.pb)}`:'待核实'));card.append(metrics);
    card.append(raw('p','research-company-summary',screen.summary||company.summary||'尚未取得足够资料形成判断。'));
    const facts=el('div','research-company-meta');facts.append(el('span','',`报告期：${company.report_period||screen.report_period||'待确认'}`),el('span','',`获取日：${time(company.fetched_at).slice(0,10)}`));card.append(facts);
    const foot=el('div','research-company-foot'),ai=company.ai_status;foot.append(el('span','small muted',ai==='evidence_only'?'已有 AI 证据整理':['succeeded','ready','complete','completed','success'].includes(ai)?'历史 AI 结果待复核':ai==='abstained'?'AI 已阅读，保留判断':'财务规则筛查'),button('查看依据 →',()=>openCompany(company.code),'text-button'),button('深度研究',()=>openDeep(company.code),'button secondary small-button'));card.append(foot);return card;
  }
  async function scan(){
    if(state.scanSubmitting||running(state.summary?.scan))return;const epoch=state.epoch;state.scanSubmitting=true;$('research-scan').disabled=true;
    try{const job=await host.api('/api/research/scan',{method:'POST',body:{force:true}});if(!current(epoch))return;state.summary={...state.summary,scan:job};renderSummary(state.summary);host.toast('全市场资料更新已提交，将重新获取来源资料；关闭网页后仍可继续。');await refresh(true);}
    catch(problem){if(current(epoch))error(problem);}finally{if(current(epoch)){state.scanSubmitting=false;$('research-scan').disabled=running(state.summary?.scan);}}
  }
  async function cancelScan(){const job=state.summary?.scan;if(!running(job))return;const epoch=state.epoch;$('research-cancel').disabled=true;try{await host.api(`/api/research/jobs/${encodeURIComponent(job.id)}/cancel`,{method:'POST',body:{}});if(current(epoch)){host.toast('停止请求已提交，已取得的资料会保留。');await refresh(true);}}catch(problem){if(current(epoch)){error(problem);$('research-cancel').disabled=false;}}}
  async function openCompany(code){
    if(!code)return;closeDeep();const epoch=state.epoch,request=++state.detailRequest;state.detailCode=String(code);state.detail=null;state.job=null;$('research-detail-title').textContent=code;replace($('research-detail-body'),empty('正在读取公司资料','财务、风险与来源会在这里分别显示。'));if(!$('research-dialog').open)$('research-dialog').showModal();
    try{const result=await host.api('/api/research/company/'+encodeURIComponent(code));if(!current(epoch)||request!==state.detailRequest||state.detailCode!==String(code)||!$('research-dialog').open)return;state.detail=result;state.job=result.job;renderDetail(result);}
    catch(problem){if(current(epoch)&&request===state.detailRequest&&$('research-dialog').open)replace($('research-detail-body'),empty('暂时无法读取',message(problem)),button('重新读取',()=>openCompany(code)));}
  }
  function section(title){const node=el('section','research-detail-section');node.append(el('h3','',title));return node;}
  function notes(node,values,emptyMessage){const rows=arr(values);if(!rows.length){node.append(el('p','small muted',emptyMessage));return;}const list=el('ul','research-notes');for(const value of rows){const item=el('li');if(typeof value==='object'){if(value.title||value.name)item.append(raw('strong','',value.title||value.name),document.createTextNode(' '));item.append(raw('span','',value.text||value.message||value.description||value.detail||value.reason||text(value)));}else item.append(raw('span','',value));list.append(item);}node.append(list);}
  const valuationViews=new WeakMap();
  function appendValuation(root,code,request){
    if(!window.ETFValuationScenarios)return;
    const key=`${state.epoch}:${request}:${code}`;
    let saved=valuationViews.get(root);
    if(!saved||saved.key!==key){saved={key,node:window.ETFValuationScenarios.render({companyCode:code,api:host.api})};valuationViews.set(root,saved);}
    root.append(saved.node);
  }
  function renderDetail(data){
    const company=data.company||{},screen=data.screen||company.screen||{},merged={...company,screen},root=$('research-detail-body');replace(root);$('research-detail-title').textContent=`${company.name||state.detailCode} · ${company.code||state.detailCode}`;$('research-detail-title').setAttribute('data-i18n-skip','');
    const quality=scoreOf(merged),valuation={...(data.report?.valuation||{}),...(screen.valuation||company.valuation||{})},risk=riskOf(merged),summary=el('div','research-detail-summary');summary.append(metric('原财务初筛',quality===null?'暂不评分':`${fmt(quality)} / 100`),metric('财务风险',quality===null&&risk==='low'?'待核实':riskText(risk)),metric('估值',n(valuation.pe??valuation.pe_ttm)>0?`PE ${fmt(valuation.pe??valuation.pe_ttm)}`:'待核实'));root.append(summary);
    if(window.ETFCompanyReview)root.append(window.ETFCompanyReview.render({companyCode:company.code||state.detailCode,financialReport:data.report,ai:data.ai,dynamic:data.dynamic_evaluation,stale:data.report_stale===true,sources:allSources(data)}));
    if(window.ETFQualityChecks)root.append(window.ETFQualityChecks.render({model:data.quality_checks,companyCode:company.code||state.detailCode,sources:allSources(data)}));
    root.append(window.ETFResearchDynamic.render(data.dynamic_evaluation,{companyCode:company.code||state.detailCode}));
    appendValuation(root,company.code||state.detailCode,state.detailRequest);
    const deepEntry=el('div','research-deep-entry');deepEntry.append(el('p','small muted','按经营、竞争、财务、治理、估值与风险整理可追溯的深度研究。'),button('深度研究',()=>openDeep(company.code||state.detailCode)));root.append(deepEntry);
    if(n(screen.coverage_weight)!==null)root.append(el('p','small muted',`已覆盖 ${fmt(screen.coverage_weight)} / ${fmt(screen.total_weight??100)} 权重；缺项不重新分配权重。`));
    if(data.report_stale)root.append(el('p','notice warning-text','已有报告基于较早数据，请重新补齐分析。'));
    const intro=section('这家公司值得继续研究吗？');intro.append(raw('p','research-detail-lead',screen.summary||'当前资料还不足以形成结论。'));intro.append(raw('p','small muted',`${company.industry||'行业待确认'} · 报告期 ${company.report_period||screen.report_period||'待确认'} · 获取 ${time(company.fetched_at)}`));notes(intro,screen.reasons||screen.strengths,quality===null?'缺失数据不计分，也不会自动视为低风险。':'入选依据以当前资料与筛查规则为准。');root.append(intro);
    const riskSection=section('风险与尚未解决的问题');notes(riskSection,screen.risks||screen.flags||company.risks||data.risks||data.report?.risks,'尚未形成完整风险清单，不代表没有风险。');if(arr(screen.missing).length||arr(screen.missing_fields).length){riskSection.append(el('p','small muted','待补齐的核查项目'));notes(riskSection,(screen.missing||screen.missing_fields).map(field=>fieldNames[field]||'专项行业资料'),'');}root.append(riskSection);
    root.append(window.ETFResearchIndustry.render(data.report?.industry_profile,{sources:allSources(data),companyCode:company.code,screen,stale:data.report_stale===true,currentContext:data.report?.price_quality_panel?.current_industry_context}));
    renderMetrics(root,arr(screen.metrics||data.report?.quality?.metrics));
    renderLongTerm(root,data.report?.quality?.long_term,allSources(data),data.report_stale===true);
    root.append(window.ETFResearchDebtGovernance.render(data.report?.debt_governance,{sources:allSources(data),companyCode:company.code,stale:data.report_stale===true}));
    root.append(window.ETFResearchBusinessCapital.render(data.report?.business_capital,{sources:allSources(data),companyCode:company.code,stale:data.report_stale===true}));
    root.append(window.ETFResearchPriceQuality.render(data.report?.price_quality_panel,{sources:allSources(data),companyCode:company.code,stale:data.report_stale===true}));
    renderFinancials(root,arr(company.financials||data.financials));renderPeers(root,arr(company.peers||data.peers),company,screen);
    const valueSection=section('价格与公司质量分开看');valueSection.append(raw('p','',valuation.summary||valuation.explanation||valuation.label||'暂未形成估值判断。低估值本身不能证明公司便宜。'));const valueMetrics=el('div','research-value-metrics');valueMetrics.append(metric('市盈率 PE',n(valuation.pe??valuation.pe_ttm)>0?fmt(valuation.pe??valuation.pe_ttm):'不适用 / 缺数据'),metric('市净率 PB',n(valuation.pb)>0?fmt(valuation.pb):'不适用 / 缺数据'));valueSection.append(valueMetrics);if(valuation.as_of||company.valuation_as_of)valueSection.append(el('p','small muted',`价格日期：${time(valuation.as_of||company.valuation_as_of)}`));
    if(data.valuation_updated===true){const ai=data.ai||{},hasEvidence=ai.mode==='evidence_extract'&&['evidence_only','abstained'].includes(ai.status)&&arr(ai.claims).length>0;valueSection.append(el('p','small muted',hasEvidence?'估值已按最新市场快照更新；已有 AI 证据整理仍保留生成时的依据。':'估值已按最新市场快照更新；财务分析仍保留生成时的依据。'));}root.append(valueSection);
    renderAI(root,data);renderSources(root,allSources(data));if(arr(data.report?.limitations).length){const limitations=section('本次研究的边界');notes(limitations,data.report.limitations,'');root.append(limitations);}
    root.append(el('p','small muted research-detail-foot','筛查帮助缩小研究范围，仍需核对行业差异、原始公告与估值假设。历史数据和 AI 结论都不保证未来收益。'));
  }
  function table(columns,rows){const wrap=el('div','table-wrap research-table'),table=el('table'),head=el('thead'),tr=el('tr');for(const col of columns)tr.append(el('th','',col.label));head.append(tr);table.append(head);const body=el('tbody');for(const row of rows){const tr=el('tr');for(const col of columns){const td=el('td');const value=col.render(row);td.append(value instanceof Node?value:raw('span','',value));tr.append(td);}body.append(tr);}table.append(body);wrap.append(table);return wrap;}
  function renderMetrics(root,metrics){if(!metrics.length)return;const area=section('初筛分怎样得出');area.append(el('p','small muted','按公开规则计算，缺项不填零、不重新分配权重。分数用于安排财务研究顺序。'));for(const item of metrics){const block=el('div','research-score-item'),head=el('div','research-score-head'),value=n(item.value)===null?'—':item.unit==='ratio'?ratio(item.value):item.unit==='CNY'?shortMoney(item.value):`${fmt(item.value)}${item.unit==='multiple'?' 倍':''}`;head.append(raw('strong','',item.label||fieldNames[item.key]||'核查项目'),raw('span','',value));block.append(head,raw('p','small muted',item.explanation||''));if(n(item.weight)>0)block.append(el('span','small muted',n(item.score)===null?'缺资料，本项不计分':`本项 ${fmt(Number(item.score)*Number(item.weight)/100)} / ${fmt(item.weight)} 分`));area.append(block);}root.append(area);}
  const longTermLabels={capex:'购建长期资产支付现金',receivables:'应收账款',inventory:'存货',simple_free_cashflow:'简化自由现金流',revenue_sum:'累计营业收入',net_profit_sum:'累计合并净利润',parent_profit_sum:'累计归母净利润',adjusted_profit_sum:'累计扣非归母净利润',op_cashflow_sum:'累计经营现金流',capex_sum:'累计购建长期资产支付现金',simple_free_cashflow_sum:'累计简化自由现金流',cash_conversion:'累计经营现金流／合并净利润',recurring_profit:'累计扣非归母／归母净利润',positive_profit_years:'合并净利润为正年度数',positive_cashflow_years:'经营现金流为正年度数',roe_average:'年度 ROE 均值',revenue_cagr:'营业收入年复合增长',net_profit_cagr:'合并净利润年复合增长',revenue_change:'营业收入首尾变化',net_profit_change:'合并净利润首尾变化',receivables_change:'应收账款首尾变化',inventory_change:'存货首尾变化',receivables_vs_revenue:'应收增速相对收入',inventory_vs_revenue:'存货增速相对收入'};
  const longTermStatus={conditional:'有条件的财务观察',insufficient:'资料不足',specialist:'专项行业待研究',conflict:'数据存在冲突',available:'数值可用',partial:'部分资料',missing:'缺失',zero:'数值为零',negative:'数值为负',not_applicable:'不适用',unknown_publication:'公告日期待核验',invalid_basis:'会计口径不兼容',invalid_value:'数值无效',support:'支持',mixed:'支持与关注并存',concern:'关注'};
  const longTermVerification={supplier_only:'供应商数据，未逐值官方核验',unavailable:'当前没有可核验数值',not_verified:'未逐值核验',unknown:'核验状态待确认',conflict:'数据存在冲突'};
  function longTermBadge(status){return el('span',`research-lt-status ${['support','concern','conflict'].includes(status)?status==='support'?'supported':status:''}`,longTermStatus[status]||'状态待确认');}
  function longTermValue(item){if(n(item?.value)===null)return '—';const format=value=>Number(value).toLocaleString('zh-CN',{maximumFractionDigits:2});if(item.unit==='CNY')return shortMoney(item.value);if(item.unit==='ratio')return `${format(Number(item.value)*100)}%`;if(item.unit==='multiple')return `${format(item.value)}×`;return format(item.value);}
  function longTermExactValue(tag,value,unit){const node=el(tag);if(n(value)===null){node.textContent='—';return node;}const units={multiple:'倍',ratio:'小数比例',years:'年',CNY:'人民币元'};node.append(raw('span','',String(value)),document.createTextNode(' '),el('span','',units[unit]||'单位待核对'));return node;}
  function longTermRefs(node,ids,sources){const refs=[...new Set(arr(ids).map(String))];if(!refs.length){node.append(el('p','small muted','尚无可跳转的数值来源。'));return;}const wrap=el('div','research-lt-evidence');wrap.append(el('p','small muted','数值来源与期间'));for(const id of refs){const source=sources.find(item=>String(item.id)===id),url=safeURL(source?.url),line=el('p');if(url){const link=raw('a','',source.title||id);link.href=url;link.target='_blank';link.rel='noopener noreferrer';line.append(link);}else line.append(raw('span','',source?.title||id),el('span','small muted',' · 来源链接待补齐'));wrap.append(line);if(source?.report_period||source?.report_date)wrap.append(raw('p','small muted',source.report_period||source.report_date));}node.append(wrap);}
  function longTermMetric(item,sources){const block=el('details','research-lt-metric'),head=el('summary');head.append(el('span','',longTermLabels[item.key]||fieldNames[item.key]||item.label||'核查项目'),el('strong','',longTermValue(item)),longTermBadge(item.status));block.append(head);if(n(item.value)!==null){block.append(el('p','small muted','原始数值（未缩写）'),longTermExactValue('p',item.value,item.unit));}if(Object.hasOwn(item,'current_value')){const values=el('dl','research-lt-values');for(const [key,label] of [['previous_value','上年同期金额'],['current_value','本期金额'],['absolute_change','金额变化']])values.append(el('dt','',label),longTermExactValue('dd',item[key],'CNY'));block.append(values);}else if(n(item.absolute_change)!==null)block.append(el('p','small muted','首尾金额变化（人民币元）'),raw('p','',item.absolute_change));if(item.note)block.append(el('p','small muted',item.note));block.append(el('p','small muted',longTermVerification[item.verification]||'核验状态待确认'));if(arr(item.periods).length)block.append(raw('p','small muted',item.periods.join(' · ')));if(arr(item.missing).length){block.append(el('p','small muted','缺失或不可比项目'));notes(block,item.missing.map(key=>longTermLabels[key]||fieldNames[key]||key),'');}longTermRefs(block,item.source_ids,sources);return block;}
  function longTermNotes(node,values){const list=el('ul','research-notes');for(const value of arr(values))list.append(el('li','',typeof value==='object'?value.text||value.message||value.reason||text(value):value));if(list.childNodes.length)node.append(list);}
  function renderLongTerm(root,data,sources,stale){
    const area=section('多年财务质量');area.className+=' research-long-term';area.append(el('p','research-lt-scope','程序按年度财务数据计算；与六项初筛并列，不是完整公司判断，也不消耗 AI 调用。'));
    if(!data||data.version!=='long-term-quality-1.0'){area.append(el('p','notice warning-text',data?'多年分析版本待更新，请补齐资料后重新查看。':'此报告尚无多年财务分析，请补齐历年财务资料。'));root.append(area);return;}
    if(stale)area.append(el('p','notice warning-text','以下是旧报告中的多年分析，尚未按最新资料重新核验。'));
    area.append(longTermBadge(data.status));if(data.label)area.append(el('p','research-detail-lead',data.label));
    const coverage=data.coverage||{},overview=el('div','research-lt-overview');overview.append(metric('完整年度覆盖',`${fmt(coverage.complete_years)} / ${fmt(coverage.target_years??5)}`,'已取得年度数与完整年度数分别统计'),metric('连续完整年度',fmt(coverage.consecutive_years),'至少连续 3 年才形成多年观察'),metric('官方逐值核验',`${fmt(coverage.official_verified_values)} / ${fmt(coverage.available_values)}`,'有 PDF 链接不等于数字已核对'));area.append(overview);area.append(el('p','small muted','完整年度仅指收入、合并利润、归母、扣非归母、经营现金与 ROE 核心字段齐全；其他字段仍可能缺失。'));
    area.append(el('p','small muted',`已取得 ${fmt(coverage.available_years)} 个年度 · 研究截止 ${data.as_of||'待确认'}`));if(data.anchor_reason)area.append(el('p','small muted',data.anchor_reason));if(arr(coverage.missing_years).length)area.append(el('p','notice warning-text',`缺失年度：${coverage.missing_years.join('、')}；不向较早年度回退补足。`));area.append(el('p','small muted',coverage.pit_status==='publication_dates_known'?'公告日期已取得；不等于已完成严格历史时点验证。':'部分公告日期待核验，不能声称通过严格历史时点验证。'));
    const windows=el('div','research-lt-windows');for(const count of [3,5]){const item=arr(data.windows).find(row=>Number(row.years)===count),card=el('div','research-lt-window');card.append(el('h4','',count===3?'最近 3 个完整年度窗口':'最近 5 个完整年度窗口'));if(!item){card.append(el('p','small muted','该窗口尚无可用分析。'));windows.append(card);continue;}card.append(longTermBadge(item.complete?'available':'insufficient'),el('p','small muted',`完整 ${fmt(item.complete_years)} / ${count} 年 · 已取得 ${fmt(item.available_years)} 年`));if(arr(item.periods).length)card.append(raw('p','small muted',item.periods.join(' · ')));if(!item.complete)card.append(el('p','small muted','窗口不完整，不以其他年份或部分合计冒充完整窗口。'));for(const metric of arr(item.metrics))card.append(longTermMetric(metric,sources));if(arr(item.missing).length){card.append(el('p','small muted','缺失或不可比项目'));longTermNotes(card,item.missing,'');}windows.append(card);}area.append(windows);
    const findings=el('div','research-lt-findings');for(const [code,label] of [['support','支持'],['concern','关注'],['insufficient','不足与适用限制']]){const card=el('div','research-lt-finding');card.append(el('h4','',label));let count=0;for(const window of arr(data.windows))for(const finding of arr(window.findings)){const group=finding.status==='support'?'support':['concern','mixed'].includes(finding.status)?'concern':'insufficient';if(group!==code)continue;count++;card.append(el('p','small muted',Number(window.years)===3?'最近 3 年':'最近 5 年'),el('p','',finding.label||longTermStatus[finding.status]||'待核查'));if(arr(finding.support).length){card.append(el('p','small muted','支持依据'));longTermNotes(card,finding.support,'');}if(arr(finding.counter_evidence).length){card.append(el('p','small muted','反面证据与限制'));longTermNotes(card,finding.counter_evidence,'');}if(arr(finding.periods).length)card.append(raw('p','small muted',finding.periods.join(' · ')));longTermRefs(card,finding.source_ids,sources);}if(!count)card.append(el('p','small muted','本次没有形成此类观察，不代表已经排除相应问题。'));findings.append(card);}area.append(findings);
    const annual=el('details','research-lt-detail');annual.append(el('summary','','逐年财务数值与核验依据'));annual.append(el('p','small muted','金额为人民币元，按万或亿显示；简化自由现金流＝经营现金流－购建长期资产支付现金，并非股东收益。'));const annualGrid=el('div','research-lt-annual');for(const row of arr(data.years)){const card=el('details','research-lt-year'),head=el('summary');head.append(raw('strong','',row.report_date||String(row.year)),longTermBadge(row.status));card.append(head);if(row.announced_at)card.append(el('p','small muted',`公告日期：${row.announced_at}`));else card.append(el('p','small muted','公告日期待核验'));if(row.restatement&&row.restatement!=='none')card.append(el('p','notice warning-text','存在重述或版本变化，请先查看冲突说明。'));const values=el('dl','research-lt-values');for(const key of ['revenue','net_profit','parent_profit','adjusted_profit','op_cashflow','capex','receivables','inventory','roe','total_assets','total_liabilities','simple_free_cashflow','net_margin','debt_ratio']){const field=row.fields?.[key]||{status:'missing'};values.append(el('dt','',longTermLabels[key]||fieldNames[key]||key));const value=el('dd');value.append(el('span','',longTermValue(field)),document.createTextNode(' '),longTermBadge(field.status));values.append(value);}card.append(values);const detail=el('details','research-lt-detail');detail.append(el('summary','','查看各数值的定义、期间与来源'));for(const field of Object.values(row.fields||{}))if(field&&typeof field==='object')detail.append(longTermMetric(field,sources));card.append(detail);if(arr(row.issues).length)longTermNotes(card,row.issues,'');longTermRefs(card,row.source_ids,sources);annualGrid.append(card);}annual.append(annualGrid);area.append(annual);
    const current=el('details','research-lt-detail'),period=data.current_period||{};current.append(el('summary','','最新可比期间（与年度分开）'));current.append(longTermBadge(period.status));if(period.report_date)current.append(raw('p','',`${period.report_date} / ${period.comparison_date||'—'}`));current.append(el('p','small muted','只比较同季累计期间，不乘倍数年化，不替代年度质量。'));if(period.seasonality_note)current.append(el('p','small muted',period.seasonality_note));for(const item of arr(period.metrics))current.append(longTermMetric(item,sources));if(!arr(period.metrics).length)current.append(el('p','small muted','尚无同季可比指标。'));area.append(current);
    if(arr(data.limitations).length){const limitations=el('details','research-lt-detail');limitations.append(el('summary','','多年分析的适用边界'));longTermNotes(limitations,data.limitations,'');area.append(limitations);}if(arr(data.excluded).length){const excluded=el('details','research-lt-detail');excluded.append(el('summary','','未纳入计算的期间'));for(const item of data.excluded){excluded.append(raw('p','',`${item.report_date||'—'} · ${item.announced_at||'—'}`),el('p','small muted',item.reason||'待核查'));}area.append(excluded);}root.append(area);
  }
  function renderFinancials(root,rows){
    const area=section('财务趋势');if(!rows.length){area.append(el('p','small muted','尚未取得可比较的历史财务数据。'));root.append(area);return;}
    area.append(el('p','small muted','金额单位：人民币元，表内自动换算为万或亿。年度与中期报告需分别比较，不把半年数字当成全年。'));
    const annual=rows.filter(row=>/-12-31$/.test(row.period||row.report_period||'')).sort((a,b)=>String(a.period||a.report_period).localeCompare(String(b.period||b.report_period))).slice(-5);
    const chart=financialChart(annual);if(chart)area.append(chart);else if(annual.length>1&&!consecutiveAnnualPeriods(annual))area.append(el('p','notice warning-text','年度存在缺口，趋势图不跨缺年连线；请逐年查看实际数值。'));
    area.append(table([{label:'报告期',render:row=>row.period||row.report_period||'—'},{label:'营业收入',render:row=>shortMoney(row.revenue)},{label:'合并净利润',render:row=>shortMoney(row.net_profit)},{label:'归母净利润',render:row=>shortMoney(row.parent_profit)},{label:'经营现金流',render:row=>shortMoney(row.operating_cash_flow??row.op_cashflow)},{label:'ROE',render:row=>ratio(row.roe)},{label:'资产负债率',render:row=>ratio(row.debt_ratio)}],rows));root.append(area);
  }
  function consecutiveAnnualPeriods(rows){return rows.every((row,index)=>{const period=String(row.period||row.report_period||'');return /^\d{4}-12-31$/.test(period)&&(index===0||Number(period.slice(0,4))===Number(String(rows[index-1].period||rows[index-1].report_period).slice(0,4))+1);});}
  function financialChart(rows){
    if(rows.length<2||!consecutiveAnnualPeriods(rows)||!rows.every(row=>n(row.net_profit)!==null&&n(row.operating_cash_flow)!==null))return null;
    const wrap=el('figure','research-chart'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 660 210');svg.setAttribute('role','img');svg.setAttribute('aria-label','近年年度净利润与经营现金流趋势，详细数值见下表');
    const values=rows.flatMap(row=>[Number(row.net_profit),Number(row.operating_cash_flow)]),min=Math.min(0,...values),max=Math.max(0,...values),range=max-min||1,x=index=>45+index*570/(rows.length-1),y=value=>165-(value-min)/range*140;
    const line=document.createElementNS(svg.namespaceURI,'line');for(const [key,value] of Object.entries({x1:45,x2:615,y1:y(0),y2:y(0),stroke:'#38515f','stroke-dasharray':'4 4'}))line.setAttribute(key,String(value));svg.append(line);
    for(const [key,color] of [['net_profit','#80dbc2'],['operating_cash_flow','#a8baf6']]){const path=document.createElementNS(svg.namespaceURI,'polyline');path.setAttribute('points',rows.map((row,index)=>`${x(index)},${y(Number(row[key]))}`).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke',color);path.setAttribute('stroke-width','3');svg.append(path);}
    rows.forEach((row,index)=>{const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',String(x(index)));label.setAttribute('y','196');label.setAttribute('text-anchor','middle');label.setAttribute('fill','#9ab0c3');label.setAttribute('font-size','12');label.textContent=String(row.period||row.report_period).slice(0,4);svg.append(label);});
    const caption=el('figcaption','research-chart-legend');caption.append(el('span','research-profit','● 合并净利润'),el('span','research-cash','● 经营现金流'));wrap.append(svg,caption);return wrap;
  }
  function renderPeers(root,peers,company,screen){const area=section('同行对照'),others=peers.filter(peer=>peer.code!==company.code);if(!others.length)area.append(el('p','small muted','尚未取得同口径同行数据，暂不做行业排名。'));else {area.append(el('p','small muted','仅比较同口径资料；报告期不同的公司需要进一步核实。'));area.append(table([{label:'公司',render:row=>{const node=button(`${row.name||row.code} · ${row.code}`,()=>openCompany(row.code),'text-button');node.setAttribute('data-i18n-skip','');return node;}},{label:'财务初筛分',render:row=>scoreOf(row)===null?(row.screen?.industry_applicability?.general_ranking_allowed===false?'普通排名未开放':'资料不足'):fmt(scoreOf(row))},{label:'财务风险',render:row=>riskText(riskOf(row))},{label:'报告期',render:row=>row.report_period||row.report_date||row.screen?.report_period||'—'}],others));}root.append(area);}
  function reportText(report){if(typeof report==='string')return report;const value=report?.content||report?.text||report?.markdown||report?.summary;return typeof value==='string'?value:'';}
  function renderAI(root,data){
    const area=section('AI 挑选的原文证据 / 待核查问题'),ai=data.ai||{},report=data.report||{},configured=state.summary?.ai_status?.configured===true||state.summary?.ai_status?.available===true;
    const claims=arr(ai.claims),evidenceMode=ai.mode==='evidence_extract',published=evidenceMode&&['evidence_only','abstained'].includes(ai.status)&&claims.length>0,legacy=['succeeded','ready','complete','completed','success'].includes(ai.status);
    area.append(el('p','small muted','AI 只挑选原文证据并整理待核查问题；不构成完整公司结论，也不是买入建议。'));
    if(published){
      area.append(el('span','pill',ai.status==='abstained'?'AI 已阅读 · 证据不足，保留判断':'AI 证据整理 · 非完整公司结论'));
      area.append(el('p','small muted',`已保留 ${fmt(n(ai.accepted_count)??claims.length)} 项 · 未采用 ${fmt(ai.rejected_count)} 项`));
      if(ai.partial===true)area.append(el('p','notice warning-text','这是部分证据整理：部分条目未通过校验，或本次只读取了财报节选。'));
      if(n(ai.rejected_count)>0)area.append(el('p','small muted','未采用的模型内容不会作为结论发布，也不在这里展示。'));
      renderClaims(area,claims,allSources(data),true);
      if(ai.model)area.append(raw('p','small muted',`${ai.model} · ${time(ai.generated_at||ai.created_at)}`));
      if(ai.evidence_coverage)area.append(el('p','small muted',`本次 AI 使用 ${fmt(ai.evidence_coverage.selected_pages)} 页节选；不代表精读全部财报。`));
      if(ai.validation_note)area.append(raw('p','small muted',ai.validation_note));
    } else {
      area.append(el('p','small muted',legacy?'这是旧模式的 AI 输出，尚未通过当前证据整理校验。请重新整理证据。':ai.status==='evidence_only'?'证据整理的标记或内容不完整，暂不展示。':!configured?'AI 尚未配置。上方为财务规则筛查，尚无 AI 证据整理。':ai.error||ai.message||'可以让 AI 从已取得的资料中挑选原文证据，并列出还需核查的问题。'));
      const content=reportText(report);if(content&&report.kind!=='ai'&&report.type!=='ai'){const draft=el('details','research-rule-report');draft.append(el('summary','','查看财务规则报告'),raw('div','research-report-text',content));area.append(draft);}
    }
    if(arr(report.sections).length)for(const entry of report.sections){const block=el('div','research-report-block');block.append(raw('h4','',entry.title||entry.heading),raw('p','',entry.content||entry.text));area.append(block);}
    const job=state.job||data.job,actions=el('div','research-report-actions');if(running(job)){area.append(el('p','research-job-note',`${statusNames[job.status]||'正在运行'} · ${job.message||'正在准备研究资料…'}`));actions.append(button('停止本次研究',()=>cancelAnalysis(job.id)));}
    else {const trigger=button(!configured||state.summary?.ai_status?.status==='limit_reached'?'补齐历年财务与证据':published?'更新 AI 证据整理':'整理这家公司的财报证据',()=>analyzeCompany());actions.append(trigger);if(job?.error)area.append(raw('p','inline-error',job.error));}
    if(!configured)actions.append(el('span','small muted','当前可补齐财务资料；配置 AI 后才可整理原文证据和待核查问题。'));else if(state.summary?.ai_status?.status==='limit_reached')actions.append(el('span','small muted','当前 AI 调用次数已用完或设为 0；点击只会补齐财务资料，不会发出新的 AI 请求。'));area.append(actions);root.append(area);
  }
  function allSources(data){const rows=[...arr(data.sources),...arr(data.company?.sources),...arr(data.report?.sources),...arr(data.report?.evidence),...arr(data.screen?.sources)],index=new Map();for(const row of rows){const key=row.id||row.url||row.title;if(key)index.set(key,{...row,...(index.get(key)||{})});}return [...index.values()];}
  function renderClaims(area,claims,sources,evidenceMode=false){const categories=evidenceMode?{fact:'原文摘录',inference:'待核查推断',counterevidence:'风险原文',missing:'资料缺口'}:{fact:'事实',inference:'推断',counterevidence:'反面证据',missing:'资料缺口'},sections={business:'生意模式',competition:'竞争优势',financial:'财务质量',governance:'公司治理',valuation:'估值',risk:'风险'};for(const claim of claims){const block=el('div','research-ai-claim'),labels=el('div','research-claim-labels');labels.append(el('span',`pill ${claim.category==='fact'?'':'neutral'}`,categories[claim.category]||'研究观点'),el('span','small muted',sections[claim.section]||'待核查'));block.append(labels,raw('p','',claim.text||''));for(const citation of arr(claim.citations)){const source=sources.find(row=>String(row.id)===String(citation.source_id)),page=n(citation.page),url=safeURL(source?.url);const quote=el('blockquote','research-citation');quote.append(raw('p','',citation.quote||''));if(url&&page!==null&&Number.isInteger(page)&&page>0){const parsed=new URL(url);parsed.hash='page='+page;const link=raw('a','',`${source.title||'原始资料'} · 第 ${page} 页 ↗`);link.href=parsed.href;link.target='_blank';link.rel='noopener noreferrer';quote.append(link);}else quote.append(raw('span','small muted',`${source?.title||citation.source_id||'来源待核对'}${page!==null?` · 第 ${page} 页`:''}`));block.append(quote);}area.append(block);}}
  function renderSources(root,sources){const area=section('证据与资料来源');if(!sources.length)area.append(el('p','small muted','当前尚无可核验的来源链接；结论需要补齐原始资料。'));for(const source of sources){const item=el('div','research-source'),url=safeURL(source.url||source.link);if(url){const link=raw('a','',source.title||source.name||'查看原始资料');link.href=url;link.target='_blank';link.rel='noopener noreferrer';item.append(link);}else item.append(raw('strong','',source.title||source.name||'资料来源'));item.append(raw('p','small muted',`报告期 ${source.report_period||source.period||'待确认'} · 获取 ${time(source.fetched_at||source.retrieved_at)}${source.page?` · 第 ${source.page} 页`:''}`));if(source.note||source.excerpt)item.append(raw('p','small',source.note||source.excerpt));area.append(item);}root.append(area);}
  async function analyzeCompany(){const code=state.detailCode;if(!code||running(state.job))return;const epoch=state.epoch,request=state.detailRequest;state.job={id:'submitting',status:'queued',message:'正在提交…'};renderDetail(state.detail);try{const job=await host.api('/api/research/analyze',{method:'POST',body:{code,force:false}});if(!current(epoch)||request!==state.detailRequest)return;state.job=job;renderDetail(state.detail);if(!running(job))await reloadDetail(code,request,epoch);}catch(problem){if(current(epoch)&&request===state.detailRequest){state.job={status:'failed',error:message(problem)};renderDetail(state.detail);}}}
  async function cancelAnalysis(id){if(id==='submitting')return;const epoch=state.epoch,request=state.detailRequest;try{const job=await host.api(`/api/research/jobs/${encodeURIComponent(id)}/cancel`,{method:'POST',body:{}});if(current(epoch)&&request===state.detailRequest){state.job={...state.job,...job};renderDetail(state.detail);}}catch(problem){if(current(epoch)&&request===state.detailRequest){state.job={...state.job,error:message(problem)};renderDetail(state.detail);}}}
  async function reloadDetail(code,request,epoch){const result=await host.api('/api/research/company/'+encodeURIComponent(code));if(!current(epoch)||request!==state.detailRequest||state.detailCode!==code||!$('research-dialog').open)return;state.detail=result;state.job=result.job||state.job;renderDetail(result);}
  async function pollDetailJob(epoch){const job=state.job,code=state.detailCode,request=state.detailRequest;if(!job?.id||job.id==='submitting'||!code||!$('research-dialog').open)return;const result=await host.api(`/api/research/jobs/${encodeURIComponent(job.id)}`);if(!current(epoch)||request!==state.detailRequest||state.job?.id!==job.id)return;state.job=result;if(terminal.has(result.status))await reloadDetail(code,request,epoch);else renderDetail(state.detail);}
  // BEGIN_DEEP_RESEARCH_UI
  const deep={request:0,readRequest:0,code:null,data:null,job:null,timer:null,polling:false,error:null,cancelling:false,pending:new Set()};
  const deepSections={business:'经营模式',competition:'竞争与反面证据',financial:'财务质量',governance:'治理与审计',valuation:'估值与价格条件',risk:'风险与待核查事项'};
  const deepStatuses={completed:'本次研究已整理',partial:'部分资料报告',evidence_only:'已有原文证据',abstained:'证据不足，保留判断',insufficient_evidence:'原文资料不足',limit_reached:'等待网站调用次数恢复',unconfigured:'AI 尚未配置',failed:'本部分研究失败',not_requested:'本部分尚未研究'};
  const deepLimitExplanation='本主题当时因本网站每日调用次数不足，尚未完成 AI 阅读；这不表示公司有问题或原文证据不足。';
  function quotaReset(value){const date=new Date(value||'');if(!Number.isFinite(date.getTime()))return null;return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date);}
  function deepAllowance(data){const usage=data?.ai_usage||{},preflight=data?.preflight||{},used=n(usage.used_today),limit=n(usage.daily_limit),explicit=n(preflight.remaining??usage.remaining),remaining=explicit!==null?Math.max(0,explicit):used!==null&&limit!==null?Math.max(0,limit-used):null;return{usage,preflight,used,limit,remaining,blocked:preflight.blocked===true||(preflight.blocked!==false&&usage.configured===true&&remaining===0&&preflight.has_cached_rounds!==true),reset:quotaReset(preflight.reset_at||usage.reset_at)};}
  function openResearchSettings(){closeDeep();if($('research-dialog').open)$('research-dialog').close();const panel=$('research-settings');if(panel){panel.open=true;panel.scrollIntoView?.({behavior:'smooth',block:'start'});}$('research-daily-limit').focus?.();}
  function deepReadable(value,fallback='资料仍需核查。'){const v=typeof value==='string'?value.trim():value&&typeof value==='object'?value.text||value.message||value.question:'';return typeof v==='string'&&v&&!/^[\[{]|Traceback|Exception|^[a-z]+(?:_[a-z0-9]+)+$/i.test(v)?v:fallback;}
  function deepProblem(problem){const value=message(problem);return ['深度研究任务主体不匹配，已停止展示。','深度研究资料主体不匹配，已停止展示。'].includes(value)?value:'读取或提交失败，请刷新状态后重试；已保存报告仍会保留。';}
  function deepCurrent(code,request,epoch){return current(epoch)&&deep.code===code&&deep.request===request&&$('research-deep-dialog').open;}
  function clearDeep(){clearTimeout(deep.timer);deep.request++;deep.code=null;deep.data=null;deep.job=null;deep.error=null;deep.polling=false;deep.cancelling=false;}
  function closeDeep(){if($('research-deep-dialog')?.open)$('research-deep-dialog').close();else clearDeep();}
  function deepJob(job,code){if(!job)return null;if(job.kind!=='deep'||String(job.code)!==code||typeof job.id!=='string')throw Error('深度研究任务主体不匹配，已停止展示。');return job;}
  function deepReport(){const report=deep.data?.report;return report&&report.version==='company-deep-research-1.0'&&String(report.company_code)===deep.code?report:null;}
  function deepPageRanges(values){const pages=[...new Set(arr(values).filter(v=>Number.isInteger(v)&&v>0))].sort((a,b)=>a-b),ranges=[];for(let i=0;i<pages.length;i++){const first=pages[i];let last=first;while(pages[i+1]===last+1)last=pages[++i];ranges.push(first===last?String(first):`${first}–${last}`);}return ranges.join(', ');}
  function deepReportStatus(report){const parts=arr(report.sections),planned=savedRounds(report.scope?.ai_rounds_planned);return report.status==='completed'&&planned!==null&&n(report.scope?.ai_rounds_completed)===planned&&parts.length===6&&Object.keys(deepSections).every(key=>parts.filter(p=>p?.key===key&&p.status==='evidence_only').length===1)?'completed':'partial';}
  function deepPlannedRounds(data){return configuredRounds(running(deep.job)?deep.job.ai_rounds_planned??deep.job.deep_research_rounds??data?.preflight?.max_requests??state.summary?.settings?.deep_research_rounds:data?.preflight?.max_requests??state.summary?.settings?.deep_research_rounds);}
  function deepSources(report){return allSources({sources:report.sources,report:report.financial_report?.report||report.financial_report});}
  function deepField(root,label,value){const row=el('p','small research-deep-field');row.append(el('span','muted',label),document.createTextNode(' '),raw('span','',value??'—'));root.append(row);}
  function deepSchedule(){clearTimeout(deep.timer);if(deep.code&&$('research-deep-dialog').open&&running(deep.job)&&deep.job.id!=='submitting')deep.timer=setTimeout(pollDeep,2500);}
  async function loadDeep(code,request,epoch){
    const read=++deep.readRequest;
    try{const data=await host.api('/api/research/deep/'+encodeURIComponent(code));if(!deepCurrent(code,request,epoch)||read!==deep.readRequest)return;
      if(String(data?.company?.code)!==code)throw Error('深度研究资料主体不匹配，已停止展示。');
      const job=deepJob(data.job,code);deep.data=data;deep.job=job;deep.error=null;renderDeep();deepSchedule();
      if(job&&terminal.has(job.status)){const changed=await loadLibraryCount();if(deepCurrent(code,request,epoch)&&state.listMode==='library'&&changed)await loadCompanies();}
    }catch(problem){if(deepCurrent(code,request,epoch)&&read===deep.readRequest){deep.error=deepProblem(problem);renderDeep();deepSchedule();}}
  }
  async function openDeep(value){
    const code=String(value||'');if(!/^[0-9]{6}$/.test(code)||!state.active)return;
    clearDeep();deep.code=code;const request=deep.request,epoch=state.epoch;
    if($('research-dialog').open)$('research-dialog').close();
    $('research-deep-title').textContent=code;$('research-deep-title').setAttribute('data-i18n-skip','');
    replace($('research-deep-body'),empty('正在读取深度研究','查看已有报告和任务状态，不会自动发起 AI 调用。'));
    if(!$('research-deep-dialog').open)$('research-deep-dialog').showModal();
    await loadDeep(code,request,epoch);
  }
  function renderDeep(){
    const root=$('research-deep-body'),data=deep.data,code=deep.code,request=deep.request,epoch=state.epoch,planned=deepPlannedRounds(data);
    if(!code||!$('research-deep-dialog').open)return;replace(root);
    $('research-deep-title').textContent=data?`${data.company.name||code} · ${code}`:code;
    root.append(el('p','research-detail-lead','深度研究'),el('p','small muted','围绕经营、竞争、财务、治理、估值与风险，整理已取得的原文证据、反证和待核查问题。'));
    root.append(el('p','notice research-deep-info',planned===3?'每次研究最多安排 3 轮 AI 调用，计入现有每日上限；已成功且资料未变化的轮次可复用，不重复计费。':'每次研究最多安排 6 轮 AI 调用，计入现有每日上限；已成功且资料未变化的轮次可复用，不重复计费。'));
    root.append(el('p','small muted','仅覆盖实际取得并提取的资料，不表示浏览全网或精读所有财报。研究结果不是买入建议。'));
    if(deep.error){root.append(el('p','inline-error',deep.error));const retry=button('刷新研究状态',()=>loadDeep(code,request,epoch));retry.disabled=deep.polling;root.append(retry);}
    if(!data)return;
    const {usage,preflight,used,limit,remaining,blocked,reset}=deepAllowance(data);
    const quota=el('div','research-deep-quota');deepField(quota,'网站次数统计日期',usage.day);deepField(quota,'今日 AI 调用',used!==null&&limit!==null?`${fmt(used)} / ${fmt(limit)}`:'—');deepField(quota,'剩余调用次数',remaining===null?'—':fmt(remaining));
    if(reset)deepField(quota,'次数恢复时间（北京时间）',reset);else deepField(quota,'次数恢复规则','每天北京时间 00:00 重新计数');
    quota.append(el('p','small muted','这里统计本网站每日请求次数，不是 DeepSeek 账户余额或 token 余额；达到上限不代表 API 没钱。'));
    quota.append(el('p','small muted',usage.configured!==true?'AI 尚未配置；开始后仅整理可用资料，不能生成已完成的 AI 研究。':blocked?'今日网站调用次数已用尽或上限设为 0，尚未发出新的 AI 请求。可等待恢复或自行调整每日上限。':remaining===0?'已有成功轮次可能可以复用；继续后会核对资料与缓存，未命中的轮次等待调用次数恢复。':remaining!==null&&remaining<planned?(planned===3?'剩余额度不足 3 轮；可继续未完成主题，已成功且资料未变的轮次不重复调用。':'剩余额度不足 6 轮；可继续未完成主题，已成功且资料未变的轮次不重复调用。'):'实际调用次数取决于可用资料、已有轮次和实时额度。'));
    if(limit===0)quota.append(el('p','small muted','每日上限为 0 时，跨日后仍不会发出 AI 请求；请先在研究设置中设定上限。'));root.append(quota);
    const report=deepReport();if(data.report&&!report)root.append(el('p','notice warning-text','深度研究报告的版本或主体不匹配，暂不展示。'));
    const busy=deep.pending.has(code)||running(deep.job),actions=el('div','research-report-actions research-deep-actions');
    if(busy){
      const job=deep.job||{status:'queued'},notice=el('div','research-deep-progress');notice.setAttribute('role','status');
      notice.append(el('strong','',deep.pending.has(code)?'正在提交深度研究…':job.cancel_requested||job.status==='cancelling'?'正在停止，等待当前步骤结束…':statusNames[job.status]||'正在运行'));
      if(job.message)notice.append(el('p','small',deepReadable(job.message,'正在整理资料，请稍候。')));
      const progress=el('progress');progress.max=100;if(n(job.progress)!==null)progress.value=Math.max(0,Math.min(100,n(job.progress)));notice.append(progress);
      deepField(notice,'本次 AI 轮次',`${fmt(job.ai_rounds_completed??0)} / ${fmt(job.ai_rounds_planned??job.deep_research_rounds??planned)}`);
      notice.append(el('p','small muted','关闭弹窗不会停止后台研究。要中止后续步骤，请使用停止按钮。'));
      if(job.id&&job.id!=='submitting'){const cancel=button('停止深度研究',()=>cancelDeep(code,request,epoch,job.id));cancel.disabled=deep.cancelling||job.cancel_requested===true||job.status==='cancelling';actions.append(cancel);}root.append(notice);
    }else{
      if(deep.job){const status=deep.job.status;root.append(el('p',status==='failed'?'inline-error':'small muted',deep.job.phase==='budget_blocked'?'等待调用次数恢复':statusNames[status]||'任务状态待核查'));if(deep.job.error)root.append(el('p','inline-error','本次研究未能完成。已保存报告仍可查看，刷新状态后可重试。'));else if(deep.job.message)root.append(el('p','small muted',deepReadable(deep.job.message)));if(deep.job.report_preserved===true)root.append(el('p','notice warning-text','本次任务未替换报告，下方保留的是此前已保存的研究。'));}
      const resume=report&&deepReportStatus(report)==='partial'||preflight.has_cached_rounds===true;
      const start=button(blocked?'等待调用次数恢复':resume?'继续未完成研究':report?'更新研究':'开始深度研究',()=>startDeep(code,request,epoch,Boolean(data.report)));start.disabled=blocked;actions.append(start);
      actions.append(button('刷新研究状态',()=>loadDeep(code,request,epoch),'text-button'));
    }
    actions.append(button('查看调用设置',openResearchSettings,'button secondary'));
    if(report)actions.append(button('下载 Markdown',()=>downloadDeep(report)));
    root.append(actions);
    const reviewSupplement=data.financial_supplement;
    const reviewSupplementValid=report&&reviewSupplement?.status==='available'&&reviewSupplement.report?.company?.code===report.company_code&&reviewSupplement.source_report_generated_at===report.generated_at;
    const reviewFinancial=reviewSupplementValid?reviewSupplement.report:report?.financial_report?.report||report?.financial_report;
    if(window.ETFCompanyReview)root.append(window.ETFCompanyReview.render({companyCode:code,financialReport:reviewFinancial,deepReport:report,dynamic:data.dynamic_evaluation,sources:allSources({sources:[...arr(report?.sources),...arr(report?.financial_sources),...(reviewSupplementValid?arr(reviewSupplement.sources):[])],report:reviewFinancial})}));
    if(window.ETFQualityChecks)root.append(window.ETFQualityChecks.render({model:data.quality_checks,companyCode:code,sources:allSources({sources:[...arr(report?.sources),...arr(report?.financial_sources),...(reviewSupplementValid?arr(reviewSupplement.sources):[])],report:reviewFinancial})}));
    root.append(window.ETFResearchDynamic.render(data.dynamic_evaluation,{companyCode:code,savedReport:Boolean(report)}));
    appendValuation(root,code,deep.request);
    if(!report){root.append(el('p','small muted',blocked?'尚无已保存的深度研究报告。本次不会生成空报告；次数可用后再开始研究。':'尚无已保存的深度研究报告。点击开始后，资料范围和未完成主题会逐项显示。'));return;}
    if(savedRounds(report.scope?.ai_rounds_planned)!==planned)root.append(el('p','small muted','已保存报告保留生成时的轮次；上方轮数用于新任务，不代表旧报告已补足。'));
    renderDeepReport(root,report,data.financial_supplement);
  }
  function renderDeepReport(root,report,supplement){
    const supplemental=supplement?.status==='available'&&supplement.report?.company?.code===report.company_code&&supplement.source_report_generated_at===report.generated_at;
    const sources=allSources({sources:[...deepSources(report),...arr(report.financial_sources),...(supplemental?arr(supplement.sources):[])],report:supplemental?supplement.report:{}}),scope=report.scope||{},status=deepReportStatus(report),intro=section('本次报告与资料范围');
    intro.append(raw('h4','',report.title||report.company_name||report.company_code),el('span','pill neutral',deepStatuses[status]));
    deepField(intro,'报告生成时间',time(report.generated_at));deepField(intro,'已取得文档',fmt(scope.documents));deepField(intro,'已提取正文文档',fmt(scope.extracted_documents));deepField(intro,'实际提取页数',fmt(scope.pages));deepField(intro,'完成的 AI 轮次',`${fmt(scope.ai_rounds_completed)} / ${fmt(savedRounds(scope.ai_rounds_planned))}`);
    if(report.summary)intro.append(raw('p','research-deep-summary',deepReadable(report.summary,'')));
    if(status==='partial')intro.append(el('p','notice warning-text','这是部分资料报告。未完成主题、额度限制与来源缺口不会被视为已完成研究。'));
    if(arr(report.sections).some(part=>part?.status==='limit_reached'))intro.append(el('p','notice warning-text','报告中标记等待次数恢复的主题，当时尚未完成 AI 阅读；这是本网站的调用次数限制，不是公司的负面结论，也不能据此判断 DeepSeek 余额不足。'));
    if(report.status==='completed'&&status!=='completed')intro.append(el('p','notice warning-text','报告完成标记与资料范围不一致，按部分资料展示。'));
    if(arr(scope.limitations).length)notes(intro,scope.limitations.map(x=>deepReadable(x)),'');root.append(intro);
    const supplied=new Map(arr(report.sections).filter(x=>x&&typeof x==='object').map(x=>[x.key,x]));
    for(const [key,title] of Object.entries(deepSections)){const part=supplied.get(key),area=section(title);area.setAttribute('data-deep-section',key);
      area.append(el('span','pill neutral',deepStatuses[part?.status]||'本部分尚未研究'));
      if(!part){area.append(el('p','small muted','该主题尚无已保存的研究，不能据此判断没有风险。'));root.append(area);continue;}
      if(part.status==='limit_reached'){area.append(el('p','small muted',deepLimitExplanation));root.append(area);continue;}
      if(part.status==='unconfigured'){area.append(el('p','small muted','当时尚未配置 AI 服务，未执行本主题阅读；请配置服务后继续研究。'));root.append(area);continue;}
      if(part.status==='not_requested'){area.append(el('p','small muted','本主题尚未安排 AI 阅读，不能当作已阅读后发现证据不足。'));root.append(area);continue;}
      if(part.summary)area.append(raw('p','',deepReadable(part.summary,'')));
      if(['evidence_only','abstained'].includes(part.status))renderClaims(area,arr(part.claims).filter(x=>x&&typeof x==='object'),sources,true);
      else if(arr(part.claims).length)area.append(el('p','small muted','本部分尚未完成证据校验，不展示模型观点。'));
      if(arr(part.questions).length){area.append(el('h4','','待核查问题'));notes(area,part.questions.map(x=>deepReadable(x)),'');}
      root.append(area);
    }
    const originalFinancial=report.financial_report?.report||report.financial_report;
    const financial=supplemental?supplement.report:originalFinancial;
    if(financial&&typeof financial==='object'){const d=el('details','research-deep-financial');d.append(el('summary','','展开财务分析与原始依据'));
      if(supplemental){
        d.append(el('p','notice','已从本次深研保存的资料补算财务分析，无需再次调用 AI。'));
        d.append(el('p','small muted','下方为补算的财务结果；上方 AI 原文摘录及其生成时间保持不变，不代表旧 AI 已使用这些数值。'));
        deepField(d,'财务资料获取时间',time(supplement.source_fetched_at));deepField(d,'财务资料截止日期',supplement.financial_as_of);
      }else if(report.financial_context){
        d.append(el('p','small muted','财务分析使用本次深度研究取得的数据，按各模块规则计算。'));
        deepField(d,'财务资料获取时间',time(report.financial_context.source_fetched_at));deepField(d,'财务资料截止日期',report.financial_context.financial_as_of);
      }else if(supplement?.status==='unavailable'){
        d.append(el('p','notice warning-text','暂未找到可安全补算的同批财务资料。下方保留原报告快照；显示缺资料不等于公司没有年报。'));
      }
      renderDeepFinancial(d,financial,sources,report.company_code);
      if(supplemental&&originalFinancial){const original=el('details','research-deep-original-financial');original.append(el('summary','','查看原报告保存的财务快照'));original.append(el('p','small muted','这是修复前保存的原始快照，可能尚未包含历年数据。'));renderDeepFinancial(original,originalFinancial,deepSources(report),report.company_code);d.append(original);}
      root.append(d);}
    const sourceArea=section('研究来源与披露日期');if(!sources.length)sourceArea.append(el('p','small muted','当前尚无可核验的来源链接；结论需要补齐原始资料。'));
    for(const source of sources){const item=el('div','research-source'),url=safeURL(source.url||source.link);if(url){const a=raw('a','',source.title||source.id||'资料来源');a.href=url;a.target='_blank';a.rel='noopener noreferrer';item.append(a);}else item.append(raw('strong','',source.title||source.id||'资料来源'));
      deepField(item,'披露日期',source.published_at||source.announced_at||'—');if(source.fetched_at||source.retrieved_at)deepField(item,'资料获取时间',time(source.fetched_at||source.retrieved_at));if(source.report_period||source.period)deepField(item,'财务报告期',source.report_period||source.period);
      if(arr(source.pages).length)deepField(item,'已提取页码',deepPageRanges(source.pages));sourceArea.append(item);}root.append(sourceArea);
  }
  function renderDeepFinancial(root,financial,sources,code){
    renderLongTerm(root,financial.quality?.long_term,sources,false);
    root.append(window.ETFResearchDebtGovernance.render(financial.debt_governance,{sources,companyCode:code}),window.ETFResearchBusinessCapital.render(financial.business_capital,{sources,companyCode:code}),window.ETFResearchIndustry.render(financial.industry_profile,{sources,companyCode:code,screen:financial.summary||{},currentContext:financial.price_quality_panel?.current_industry_context}),window.ETFResearchPriceQuality.render(financial.price_quality_panel,{sources,companyCode:code}));
  }
  async function startDeep(code,request,epoch,force){
    if(!deepCurrent(code,request,epoch)||deep.pending.has(code)||running(deep.job)||deepAllowance(deep.data).blocked)return;
    deep.pending.add(code);deep.readRequest++;deep.error=null;deep.job={id:'submitting',kind:'deep',code,status:'queued'};renderDeep();
    try{const result=await host.api('/api/research/deep',{method:'POST',body:{code,force}});if(!deepCurrent(code,request,epoch))return;deep.job=deepJob(result,code);renderDeep();if(terminal.has(result.status))await loadDeep(code,request,epoch);else deepSchedule();}
    catch(problem){if(deepCurrent(code,request,epoch)){deep.job=null;deep.error=deepProblem(problem);}}
    finally{deep.pending.delete(code);if(deepCurrent(code,request,epoch))renderDeep();else if(current(epoch)&&deep.code===code&&$('research-deep-dialog').open)await loadDeep(code,deep.request,epoch);}
  }
  async function cancelDeep(code,request,epoch,id){
    if(!deepCurrent(code,request,epoch)||deep.cancelling||deep.job?.id!==id||!running(deep.job))return;deep.cancelling=true;deep.readRequest++;deep.error=null;renderDeep();
    try{const result=await host.api(`/api/research/jobs/${encodeURIComponent(id)}/cancel`,{method:'POST',body:{}});if(!deepCurrent(code,request,epoch))return;deep.job=deepJob(result,code);deep.error=null;if(terminal.has(result.status))await loadDeep(code,request,epoch);else deepSchedule();}
    catch(problem){if(deepCurrent(code,request,epoch))deep.error=deepProblem(problem);}
    finally{if(deepCurrent(code,request,epoch)){deep.cancelling=false;renderDeep();}}
  }
  async function pollDeep(){
    const code=deep.code,request=deep.request,epoch=state.epoch,job=deep.job,read=deep.readRequest;
    if(!deepCurrent(code,request,epoch)||deep.polling||!running(job)||job.id==='submitting')return;deep.polling=true;
    try{const result=await host.api('/api/research/jobs/'+encodeURIComponent(job.id));if(!deepCurrent(code,request,epoch)||deep.job?.id!==job.id||read!==deep.readRequest)return;deep.job=deepJob(result,code);deep.error=null;if(terminal.has(result.status))await loadDeep(code,request,epoch);else renderDeep();}
    catch(problem){if(deepCurrent(code,request,epoch)&&read===deep.readRequest){deep.error=deepProblem(problem);renderDeep();}}
    finally{if(deepCurrent(code,request,epoch)){deep.polling=false;deepSchedule();}}
  }
  function deepMarkdown(report){
    const escape=value=>text(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/[\\`*_\[\]{}]/g,'\\$&');
    const scope=report.scope||{},rows=[`# ${escape(report.title||report.company_name||report.company_code)}`,'',`${escape(report.company_name)} · ${escape(report.company_code)}`,`生成时间：${escape(report.generated_at)}`,`状态：${escape(deepStatuses[deepReportStatus(report)])}`,'','仅覆盖实际取得的资料；不是全网研究、完整精读或买入建议。','',escape(deepReadable(report.summary,'')),'','## 资料范围',`文档：${fmt(scope.documents)}；已提取文档：${fmt(scope.extracted_documents)}；页数：${fmt(scope.pages)}；AI 轮次：${fmt(scope.ai_rounds_completed)} / ${fmt(savedRounds(scope.ai_rounds_planned))}`, ...arr(scope.limitations).map(x=>'- '+escape(deepReadable(x))), ''];
    const sources=deepSources(report);for(const part of arr(report.sections)){rows.push(`## ${escape(deepSections[part.key]||part.title||'待核查')}`,`状态：${escape(deepStatuses[part.status]||part.status)}`,escape(part.status==='limit_reached'?deepLimitExplanation:part.summary),'');
      if(part.status==='limit_reached')continue;
      if(['evidence_only','abstained'].includes(part.status))for(const claim of arr(part.claims)){rows.push(escape(claim.text));for(const citation of arr(claim.citations)){rows.push(...text(citation.quote).split('\n').map(line=>'> '+escape(line)));const source=sources.find(s=>String(s.id)===String(citation.source_id)),url=safeURL(source?.url);if(url){const link=new URL(url);if(Number.isInteger(n(citation.page))&&n(citation.page)>0)link.hash='page='+n(citation.page);rows.push(`[${escape(source.title||citation.source_id)}](<${link.href}>)`);}}rows.push('');}
      if(arr(part.questions).length){rows.push('### 待核查问题');for(const question of part.questions)rows.push('- '+escape(deepReadable(question)));}}
    rows.push('','## 资料来源');for(const source of sources){const url=safeURL(source.url||source.link);rows.push(url?`- [${escape(source.title||source.id)}](<${url}>)`:'- '+escape(source.title||source.id));rows.push(`  披露日期：${escape(source.published_at||source.announced_at||'待确认')}；报告期：${escape(source.report_period||source.period||'待确认')}；获取时间：${escape(source.fetched_at||source.retrieved_at||'待确认')}`);}
    if(report.financial_report)rows.push('','## 财务分析原始依据','财务原始依据与各模块详表请在网页“展开财务分析与原始依据”中查看。');
    return rows.join('\n')+'\n';
  }
  function downloadDeep(report){const blob=new Blob(['\ufeff',deepMarkdown(report)],{type:'text/markdown;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`公司深度研究_${String(report.company_code).replace(/[^0-9A-Za-z_-]/g,'')}_${String(report.generated_at||'').slice(0,10).replace(/[^0-9-]/g,'')}.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  $('research-deep-close').addEventListener('click',closeDeep);$('research-deep-dialog').addEventListener('close',clearDeep);
  // END_DEEP_RESEARCH_UI
  function filterChanged(){clearTimeout(state.queryTimer);state.listRequest++;state.moreLoading=false;renderSortBasis();state.queryTimer=setTimeout(()=>loadCompanies(false),180);}
  for(const [id,mode] of [['research-tab-all','all'],['research-tab-library','library']]){$(id).addEventListener('click',()=>selectResearchList(mode));$(id).addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?'all':event.key==='End'?'library':mode==='all'?'library':'all';selectResearchList(next);$(next==='all'?'research-tab-all':'research-tab-library').focus?.();});}
  $('research-scan').addEventListener('click',scan);$('research-cancel').addEventListener('click',cancelScan);$('research-refresh').addEventListener('click',()=>refresh(true,true));$('research-settings-form').addEventListener('submit',saveSettings);
  $('research-settings-form').addEventListener('input',event=>{state.settingsDirty=true;state.settingsRevision++;if(event.target!==$('research-base-url'))$('research-settings-message').textContent='设置已修改，保存后生效。';});
  $('research-provider').addEventListener('change',providerChanged);
  $('research-base-url').addEventListener('input',guardEndpointKey);$('research-base-url').addEventListener('change',guardEndpointKey);
  for(const id of ['research-query','research-industry','research-candidate','research-sort'])$(id).addEventListener(id==='research-query'?'input':'change',filterChanged);
  $('research-more').addEventListener('click',()=>loadCompanies(true));$('research-detail-close').addEventListener('click',()=>$('research-dialog').close());$('research-dialog').addEventListener('close',()=>{state.detailRequest++;state.detailCode=null;state.detail=null;state.job=null;});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.active)refresh(false);});
  window.ETFCompanyResearch={setActive,openDeep,deepMarkdown};
  if(!['dynamic','quality','risk','valuation','code'].includes($('research-sort').value))$('research-sort').value='dynamic';renderSortBasis();
  if(host.isAuthenticated()&&host.page()==='research')setActive(true);
})();
