"""Isolated standard-library checks. Never touch the real database or network."""
import asyncio
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot.core import MODULE, Store, Problem, digest, encoded
from copilot.backup import snapshot, restore_preview, restore
from copilot.generation import Generator, SEPARATOR

ROOT = Path(__file__).resolve().parents[3]
DATE = '2026-10-14T10:00:00+08:00'


class CourseChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / MODULE, self.root / MODULE)
        (self.root / 'server').mkdir()
        self.store = Store(self.root, self.root / 'server/data.db')
        self.clock = patch('copilot.core.now', return_value=DATE)
        self.clock.start()
        self.store.initialize()

    def tearDown(self):
        self.clock.stop()
        self.temp.cleanup()

    def writer(self):
        self.store.set_meta('writer_session', {'expires_at': '2099-01-01T00:00:00+08:00'})

    def sources(self):
        p = self.store.path('备课资料')
        p.mkdir(exist_ok=True)
        (p / '第003课-摘要.md').write_text('已核验的教学摘要。', encoding='utf-8')
        (p / '第003课.json').write_text(encoded([{'title': '测试资料', 'url': 'https://example.org/source',
            'verified_at': '2026-10-13', 'verification': '隔离测试夹具，不代表实际核验',
            'claim': '示范内容', 'note_path': '备课资料/第003课-摘要.md'}]), encoding='utf-8')

    def ready_draft(self):
        self.sources()
        data, plan, source, blockers = self.store.readiness()
        self.assertFalse(blockers)
        content = ('# 第003课：确认偏误\n\n日期：2026-10-14\n\n## 引导问题\n问题\n'
                   '## 核心概念\n概念\n## 完整示范\n假设案例\n## 误区与边界\n边界\n'
                   '## 练习\n练习\n\n---\n\n## 参考分析\n分析\n## 自查\n标准\n## 记忆提示\n提示\n'
                   '[来源](https://example.org/source)')
        d = {'lesson_no': 3, 'content': content, 'sources': '[来源](https://example.org/source)\n本地资料摘要',
             'source_snapshot': source, 'plan_snapshot': plan, 'record_hash': self.store.file_hash('学习记录.md'),
             'stream_completed': True, 'errors': []}
        with self.store.conn() as c:
            c.execute('INSERT INTO copilot_drafts VALUES (?,?,1,?,?,?)', ('draft', 3, 'ready', encoded(d), DATE))
        return d

    def test_existing_import_and_read_only_content(self):
        before = {str(p.relative_to(self.store.module)): p.read_bytes() for p in self.store.module.rglob('*.md')}
        result = self.store.scan()
        self.assertEqual((result['generated_count'], result['completed_count']), (2, 0))
        self.assertEqual(result['next_generation_lesson'], 3)
        self.assertEqual(result['blockers'], [])
        self.assertEqual(before, {str(p.relative_to(self.store.module)): p.read_bytes() for p in self.store.module.rglob('*.md')})

    def test_same_day_and_missing_volume(self):
        with patch('copilot.core.now', return_value='2026-10-13T20:00:00+08:00'):
            self.assertIn('already_generated_today', [x['code'] for x in self.store.readiness()[3]])
        self.store.module.rename(self.root / 'unmounted')
        with self.assertRaises(Problem) as e:
            self.store.scan()
        self.assertEqual(e.exception.code, 'workspace_unavailable')
        with self.store.conn() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM copilot_lessons').fetchone()[0], 2)

    def test_duplicate_missing_sources_and_short_filename(self):
        course = self.store.path('每日课程/2026-10-13-第002课-什么样的证据更可信.md')
        short = self.store.path('每日课程/第002课.md')
        shutil.copyfile(course, short)
        self.assertTrue(self.store.scan()['blockers'])
        short.unlink()
        self.store.path('参考资料/第002课-参考资料.md').unlink()
        self.assertEqual(self.store.scan()['generated_count'], 1)
        course.rename(short)
        self.assertEqual(self.store.scan()['lessons'][1]['date'], '2026-10-13')

    def test_plan_confirmation_invalidation_and_missing_sources(self):
        self.assertEqual(self.store.plan()['items'][0]['topic'], '区分事实、解释与判断')
        self.assertIn('sources_required', [x['code'] for x in self.store.readiness()[3]])
        p = self.store.path('课程主题规划.md')
        p.write_text('| 008 | 注意力 | 解释注意力 |\n', encoding='utf-8')
        plan = self.store.plan()
        self.assertFalse(plan['items'][0]['confirmed'])
        self.assertTrue(self.store.confirm_plan(plan['hash'], [8])['items'][0]['confirmed'])
        p.write_text('| 008 | 记忆 | 解释记忆 |\n', encoding='utf-8')
        self.assertFalse(self.store.plan()['items'][0]['confirmed'])

    def test_publish_idempotency_and_learning(self):
        self.ready_draft()
        with self.assertRaises(Problem) as e:
            self.store.publish('draft', 1, 'publish-key')
        self.assertEqual(e.exception.code, 'external_writer_uncoordinated')
        self.writer()
        record = self.store.path('学习记录.md').read_text()
        personal = record.split('## 个人记录区', 1)[1]
        first = self.store.publish('draft', 1, 'publish-key')
        self.assertEqual(first, self.store.publish('draft', 1, 'publish-key'))
        self.assertEqual(self.store.scan()['generated_count'], 3)
        self.assertEqual(self.store.scan()['completed_count'], 0)
        self.assertEqual(personal, self.store.path('学习记录.md').read_text().split('## 个人记录区', 1)[1])
        lesson = self.store.lesson(3)
        self.store.learning(3, 'completed', lesson['version'], 'learning-key')
        self.assertEqual(self.store.scan()['completed_count'], 1)
        lesson = self.store.lesson(3)
        self.store.learning(3, 'unknown', lesson['version'], 'unlearn-key')
        self.assertEqual(self.store.scan()['completed_count'], 0)
        with self.assertRaises(Problem):
            self.store.publish('draft', 2, 'publish-key')

    def test_conflict_preserves_external_notes(self):
        self.ready_draft(); self.writer()
        p = self.store.path('学习记录.md')
        p.write_text(p.read_text() + '\n我的新笔记\n')
        with self.assertRaises(Problem):
            self.store.publish('draft', 1, 'publish-key')
        self.assertIn('我的新笔记', p.read_text())
        self.assertEqual(len(list(self.store.path('每日课程').glob('*.md'))), 2)

    def test_recovery_after_second_file_failure(self):
        self.ready_draft(); self.writer()
        import os
        original = os.link
        count = 0
        def link(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('simulated disk failure')
            original(src, dst)
        with patch('copilot.core.os.link', side_effect=link):
            with self.assertRaises(Problem):
                self.store.publish('draft', 1, 'publish-key')
        with self.store.conn() as c:
            op = c.execute('SELECT id FROM copilot_operations').fetchone()[0]
        self.assertEqual(self.store.recover(op)['status'], 'done')
        self.assertEqual(self.store.scan()['generated_count'], 3)
        self.assertEqual(self.store.recover(op)['status'], 'done')

    def test_path_and_version_protection(self):
        with self.assertRaises(Problem):
            self.store.path('../outside.md')
        self.store.path('备课资料').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(Problem):
            self.store.path('备课资料/note.md')
        self.store.path('学习记录.md').write_text(self.store.path('学习记录.md').read_text() + '\n笔记\n')
        self.writer()
        with self.assertRaises(Problem):
            self.store.learning(1, 'completed', '0' * 64, 'bad-version')

    def test_backup_restore_preserves_learning_state(self):
        self.writer()
        self.store.learning(1, 'completed', self.store.lesson(1)['version'], 'complete-key')
        with self.store.lock():
            backup = snapshot(self.store)
        self.store.learning(1, 'unknown', self.store.lesson(1)['version'], 'undo-key')
        preview = restore_preview(self.store, backup['path'])
        restore(self.store, backup['path'], preview['preview_token'])
        self.assertEqual(self.store.scan()['completed_count'], 1)
        self.assertFalse((Path(backup['path']) / '.env').exists())

    def test_generation_simulated_events_and_cancel(self):
        d = self.ready_draft()
        with self.store.conn() as c:
            c.execute('DELETE FROM copilot_drafts')
        async def transport(messages, config):
            yield {'text': d['content'] + SEPARATOR + d['sources']}
            yield {'usage': {'prompt_tokens': 10, 'completion_tokens': 20}}
            yield {'done': True}
        g = Generator(self.store, transport)
        draft_id, fresh = g.begin(3, 'generation-key')
        self.assertTrue(fresh)
        self.assertEqual(g.begin(3, 'generation-key'), (draft_id, False))
        async def collect():
            return [x async for x in g.stream(draft_id, fresh)]
        events = asyncio.run(collect())
        self.assertTrue(any('event: completed' in x for x in events))
        self.assertEqual(self.store.draft(draft_id)['status'], 'ready')
        draft2, fresh = g.begin(3, 'generation-key-2')
        g.cancel(draft2)
        self.assertEqual(self.store.draft(draft2)['status'], 'cancelled')

    def test_gap_unknown_date_and_round_end(self):
        content = self.store.path('每日课程/2026-10-13-第002课-什么样的证据更可信.md').read_text()
        self.store.path('每日课程/第004课.md').write_text(content.replace('第002课', '第004课').replace('日期：2026-10-13', '日期未知'))
        scan = self.store.scan()
        self.assertTrue(any(x.get('lesson_no') == 3 for x in scan['blockers']))
        self.assertTrue(any('日期' in x['message'] for x in scan['blockers']))
        with patch.object(self.store, '_scan', return_value={'blockers': [], 'next_generation_lesson': None, 'today_lessons': []}):
            self.assertIn('round_complete', [x['code'] for x in self.store.readiness()[3]])

    def test_generation_failure_and_unverified_citation(self):
        d = self.ready_draft()
        d['content'] += '[新来源](https://unverified.example/source)'
        self.assertTrue(self.store.validate_draft(d))
        with self.store.conn() as c:
            c.execute('DELETE FROM copilot_drafts')
        async def broken(messages, config):
            yield {'text': '# 第003课：片段'}
            raise OSError('simulated interruption')
        g = Generator(self.store, broken)
        draft_id, fresh = g.begin(3, 'failed-generation')
        async def collect():
            return [x async for x in g.stream(draft_id, fresh)]
        result = asyncio.run(collect())
        self.assertTrue(any('event: failed' in x for x in result))
        self.assertEqual(self.store.draft(draft_id)['status'], 'failed')
        edited = self.store.edit_draft(draft_id, 1, d['content'], d['sources'])
        self.assertEqual(edited['status'], 'failed')

    def test_recovery_preserves_unknown_hash(self):
        self.writer()
        with self.store.lock():
            with patch('copilot.core.os.link', side_effect=OSError('disk failure')):
                with self.assertRaises(Problem):
                    self.store.prepare('operation-key', {}, [{'path': '参考资料/new.md', 'old_hash': None, 'content': 'expected'}])
        with self.store.conn() as c:
            op = c.execute('SELECT id FROM copilot_operations').fetchone()[0]
        target = self.store.path('参考资料/new.md'); target.write_text('personal edit')
        with self.assertRaises(Problem):
            self.store.recover(op)
        self.assertEqual(target.read_text(), 'personal edit')

    def test_old_state_sync_does_not_clear_copilot(self):
        import app as dashboard
        with patch.object(dashboard, 'DB_PATH', self.store.db):
            dashboard.init_db()
            dashboard.save_state({'modules': dashboard.DEFAULT_MODULES})
            with self.store.conn() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM copilot_lessons').fetchone()[0], 2)

    def test_backup_change_detection_and_stale_preview(self):
        from copilot.backup import inventory
        expected = inventory(self.store)
        with patch('copilot.backup.inventory', side_effect=[expected, {**expected, 'extra.md': 'changed'}]):
            with self.assertRaises(Problem):
                snapshot(self.store)
        with self.store.lock():
            backup = snapshot(self.store)
        preview = restore_preview(self.store, backup['path'])
        self.store.path('学习记录.md').write_text(self.store.path('学习记录.md').read_text() + '\n新笔记\n')
        with self.assertRaises(Problem):
            restore(self.store, backup['path'], preview['preview_token'])

    def test_full_168_lesson_boundary(self):
        from datetime import date, timedelta
        import re
        original = self.store.path('每日课程/2026-10-13-第002课-什么样的证据更可信.md').read_text()
        for p in self.store.path('每日课程').glob('*.md'):
            p.unlink()
        for p in self.store.path('参考资料').glob('*.md'):
            p.unlink()
        rows = ['# 课程目录与学习记录\n\n| 课次 | 生成日期 | 课程 | 资料 | 学习状态 |\n|---|---|---|---|---|\n']
        for n in range(1, 169):
            day = (date(2025, 1, 1) + timedelta(days=n)).isoformat()
            course = f'每日课程/{day}-第{n:03d}课-样本.md'
            source = f'参考资料/第{n:03d}课-参考资料.md'
            content = original.replace('第002课', f'第{n:03d}课').replace('2026-10-13', day)
            content = re.sub(r'\[[^\]]*\]\(\.\./参考资料/[^)]+\)', f'[资料](../{source})', content)
            content += '\n## 复盘回顾与跨领域整合\n隔离教学样本\n'
            self.store.path(course).write_text(content)
            self.store.path(source).write_text(f'# 参考资料\n本地摘要\n[课程](../{course})')
            rows.append(f'| {n:03d} | {day} | [课程]({course}) | [资料]({source}) | 待本人记录 |\n')
        self.store.path('学习记录.md').write_text(''.join(rows))
        state = self.store.scan()
        self.assertEqual(state['generated_count'], 168)
        self.assertIsNone(state['next_generation_lesson'])
        self.assertEqual(state['completed_count'], 0)
        self.assertEqual(state['blockers'], [])

    def test_isolated_api_access_and_local_reading(self):
        from fastapi import FastAPI
        from copilot.api import register
        app = FastAPI()
        register(app, self.root, self.store.db)
        async def send_request(path, headers=None, method='GET', body=b'', peer='127.0.0.1'):
            messages = []
            async def send(message):
                messages.append(message)
            sent = False
            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                await asyncio.Event().wait()
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                     'method': method, 'scheme': 'http', 'path': path.split('?')[0],
                     'raw_path': path.split('?')[0].encode(), 'query_string': path.partition('?')[2].encode(),
                     'root_path': '', 'headers': headers or [(b'host', b'localhost')],
                     'client': (peer, 1234), 'server': ('localhost', 80)}
            await app(scope, receive, send)
            status = next(x['status'] for x in messages if x['type'] == 'http.response.start')
            payload = b''.join(x.get('body', b'') for x in messages if x['type'] == 'http.response.body')
            return status, json.loads(payload)
        code, data = asyncio.run(send_request('/api/copilot/today-task'))
        self.assertEqual(code, 200)
        self.assertEqual(data['generated_count'], 2)
        code, _ = asyncio.run(send_request('/api/copilot/lessons/1'))
        self.assertEqual(code, 200)
        code, _ = asyncio.run(send_request('/api/copilot/today-task?module=other'))
        self.assertEqual(code, 422)
        code, _ = asyncio.run(send_request('/api/copilot/today-task', [(b'host', b'evil.example')]))
        self.assertEqual(code, 403)
        code, _ = asyncio.run(send_request('/api/copilot/scan', method='POST', body=b'{}'))
        self.assertEqual(code, 403)
        code, _ = asyncio.run(send_request('/api/copilot/today-task', peer='192.168.1.2'))
        self.assertEqual(code, 403)
        headers = [(b'host', b'localhost'), (b'origin', b'https://evil.example'), (b'x-copilot-request', b'1')]
        code, _ = asyncio.run(send_request('/api/copilot/scan', headers, 'POST', b'{}'))
        self.assertEqual(code, 403)

    def test_numbered_tables_in_personal_notes_are_not_catalog(self):
        p = self.store.path('学习记录.md')
        p.write_text(p.read_text() + '\n| 001 | 我的个人练习答案 |\n')
        self.assertEqual(self.store.scan()['generated_count'], 2)
        self.writer()
        self.store.learning(1, 'completed', self.store.lesson(1)['version'], 'notes-kept-key')
        self.assertIn('| 001 | 我的个人练习答案 |', p.read_text())

    def test_concurrent_publication_is_single(self):
        from concurrent.futures import ThreadPoolExecutor
        self.ready_draft(); self.writer()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.publish('draft', 1, 'concurrent-key'), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.store.scan()['generated_count'], 3)
        rows = [line for _, n, line in self.store.record_rows(self.store.path('学习记录.md').read_text()) if n == 3]
        self.assertEqual(len(rows), 1)

    def test_recovery_after_index_failure(self):
        import os
        self.ready_draft(); self.writer()
        original = os.replace
        def replace(src, dst):
            if Path(dst).name == '学习记录.md':
                raise OSError('simulated index failure')
            original(src, dst)
        with patch('copilot.core.os.replace', side_effect=replace):
            with self.assertRaises(Problem):
                self.store.publish('draft', 1, 'index-failure-key')
        with self.store.conn() as c:
            op = c.execute('SELECT id FROM copilot_operations').fetchone()[0]
        self.assertEqual(self.store.recover(op)['status'], 'done')
        self.assertEqual(self.store.scan()['generated_count'], 3)

    def test_recovery_after_database_finalize_failure(self):
        from contextlib import contextmanager
        self.ready_draft(); self.writer()
        original = self.store.conn
        triggered = False
        class ConnectionProxy:
            def __init__(self, connection):
                self.connection = connection
            def execute(self, sql, parameters=()):
                nonlocal triggered
                if "UPDATE copilot_operations SET status='done'" in sql and not triggered:
                    triggered = True
                    raise sqlite3.OperationalError('simulated commit failure')
                return self.connection.execute(sql, parameters)
            def __getattr__(self, attr):
                return getattr(self.connection, attr)
        @contextmanager
        def conn():
            with original() as c:
                yield ConnectionProxy(c)
        with patch.object(self.store, 'conn', conn):
            with self.assertRaises(Problem):
                self.store.publish('draft', 1, 'database-failure-key')
        with self.store.conn() as c:
            op = c.execute('SELECT id FROM copilot_operations').fetchone()[0]
        self.assertEqual(self.store.recover(op)['status'], 'done')
        self.assertEqual(self.store.scan()['generated_count'], 3)

    def test_unplanned_lesson_never_calls_transport(self):
        called = False
        async def transport(messages, config):
            nonlocal called
            called = True
            yield {'done': True}
        state = {'blockers': [], 'next_generation_lesson': 8, 'today_lessons': []}
        with patch.object(self.store, '_scan', return_value=state):
            with self.assertRaises(Problem) as error:
                Generator(self.store, transport).begin(8, 'unplanned-key')
        self.assertEqual(error.exception.code, 'plan_required')
        self.assertFalse(called)

    def test_different_writers_compete_for_same_lesson(self):
        from concurrent.futures import ThreadPoolExecutor
        self.ready_draft(); self.writer()
        def publish(key):
            try:
                return self.store.publish('draft', 1, key)['status']
            except Problem as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, ['writer-one-key', 'writer-two-key']))
        self.assertEqual(sorted(results), ['conflict', 'done'])
        self.assertEqual(self.store.scan()['generated_count'], 3)


if __name__ == '__main__':
    unittest.main()
