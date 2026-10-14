# 技术设计：在现有仪表盘中增加学习副驾驶

## Context

当前仪表盘使用 FastAPI、SQLite、原生 HTML/CSS/JavaScript，已有模块标识 `renzhi`、数据同步、知识扫描、周月报和导出。课程及资料保存在工作区 Markdown 中，日常生成流程也直接读写这些文件。

已有 `save_state()` 会清空 `TABLES` 中的表再写回前端全量状态。因此课程相关数据必须使用独立的增量接口，不能进入旧同步表列表。现有模块级打卡并不包含课次，不能推断某一课已经学完。

当前规划只明确列出第001–007课主题，后续仅有阶段方向。第一轮共168课；每7课复盘、每28课整合，适时回顾约1、7、30课前内容。

## Goals / Non-Goals

目标：兼容既有内容、区别生成与学习、支持有依据的课程草稿、可靠保存、允许离线使用已有内容。

非目标：另建学习副驾驶应用、全仓重构、其他模块生成、自动爬取来源、自动提高难度、完整版本管理和云同步。本文不执行自动任务变更、依赖安装、真实 API 调用或应用启动。

## Decisions

### 1. 复用部署与模块边界

沿用 `学习仪表盘/start.sh`、现有服务和数据库；新增 `/api/copilot/*` 接口及现有页面中的课程区域。按实现复杂度拆分课程发现、生成、持久化服务，不预设多层空目录。后端仅接受稳定标识 `renzhi`，通过白名单映射目录和展示名；不得把任意客户端模块字符串拼入文件路径。

默认仅本机访问。同源页面不需要开放通配 CORS；若保留局域网手机访问，须显式开启并具备写操作凭证与来源检查，不能把 CORS 当作认证。新增付费生成接口不能在无访问控制的全网卡监听下启用。

沿用虚拟环境，不每次启动安装依赖，不新增并行8756端口服务。新依赖用途及兼容性在实施前核实并获得用户明确同意。CSS、渲染资源需本地可用，不能依赖 CDN 才能浏览已有内容；渲染器输出必须净化，主题等普通文本使用文本节点。

### 2. 内容、状态和数据权威来源

| 数据 | 权威来源 | 同步规则 |
|---|---|---|
| 正式课程正文、参考资料 | 工作区 Markdown | 数据库只保存路径、摘要和哈希；外部编辑后重扫更新索引 |
| 既有学习状态、个人记录 | 学习记录.md | 缺少明确完成证据时保留“待本人记录”；不根据文件存在推断完成 |
| 新的完成/撤销完成操作 | 保存操作成功后的学习记录条目 | 数据库是查询投影；通过受保护的记录更新流程同步，个人记录区不变 |
| 周主题规划 | 模块下新增的课程主题规划.md | 只读导入首周已确定主题；后续由用户编辑或确认后生效 |
| 草稿、生成尝试、操作日志 | 现有 SQLite 的新增表 | 与正式课程区分，不因草稿存在推进生成进度 |
| 旧模块打卡和报告 | 原有表 | 维持现有语义，不转换为课次完成状态 |

不维护含义模糊的 `current_lesson` 真值表。生成数量、完成数量和下一待生成编号分别推导，编号不等于数量。数据库损坏后扫描能重建正式内容与明确写入 Markdown 的学习状态，但不能还原未备份草稿、调用记录或未落盘操作。

### 3. 最小数据模型

以下为逻辑约束，不提供可直接复制的未验证 SQL：

- `copilot_lessons`：`module_id + round_id + lesson_no` 唯一；主题、课程/资料相对路径与哈希、内容完整性状态、学习状态、完成时间、投影版本。第一轮 `round_id=1`，课次限定1–168。
- `copilot_drafts`：草稿ID、课次、版本、正文、资料摘要、来源清单、规划及资料快照哈希、状态和更新时间。状态为 generating / ready / failed / cancelled / published；重新生成创建新尝试，旧草稿不立即丢弃。
- `copilot_generation_attempts`：尝试ID、草稿ID、状态、模型、输入/输出实际 token、费用估算、定价版本、耗时和错误类别。用量未知记录为空，不写成0，不以中文字数除4假装实际 token。
- `copilot_operations`：操作ID、幂等键、请求哈希、课次、预期旧哈希、目标哈希、受控暂存路径、保存阶段、错误和返回结果；用于保存、学习反馈同步及恢复。
- 增量迁移版本记录：迁移前做一致性备份，执行可重复；不得删除旧业务表。课程表不加入原 `TABLES` 清空列表。

