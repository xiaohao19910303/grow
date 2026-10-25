const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/theme.js', 'utf8');
function setup({saved = null, dark = false, denyRead = false, denyWrite = false} = {}) {
  const attributes = new Map(), button = {textContent: '', setAttribute() {}}, writes = [];
  let onSystemChange;
  const media = {matches: dark, addEventListener(type, fn) {onSystemChange = fn;}};
  const storage = {
    getItem() {return saved;},
    setItem(key, value) {if (denyWrite) throw Error('quota exceeded'); saved = value; writes.push([key, value]);},
  };
  const ctx = {
    window: {matchMedia() {return media;}},
    document: {
      documentElement: {getAttribute(key) {return attributes.get(key) ?? null;}, setAttribute(key, value) {attributes.set(key, value);}},
      getElementById() {return button;},
    },
  };
  Object.defineProperty(ctx, 'localStorage', {get() {if (denyRead) throw Error('denied getter'); return storage;}});
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return {ctx, attributes, button, writes, media, changed() {onSystemChange();}};
}
for (const saved of ['light', 'dark']) {
  const ui = setup({saved});
  assert.equal(ui.attributes.get('data-theme'), saved);
  ui.ctx.toggleTheme();
  const next = saved === 'dark' ? 'light' : 'dark';
  assert.equal(ui.attributes.get('data-theme'), next);
  assert.deepEqual(ui.writes, [['theme', next]]);
}
const system = setup({dark: true});
assert.equal(system.button.textContent, '☀️');
system.media.matches = false; system.changed();
assert.equal(system.button.textContent, '🌙');
const denied = setup({dark: true, denyRead: true});
assert.equal(denied.button.textContent, '☀️');
assert.doesNotThrow(() => denied.ctx.toggleTheme());
assert.equal(denied.attributes.get('data-theme'), 'light');
assert.doesNotThrow(() => denied.changed());
const quota = setup({denyWrite: true});
assert.doesNotThrow(() => quota.ctx.toggleTheme());
assert.equal(quota.attributes.get('data-theme'), 'dark');
assert.equal(quota.button.textContent, '☀️');
console.log('Theme checks passed: saved preference, system changes, denied getter and failed persistence.');
