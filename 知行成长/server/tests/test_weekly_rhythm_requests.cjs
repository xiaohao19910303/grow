/* Late weekly requests must not replace a newer week or a disabled feature. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{constructor(tag,text){this.tag=tag;this.textContent=text;this.style={display:'none'};this.children=[];this.hidden=false;}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}}
const root=new Element(),view=new Element(),pending=[];
let weekField;
let state={preferences:{enabled:true,timezone:'Asia/Shanghai'}};
const client={read:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))};
const ui={client:()=>client,state:()=>state,node:(tag,text)=>new Element(tag,text),button:()=>{},field:()=>{weekField=new Element();return weekField;},event:()=>{}};
const context={window:{DailyRhythm:ui,ActionPlans:{day:()=> '2026-10-23'}},document:{getElementById:id=>id==='weeklyRhythm'?root:view,hidden:false},Date,Set,goTab:()=>{}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/weekly-rhythm.js'),'utf8'),context);
const data={week_start:'2026-10-19',week_end:'2026-10-25',stats:{action_days:0,loop_days:0,standard_days:0,minimum_days:0},target_days:3,records:[]};
(async()=>{
 const first=context.window.WeeklyRhythm.load(),second=context.window.WeeklyRhythm.load();
 pending[1].resolve(data);await second;const heading=root.children[0].textContent;
 pending[0].reject(Error('old request failed'));await first;assert.equal(root.children[0].textContent,heading);
 weekField.value='';assert.doesNotThrow(()=>weekField.onchange());assert.equal(pending.length,2);
 const third=context.window.WeeklyRhythm.load();state={preferences:{enabled:false}};await context.window.WeeklyRhythm.load();
 pending[2].resolve(data);await third;assert.equal(root.hidden,true);assert.equal(root.children[0].textContent,'本周行动成果');
 console.log('Weekly stale failure and disabled-state request invalidation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
