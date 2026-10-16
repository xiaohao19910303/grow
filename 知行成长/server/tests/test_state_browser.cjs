// Actual UI + actual APIs, backed by a temporary workspace and an ephemeral port.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');
const server = path.resolve(__dirname, '..');
const temp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'grow-state-browser-')));
const fixture = String.raw`
import json,os,socket,sqlite3,sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import app as dashboard
from copilot.core import Problem
from reflections.api import register
server=Path.cwd();root=Path(os.environ['P0_TEST_ROOT']).resolve()
assert root.name.startswith('grow-state-browser-') and not root.is_relative_to(server.parent.parent)
def guard(event,args):
 if event=='sqlite3.connect' and str(server.parent.parent) in str(args[0]):
  raise RuntimeError('Real workspace database access blocked')
sys.addaudithook(guard)
dashboard.DB_PATH=root/'data.db';dashboard.init_db()
s=dashboard.load_state();s['modules']=dashboard.DEFAULT_MODULES
s['reviews']=[{'date':'2026-10-16','thought':'old review','actual':'','gap':'','action':''}]
dashboard.save_state(s,require_revision=True)
api=FastAPI()
@api.exception_handler(Problem)
async def problem(request,error):return JSONResponse({'error':error.code,'message':error.message},status_code=error.status)
api.get('/api/data')(dashboard.get_data);api.put('/api/data')(dashboard.put_data)
store,_=register(api,root,dashboard.DB_PATH);store.initialize()
entry=store.create({'record_date':'2026-10-16','raw_text':'original reflection','tags':['keep'],'guided_answers':{}},'browser-create-key')
api.mount('/static',StaticFiles(directory=server/'static'),name='static')
@api.get('/')
def index():return FileResponse(server/'static/index.html')
@api.get('/api/{rest:path}')
def empty(rest:str):return {'modules':[],'lessons':[],'plans':[],'records':[],'items':[],'reports':[],'daily':[],'stats':{},'total':0,'trend':[],'top_concepts':[],'module_distribution':[],'types':[]}
sock=socket.socket();sock.bind(('127.0.0.1',0))
print(json.dumps({'port':sock.getsockname()[1],'id':entry['id'],'mirror':str(root/store.entry(entry['id'])['path'])}),flush=True)
uvicorn.Server(uvicorn.Config(api,log_level='error')).run(sockets=[sock])
`;
const child = spawn(path.resolve(server, '../.venv/bin/python'), ['-c',fixture], {
  cwd:server, env:{...process.env,P0_TEST_ROOT:temp,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe'],
});
let stderr='';child.stderr.on('data',x=>stderr+=x);
async function response(page,status){
  return page.waitForResponse(r=>new URL(r.url()).pathname==='/api/data' && r.request().method()==='PUT' && r.status()===status);
}
(async()=>{
  const meta=await new Promise((resolve,reject)=>{
    let out='';const timer=setTimeout(()=>reject(Error('fixture startup timeout: '+stderr)),15000);
    child.stdout.on('data',x=>{out+=x;if(out.includes('\n')){clearTimeout(timer);resolve(JSON.parse(out.split('\n')[0]))}});
    child.once('exit',()=>{clearTimeout(timer);reject(Error('fixture exited: '+stderr))});
  });
  const base='http://127.0.0.1:'+meta.port;
  let ready=false;
  for(let i=0;i<100;i++){try{if((await fetch(base+'/api/data')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,50))}
  assert.ok(ready,'fixture not ready');
  const browser=await chromium.launch({headless:true});
  try{
    const context=await browser.newContext({acceptDownloads:true});
    await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
    const first=await context.newPage(),second=await context.newPage();
    const errors=[];
    for(const p of [first,second]){
      p.on('pageerror',e=>errors.push(e.message));
      await p.goto(base);
      await p.waitForFunction(()=>document.getElementById('storageStatus').textContent.includes('已连接'));
      await p.getByRole('button',{name:'记录',exact:true}).click();
      await p.locator('#reflectionList .ref-row').waitFor();
    }
    const before=await (await fetch(base+'/api/data')).json();
    await first.locator('#reviewTable').getByRole('button',{name:'编辑',exact:true}).click();
    await first.locator('#gf_thought').fill('first page saved');
    let saved=response(first,200);await first.locator('#gfSaveBtn').click();await saved;
    const after=await (await fetch(base+'/api/data')).json();
    assert.equal(after.reviews[0].id,before.reviews[0].id);
    await second.locator('#reviewTable').getByRole('button',{name:'编辑',exact:true}).click();
    await second.locator('#gf_thought').fill('second page unsaved');
    let conflict=response(second,409);await second.locator('#gfSaveBtn').click();await conflict;
    await second.locator('#legacyConflict').waitFor();
    assert.equal(await second.evaluate(()=>state.reviews[0].thought),'second page unsaved');
    assert.equal((await (await fetch(base+'/api/data')).json()).reviews[0].thought,'first page saved');
    let download=second.waitForEvent('download');await second.getByRole('button',{name:'下载副本并载入最新记录'}).click();
    const copy=await download;await copy.saveAs(path.join(temp,'unsaved-state.json'));
    assert.equal(JSON.parse(fs.readFileSync(path.join(temp,'unsaved-state.json'),'utf8')).reviews[0].thought,'second page unsaved');
    await second.waitForFunction(()=>state.reviews[0].thought==='first page saved');
    // Change only the synthetic mirror, then save through the real editor.
    assert.ok(meta.mirror.startsWith(temp+path.sep));
    const external='external personal text\n<script>throw Error("must stay text")</script>';
    fs.writeFileSync(meta.mirror,external);
    await first.locator('#reflectionList').getByRole('button',{name:'编辑',exact:true}).click();
    await first.locator('#refRaw').fill('unsaved reflection draft');
    const refConflict=first.waitForResponse(r=>r.url().includes('/api/reflections/'+meta.id) && r.request().method()==='PUT' && r.status()===409);
    await first.locator('#refSaveBtn').click();await refConflict;
    await first.locator('#refConflict textarea').first().waitFor();
    assert.equal(await first.locator('#refRaw').inputValue(),'unsaved reflection draft');
    assert.equal(await first.locator('#refConflict textarea').nth(1).inputValue(),external);
    assert.equal(fs.readFileSync(meta.mirror,'utf8'),external);
    assert.equal((await (await fetch(base+'/api/reflections/'+meta.id)).json()).entry.raw_text,'original reflection');
    download=first.waitForEvent('download');await first.getByRole('button',{name:'下载当前草稿并重新读取'}).click();
    const draft=await download;await draft.saveAs(path.join(temp,'reflection-draft.txt'));
    assert.equal(fs.readFileSync(path.join(temp,'reflection-draft.txt'),'utf8'),'unsaved reflection draft');
    await first.waitForFunction(()=>document.getElementById('refRaw').value==='original reflection');
    assert.deepEqual(errors,[],'unexpected browser errors');
    console.log('Browser checks passed: actual UI/API stable ID, two-page conflict, unsaved copy, external-file protection, escaped diff and draft reload.');
  }finally{await browser.close()}
})().catch(e=>{console.error(e,stderr);process.exitCode=1}).finally(async()=>{
  if(child.exitCode===null && child.signalCode===null){const stopped=new Promise(r=>child.once('exit',r));child.kill('SIGTERM');await stopped}
  fs.rmSync(temp,{recursive:true,force:true});
});
