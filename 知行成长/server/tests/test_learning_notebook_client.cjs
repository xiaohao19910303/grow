const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
function element(tag) {
  return {tag, children: [], textContent: '', value: '', append(...items) {this.children.push(...items);},
    replaceChildren(...items) {this.children = items;}, setAttribute(key, value) {this[key] = value;}};
}
function descendants(node) {return [node, ...node.children.flatMap(descendants)];}
function text(node) {return descendants(node).map(n => n.textContent).join(' ');}
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const root = element('div'), pending = [];
  const ctx = {window: {Account: {ready: Promise.resolve(), user: {id: 'owner'}}},
    document: {getElementById() {return root;}, createElement: element}, URLSearchParams, AbortController,
    fetch(url, options) {return new Promise(resolve => pending.push({url, options, resolve(data) {resolve({ok: true, json: async () => data});}}));}};
  vm.createContext(ctx); vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/learning-notebook.js'), 'utf8'), ctx);
  return {root, pending, ctx, ui: ctx.window.LearningNotebook};
}
function result(preview) {return {total: 1, items: [{title: '课程', kind: 'biaoda', course_id: 'one.md', module_label: '表达', preview,
  answer_count: 1, updated_at: '2026-10-25T10:00:00Z', target: {kind: 'study', module: 'biaoda', course: 'one.md'}}]};}
(async () => {
  const {root, pending, ctx, ui} = setup();
  const initial = ui.enter(); await flush(); pending[0].resolve(result('最初笔记')); await initial;
  assert(text(root).includes('最初笔记'));
  const input = descendants(root).find(n => n.tag === 'input'), form = descendants(root).find(n => n.tag === 'form');
  input.value = '旧词'; form.onsubmit({preventDefault() {}}); await flush();
  input.value = '新词'; form.onsubmit({preventDefault() {}}); await flush();
  assert(pending[1].options.signal.aborted);
  pending[2].resolve(result('新的查询结果')); await flush();
  pending[1].resolve(result('过时查询结果')); await flush();
  assert(text(root).includes('新的查询结果')); assert(!text(root).includes('过时查询结果'));
  assert(pending[2].url.includes(encodeURIComponent('新词')));
  const leaving = ui.enter(); await flush(); ui.leave();
  assert(pending[3].options.signal.aborted); pending[3].resolve(result('离开后的迟到内容')); await leaving;
  assert(!text(root).includes('离开后的迟到内容'));
  const switched = ui.enter(); await flush(); ctx.window.Account.user = {id: 'another'};
  pending[4].resolve(result('旧账号的私人笔记')); await switched;
  assert(!text(root).includes('旧账号的私人笔记'));
  console.log('Notebook client checks passed: superseded requests, navigation cancellation and account changes.');
})().catch(error => {console.error(error); process.exitCode = 1;});