使用唯一约束和显式更新，避免 `INSERT OR REPLACE` 重建记录而丢失完成时间等字段。内容哈希仅用于冲突检测，不能证明学习完成或来源可信。

### 4. 课程发现、完整性与课次推进

扫描根目录从服务文件位置或显式配置解析，不依赖启动时工作目录。路径不存在、挂载卷不可访问或权限不足返回 `workspace_unavailable`，禁止初始化成空学习库。

识别现有“日期-第NNN课-主题.md”，兼容历史短文件名但不改名；用模块、轮次、课次归组，不以主题为主键。短文件名没有日期时读正文日期，仍未知则标记待补日期，不能假设是今天或允许绕过同日限制。

完整课程须满足：课次在范围内；正文非空并具备规划要求的教学部分；参考资料非空、可定位；学习记录存在唯一条目且本地链接有效。对历史文件按教学语义映射标题，不强迫已有“参考分析与自查”拆成两个标题。缺资料或索引的课程保留显示并标为待修复，不跳过、不自动重写。

以从001开始的连续完整课次确定下一待生成编号。缺课、同课多文件、日期冲突或正文与文件名课次不符时先返回修复项。完整生成数与连续前缀分别计算。第168课完成生成后返回 `round_complete`，继续保留待学课程，不生成169或自动重置第一轮。

日期统一使用 Asia/Shanghai。当天已存在完整课程时，默认不再提供新课生成；继续显示草稿或待修复状态不视为可跳课。用户另行改变生成频率不属于本次实现。

### 5. 周主题与教学上下文

首周主题从现有规划导入，不修改其顺序。新增的课程主题规划包含轮次、课次、主题、课程类型、学习目标、所需来源及确认状态。下一周尚无确认主题时返回 `plan_required`；一期通过本地编辑与页面确认接入，不隐式让模型自选“未知主题”。

每7课使用复盘结构；每28课使用整合复盘结构，避免同时要求两节课。取最近完整课程的教学摘要与可用回顾课次作为上下文，不截取前200字符假装摘要。未确认学习完成的旧课可以回顾，但不能称为“已掌握”。无个人反馈时维持既定难度。

普通课保留日期/课次、引导问题、解释、完整示范、误区与边界、独立练习、分隔的参考分析、自查和记忆提示；复盘及整合课按相应教学目标检查。600–1000字是指导范围，不以字数代替教学完整性。

### 6. 来源与生成协议

生成前要求有用户或既有工作流已核验的本地资料。保存来源标题、链接、核验说明/日期及支持的主张；仅有一个 URL 不代表已核验。缺资料时返回 `sources_required`，不调用付费模型。正文引用只允许来自本次资料清单；模型新增来源须先核验，不得伪装成已验证。

Prompt 输入限于确认主题、教学要求、课程摘要和选定资料；默认不发送个人笔记和整份学习数据库。生成正文与可本地阅读的资料摘要，事实依据与示例假设分开。API成功不等于内容通过校验。

`POST /api/copilot/generations` 使用请求幂等键并返回 SSE：`started`（草稿ID）、`delta`（正文或资料片段）、`completed`（版本、校验结果、用量）、`failed`、`cancelled`。服务端使用真正流式的 HTTP 客户端接口和异步生成器；前端按事件边界解析，不能假设每个网络块是一条完整事件。只有 `completed` 且校验通过后才允许确认保存。

中途失败通过事件表达，不能在响应开始后改发普通 JSON 错误。中断内容保留为未完成草稿，禁止发布；断开连接取消尚在运行的上游请求，重连通过草稿ID查询状态，不重复发起计费请求。明确取消使用取消接口。

首次字节之前的短暂失败可以有上限地退避重试；已收到内容或结果不确定时不自动重新计费。显式重新生成会创建新的尝试，界面说明可能新增费用；不以改变随机种子作为质量保证。

### 7. 保存、幂等与并发

新课文件名沿用 `YYYY-MM-DD-第NNN课-主题.md`，资料为 `第NNN课-参考资料.md`。日期由服务端在正式发布时按北京时间确定；若草稿跨日，重新检查当前日任务约束并更新日期。主题仅用于受控文件名展示，必须去除路径分隔符等危险字符，最终路径须位于白名单目录，拒绝符号链接越界。

