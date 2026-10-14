# Capability Spec: 学习完成检测与自动打卡（learning-completion）

## 概述

实现基于阅读行为监控的自动学习完成检测系统，支持三种完成方式（复盘问题、学习总结、快速完成），提交后自动标记课程为已完成并记录学习证据。

---

## 目标

1. **自动化学习追踪**：无需手动点击打卡，系统自动检测阅读完成
2. **多种完成方式**：适应不同场景和用户偏好（深度 / 中等 / 快速）
3. **学习证据保存**：记录复盘内容、总结、阅读时长，支持后续回顾
4. **进度分离展示**：区分"生成进度"和"学习进度"，避免虚假成就感

---

## 核心概念

### 阅读完成检测

**触发条件（满足任一）**
- 滚动到底部（距离页面底部 < 100px）
- 停留时间达到阈值（默认 180 秒 = 3分钟）

**监控指标**
- `scrolledToBottom`: 是否滚动到底部
- `timeSpent`: 已停留时间（秒）
- `scrollDepth`: 滚动深度（0-1）

### 完成方式

| 方式 | 深度 | 负担 | 适用场景 | 保存内容 |
|---|---|---|---|---|
| **复盘问题** | 深 | 高 | 重要课程、想深入理解 | 2-3 个问题的答案 |
| **学习总结** | 中 | 中 | 日常学习、记录启发 | 50-100 字总结 |
| **快速完成** | 浅 | 低 | 时间紧、内容简单 | 仅记录完成状态 |

### 学习记录

每个完成的学习记录包含：
- `lesson_id`: 课程 ID
- `module`: 模块名
- `completion_type`: 完成方式（review / summary / quick）
- `review_answers`: 复盘答案（JSON，仅 review 方式）
- `summary_text`: 学习总结（仅 summary 方式）
- `time_spent_seconds`: 阅读时长（秒）
- `completed_at`: 完成时间
- `idempotency_key`: 幂等键，防止重复提交

---

## 用户故事

### 场景 1：日常学习

**作为** 每日学习者  
**我想要** 阅读完课程内容后，通过写总结来标记完成  
**以便** 记录我的学习启发，同时系统自动追踪我的学习进度

**验收标准**
- 阅读课程后，系统自动检测阅读完成（滚动到底部或停留 3分钟）
- 显示复盘区，默认选中"写学习总结"
- 提交总结后，课程标记为 completed
- 学习进度更新，显示"已学习 1/168"

### 场景 2：深度学习

**作为** 深度学习者  
**我想要** 回答复盘问题来加深理解  
**以便** 确保我真的理解了课程内容，而不仅仅是阅读

**验收标准**
- 选择"回答复盘问题"方式
- 系统展示 2-3 个从课程练习中提取的问题
- 用 1-2 句话回答每个问题
- 提交后，答案被保存，可以后续查看

### 场景 3：快速完成

**作为** 时间紧张的学习者  
**我想要** 一键确认已完成学习  
**以便** 快速标记进度，不花费时间写内容

**验收标准**
- 选择"快速完成"方式
- 点击确认按钮
- 课程标记为 completed
- 学习进度更新

---

## 接口规范

### 提交复盘

```http
POST /api/copilot/lessons/{lesson_id}/review
Content-Type: application/json

{
    "answers": [
        {
            "question_id": 1,
            "question_text": "本课的核心概念是什么？",
            "answer": "证据的可信度取决于来源的可靠性和证据的充分性..."
        },
        {
            "question_id": 2,
            "question_text": "你能举一个生活中的例子吗？",
            "answer": "比如看到一则新闻报道..."
        }
    ],
    "time_spent_seconds": 240,
    "idempotency_key": "unique-key-123"
}
```

**响应**
```json
{
    "success": true,
    "learning_state": "completed",
    "completed_at": "2026-10-14T10:30:00+08:00",
    "review_id": 123,
    "message": "已提交复盘，标记为学习完成"
}
```

### 提交总结

