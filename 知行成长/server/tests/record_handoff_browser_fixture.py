"""Local-only, synthetic records-link panel with real PG and Zook HTTP transport."""
import os,json,socket,subprocess,tempfile,uuid
from pathlib import Path
from unittest.mock import patch
import httpx,psycopg2,uvicorn
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from copilot.core import Problem
from reflections.api import register
from tenancy import current_user
import db

DSN=os.environ['TEST_POSTGRES_DSN']
if 'host=127.0.0.1' not in DSN:raise RuntimeError('Synthetic localhost PostgreSQL required')
schema='record_browser_'+uuid.uuid4().hex
with psycopg2.connect(DSN) as c:c.cursor().execute('CREATE SCHEMA '+schema)
secret='record-handoff-browser-test-secret-1234567'
backend=subprocess.Popen(['node','--experimental-transform-types','test/support/lighttick-record-handoff-http-fixture.ts'],cwd=os.environ['TEST_ZOOK_WORKTREE'],text=True,stdout=subprocess.PIPE,stderr=open("/tmp/grow-g1-browser-backend.log","w"),env={**os.environ,'LIGHTTICK_RECORD_HANDOFF_ENABLED':'1','GROW_RECORDS_SOURCE_ID':'grow-browser','GROW_RECORDS_BRIDGE_SECRET':secret,'LIGHTTICK_TEST_DATABASE_URL':'postgresql://localhost:55439/postgres'})
fixture=None
for line in backend.stdout:
 if line.startswith('READY '):fixture=json.loads(line[6:]);break
if fixture is None:raise RuntimeError(Path('/tmp/grow-g1-browser-backend.log').read_text())
url='http://127.0.0.1:'+str(fixture['port'])
os.environ.update(LIGHTTICK_BRIDGE_URL=url,GROW_RECORDS_SOURCE_ID='grow-browser',GROW_RECORDS_BRIDGE_SECRET=secret,PLAN_CONTENT_BACKEND='github')
original=db.connect;db.connect=lambda *a,**k:original(DSN+' options=-csearch_path='+schema,tenant=False)
app=FastAPI();root=tempfile.TemporaryDirectory(prefix='grow-record-browser-');store,assistant=register(app,root.name,root.name)
identity={'id':'source-'+schema,'schema_name':schema,'is_owner':True}
current_user.set(identity);store.initialize()
store.create({'record_date':'2026-10-25','raw_text':'合成验收记录：今天把一个想法记下来。','prompt_kind':'自由记录','guided_answers':{},'tags':['合成验收']},'browser-create-key')
@app.middleware('http')
async def synthetic_identity(request,call_next):
 token=current_user.set(identity)
 try:return await call_next(request)
 finally:current_user.reset(token)
@app.exception_handler(Problem)
async def problem(request,error):return JSONResponse({'message':error.message,'error':error.code},status_code=error.status)
static=Path(__file__).resolve().parents[1]/'static'
app.mount('/static',StaticFiles(directory=static),name='static')
@app.get('/')
def page():return HTMLResponse('''<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Grow 记录联动合成验收</title><style>body{font:17px system-ui;background:#f7f8f5;color:#24362b;max-width:760px;margin:32px auto;padding:20px;line-height:1.7}section{background:white;padding:24px;border:1px solid #d8e2d9;border-radius:16px}input{font:inherit;max-width:100%;box-sizing:border-box}input:not([type=checkbox]){display:block;width:100%;padding:10px}button{font:inherit;margin:8px 8px 8px 0;padding:10px 16px;border:1px solid #6f8974;border-radius:8px;background:#eff5ee;color:#23472e}label{display:block}p[role=status]{color:#8a4b0f}h1{font-size:20px}</style><h1>Grow 记录联动 · 合成数据验收</h1><section id="recordLinkSettings"></section><script src="/static/record-link.js"></script></html>''')
code=httpx.post(url+'/api/v1/lighttick/record-link/tickets',json={},headers={'Authorization':'Bearer '+fixture['owners'][0]['token'],'X-App-Id':'lighttick'}).json()['data']['code']
sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
print('READY '+json.dumps({'url':'http://127.0.0.1:'+str(port),'code':code}),flush=True)
try:uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')
finally:
 backend.terminate();backend.wait(timeout=20);root.cleanup()
 with psycopg2.connect(DSN) as c:c.cursor().execute('DROP SCHEMA '+schema+' CASCADE')
