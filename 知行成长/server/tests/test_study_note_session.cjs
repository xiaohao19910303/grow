/* Exercise draft recovery and async saves without a browser or model. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {window: {}, crypto: require('node:crypto').webcrypto};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/study-note-session.js'), 'utf8'), context);
const Session = context.window.StudyDraftSession;
const storage = () => {const items = new Map(); return {getItem:k=>items.get(k)||null,setItem:(k,v)=>items.set(k,v)};};
const response = (data, status=200) => ({ok:status<400,status,json:async()=>data});
const options = (extra={}) => ({kind:'biaoda',course:'Day 001.md',version:'a'.repeat(64),userId:'owner',storage:storage(),...extra});
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  let cloud=null, calls=[];
  const fetch=async(url,request={})=>{
    if(!request.method)return response(cloud);
    const body=JSON.parse(request.body);calls.push(body);
    cloud={notes:body.notes,answers:body.answers,version:body.version,revision:body.revision+1,updated_at:'2026-10-18T10:00:00+08:00'};
    return response(cloud);
  };
  const disk=storage(), session=new Session(options({storage:disk,fetch}));
  await session.load();session.setNotes('中途的笔记');session.setAnswer('练习1','尚未完成的答案');
  assert.equal(session.safe,true,'each input must survive a reload before a network save');
  const restored=new Session(options({storage:disk,fetch}));await restored.load();
  assert.equal(restored.notes,'中途的笔记');assert.equal(restored.answers['练习1'],'尚未完成的答案');
  await restored.save();assert.equal(cloud.notes,'中途的笔记');assert.equal(calls.length,1);
  assert.equal(calls[0].state,undefined,'draft saves never submit completion state');
  const differentUser=new Session(options({userId:'someone',storage:disk,fetch:async()=>response(null)}));await differentUser.load();
  assert.equal(differentUser.notes,'','accounts must never share browser drafts');
  let seedCloud=null;
  const seeded=new Session(options({seedNotes:'已有完成记录中的笔记',fetch:async(url,request)=>{
    if(request)seedCloud={...JSON.parse(request.body),revision:1};return response(seedCloud);
  }}));await seeded.load();await seeded.save();
  assert.equal(seedCloud.notes,'已有完成记录中的笔记','explicit save must protect existing notes before a completion state change');

  const offlineDisk=storage(), offline=new Session(options({storage:offlineDisk,fetch:async()=>{throw Error('offline');}}));
  await offline.load();offline.setAnswer('q1','离线答案');await assert.rejects(offline.save());
  const offlineRestore=new Session(options({storage:offlineDisk,fetch:async()=>{throw Error('offline');}}));await offlineRestore.load();
  assert.equal(offlineRestore.answers.q1,'离线答案');assert.equal(offlineRestore.safe,true);

  let finish;
  const delayed=new Session(options({fetch:async(url,request)=>request ? new Promise(resolve=>{finish=()=>resolve(response({...JSON.parse(request.body),revision:1}));}) : response(null)}));
  await delayed.load();delayed.setNotes('first');const pending=delayed.save();await flush();
  delayed.setNotes('second');finish();await flush();
  // Resolve the second snapshot if the session drains edits made during saving.
  if(delayed.dirty) {finish();}
  await pending;assert.equal(delayed.notes,'second','an old response cannot reset newer input');

  let other={notes:'云端已有笔记',answers:{},version:'a'.repeat(64),revision:3};
  const conflictDisk=storage(), editing=new Session(options({storage:conflictDisk,fetch:async()=>response(null)}));
  await editing.load();editing.setNotes('本机未同步笔记');
  const conflict=new Session(options({storage:conflictDisk,fetch:async(url,request)=>{
    if(request) { const body=JSON.parse(request.body);assert.equal(body.revision,3);other={...body,revision:4}; }
    return response(other);
  }}));await conflict.load();
  await assert.rejects(conflict.save());assert.equal(conflict.notes,'本机未同步笔记');assert.equal(conflict.safe,true);
  conflict.keepLocal();await conflict.save();assert.equal(other.notes,'本机未同步笔记');

  let lost=true, saved=null, revisions=[];const uncertainDisk=storage();
  const uncertainFetch=async(url,request)=>{
    if(!request)return response(saved);
    const body=JSON.parse(request.body);revisions.push(body.revision);
    saved={notes:body.notes,answers:body.answers,version:body.version,revision:body.revision+1};
    if(lost){lost=false;throw Error('response lost');}return response(saved);
  };
  const uncertain=new Session(options({storage:uncertainDisk,fetch:uncertainFetch}));await uncertain.load();uncertain.setNotes('已到云端');
  await assert.rejects(uncertain.save());
  const afterLost=new Session(options({storage:uncertainDisk,fetch:uncertainFetch}));await afterLost.load();
  afterLost.setNotes('恢复后继续写');await afterLost.save();
  assert.equal(saved.notes,'恢复后继续写');assert.deepEqual(revisions,[0,1],'lost response must reconcile before the next edit');
  console.log('Study draft session checks passed: recovery, offline, accounts, concurrent edits, conflicts, uncertain saves.');
})().catch(error=>{console.error(error);process.exitCode=1;});
