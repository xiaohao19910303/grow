/* Run the actual inline new-record entry points against the actual editor. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const elements=new Map(),storage=new Map();let modal='',message='',writes=[];
const element=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',dataset:{},events:{},addEventListener(name,fn){this.events[name]=fn;},querySelectorAll(selector){this.inputs=[...this.innerHTML.matchAll(/data-four="([^"]+)"/g)].map(m=>({dataset:{four:m[1]},value:'',events:{},addEventListener(name,fn){this.events[name]=fn;}}));return this.inputs;}});return elements.get(id);};
const record={id:'record-one',version:2,record_date:'2026-10-19',raw_text:'已有原文',guided_answers:{},tags:[]};
const context={window:{Account:{user:{id:'owner'}},addEventListener(){}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},document:{getElementById:element,querySelectorAll:()=>[...elements.values()]},crypto:require('node:crypto').webcrypto,AIConfig:{status:()=>''},console,
 openModal(value){for(const node of elements.values())node.disabled=false;modal=value;const date=value.match(/id="refDate" value="([^"]*)"/);if(date)element('refDate').value=date[1];const raw=value.match(/id="refRaw"[^>]*>([\s\S]*?)<\/textarea>/);element('refRaw').value=raw?raw[1]:'';},closeModal(){},
 fetch:async(url,options={})=>{if(options.method==='POST'||options.method==='PUT'){writes.push(JSON.parse(options.body));return{ok:true,json:async()=>record};}return{ok:true,json:async()=>({entries:[record]})};}};
context.window.toast=value=>message=value;vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/reflections.js'),'utf8'),context);context.Reflections=context.window.Reflections;
(async()=>{await new Promise(resolve=>setImmediate(resolve));
 const handlers=[...html.matchAll(/onclick="([^"]*Reflections\.openEditor[^\"]*)"/g)].map(m=>m[1]);
 assert(handlers.length>=2,'both new-record entry points must be tested');
 for(const handler of handlers){modal='';vm.runInContext(handler.replace('${selected}','2026-10-18'),context);assert(modal.includes('记下今天的一点收获'));assert(!modal.includes('编辑记录'));}
 context.Reflections.openEditor('2026-10-18');assert.equal(element('refDate').value,'2026-10-18');
 element('refRaw').value='历史日期的新增记录';await context.Reflections.saveEntry();assert.equal(writes.at(-1).record_date,'2026-10-18');assert.equal(writes.at(-1).base_version,undefined);
 context.Reflections.openEditor(null,'record-one');assert(modal.includes('已有原文'));
 record.adopted_summary={sections:[{kind:'event',text:'已有原文',basis:'statement'},{kind:'next_step',text:'可以尝试先写结论',basis:'suggestion'},{kind:'understanding',text:'旧整理未标来源',basis:'toString'}]};
 context.Reflections.viewEntry('record-one');assert(modal.includes('发生的事情 （原文整理）'));assert(modal.includes('下一步想试什么 （AI 建议）'));assert(modal.includes('我目前的认识 （来源未标注）'));assert.equal(record.raw_text,'已有原文');
 modal='';context.Reflections.openEditor(null,'missing');assert.equal(modal,'');assert(message,'unknown IDs should show a visible recovery hint');
 context.Reflections.openEditor('2026-10-18');element('refRaw').value='尚未提交的本机草稿';context.Reflections.preserveDraft();context.Reflections.closeEditor();context.Reflections.openEditor('2026-10-18');assert(modal.includes('尚未提交的本机草稿'));
 context.window.Account.user.id='other';context.Reflections.openEditor('2026-10-18');assert(!modal.includes('尚未提交的本机草稿'),'drafts are account scoped');context.window.Account.user.id='owner';
 context.Reflections.openEditor('2026-10-20',null,{four:true});assert(modal.includes('id="refFourDetails" open'));const answer=element('refFour').inputs[0];answer.value='四问独立答案';answer.events.input();element('refRaw').value='';await context.Reflections.saveEntry();assert.equal(writes.at(-1).guided_answers.expected,'四问独立答案');assert(writes.at(-1).raw_text.includes('四问独立答案'));assert.equal(storage.has('grow.reflections.draft.owner.2026-10-20'),false);
 context.Reflections.renderList(element('testList'),false);assert(element('testList').innerHTML.includes('ref-day-count">1 条'),'record count is the number of records, not HTML characters');
 assert.equal(context.Reflections.entries.length,1,'public record access remains live after async loads');
 storage.set('grow.reflections.draft.owner.record-one',JSON.stringify({entryId:'record-one',date:'2026-10-19',baseVersion:1,raw:'旧版本未提交草稿',guided:{}}));context.Reflections.openEditor(null,'record-one');assert(modal.includes('旧版本未提交草稿'));assert(modal.includes('云端记录已更新'));await context.Reflections.saveEntry();assert.equal(writes.at(-1).base_version,1,'a stale draft must never adopt the newer remote revision silently');
 context.Reflections.openEditor('2026-10-23');element('refRaw').value='移动日期的草稿';context.Reflections.preserveDraft();element('refDate').value='2026-10-24';context.Reflections.preserveDraft();assert.equal(storage.has('grow.reflections.draft.owner.2026-10-23'),false,'changing a new record date moves its draft instead of leaving a duplicate');assert(storage.get('grow.reflections.draft.owner.2026-10-24').includes('移动日期的草稿'));
 const originalFetch=context.fetch;let finishSave;context.fetch=(url,options={})=>options.method==='POST'?new Promise(resolve=>{finishSave=resolve;}):originalFetch(url,options);
 context.Reflections.openEditor('2026-10-21');element('refRaw').value='保存期间应保护的原文';const saving=context.Reflections.saveEntry();
 assert.equal(element('refRaw').disabled,true,'saving locks input so a late response cannot discard new edits');assert.equal(context.Reflections.preserveDraft(),false,'escape/backdrop cannot close a pending save');
 const pendingModal=modal;context.Reflections.openEditor('2026-10-22');assert.equal(modal,pendingModal,'cannot replace the editor while its save is pending');await context.Reflections.saveEntry();
 finishSave({ok:false,status:503,json:async()=>({})});await saving;assert.equal(element('refRaw').disabled,false,'a failed save unlocks editing');assert.equal(element('refRaw').value,'保存期间应保护的原文');
 assert(storage.get('grow.reflections.draft.owner.2026-10-21').includes('保存期间应保护的原文'),'submission is locally recoverable before requesting the server');context.fetch=originalFetch;
 console.log('Reflection entry points passed: today, record list, historical date, edit, missing record and save.');
})().catch(e=>{console.error(e);process.exitCode=1;});
