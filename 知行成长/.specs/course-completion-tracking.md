# Spec: 课程完成标记与学习记录

## Context

"知行成长"平台的"今日"页面显示待学习课程，但学完的课程没有明确的完成标记，继续留在"今日"列表中，导致用户无法区分哪些课程已学完、哪些待学习。同时，用户缺少一个专门的地方查看自己的学习历史和复盘记录。

**谁在乎**：
- 个人学习者（用户自己）：需要清晰的学习进度追踪和回顾
- 学习闭环：学习 → 完成标记 → 复盘 → 回顾，形成完整的学习循环

**为什么现在**：
- 当前"今日"页面混杂了已学和未学课程，用户体验混乱
- 学完的课程没有记录，无法回顾自己的学习历程
- 复盘功能缺失，学习效果无法巩固

**如何知道完成**：
- 学完的课程从"今日待学习"列表移除，显示在"学习记录"中
- 可以通过日历视图查看任意日期的学习记录
- 每条记录包含：课程标题、完成时间、学习时长、核心收获、个人思考

## Current State

**验证日期**：2026-10-15

### 现有代码结构

| 文件 | 功能 | 状态 |
|------|------|------|
| `server/static/daily-learning.js` | 今日页面渲染 | ✅ 现有 |
| `server/static/index.html` | 主界面框架 | ✅ 现有 |
| `server/copilot/api.py:155-169` | 课程完成API | ✅ 现有 |
| `server/copilot/core.py:630-654` | 学习历史查询 | ✅ 现有 |
| `server/copilot/core.py:507-643` | 完成记录存储 | ✅ 现有 |

### 现有问题

1. **"今日"页面**：
   - 已完成课程继续显示在列表中
   - 没有明确的完成状态标识
   - 缺少快速完成标记入口

2. **"记录"页面**：
   - 没有学习记录子页面
   - 无法按日期查看学习历史
   - 没有日历视图

3. **完成标记**：
   - API已存在（`/api/copilot/lessons/{number}/learning-state`）
   - 前端调用入口缺失
   - 复盘表单不存在

## Proposed Change

### 架构概览

```
┌─────────────────────────────────────────┐
│  今日页面                                │
│  ┌───────────────────────────────────┐  │
│  │ 待学习课程                         │  │
│  │ • 课程A [开始学习]                 │  │
│  │ • 课程B [开始学习]                 │  │
│  └───────────────────────────────────┘  │
│                                          │
│  ┌───────────────────────────────────┐  │
│  │ 已完成（今日）                      │  │
│  │ • 课程C ✓ 45分钟 [查看记录]        │  │
│  ───────────────────────────────────┘  │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  记录页面                                │
│  ┌───────────────────────────────────┐  │
│  │ 日历视图                           │  │
│  │ [2026年10月]                       │  │
│  │ 一  二  三  四  五  六  日          │  │
│  │     1   2   3   4   5   6          │  │
│  │  7  ●8   9  10  11  12  13         │  │
│  │ 14  15  16  17  18  19  20         │  │
│  │ (● = 有学习记录)                    │  │
│  └───────────────────────────────────┘  │
│                                          │
│  ┌───────────────────────────────────┐  │
│  │ 2026-10-15 学习记录 (3条)          │  │
│  │ ┌─────────────────────────────┐   │  │
│  │ │ 第001课 - 认知的本质         │   │  │
│  │ │ ⏱ 45分钟 · 15:30完成        │   │  │
│  │ │ 核心收获：...                │   │  │
│  │ │ 个人思考：...                │   │  │
│  │ └─────────────────────────────┘   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Implementation Details

#### 1. 今日页面改造 (`server/static/daily-learning.js`)

**改动点**：

```javascript
// 现有逻辑（第66-77行）
const available = module.lessons.filter(lesson => !lesson.date || lesson.date <= selected);
const todayLessons = available.filter(lesson => lesson.date === selected);
const pending = available.filter(lesson => lesson.date !== selected && lesson.learning_state !== 'completed');
const completed = available.filter(lesson => lesson.learning_state === 'completed').length;

// 新增：分离今日已完成课程
const todayCompleted = todayLessons.filter(lesson => lesson.learning_state === 'completed');
const todayPending = todayLessons.filter(lesson => lesson.learning_state !== 'completed');

// 渲染逻辑
section.append(node('h3', module.name + ' · ' + module.duration));
section.append(node('p', `待学习 ${todayPending.length} 课 · 已完成 ${todayCompleted.length} 课`, 'desc'));

