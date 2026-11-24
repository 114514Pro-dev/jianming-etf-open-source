"""Run bank-rule presentation against the real JS with a read-only tiny DOM.

The VM never initializes the application, makes network calls, loads a ledger,
or submits an order. Its sole injected export exposes otherwise private display
functions; all assertions exercise the shipped source, not a copied helper.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'production' / 'web_static' / 'realtime-paper.js'


def node_executable():
    found = shutil.which('node')
    if found:
        return found
    if os.name == 'nt':
        runtime_root = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'WindowsApps'
        candidates = sorted(runtime_root.glob('OpenAI.CodexPrimaryRuntime*/dependencies/node/bin/node.exe'))
        if candidates:
            return str(candidates[-1])
    return None


HARNESS = r"""
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const file = process.argv[1];
const original = fs.readFileSync(file, 'utf8');
const closing = original.lastIndexOf('})();');
if (closing < 0) throw new Error('expected IIFE in realtime-paper.js');
const source = original.slice(0, closing) +
  'window.__bankRuleTest = {bankRule, renderIndicatorTradingRules, state};\n' +
  original.slice(closing);

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.className = '';
    this.ownText = '';
    this.classList = {add(){}, remove(){}, toggle(){}};
  }
  append(...items) {
    for (const item of items) {
      if (item instanceof Element) this.children.push(item);
      else {const text = new Element('#text'); text.ownText = String(item); this.children.push(text);}
    }
  }
  replaceChildren(...items) {this.children = []; this.ownText = ''; this.append(...items);}
  setAttribute(key, value) {this.attributes[key] = String(value);}
  getAttribute(key) {return this.attributes[key] ?? null;}
  addEventListener() {}
  set textContent(value) {this.children = []; this.ownText = String(value);}
  get textContent() {return this.ownText + this.children.map(child => child.textContent).join('');}
}
const document = {createElement: tag => new Element(tag), addEventListener(){}, getElementById(){return null;}};
const window = {};
const sandbox = {document, window, console, URL, Intl, Date, Map, Set, Symbol,
  setTimeout(){throw new Error('display tests must not schedule background work');}, clearTimeout(){},
  fetch(){throw new Error('display tests must not access network');}};
const localeFile = require('node:path').join(require('node:path').dirname(file), 'locale-en.js');
vm.runInNewContext(fs.readFileSync(localeFile, 'utf8'), sandbox, {filename:localeFile, timeout:2000});
vm.runInNewContext(source, sandbox, {filename:file, timeout:2000});
const api = window.__bankRuleTest;
const DAY = '2026-11-13';
const baseRule = {contract_version:'d0-bank-entry-rule-v1', source:'saved_signal',
  mode:'conditional', status:'confirmed', entry_k_limit:50, active:true, day:DAY,
  weekly_status:'confirmed', week_end:DAY, available:DAY, weekly_close:2.9, ma:3};
