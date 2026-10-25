// Actual reading UI; hold the admission response to verify immediate progress.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright');
const staticRoot=path.resolve(__dirname,'../static');
const styles=fs.readFileSync(path.join(staticRoot,'design-tokens.css'),'utf8')+'\n'+fs.readFileSync(path.join(staticRoot,'index.html'),'utf8').match(/<style>([\s\S]*?)<\/style>/)[1];
const preferences={enabled:false,hour:10,minute:0,count:2,mode:'recent',topics:['科技'],languages:['en'],query:'AI',auto_guide:false};
const requests=[],jobs=new Map(),pending=[],pendingSaves=[];
let rejectNext=false,jobReads=0,holdListing=true,rejectSetup=false;const heldListings=[],heldSetups=[];
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  res.setHeader('Content-Type','application/json');
  if(url.pathname==='/api/reading/library'){
    const listed=url.searchParams.get('kind')==='jobs'?[...jobs.values()].map(job=>({...job,candidate_count:job.candidates?.length||0})):[];
    return res.end(JSON.stringify({jobs:listed,articles:[],total:listed.length,page:1,page_size:20}));
  }
  if(url.pathname==='/api/reading'){
    const reply=()=>res.end(JSON.stringify({preferences,topics:['科技','认知'],default_sources:[],custom_sources:[],articles:[],jobs:[...jobs.values()]}));
    if(holdListing){heldListings.push(reply);return;}return reply();
  }
  if(url.pathname==='/api/reading/setup'){
    if(rejectSetup){res.statusCode=503;return res.end(JSON.stringify({message:'temporary failure'}));}
    heldSetups.push(()=>res.end(JSON.stringify({preferences,topics:['科技','认知']})));return;
  }
  if(url.pathname==='/api/reading/collect'){
    let raw='';for await(const chunk of req)raw+=chunk;
    const data=JSON.parse(raw).data;requests.push(data);
    if(rejectNext){const plain=rejectNext==='html';rejectNext=false;res.statusCode=503;return res.end(plain?'Internal Server Error':JSON.stringify({message:'来源服务暂不可用，请重试。'}));}
    pending.push(()=>{
      const id='job-'+data.key;
      if(!jobs.has(id))jobs.set(id,{id,kind:'collect',state:'running',phase:'正在读取来源',preferences:data.preferences,sources:[],warnings:[],candidates:[]});
      res.end(JSON.stringify(jobs.get(id)));
    });return;
  }
  if(url.pathname.startsWith('/api/reading/jobs/')){
    jobReads++;const id=url.pathname.split('/')[4],job=jobs.get(id);
    if(!job){res.statusCode=404;return res.end('{}');}
    if(url.pathname.endsWith('/save')){
      let raw='';for await(const chunk of req)raw+=chunk;
      const ids=JSON.parse(raw).data.ids;
      pendingSaves.push(()=>{job.saved_ids=ids;res.end(JSON.stringify(job));});return;
    }
    if(url.pathname.endsWith('/cancel'))job.state='cancelled';
    return res.end(JSON.stringify(job));
  }
  if(url.pathname==='/'){
    res.setHeader('Content-Type','text/html;charset=utf-8');
    return res.end(`<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${styles}</style><link rel="stylesheet" href="/reading.css"><link rel="stylesheet" href="/plans.css"><main class="wrap"><nav class="tabs"><button class="tab active" onclick="loadReading()">今日阅读</button></nav><div id="view-reading" class="section"></div></main><script>window.toast=()=>{};window.AIConfig={read:()=>({model_name:'fixture'})};window.ReadingGrowth={hasFeedback:()=>false};window.goTab=()=>enterReading();</script><script src="/reading.js"></script><script>if(!location.hash)loadReading()</script></html>`);
  }
  if(['/reading.js','/reading.css','/plans.css'].includes(url.pathname)){
    res.setHeader('Content-Type',url.pathname.endsWith('.js')?'text/javascript':'text/css');
    return res.end(fs.readFileSync(path.join(staticRoot,url.pathname.slice(1))));
  }
  res.statusCode=404;res.end('{}');
});
async function main(){
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
  const page=await browser.newPage({viewport:{width:1100,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const form=async()=>{
    await page.getByRole('button',{name:'帮我找文章',exact:true}).click();
    await page.getByRole('button',{name:'开始查找',exact:true}).waitFor();
  };
  const release=async()=>{
    // A queued handler confirms the request reached the server before release.
    for(let i=0;i<100&&!pending.length;i++)await page.waitForTimeout(10);
    assert(pending.length);pending.shift()();
  };
  const conditions=async target=>({
    query:await target.getByRole('textbox',{name:/主题或关键词/}).inputValue(),
    count:await target.getByLabel('推荐数量（1—8篇）',{exact:true}).inputValue(),
    mode:await target.getByLabel('文章类型').inputValue(),
    topics:await target.getByRole('group',{name:'感兴趣的主题',exact:true}).getByRole('checkbox').evaluateAll(inputs=>inputs.filter(input=>input.checked).map(input=>input.parentElement.textContent)),
    languages:await target.getByRole('group',{name:'文章语言',exact:true}).getByRole('checkbox').evaluateAll(inputs=>inputs.filter(input=>input.checked).map(input=>input.parentElement.textContent))
  });
  try{
    await page.goto('http://127.0.0.1:'+server.address().port);
    const unedited=await browser.newPage();unedited.on('pageerror',error=>errors.push(error.message));
    await unedited.goto('http://127.0.0.1:'+server.address().port);
    await unedited.getByRole('button',{name:'帮我找文章',exact:true}).click();
    assert(await unedited.getByRole('button',{name:'开始查找',exact:true}).isEnabled(),'form must stay actionable before preferences arrive');
    for(let i=0;i<100&&!heldSetups.length;i++)await unedited.waitForTimeout(10);
    assert(heldSetups.length);heldSetups.shift()();
    await unedited.getByText('已载入你的阅读偏好。',{exact:true}).waitFor();
    assert.deepEqual(await conditions(unedited),{query:'AI',count:'2',mode:'recent',topics:['科技'],languages:['英文（可生成中文导读）']},'all saved conditions must load into an untouched form');
    await unedited.close();
    const formClicked=Date.now();
    await form();
    const formMs=Date.now()-formClicked;
    assert(formMs<1000,'conditions must render before any data response');
    await page.getByRole('textbox',{name:/主题或关键词/}).fill('my in-progress edit');
    await page.getByLabel('推荐数量（1—8篇）',{exact:true}).fill('5');
    await page.getByLabel('文章类型').selectOption('classic');
    for(const checkbox of await page.getByRole('group',{name:'感兴趣的主题',exact:true}).getByRole('checkbox').all())await checkbox.uncheck();
    await page.getByRole('checkbox',{name:'成长',exact:true}).check();
    await page.getByRole('checkbox',{name:'英文（可生成中文导读）',exact:true}).uncheck();
    const editedConditions=await conditions(page);
    for(let i=0;i<100&&!heldSetups.length;i++)await page.waitForTimeout(10);
    assert(heldSetups.length);heldSetups.shift()();
    await page.getByText('已保留你正在调整的条件。',{exact:true}).waitFor();
    assert.equal(await page.getByRole('textbox',{name:/主题或关键词/}).inputValue(),'my in-progress edit');
    assert.deepEqual(await conditions(page),editedConditions,'late saved preferences must preserve every edited condition');
    holdListing=false;heldListings.splice(0).forEach(reply=>reply());
    await page.waitForTimeout(50);
    assert.equal(await page.getByRole('heading',{name:'帮我找文章',exact:true}).count(),1,'stale home response must not replace conditions');
    const clicked=Date.now();
    await page.getByRole('button',{name:'开始查找',exact:true}).click();
    await page.getByRole('heading',{name:'正在启动查找',exact:true}).waitFor({timeout:1000});
    const progressMs=Date.now()-clicked;
    assert(progressMs<1000,'progress page must not wait for admission');
    await page.getByText('正在创建查找任务…',{exact:true}).waitFor();
    assert.equal(jobReads,0,'must not poll a job before admission');
    assert.equal(jobs.size,0);
    assert.equal(await page.getByRole('button',{name:'取消任务',exact:true}).count(),0);
    if(process.env.READING_SCREENSHOTS)await page.screenshot({path:process.env.READING_SCREENSHOTS+'/immediate-progress.png',fullPage:true});
    await page.setViewportSize({width:320,height:900});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'startup page must fit mobile');
    await page.setViewportSize({width:1100,height:900});
    // Returning while admission is pending must neither duplicate nor abort it.
    await page.getByRole('button',{name:'返回阅读',exact:true}).click();await form();
    await page.getByRole('button',{name:'开始查找',exact:true}).click();
    await page.getByRole('heading',{name:'正在启动查找',exact:true}).waitFor();
    assert.equal(requests.length,1);
    await release();
    await page.getByRole('button',{name:'取消任务',exact:true}).waitFor();
    assert.equal(jobs.size,1);
    await page.getByRole('button',{name:'取消任务',exact:true}).click();
    await page.getByRole('button',{name:'调整条件重新搜集',exact:true}).waitFor();
    // Failure stays actionable on the progress page and retries the same key.
    await page.getByRole('button',{name:'返回阅读',exact:true}).click();await form();
    rejectNext=true;
    await page.getByRole('button',{name:'开始查找',exact:true}).click();
    await page.getByRole('heading',{name:'启动查找遇到问题',exact:true}).waitFor();
    const failedRequest=requests.at(-1);
    assert.equal(await page.locator('.reading-loading').count(),0);
    await page.getByText('来源服务暂不可用，请重试。',{exact:true}).waitFor();
    await page.getByRole('button',{name:'重试启动',exact:true}).click();
    await page.getByRole('heading',{name:'正在启动查找',exact:true}).waitFor();
    await release();
    assert.equal(requests.at(-1).key,failedRequest.key);
    assert.deepEqual(requests.at(-1).preferences,failedRequest.preferences);
    await page.getByRole('button',{name:'取消任务',exact:true}).waitFor();
    await page.getByRole('button',{name:'取消任务',exact:true}).click();
    await page.getByRole('button',{name:'调整条件重新搜集',exact:true}).waitFor();
    // Completion after navigation cannot unexpectedly pull the user back.
    await page.getByRole('button',{name:'返回阅读',exact:true}).click();await form();
    await page.getByRole('button',{name:'开始查找',exact:true}).click();
    await page.getByRole('heading',{name:'正在启动查找',exact:true}).waitFor();
    await page.getByRole('button',{name:'返回阅读',exact:true}).click();
    await release();await page.waitForTimeout(200);
    assert.equal(await page.getByRole('heading',{name:'阅读',exact:true}).count(),1);
    assert.equal(jobs.size,3);
    await form();rejectNext='html';
    await page.getByRole('button',{name:'开始查找',exact:true}).click();
    await page.getByRole('heading',{name:'启动查找遇到问题',exact:true}).waitFor();
    await page.getByText('服务暂时不可用，请稍后重试。',{exact:true}).waitFor();
    assert.equal(await page.locator('.reading-loading').count(),0);
    const readyJob=[...jobs.values()].at(-1);readyJob.state='ready';readyJob.created_at='2026-10-17T12:00:00';
    readyJob.candidates=[{id:'article-fixture',title:'Technology article',category:'recent',language:'en',source:'Fixture',summary:'Public source summary.'}];
    await page.getByRole('button',{name:'返回阅读',exact:true}).click();
    await page.getByRole('button',{name:'历史搜集记录',exact:true}).click();
    await page.getByRole('button',{name:'查看并保存',exact:true}).click();
    await page.getByRole('button',{name:'保存选中的文章与资料',exact:true}).click();
    await page.getByText('正在保存文章与正文…',{exact:true}).waitFor();
    for(let i=0;i<100&&!pendingSaves.length;i++)await page.waitForTimeout(10);
    assert(pendingSaves.length);pendingSaves.shift()();
    await page.getByRole('button',{name:'本站阅读',exact:true}).waitFor();
    // Unedited forms must hydrate every saved condition, not only the keyword.
    const hydrated=await browser.newPage();hydrated.on('pageerror',error=>errors.push(error.message));
    preferences.count=2;
    await hydrated.goto('http://127.0.0.1:'+server.address().port);
    await hydrated.getByRole('button',{name:'帮我找文章',exact:true}).click();
    for(let i=0;i<100&&!heldSetups.length;i++)await page.waitForTimeout(10);
    assert(heldSetups.length);heldSetups.shift()();
    await hydrated.getByText('已载入你的阅读偏好。',{exact:true}).waitFor();
    assert.equal(await hydrated.getByLabel('推荐数量（1—8篇）',{exact:true}).inputValue(),'2');
    assert.equal(await hydrated.getByRole('textbox',{name:/主题或关键词/}).inputValue(),'AI');
    assert(await hydrated.getByLabel('科技',{exact:true}).isChecked());
    assert(!await hydrated.getByLabel('认知',{exact:true}).isChecked());
    assert(await hydrated.getByLabel('英文（可生成中文导读）',{exact:true}).isChecked());
    assert(!await hydrated.getByLabel('中文',{exact:true}).isChecked());
    await hydrated.close();
    // A fresh page must remain usable even when preferences fail to load.
    const cold=await browser.newPage();cold.on('pageerror',error=>errors.push(error.message));
    holdListing=true;rejectSetup=true;
    await cold.goto('http://127.0.0.1:'+server.address().port);
    await cold.getByRole('button',{name:'帮我找文章',exact:true}).click();
    await cold.getByText('偏好暂未载入，可继续使用当前条件查找。',{exact:true}).waitFor();
    assert(await cold.getByRole('button',{name:'开始查找',exact:true}).isEnabled());
    holdListing=false;heldListings.splice(0).forEach(reply=>reply());await cold.close();
    // An article request error must offer recovery instead of leaving a blank reader.
    await page.goto('http://127.0.0.1:'+server.address().port+'/#reading/article/article-missing');
    await page.reload();
    await page.getByRole('button',{name:'重试加载文章',exact:true}).waitFor();
    await page.getByText('读取失败，请稍后重试。',{exact:true}).waitFor();
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({result:'PASS',click_to_form_ms:formMs,click_to_progress_ms:progressMs,cases:['immediate conditions','load every saved condition','preserve all edits during preference loading','stale home response','slow admission','single submission','safe navigation','failure feedback','idempotent retry','normal polling and cancel']}));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.close());
