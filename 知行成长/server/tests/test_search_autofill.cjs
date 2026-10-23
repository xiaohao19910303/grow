/* Password-manager autofill must not navigate away from the current page. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const elements = {}, timers = new Map(), navigations = [], requests = [];
let timerId = 0;
function element(id) {
  return elements[id] ||= {value:'', innerHTML:'', textContent:'', events:{},
    addEventListener(name, run) { this.events[name] = run; },
    querySelectorAll() { return []; }, replaceChildren() { this.innerHTML = ''; }};
}
const document = {activeElement:null, readyState:'complete', getElementById:element, addEventListener() {}};
const context = {window:{}, document, console, URLSearchParams, AbortController,
  setTimeout(run) { timers.set(++timerId, run); return timerId; },
  clearTimeout(id) { timers.delete(id); },
  goTab(name) { navigations.push(name); }, esc:value=>value, toast() {},
  fetch:async url=> { requests.push(url); return {ok:true, json:async()=>({results:[],total_count:0})}; }};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/search.js'), 'utf8'), context);
function flush() { const pending = [...timers.values()]; timers.clear(); pending.forEach(run=>run()); }
const input = element('globalSearch');
(async () => {
  input.value = 'owner'; input.events.input({target:input}); flush();
  assert.equal(navigations.length, 0, 'unfocused autofill must not open search');
  document.activeElement = input;
  input.value = 'SpaceX'; input.events.input({target:input});
  document.activeElement = null; flush();
  assert.equal(navigations.length, 0, 'leaving the field before debounce must cancel navigation');
  document.activeElement = input;
  input.events.input({target:input}); flush();
  await new Promise(setImmediate);
  assert.deepEqual(navigations, ['search']);
  assert.equal(requests.length, 1, 'intentional focused typing still searches');
  console.log('Search autofill and pending-navigation checks passed.');
})().catch(error=> { console.error(error); process.exitCode = 1; });
