/* Arrange waits for capabilities before deciding between content and time modes. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{constructor(tag){this.tag=tag;this.children=[];this.isConnected=true;}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}}
const source=fs.readFileSync(path.join(__dirname,'../static/daily-agenda.js'),'utf8');
const all=node=>[node,...node.children.flatMap(all)];
function setup({plans=[],compact=false}={}){
 let snapshot={plans},release,reject;
 const calls={schedule:[],newDay:[],change:[],toasts:[]};
 const actions={snapshot:()=>snapshot,day:()=> '2026-10-23',refresh:()=>new Promise((resolve,fail)=>{release=resolve;reject=fail;}),
  schedule:async values=>{calls.schedule.push(values);return {existing:false};},newDay:async values=>calls.newDay.push(values),
  change:async(p,operation,values)=>{calls.change.push({id:p.id,operation,...values});return {plan:p};}};
 const context={window:{ActionPlans:actions},ActionPlans:actions,document:{createElement:tag=>new Element(tag)},Date,Set,toast:text=>calls.toasts.push(text)};
 vm.createContext(context);vm.runInContext(source,context);
 const root=new Element('div');context.window.DailyAgenda.mount(root,{kind:'plan',plan_id:'course',lesson_no:1},'学习课程',20,{compact});
 const button=all(root).find(child=>child.textContent==='安排到明日');
 return {calls,button,root,api:context.window.DailyAgenda,finish:(capabilities,nextPlans=plans)=>{snapshot={plans:nextPlans,capabilities};release();},fail:()=>reject(Error('offline'))};
}
(async()=>{
 const supported=setup(),waiting=supported.button.onclick();
 assert.equal(supported.button.disabled,true);assert.equal(supported.calls.schedule.length,0);assert.equal(supported.calls.newDay.length,0);
 supported.finish({content_receipts:['plan']});await waiting;
 assert.equal(supported.calls.schedule.length,1);assert.equal(supported.calls.newDay.length,0);assert.equal(supported.calls.schedule[0].date,'2026-10-24');
 const unsupported=setup(),fallback=unsupported.button.onclick();unsupported.finish({content_receipts:[]});await fallback;
 assert.equal(unsupported.calls.schedule.length,0);assert.equal(unsupported.calls.newDay.length,1);assert.equal(unsupported.calls.newDay[0].seedValues.completion_mode,'time');
 const failed=setup(),failure=failed.button.onclick();failed.fail();await failure;
 assert.equal(failed.calls.schedule.length,0);assert.equal(failed.calls.newDay.length,0);assert.deepEqual(failed.calls.toasts,['offline']);assert.equal(failed.button.disabled,false);
 const target={kind:'plan',plan_id:'course',lesson_no:1};
 const plan={id:'linked-course',period:'day',completion_mode:'content',status:'active',start_date:null,target};
 const undated=setup({plans:[plan]}),assign=undated.button.onclick();undated.finish({content_receipts:['plan']});await assign;
 assert.equal(undated.calls.schedule.length,0);assert.equal(undated.calls.newDay.length,0);
 assert.deepEqual(undated.calls.change,[{id:'linked-course',operation:'reschedule',date:'2026-10-24'}],'reuse an existing linked action');
 const duplicate=setup(),repeat=duplicate.button.onclick();duplicate.finish({content_receipts:[]},[{...plan,start_date:'2026-10-24',completion_mode:'time'}]);await repeat;
 assert.equal(duplicate.calls.newDay.length,0,'a timed course already on this date must not create another draft');
 assert.equal(duplicate.calls.schedule.length,0);assert.equal(duplicate.calls.change.length,0);
 const optional=setup({compact:true});
 assert(all(optional.root).some(n=>n.textContent==='加入今日安排'));
 assert(all(optional.root).some(n=>n.tag==='summary'&&n.textContent==='更多安排'));
 assert(!all(optional.root).some(n=>n.textContent==='安排到今日'));
 for(const date of ['2026-10-22','2026-10-24']){
  const existing=setup({compact:true,plans:[{...plan,start_date:date}]});
  assert(all(existing.root).some(n=>String(n.textContent).includes(date)));
  assert(!all(existing.root).some(n=>n.textContent==='加入今日安排'),'existing other-date plans offer rescheduling instead of duplicate creation');
  assert.equal(existing.api.isScheduled(target),false);assert.equal(existing.api.isScheduled(target,date),true);
  const move=all(existing.root).find(n=>n.textContent===(date<'2026-10-23'?'移至今日':'改到今日')),moving=move.onclick();existing.finish({content_receipts:['plan']});await moving;
  assert.deepEqual(existing.calls.change,[{id:'linked-course',operation:'reschedule',date:'2026-10-23'}]);
 }
 const stale=setup({compact:true,plans:[{...plan,start_date:'2026-10-24'}]});
 const staleMove=all(stale.root).find(n=>n.textContent==='改到今日'),staleMoving=staleMove.onclick();
 stale.finish({content_receipts:['plan']},[{...plan,start_date:'2026-10-24'},{...plan,id:'another-tab',start_date:'2026-10-23'}]);await staleMoving;
 assert.equal(stale.calls.change.length,0,'a freshly discovered same-day arrangement blocks duplicate rescheduling');
 console.log('Daily agenda waits for capabilities, retains unsupported fallback, and reports load failure.');
 console.log('Course arrangements retain other-date visibility, reuse linked actions, and avoid same-date timed duplicates.');
})().catch(error=>{console.error(error);process.exitCode=1;});