```http
POST /api/copilot/lessons/{lesson_id}/summary
Content-Type: application/json

{
    "summary": "今天我学到了证据的可信度判断方法。我原来认为只要有人说的就是真的，现在我明白了需要看来源和证据...",
    "time_spent_seconds": 180,
    "idempotency_key": "unique-key-456"
}
```

**响应**
```json
{
    "success": true,
    "learning_state": "completed",
    "completed_at": "2026-10-14T10:35:00+08:00",
    "summary_id": 124,
    "message": "已提交总结，标记为学习完成"
}
```

### 快速完成

```http
POST /api/copilot/lessons/{lesson_id}/complete
Content-Type: application/json

{
    "time_spent_seconds": 200,
    "idempotency_key": "unique-key-789"
}
```

**响应**
```json
{
    "success": true,
    "learning_state": "completed",
    "completed_at": "2026-10-14T10:40:00+08:00",
    "message": "已标记为学习完成"
}
```

### 查询学习记录

```http
GET /api/copilot/lessons/{lesson_id}/learning-record
```

**响应**
```json
{
    "lesson_id": 2,
    "module": "每日认知通识",
    "completion_type": "summary",
    "summary_text": "今天我学到了...",
    "time_spent_seconds": 180,
    "completed_at": "2026-10-14T10:35:00+08:00"
}
```

### 查询学习历史

```http
GET /api/copilot/learning-history?page=1&page_size=20
```

**响应**
```json
{
    "total": 15,
    "page": 1,
    "page_size": 20,
    "records": [
        {
            "lesson_id": 2,
            "topic": "什么样的证据更可信",
            "completion_type": "summary",
            "completed_at": "2026-10-14T10:35:00+08:00",
            "time_spent_seconds": 180
        },
        {
            "lesson_id": 1,
            "topic": "区分事实、解释与判断",
            "completion_type": "review",
            "completed_at": "2026-10-13T09:20:00+08:00",
            "time_spent_seconds": 240
        }
    ]
}
```

---

## 数据模型

```sql
CREATE TABLE copilot_learning_records (
    id INTEGER PRIMARY KEY,
    lesson_id INTEGER NOT NULL,
    module TEXT NOT NULL,
    
    -- 完成方式
    completion_type TEXT NOT NULL CHECK (completion_type IN ('review', 'summary', 'quick')),
    review_answers TEXT,            -- JSON array, only for review type
    summary_text TEXT,              -- text, only for summary type
    
    -- 阅读数据
    time_spent_seconds INTEGER,     -- reading time in seconds
    scroll_depth REAL,              -- scroll depth 0-1
    
    -- 元数据
    completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    idempotency_key TEXT UNIQUE,
    
    -- 约束
    UNIQUE(module, lesson_id)
);

CREATE INDEX idx_learning_completed ON copilot_learning_records(completed_at);
CREATE INDEX idx_learning_type ON copilot_learning_records(completion_type);
```

---

## 前端实现

### 阅读监控

```javascript
class ReadingTracker {
    constructor(lessonId) {
        this.lessonId = lessonId;
        this.scrolledToBottom = false;
        this.timeSpent = 0;
        this.threshold = 180;  // 3 minutes
        this.timer = null;
        this.completed = false;
    }
    
    start() {
        this.bindScrollListener();
        this.startTimer();
    }
    
    bindScrollListener() {
        window.addEventListener('scroll', () => {
            const scrolled = (window.scrollY + window.innerHeight) >= 
                           document.body.scrollHeight - 100;
            if (scrolled && !this.scrolledToBottom) {
                this.scrolledToBottom = true;
                this.checkCompletion();
            }
        });
    }
    
    startTimer() {
        this.timer = setInterval(() => {
            if (!this.completed) {
                this.timeSpent++;
                this.updateUI();
                this.checkCompletion();
            }
        }, 1000);
    }
    
    checkCompletion() {
        if (this.scrolledToBottom || this.timeSpent >= this.threshold) {
            this.showReviewSection();
            this.completed = true;
            this.stopTimer();
        }
    }
    
    showReviewSection() {
        const section = document.getElementById('review-section');
        section.classList.remove('hidden');
        section.scrollIntoView({ behavior: 'smooth' });
    }
    
    updateUI() {
        const minutes = Math.floor(this.timeSpent / 60);
        const seconds = this.timeSpent % 60;
        document.getElementById('time-spent').textContent = 
            `${minutes}:${seconds.toString().padStart(2, '0')}`;
        
        const progress = Math.min(this.timeSpent / this.threshold * 100, 100);
        document.getElementById('progress-bar').style.width = `${progress}%`;
    }
    
    stopTimer() {
        if (this.timer) {
            clearInterval(this.timer);
        }
    }
}
```