const fixtures = {
  active50: {...baseRule},
  inactive40: {...baseRule, active:false, entry_k_limit:40, weekly_close:3.1},
  legacy40: {...baseRule, mode:'legacy', status:'legacy', active:false, entry_k_limit:40,
    weekly_status:'unknown', week_end:null, available:null, weekly_close:null, ma:null},
  unknown: {...baseRule, status:'unknown', active:null, entry_k_limit:null,
    weekly_status:'unknown', week_end:null, available:null, weekly_close:null, ma:null},
  invalid: {...baseRule, status:'invalid', active:null, entry_k_limit:null},
  wrongDay: {...baseRule, day:'2026-11-12'},
  missing: null,
};
function collectedRows(root) {
  const out = [];
  function visit(node) {
    const label = node.children.find(child => child.tagName === 'DT');
    const value = node.children.find(child => child.tagName === 'DD');
    if (label && value) out.push({label:label.textContent, value:value.textContent});
    node.children.forEach(visit);
  }
  visit(root);
  return out;
}
function exercise(rule, strategy = 'D0') {
  api.state.strategy = strategy;
  api.state.data = {signal:{confirmed_day:DAY}};
  const commentary = {confirmed_day:DAY, state:{ready:true, long:true, eligible:true,
    entry:false, exit:false, holding_days:4}, momentum:{score_ready:true},
    pairs:[{id:'skdj', left:48, right:45, position:'above'}]};
  if (rule !== null) commentary.bank_rule = rule;
  const result = api.bankRule(commentary, DAY);
  const target = new Element('div');
  api.renderIndicatorTradingRules(target, {symbol:'sh512800'}, commentary);
  return {mode:result.mode, limit:result.limit, rule:result.rule,
    rows:collectedRows(target), text:target.textContent};
}
const output = {};
for (const [key, rule] of Object.entries(fixtures)) output[key] = exercise(rule);
output.wwWithConditional50 = exercise(fixtures.active50, 'D0I-BOND-WW');
output.wwMissing = exercise(null, 'D0I-BOND-WW');
window.ETF_I18n = {language:'en'};
output.english50 = exercise(fixtures.active50);
process.stdout.write(JSON.stringify(output));
"""


class D0BankRuleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = node_executable()
        if not node:
            raise unittest.SkipTest('Node.js is not available for JS presentation contract checks')
        process = subprocess.run([node, '-e', HARNESS, str(SOURCE)], capture_output=True,
                                 text=True, encoding='utf-8', timeout=20, check=False)
        if process.returncode:
            raise AssertionError('real browser script VM failed:\n' + process.stderr)
        cls.results = json.loads(process.stdout)

    def threshold_rows(self, case, limit):
        return [row for row in self.results[case]['rows'] if f'K≤{limit}' in row['label']]

    def test_confirmed_conditional50_displays50_and_accepts_k48_in_checklist(self):
        result = self.results['active50']
        self.assertEqual((result['mode'], result['limit']), ('conditional', 50))
        rows = self.threshold_rows('active50', 50)
        self.assertTrue(rows, result['rows'])
        self.assertTrue(any(row['value'] == '满足' for row in rows), rows)
        self.assertFalse(self.threshold_rows('active50', 40))

    def test_confirmed_inactive_rule_displays40_and_k48_fails_checklist(self):
        result = self.results['inactive40']
        self.assertEqual((result['mode'], result['limit']), ('conditional', 40))
        rows = self.threshold_rows('inactive40', 40)
        self.assertTrue(rows, result['rows'])
        self.assertTrue(any(row['value'] == '未满足' for row in rows), rows)
        self.assertFalse(self.threshold_rows('inactive40', 50))

    def test_old_saved_rule_remains_legacy40(self):
        result = self.results['legacy40']
        self.assertEqual((result['mode'], result['limit']), ('legacy', 40))
        self.assertTrue(self.threshold_rows('legacy40', 40))
        self.assertFalse(self.threshold_rows('legacy40', 50))

    def test_unknown_and_missing_evidence_never_silently_become40(self):
        for case in ('unknown', 'missing'):
            with self.subTest(case=case):
                result = self.results[case]
                self.assertEqual(result['mode'], 'conditional')
                self.assertIsNone(result['limit'])
                self.assertFalse(self.threshold_rows(case, 40))
                self.assertFalse(self.threshold_rows(case, 50))
                self.assertIn('待核对', result['text'])

    def test_invalid_or_different_confirmed_day_cannot_display_a_valid_limit(self):
        for case in ('invalid', 'wrongDay'):
            with self.subTest(case=case):
                result = self.results[case]
                self.assertEqual(result['mode'], 'conditional')
                self.assertIsNone(result['limit'])
                self.assertFalse(self.threshold_rows(case, 40))
                self.assertFalse(self.threshold_rows(case, 50))
                self.assertIn('待核对', result['text'])

    def test_ww_forces_legacy40_even_if_given_conditional50_or_no_rule(self):
        for case in ('wwWithConditional50', 'wwMissing'):
            with self.subTest(case=case):
                result = self.results[case]
                self.assertEqual((result['mode'], result['limit']), ('legacy', 40))
                self.assertTrue(self.threshold_rows(case, 40))
                self.assertFalse(self.threshold_rows(case, 50))

    def test_saved_signal_entry_is_not_recomputed_from_current_kd_position(self):
        result = self.results['active50']
        saved_rows = [row for row in result['rows'] if '保存' in row['label'] and '入场信号' in row['label']]
        self.assertTrue(saved_rows, result['rows'])
        self.assertTrue(all(row['value'] == '未满足' for row in saved_rows), saved_rows)

    def test_english_locale_loads_and_translates_the_current_limit(self):
        result = self.results['english50']
        self.assertIn('current K≤50', result['text'])
        self.assertIn('strictly below its 50-week average', result['text'])
        self.assertTrue(any(row['label'] == 'A new reference position requires K≤50'
                            for row in result['rows']))


if __name__ == '__main__':
    unittest.main()
