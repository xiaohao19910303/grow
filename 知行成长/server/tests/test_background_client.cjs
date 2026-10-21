/* Lost POST responses keep their request ID; a refreshed view only observes GET. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/course-summary.js'),'utf8');
const storage=new Map(),calls=[],observed=[],output={},button={disabled:false};let uncertain=true;
const context={backgroundReady:Promise.resolve(),summaryTask:null,advancedTask:null,selectedSummaryResult:null,summaryDisplayRequest:0,activeTask:t=>t&&['queued','generating'].includes(t.state),
  window:{AIConfig:{require:()=>({api_key:'PRIVATE_CLIENT_KEY'})},Account:{user:{id:'fixture'}},GenerationTasks:{track:()=>{}}},
  sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=> 'one-original-request-id'},
  document:{getElementById:id=>id==='outputContent'?output:button},showToast:()=>{},backgroundTask:j=>j,observeBackground:async job=>observed.push(job.id),
  jobAPI:async(path,body)=>{calls.push({path,body});if(body){if(uncertain){uncertain=false;throw Error('response lost');}return {id:'server-job',state:'generating',kind:'summary'};}return {items:[{id:'server-job',state:'generating',kind:'summary'}]};}};
const functions=source.slice(source.indexOf('  async function startBackground('),source.indexOf('  async function viewSummary('));
vm.createContext(context);vm.runInContext(functions,context);
(async()=>{
  await context.startBackground('summary',{scope:'full_course'});
  await context.startBackground('summary',{scope:'full_course'});
  assert.equal(calls[0].body.key,calls[1].body.key,'uncertain submissions retain the original key');
  assert.equal(storage.size,0,'a confirmed task ID clears the pending submission key');
  await context.resumeBackground();
  assert.equal(calls[2].path,'/background-jobs');assert.equal(calls[2].body,undefined,'view recovery must never POST or send model credentials');
  assert.deepEqual(observed,['server-job','server-job']);
  console.log('Background client checks passed: retry-safe submission and GET-only view recovery.');
})().catch(error=>{console.error(error);process.exitCode=1;});
