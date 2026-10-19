"""Serve the real readers/APIs with disposable local PostgreSQL data for manual QA.

TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=...' python tests/serve_study_notes_fixture.py
The printed URL uses a loopback-only random port; Ctrl-C removes the test schema.
"""
import json
from pathlib import Path
import signal
import socket

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from test_study_materials import StudyMaterialTests
from study_materials import register
from study_notes import register as register_notes


def main():
    fixture = StudyMaterialTests('test_completion_notes_replay_updates_and_history_preserve_original_files')
    fixture.setUp()
    try:
        (fixture.root / '结构化表达/每日练习/Day 001.md').write_text('''# P1 验证课程：结论先行

## 练习 1：改写工作建议

先写结论，再用事实支撑。

## 先做阅读理解

1. 本课的核心方法是什么？
2. 如何应用到一次工作沟通？

我的答案：
1.
2.

## 练习完成了吗？

- [ ] 写出结论
- [ ] 补充证据

## 参考答案与解释

### 阅读理解

1. 先给结论，再给原因和例子。
''', encoding='utf-8')
        app = FastAPI()
        register(app, fixture.root)
        register_notes(app)
        static = Path(__file__).resolve().parents[1] / 'static'
        app.mount('/static', StaticFiles(directory=static))

        @app.get('/')
        def index():
            return FileResponse(static / 'index.html')

        @app.get('/api/auth/me')
        def identity():
            return {'user': {'id': 'study-notes-fixture', 'username': 'P1 隔离验证', 'is_owner': True}}

        @app.get('/api/data')
        def data():
            return dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[],
                        predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')

        @app.get('/api/{rest:path}')
        def empty(rest: str):
            return dict(modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[], entries=[],
                        reports=[], stats={}, preferences={}, budget={}, attempts=[], legacy=[], drafts=[])

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        signal.signal(signal.SIGTERM, lambda *_: setattr(server, 'should_exit', True))
        print(json.dumps({'url': 'http://127.0.0.1:' + str(sock.getsockname()[1])}), flush=True)
        server.run(sockets=[sock])
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main()
