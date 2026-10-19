# 课程完成闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a course completion loop: feedback → AI summary → advanced generation → archiving, so that finished courses get reviewed, archived, and can trigger new advanced courses.

**Architecture:** Four phases of incremental features. Each phase adds backend API + database schema + frontend UI. Backend extends `core.py` and `api.py` with new tables and methods; frontend adds new JS modules and modifies the daily learning view.

**Tech Stack:** Python 3.13 + FastAPI + SQLite (existing), vanilla JS (existing), OpenAI-compatible SSE streaming (existing `transport.py`).

**Spec:** `docs/superpowers/specs/2026-10-19-course-completion-loop-design.md`

## Global Constraints

- All AI-generated content is draft, requires manual confirmation before publish (existing principle)
- All operations are manually triggered, no auto-push
- Reuse existing `transport.py` for SSE streaming
- Reuse existing `copilot_learning_records` table pattern
- Single user local app, no cloud dependency
- API endpoints live under `/api/copilot/`
- Schema version must be bumped to '3' for new tables
- Follow existing code style: `fail()` for errors, `with self.lock()` for writes, `encoded()` for JSON serialization

## Review Focus

1. **SQLite migration on existing DB** — existing `copilot_learning_records` has no `archived` column; `ALTER TABLE ADD COLUMN` works but must be idempotent and not break existing data.
2. **Feedback without completion** — user can submit feedback only for completed lessons; API must reject feedback for incomplete lessons.
3. **AI summary with partial feedback** — not all lessons may have feedback; summary prompt must handle missing feedback gracefully.
4. **Archive/unarchive toggle** — archived lessons must not appear in daily view but must remain queryable; toggling must be instant and reversible.
5. **Advanced generation with no feedback** — if no feedback exists for a module, advanced generation should still work using just lesson topics.

---

### Task 1: Database Schema Migration + Feedback Backend

**Files:**
- Create: `server/tests/test_feedback.py`
- Modify: `server/copilot/core.py:129-177` (add new tables in `initialize()`)
- Modify: `server/copilot/core.py` (add `save_feedback`, `get_feedback`, `list_feedback` methods)
- Modify: `server/copilot/api.py` (add feedback request models + routes)

**Interfaces:**
- Consumes: existing `Store` class, `with self.conn()`, `with self.lock()`, `fail()`, `encoded()`, `now()`
- Produces: `save_feedback(lesson_no, data, key)`, `get_feedback(lesson_no)`, `list_feedback(module_id, round_id)` methods; API routes `POST /lessons/{number}/feedback`, `GET /lessons/{number}/feedback`

- [ ] **Step 1: Write failing test for feedback schema creation**

```python
def test_feedback_table_created_on_initialize(store):
    store.initialize()
    with store.conn() as c:
        row = c.execute("SELECT 1 FROM sqlite_master WHERE name='copilot_feedback'").fetchone()
    assert row is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Xiaohao/学习/知行成长/server && python -m pytest tests/test_feedback.py::test_feedback_table_created_on_initialize -v`
Expected: FAIL — table does not exist

- [ ] **Step 3: Add schema migration in `core.py:initialize()`**

Add to the `executescript` block after `copilot_learning_records` creation, and bump schema_version to '3'. Add these tables:

```sql
CREATE TABLE IF NOT EXISTS copilot_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id TEXT NOT NULL DEFAULT 'renzhi',
    round_id INTEGER NOT NULL DEFAULT 1,
    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
    mastery_level TEXT NOT NULL CHECK(mastery_level IN ('fully_understood', 'basically_understood', 'partially_understood', 'not_understood')),
    value_rating INTEGER NOT NULL CHECK(value_rating BETWEEN 0 AND 3),
    feeling_tags TEXT,
    key_learnings TEXT,
    questions TEXT,
    next_direction TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(module_id, round_id, lesson_no)
);

CREATE TABLE IF NOT EXISTS copilot_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id TEXT NOT NULL DEFAULT 'renzhi',
    round_id INTEGER NOT NULL DEFAULT 1,
    scope TEXT NOT NULL DEFAULT 'full_course',
    content TEXT NOT NULL,
    feedback_snapshot TEXT,
    created_at TEXT NOT NULL
);
```

