# 课程完成闭环系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建课程完成闭环系统，实现学完→反馈→AI总结→进阶生成→归档的完整学习循环

**Architecture:** 基于现有 copilot 模块扩展，新增反馈收集、课程归档、AI整课总结、进阶课程生成四个子系统。复用现有 AI 生成管道（transport.py）、数据库结构和 Markdown 文件存储模式。前端使用原生 HTML/CSS/JS，后端 FastAPI + SQLite。

**Tech Stack:** Python 3.13, FastAPI, SQLite, 原生 HTML/CSS/JS, OpenAI 兼容协议 (Qwen)

**Spec:** docs/superpowers/specs/2026-10-19-course-completion-loop-design.md

## Global Constraints

- Python 版本：3.13+
- 数据库：SQLite（现有架构）
- 前端：原生 HTML/CSS/JS（无框架）
- AI 协议：OpenAI 兼容协议，默认 Qwen
- 单用户本地部署，不依赖云服务
- 复用现有 `copilot_learning_records` 表结构
- 复用现有 AI 生成管道（`transport.py`）
- 遵循"草稿→确认→发布"流程
- 所有 AI 生成内容需人工确认后发布
- 所有操作由用户主动触发

## Review Focus

1. **反馈数据完整性**：部分课程可能没有反馈数据，AI 总结需要优雅处理缺失反馈的情况
   - 测试：Task 3 的 `test_generate_summary_with_partial_feedback()` 验证部分课程无反馈时仍能生成总结

2. **归档状态一致性**：归档课程在"今日"视图不可见，但在归档页面可见，状态切换需原子性
   - 测试：Task 2 的 `test_archive_unarchive_consistency()` 验证归档/取消归档状态正确切换

3. **AI 流式响应中断**：用户在 AI 生成总结过程中刷新页面或网络中断，需能恢复或重新生成
   - 测试：Task 3 的 `test_summary_generation_resilience()` 验证中断后可重新生成

4. **进阶生成与反馈数据关联**：进阶课程生成需正确读取并注入反馈数据到 prompt
   - 测试：Task 4 的 `test_advanced_generation_injects_feedback()` 验证反馈数据正确注入到生成 prompt

5. **数据库迁移兼容性**：SQLite ALTER TABLE 限制，新增字段需处理默认值和 NULL 情况
   - 测试：Task 2 的 `test_database_migration_with_existing_data()` 验证现有数据迁移成功

---

# Phase 1: 课程反馈系统

## Task 1: 反馈数据库表初始化

**Files:**
- Modify: `server/copilot/core.py:1-50` (SCHEMA 定义区域)
- Test: `tests/copilot/test_feedback_schema.py`

**Interfaces:**
- Consumes: 无（初始任务）
- Produces: `copilot_feedback` 表创建完成，可通过 `db.connect()` 访问

- [ ] **Step 1: Write the failing test**

```python
# tests/copilot/test_feedback_schema.py
import pytest
import db

def test_copilot_feedback_table_exists():
    """验证 copilot_feedback 表已创建"""
    with db.connect() as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='copilot_feedback'").fetchone()
        assert row is not None, "copilot_feedback 表不存在"

def test_copilot_feedback_table_schema():
    """验证表结构包含所有必需字段"""
    with db.connect() as conn:
        columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(copilot_feedback)")}
        assert 'id' in columns
        assert 'module_id' in columns
        assert 'round_id' in columns
        assert 'lesson_no' in columns
        assert 'mastery_level' in columns
        assert 'value_rating' in columns
        assert 'feeling_tags' in columns
        assert 'key_learnings' in columns
        assert 'questions' in columns
        assert 'next_direction' in columns
        assert 'created_at' in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/copilot/test_feedback_schema.py -v`
Expected: FAIL - "copilot_feedback 表不存在"

- [ ] **Step 3: Implement table creation in `server/copilot/core.py`**