保存请求只接收草稿ID、草稿版本和幂等键，服务端从草稿读取主题和内容。编辑通过草稿更新接口递增版本；正式保存前重新校验主题、来源、完整性和文件状态。

在模块级跨进程锁内执行：

1. 检查幂等记录；同键同请求返回原结果，同键不同请求返回冲突。
2. 重新扫描课次、当日课程、正式文件及学习记录哈希；发现外部修改返回409并保留草稿。检查与锁必须覆盖资料和索引。
3. 将目标正文、资料、保留原个人区的索引更新写入受控暂存区，记录预期旧/新哈希及持久操作阶段。
4. 以单文件原子发布方式逐项落盘，并记录每项进度；新文件不得覆盖已存在文件。数据库事务不能使多个 Markdown 文件同时原子提交，因此中间态必须可恢复。
5. 文件全部就绪后，事务更新课程投影、草稿状态和操作结果，再返回成功。索引按课程身份追加一次，不能重复追加或重写个人区。

恢复时：文件为预期新哈希则视为该步完成；为预期旧哈希且暂存完好才可继续；任一未知哈希转为人工冲突，绝不盲目回滚覆盖。存在未恢复操作的课次不能继续生成或发布。完成状态更新也使用该日志与哈希机制，不能先改数据库再忽略 Markdown 失败。

正式课程的再次生成只产生新草稿，一期不自动替换已发布正文；保留旧课程及用户笔记。旧课程修复以缺失项为单位并需预览确认。

### 8. 与外部每日生成流程共存

启动、打开今日任务及保存前重扫文件；外部写入的完整课程导入为已生成、学习状态按记录读取。保留已有同日不重复、连续课次和个人笔记规则。

强互斥要求自动任务与网页共同使用保存入口或同一模块锁协议。独立扫描加哈希只能发现部分竞争，不能保证未使用锁的外部程序不会在检查后写入。因此在尚未协调时仍可浏览、生成草稿，但正式发布须在用户确认该时段外部写入已暂停后开放；协调方式和结果需有记录，不能凭时间推测任务已结束。待后续授权接入统一保存机制后解除该限制。

本次文档修改不会更改实际自动任务；实施阶段如需调整任务，须明确提出具体变更并在授权范围内执行。

### 9. 学习状态与页面行为

学习状态为 unknown（待本人记录）/ completed；用户可明确完成或撤销，记录时间及来源，撤销不删除课程。没有本人反馈时不自动提高难度或标记掌握。

首页分别返回 `generated_count`、`completed_count`、`total_lessons`、`next_generation_lesson`、`pending_learning_lessons`、`blockers` 和当日课程。缺少日期或发现重复时展示待处理项而非错误的下一课。

首屏以阅读已有课程为主；没有待学课且允许生成时展示生成入口。待学积压不自动停止原有每日生成频率。保存后刷新今日任务及真实历史。编辑使用多行文本区和预览；参考分析可折叠，保留先练习再查看答案的顺序。

一期进度只称“认知与通识模块进度”，不称全局课次进度。内容页提供课程与资料本地链接，外部原文需联网；无Key、断网时仍可使用本地读取和本人学习反馈功能。

### 10. 接口契约

| 接口（前缀 /api/copilot） | 行为 |
|---|---|
| GET /today-task | 返回上述分离的进度、待学课程和阻断原因 |
| POST /scan | 重新扫描并返回导入/冲突/待修复项，不生成新课 |
| GET /lessons；GET /lessons/{id} | 真实历史、内容和资料；支持状态筛选及分页 |
| GET /plan；POST /plan/confirm | 读取本地主题规划；对指定文件哈希和课次确认，外部修改使确认失效 |
| POST /generations | 幂等流式生成；首次失败可在流开启前返回结构化错误 |
| GET /drafts/{id}；PATCH /drafts/{id} | 恢复草稿、带版本编辑；过期版本409 |
| POST /generations/{id}/cancel | 取消调用并保留不完整草稿 |
| POST /publications | 以草稿版本、幂等键可靠发布 |
| PATCH /lessons/{id}/learning-state | 本人明确完成/撤销，带版本和幂等键 |
| POST /lessons/{id}/review | 提交复盘答案，自动标记完成 |
| POST /lessons/{id}/summary | 提交学习总结，自动标记完成 |
| POST /lessons/{id}/complete | 快速完成，自动标记完成 |
| GET /lessons/{id}/learning-record | 查询学习记录（复盘内容、总结、阅读时长） |
| GET /learning-history | 查询所有学习完成记录，支持分页和筛选 |
| GET /operations/{id} | 查询保存或恢复状态，不触发重复写入 |