// 待学习课程
todayPending.forEach(lesson => lessonRow(section, module, lesson));

// 今日已完成（新增区域）
if (todayCompleted.length) {
  const completedSection = node('details', undefined, 'completed-today');
  completedSection.open = true;
  completedSection.append(node('summary', `今日已完成 · ${todayCompleted.length} 课`));
  todayCompleted.forEach(lesson => completedLessonRow(completedSection, module, lesson));
  section.append(completedSection);
}
```

**新增函数**：

```javascript
function completedLessonRow(parent, module, lesson) {
  const row = node('div', undefined, 'todo-row lesson-row completed');
  const text = node('div'); text.style.flex = '1';
  text.append(node('strong', lesson.topic, 'lesson-title'));
  text.append(node('p', `✓ 已完成 · ${lesson.completed_at || '未知时间'}`, 'desc'));
  row.append(text);
  
  // 快速标记按钮（如果未标记）
  if (!lesson.completed_at) {
    button(row, '标记完成', () => markComplete(module, lesson));
  }
  // 查看记录按钮
  button(row, '查看记录', () => viewLearningRecord(module, lesson));
  parent.append(row);
}

async function markComplete(module, lesson) {
  // 调用完成API
  await fetch('/api/copilot/lessons/' + lesson.lesson_no + '/complete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Copilot-Request': '1' },
    body: JSON.stringify({ time_spent_seconds: 0, version: lesson.version, key: crypto.randomUUID() })
  });
  // 刷新列表
  await window.renderDailyLearning();
  toast('课程已标记完成');
}
```

#### 2. 记录页面 - 学习记录子页面

**新建文件**：`server/static/learning-history.js`

```javascript
/* Learning history with calendar view */
(() => {
  'use strict';
  const root = document.getElementById('view-learning-history');
  let currentMonth = new Date();
  let selectedDate = null;
  
  async function loadHistory(date) {
    const params = new URLSearchParams();
    if (date) params.set('date', date);
    const response = await fetch('/api/copilot/learning-history?' + params);
    if (!response.ok) throw new Error('加载失败');
    return response.json();
  }
  
  function renderCalendar(year, month) {
    // 渲染日历视图
    const calendar = node('div', undefined, 'learning-calendar');
    const header = node('div', undefined, 'calendar-header');
    header.append(node('button', '◀', () => changeMonth(-1)));
    header.append(node('span', `${year}年${month + 1}月`));
    header.append(node('button', '▶', () => changeMonth(1)));
    calendar.append(header);
    
    // 渲染日期格子
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const firstDay = new Date(year, month, 1).getDay();
    
    const grid = node('div', undefined, 'calendar-grid');
    for (let i = 0; i < firstDay; i++) {
      grid.append(node('div', '', 'calendar-cell empty'));
    }
    for (let day = 1; day <= daysInMonth; day++) {
      const date = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const cell = node('div', String(day), 'calendar-cell');
      cell.dataset.date = date;
      cell.onclick = () => selectDate(date);
      grid.append(cell);
    }
    calendar.append(grid);
    root.append(calendar);
  }
  
  async function selectDate(date) {
    selectedDate = date;
    const history = await loadHistory(date);
    renderHistoryList(history.items);
  }
  
  function renderHistoryList(items) {
    const list = root.querySelector('.history-list') || node('div', undefined, 'history-list');
    list.replaceChildren();
    
    if (!items.length) {
      list.append(node('p', '这天没有学习记录。', 'desc'));
      root.append(list);
      return;
    }
    
    items.forEach(record => {
      const card = node('div', undefined, 'history-card');
      card.append(node('h4', `第${String(record.lesson_no).padStart(3, '0')}课`));
      card.append(node('p', `⏱ ${Math.round(record.time_spent_seconds / 60)}分钟 · ${formatTime(record.completed_at)}`));
      
      if (record.summary_text) {
        card.append(node('h5', '核心收获'));
        card.append(node('p', record.summary_text));
      }
      if (record.review_answers) {
        card.append(node('h5', '练习反馈'));
        card.append(node('p', JSON.stringify(record.review_answers)));
      }
      
      list.append(card);
    });
    
    root.append(list);
  }
  
  window.loadLearningHistory = () => {
    root.replaceChildren();
    renderCalendar(currentMonth.getFullYear(), currentMonth.getMonth());
    selectDate(today());
  };
})();
```

#### 3. 后端API扩展 (`server/copilot/api.py`)

**新增端点**：

```python
@router.get('/learning-history/by-date')
def learning_history_by_date(date: str, module: Literal['renzhi'] = 'renzhi'):
    """Get learning history for a specific date."""
    # date format: YYYY-MM-DD
    return store.get_learning_history_by_date(module, date)
