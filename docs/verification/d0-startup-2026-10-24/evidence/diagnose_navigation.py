import json, time, os, sys, subprocess, runpy, functools, fcntl, termios, array
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import BrowserContext, Page
out=Path(os.environ['D0_DIAGNOSTICS']);out.mkdir(parents=True,exist_ok=True)
log=(out/'navigation.jsonl').open('a',buffering=1)
fixtures=[];requests={}
def event(kind,**data):log.write(json.dumps(dict(kind=kind,time=time.time(),**data),ensure_ascii=False)+'\n')
original_popen=subprocess.Popen
def spawn(*args,**kwargs):
    p=original_popen(*args,**kwargs)
    command=args[0] if args else kwargs.get('args',[])
    if any('serve_daily_arrangements_fixture.py' in str(v) for v in command):fixtures.append(p)
    return p
subprocess.Popen=spawn
original_new=BrowserContext.new_page
def new_page(self,*args,**kwargs):
    page=original_new(self,*args,**kwargs);pending={};requests[id(page)]=pending
    page.on('request',lambda r:(pending.update({id(r):dict(url=r.url,type=r.resource_type,started=time.perf_counter())}),event('request',url=r.url,type=r.resource_type)))
    def finished(r,failed=False):
        row=pending.pop(id(r),None)
        if row:event('request_failed' if failed else 'request_finished',url=row['url'],type=row['type'],ms=round(1000*(time.perf_counter()-row['started']),1),failure=r.failure if failed else None)
    page.on('requestfinished',finished);page.on('requestfailed',lambda r:finished(r,True))
    page.on('pageerror',lambda e:event('pageerror',error=str(e)[:3000]))
    page.on('domcontentloaded',lambda:event('domcontentloaded',url=page.url))
    page.on('load',lambda:event('load',url=page.url))
    return page
BrowserContext.new_page=new_page
for name in ('goto','reload'):
    original=getattr(Page,name)
    def decorate(original,name):
        @functools.wraps(original)
        def navigate(self,*args,**kwargs):
            begin=time.perf_counter();event('nav_begin',method=name,options=kwargs)
            try:
                result=original(self,*args,**kwargs);event('nav_ok',method=name,ms=round(1000*(time.perf_counter()-begin),1));return result
            except Exception as error:
                event('nav_error',method=name,ms=round(1000*(time.perf_counter()-begin),1),error=str(error),pending=[dict(url=r['url'],type=r['type'],age_ms=round(1000*(time.perf_counter()-r['started']),1)) for r in requests.get(id(self),{}).values()])
                for p in fixtures:
                    if not p.stderr:continue
                    available=array.array('i',[0]);fcntl.ioctl(p.stderr.fileno(),termios.FIONREAD,available,True)
                    event('fixture_pipe',pid=p.pid,stderr_bytes=available[0])
                    if available[0]:
                        body=os.read(p.stderr.fileno(),available[0]);(out/('fixture-stderr-'+str(p.pid)+'.log')).write_bytes(body)
                raise
        return navigate
    setattr(Page,name,decorate(original,name))
sys.argv=[sys.argv[1],'--child','test_action_p0_browser.py']
runpy.run_path(sys.argv[0],run_name='__main__')
