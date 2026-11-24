'use strict';
// Read-only, grouped historical candidates. Research metrics never come from live signal rows.
// Frozen source: etf-management-report/work/六候选独立核对.json
// SHA256 26c60071a20b26268935fc8cdc6043fbbda236fae978341256a907bae227bd0a
(() => {
  const candidates = Object.freeze([
    {code:'F0',floor:0,cagr:.1537708230216872,drawdown:.16039061975458846,minCagr:.09269110659973512,maxDrawdown:.24943560350451743},
    {code:'F10',floor:10,cagr:.1492453386147936,drawdown:.15360861232876832,minCagr:.08828043164811405,maxDrawdown:.24200245261082354},
    {code:'F20',floor:20,cagr:.14565944605132675,drawdown:.15613990803648403,minCagr:.08816081966555567,maxDrawdown:.23270108255008082},
    {code:'L0',floor:0,cagr:.21399751385093357,drawdown:.20508738157164885,minCagr:.15149104671335323,maxDrawdown:.2922403912581414},
    {code:'L10',floor:10,cagr:.20887465418234585,drawdown:.21110044595973332,minCagr:.1482569478562752,maxDrawdown:.284432312742706},
    {code:'L20',floor:20,cagr:.20449631737984442,drawdown:.21628363798136563,minCagr:.14622417632020213,maxDrawdown:.2782947759507597}
  ].map(Object.freeze));
  const words = {
    zh:{
      title:'重点观察历史候选',familyF:'F 类 · 分阶段配置',familyL:'L 类 · 四态融合',
      nameF:n=>`分阶段配置 · 股票底仓${n}%`,nameL:n=>`四态融合 · 股票底仓${n}%`,
      floor:n=>`股票均转弱时，预设合计股票底仓 ${n}%；仍须满足原预热与执行条件。`,
      cagr:'基线年化',drawdown:'基线最大回撤',period:'历史研究：2017-08-03 — 2026-09-24',
      signalDate:'最近信号日期',livePeriod:'当前参考组合从 2023-01-03 开始，操作与上方研究区间分开。',
      loading:'正在读取信号',failed:'读取失败 · 等待更新',missing:'等待信号计算',ambiguous:'信号重复 · 等待核对',
      stale:'旧信号 · 等待更新',unknown:'信号尚未确认',noActivity:'暂无可核对的模拟成交记录',
      activity:n=>`该确认日模拟成交 ${n} 笔`,noTrades:'该确认日无模拟成交',oldActivity:'历史回看：',
      prior:'旧意向：',intent:'当前意向：',day:'成交确认日：',detail:'查看操作依据',oldDetail:'回看旧操作依据',
      selection:'入选依据与压力范围',selectionText:'五个历史情景中，年化均高于自身过去波动对照，回撤幅度均更小。',
      comparison:'对照持创业板 ETF＋现金，按策略与目标 ETF 过去 63 日波动比每月调整仓位；资产集合不同，也不保证实际风险相同。',
      minCagr:'五情景最低年化',maxDrawdown:'五情景最大回撤',cost3:'费用 3 倍',delay2:'费用 2 倍＋晚一次可执行机会',
      extremes:'两个极值可能来自不同情景，不代表同一条收益路径；压力范围不是未来损失上限。',
      scenarios:'五情景：原费用与执行、费用 2 倍、费用 3 倍、晚一次可执行机会、费用 2 倍并延迟。',
      costs:'历史基线：10 万元现金起步；佣金 0.03%（最低 5 元），单边滑点 0.02%，100 份整手，现金不计息，期末按市值结算。',
      limitation:'统计证据不足，尚无未见前瞻验证；六个相关版本不构成六份独立证据。先观察，不代表未来最优。',
      ruleF:'F 类：创业板用原 50 周趋势与 SKDJ/TRIX，银行用原 SKDJ；黄金、国债分别受趋势条件约束。',
      ruleL:'L 类：创业板和银行双多时按 60/40，单多时配置该股票 ETF；双空按预设股票底仓，其余黄金或现金，短周采用保守确认。',
      floorLimit:'底仓是条件下的股票预算，不是收益目标或固定创业板仓位。',
      states:{buy:'待买入（尚未成交）',sell:'待卖出（尚未成交）',rebalance:'待调仓（尚未成交）',hold:'继续持有',cash:'保持空仓',wait:'等待确认'}
    },
    en:{
      title:'Historical candidates to observe',familyF:'F · Staged allocation',familyL:'L · Four-state allocation',
      nameF:n=>`Staged allocation · ${n}% equity floor`,nameL:n=>`Four-state allocation · ${n}% equity floor`,
      floor:n=>`When both equity signals weaken, the preset combined equity floor is ${n}%; original warm-up and execution conditions still apply.`,
      cagr:'Baseline CAGR',drawdown:'Baseline max drawdown',period:'Historical study: 2017-08-03 — 2026-09-24',
      signalDate:'Latest signal date',livePeriod:'The current reference portfolio starts on 2023-01-03, separately from the study above.',
      loading:'Loading signals',failed:'Load failed · awaiting update',missing:'Awaiting signal calculation',ambiguous:'Duplicate signals · review needed',
      stale:'Old signal · awaiting update',unknown:'Signal not yet confirmed',noActivity:'No verifiable simulated trade record',
      activity:n=>`${n} simulated trades on that confirmed day`,noTrades:'No simulated trades on that confirmed day',oldActivity:'Historical review: ',
      prior:'Previous intention: ',intent:'Current intention: ',day:'Trade confirmation day: ',detail:'View operation evidence',oldDetail:'Review previous operation evidence',
      selection:'Selection evidence and stress scenarios',selectionText:'Across all five historical scenarios, CAGR exceeded the own-past-volatility comparison and drawdown was smaller.',
      comparison:'The comparison holds ChiNext ETF plus cash, adjusting its weight monthly using the ratio of the strategy’s to the target ETF’s past 63-day volatility. The asset sets differ, and equal realized risk is not assured.',
      minCagr:'Lowest CAGR across five scenarios',maxDrawdown:'Largest drawdown across five scenarios',cost3:'3× costs',delay2:'2× costs + one executable opportunity later',
      extremes:'The two extremes may come from different scenarios; they are not one return path. These stresses do not cap future losses.',
      scenarios:'Five scenarios: original costs/execution, 2× costs, 3× costs, one executable opportunity later, and 2× costs with that delay.',
      costs:'Historical baseline: CNY 100,000 cash; 0.03% commission (CNY 5 minimum), 0.02% one-way slippage, 100-unit lots, no cash interest, marked to market at the end.',
      limitation:'Statistical evidence is insufficient and unseen forward validation is unavailable. Six related versions are not six independent pieces of evidence. Observe first; future superiority is not established.',
      ruleF:'F: ChiNext uses the original 50-week trend and SKDJ/TRIX; banks use the original SKDJ. Gold and government bonds have their own trend conditions.',
      ruleL:'L: 60/40 ChiNext/banks when both are bullish, the single bullish equity ETF otherwise; when both are bearish, use the preset equity floor and gold or cash. Short weeks use conservative confirmation.',
      floorLimit:'The floor is a conditional equity budget, not a return target or fixed ChiNext allocation.',
      states:{buy:'Pending buy (not executed)',sell:'Pending sell (not executed)',rebalance:'Pending rebalance (not executed)',hold:'Continue holding',cash:'Remain in cash',wait:'Await confirmation'}
    }
  };
  const groups = {
    original:{zh:'四资产',en:'Four assets',signalGroups:['original']},
    top5:{zh:'创业板五策略',en:'ChiNext five',signalGroups:['top5']},
    seven:{zh:'七组合',en:'Seven combinations',signalGroups:['seven']},
    overseas:{zh:'海外',en:'Overseas',signalGroups:['nasdaq','hangseng','hangtech']}
  };
  const groupWords = {
    zh:{
      nav:'按策略组查看历史候选',title:'分组查看历史候选',
      count:n=>`${n} 个候选`,empty:'本组尚无已核对的候选研究，全部策略仍可在策略信号查看。',
      scope:'各组使用各自的研究区间、对照与筛选条件，成绩不作跨组高低排名。刷新只更新交易信号，不会重新筛选候选。',
      original:'四资产 · 六个相关版本；保留五种成本和延迟情景的原研究依据。',
      top5:'创业板五策略 · 展示既有多周期研究中筛出的观察候选；采用卡片标注的研究区间与条件。',
      seven:'七组合 · 展示既有组合研究中的观察候选；A 类与 B 类的资金分配及执行频率不同。',
      overseas:'海外 · 纳指、恒生、恒生科技分别甄选，按卡片所列市场理解成绩。',
      research:'历史研究：',metric:'历史年化',drawdown:'历史最大回撤',selection:'历史入选依据与限制',
      selectionMissing:'入选依据尚待补充。',limitMissing:'研究适用范围尚待补充，不据此作出策略优劣判断。',
      live:'当前参考信号与历史研究成绩分开展示。',market:'研究市场：',
      settlement:{terminal_liquidation:'期末结算：清算持仓。',terminal_mark_to_market:'期末结算：持仓按市值计价。'},
      costs:(capital,commission,minimum,slippage,interest)=>`研究成本：初始本金 ${capital} 元；佣金 ${commission}%（最低 ${minimum} 元），单边滑点 ${slippage}%；现金利息 ${interest}%。`
    },
    en:{
      nav:'Historical candidates by strategy group',title:'Historical candidates by group',
      count:n=>`${n} candidates`,empty:'No verified candidate study is available for this group yet. All strategies remain in Strategy signals.',
      scope:'Each group uses its own study period, comparison and selection criteria. Results are not ranked across groups. Refresh updates signals only; it does not reselect candidates.',
      original:'Four assets · six related variants, retaining the original evidence from five cost and execution-delay scenarios.',
      top5:'ChiNext five · observation candidates from the existing multi-timeframe study; use the period and conditions on each card.',
      seven:'Seven combinations · observation candidates from the existing combination study. A and B use different capital allocations and execution frequencies.',
      overseas:'Overseas · Nasdaq, Hang Seng and Hang Seng Tech are selected separately. Read each result in its stated market.',
      research:'Historical study: ',metric:'Historical CAGR',drawdown:'Historical max drawdown',selection:'Historical selection evidence and limits',
      selectionMissing:'Selection evidence is not yet available.',limitMissing:'The study scope is incomplete; strategy superiority cannot be inferred.',
      live:'Current reference signals are shown separately from historical study results.',market:'Study market: ',
      settlement:{terminal_liquidation:'Terminal settlement: liquidate remaining positions.',terminal_mark_to_market:'Terminal settlement: value remaining positions at market.'},
      costs:(capital,commission,minimum,slippage,interest)=>`Study costs: CNY ${capital} initial capital; ${commission}% commission (CNY ${minimum} minimum), ${slippage}% one-way slippage; ${interest}% cash interest.`
    }
  };
  const views = new WeakMap();
  const str = x => typeof x === 'string' ? x : '';
  const array = x => Array.isArray(x) ? x : [];
  const pct = x => typeof x === 'number' && Number.isFinite(x) ? (x * 100).toFixed(2) + '%' : '—';
  const drawdownPct = x => typeof x === 'number' && Number.isFinite(x) && x >= 0 ? (x > 0 ? '−' : '') + pct(x) : '—';
  const language = () => window.ETF_I18n?.language === 'en' || (!window.ETF_I18n && str(document.documentElement.lang).startsWith('en')) ? 'en' : 'zh';
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  function date(value) {
    const s = str(value), d = s.slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || d > today()) return null;
    if (s.length > 10 && (!/^[T ](?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?$/.test(s.slice(10)) || !Number.isFinite(new Date(s.replace(' ', 'T')).valueOf()))) return null;
    const parsed = new Date(d + 'T00:00:00Z');
    return Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === d ? d : null;
  }
  function el(tag, className, parent) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (parent) parent.append(node);
    return node;
  }
  function researchRecords() {
    const records = array(window.ETFFeaturedResearch?.records);
    const valid = records.filter(r => r && ['top5','seven','overseas'].includes(r.category) && groups[r.category].signalGroups.includes(r.group) && /^[A-Za-z0-9_]+$/.test(str(r.code)));
    // Ambiguous research identities are withheld, just as duplicate live rows are.
    return valid.filter(r => valid.filter(other => other.group === r.group && other.code === r.code).length === 1).map(r => Object.freeze({...r}));
  }
  function makeSupplementalCard(candidate, view, parent) {
    const card = el('article', 'featured-card', parent);
    card.setAttribute('data-featured-code', candidate.code);
    card.setAttribute('data-featured-group', candidate.group);
    const header = el('div', 'featured-card-head', card);
    el('span', 'featured-code', header).textContent = candidate.code;
    const family = el('span', 'featured-family', header), title = el('h3', 'featured-title', card);
    const floor = el('p', 'featured-note featured-floor', card);
    const metrics = el('dl', 'featured-metrics', card);
    const cagrBox = el('div', '', metrics), cagrLabel = el('dt', '', cagrBox), cagr = el('dd', '', cagrBox);
    const drawdownBox = el('div', '', metrics), drawdownLabel = el('dt', '', drawdownBox), drawdown = el('dd', '', drawdownBox);
    cagr.textContent = pct(candidate.cagr);
    drawdown.textContent = drawdownPct(candidate.drawdown);
    const period = el('p', 'featured-period', card);
    const signal = el('section', 'featured-signal', card), dateLabel = el('span', 'featured-note', signal), signalDate = el('strong', 'featured-signal-date', signal);
    const badge = el('span', 'featured-badge', signal), intention = el('p', 'featured-note', signal), activity = el('p', 'featured-activity', signal), livePeriod = el('p', 'featured-period', signal);
    const button = el('button', 'featured-detail-button', card);
    button.type = 'button';
    const create = el('button', 'featured-detail-button featured-create-button', card);create.type='button';create.addEventListener('click',()=>view.input.onCreate?.({group:card.dataset.featuredGroup,code:candidate.code}));
    const details = el('details', 'featured-evidence', card), summary = el('summary', '', details);
    const selection = el('p', 'featured-note', details), costs = el('p', 'featured-note', details), settlement = el('p', 'featured-note', details), limitation = el('p', 'featured-limitation', details);
    const nodes = {candidate,card,family,title,floor,cagrLabel,drawdownLabel,period,dateLabel,signalDate,badge,intention,activity,livePeriod,button,create,details,summary,selection,costs,settlement,limitation,row:null};
    button.addEventListener('click', () => {if (!button.disabled && nodes.row && typeof view.input.onDetail === 'function') view.input.onDetail(nodes.row);});
    return nodes;
  }
  function makeCard(candidate, view, parent) {
    const card = el('article', 'featured-card', parent);
    card.setAttribute('data-featured-code', candidate.code);
    card.setAttribute('data-featured-group', 'original');
    const header = el('div', 'featured-card-head', card);
    el('span', 'featured-code', header).textContent = candidate.code;
    const family = el('span', 'featured-family', header);
    const title = el('h3', 'featured-title', card);
    const floor = el('p', 'featured-note featured-floor', card);
    const metrics = el('dl', 'featured-metrics', card);
    const cagrBox = el('div', '', metrics), cagrLabel = el('dt', '', cagrBox), cagr = el('dd', '', cagrBox);
    const drawdownBox = el('div', '', metrics), drawdownLabel = el('dt', '', drawdownBox), drawdown = el('dd', '', drawdownBox);
    cagr.textContent = pct(candidate.cagr);
    drawdown.textContent = '−' + pct(candidate.drawdown);
    const period = el('p', 'featured-period', card);
    const signal = el('section', 'featured-signal', card), dateLabel = el('span', 'featured-note', signal), signalDate = el('strong', 'featured-signal-date', signal);
    const badge = el('span', 'featured-badge', signal), intention = el('p', 'featured-note', signal), activity = el('p', 'featured-activity', signal), livePeriod = el('p', 'featured-period', signal);
    const button = el('button', 'featured-detail-button', card);
    button.type = 'button';
    const create = el('button', 'featured-detail-button featured-create-button', card);create.type='button';create.addEventListener('click',()=>view.input.onCreate?.({group:card.dataset.featuredGroup,code:candidate.code}));
    const details = el('details', 'featured-evidence', card), summary = el('summary', '', details);
    const selection = el('p', 'featured-note', details), comparison = el('p', 'featured-note', details);
    const stress = el('dl', 'featured-stress', details);
    const minBox = el('div', '', stress), minLabel = el('dt', '', minBox), minValue = el('dd', '', minBox), minScenario = el('small', '', minBox);
    const maxBox = el('div', '', stress), maxLabel = el('dt', '', maxBox), maxValue = el('dd', '', maxBox), maxScenario = el('small', '', maxBox);
    minValue.textContent = pct(candidate.minCagr);
    maxValue.textContent = '−' + pct(candidate.maxDrawdown);
    const extremes = el('p', 'featured-note', details), scenarios = el('p', 'featured-note', details), costs = el('p', 'featured-note', details), rule = el('p', 'featured-note', details), floorLimit = el('p', 'featured-note', details), limitation = el('p', 'featured-limitation', details);
    const nodes = {candidate,card,family,title,floor,cagrLabel,drawdownLabel,period,dateLabel,signalDate,badge,intention,activity,livePeriod,button,create,details,summary,selection,comparison,minLabel,minScenario,maxLabel,maxScenario,extremes,scenarios,costs,rule,floorLimit,limitation,row:null};
    button.addEventListener('click', () => {if (!button.disabled && nodes.row && typeof view.input.onDetail === 'function') view.input.onDetail(nodes.row);});
    return nodes;
  }
  function update(view) {
    const input = view.input, lang = language(), t = words[lang], g = groupWords[lang], rows = array(input.rows);
    view.root.setAttribute('aria-label', g.title);
    view.navigation.setAttribute('aria-label', g.nav);
    view.scope.textContent = g.scope;
    view.groupScope.textContent = g[view.category];
    for (const [category, button] of Object.entries(view.buttons)) {
      const count = view.records[category].length;
      button.textContent = groups[category][lang] + ' · ' + g.count(count);
      button.classList.toggle('featured-category-active', category === view.category);
      button.setAttribute('aria-pressed', String(category === view.category));
    }
    const active = view.panels[view.category];
    for (const [category, panel] of Object.entries(view.panels)) panel.root.hidden = category !== view.category;
    active.empty.textContent = g.empty;
    active.empty.hidden = active.cards.length > 0;
    for (const n of active.cards) {
      n.create.textContent=lang==='en'?'Create a paper account with this strategy':'用此策略建立模拟账户';n.create.disabled=typeof input.onCreate!=='function';
      const c = n.candidate, original = view.category === 'original', isF = c.code[0] === 'F', group = original ? 'original' : c.group;
      const matches = rows.filter(row => row && row.group === group && row.code === c.code);
      const row = matches.length === 1 ? matches[0] : null;
      const asOf = date(row?.as_of), hasSignal = Boolean(row && asOf && Object.hasOwn(t.states, row.status));
      const current = Boolean(hasSignal && input.loaded === true && !input.error && row.current === true && row.source_status === 'confirmed' && !row.error && !row.source_warning);
      // A stale card must also open a stale detail; never mutate the shared signal row.
      const oldReason = input.error || row?.error ? t.failed : row?.source_status === 'unknown' ? t.unknown : t.stale;
      n.row = hasSignal ? current ? row : {...row,current:false,status:'wait',label:t.states.wait,previous_status:row.previous_status || row.status,source_warning:oldReason} : null;
      n.family.textContent = original ? isF ? t.familyF : t.familyL : str(c[lang === 'en' ? 'marketEn' : 'marketZh']) || groups[view.category][lang];
      n.title.textContent = original ? (isF ? t.nameF : t.nameL)(c.floor) : str(c[lang === 'en' ? 'titleEn' : 'titleZh']) || c.code;
      n.floor.textContent = original ? t.floor(c.floor) : g.market + n.family.textContent;
      n.cagrLabel.textContent = original ? t.cagr : g.metric;
      n.drawdownLabel.textContent = original ? t.drawdown : g.drawdown;
      n.period.textContent = original ? t.period : g.research + (date(c.start) || '—') + ' — ' + (date(c.end) || '—');
      n.dateLabel.textContent = t.signalDate;
      n.signalDate.textContent = asOf || '—';
      n.badge.className = 'featured-badge' + (current ? ' featured-badge-current' : ' featured-badge-wait');
      n.badge.textContent = input.error ? t.failed : input.loaded !== true ? t.loading : matches.length > 1 ? t.ambiguous : !hasSignal ? t.missing : current ? t.states[row.status] : row.source_status === 'unknown' ? t.unknown : t.stale;
      const prior = row?.previous_status || row?.status;
      n.intention.textContent = !current && hasSignal && Object.hasOwn(t.states, prior) ? t.prior + t.states[prior] : '';
      n.intention.hidden = !n.intention.textContent;
      const activity = row?.activity, day = date(activity?.day), hasTrades = Array.isArray(activity?.day_trades);
      n.activity.textContent = hasSignal && day === asOf && hasTrades ? (current ? '' : t.oldActivity) + t.day + day + ' · ' + (activity.day_trades.length ? t.activity(activity.day_trades.length) : t.noTrades) : t.noActivity;
      n.livePeriod.textContent = original ? t.livePeriod : g.live;
      n.button.textContent = hasSignal && !current ? t.oldDetail : t.detail;
      n.button.disabled = !hasSignal || typeof input.onDetail !== 'function';
      n.button.setAttribute('aria-label', n.family.textContent + ' · ' + c.code + ' · ' + n.button.textContent);
      n.summary.textContent = original ? t.selection : g.selection;
      n.selection.textContent = original ? t.selectionText : str(c[lang === 'en' ? 'selectionEn' : 'selectionZh']) || g.selectionMissing;
      n.limitation.textContent = original ? t.limitation : str(c[lang === 'en' ? 'limitationEn' : 'limitationZh']) || g.limitMissing;
      if (!original) {
        const costValues = [c.initial_capital,c.commission_rate,c.minimum_commission,c.one_way_slippage,c.cash_interest];
        const hasCosts = costValues.every(value => typeof value === 'number' && Number.isFinite(value) && value >= 0);
        const compactPercent = value => String(Number((value * 100).toFixed(4)));
        n.costs.textContent = hasCosts ? g.costs(new Intl.NumberFormat(lang === 'en' ? 'en-US' : 'zh-CN').format(c.initial_capital),compactPercent(c.commission_rate),String(c.minimum_commission),compactPercent(c.one_way_slippage),compactPercent(c.cash_interest)) : '';
        n.costs.hidden = !hasCosts;
        n.settlement.textContent = Object.hasOwn(g.settlement, c.settlement) ? g.settlement[c.settlement] : '';
        n.settlement.hidden = !n.settlement.textContent;
        continue;
      }
      n.comparison.textContent = t.comparison;
      n.minLabel.textContent = t.minCagr;
      n.minScenario.textContent = isF ? t.cost3 : t.delay2;
      n.maxLabel.textContent = t.maxDrawdown;
      n.maxScenario.textContent = t.cost3;
      n.extremes.textContent = t.extremes;
      n.scenarios.textContent = t.scenarios;
      n.costs.textContent = t.costs;
      n.rule.textContent = isF ? t.ruleF : t.ruleL;
      n.floorLimit.textContent = t.floorLimit;
    }
  }
  function ensurePanel(view, category) {
    if (view.panels[category]) return;
    const root = el('section', 'featured-group-panel', view.root);
    root.setAttribute('data-featured-category-panel', category);
    const grid = el('div', 'featured-card-grid', root), empty = el('p', 'featured-note featured-empty', root);
    const cards = view.records[category].map(candidate => category === 'original' ? makeCard(candidate, view, grid) : makeSupplementalCard(candidate, view, grid));
    view.panels[category] = {root,cards,empty};
  }
  function render(input = {}) {
    const root = input.root;
    if (!root || typeof root.append !== 'function') throw new TypeError('Featured strategies require a root element.');
    let view = views.get(root);
    if (!view) {
      root.classList.add('featured-list');
      root.setAttribute('data-i18n-skip', '');
      const supplemental = researchRecords();
      view = {root,input,category:'original',panels:{},buttons:{},records:{original:candidates}};
      for (const category of ['top5','seven','overseas']) view.records[category] = supplemental.filter(r => r.category === category);
      view.navigation = el('div', 'featured-categories', root);
      view.navigation.setAttribute('role', 'group');
      for (const category of Object.keys(groups)) {
        const button = el('button', 'featured-category', view.navigation);
        button.type = 'button';
        button.setAttribute('data-featured-category', category);
        button.addEventListener('click', () => {view.category = category;ensurePanel(view, category);update(view);});
        view.buttons[category] = button;
      }
      view.scope = el('p', 'featured-note featured-groups-scope', root);
      view.groupScope = el('p', 'featured-note featured-group-scope', root);
      ensurePanel(view, 'original');
      views.set(root, view);
    }
    view.input = input;
    update(view);
    return root;
  }
  // Parent owns polling and etf-language-change; repeated renders preserve details/focus.
  window.ETFFeaturedStrategies = Object.freeze({render});
})();