在 SCHEMA 常量中添加：

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/copilot/test_feedback_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/copilot/test_feedback_schema.py server/copilot/core.py
git commit -m "feat: add copilot_feedback table schema"
```

## Task 2: 反馈 CRUD API

**Files:**
- Create: `server/copilot/feedback.py`
- Modify: `server/app.py` (注册路由)
- Test: `tests/copilot/test_feedback_api.py`

**Interfaces:**
- Consumes: `copilot_feedback` 表（Task 1）
- Produces: 
  - `POST /api/copilot/lessons/{number}/feedback` - 创建/更新反馈
  - `GET /api/copilot/lessons/{number}/feedback` - 获取反馈
  - 函数签名: `save_feedback(module_id: str, round_id: int, lesson_no: int, mastery_level: str, value_rating: int, feeling_tags: list[str], key_learnings: str, questions: str, next_direction: str) -> dict`
  - 函数签名: `get_feedback(module_id: str, round_id: int, lesson_no: int) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/copilot/test_feedback_api.py
import pytest
from fastapi.testclient import TestClient
from app import app
import db

client = TestClient(app)

def test_save_and_get_feedback():
    """测试保存和获取反馈"""
    # 保存反馈
    response = client.post('/api/copilot/lessons/3/feedback', json={
        'module_id': 'renzhi',
        'round_id': 1,
        'mastery_level': 'basically_understood',
        'value_rating': 2,
        'feeling_tags': ['例子很好', '概念很清晰'],
        'key_learnings': '学会了独立思考的方法',
        'questions': '如何应用到实际工作中？',
        'next_direction': '想学习更多案例分析'
    })
    assert response.status_code == 200
    data = response.json()
    assert data['lesson_no'] == 3
    assert data['mastery_level'] == 'basically_understood'
    
    # 获取反馈
    response = client.get('/api/copilot/lessons/3/feedback')
    assert response.status_code == 200
    data = response.json()
    assert data['mastery_level'] == 'basically_understood'
    assert data['value_rating'] == 2
    assert '例子很好' in data['feeling_tags']

def test_update_existing_feedback():
    """测试更新已存在的反馈（UPSERT）"""
    # 第一次保存
    client.post('/api/copilot/lessons/5/feedback', json={
        'module_id': 'renzhi',
        'round_id': 1,
        'mastery_level': 'partially_understood',
        'value_rating': 1,
        'feeling_tags': [],
        'key_learnings': '',
        'questions': '',
        'next_direction': ''
    })
    
    # 更新
    response = client.post('/api/copilot/lessons/5/feedback', json={
        'module_id': 'renzhi',
        'round_id': 1,
        'mastery_level': 'fully_understood',
        'value_rating': 3,
        'feeling_tags': ['太抽象了'],
        'key_learnings': '更新后的收获',
        'questions': '',
        'next_direction': ''
    })
    assert response.status_code == 200
    
    # 验证更新
    response = client.get('/api/copilot/lessons/5/feedback')
    data = response.json()
    assert data['mastery_level'] == 'fully_understood'
    assert data['value_rating'] == 3

def test_get_nonexistent_feedback():
    """测试获取不存在的反馈返回 404"""
    response = client.get('/api/copilot/lessons/999/feedback')
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/copilot/test_feedback_api.py -v`
Expected: FAIL - "404 Not Found" (路由不存在)

- [ ] **Step 3: Implement feedback API in `server/copilot/feedback.py`**

```python
# server/copilot/feedback.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import db
from datetime import datetime

router = APIRouter(prefix='/api/copilot')

class FeedbackInput(BaseModel):
    module_id: str = 'renzhi'
    round_id: int = 1
    mastery_level: str = Field(pattern=r'^(fully_understood|basically_understood|partially_understood|not_understood)$')
    value_rating: int = Field(ge=0, le=3)
    feeling_tags: list[str] = []
    key_learnings: str = ''
    questions: str = ''
    next_direction: str = ''