```

**core.py新增方法**：

```python
def get_learning_history_by_date(self, module_id, date):
    """Get learning records for a specific date."""
    with self.conn() as c:
        rows = c.execute('''
            SELECT lesson_no, completion_type, review_answers, summary_text,
                   time_spent_seconds, completed_at
            FROM copilot_learning_records
            WHERE module_id = ? AND DATE(completed_at) = ?
            ORDER BY completed_at DESC
        ''', (module_id, date)).fetchall()
    
    items = []
    for row in rows:
        record = dict(row)
        if record['review_answers']:
            record['review_answers'] = json.loads(record['review_answers'])
        items.append(record)
    
    return {'date': date, 'total': len(items), 'items': items}
```

#### 4. 复盘表单组件

**新建文件**：`server/static/completion-form.js`

```javascript
/* Completion form with reflection */
function showCompletionForm(lesson, module) {
  const dialog = document.createElement('dialog');
  dialog.className = 'completion-dialog';
  
  const content = document.createElement('div');
  content.className = 'completion-form';
  
  // 标题
  content.append(document.createElement('h2').textContent = `完成第${lesson.lesson_no}课`);
  
  // 学习时长
  const durationField = document.createElement('div');
  durationField.className = 'form-field';
  durationField.append(document.createElement('label').textContent = '学习时长（分钟）：');
  const durationInput = document.createElement('input');
  durationInput.type = 'number';
  durationInput.min = 1;
  durationInput.value = 30;
  durationField.append(durationInput);
  content.append(durationField);
  
  // 核心收获
  const summaryField = document.createElement('div');
  summaryField.className = 'form-field';
  summaryField.append(document.createElement('label').textContent = '核心收获（必填）：');
  const summaryInput = document.createElement('textarea');
  summaryInput.rows = 4;
  summaryInput.required = true;
  summaryInput.placeholder = '这节课最重要的1-3个观点是什么？';
  summaryField.append(summaryInput);
  content.append(summaryField);
  
  // 个人思考
  const reflectionField = document.createElement('div');
  reflectionField.className = 'form-field';
  reflectionField.append(document.createElement('label').textContent = '个人思考（选填）：');
  const reflectionInput = document.createElement('textarea');
  reflectionInput.rows = 4;
  reflectionInput.placeholder = '如何应用到实际？还有哪些疑问？';
  reflectionField.append(reflectionInput);
  content.append(reflectionField);
  
  // 按钮
  const actions = document.createElement('div');
  actions.className = 'form-actions';
  
  const cancelButton = document.createElement('button');
  cancelButton.textContent = '取消';
  cancelButton.onclick = () => dialog.close();
  actions.append(cancelButton);
  
  const submitButton = document.createElement('button');
  submitButton.textContent = '确认完成';
  submitButton.className = 'btn primary';
  submitButton.onclick = async () => {
    if (!summaryInput.value.trim()) {
      alert('请填写核心收获');
      return;
    }
    
    const data = {
      summary: summaryInput.value.trim(),
      time_spent_seconds: parseInt(durationInput.value) * 60,
      version: lesson.version,
      key: crypto.randomUUID()
    };
    
    try {
      await fetch('/api/copilot/lessons/' + lesson.lesson_no + '/summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Copilot-Request': '1' },
        body: JSON.stringify(data)
      });
      dialog.close();
      toast('课程已完成');
      await window.renderDailyLearning();
    } catch (e) {
      alert('提交失败：' + e.message);
    }
  };
  actions.append(submitButton);
  
  content.append(actions);
  dialog.append(content);
  document.body.append(dialog);
  dialog.showModal();
}

