"""Manual browser QA: real saved-reading APIs, isolated PG/GitHub simulator.

Run with TEST_LEGACY_PG_DSN pointing to localhost. Ctrl-C removes test data.
"""
from collections import Counter
import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import time
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from cloud_fixtures import CloudFixture
from copilot.core import Problem
from reading.api import register
from study_materials import initialize as initialize_materials, register as register_materials
from study_notes import register as register_notes


def main():
    fixture = CloudFixture()
    fixture.setUp()
    try:
        store = fixture.new_reading();store.initialize();store.startup_error = None
        for index in range(23):
            store.import_from_paste(f'历史文章 {index+1:02d}：学习与证据',
                                    '# 学习与证据\n\n先区分观察到的事实和自己的解释，再寻找更多证据。\n\n' * 10,
                                    author='测试作者', language='zh', tags=['证据'],
                                    url=f'https://example.org/history-{index+1}')
        article = store.articles()[0]
        store.put('reading_records', 'job-history-fixture', dict(id='job-history-fixture', type='job', kind='collect',
                  state='ready', created_at='2026-10-17T10:00:00+08:00', candidates=[article], saved_ids=[], warnings=[]))
        directory = fixture.root / '结构化表达/每日练习';directory.mkdir(parents=True)
        (directory / 'Day 001.md').write_text('# 学习验证课程\n\n## 练习\n\n先写结论，再补充事实。')
        initialize_materials()
        app = FastAPI();counts = Counter()

        @app.middleware('http')
        async def timing(request, call_next):
            counts[request.method + ' ' + request.url.path] += 1
            if request.method == 'GET' and (request.url.path.startswith('/api/reading/articles/') or request.url.path.startswith('/api/study-materials/biaoda/')):
                await asyncio.sleep(3)
            return await call_next(request)

        @app.exception_handler(Problem)
        async def problem(request, error):
            return JSONResponse({'message': error.message}, status_code=error.status)

        with patch('reading.api.make_store', return_value=store):
            register(app, fixture.root, fixture.runtime)
        register_materials(app, fixture.root);register_notes(app)
        static = Path(__file__).resolve().parents[1] / 'static'
        app.mount('/static', StaticFiles(directory=static))

        @app.get('/')
        def index():return FileResponse(static / 'index.html')

        @app.get('/login')
        def login_page():return FileResponse(static / 'login.html')

        @app.post('/api/auth/login')
        def login():
            time.sleep(3)
            return {'ok': True}

        @app.get('/api/auth/me')
        def identity():
            time.sleep(.5)
            return {'user': {'id': 'performance-fixture', 'username': '隔离验证', 'is_owner': True}}

        @app.get('/api/data')
        def data():
            return dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[],
                        predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')

        @app.get('/api/plans')
        def plans():
            time.sleep(5)
            return dict(plans=[], attempts=[], legacy=[])

        @app.get('/api/search')
        def search(q: str):
            time.sleep(3)
            return {'results': [], 'total_count': 0}

        @app.get('/__qa/stats')
        def stats():return dict(counts)

        @app.get('/api/{rest:path}')
        def empty(rest: str):
            return dict(modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[], entries=[],
                        reports=[], stats={}, preferences={}, budget={}, attempts=[], legacy=[], drafts=[])

        sock = socket.socket();sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1);sock.bind(('127.0.0.1', int(os.getenv('GROW_QA_PORT', '0'))))
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        signal.signal(signal.SIGTERM, lambda *_: setattr(server, 'should_exit', True))
        print(json.dumps({'url': 'http://127.0.0.1:' + str(sock.getsockname()[1])}), flush=True)
        server.run(sockets=[sock])
    finally:
        fixture.doCleanups()


if __name__ == '__main__':main()