Add schema_version migration block (version '3'): ALTER `copilot_learning_records` to add `archived INTEGER NOT NULL DEFAULT 0` and `archived_at TEXT` columns. Use `PRAGMA table_info` to check if columns exist before ALTER.

- [ ] **Step 4: Run test to verify schema is created**

Run: `cd /Volumes/Xiaohao/学习/知行成长/server && python -m pytest tests/test_feedback.py::test_feedback_table_created_on_initialize -v`
Expected: PASS

- [ ] **Step 5: Write failing test for save_feedback and get_feedback**

```python
def test_save_and_get_feedback(store):
    store.initialize()
    # Need a completed lesson first — create a minimal one
    # (reuse existing test fixture pattern from test_copilot.py)
    data = {
        'mastery_level': 'fully_understood',
        'value_rating': 3,
        'feeling_tags': ['例子很好', '概念很清晰'],
        'key_learnings': '核心观点是...',
        'questions': '',
        'next_direction': '想深入逻辑谬误'
    }
    result = store.save_feedback(1, data, 'test-key-001')
    assert result['lesson_no'] == 1
    fetched = store.get_feedback(1)
    assert fetched['mastery_level'] == 'fully_understood'
    assert fetched['value_rating'] == 3
```

- [ ] **Step 6: Implement `save_feedback`, `get_feedback`, `list_feedback` in `core.py`**

Add after `get_learning_history_months` method:

```python
def save_feedback(self, number, data, key):
    """Save course feedback. Requires lesson to be completed."""
    with self.lock():
        self._ensure_completed(number)
        with self.conn() as c:
            c.execute('''
                INSERT INTO copilot_feedback
                (module_id, round_id, lesson_no, mastery_level, value_rating,
                 feeling_tags, key_learnings, questions, next_direction, created_at)
                VALUES ('renzhi', 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(module_id, round_id, lesson_no) DO UPDATE SET
                    mastery_level=excluded.mastery_level,
                    value_rating=excluded.value_rating,
                    feeling_tags=excluded.feeling_tags,
                    key_learnings=excluded.key_learnings,
                    questions=excluded.questions,
                    next_direction=excluded.next_direction
            ''', (number, data['mastery_level'], data['value_rating'],
                  json.dumps(data.get('feeling_tags', []), ensure_ascii=False),
                  data.get('key_learnings', ''),
                  data.get('questions', ''),
                  data.get('next_direction', ''),
                  now()))
        return {'lesson_no': number, **data}

def get_feedback(self, number):
    with self.conn() as c:
        row = c.execute('''
            SELECT mastery_level, value_rating, feeling_tags, key_learnings,
                   questions, next_direction, created_at
            FROM copilot_feedback WHERE module_id='renzhi' AND round_id=1 AND lesson_no=?
        ''', (number,)).fetchone()
    if not row:
        return None
    result = dict(row)
    if result['feeling_tags']:
        result['feeling_tags'] = json.loads(result['feeling_tags'])
    return result

def list_feedback(self, module_id='renzhi', round_id=1):
    with self.conn() as c:
        rows = c.execute('''
            SELECT lesson_no, mastery_level, value_rating, feeling_tags,
                   key_learnings, questions, next_direction, created_at
            FROM copilot_feedback WHERE module_id=? AND round_id=?
            ORDER BY lesson_no
        ''', (module_id, round_id)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        if d['feeling_tags']:
            d['feeling_tags'] = json.loads(d['feeling_tags'])
        items.append(d)
    return items
```

Add helper `_ensure_completed(number)` that checks `copilot_learning_records` for the lesson.

- [ ] **Step 7: Run test to verify feedback CRUD**

Run: `cd /Volumes/Xiaohao/学习/知行成长/server && python -m pytest tests/test_feedback.py -v`
Expected: PASS

- [ ] **Step 8: Add feedback API routes in `api.py`**

Add Pydantic models:

