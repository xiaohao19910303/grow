# 课程完成闭环设计：反馈、AI总结、进阶生成与归档

**日期：** 2026-10-19
**作者：** xiaohaohao002
**状态：** 待审批

---

## 1. 意图与为什么

### 1.1 背景

当前"认知与通识学习"模块的6课已全部学完，但系统停留在"待学习0课 · 累计已完成6课"的静态展示。学完课程后：

- **没有反馈机制**：学完就学完了，没有记录"学得怎么样"
- **没有AI总结**：没有利用AI对整门课进行复盘总结
- **没有进阶引导**：没有基于已学内容生成进阶课程的能力
- **归档不清晰**：已完成课程仍混在"今日"视图中，没有独立的归档区

### 1.2 目标

构建**课程完成闭环**：学完 → 反馈 → AI总结 → 进阶生成 → 归档，让学习形成完整的循环。

### 1.3 设计原则

- **人在环中**：所有AI生成内容都是草稿，需人工确认后发布（延续现有设计原则）
- **手动触发**：所有操作由用户主动触发，系统不自动推送
- **反馈驱动**：AI总结和进阶生成都参考用户的课程反馈数据
- **归档可查**：归档不是删除，是整理，随时可以回看

---

## 2. 目标、非目标、反目标

### 2.1 目标（Goals）

- [x] 课程反馈能力：结构化的轻量标注 + 开放式自由记录
- [x] AI整课总结：基于课程内容和反馈数据，生成整门课的复盘总结
- [x] 进阶课程生成：基于已学课程的反馈，AI生成进阶/新课程草稿
- [x] 课程归档：已完成课程从"今日"视图移除，进入独立归档区

### 2.2 非目标（Non-Goals）

- 不自动推送课程内容（用户自己决定何时触发）
- 不做课程难度自适应（难度由AI生成时根据反馈动态调整，不是系统自动调参）
- 不做多用户支持（单用户本地应用）

### 2.3 反目标（Anti-Goals）

- **反馈不是考试**：不做答题评测，不做正确率统计
- **AI总结不是重写**：不是把课程内容换个说法再说一遍，而是提炼、串联、反思
- **归档不是隐藏**：归档课程仍然可见、可查、可复习，只是不占"今日"注意力

---

## 3. 约束

### 3.1 技术约束

- 后端：Python 3.13 + FastAPI + SQLite（现有架构）
- 前端：原生 HTML/CSS/JS（无框架）
- AI：OpenAI 兼容协议（现有 `transport.py`），默认 Qwen
- 单用户本地部署，不依赖云服务

### 3.2 设计约束

- 复用现有的 `copilot_learning_records` 表结构
- 复用现有的 AI 生成管道（`generation.py` + `transport.py`）
- 复用现有的 Markdown 文件存储模式
- 遵循现有的"草稿→确认→发布"流程

---

## 4. 功能设计

### 4.1 课程反馈

#### 4.1.1 触发时机

用户在"今日"视图或"学习"模块的课程卡片上，点击"完成反馈"按钮（仅对已完成的课程显示）。

#### 4.1.2 反馈表单

**第一层：快速标注（3秒完成）**

| 字段 | 类型 | 选项 |
|------|------|------|
| 掌握程度 | 单选 | 😎 完全掌握 / 🙂 基本懂了 / 😐 一知半解 / 😟 没学明白 |
| 收获评价 | 单选 | ⭐⭐⭐ 很有收获 / ⭐⭐ 还行 / ⭐ 一般 / 没收获 |
| 学习感受 | 多选标签 | 太抽象了 / 例子很好 / 想多练练 / 节奏太快 / 可以复习再看 / 概念很清晰 / 需要更多案例 / 其他（可输入） |

**第二层：自由记录（可选）**

| 字段 | 类型 | 说明 |
|------|------|------|
| 核心收获 | 文本框 | "这节课我学到了什么？哪些观点改变了我的想法？" |
| 疑问/困惑 | 文本框 | "哪个点还没搞清？想深入探索什么？" |
| 后续方向 | 文本框 | "接下来想往哪个方向深入？" |

#### 4.1.3 数据存储

新增数据库表 `copilot_feedback`：

```sql
CREATE TABLE copilot_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id TEXT NOT NULL DEFAULT 'renzhi',
    round_id INTEGER NOT NULL DEFAULT 1,
    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 168),
    mastery_level TEXT NOT NULL CHECK(mastery_level IN ('fully_understood', 'basically_understood', 'partially_understood', 'not_understood')),
    value_rating INTEGER NOT NULL CHECK(value_rating BETWEEN 0 AND 3),
    feeling_tags TEXT,  -- JSON array of strings
    key_learnings TEXT,  -- free text
    questions TEXT,      -- free text
    next_direction TEXT, -- free text
    created_at TEXT NOT NULL,
    UNIQUE(module_id, round_id, lesson_no)
);
```