window.showCompletionForm = showCompletionForm;
```

## Acceptance Criteria

1. ✅ "今日"页面显示"待学习"和"今日已完成"两个区域
2. ✅ 已完成课程显示完成时间和学习时长
3. ✅ 课程卡片上有"标记完成"按钮，点击后快速标记
4. ✅ 课程正文底部有"完成并记录"按钮，点击后弹出复盘表单
5. ✅ "记录"标签页新增"学习记录"子页面
6. ✅ 学习记录页面有日历视图，有记录的日期高亮显示
7. ✅ 点击日历日期，显示当天的学习记录列表
8. ✅ 每条记录显示：课程标题、完成时间、学习时长、核心收获、练习反馈
9. ✅ 复盘表单包含：学习时长（必填）、核心收获（必填）、个人思考（选填）
10. ✅ 完成标记后，课程从"待学习"移到"已完成"区域

## Testing Plan

| Layer       | What                                          | Count |
|-------------|-----------------------------------------------|-------|
| Unit        | `completedLessonRow()` 渲染已完成课程          | +2    |
| Unit        | `showCompletionForm()` 表单验证               | +2    |
| Integration | 完成API调用 → 数据库记录 → 前端刷新           | +1    |
| Integration | 日历点击 → API查询 → 列表渲染                 | +1    |
| E2E         | 学习课程 → 标记完成 → 查看记录                | +1    |

## Rules for the implementing agent

1. 复用现有的完成API（`/api/copilot/lessons/{number}/complete` 和 `/summary`）
2. 日历组件使用原生实现，不引入第三方库
3. 复盘表单的样式复用现有的 `.plan-field` 和 `.btn` 样式
4. 学习记录数据从 `copilot_learning_records` 表查询
5. "今日已完成"区域默认展开，可以折叠

## Rollback Plan

- 前端：移除新增的JS文件和HTML片段，恢复原有 `daily-learning.js`
- 后端：新增的API端点是附加的，不影响现有功能
- 数据：`copilot_learning_records` 表已存在，无需迁移

## Effort Estimate

- **前端改造**：~4h
  - 今日页面改造：1.5h
  - 学习记录页面：2h
  - 复盘表单：0.5h
- **后端扩展**：~1h
  - 按日期查询API：0.5h
  - 测试：0.5h
- **总时间**：~5h

## Files Reference

| File | Change |
|------|--------|
| `server/static/daily-learning.js` | 改造：分离待学习和已完成区域，添加完成按钮 |
| `server/static/learning-history.js` | 新增：学习记录页面和日历视图 |
| `server/static/completion-form.js` | 新增：复盘表单组件 |
| `server/static/index.html` | 修改：添加学习记录子页面入口 |
| `server/copilot/api.py` | 新增：`/learning-history/by-date` 端点 |
| `server/copilot/core.py` | 新增：`get_learning_history_by_date()` 方法 |
| `server/static/learning-history.css` | 新增：日历和记录样式 |

## Out of Scope

- 学习统计分析（学习时长趋势、完成率等）
- 学习记录导出（PDF、Markdown）
- 多模块学习记录（目前只支持认知与通识模块）
- 学习记录分享功能

## Related

- 课程完成记录功能（已完成）- 提供复盘表单基础
- 认知阅读功能 - 类似的学习记录模式可复用

---

## 依赖图

```
#1 后端API扩展 ──> #2 学习记录页面
                 ──> #3 今日页面改造
#4 复盘表单 ─────> #3 今日页面改造
```

**顺序理由**：
1. 先扩展后端API（1h），为前端提供数据支持
2. 再开发学习记录页面（2h），这是核心新功能
3. 最后改造今日页面（1.5h），复用已完成的组件
4. 复盘表单（0.5h）可以并行开发

---

## 完整清单

### Phase 1: 后端API（1h）
- [ ] `api.py` 添加 `/learning-history/by-date` 端点
- [ ] `core.py` 添加 `get_learning_history_by_date()` 方法
- [ ] 测试API返回格式

### Phase 2: 学习记录页面（2h）
- [ ] 创建 `learning-history.js`
- [ ] 实现日历视图组件
- [ ] 实现日期选择和高亮
- [ ] 实现记录列表渲染
- [ ] 创建 `learning-history.css`
- [ ] 在 `index.html` 添加入口

### Phase 3: 今日页面改造（1.5h）
- [ ] 修改 `daily-learning.js` 分离待学习和已完成
- [ ] 添加 `completedLessonRow()` 函数
- [ ] 添加快速完成按钮
- [ ] 添加查看记录按钮

### Phase 4: 复盘表单（0.5h）
- [ ] 创建 `completion-form.js`
- [ ] 实现表单UI和验证
- [ ] 集成到课程正文底部

### Phase 5: 测试与优化（1h）
- [ ] 端到端测试完整流程
- [ ] 样式调优
- [ ] 边界情况处理（空数据、加载状态等）

---

**Spec版本**：v1.0  
**创建时间**：2026-10-15  
**预计工时**：6小时  
**优先级**：High
