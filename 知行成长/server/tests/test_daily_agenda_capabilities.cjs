/* Arrange waits for capabilities before deciding between content and time modes. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{constructor(tag){this.tag=tag;this.children=[];this.isConnected=true;}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}}
const source=fs.readFileSync(path.join(__dirname,'../static/daily-agenda.js'),'utf8');
function setup(){
 let snapshot={plans:[]},release,reject;
 const calls={schedule:[],newDay:[],toasts:[]};
 const actions={snapshot:()=>snapshot,day:()=> '2026-10-23',refresh:()=>new Promise((resolve,fail)=>{release=resolve;reject=fail;}),
  schedule:async values=>{calls.schedule.push(values);return {existing:false};},newDay:async values=>calls.newDay.push(values)};
 const context={window:{ActionPlans:actions},ActionPlans:actions,document:{createElement:tag=>new Element(tag)},Date,Set,toast:text=>calls.toasts.push(text)};
 vm.createContext(context);vm.runInContext(source,context);
 const root=new Element('div');context.window.DailyAgenda.mount(root,{kind:'plan',plan_id:'course',lesson_no:1},'学习课程');
 const button=root.children[0].children.find(child=>child.textContent==='安排到明日');
 return {calls,button,finish:capabilities=>{snapshot={plans:[],capabilities};release();},fail:()=>reject(Error('offline'))};
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
 console.log('Daily agenda waits for capabilities, retains unsupported fallback, and reports load failure.');
})().catch(error=>{console.error(error);process.exitCode=1;});