#### 4.1.4 API

```
POST /api/copilot/lessons/{number}/feedback
  body: { mastery_level, value_rating, feeling_tags, key_learnings, questions, next_direction }

GET /api/copilot/lessons/{number}/feedback
  response: { mastery_level, value_rating, feeling_tags, key_learnings, questions, next_direction, created_at }
```

---

### 4.2 AI 整课总结

#### 4.2.1 触发时机

用户在"学习"模块的课程管理页面，点击"AI整课总结"按钮。前提条件：
- 该模块（如"认知与通识学习"）至少有1课已完成
- 已配置AI API（设置页面已保存API Key）

#### 4.2.2 总结范围

默认总结**整门课程**（当前模块所有已完成的课），不是单课。

#### 4.2.3 AI Prompt 设计

```
你是一个个人学习助手。请基于以下信息，生成一份整门课程的复盘总结。

【课程信息】
模块名：{module_name}
已学课数：{completed_count}
课程列表：
{lesson_list_with_topics}

【用户反馈】
{feedback_for_each_lesson}

【要求】
1. 总结这门课的核心知识框架（不是逐课复述，而是提炼脉络）
2. 基于用户的反馈，指出掌握得好的部分和需要加强的部分
3. 串联各课之间的关联（哪些概念是递进的，哪些是并列的）
4. 给出"如果要继续深入学习，建议的方向"（参考用户填写的后续方向）
5. 用中文输出，语气像一个耐心的导师，不要说教

【输出格式】
## 知识脉络
（核心框架）

## 掌握情况
（基于反馈的分析）

## 概念关联
（课与课之间的联系）

## 进阶建议
（后续学习方向）
```

#### 4.2.4 输出处理

- AI生成的总结以**流式**显示（复用现有 `transport.py`）
- 总结内容同时保存到数据库和 Markdown 文件
- 文件路径：`每日认知与通识学习/课程总结/整课总结-第X轮.md`

#### 4.2.5 数据存储

新增数据库表 `copilot_summaries`：

```sql
CREATE TABLE copilot_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id TEXT NOT NULL DEFAULT 'renzhi',
    round_id INTEGER NOT NULL DEFAULT 1,
    scope TEXT NOT NULL DEFAULT 'full_course',  -- full_course | single_lesson
    content TEXT NOT NULL,
    feedback_snapshot TEXT,  -- JSON: 生成时参考的反馈数据快照
    created_at TEXT NOT NULL
);
```

#### 4.2.6 API

```
POST /api/copilot/summaries/generate
  body: { module_id, round_id, scope }
  response: SSE stream of the summary

GET /api/copilot/summaries
  response: { items: [{ id, module_id, round_id, scope, created_at, content }] }

GET /api/copilot/summaries/{id}
  response: { id, module_id, round_id, scope, content, created_at }
```

---

### 4.3 进阶课程生成

#### 4.3.1 触发时机

用户在查看"AI整课总结"后，点击"基于总结生成进阶课程"按钮。

#### 4.3.2 生成逻辑

**输入：**
- 已学课程的反馈数据（哪些课掌握得好，哪些没学明白）
- AI整课总结的内容
- 用户填写的"后续方向"

**处理：**
- 复用现有的 `generation.py` 管道
- 在现有 prompt 基础上，增加"进阶"指令：
  - 如果用户多门课标记"没学明白" → 生成**基础强化课**（更详细的解释、更多案例）
  - 如果用户多门课标记"完全掌握" → 生成**进阶拓展课**（更深的概念、跨领域应用）
  - 如果用户填写了"后续方向" → 围绕该方向生成课程

**输出：**
- 生成草稿（复用现有 `copilot_drafts` 表）
- 用户在课程管理页面预览、编辑、确认发布

#### 4.3.3 进阶 Prompt 扩展

在现有课程生成 prompt 基础上，追加：

```
【进阶指令】
基于上一轮课程的反馈数据，生成进阶课程：
- 用户掌握较好的领域：{well_mastered_topics}
- 用户需要加强的领域：{weak_topics}
- 用户希望深入的方向：{next_directions}

请生成8-12课进阶内容，重点覆盖用户需要加强的领域，
同时延伸到用户感兴趣的新方向。
课程难度可以适当提升，但要确保概念解释足够清晰。
```

---

### 4.4 课程归档

#### 4.4.1 归档逻辑

**归档条件：**
- 课程 `learning_state = 'completed'` 且已有反馈记录

