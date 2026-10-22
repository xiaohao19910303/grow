// Small, isolated regression tests: no credentials, network, browser profile or database.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const context = {window:{}, Intl, Date, Map, JSON, Error, Object, encodeURIComponent};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/action-plan-client.js'), 'utf8'), context);
const {create} = context.window.ActionPlanClient;
const form = {flow:'create-day', origin_key:'fixture', parent_context:null, entry_date:'2026-10-22'};
const plain = value => JSON.parse(JSON.stringify(value));

function fixture(errorName = null) {
  const entries = new Map(), requests = [], saved = new Map();
  let serial = 0, fail = true, found = false;
  const storage = {
    getItem:key => entries.get(key) ?? null,
    setItem(key, value) {
      if (errorName) { const error = Error('synthetic storage failure'); error.name = errorName; throw error; }
      entries.set(key, value);
    },
    removeItem(key) {
      if (errorName === 'SecurityError') { const error = Error('synthetic denied removal'); error.name = errorName; throw error; }
      entries.delete(key);
    },
  };
  const request = async (url, options) => {
    requests.push({url, options});
    if (url.includes('/requests/')) return {ok:true, json:async () => ({found})};
    const body = JSON.parse(options.body);
    if (!saved.has(body.key)) saved.set(body.key, {plans:[{id:'saved-plan'}]});
    if (fail) throw Error('synthetic response lost after commit');
    return {ok:true, json:async () => saved.get(body.key)};
  };
  return {
    entries, requests, saved,
    client:(account = 'storage-fixture') => create({account, storage, request, random:() => `storage-${++serial}`}),
    denyStorage:name => { errorName = name; },
    online:() => { fail = false; },
    findReceipt:() => { found = true; },
  };
}

for (const [name, reason] of [['QuotaExceededError', 'quota'], ['SecurityError', 'unavailable']]) {
  test(`${name}: failed persistence is explicit and the volatile draft stays exportable`, () => {
    const f = fixture(name), client = f.client();
    const draft = client.newDraft(form, {title:'unsaved local draft'});
    assert.equal(client.listDrafts(form)[0].draft_id, draft.draft_id);
    assert.equal(typeof client.storageStatus, 'function', 'storage failures need an observable state instead of silent memory fallback');
    assert.equal(client.storageStatus().durable, false);
    assert.equal(client.storageStatus().reason, reason);
    assert.equal(typeof client.exportRecovery, 'function', 'volatile data needs an explicit recoverable download');
    const bundle = plain(client.exportRecovery());
    assert.equal(bundle.version, 1);
    assert.equal(bundle.account, 'storage-fixture');
    assert(!Object.hasOwn(bundle.entries, 'device'), 'recovery packages must not include device identity');
    assert.match(JSON.stringify(bundle), /unsaved local draft/);
    assert.equal(f.client().listDrafts(form).length, 0, 'browser storage failure cannot promise refresh persistence');
  });
}

test('a recovery package restores the original unknown request key after a new page instance', async () => {
  const f = fixture('QuotaExceededError'), first = f.client();
  const draft = first.newDraft(form, {title:'unknown submission'});
  const identity = 'draft:' + draft.draft_id;
  await assert.rejects(first.write(identity, '', draft.values), /response lost/);
  const original = plain(first.pending(identity));
  assert.equal(f.saved.size, 1, 'the synthetic server committed before losing the response');
  assert.equal(typeof first.exportRecovery, 'function', 'missing recovery export loses the idempotency key on refresh');
  const bundle = plain(first.exportRecovery()), fresh = f.client();
  fresh.importRecovery(bundle);
  assert.deepEqual(plain(fresh.pending(identity)), original);
  assert.equal(fresh.listDrafts(form)[0].draft_id, draft.draft_id);
  f.online();
  await fresh.retryPending(identity, '');
  assert.equal(JSON.parse(f.requests.at(-1).options.body).key, original.key);
  assert.equal(f.saved.size, 1, 'recovering an unknown result must not create a second server operation');
  assert.equal(fresh.pending(identity), undefined);
});