### 提交复盘

```javascript
async function submitReview(lessonId) {
    const answers = [];
    const questions = document.querySelectorAll('.question');
    
    questions.forEach((q, index) => {
        const textarea = q.querySelector('textarea');
        answers.push({
            question_id: index + 1,
            question_text: q.querySelector('p').textContent,
            answer: textarea.value
        });
    });
    
    try {
        const response = await fetch(`/api/copilot/lessons/${lessonId}/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                answers: answers,
                time_spent_seconds: readingTracker.timeSpent,
                idempotency_key: generateIdempotencyKey()
            })
        });
        
        const result = await response.json();
        if (result.success) {
            showSuccess('✅ 已提交复盘，标记为学习完成！');
            refreshProgress();
            hideReviewSection();
        }
    } catch (error) {
        showError('提交失败：' + error.message);
    }
}
```

---

## 错误处理

### 错误码

| 错误 | 描述 | 处理 |
|---|---|---|
| `lesson_not_found` | 课程不存在 | 返回 404 |
| `already_completed` | 课程已完成 | 返回 200，标记为重复 |
| `invalid_idempotency_key` | 幂等键冲突 | 返回 409 |
| `missing_answers` | 复盘答案不完整 | 返回 400 |
| `summary_too_short` | 总结太短（< 10字） | 返回 400 |

### 前端错误提示

```javascript
function showError(message) {
    const toast = document.createElement('div');
    toast.className = 'fixed top-4 right-4 bg-red-500 text-white px-6 py-3 rounded shadow';
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => toast.remove(), 3000);
}
```

---

## 配置选项

允许用户自定义：

```javascript
const completionConfig = {
    // 阅读完成条件
    reading: {
        requireScrollToBottom: true,
        requireMinTime: 180,
        enableQuickSkip: false
    },
    
    // 默认完成方式
    defaultMode: 'summary',  // review | summary | quick
    
    // 复盘问题
    reviewQuestions: {
        count: 2,
        source: 'auto'  // auto: 从课程练习提取
    },
    
    // 总结要求
    summary: {
        minLength: 10,
        maxLength: 500
    }
};
```

---

## 验收标准

### 功能验收

- [ ] 阅读课程后，系统能自动检测阅读完成
- [ ] 满足条件后显示复盘区
- [ ] 三种完成方式均能正常工作
- [ ] 提交后课程标记为 completed
- [ ] 学习进度正确更新
- [ ] 可以查看历史复盘记录和总结
- [ ] 幂等性检查正常工作

### 性能验收

- [ ] 阅读监控不影响页面性能
- [ ] 提交响应时间 < 1秒
- [ ] 学习历史查询响应时间 < 500ms

### 用户体验验收

- [ ] 阅读进度条流畅更新
- [ ] 复盘区显示平滑（scrollIntoView）
- [ ] 错误提示清晰明确
- [ ] 成功提示友好

---

## 后续扩展

### 二期功能

1. **复盘质量分析**：AI 分析复盘答案的质量
2. **学习报告**：基于学习记录生成周报/月报
3. **间隔复习**：基于艾宾浩斯遗忘曲线提醒复习
4. **学习小组**：分享复盘内容，互相学习

---

## 参考资料

- [艾宾浩斯遗忘曲线](https://en.wikipedia.org/wiki/Forgetting_curve)
- [间隔重复](https://en.wikipedia.org/wiki/Spaced_repetition)
- [主动回忆](https://en.wikipedia.org/wiki/Testing_effect)

---

*最后更新：2026-10-13*