**归档行为：**
- "今日"视图不再展示已归档课程（即使日期匹配）
- 课程移入"归档"视图
- Markdown 文件不删除，只是 UI 层面归档

#### 4.4.2 归档视图

在"学习"模块下新增子页面"课程归档"：

| 展示内容 | 说明 |
|----------|------|
| 课程编号 + 主题 | 基本信息 |
| 完成日期 | 何时完成的 |
| 掌握程度 | 反馈中的掌握程度标签 |
| 反馈摘要 | 核心收获的缩略显示 |
| 操作按钮 | "查看反馈" / "再次学习" / "取消归档" |

#### 4.4.3 取消归档

用户可以随时取消归档，课程重新出现在"今日"视图（如果日期匹配）或"继续学习"区域。

#### 4.4.4 数据存储

在 `copilot_lessons` 表的 `data` JSON 中增加字段，或在 `copilot_learning_records` 中增加 `archived` 字段：

```sql
ALTER TABLE copilot_learning_records ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
ALTER TABLE copilot_learning_records ADD COLUMN archived_at TEXT;
```

#### 4.4.5 API

```
POST /api/copilot/lessons/{number}/archive
  response: { archived: true }

POST /api/copilot/lessons/{number}/unarchive
  response: { archived: false }

GET /api/copilot/lessons/archived
  response: { items: [{ lesson_no, topic, completed_at, mastery_level, archived_at }] }
```

---

## 5. UI 设计

### 5.1 "今日"视图变化

**当前：** 已完成课程显示在"继续学习"区域的折叠列表中

**改后：**
- 已完成且有反馈的课程 → 不显示（已归档）
- 已完成但无反馈的课程 → 显示在"待反馈"区域，提示"完成反馈"
- 未完成课程 → 正常显示在"今日待学习"

### 5.2 "学习"模块变化

新增子页面入口：

```
学习模块导航：
- 我的课程
- 学习打卡
- 课程管理
- 认知阅读
- 学习计划
- 课程归档 ← 新增
- 课程总结 ← 新增
```

### 5.3 课程卡片变化

在"我的课程"和"继续学习"区域的课程卡片上：

**已完成课程卡片新增：**
- 反馈状态标签：`已反馈` / `待反馈`
- "完成反馈"按钮（未反馈时）或"查看反馈"按钮（已反馈时）
- 掌握程度小图标（😎/🙂/😐/😟）

### 5.4 反馈弹窗设计

```
┌─────────────────────────────────────────┐
│  第3课完成反馈                          │
│                                         │
│  掌握程度：                             │
│  [ 完全掌握] [🙂 基本懂了]            │
│  [😐 一知半解] [😟 没学明白]             │
│                                         │
│  收获评价：                             │
│  [⭐⭐⭐ 很有收获] [⭐⭐ 还行]            │
│  [⭐ 一般] [没收获]                     │
│                                         │
│  学习感受（多选）：                      │
│  [太抽象了] [例子很好] [想多练练]        │
│  [节奏太快] [概念很清晰] [+ 其他___]    │
│                                         │
│  核心收获（可选）：                      │
│  ┌─────────────────────────────────┐    │
│  │                                 │    │
│  └─────────────────────────────────┘    │
│                                         │
│  疑问/困惑（可选）：                     │
│  ┌─────────────────────────────────┐    │
│  │                                 │    │
│  └─────────────────────────────────┘    │
│                                         │
│  后续方向（可选）：                      │
│  ┌─────────────────────────────────┐    │
│  │                                 │    │
│  └─────────────────────────────────    │
│                                         │
│        [取消]          [保存反馈]        │
─────────────────────────────────────────┘
```

### 5.5 AI总结页面设计

```
┌─────────────────────────────────────────┐
│  整课总结生成                           │
│                                         │
│  当前模块：认知与通识学习               │
│  已学课程：6课                          │
│  已反馈：4课                            │
│                                         │
│  生成范围：[整门课程 ▼]                │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  AI正在生成总结...              │    │
│  │  ▓▓▓▓▓░░░░ 60%                 │    │
│  │                                 │    │
│  │  ## 知识脉络                    │    │
│  │  这门课围绕"如何独立思考"展开... │    │
│  │                                 │    │
│  ─────────────────────────────────┘    │
│                                         │
│  [保存总结]  [基于总结生成进阶课程]      │
─────────────────────────────────────────┘
```

---

## 6. 数据流