```python
class FeedbackSubmission(Key):
    mastery_level: Literal['fully_understood', 'basically_understood', 'partially_understood', 'not_understood']
    value_rating: int = Field(ge=0, le=3)
    feeling_tags: list[str] = Field(default=[], max_length=10)
    key_learnings: str = Field(default='', max_length=2000)
    questions: str = Field(default='', max_length=2000)
    next_direction: str = Field(default='', max_length=1000)
```

Add routes:

```python
@router.post('/lessons/{number}/feedback')
def submit_feedback(number: int, body: FeedbackSubmission):
    return store.save_feedback(number, body.model_dump(), body.key)

@router.get('/lessons/{number}/feedback')
def get_feedback(number: int, module: Literal['renzhi'] = 'renzhi'):
    result = store.get_feedback(number)
    if not result:
        raise HTTPException(status_code=404, detail='未找到反馈记录。')
    return result
```

- [ ] **Step 9: Commit**

```bash
git add server/copilot/core.py server/copilot/api.py server/tests/test_feedback.py
git commit -m "feat: add course feedback schema, CRUD, and API endpoints"
```

---

### Task 2: Archive Backend + API

**Files:**
- Create: `server/tests/test_archive.py`
- Modify: `server/copilot/core.py` (add `archive_lesson`, `unarchive_lesson`, `list_archived` methods)
- Modify: `server/copilot/api.py` (add archive routes)
- Modify: `server/copilot/core.py:253-263` (include archived status in `_scan()` lesson data)

**Interfaces:**
- Consumes: `copilot_learning_records.archived` column (from Task 1 migration), existing `Store` methods
- Produces: `archive_lesson(number, key)`, `unarchive_lesson(number, key)`, `list_archived()` methods; API routes `POST /lessons/{number}/archive`, `POST /lessons/{number}/unarchive`, `GET /lessons/archived`

- [ ] **Step 1: Write failing test for archive**

```python
def test_archive_and_unarchive(store):
    store.initialize()
    # Create a completed lesson via existing mechanism
    store.archive_lesson(1, 'archive-key-001')
    archived = store.list_archived()
    assert any(x['lesson_no'] == 1 for x in archived)
    store.unarchive_lesson(1, 'unarchive-key-001')
    archived = store.list_archived()
    assert not any(x['lesson_no'] == 1 for x in archived)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Xiaohao/学习/知行成长/server && python -m pytest tests/test_archive.py -v`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Implement archive methods in `core.py`**

```python
def archive_lesson(self, number, key):
    with self.lock():
        self._ensure_completed(number)
        with self.conn() as c:
            c.execute('''
                UPDATE copilot_learning_records SET archived=1, archived_at=?
                WHERE module_id='renzhi' AND round_id=1 AND lesson_no=?
            ''', (now(), number))
        return {'archived': True}

def unarchive_lesson(self, number, key):
    with self.lock():
        with self.conn() as c:
            c.execute('''
                UPDATE copilot_learning_records SET archived=0, archived_at=NULL
                WHERE module_id='renzhi' AND round_id=1 AND lesson_no=?
            ''', (number,))
        return {'archived': False}

def list_archived(self):
    with self.conn() as c:
        rows = c.execute('''
            SELECT r.lesson_no, r.completed_at, r.archived_at,
                   f.mastery_level, f.key_learnings
            FROM copilot_learning_records r
            LEFT JOIN copilot_feedback f ON r.module_id=f.module_id AND r.round_id=f.round_id AND r.lesson_no=f.lesson_no
            WHERE r.module_id='renzhi' AND r.round_id=1 AND r.archived=1
            ORDER BY r.completed_at DESC
        ''').fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Update `_scan()` to include archived status**

In the `_scan()` method, after the database check at line ~253, add archived status to the lesson dict:

```python
db_archived = c.execute(
    'SELECT archived FROM copilot_learning_records WHERE module_id=\'renzhi\' AND round_id=1 AND lesson_no=?',
    (n,)).fetchone()
lesson['archived'] = bool(db_archived['archived']) if db_archived else False
```

- [ ] **Step 5: Add archive API routes in `api.py`**

```python
class ArchiveRequest(Key):
    pass

@router.post('/lessons/{number}/archive')
def archive(number: int, body: ArchiveRequest):
    return store.archive_lesson(number, body.key)