错误至少区分：workspace_unavailable、plan_required、sources_required、course_incomplete、conflict、generation_failed、save_pending_recovery、round_complete、external_writer_uncoordinated。返回可操作说明，不泄露Key、上游完整请求或个人笔记。只允许已注册模块，客户端不得自由决定正式课程路径或跳过规划课次。

### 11. 备份、恢复和成本

提供显式完整备份与恢复流程，包含一致性 SQLite 快照、正式课程、资料、学习记录、主题规划和校验清单；排除 `.env`。备份时暂停共同写入并检查外部文件是否变化，发现变化则失败重试；恢复前预览差异并备份当前状态，不静默覆盖。原仪表盘JSON导出仍保留，但不能称为课程系统完整备份。

模型返回的实际usage优先，缺失时显示未知或明确标注估算。价格作为带生效时间的配置，不固化未核验报价。区分成功、失败、取消和重试费用；统计首字延迟与总耗时，记录样本规模。未配置当期价格时可以记录token，不输出伪精确费用。不承诺固定月费或生成时长。

## Migration Plan

1. 备份现有数据库及相关Markdown，确认工作区可访问。
2. 增量建表，扫描已有两课及学习记录，不重命名、不重生成、不标记完成。
3. 导入首周主题，展示识别与冲突结果；准备来源及生成配置。
4. 协调外部写入后启用发布；此前保留只读及草稿能力。
5. 回退时关闭新增入口和路由，保留新表与已发布Markdown，不能回退删除用户资料。

## Risks / Trade-offs

- 多文件保存没有跨文件数据库事务：接受可恢复的中间态，通过操作日志和冲突检测避免静默覆盖。
- 外部写入方不遵守锁：必须协调发布时段或统一入口，不能宣称已解决并发。
- 本地资料核验需要人参与：一期优先可信来源和可追溯性，自动检索后续另立变更。
- 不做正式课程版本管理：重新生成只保留草稿，替换既有正文另行设计。
- 第008课以后主题需要补齐：以周规划推进，未确认不计费生成。

## Validation Strategy

按四份 capability spec 场景验收，优先使用临时工作区、既有格式样本和模拟模型响应。覆盖重复保存、中途失败、外部修改、备份恢复和旧同步接口回归。真实API调用和应用启动按实施阶段授权执行，不能把静态检查或模拟结果当成真实模型质量、费用或运行证明。

