/* Saved results retain their exact destination and remain usable by keyboard. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const elements={},calls=[];let currentTab='search',origin=null;let allow=true,response={results:[],records:[],total_count:0,warnings:[]};
function element(id){return elements[id]||=( {innerHTML:'',textContent:'',value:'',selectedOptions:[],replaceChildren(){this.innerHTML='';},
  querySelectorAll(){this.items=[...this.innerHTML.matchAll(/data-index="(\d+)"/g)].map(match=>({dataset:{index:match[1]},events:{},addEventListener(name,fn){this.events[name]=fn;},click(){this.events.click();}}));return this.items;}} );}
const context={window:{},document:{getElementById:element,readyState:'loading',addEventListener:()=>{}},console,URLSearchParams,AbortController,
  goTab:tab=>{calls.push(['tab',tab]);if(allow)currentTab=tab;return allow;},esc:value=>String(value),hexRgba:()=>'',toast:message=>calls.push(['error',message]),
  state:{decisions:[{id:8}]},fetch:async url=>({ok:true,json:async()=>url.includes('/stats')?{by_module:{learning:{count:1}},active_days:1}:response})};
for(const name of ['loadDailyLearning','openStudyCourse','openPlanCourse','openCopilotLesson','openActionArticle','openDecisionForm'])context.window[name]=async(...args)=>calls.push([name,...args]);
context.window.rememberLearningOrigin=()=>{origin=currentTab;calls.push(['origin',currentTab]);};
context.window.Reflections={load:async()=>true,viewEntry:id=>calls.push(['reflection',id])};
context.window.ActionPlans={openRecord:async id=>calls.push(['action',id])};
vm.createContext(context);
for(const file of ['search.js','timeline.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/'+file),'utf8'),context);
(async()=>{
  const open=context.window.RecordDiscovery.open;
  await open({target:{kind:'study',module:'biaoda',course:'two.md'}});
  const studyCall=calls.find(call=>call[0]==='openStudyCourse');
  assert.equal(studyCall[1],'biaoda');assert.equal(studyCall[2],'two.md');
  assert.equal(studyCall[3]?.preserveOrigin,true);assert.equal(origin,'search');
  currentTab='timeline';
  await open({target:{kind:'study',module:'yingyu',course:'one.md'}});
  assert.equal(origin,'timeline');
  await open({target:{kind:'study',module:'plan',course:'plan-1/3'}});
  assert(calls.some(call=>call.join('|')==='openPlanCourse|plan-1|3'));
  await open({target:{kind:'copilot',lesson_no:2}});
  await open({target:{kind:'article',id:'article-1'}});
  await open({target:{kind:'reflection',id:'ref-1'}});
  await open({target:{kind:'action',id:'plan-2'}});
  await open({target:{kind:'legacy',module:'decision',id:8}});
  assert(calls.some(call=>call.join('|')==='openDecisionForm|0'));
  assert(calls.some(call=>call.join('|')==='reflection|ref-1'));
  assert(calls.some(call=>call.join('|')==='action|plan-2'));
  allow=false;const before=calls.filter(call=>call[0]==='openStudyCourse').length;
  await open({target:{kind:'study',module:'yingyu',course:'one.md'}});
  assert.equal(calls.filter(call=>call[0]==='openStudyCourse').length,before);allow=true;
  response={results:[{id:'note',module:'learning',title:'保存笔记',summary:'确切内容',target:{kind:'study',module:'biaoda',course:'two.md'}}],total_count:1,warnings:[{source:'custom_records'}]};
  await context.window.Search.performSearch('保存');
  assert(element('searchMeta').textContent.includes('部分内容暂时无法读取'));
  assert(element('searchResults').innerHTML.includes('确切内容'));
  const item=element('searchResults').items[0];let prevented=false;
  item.events.keydown({key:'Enter',preventDefault:()=>{prevented=true;}});await Promise.resolve();assert(prevented);
  response={records:[{id:'ref-1',module:'reflection',title:'日常记录',date:'2026-10-21',target:{kind:'reflection',id:'ref-1'}}],total_count:1,warnings:[{source:'custom_records'}]};
  await context.window.Timeline.load();
  assert(element('timelineList').innerHTML.includes('可能不完整'));
  element('timelineList').items[0].events.keydown({key:' ',preventDefault:()=>{}});
  await new Promise(setImmediate);
  assert.equal(calls.filter(call=>call.join('|')==='reflection|ref-1').length,2);
  const pending=[];
  context.fetch=async(url,options)=>new Promise(resolve=>pending.push({url,options,resolve:data=>resolve({ok:true,json:async()=>data})}));
  const first=context.window.Timeline.load(),latest=context.window.Timeline.load();
  assert(pending[0].options.signal.aborted);
  pending[1].resolve({records:[],total_count:0});await latest;
  const visible=element('timelineList').innerHTML;
  pending[0].resolve({records:[{module:'learning',title:'过期时间线',date:'2026-10-20'}],total_count:1});await first;
  assert.equal(element('timelineList').innerHTML,visible);
  pending[2].resolve({by_module:{},active_days:0});
  console.log('Discovery navigation checks passed: exact saved targets, keyboard, partial warnings and leave guards.');
})().catch(error=>{console.error(error);process.exitCode=1;});