@router.post('/lessons/{number}/unarchive')
def unarchive(number: int, body: ArchiveRequest):
    return store.unarchive_lesson(number, body.key)

@router.get('/lessons/archived')
def archived_lessons(module: Literal['renzhi'] = 'renzhi'):
    return {'items': store.list_archived()}
```

- [ ] **Step 6: Run test to verify archive**

Run: `cd /Volumes/Xiaohao/学习/知行成长/server && python -m pytest tests/test_archive.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add server/copilot/core.py server/copilot/api.py server/tests/test_archive.py
git commit -m "feat: add course archive/unarchive backend and API"
```

---

### Task 3: Feedback Frontend — Modal UI + Course Card Integration

**Files:**
- Create: `server/static/course-feedback.js`
- Modify: `server/static/daily-learning.js` (add feedback button to course cards, add "待反馈" section)
- Modify: `server/static/copilot.js` (add feedback button to course cards in "我的课程")
- Modify: `server/static/index.html` (add script tag for course-feedback.js)

**Interfaces:**
- Consumes: `POST /api/copilot/lessons/{number}/feedback`, `GET /api/copilot/lessons/{number}/feedback`, `GET /api/copilot/lessons` (existing, now includes `archived` field)
- Produces: `window.showCourseFeedback(lessonNo)`, `window.checkLessonFeedback(lessonNo)` functions

- [ ] **Step 1: Create feedback modal UI in `course-feedback.js`**

Build a dialog-based modal with:
- Two-layer layout: quick tags (mastery, value, feeling) + free text fields
- Radio buttons for mastery_level (4 options) and value_rating (4 options)
- Checkbox group for feeling_tags (8 predefined + custom input)
- Three textareas for key_learnings, questions, next_direction
- Save button calls `POST /api/copilot/lessons/{number}/feedback`
- On success: close dialog, show toast, trigger page refresh

Style: match existing `copilot.css` variables (`--primary`, `--border`, `--bg-soft`, etc.)

- [ ] **Step 2: Add feedback button to daily-learning.js course cards**

In the completed lesson card rendering, add:
- If lesson has feedback: show "已反馈" badge with mastery emoji
- If lesson has no feedback: show "完成反馈" button that calls `showCourseFeedback(lesson_no)`
- Add a "待反馈" section above the completed lessons section, listing completed lessons without feedback

- [ ] **Step 3: Add feedback status to copilot.js course cards**

In the "我的课程" view, add feedback status indicator next to each completed course.

- [ ] **Step 4: Add script tag in `index.html`**

Add `<script src="course-feedback.js"></script>` after the copilot.js script tag.

- [ ] **Step 5: Test feedback flow end-to-end**

1. Start server: `./start.sh`
2. Navigate to 今日 tab
3. Click "完成反馈" on a completed course
4. Fill in feedback, save
5. Verify badge shows "已反馈" with mastery emoji
6. Refresh page, verify feedback persists

- [ ] **Step 6: Commit**

```bash
git add server/static/course-feedback.js server/static/daily-learning.js server/static/copilot.js server/static/index.html
git commit -m "feat: add course feedback modal UI and card integration"
```

---

### Task 4: Archive Frontend — Daily View Filter + Archive Page

**Files:**
- Create: `server/static/course-archive.js`
- Modify: `server/static/daily-learning.js` (filter archived lessons from today view)
- Modify: `server/static/index.html` (add archive page + script tag)

**Interfaces:**
- Consumes: `GET /api/copilot/lessons/archived`, `POST /api/copilot/lessons/{number}/archive`, `POST /api/copilot/lessons/{number}/unarchive`
- Produces: archive page UI, daily view filters archived lessons

- [ ] **Step 1: Filter archived lessons in daily-learning.js**

Modify the lesson filtering logic: when building `todayCompleted` and `pending` lists, exclude lessons where `lesson.archived === true`. Add a "待反馈" section for completed lessons without feedback (not yet archived).

- [ ] **Step 2: Create archive page UI in `course-archive.js`**

Build a page showing:
- List of archived courses with: lesson_no, topic, completed_at, mastery_level emoji, key_learnings preview
- Buttons per course: "查看反馈", "取消归档"
- Empty state message when no archived courses

- [ ] **Step 3: Add archive page to index.html navigation**

Add "课程归档" tab to the 学习 module navigation. Wire up tab switching.

- [ ] **Step 4: Test archive flow end-to-end**

1. Archive a course via API or UI
2. Verify it disappears from 今日 view
3. Navigate to 课程归档 page, verify it appears
4. Click "取消归档", verify it reappears in 今日 view

- [ ] **Step 5: Commit**

```bash
git add server/static/course-archive.js server/static/daily-learning.js server/static/index.html
git commit -m "feat: add archive page and filter archived lessons from daily view"
```

---

### Task 5: AI Course Summary Backend

**Files:**
- Create: `server/tests/test_summary.py`
- Create: `server/copilot/summary.py`
- Modify: `server/copilot/api.py` (add summary routes)
- Modify: `server/copilot/core.py` (add `list_summaries`, `get_summary`, `save_summary` methods)

**Interfaces:**
- Consumes: existing `transport.py` (`qwen_stream`), `config()` from `generation.py`, `list_feedback()` from Task 1, `_scan()` from core
- Produces: `generate_summary(module_id, round_id, scope)` method that returns SSE stream; summary saved to `copilot_summaries` table and Markdown file

- [ ] **Step 1: Write failing test for summary generation**

```python
def test_summary_prompt_includes_feedback(store):
    store.initialize()
    # Mock the transport to capture the prompt
    captured = []
    class MockTransport:
        async def stream(self, messages, cfg):
            captured.append(messages)
            yield {'done': True}
    gen = SummaryGenerator(store, MockTransport())
    # Add some feedback
    store.save_feedback(1, {'mastery_level': 'fully_understood', 'value_rating': 3,
                            'feeling_tags': [], 'key_learnings': 'test', 'questions': '', 'next_direction': ''}, 'key1')
    list(gen.generate('renzhi', 1, 'full_course'))
    assert any('feedback' in m['content'] for batch in captured for m in batch)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Xiaohao/学习/知行成长/server && python -m pytest tests/test_summary.py -v`
Expected: FAIL

- [ ] **Step 3: Create `server/copilot/summary.py`**

```python
"""AI-powered course summary generation."""
import json
from .core import now, encoded, fail, MODULE, TZ
from .generation import config, event
from datetime import datetime