参考：[HTTPX流式接口](https://www.python-httpx.org/async/#streaming-responses)、[Marked输出安全说明](https://marked.js.org/)、[SQLite冲突处理](https://www.sqlite.org/lang_conflict.html)。

最后更新：2026-10-13。

## 12. 学习完成检测与自动打卡

### 12.1 阅读监控机制

前端监控用户阅读行为，满足以下条件时显示复盘区：

**阅读完成条件（满足任一）**
- 滚动到底部（距离页面底部 < 100px）
- 停留时间达到阈值（默认 180 秒 = 3分钟）

**前端实现**
```javascript
const readingTracker = {
    scrolledToBottom: false,
    timeSpent: 0,
    threshold: 180,  // 秒
    lessonId: null,
    
    startTracking(lessonId) {
        this.lessonId = lessonId;
        this.timeSpent = 0;
        this.startTimer();
        this.bindScrollListener();
    },
    
    startTimer() {
        this.timer = setInterval(() => {
            this.timeSpent++;
            this.checkCompletion();
        }, 1000);
    },
    
    bindScrollListener() {
        window.addEventListener('scroll', () => {
            const scrolled = (window.scrollY + window.innerHeight) >= 
                           document.body.scrollHeight - 100;
            if (scrolled) {
                this.scrolledToBottom = true;
                this.checkCompletion();
            }
        });
    },
    
    checkCompletion() {
        if (this.scrolledToBottom || this.timeSpent >= this.threshold) {
            this.showReviewSection();
            this.stopTracking();
        }
    },
    
    showReviewSection() {
        // 显示复盘区，让用户选择完成方式
        document.getElementById('review-section').classList.remove('hidden');
    },
    
    stopTracking() {
        clearInterval(this.timer);
    }
};
```

### 12.2 三种完成方式

#### 方式 A：回答复盘问题（深度）

从课程练习中提取 2-3 个问题，用户用 1-2 句话回答。

**优点**：确保深度思考，复盘内容可保存回顾  
**缺点**：负担较重

**实现**
```javascript
async function submitReview(lessonId, answers) {
    const response = await fetch(`/api/copilot/lessons/${lessonId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            answers: answers,  // [{question_id, answer}]
            time_spent_seconds: readingTracker.timeSpent,
            idempotency_key: generateIdempotencyKey()
        })
    });
    
    const result = await response.json();
    if (result.success) {
        showSuccess('已完成复盘，标记为学习完成！');
        refreshProgress();
    }
}
```

#### 方式 B：写学习总结（中等）

用户写 50-100 字总结，记录学到的内容和启发。

**优点**：自由度高，可记录个人洞察  
**缺点**：可能写得很简单

**实现**
```javascript
async function submitSummary(lessonId, summary) {
    const response = await fetch(`/api/copilot/lessons/${lessonId}/summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            summary: summary,
            time_spent_seconds: readingTracker.timeSpent,
            idempotency_key: generateIdempotencyKey()
        })
    });
    
    const result = await response.json();
    if (result.success) {
        showSuccess('已提交总结，标记为学习完成！');
        refreshProgress();
    }
}
```

#### 方式 C：快速完成（简单）

一键确认已完成学习，不要求写内容。

**优点**：最省事  
**缺点**：缺少学习证据

**实现**
```javascript
async function quickComplete(lessonId) {
    const response = await fetch(`/api/copilot/lessons/${lessonId}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            time_spent_seconds: readingTracker.timeSpent,
            idempotency_key: generateIdempotencyKey()
        })
    });
    
    const result = await response.json();
    if (result.success) {
        showSuccess('已标记为学习完成！');
        refreshProgress();
    }
}
```

### 12.3 数据模型

```sql
-- 学习记录表（新增）
CREATE TABLE copilot_learning_records (
    id INTEGER PRIMARY KEY,
    lesson_id INTEGER NOT NULL,
    module TEXT NOT NULL,
    
    -- 完成方式
    completion_type TEXT NOT NULL,  -- review | summary | quick
    review_answers TEXT,            -- JSON: 复盘回答
    summary_text TEXT,              -- 学习总结
    
    -- 阅读数据
    time_spent_seconds INTEGER,     -- 阅读时长
    scroll_depth REAL,              -- 滚动深度（0-1）
    
    -- 元数据
    completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    idempotency_key TEXT UNIQUE,
    
    UNIQUE(module, lesson_id)
);

CREATE INDEX idx_learning_completed ON copilot_learning_records(completed_at);
CREATE INDEX idx_learning_type ON copilot_learning_records(completion_type);
```

### 12.4 后端接口实现

#### 提交复盘
```python
@app.post("/api/copilot/lessons/{lesson_id}/review")
async def submit_review(
    lesson_id: int,
    request: ReviewSubmission,
    db: Session = Depends(get_db)
):
    # 幂等检查
    existing = db.query(LearningRecord).filter(
        LearningRecord.idempotency_key == request.idempotency_key
    ).first()
    if existing:
        return {"success": True, "message": "已处理", "duplicate": True}
    
    # 检查课程是否存在
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="课程不存在")
    
    # 保存学习记录
    record = LearningRecord(
        lesson_id=lesson_id,
        module=lesson.module,
        completion_type="review",
        review_answers=json.dumps([a.dict() for a in request.answers]),
        time_spent_seconds=request.time_spent_seconds,
        idempotency_key=request.idempotency_key,
        completed_at=datetime.now()
    )
    db.add(record)
    
    # 更新课程学习状态
    lesson.learning_state = "completed"
    lesson.completed_at = datetime.now()
    
    db.commit()
    
    return {
        "success": True,
        "learning_state": "completed",
        "completed_at": record.completed_at.isoformat(),
        "review_id": record.id
    }