test('a failed update shadows stale durable values and exports the newest unsaved input', () => {
  const f = fixture(), client = f.client();
  const draft = client.newDraft(form, {title:'old stored text'});
  f.denyStorage('QuotaExceededError');
  client.saveDraft(draft, {title:'new unsaved text'});
  assert.equal(client.listDrafts(form)[0].values.title, 'new unsaved text', 'stale storage must not hide the newer memory copy');
  const bundle = plain(client.exportRecovery()), fresh = fixture().client();
  fresh.importRecovery(bundle);
  assert.equal(fresh.listDrafts(form)[0].values.title, 'new unsaved text');
});

test('a denied deletion does not resurrect a deleted draft from stale storage or export it', () => {
  const f = fixture(), client = f.client();
  const draft = client.newDraft(form, {title:'deleted local draft'});
  f.denyStorage('SecurityError');
  client.deleteDraft(draft.draft_id);
  assert.equal(client.listDrafts(form).length, 0, 'failed removal must retain an in-page deletion marker');
  const bundle = plain(client.exportRecovery());
  assert(!Object.hasOwn(bundle.entries, 'draft.' + draft.draft_id));
  assert.equal(client.storageStatus().durable, false);
});

test('recovery exports retain immutable pending payloads and forked edits but exclude ephemeral AI secrets', async () => {
  const f = fixture('SecurityError'), client = f.client();
  const draft = client.newDraft(form, {title:'original text', revision:7}), identity = 'draft:' + draft.draft_id;
  await assert.rejects(client.write(identity, '', draft.values, {ai_config:{api_key:'FIXTURE_EPHEMERAL_SECRET'}}));
  const edited = client.saveDraft(draft, {title:'edited text'});
  assert.notEqual(edited.draft_id, draft.draft_id);
  assert.equal(typeof client.exportRecovery, 'function');
  const bundle = plain(client.exportRecovery());
  assert(!JSON.stringify(bundle).includes('FIXTURE_EPHEMERAL_SECRET'));
  const fresh = f.client();fresh.importRecovery(bundle);
  assert.equal(fresh.pending(identity).title, 'original text');
  assert.equal(fresh.listDrafts(form).length, 2);
  assert.equal(fresh.listDrafts(form).find(item => item.draft_id === edited.draft_id).values.title, 'edited text');
  assert.equal(fresh.listDrafts(form).find(item => item.draft_id === edited.draft_id).base_revision, 7);
});

test('a not-found receipt keeps the imported original key until an explicit same-key retry', async () => {
  const f = fixture('QuotaExceededError'), first = f.client();
  await assert.rejects(first.write('create', '', {title:'unknown'}));
  const original = first.pending('create').key;
  assert.equal(typeof first.exportRecovery, 'function');
  const fresh = f.client();fresh.importRecovery(plain(first.exportRecovery()));
  const receipt = await fresh.resolvePending('create');
  assert.equal(receipt.found, false);
  assert.equal(fresh.pending('create').key, original);
  f.online();await fresh.retryPending('create', '');
  assert.equal(f.saved.size, 1);
});

test('recovery packages cannot cross accounts or overwrite an unresolved different request', async () => {
  const f = fixture(), alice = f.client('alice');
  await assert.rejects(alice.write('create', '', {title:'alice private draft'}));
  assert.equal(typeof alice.exportRecovery, 'function');
  const bundle = plain(alice.exportRecovery()), bob = f.client('bob');
  assert.throws(() => bob.importRecovery(bundle), /账号|账户|account/i);
  assert.equal(bob.pending('create'), undefined);
  const independent = fixture(), current = independent.client('alice');
  await assert.rejects(current.write('create', '', {title:'another unresolved draft'}));
  const retained = plain(current.pending('create'));
  assert.throws(() => current.importRecovery(bundle), /冲突|待确认|覆盖|conflict|pending/i);
  assert.deepEqual(plain(current.pending('create')), retained);
});

