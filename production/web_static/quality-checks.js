'use strict';
// Read-only presentation of explicit experimental checks from a saved report.
(() => {
  const VERSION = 'quality-checks-1.0';
  const statuses = ['pass', 'watch', 'fail', 'insufficient', 'not_applicable'];
  const overallStates = ['ready', 'partial', 'specialist', 'unavailable'];
  const labels = {
    pass: ['符合试验条件', 'Meets experimental condition'],
    watch: ['需核查', 'Needs review'],
    fail: ['未达试验条件', 'Does not meet experimental condition'],
    insufficient: ['资料不足', 'Insufficient information'],
    not_applicable: ['专项判断', 'Specialist assessment'],
  };
  const pair = (zh, en) => [zh, en];
  const obj = x => x && typeof x === 'object' && !Array.isArray(x) ? x : {};
  const list = x => Array.isArray(x) ? x : [];
  const text = x => typeof x === 'string' ? x : '';
  const bilingual = x => Array.isArray(x) && x.length === 2 && x.every(t => typeof t === 'string' && t.trim());
  const display = (x, fallback) => bilingual(x) ? x.slice() : fallback;
  const unique = x => [...new Set(x)];
  function day(value) {
    const raw = text(value), d = raw.slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return null;
    if (raw.length !== 10 && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw) || !Number.isFinite(new Date(raw).valueOf()))) return null;
    const date = new Date(d + 'T00:00:00Z');
    return Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === d ? d : null;
  }
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  function safeURL(value) {
    try {
      const url = new URL(text(value));
      return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch (_) { return null; }
  }
  function buildModel(input = {}) {
    const data = obj(obj(input).model), code = text(obj(input).companyCode);
    const asOf = day(data.as_of), reportDate = day(data.report_date);
    const output = {
      version: VERSION, code, available: false, status: 'unavailable', as_of: null,
      report_date: null, experimental: true, rules_version: VERSION,
      summary: pair('尚无可核对的逐项检查资料。', 'No validated item-by-item checks are available.'),
      checks: [], data_notes: [], counts: Object.fromEntries(statuses.map(s => [s, 0])),
    };
    if (!/^\d{6}$/.test(code) || data.code !== code || data.version !== VERSION || data.schema_version !== undefined && data.schema_version !== VERSION || data.rules_version !== VERSION || data.experimental !== true || !overallStates.includes(data.status) || !asOf || asOf > today() || !reportDate || reportDate > asOf) {
      output.data_notes.push(pair('公司主体、版本或日期未通过核对，暂不展示条件判断。', 'The company identity, version or dates could not be validated; condition judgments are withheld.'));
      return output;
    }
    output.available = true;
    output.status = data.status;
    output.as_of = asOf;
    output.report_date = reportDate;
    output.summary = display(data.summary, output.summary);
    output.data_notes = list(data.data_notes).filter(bilingual).map(x => x.slice());
    const sources = new Map();
    // Ambiguous duplicate IDs never inherit whichever URL appeared first.
    for (const source of list(obj(input).sources)) {
      const id = text(obj(source).id);
      if (id) sources.set(id, sources.has(id) ? null : source);
    }
    function reference(id) {
      const source = obj(sources.get(id));
      const dates = [source.published_at, source.announced_at].filter(value => value !== undefined && value !== null && value !== '');
      const located = source.company_code === code && dates.length > 0 && dates.every(value => day(value) && day(value) <= asOf);
      return {id, title: located ? text(source.title) || id : id, url: located ? safeURL(source.url) : null};
    }
    const keyCounts = new Map();
    for (const check of list(data.checks)) {
      const key = text(obj(check).key);
      keyCounts.set(key, (keyCounts.get(key) || 0) + 1);
    }
    for (const [index, raw] of list(data.checks).entries()) {
      const check = obj(raw), key = text(check.key);
      let status = statuses.includes(check.status) ? check.status : 'insufficient';
      const missing = list(check.missing).map(text).filter(t => t.trim());
      const periods = list(check.periods).map(text);
      const sourceIDs = unique(list(check.source_ids).map(text).filter(t => t.trim()));
      const fieldsValid = ['title', 'rule', 'value_text', 'reason', 'review_trigger'].every(field => bilingual(check[field]));
      const arraysValid = Array.isArray(check.missing) && check.missing.every(v => typeof v === 'string' && v.trim()) && Array.isArray(check.periods) && unique(check.periods).length === check.periods.length && check.periods.every(p => typeof p === 'string' && day(p) === p && p <= reportDate) && Array.isArray(check.source_ids) && check.source_ids.every(v => typeof v === 'string' && v.trim());
      const structurallyValid = Boolean(key && keyCounts.get(key) === 1 && fieldsValid && arraysValid && statuses.includes(check.status));
      const validationNotes = [];
      if (!structurallyValid) {
        status = 'insufficient';
        validationNotes.push(pair('此项字段或期间未通过校验，条件结果暂不可用。', 'This item has invalid fields or periods; its condition result is unavailable.'));
      }
      if (status === 'pass' && (missing.length || !periods.length || !sourceIDs.length)) {
        status = 'insufficient';
        validationNotes.push(pair('尚有资料、期间或来源标识缺口，不能显示为符合条件。', 'Information, periods or source identifiers remain missing; this item cannot be shown as meeting the condition.'));
      }
      if (data.status === 'specialist') status = 'not_applicable';
      if (data.status === 'unavailable') status = 'insufficient';
      output.checks.push({
        key: key || 'invalid-' + index, status,
        title: display(check.title, pair('待核查项目', 'Item requiring review')),
        rule: display(check.rule, pair('检查条件尚未提供。', 'The condition is not available.')),
        value_text: display(check.value_text, pair('资料不足', 'Insufficient information')),
        reason: display(check.reason, pair('尚不能判断。', 'No assessment is available.')),
        review_trigger: display(check.review_trigger, pair('补齐可核对资料后再检查。', 'Recheck after obtaining verifiable information.')),
        periods: structurallyValid ? periods.slice() : [],
        missing, sources: sourceIDs.map(reference), validation_notes: validationNotes,
      });
      output.counts[status]++;
    }
    if (!output.checks.length) {
      output.status = data.status === 'specialist' ? 'specialist' : 'unavailable';
      output.data_notes.push(pair('尚无逐项结果，空白不表示符合条件或风险已排除。', 'There are no item results; an empty list does not mean conditions are met or risks are cleared.'));
    }
    return output;
  }
  function render(input = {}) {
    const model = buildModel(input), root = document.createElement('section'), translations = [];
    root.className = 'research-detail-section quality-checks';
    root.setAttribute('data-i18n-skip', '');
    const english = () => text(document.documentElement.lang).startsWith('en') || window.ETF_I18n?.language === 'en';
    function el(tag, cls, value) {
      const n = document.createElement(tag);
      if (cls) n.className = cls;
      if (value !== undefined) n.textContent = String(value);
      return n;
    }
    function tr(tag, cls, value) {
      const n = el(tag, cls);
      translations.push({n, value});
      n.textContent = value[english() ? 1 : 0];
      return n;
    }
    function field(parent, label, value) {
      const row = el('div', 'quality-checks-field');
      row.append(tr('strong', '', label), Array.isArray(value) ? tr('span', '', value) : el('span', '', value));
      parent.append(row);
    }
    root.append(tr('h4', '', pair('质量与现金逐项检查', 'Quality and cash checks')));
    root.append(tr('p', 'quality-checks-caveat', pair('试验规则 · 只读研究参考。逐项条件不是公司总评级，也不代表官方核验、审计结论或买卖建议。', 'Experimental rules · Read-only research reference. Item conditions are not an overall company rating, official verification, an audit conclusion or a trading recommendation.')));
    root.append(tr('p', 'quality-checks-summary', model.summary));
    if (model.available) {
      const meta = el('div', 'quality-checks-meta');
      field(meta, pair('研究截止', 'Research cutoff'), model.as_of);
      field(meta, pair('财报期', 'Financial period'), model.report_date);
      field(meta, pair('试验规则版本', 'Experimental rules version'), model.rules_version);
      root.append(meta);
    }
    const counts = el('ul', 'quality-checks-counts');
    counts.setAttribute('aria-label', english() ? 'Item counts' : '逐项数量');
    if (model.checks.length) {
      for (const status of statuses) counts.append(tr('li', 'quality-checks-count', pair(`${labels[status][0]} ${model.counts[status]}`, `${labels[status][1]} ${model.counts[status]}`)));
      root.append(counts);
      const headings = el('div', 'quality-checks-columns');
      headings.setAttribute('aria-hidden', 'true');
      for (const value of [pair('检查项目 / 条件', 'Item / condition'), pair('本期结果', 'Reported result'), pair('逐项状态', 'Item status')]) headings.append(tr('span', '', value));
      root.append(headings);
    }
    for (const check of model.checks) {
      const details = el('details', 'quality-checks-row');
      details.setAttribute('data-check-key', check.key);
      details.setAttribute('data-check-status', check.status);
      const summary = el('summary', 'quality-checks-row-summary');
      const condition = el('span', 'quality-checks-condition');
      condition.append(tr('strong', '', check.title), tr('span', 'quality-checks-rule', check.rule), tr('span', 'quality-checks-expand', pair('展开依据与缺口', 'Expand evidence and gaps')));
      summary.append(condition, tr('span', 'quality-checks-value', check.value_text), tr('span', 'quality-checks-status quality-checks-status-' + check.status, labels[check.status]));
      details.append(summary);
      const content = el('div', 'quality-checks-detail');
      field(content, pair('条件说明', 'Condition'), check.rule);
      field(content, pair('结果解释', 'Explanation'), check.reason);
      field(content, pair('对应期间', 'Periods'), check.periods.length ? check.periods.join(' / ') : pair('尚无可核对期间', 'No validated periods'));
      field(content, pair('复核触发条件', 'When to review'), check.review_trigger);
      for (const note of check.validation_notes) content.append(tr('p', 'quality-checks-warning', note));
      if (check.missing.length) {
        field(content, pair('仍缺少的资料', 'Missing information'), pair('以下缺口仍需补齐，不按零值或已通过处理。', 'These gaps still require evidence; they are not treated as zero or as passed.'));
        const gaps = el('ul', 'quality-checks-missing');
        for (const gap of check.missing) gaps.append(el('li', '', gap));
        content.append(gaps);
      }
      const sources = el('div', 'quality-checks-sources');
      sources.append(tr('strong', '', pair('来源引用', 'Source references')));
      if (!check.sources.length) sources.append(tr('p', 'quality-checks-note', pair('尚无来源标识，需回到原始资料核对。', 'No source identifiers are available; review the original material.')));
      for (const source of check.sources) {
        const sourceRow = el('div', 'quality-checks-source');
        if (source.url) {
          const link = el('a', '', source.id + (source.title !== source.id ? ' · ' + source.title : ''));
          link.href = source.url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          sourceRow.append(link);
        } else sourceRow.append(el('span', '', source.id), tr('span', 'quality-checks-note', pair(' · 链接待核对（来源主体、日期或地址尚未完整匹配）', ' · Link unavailable (source identity, date or URL is not fully matched)')));
        sources.append(sourceRow);
      }
      content.append(sources);
      details.append(content);
      root.append(details);
    }
    for (const note of model.data_notes) root.append(tr('p', 'quality-checks-note', note));
    root.append(tr('p', 'quality-checks-note', pair('数量只汇总上述逐项状态，不相加为总分。数据缺口不自动等于公司的负面事实，单项符合条件也不能抵消其他风险。', 'Counts summarize the item states only; they are not added into a score. Missing data is not automatically an adverse company fact, and meeting one condition does not offset other risks.')));
    let connected = false, disposed = false, observer = null;
    function update() {
      if (disposed) return;
      const en = english();
      for (const {n, value} of translations) n.textContent = value[en ? 1 : 0];
      root.setAttribute('aria-label', en ? 'Quality and cash checks' : '质量与现金逐项检查');
      counts.setAttribute('aria-label', en ? 'Item counts' : '逐项数量');
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      document.removeEventListener?.('etf-language-change', update);
      observer?.disconnect();
    }
    document.addEventListener?.('etf-language-change', update);
    if (typeof MutationObserver === 'function') {
      observer = new MutationObserver(() => {
        if (root.isConnected) connected = true;
        else if (connected) dispose();
      });
      observer.observe(document.documentElement, {childList: true, subtree: true});
    }
    root.dispose = dispose;
    update();
    return root;
  }
  window.ETFQualityChecks = {buildModel, render, version: VERSION};
})();