def save_feedback(module_id: str, round_id: int, lesson_no: int, mastery_level: str, 
                  value_rating: int, feeling_tags: list[str], key_learnings: str, 
                  questions: str, next_direction: str) -> dict:
    import json
    created_at = datetime.utcnow().isoformat()
    feeling_tags_json = json.dumps(feeling_tags, ensure_ascii=False)
    
    with db.connect() as conn:
        # UPSERT: 如果存在则更新，不存在则插入
        existing = conn.execute(
            'SELECT id FROM copilot_feedback WHERE module_id=? AND round_id=? AND lesson_no=?',
            (module_id, round_id, lesson_no)
        ).fetchone()
        
        if existing:
            conn.execute('''UPDATE copilot_feedback 
                           SET mastery_level=?, value_rating=?, feeling_tags=?, 
                               key_learnings=?, questions=?, next_direction=?, created_at=?
                           WHERE id=?''',
                        (mastery_level, value_rating, feeling_tags_json, 
                         key_learnings, questions, next_direction, created_at, existing[0]))
        else:
            conn.execute('''INSERT INTO copilot_feedback 
                           (module_id, round_id, lesson_no, mastery_level, value_rating, 
                            feeling_tags, key_learnings, questions, next_direction, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (module_id, round_id, lesson_no, mastery_level, value_rating,
                         feeling_tags_json, key_learnings, questions, next_direction, created_at))
    
    return {
        'module_id': module_id,
        'round_id': round_id,
        'lesson_no': lesson_no,
        'mastery_level': mastery_level,
        'value_rating': value_rating,
        'feeling_tags': feeling_tags,
        'key_learnings': key_learnings,
        'questions': questions,
        'next_direction': next_direction,
        'created_at': created_at
    }

def get_feedback(module_id: str, round_id: int, lesson_no: int) -> Optional[dict]:
    import json
    with db.connect() as conn:
        row = conn.execute(
            'SELECT * FROM copilot_feedback WHERE module_id=? AND round_id=? AND lesson_no=?',
            (module_id, round_id, lesson_no)
        ).fetchone()
        
        if not row:
            return None
        
        # 将 Row 对象转为 dict
        row_dict = dict(row)
        row_dict['feeling_tags'] = json.loads(row_dict['feeling_tags'] or '[]')
        return row_dict

@router.post('/lessons/{lesson_no}/feedback')
def post_feedback(lesson_no: int, body: FeedbackInput):
    result = save_feedback(
        body.module_id, body.round_id, lesson_no,
        body.mastery_level, body.value_rating, body.feeling_tags,
        body.key_learnings, body.questions, body.next_direction
    )
    return result

@router.get('/lessons/{lesson_no}/feedback')
def get_lesson_feedback(lesson_no: int, module_id: str = 'renzhi', round_id: int = 1):
    result = get_feedback(module_id, round_id, lesson_no)
    if not result:
        raise HTTPException(status_code=404, detail='反馈不存在')
    return result
```

- [ ] **Step 4: Register routes in `server/app.py`**

在 app.py 中添加：

```python
from copilot.feedback import router as feedback_router
app.include_router(feedback_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/copilot/test_feedback_api.py -v`
Expected: PASS (3/3 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/copilot/test_feedback_api.py server/copilot/feedback.py server/app.py
git commit -m "feat: add feedback CRUD API endpoints"
```

## Task 3: 反馈弹窗前端 UI

**Files:**
- Create: `server/static/course-feedback.js`
- Modify: `server/static/copilot.js` (集成反馈按钮)
- Modify: `server/templates/copilot.html` (引入 JS)
- Test: 手动测试（浏览器验证）

**Interfaces:**
- Consumes: `POST /api/copilot/lessons/{number}/feedback` (Task 2)
- Produces: 反馈弹窗组件，可在课程卡片上调用 `showFeedbackDialog(lessonNo)`

- [ ] **Step 1: Create feedback dialog component in `server/static/course-feedback.js`**

实现要点：
- 弹窗使用 `<dialog>` 元素
- 三层结构：快速标注（掌握程度、收获评价、学习感受）+ 自由记录（核心收获、疑问、后续方向）
- 掌握程度使用 emoji 单选按钮：😎 完全掌握 / 🙂 基本懂了 / 😐 一知半解 / 😟 没学明白
- 收获评价使用星星单选：⭐⭐⭐ 很有收获 / ⭐⭐ 还行 / ⭐ 一般 / 没收获
- 学习感受使用多选标签（可自定义输入）
- 保存时调用 API，成功后关闭弹窗并刷新课程卡片状态

关键函数签名：
```javascript
function showFeedbackDialog(lessonNo, existingFeedback = null)
function saveFeedback(lessonNo, formData)
function loadExistingFeedback(lessonNo)
```

- [ ] **Step 2: Integrate feedback button in course cards**

在 `server/static/copilot.js` 的课程卡片渲染函数中：
- 已完成课程显示"完成反馈"按钮（未反馈）或"查看反馈"按钮（已反馈）
- 显示掌握程度小图标（如果有反馈）
- 点击按钮调用 `showFeedbackDialog(lessonNo)`

- [ ] **Step 3: Add CSS styles**

在 `server/static/copilot.css` 中添加弹窗样式：
- 弹窗居中显示，带半透明背景遮罩
- 单选按钮使用自定义样式（隐藏原生 radio，使用 label 包裹）
- 多选标签使用 pill 样式
- 文本框自适应高度

- [ ] **Step 4: Manual testing**

打开浏览器访问 http://127.0.0.1:8756，验证：
1. 已完成课程卡片显示"完成反馈"按钮
2. 点击按钮弹出反馈表单
3. 填写表单并保存，成功提示
4. 刷新页面，按钮变为"查看反馈"
5. 点击"查看反馈"，表单回填已有数据
6. 修改并保存，验证更新成功

- [ ] **Step 5: Commit**

```bash
git add server/static/course-feedback.js server/static/copilot.js server/static/copilot.css server/templates/copilot.html
git commit -m "feat: add feedback dialog UI component"
```

---

# Phase 2: 课程归档系统

## Task 4: 归档数据库字段迁移

**Files:**
- Modify: `server/copilot/core.py` (SCHEMA 定义)
- Test: `tests/copilot/test_archive_schema.py`

**Interfaces:**
- Consumes: `copilot_learning_records` 表（已存在）
- Produces: 表新增 `archived` (INTEGER) 和 `archived_at` (TEXT) 字段

- [ ] **Step 1: Write the failing test**

```python
# tests/copilot/test_archive_schema.py
import db

def test_learning_records_has_archive_fields():
    """验证 copilot_learning_records 表包含归档字段"""
    with db.connect() as conn:
        columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(copilot_learning_records)")}
        assert 'archived' in columns, "缺少 archived 字段"
        assert 'archived_at' in columns, "缺少 archived_at 字段"

def test_archive_fields_default_values():
    """验证归档字段默认值正确"""
    with db.connect() as conn:
        # 插入测试数据
        conn.execute('''INSERT INTO copilot_learning_records 
                       (module_id, round_id, lesson_no, learning_state, completed_at)
                       VALUES ('renzhi', 1, 999, 'completed', '2026-10-20T10:00:00')''')
        
        row = conn.execute('SELECT archived, archived_at FROM copilot_learning_records WHERE lesson_no=999').fetchone()
        assert row['archived'] == 0, "archived 默认值应为 0"
        assert row['archived_at'] is None, "archived_at 默认值应为 NULL"
        
        # 清理
        conn.execute('DELETE FROM copilot_learning_records WHERE lesson_no=999')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/copilot/test_archive_schema.py -v`
Expected: FAIL - "缺少 archived 字段"

- [ ] **Step 3: Implement migration in `server/copilot/core.py`**

由于 SQLite ALTER TABLE 限制，使用条件迁移：

```python
def migrate_learning_records_table(conn):
    """为 copilot_learning_records 表添加归档字段"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(copilot_learning_records)")}
    
    if 'archived' not in columns:
        conn.execute('ALTER TABLE copilot_learning_records ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
    
    if 'archived_at' not in columns:
        conn.execute('ALTER TABLE copilot_learning_records ADD COLUMN archived_at TEXT')
```

在 SCHEMA 初始化后调用此函数。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/copilot/test_archive_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/copilot/test_archive_schema.py server/copilot/core.py
git commit -m "feat: add archive fields to copilot_learning_records"
```

## Task 5: 归档/取消归档 API

**Files:**
- Create: `server/copilot/archive.py`
- Modify: `server/app.py` (注册路由)
- Test: `tests/copilot/test_archive_api.py`

**Interfaces:**
- Consumes: `copilot_learning_records.archived` 字段（Task 4）
- Produces: 
  - `POST /api/copilot/lessons/{number}/archive` - 归档课程
  - `POST /api/copilot/lessons/{number}/unarchive` - 取消归档
  - `GET /api/copilot/lessons/archived` - 获取归档课程列表

- [ ] **Step 1: Write the failing test**

```python
# tests/copilot/test_archive_api.py
from fastapi.testclient import TestClient
from app import app
import db

client = TestClient(app)

def test_archive_and_unarchive_lesson():
    """测试归档和取消归档"""
    # 先完成一课
    client.post('/api/copilot/lessons/10/complete')
    
    # 归档
    response = client.post('/api/copilot/lessons/10/archive')
    assert response.status_code == 200
    assert response.json()['archived'] == True
    
    # 验证归档状态
    with db.connect() as conn:
        row = conn.execute('SELECT archived, archived_at FROM copilot_learning_records WHERE lesson_no=10').fetchone()
        assert row['archived'] == 1
        assert row['archived_at'] is not None
    
    # 取消归档
    response = client.post('/api/copilot/lessons/10/unarchive')
    assert response.status_code == 200
    assert response.json()['archived'] == False
    
    # 验证取消归档
    with db.connect() as conn:
        row = conn.execute('SELECT archived, archived_at FROM copilot_learning_records WHERE lesson_no=10').fetchone()
        assert row['archived'] == 0

def test_get_archived_lessons():
    """测试获取归档课程列表"""
    # 归档两课
    client.post('/api/copilot/lessons/11/complete')
    client.post('/api/copilot/lessons/11/archive')
    client.post('/api/copilot/lessons/12/complete')
    client.post('/api/copilot/lessons/12/archive')
    
    # 获取归档列表
    response = client.get('/api/copilot/lessons/archived')
    assert response.status_code == 200
    data = response.json()
    assert 'items' in data
    assert len(data['items']) >= 2
    
    # 验证返回字段
    item = data['items'][0]
    assert 'lesson_no' in item
    assert 'topic' in item
    assert 'completed_at' in item
    assert 'archived_at' in item
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/copilot/test_archive_api.py -v`
Expected: FAIL - "404 Not Found"

- [ ] **Step 3: Implement archive API in `server/copilot/archive.py`**

```python
# server/copilot/archive.py
from fastapi import APIRouter, HTTPException
from datetime import datetime
import db

router = APIRouter(prefix='/api/copilot')

@router.post('/lessons/{lesson_no}/archive')
def archive_lesson(lesson_no: int, module_id: str = 'renzhi', round_id: int = 1):
    archived_at = datetime.utcnow().isoformat()
    with db.connect() as conn:
        conn.execute('''UPDATE copilot_learning_records 
                       SET archived=1, archived_at=?
                       WHERE module_id=? AND round_id=? AND lesson_no=? AND learning_state='completed' ''',
                    (archived_at, module_id, round_id, lesson_no))
    return {'archived': True, 'archived_at': archived_at}

@router.post('/lessons/{lesson_no}/unarchive')
def unarchive_lesson(lesson_no: int, module_id: str = 'renzhi', round_id: int = 1):
    with db.connect() as conn:
        conn.execute('''UPDATE copilot_learning_records 
                       SET archived=0, archived_at=NULL
                       WHERE module_id=? AND round_id=? AND lesson_no=?''',
                    (module_id, round_id, lesson_no))
    return {'archived': False}

@router.get('/lessons/archived')
def get_archived_lessons(module_id: str = 'renzhi', round_id: int = 1):
    with db.connect() as conn:
        rows = conn.execute('''SELECT lesson_no, topic, completed_at, archived_at
                              FROM copilot_learning_records
                              WHERE module_id=? AND round_id=? AND archived=1 AND learning_state='completed'
                              ORDER BY archived_at DESC''',
                           (module_id, round_id)).fetchall()
        return {'items': [dict(row) for row in rows]}
```

- [ ] **Step 4: Register routes in `server/app.py`**

```python
from copilot.archive import router as archive_router
app.include_router(archive_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/copilot/test_archive_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/copilot/test_archive_api.py server/copilot/archive.py server/app.py
git commit -m "feat: add archive/unarchive API endpoints"
```

## Task 6: "今日"视图过滤已归档课程

**Files:**
- Modify: `server/static/daily-learning.js`
- Test: 手动测试

**Interfaces:**
- Consumes: `GET /api/copilot/lessons` (已存在，需修改返回数据包含 archived 字段)
- Produces: "今日"视图不再显示已归档课程

- [ ] **Step 1: Modify backend to include archived status**

在现有获取课程列表的 API 中，确保返回 `archived` 字段。

- [ ] **Step 2: Filter archived courses in frontend**

在 `server/static/daily-learning.js` 的课程渲染逻辑中：
```javascript
// 过滤已归档课程
const visibleLessons = lessons.filter(lesson => !lesson.archived);
```

- [ ] **Step 3: Manual testing**

验证：
1. 归档课程后，"今日"视图不再显示该课程
2. 取消归档后，课程重新出现（如果日期匹配）

- [ ] **Step 4: Commit**

```bash
git add server/static/daily-learning.js
git commit -m "feat: filter archived courses from Today view"
```

## Task 7: 课程归档页面

**Files:**
- Create: `server/static/course-archive.js`
- Create: `server/templates/archive.html`
- Test: 手动测试

**Interfaces:**
- Consumes: `GET /api/copilot/lessons/archived` (Task 5)
- Produces: 归档课程列表页面，支持查看反馈、再次学习、取消归档

- [ ] **Step 1: Create archive page UI**

实现要点：
- 表格展示归档课程：课程编号、主题、完成日期、掌握程度、反馈摘要
- 操作按钮："查看反馈"、"再次学习"（取消归档）、"取消归档"
- 空状态提示

- [ ] **Step 2: Add navigation entry**

在"学习"模块导航中添加"课程归档"入口。

- [ ] **Step 3: Manual testing**

验证归档页面的完整功能。

- [ ] **Step 4: Commit**

```bash
git add server/static/course-archive.js server/templates/archive.html
git commit -m "feat: add course archive page UI"
```

---

# Phase 3: AI 整课总结

## Task 8: 总结数据库表初始化

**Files:**
- Modify: `server/copilot/core.py` (SCHEMA 定义)
- Test: `tests/copilot/test_summary_schema.py`

**Interfaces:**
- Consumes: 无
- Produces: `copilot_summaries` 表创建完成

- [ ] **Step 1: Write the failing test**

```python
# tests/copilot/test_summary_schema.py
import db

def test_copilot_summaries_table_exists():
    """验证 copilot_summaries 表已创建"""
    with db.connect() as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='copilot_summaries'").fetchone()
        assert row is not None

def test_copilot_summaries_table_schema():
    """验证表结构"""
    with db.connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(copilot_summaries)")}
        assert 'id' in columns
        assert 'module_id' in columns
        assert 'round_id' in columns
        assert 'scope' in columns
        assert 'content' in columns
        assert 'feedback_snapshot' in columns
        assert 'created_at' in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/copilot/test_summary_schema.py -v`
Expected: FAIL

- [ ] **Step 3: Implement table creation**

```sql
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/copilot/test_summary_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/copilot/test_summary_schema.py server/copilot/core.py
git commit -m "feat: add copilot_summaries table schema"
```

## Task 9: AI 总结生成 API

**Files:**
- Create: `server/copilot/summary.py`
- Modify: `server/app.py`
- Test: `tests/copilot/test_summary_api.py`

**Interfaces:**
- Consumes: 
  - `copilot_feedback` 表（Task 1）
  - `copilot_summaries` 表（Task 8）
  - `copilot.transport.qwen_stream()` (已存在)
- Produces: 
  - `POST /api/copilot/summaries/generate` - SSE 流式生成总结
  - `GET /api/copilot/summaries` - 获取总结列表

- [ ] **Step 1: Write the failing test**

```python
# tests/copilot/test_summary_api.py
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_generate_summary_with_feedback():
    """测试基于反馈数据生成总结"""
    # 先添加一些反馈
    client.post('/api/copilot/lessons/1/feedback', json={
        'mastery_level': 'fully_understood',
        'value_rating': 3,
        'feeling_tags': ['例子很好'],
        'key_learnings': '学会了批判性思维'
    })
    
    # 生成总结（SSE 流式响应）
    response = client.post('/api/copilot/summaries/generate', json={
        'module_id': 'renzhi',
        'round_id': 1,
        'scope': 'full_course'
    })
    assert response.status_code == 200
    assert 'text/event-stream' in response.headers['content-type']

def test_generate_summary_with_partial_feedback():
    """测试部分课程无反馈时仍能生成总结"""
    response = client.post('/api/copilot/summaries/generate', json={
        'module_id': 'renzhi',
        'round_id': 1,
        'scope': 'full_course'
    })
    assert response.status_code == 200

def test_get_summaries_list():
    """测试获取总结列表"""
    response = client.get('/api/copilot/summaries')
    assert response.status_code == 200
    data = response.json()
    assert 'items' in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/copilot/test_summary_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement summary generation API**

实现要点：
- 读取模块所有已完成课程的反馈数据
- 构建 prompt（参考设计文档 4.2.3）
- 调用 `qwen_stream()` 生成流式响应
- 保存总结到 `copilot_summaries` 表和 Markdown 文件
- 返回 SSE 流

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/copilot/test_summary_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/copilot/test_summary_api.py server/copilot/summary.py server/app.py
git commit -m "feat: add AI summary generation API"
```

## Task 10: AI 总结前端页面

**Files:**
- Create: `server/static/course-summary.js`
- Create: `server/templates/summary.html`
- Test: 手动测试

**Interfaces:**
- Consumes: `POST /api/copilot/summaries/generate` (Task 9)
- Produces: 总结生成页面，支持流式显示、保存、生成进阶课程

- [ ] **Step 1: Create summary page UI**

实现要点：
- 显示模块信息和已学课程数
- "生成总结"按钮触发 AI 生成
- 流式显示生成内容（逐字显示）
- 生成完成后显示"保存总结"和"基于总结生成进阶课程"按钮

- [ ] **Step 2: Implement SSE streaming display**

使用 EventSource API 接收流式响应并实时更新页面。

- [ ] **Step 3: Manual testing**

验证流式生成和保存功能。

- [ ] **Step 4: Commit**

```bash
git add server/static/course-summary.js server/templates/summary.html
git commit -m "feat: add AI summary page UI"
```

---

# Phase 4: 进阶课程生成

## Task 11: 扩展生成管道支持进阶模式

**Files:**
- Modify: `server/copilot/generation.py`
- Test: `tests/copilot/test_advanced_generation.py`

**Interfaces:**
- Consumes: 
  - `copilot_feedback` 表（Task 1）
  - `copilot_summaries` 表（Task 8）
- Produces: 新增 `generate_advanced_course()` 函数

- [ ] **Step 1: Write the failing test**

```python
# tests/copilot/test_advanced_generation.py
from copilot.generation import generate_advanced_course

def test_advanced_generation_injects_feedback():
    """测试进阶生成正确注入反馈数据"""
    # Mock 反馈数据
    feedback_data = [
        {'lesson_no': 1, 'mastery_level': 'fully_understood', 'next_direction': '深入学习'},
        {'lesson_no': 2, 'mastery_level': 'not_understood', 'questions': '概念不清晰'}
    ]
    
    prompt = generate_advanced_course(feedback_data, summary_content='...')
    assert '深入学习' in prompt or 'not_understood' in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/copilot/test_advanced_generation.py -v`
Expected: FAIL - "function not defined"

- [ ] **Step 3: Implement advanced generation**

在 `generation.py` 中新增函数，参考设计文档 4.3.3 的 prompt 扩展。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/copilot/test_advanced_generation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/copilot/test_advanced_generation.py server/copilot/generation.py
git commit -m "feat: add advanced course generation with feedback injection"
```

## Task 12: 进阶生成前端集成

**Files:**
- Modify: `server/static/course-summary.js`
- Test: 手动测试

**Interfaces:**
- Consumes: 现有草稿生成和预览流程
- Produces: "基于总结生成进阶课程"按钮功能

- [ ] **Step 1: Add generation button**

在总结页面添加"基于总结生成进阶课程"按钮。

- [ ] **Step 2: Wire up generation flow**

点击按钮后：
1. 读取当前总结和反馈数据
2. 调用进阶生成 API
3. 跳转到草稿预览页面

- [ ] **Step 3: Manual testing**

验证完整的进阶生成流程。

- [ ] **Step 4: Commit**

```bash
git add server/static/course-summary.js
git commit -m "feat: integrate advanced course generation in summary page"
```

---

# Final Integration

## Task 13: 端到端集成测试

**Files:**
- Create: `tests/test_course_completion_loop.py`
- Test: 端到端测试

- [ ] **Step 1: Write end-to-end test**

```python
# tests/test_course_completion_loop.py
def test_complete_course_completion_loop():
    """测试完整的课程完成闭环"""
    # 1. 完成课程
    # 2. 提交反馈
    # 3. 归档课程
    # 4. 生成 AI 总结
    # 5. 生成进阶课程
    pass
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Manual acceptance testing**

完整走一遍用户流程，验证所有功能正常。

- [ ] **Step 4: Commit**

```bash
git add tests/test_course_completion_loop.py
git commit -m "test: add end-to-end integration test for course completion loop"
```