```
用户学完课程
    │
    ▼
标记完成（现有流程：review/summary/quick/manual）
    │
    ▼
─── 触发反馈 ───┐
│  POST /lessons/{n}/feedback  │
│  → copilot_feedback 表       │
└──────────────┘
    │
    ▼
课程进入"待归档"状态
    │
    ▼
┌─── 用户主动触发归档 ───┐
│  POST /lessons/{n}/archive      │
│  → copilot_learning_records.archived = 1  │
│  → "今日"视图不再显示          │
└────────────────────┘
    │
    ▼
┌─── 用户主动触发AI总结 ───┐
│  POST /summaries/generate          │
│  → 读取 copilot_feedback 数据      │
│  → 调用 AI 生成总结                │
│  → 保存到 copilot_summaries 表     │
│  → 写入 Markdown 文件              │
└──────────────────────┘
    │
    ▼
┌─── 用户主动触发进阶生成 ───
│  POST /generations（进阶模式）       │
│  → 基于反馈数据调整 prompt           │
│  → 生成草稿到 copilot_drafts 表      │
│  → 用户确认后发布                    │
└────────────────────────┘
```

---

## 7. 文件变更清单

### 7.1 后端

| 文件 | 变更 |
|------|------|
| `server/copilot/core.py` | 新增 `copilot_feedback` 表初始化、反馈CRUD、归档逻辑 |
| `server/copilot/api.py` | 新增反馈/总结/归档API路由 |
| `server/app.py` | 注册新表结构 |

### 7.2 前端

| 文件 | 变更 |
|------|------|
| `server/static/daily-learning.js` | "今日"视图过滤已归档课程，新增"待反馈"区域 |
| `server/static/copilot.js` | 课程卡片新增反馈按钮、掌握程度标签 |
| `server/static/course-feedback.js` | **新文件**：反馈弹窗UI |
| `server/static/course-summary.js` | **新文件**：AI总结页面UI |
| `server/static/course-archive.js` | **新文件**：归档视图UI |

### 7.3 数据库

| 变更 | 说明 |
|------|------|
| 新增 `copilot_feedback` 表 | 存储课程反馈数据 |
| 新增 `copilot_summaries` 表 | 存储AI生成的课程总结 |
| 修改 `copilot_learning_records` 表 | 新增 `archived` 和 `archived_at` 字段 |

---

## 8. 实施计划

### Phase 1：课程反馈（预计2-3小时）

1. 数据库：创建 `copilot_feedback` 表
2. 后端：实现反馈 CRUD API
3. 前端：实现反馈弹窗 UI
4. 前端：课程卡片集成反馈按钮和状态标签

### Phase 2：课程归档（预计1-2小时）

1. 数据库：修改 `copilot_learning_records` 表
2. 后端：实现归档/取消归档 API
3. 前端："今日"视图过滤已归档课程
4. 前端：新增"课程归档"子页面

### Phase 3：AI整课总结（预计3-4小时）

1. 后端：实现总结生成 API（复用 transport.py）
2. 后端：创建 `copilot_summaries` 表
3. 前端：实现总结页面 UI（流式显示）
4. 前端：新增"课程总结"子页面

### Phase 4：进阶课程生成（预计2-3小时）

1. 后端：扩展 `generation.py` 支持进阶模式
2. 后端：在生成 prompt 中注入反馈数据
3. 前端：在总结页面添加"生成进阶课程"按钮
4. 前端：复用现有草稿预览/发布流程

---

## 9. 风险与注意事项

### 9.1 数据迁移

- 现有 `copilot_learning_records` 表无 `archived` 字段，需要 ALTER TABLE
- SQLite 的 ALTER TABLE 支持有限，可能需要重建表

### 9.2 AI 成本

- 整课总结调用一次 AI，费用可控
- 进阶课程生成调用一次 AI，费用可控
- 用户手动触发，不会产生意外费用

### 9.3 反馈数据质量

- 反馈是用户自愿填写的，可能不完整
- AI 总结需要处理"部分课程无反馈"的情况

### 9.4 归档与复习的平衡

- 归档课程仍可通过"课程归档"页面访问
- "再次学习"按钮可以重新激活课程

---

## 10. 验收标准

- [ ] 用户可以在已完成的课程上提交反馈
- [ ] 反馈数据正确保存到数据库
- [ ] "今日"视图不再显示已归档课程
- [ ] 归档课程在"课程归档"页面可见
- [ ] 用户可以取消归档
- [ ] AI整课总结可以正常生成（流式显示）
- [ ] 总结内容保存到数据库和 Markdown 文件
- [ ] 基于总结可以触发进阶课程生成
- [ ] 进阶课程草稿可以预览、编辑、发布

---

## 11. 后续扩展（不在本次范围）

- 反馈数据统计：可视化展示各模块的掌握程度分布
- 智能推荐：基于反馈自动推荐复习时间（间隔重复）
- 多轮课程关联：第2轮课程自动参考第1轮的反馈数据
- 导出功能：将课程总结导出为 PDF 或 Markdown