test('durable storage remains durable and old saved drafts still load without a recovery package', () => {
  const f = fixture(), first = f.client();
  const draft = first.newDraft(form, {title:'durable draft'}), fresh = f.client();
  assert.equal(fresh.listDrafts(form)[0].draft_id, draft.draft_id);
  assert.equal(typeof fresh.storageStatus, 'function');
  assert.equal(fresh.storageStatus().durable, true);
  f.denyStorage('QuotaExceededError');
  fresh.saveDraft(fresh.listDrafts(form)[0], {title:'recovered durable draft'});
  assert.equal(fresh.storageStatus().durable, false);
  f.denyStorage(null);
  assert.equal(fresh.retryStorage().durable, true, 'retrying storage must flush all volatile writes before reporting success');
  assert.equal(f.client().listDrafts(form)[0].values.title, 'recovered durable draft');
});

test('healthy shared storage exposes another client changes, deletes, and same-name recreation', () => {
  const f=fixture(), first=f.client(), second=f.client();
  const draft=first.newDraft(form,{title:'initial shared draft'});
  assert.equal(second.listDrafts(form)[0].values.title,'initial shared draft');
  first.saveDraft(draft,{title:'newer shared draft'});
  assert.equal(second.listDrafts(form)[0].values.title,'newer shared draft','clean caches must read another tab updates');
  second.deleteDraft(draft.draft_id);
  assert.equal(first.listDrafts(form).length,0,'clean caches must read another tab deletions');
  first.deleteDraft(draft.draft_id);
  second.put('draft.'+draft.draft_id,{...draft,values:{title:'same name recreated'}});
  second.put('draft.index',[draft.draft_id]);
  assert.equal(first.listDrafts(form)[0].values.title,'same name recreated','successful removal must not leave a permanent deletion marker');
});

test('invalid versions and illegal recovery keys are rejected before any entry is imported', () => {
  const source = fixture().client(), draft = source.newDraft(form, {title:'must stay out'});
  assert.equal(typeof source.exportRecovery, 'function');
  const original = plain(source.exportRecovery());
  for (const mutation of [
    bundle => { bundle.version = 999; },
    bundle => { bundle.unknown = true; },
    bundle => { bundle.entries['draft.' + draft.draft_id].unknown = true; },
    bundle => { bundle.entries['draft.' + draft.draft_id].values.title = 'x'.repeat(1048577); },
    bundle => { bundle.entries['draft.' + draft.draft_id].values.ai_config = {api_key:'IMPORT_MUST_REJECT_SECRET'}; },
    bundle => { bundle.entries.device = 'forbidden-device'; },
    bundle => { bundle.entries['grow.actions.other-account.pending.create'] = {body:{key:'wrong-account-key'}}; },
    bundle => { Object.defineProperty(bundle.entries, '__proto__', {value:{polluted:true}, enumerable:true}); },
  ]) {
    const bundle = plain(original), destination = fixture().client();mutation(bundle);
    assert.throws(() => destination.importRecovery(bundle), /格式|版本|恢复|非法|version|recovery|invalid/i);
    assert.equal(destination.listDrafts(form).length, 0, 'rejected packages must not partly import an earlier valid draft');
    assert.equal(destination.get('draft.' + draft.draft_id), null);
  }
});

test('a conflicting late entry rejects the entire recovery package without importing earlier valid entries', async () => {
  const sourceFixture = fixture(), source = sourceFixture.client();
  const draft = source.newDraft(form, {title:'new draft before conflicting pending'});
  await assert.rejects(source.write('create', '', {title:'source unresolved'}));
  assert.equal(typeof source.exportRecovery, 'function');
  const bundle = plain(source.exportRecovery()), f = fixture(), destination = f.client();
  await assert.rejects(destination.write('create', '', {title:'destination unresolved'}));
  const pending = plain(destination.pending('create'));
  assert.throws(() => destination.importRecovery(bundle), /冲突|待确认|覆盖|conflict|pending/i);
  assert.deepEqual(plain(destination.pending('create')), pending);
  assert.equal(destination.get('draft.' + draft.draft_id), null);
  assert.equal(destination.listDrafts(form).length, 0);
  assert.equal(destination.storageStatus().durable, true, 'validating an invalid package must not mutate storage health');
});
