const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:'',querySelectorAll:()=>[],append(){}});return nodes.get(id);};
let refreshes=0,checkins=0,fail=false;
const context={window:{ActionPlans:{refresh:async()=>{refreshes++;if(fail)throw Error('offline');}},refreshAutoCheckins:async()=>{checkins++;}},document:{getElementById:node},console};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/learning-completion.js'),'utf8'),context);
(async()=>{assert.equal(await context.window.refreshLearningCompletion({}), '');assert.equal(refreshes,1);assert.equal(checkins,1);assert.equal(node('learningSyncStatus').hidden,true);
 fail=true;const warning=await context.window.refreshLearningCompletion({});assert(warning.includes('完成记录已保存'));assert.equal(node('learningSyncStatus').hidden,false);
 fail=false;await context.window.retryLearningCompletion();assert.equal(node('learningSyncStatus').hidden,true);
 const serverWarning=await context.window.refreshLearningCompletion({arrangement_sync_error:'课程完成记录已保存，日期安排暂未同步。'});assert(serverWarning.includes('暂未同步'));assert.equal(node('learningSyncStatus').hidden,false,'reading a snapshot cannot claim server-side reconciliation succeeded');
 // Exercise the actual inline refresh function: its caught failure must remain observable.
 const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
 context.fetch=async()=>{throw Error('offline checkins');};context.renderProgress=()=>{};context.renderOverview=()=>{};context.renderHabits=()=>{};
 vm.runInContext('let checkinRequest=0,automaticCheckins={},automaticCheckinModules=[];'+html.slice(html.indexOf('async function refreshAutoCheckins()'),html.indexOf('function activityOf(date)')),context);
 context.window.refreshAutoCheckins=context.refreshAutoCheckins;const caughtWarning=await context.window.refreshLearningCompletion({});assert(caughtWarning.includes('完成记录已保存'),'caught checkin failures must show a completion warning');assert.equal(node('learningSyncStatus').hidden,false);
 context.fetch=async()=>({ok:true,json:async()=>({checkins:{},modules:[]})});await context.window.retryLearningCompletion();assert.equal(node('learningSyncStatus').hidden,true);
 console.log('Completion synchronization passed: immediate refresh, warning, retry and server reconciliation failure.');
})().catch(e=>{console.error(e);process.exitCode=1;});