```

#### 提交总结
```python
@app.post("/api/copilot/lessons/{lesson_id}/summary")
async def submit_summary(
    lesson_id: int,
    request: SummarySubmission,
    db: Session = Depends(get_db)
):
    # 类似 submit_review，但 completion_type = "summary"
    # 保存 summary_text 而不是 review_answers
    pass
```

#### 快速完成
```python
@app.post("/api/copilot/lessons/{lesson_id}/complete")
async def quick_complete(
    lesson_id: int,
    request: QuickCompletion,
    db: Session = Depends(get_db)
):
    # 类似 submit_review，但 completion_type = "quick"
    # 不保存复盘内容或总结
    pass
```

### 12.5 前端界面

```html
<!-- 阅读进度条 -->
<div id="reading-progress" class="fixed bottom-0 left-0 right-0 bg-gray-200 h-1">
    <div id="progress-bar" class="bg-blue-500 h-1 transition-all" style="width: 0%"></div>
</div>

<!-- 阅读信息 -->
<div id="reading-info" class="fixed bottom-2 right-2 bg-white rounded shadow px-3 py-1 text-sm">
    ⏱️ <span id="time-spent">0:00</span> / 3:00
</div>

<!-- 复盘区（隐藏，满足条件后显示） -->
<div id="review-section" class="hidden mt-8 bg-white rounded-lg shadow-md p-6">
    <h3 class="text-2xl font-bold mb-4">💭 学习完成确认</h3>
    
    <p class="text-gray-600 mb-4">选择一种方式完成本课学习：</p>
    
    <!-- 选项卡 -->
    <div class="flex gap-2 mb-4">
        <button onclick="showTab('review')" class="tab-btn active">
            回答复盘问题
        </button>
        <button onclick="showTab('summary')" class="tab-btn">
            写学习总结
        </button>
        <button onclick="showTab('quick')" class="tab-btn">
            快速完成
        </button>
    </div>
    
    <!-- 复盘问题 -->
    <div id="tab-review" class="tab-content">
        <div class="question mb-4">
            <p class="font-bold">1. 本课的核心概念是什么？用自己的话解释。</p>
            <textarea rows="2" class="w-full border rounded p-2" 
                      placeholder="用 1-2 句话回答..."></textarea>
        </div>
        <div class="question mb-4">
            <p class="font-bold">2. 你能举一个生活中的例子吗？</p>
            <textarea rows="2" class="w-full border rounded p-2" 
                      placeholder="举例说明..."></textarea>
        </div>
        <button onclick="submitReview()" 
                class="bg-green-500 text-white px-6 py-2 rounded">
            ✅ 提交复盘，标记完成
        </button>
    </div>
    
    <!-- 学习总结 -->
    <div id="tab-summary" class="tab-content hidden">
        <textarea rows="4" class="w-full border rounded p-2 mb-4"
                  placeholder="用 50-100 字总结：今天我学到了什么？有什么启发？"></textarea>
        <button onclick="submitSummary()" 
                class="bg-green-500 text-white px-6 py-2 rounded">
            ✅ 提交总结，标记完成
        </button>
    </div>
    
    <!-- 快速完成 -->
    <div id="tab-quick" class="tab-content hidden">
        <p class="mb-4">确认已认真学习本课内容？</p>
        <button onclick="quickComplete()" 
                class="bg-green-500 text-white px-6 py-2 rounded">
            ✅ 确认完成
        </button>
    </div>
</div>
```

### 12.6 进度展示

在今日任务卡片中分别展示：

```
生成进度：██████░░░░ 2/168 (1.2%)
学习进度：██░░░░░░░░ 1/168 (0.6%)

今日状态：✅ 已完成
完成方式：写学习总结
用时：3分45秒

[查看我的总结] [查看复盘历史]
```

### 12.7 配置选项

允许用户自定义阅读完成条件：

```javascript
const completionSettings = {
    readingComplete: {
        requireScrollToBottom: true,   // 必须滚动到底部
        requireMinTime: 180,           // 最少停留时间（秒）
        enableQuickSkip: false         // 允许快速跳过（不推荐）
    },
    completionMode: {
        default: 'summary',            // 默认方式
        allowReview: true,             // 允许复盘问题
        allowSummary: true,            // 允许学习总结
        allowQuick: true               // 允许快速完成
    }
};
```
