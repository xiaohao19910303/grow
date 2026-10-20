"""Real cookie authentication and actions in disposable localhost PostgreSQL."""
from pathlib import Path
from unittest.mock import patch
import os, json, signal, uuid, tempfile
import psycopg2
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import db, accounts, action_plans

def main():
    dsn=os.environ['TEST_LEGACY_PG_DSN']
    if 'host=127.0.0.1' not in dsn:raise RuntimeError('localhost only')
    schema='action_link_qa_'+uuid.uuid4().hex
    with psycopg2.connect(dsn) as c:c.cursor().execute('CREATE SCHEMA '+schema)
    database=patch.object(db,'DATABASE_URL',dsn+' options=-csearch_path='+schema)
    env=patch.dict(os.environ,{'LIGHTTICK_BRIDGE_URL':'http://127.0.0.1:18880','GROW_ACTION_BRIDGE_SECRET':'TEST_ONLY_BRIDGE_SECRET_01234567890123456789','APP_USERNAME':'qa_alice','APP_PASSWORD':'ISOLATED-QA-Password-1234-ONLY'})
    database.start();env.start()
    try:
        app=FastAPI();app.state.multiuser=True;static=Path(__file__).resolve().parents[1]/'static'
        action_plans.register(app)
        auth=accounts.install(app,static,lambda user:None);auth.initialize()
        app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():return FileResponse(static/'index.html')
        @app.get('/api/data')
        def data():return dict(modules=[],checkins={},habits={},customFields=[],customRecords=[],decisions=[],predictions=[],reviews=[],insights=[],todos=[],_revision='fixture')
        @app.get('/api/{rest:path}')
        def empty(rest:str):return dict(modules=[],lessons=[],plans=[],records=[],items=[],articles=[],jobs=[],entries=[],reports=[],stats={},preferences={},budget={},attempts=[],legacy=[],drafts=[])
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18881,log_level='error'))
        signal.signal(signal.SIGTERM,lambda *_:setattr(server,'should_exit',True))
        print(json.dumps({'url':'http://127.0.0.1:18881','schema':schema}),flush=True);server.run()
    finally:
        database.stop();env.stop()
        with psycopg2.connect(dsn) as c:c.cursor().execute('DROP SCHEMA '+schema+' CASCADE')

if __name__=='__main__':main()