SUMMARY_PROMPT_TEMPLATE = """你是一个个人学习助手。请基于以下信息，生成一份整门课程的复盘总结。

【课程信息】
模块名：{module_name}
已学课数：{completed_count}
课程列表：
{lesson_list}

【用户反馈】
{feedback_section}

【要求】
1. 总结这门课的核心知识框架（不是逐课复述，而是提炼脉络）
2. 基于用户的反馈，指出掌握得好的部分和需要加强的部分
3. 串联各课之间的关联
4. 给出进阶学习建议（参考用户填写的后续方向）
5. 用中文输出，语气像一个耐心的导师

【输出格式】
## 知识脉络
（核心框架）

## 掌握情况
（基于反馈的分析）

## 概念关联
（课与课之间的联系）

## 进阶建议
（后续学习方向）"""


class SummaryGenerator:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport

    def generate(self, module_id, round_id, scope='full_course'):
        lessons_data = self.store._scan()
        completed = [l for l in lessons_data['lessons'] if l['learning_state'] == 'completed']
        if not completed:
            fail('no_completed_lessons', '没有已完成的课程，无法生成总结。')

        feedback = self.store.list_feedback(module_id, round_id)
        feedback_by_lesson = {f['lesson_no']: f for f in feedback}

        lesson_list = '\n'.join(
            f"- 第{l['lesson_no']:03d}课：{l['topic']} ({l.get('completed_at', 'N/A')})"
            for l in completed
        )

        if feedback:
            fb_lines = []
            for l in completed:
                fb = feedback_by_lesson.get(l['lesson_no'])
                if fb:
                    fb_lines.append(f"- 第{l['lesson_no']:03d}课：掌握={fb['mastery_level']}, 收获={fb['value_rating']}/3, 感受={fb.get('feeling_tags', [])}, 收获={fb.get('key_learnings', '无')}, 方向={fb.get('next_direction', '无')}")
                else:
                    fb_lines.append(f"- 第{l['lesson_no']:03d}课：无反馈")
            feedback_section = '\n'.join(fb_lines)
        else:
            feedback_section = '暂无反馈数据'

        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            module_name=MODULE, completed_count=len(completed),
            lesson_list=lesson_list, feedback_section=feedback_section
        )

        messages = [
            {'role': 'system', 'content': '你是一个个人学习助手，擅长总结学习内容和生成复盘。'},
            {'role': 'user', 'content': prompt}
        ]

        cfg = config(self.store)
        if not cfg['key'] or not cfg['url']:
            fail('ai_not_configured', '请先在设置页面配置AI API。')

        full_content = ''
        if self.transport:
            stream = self.transport.stream(messages, cfg)
        else:
            from .transport import qwen_stream
            stream = qwen_stream(messages, cfg)

        async def _generate():
            nonlocal full_content
            try:
                async for packet in stream:
                    if packet.get('done'):
                        break
                    text = packet.get('text', '')
                    if text:
                        full_content += text
                        yield event('content', {'text': text})
                # Save to DB and file
                self.store.save_summary(module_id, round_id, scope, full_content, feedback)
                yield event('complete', {'content': full_content})
            except Exception as e:
                yield event('error', {'message': str(e)})

        return _generate()
```

- [ ] **Step 4: Add save_summary and list_summaries to core.py**

```python
def save_summary(self, module_id, round_id, scope, content, feedback_snapshot):
    with self.lock():
        with self.conn() as c:
            c.execute('''
                INSERT INTO copilot_summaries (module_id, round_id, scope, content, feedback_snapshot, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (module_id, round_id, scope, content,
                  json.dumps(feedback_snapshot, ensure_ascii=False), now()))
        # Also write to Markdown file
        round_num = round_id
        summary_dir = self.module / '课程总结'
        summary_dir.mkdir(parents=True, exist_ok=True)
        summary_file = summary_dir / f'整课总结-第{round_num}轮.md'
        header = f'# 整课总结 · 第{round_num}轮\n\n生成时间：{now()}\n\n---\n\n'
        summary_file.write_text(header + content, encoding='utf-8')
        return True

def list_summaries(self, module_id='renzhi', round_id=1):
    with self.conn() as c:
        rows = c.execute('''
            SELECT id, module_id, round_id, scope, content, feedback_snapshot, created_at
            FROM copilot_summaries WHERE module_id=? AND round_id=?
            ORDER BY created_at DESC
        ''', (module_id, round_id)).fetchall()
    return [dict(r) for r in rows]

def get_summary(self, summary_id):
    with self.conn() as c:
        row = c.execute('SELECT * FROM copilot_summaries WHERE id=?', (summary_id,)).fetchone()
    if not row:
        fail('not_found', '总结不存在。', 404)
    return dict(row)
```

- [ ] **Step 5: Add summary API routes in `api.py`**

```python
class SummaryGeneration(Input):
    scope: Literal['full_course', 'single_lesson'] = 'full_course'

@router.post('/summaries/generate')
def generate_summary(body: SummaryGeneration):
    from .summary import SummaryGenerator
    gen = SummaryGenerator(store)
    return StreamingResponse(gen.generate(body.module, body.round_id if hasattr(body, 'round_id') else 1, body.scope),
                             media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@router.get('/summaries')
def summaries(module: Literal['renzhi'] = 'renzhi'):
    return {'items': store.list_summaries(module)}

@router.get('/summaries/{summary_id}')
def summary(summary_id: int, module: Literal['renzhi'] = 'renzhi'):
    return store.get_summary(summary_id)
```

- [ ] **Step 6: Run test to verify summary**

Run: `cd /Volumes/Xiaohao/学习/知行成长/server && python -m pytest tests/test_summary.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add server/copilot/summary.py server/copilot/core.py server/copilot/api.py server/tests/test_summary.py
git commit -m "feat: add AI course summary generation backend"
```

---

### Task 6: AI Summary Frontend — Summary Page UI

**Files:**
- Create: `server/static/course-summary.js`
- Create: `server/static/course-summary.css`
- Modify: `server/static/index.html` (add summary page + script tags)

**Interfaces:**
- Consumes: `POST /api/copilot/summaries/generate` (SSE), `GET /api/copilot/summaries`
- Produces: summary page with streaming display, save button, "生成进阶课程" button

- [ ] **Step 1: Create summary page UI**

Build a page with:
- Module info header (module name, completed count, feedback count)
- "生成整课总结" button
- Streaming output area (shows AI response as it arrives)
- "保存总结" button (after generation completes)
- "基于总结生成进阶课程" button (after save)
- List of previous summaries

- [ ] **Step 2: Implement SSE streaming display**

Use EventSource or fetch with ReadableStream to display AI output in real-time, matching the existing pattern in `copilot.js`.

- [ ] **Step 3: Add summary page to index.html navigation**

Add "课程总结" tab to the 学习 module navigation.

- [ ] **Step 4: Test summary flow end-to-end**

1. Navigate to 课程总结 page
2. Click "生成整课总结"
3. Verify streaming output appears
4. Click "保存总结"
5. Verify summary appears in the list
6. Verify Markdown file created in 课程总结/ directory

- [ ] **Step 5: Commit**

```bash
git add server/static/course-summary.js server/static/course-summary.css server/static/index.html
git commit -m "feat: add AI course summary page with streaming UI"
```

---

### Task 7: Advanced Course Generation

**Files:**
- Modify: `server/copilot/generation.py` (add advanced generation mode)
- Modify: `server/copilot/summary.py` (add advanced generation trigger method)
- Modify: `server/static/course-summary.js` (add "生成进阶课程" button handler)

**Interfaces:**
- Consumes: existing `Generator` class, `config()`, `messages()`, `teaching_context()`, `list_feedback()`
- Produces: `generate_advanced(module_id, round_id, summary_content)` that creates a new round of lessons as drafts

- [ ] **Step 1: Add advanced generation prompt builder in `generation.py`**

Add a function `advanced_messages(feedback_data, summary_content, next_lesson_no)` that builds the prompt with the advanced instruction block from the spec.

- [ ] **Step 2: Add `generate_advanced` method to `SummaryGenerator`**

This method reads feedback data + summary content, builds an advanced prompt, and generates a draft for the next round of lessons.

- [ ] **Step 3: Add API route for advanced generation**

```python
@router.post('/summaries/{summary_id}/generate-advanced')
def generate_advanced(summary_id: int, body: Input):
    return StreamingResponse(gen.generate_advanced(summary_id),
                             media_type='text/event-stream', ...)
```

- [ ] **Step 4: Add "生成进阶课程" button in summary page**

After a summary is saved, show the button. Clicking it triggers advanced generation, which creates drafts viewable in the existing course management page.

- [ ] **Step 5: Test advanced generation flow**

1. Generate and save a summary
2. Click "基于总结生成进阶课程"
3. Verify draft is created
4. Navigate to 课程管理, verify draft appears
5. Preview, edit, and publish the draft

- [ ] **Step 6: Commit**

```bash
git add server/copilot/generation.py server/copilot/summary.py server/static/course-summary.js
git commit -m "feat: add advanced course generation based on summary and feedback"
```

---

### Task 8: Integration Testing + Polish

**Files:**
- Modify: `server/static/daily-learning.js` (final polish of "待反馈" section)
- Modify: all frontend files for CSS consistency

- [ ] **Step 1: End-to-end test of full flow**

1. Complete a course → submit feedback → archive → verify daily view updated
2. Generate AI summary → verify streaming + save + Markdown file
3. Generate advanced course → verify draft creation
4. Unarchive a course → verify it reappears

- [ ] **Step 2: CSS polish**

Ensure all new UI elements match existing design system (colors, spacing, typography).

- [ ] **Step 3: Error handling**

Verify error states: no AI configured, no completed lessons, network errors during streaming.

- [ ] **Step 4: Commit**

```bash
git add server/static/
git commit -m "fix: polish course completion loop UI and error handling"
```
