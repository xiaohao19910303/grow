# 日常节奏第一版开发计划

日期：2026-10-21。状态：R01、R02 已实施并通过定向隔离验证；R03及以后尚未实施。适用仓库：`/Users/hao/Documents/grow`。

## 1. 交付目标与范围

将“今日一件事 → 实际行动 → 一句总结 → 每周调整”接入现有 Grow 网页；低状态时可以缩小行动，中断后直接继续。第一版复用原生 HTML/CSS/JavaScript、FastAPI、PostgreSQL、账号 schema 隔离，不引入前端框架、分析 SaaS、后台模型调用或新的推送服务。

先面向行动归属 Grow 的账号灰度，即 `action_link_state.phase=local`。LightTick 接管中的账号不读取本地旧行动表冒充当前数据，也不绕过转发写入；原有功能保持可用，新节奏入口显示暂不可用。连接端支持属于 P2，需要联动服务合同与验收完成后再开放。本轮不改 iOS、Android 或 Zook 代码，不替代已有原生迁移计划。

这是一条可选的行动路径。独立日常记录、未安排的学习、原有课程完成和其他行动仍可直接使用，不以填写计划、总结作为保存原记录或确认学完的前提。首轮指标只评价这条新路径，不能推断全产品学习覆盖率。

第一版激励：服务端确认后的具体进展反馈、每周行动天数、可回看的成果卡。不开成长总分、排行榜、积分商城、付费补签或断更惩罚。

## 2. 当前实现依据

以下是当前工作树的代码核查，不是本轮运行验收。现有文件有未提交修改，实施前需要重新确认差异，不能覆盖其他工作。

本节路径均相对 `/Users/hao/Documents/grow/知行成长/`；后续路径同此约定。

| 已有能力 | 代码依据 | 本轮处理 |
|---|---|---|
| 今日、行动、学习、记录、成长五个导航 | `server/static/index.html`，`GROUPS`、`view-personal` | 保持主导航，增加局部卡片 |
| 内容加入今日/明日、改期、取消 | `server/static/daily-agenda.js`；`server/action_plans.py`，`schedule/mutate` | 今日一件事引用原 day 行动，不复制内容 |
| time/content/check 三种完成模式 | `server/action_plans.py`，`PlanFields/complete_fact/mutate` | 保留各自完成语义 |
| 标准/起步执行、持久进行中记录 | `Mutation.variant`、`minimum_minutes`；`static/action-plans.js`，`start/finish` | 扩展低状态入口，复用执行事实 |
| 执行记录已有可选 note | `action_executions.data.note`、`finish` | 作为行动一句总结的唯一正文，补可后填和下一步 |
| 自由日常记录与 AI 辅助 | `server/reflections/api.py`、`store.py`；`static/reflections.js` | 保留独立入口；不因每次执行自动再创建一条复盘 |
| 按计划复盘及显式 AI 总结 | `server/action_reviews.py`，`Scope.plan_id/context` | 保留；新增无需上级计划的跨行动周成果卡 |
| 旧周报按 habits/checkins 等统计 | `server/app.py`，`build_report` | 与节奏统计分别标注，不沿用旧 active_days/streak |
| PostgreSQL、账号隔离 | `server/db.py`，`connect`；`server/tenancy.py` | 新数据进入同一私有 schema，不能按旧 SQLite 文档开发 |
| LightTick 唯一写入方与转发 | `server/action_link.py` | 新合同未支持时关闭连接端新写入 |
| 独立 PostgreSQL 和真实页面测试入口 | `server/tests/README.md`、`run_isolated_checks.py` | 复用隔离测试，不连接业务库或真实模型 |

特别注意：当前执行 `business_date` 取计划安排日期；不能直接当作实际行动发生日期。`minimum/partial` 不等于原行动达标，`note` 不等于课程完成。历史文档中的 SQLite、单用户、备份能力描述需要按当前代码甄别。

## 3. 页面与用户流程

| 页面/组件 | 用户操作与状态 | 文件 |
|---|---|---|
| 今日顶部「今日一件事」 | 选择已有当日日行动；或先沿用现有表单创建，再选为主任务；输入完成标准、第一步；显示待开始/进行中/已行动待总结/已留总结/休息 | 修改 `server/static/index.html`；新增 `static/daily-rhythm.js`、`daily-rhythm.css`；接入 `daily-agenda.js` |
| 今日「今天轻一点」 | 查看标准/最低版本，确认这次采用的具体步骤；可选休息；不改写原任务完成标准 | `daily-rhythm.js`、`action-plans.js` |
| 执行结束弹窗 | 复用实际分钟确认；可填一句收获或卡点、可选下一步；可以先保存执行，之后补总结 | 修改 `static/action-plans.js`，新增复用型 recap 编辑器到 `daily-rhythm.js` |
| 文章/课程完成之后 | 已关联行动时展示可关闭的总结入口；未关联时保持原流程；来源保存成功但行动同步失败时先核对，不再保存一次来源完成 | 修改 `static/reading.js`、`plans.js`、`daily-learning.js`、`copilot.js`；检查其他完成入口只在适用时接入 |
| 记录 → 执行记录 | 在同一执行记录中查看/补填/修改总结及下一步；自由日常复盘仍在原入口 | 修改 `static/action-plans.js`；不改写 `reflection_entries` |
| 成长 → 周报 | 新增「本周成果」区域：行动日、完整闭环日、标准/低状态分布、具体成果、本人选择的一项调整；支持历史周卡 | 修改 `static/index.html`，新增 `static/weekly-rhythm.js` |
| 设置 → 日常节奏 | 开启/关闭、每周目标天数、周回顾星期、提醒开关/时间；初次可跳过，默认每周3天、提醒关闭 | `index.html`、`daily-rhythm.js` |

### 流程 A：普通一天

1. 首次启用：确认时区与每周目标，提醒默认关闭；跳过不阻碍原功能。
2. 从今日安排选一项主任务，填写可选第一步及完成标准；一次仅有一个当前主任务。
3. 开始：沿用 `ActionPlans.start` 和原内容跳转；服务端已有 running 时回到该执行，不创建第二个。
4. 结束：确认实际投入/来源完成，提供一句总结。总结可跳过，执行先成功保存。
5. 保存总结后展示本人文字和下一步；次日仅提供「沿用下一步」建议，由用户确认并创建/选择当日行动，不自动改期旧任务。

新建行动与选主任务是两次已有/新增写入：第一步成功、第二步失败时明确提示「行动已创建，尚未设为今日一件事」，重试只补选择，不再次创建。第一版不为此重构全部行动创建事务。

### 流程 B：低状态与休息

- time：复用 `variant=minimum` 和起步时长；少于起步时长但确认有实际投入仍能保留事实，不把它标为原目标达标。
- content：保存这次缩小的步骤，可用 minimum variant 开始；保存投入/中断不会把文章或课程标为读完。来源确实完成仍须原入口明确确认。
- check：缩小步骤只作为行动记录，不自动勾选完整待办；增加明确的 partial 保存路径，允许不填写分钟但必须确认「做过这一步」，不能把0分钟转换为时长。
- 休息：不新增执行或有效日。仍有 running 时先结束/保存；当天已有事实保留，休息不隐藏或抵销它们。
- 已经开始的执行固定使用开始时的标准/最低版本快照；改变当前界面选择不能追溯修改旧执行。

### 流程 C：每周回看

1. 周回顾日打开今日或成长时显示站内入口；不启动后台模型、不新增自动任务。
2. 按当地周一至周日汇总当前周，标注「截至当前」；过去周显示完整区间。
3. 展示事实及原文摘录，允许选择最有价值的记录；不自动推断能力提升或阻碍原因。
4. 用户写/选择一项调整并确认周卡；改动采用新 revision，不覆盖旧确认快照。
5. 「下次试这个」由用户选择一个当日/未来行动并确认关联；后续该行动有有效事实时才算已尝试，单纯保存文字不算执行。

## 4. 数据结构与事实口径

### 4.1 复用主数据，不新增第二套任务或复盘正文

- `action_plans`：仍是任务唯一主数据；主任务卡存 `plan_id` 引用。
- `action_executions`：仍是行动与投入事实；`data.note` 为行动一句总结的唯一正文；新增以下可选字段，旧记录采用读取默认值。
- `reflection_entries`：仍是独立生活/学习日常记录，本轮不强制关联、不重复写总结正文、不将普通自由记录算作完成行动。
- `action_reviews/action_reports`：保留按计划的历史复盘与 AI 报告，新周卡不伪造父计划。

执行事实的增量字段合同：

```json
{
  "fact_version": 2,
  "activity_at": "2026-10-21T12:00:00+00:00",
  "activity_date": "2026-10-21",
  "activity_timezone": "Asia/Shanghai",
  "activity_confirmed": true,
  "rhythm_variant": "minimum",
  "minimum_step_snapshot": "读一段，留一个问题",
  "focus_day_id": "focus-uuid",
  "focus_plan_id_snapshot": "action-uuid",
  "focus_selected_at_snapshot": "2026-10-21T00:30:00+00:00",
  "note": "目前还不能区分用户目标和功能需求",
  "next_step": "对照案例各写一条",
  "recap_kind": "blocker",
  "recap_revision": 1,
  "recap_saved_at": "2026-10-21T12:01:00+00:00"
}
```

`activity_at/date` 表示本次行动由用户确认并被服务端记录的时间/日期，不声称精确测量实际学习发生时间。按结束/来源完成/确认小步骤时写入；业务安排日期 `business_date` 不变。跨午夜按确认日期计本轮指标。历史记录无这些字段时不猜日期、不补写试验事件；补填旧 note 也不算新行动。

`activity_confirmed` 由服务端根据合法操作确定：time 有正数实际分钟；content/check 有有效完成确认；或合法的低状态步骤确认。start、浏览、自动计时、保存计划、单独保存总结均不构成事实。撤销 check 完成后，排除被撤销事实；旧 partial/interrupted 不因状态名称自动算进，需满足真实确认条件。

`rhythm_variant` 来自执行/小步骤确认时的不可变快照，不从当前开关反推。原有 `variant/planned_minutes` 继续保留。对同一次事实更新总结仅改变 recap revision，不改变活动日期、投入或完成结论。

主任务关联必须在开始时固定（没有start的明确完成/小步骤确认在确认时固定），并存当时plan与选择时间快照；后续重选主任务不能改变已有事实关联。没有有效关联时这些字段为空。

当前 `with_content_completion` 不返回可用于补总结的执行回执。本轮须增加兼容的 `action_completion_receipts` 返回字段（plan_id、execution_id、activity_date），在来源成功后关联总结；重复来源请求/核对操作返回同一个已确认执行。不能在前端按标题或records第一页猜执行ID。涉及 `server/action_plans.py`、`reading/api.py`、`plans/api.py`、`copilot/api.py` 和固定课程实际保存路由的适配。

### 4.2 新增私有表（建议放 `server/rhythm/schema.py`）

沿用项目 TEXT JSON、revision 和幂等操作表习惯。R02已实现下列五张业务表及独立迁移版本表，并通过隔离库验证；未在业务库执行迁移。JSON业务字段的实际读写仍由R03及后续任务接入。

| 表 | 键与核心字段 | 约束 |
|---|---|---|
| `action_rhythm_preferences` | `id TEXT PK, effective_from DATE, data TEXT, revision INT`；data 含 timezone、weekly_target_days、review_weekday、reminder_enabled、reminder_time | 生效日唯一；首次立即生效；目标天数1–7；后续周目标/时区修改从下周生效，保留历史版本 |
| `action_focus_days` | `id TEXT PK, local_date DATE UNIQUE, data TEXT, revision INT`；data 含 plan_id、timezone、success_criterion、first_step、mode、minimum_step、rest、selected_at | 每账号每天一条；plan 引用校验当日、day 类型、未归档且账号可见；切换任务只更新引用，不删事实 |
| `action_weekly_cards` | `id TEXT PK, week_start DATE UNIQUE, data TEXT, revision INT`；data 含 timezone、target_days_snapshot、source_fact_ids、source_recap_revisions、stats、selected_execution_ids、adjustment_text、adjustment_target_plan_id、confirmed_at、confirmed_snapshots | 周一边界；有历史修订；历史确认快照不被刷新重写；后续事实变化显示可重看 |
| `action_rhythm_events` | `id TEXT PK, dedupe_key TEXT UNIQUE, event_name TEXT, occurred_at TIMESTAMPTZ, data TEXT` | 白名单事件/属性，按现有账号 schema 隔离；不存正文、完整URL、模型输入或密钥 |
| `action_rhythm_enrollments` | `id TEXT PK, experiment_key TEXT UNIQUE, data TEXT`；data 含 enrolled_at、timezone_snapshot、eligible_reason、app_version、day7_survey、day14_survey | 测试账号排除；同一账号同轮只入组一次；入组后退出或不回访仍留在分母 |

新增 migration 版本检测及初始化入口，不能只依赖 `action_plans.connection` 当前的两张旧表存在性判断，否则已有账号不会创建新表。新表不加入旧 `/api/data` 全量覆盖表单。

### 4.3 统计口径

1. **行动日**：当天至少一个有效、未撤销的行动事实；同日只计1天。计划、内容、父级汇总不重复相加。所有行动可计，学习类型另分组。
2. **完整闭环日**：当天行动事实之一属于用户在该事实发生前选定的主任务，且该执行有非空总结。同一天多次执行或重选主任务最多1天；执行中的 `focus_day_id` 固定关联当时选择。
3. **行动事实发生后才选主任务**：保留行动日，但不追补成完整闭环日，避免事后选择制造计划到执行的转化。界面不因此贬低已有成果。
4. **周目标激励**：使用行动日/自定目标天数，标准与最低版本均可贡献；完整闭环日单独展示，不以强制总结换取已有行动认可。
5. **最低版本**：属于执行事实的模式维度；最低版本行动仍不改变原任务是否达标、课程是否学完。
6. **试验日期**：入组后新增行动才进入14天指标；日期按入组 timezone_snapshot 从时间戳计算，入组当日为D1。业务周卡按自然周，试验W1/W2按入组D1–7/D8–14，二者不能混用。
7. **补总结**：对应行动日可在观察窗内转为闭环；首日指标只认D1内形成的闭环，避免未来补填改写首日激活。14天正式结果在每人D14结束时截断。
8. **总结承接单位**：同一plan同一确认日期的投入事实和来源完成事实聚合为一个行动单位，有任一有效执行总结即可。避免先保存投入、再确认读完导致要求写两次总结；UI显示已有总结链接，正文仍只保存在原执行中，不复制。不同日/不同plan分别计算。

不使用现有旧 `checkins/habits/streak` 推算闭环。不把浏览器前台停留等同投入；actual_minutes 继续标注本人确认。

## 5. 接口合同

新增节奏接口挂在 `/api/action-plans/rhythm` 下，复用现有同源检查、账号上下文、action operations 幂等和转发边界；静态子路由需在可能冲突的动态路由前注册。建议由 `server/rhythm/api.py` 注册到现有 router，业务逻辑在 `store.py/service.py/metrics.py`，避免继续堆入单个 action_plans.py。

| 接口 | 输入/返回重点 |
|---|---|
| `GET /rhythm/capabilities` | supported、reason、contract_version；pending/active 接管未支持时不能返回本地试算结果。连接端未部署时由联动状态禁用入口，不依赖404猜能力 |
| `GET /rhythm/today?date=YYYY-MM-DD` | 当前偏好、focus、关联执行、待补总结、周进展；历史日期只读；运行中优先 |
| `POST /rhythm/preferences` | key、expected_revision、weekly_target_days、review_weekday、timezone、reminder_enabled、reminder_time；返回生效日与新revision |
| `POST /rhythm/focus` | key、expected_revision（新建0）、date、plan_id、success_criterion≤500、first_step≤500；首次插入与并发冲突受唯一键保护 |
| `POST /rhythm/focus/{id}/mode` | key、expected_revision、mode=standard/minimum/rest、minimum_step≤500；running 时不改执行快照；休息需先结束running |
| `POST /rhythm/executions/{id}/recap` | key、expected_recap_revision（旧记录0）、note≤2000、next_step≤500、recap_kind=gain/blocker/result；拒绝纯空白；返回执行的总结字段 |
| `POST /rhythm/steps` | key、plan_id、plan_revision、focus_day_id、minimum_step≤500、did_act=true、note/next_step可选；只适用check的最低步骤；事务新增partial事实，不完成原待办、不伪造分钟；已有running时要求先处理 |
| `GET /rhythm/weeks/{week_start}` | 动态事实汇总、已保存卡片、当前事实版本是否变化；读取不写确认、不创建试验事件 |
| `POST /rhythm/weeks/{week_start}/confirm` | key、expected_revision、snapshot_hash、selected_execution_ids≤3、adjustment_text≤500、adjustment_target_plan_id可空；验证选择可见且在区间，保存确认快照与修订 |
| `POST /rhythm/enrollment` | key、experiment_key；服务端校验功能已开启及资格、生成固定观察窗；不接收用户指定账号/schema |
| `POST /rhythm/survey` | key、day=7/14、clarity_score、progress_score（1–5）；只写对应入组记录，允许跳过 |
| `POST /rhythm/events` | ≤20个白名单UI事件，包含客户端event_id；失败不阻碍业务保存，短期有界队列重试 |
| `GET /rhythm/export` | 本账号配置、主任务、总结增量字段、周卡与试验事实JSON/CSV；分析事件独立可选导出，不混入成果正文 |

写接口均由服务端校验来源、状态、版本与幂等。业务结果成功、响应丢失时使用同一请求键恢复；不同内容复用键返回409。执行结束与来源完成成功后总结失败，只显示「行动已保存，总结待补」，不重新结束执行。

总结补写与 `finish` 必须维护同一个 recap_revision 合同。finish 在一次事务中保存 note/next_step 和对应事实；独立 recap 接口仅修改已结束且可见的执行，旧版本冲突不覆盖正文。

提醒第一版仅扩展现有前台提醒，不承诺关网页送达。节奏提醒默认关闭；按账号+本地日原子认领一次，并与既有提醒循环合并去重，不新增第二套轮询。旧任务提醒设置不被开启节奏功能静默修改；同日已有任务通知时节奏提醒让位，不保证旧任务通知总量随本功能自动变为一天一次。

## 6. 埋点与两周验证

### 6.1 事件及触发条件

公共属性：`schema_version=1`、event_id、experiment_key（入组后）、feature_version、source（today/reader/records/weekly/settings）、session_id（随机会话标识）；服务端补 occurred_at、账号上下文。模式/日期/相关ID由服务端核验，不接受前端自报事实当统计依据。

| 事件 | 触发方 | 去重与含义 |
|---|---|---|
| `rhythm_enrolled` | 服务端入组事务 | 每轮一次 |
| `focus_selected` | 服务端主任务保存事务 | 每次成功选择；换任务可多条，主任务转化分母按账号日去重 |
| `execution_started` | 服务端 start 事务 | 每execution一次；不表示已经行动 |
| `activity_confirmed` | 服务端 finish/来源完成/步骤确认事务 | 每execution一次；带plan_id、focus_day_id、mode、completion_mode、activity_date |
| `activity_reversed` | 服务端合法撤销事务 | 引用原事实，统计排除原完成；不能只累计confirmed事件 |
| `recap_saved` | 服务端保存事务 | execution_id+recap_revision唯一；含has_note/has_next_step/kind，不含正文 |
| `minimum_selected` / `rest_selected` | 服务端mode保存事务 | operation key去重；选择本身不计行动 |
| `weekly_card_viewed` | UI可见后上报 | 同会话同周一次；不可由后台刷新触发 |
| `weekly_card_confirmed` | 服务端确认事务 | week_start+revision唯一 |
| `adjustment_linked` | 服务端周卡确认/更新事务 | 关联到明确plan；后续依据事实派生是否尝试，不靠点击上报 |
| `form_finished` | UI上报 | form_kind=focus/recap/weekly、result=save/cancel、active_duration_ms；失焦/隐藏暂停计时，标注为操作负担估计 |
| `rhythm_survey_saved` | 服务端问卷事务 | enrollment+day唯一 |
| `rhythm_reminder_claimed` | 服务端提醒认领事务 | 账号schema+本地日唯一；记录认领，不声称已送达；通知失败也不在同日反复尝试 |

业务成功事件和写入同事务，事务回滚不记成功；客户端事件只是交互辅助，丢失不影响核心指标。不能采集正文、输入过程、用户阅读内容或凭证。原文只经业务接口保存。

### 6.2 每人14天的计算合同

| 指标 | 分子/分母 | 第一轮判断线 |
|---|---|---|
| 首日启动 | D1内完成闭环的账号 / 全部有效入组账号 | ≥60% |
| 总结完成率 | 入组D1–14的有效行动单位中在D14截止前有非空总结的单位 / 同窗有效行动单位；单位为(plan_id, activity_date) | ≥70%；先保存投入再确认来源完成不重复要求总结 |
| W2持续率 | D8–14有≥3个闭环日的账号 / 已完整观察14天的全部有效入组账号 | ≥40%；另报告行动日版，避免把缺总结误作没行动 |
| 周回顾完成率 | 有行动且至少确认一张覆盖观察期周卡的账号 / 有行动且已到一次回顾时点的账号 | ≥50%；未到回顾时点不提前判失败 |
| 调整执行率 | D1–7确认调整且关联行动，D8–14该行动有有效事实的账号 / D1–7确认并关联调整的账号 | ≥50%；另报「有调整但未关联」人数 |
| 主观价值 | D14 clarity/progress分别≥4分人数 / 对应问题答卷人数 | 各≥70%，同时报告答卷率和人数，不把未答卷者当满意 |
| 中断恢复（探索） | 首次连续两天无行动后3天内重新行动人数 / 出现该中断且有完整后续3天观察窗人数 | 不设通过线；最低模式使用者分组，只描述关联 |
| 操作负担（探索） | focus/recap/weekly的前台有效操作时长P50/P90、取消率、保存失败率 | 目标规划≤1分钟、总结≤1分钟、周卡≤5分钟；先看分布和访谈 |

旧讨论中的百分比为待验证假设，不是承诺或统计显著性标准。首轮无对照组，不能据此声称激励导致留存提高。20–30人是招募目标；若只有项目拥有者参与，交付个人14天节奏报告和逐日案例，不包装为多用户留存验证。

阶段看板D7、D14生成本账号汇总；多账号试验采用参与者主动导出的汇总文件，分析脚本按匿名试验编号合并，固定包含零活跃账号。第一版不新增跨租户全库查询接口。输出每项分子、分母、未到观察窗人数、样本不足、数据缺失和模式分组。

## 7. 可执行任务与优先级

每项单独提交，提交前限定文件范围；表内测试文件为拟新增，相关既有用例继续复用。P0、P1均属于本轮试用交付，P2另行推进。任务按可验收单元拆分，不按主观“前后端进度百分比”判断完成。

### P0-A：合同和数据，先得到可信事实

| ID | 开发任务 / 文件 | 依赖 | 完成标准与验证 |
|---|---|---|---|
| R01 | 固定合同、复核当前差异及与 `openspec/changes/action-plans-p0-clarity` 的重叠；新增 `server/rhythm/contracts.py`，记录支持模式与切换边界 | 无 | 不将既有P0草案视为已实施；字段、错误码、日期、事实有效性在隔离fixture可断言 |
| R02 | 新增 `rhythm/schema.py`、`store.py`，增量创建五表、索引、迁移标记；注册到已有账号初始化和新用户初始化 | R01 | 空库/已有账号重复初始化不损坏数据；旧 `/api/data` 保存不清除新表；新增 `tests/test_rhythm_schema.py` |
| R03 | 新增 `rhythm/service.py` 偏好版本与每日主任务读写，复用action操作锁及幂等；新增 `rhythm/api.py` 并注册 | R02 | 每日唯一、多标签页409、异账号/错误日期/非day引用拒绝、先建行动后选失败可恢复；`test_rhythm_focus.py` |
| R04 | 为 finish、complete_fact、start 添加增量日期/模式/主任务快照；补来源完成执行回执；新增check最低步骤确认及撤销处理 | R01、R02 | 三模式保持原完成语义；0分钟不造时长；跨午夜/过去计划/未来拒绝；来源重复确认/核对返回相同回执；`test_rhythm_facts.py`及原action回归 |
| R05 | 添加总结补写接口、note/next_step/kind版本合同；finish和补写共享同一正文与revision | R04 | 总结失败不回滚已完成行动；重试不重复事实；旧执行可补但不算新行动；`test_rhythm_recap.py` |
| R06 | 新增 `rhythm/events.py`，将入组、业务事件纳入同事务，支持白名单UI事件 | R02、R04、R05 | 回滚无成功事件，重复key不增事件，用户正文不进入埋点；`test_rhythm_events.py` |

P0-A演示：通过隔离API完成选任务→minimum执行→保存一句总结，核对只产生一个执行事实；原任务是否达标仍按原规则。

### P0-B：日常闭环与恢复，可以真实试用

| ID | 开发任务 / 文件 | 依赖 | 完成标准与验证 |
|---|---|---|---|
| R07 | 新增 `static/rhythm-client.js`，复用提取后的现有请求幂等/账号草稿机制；不复制第二套未校验transport | R03、R05 | pending按账号+操作隔离，响应丢失同key恢复、冲突保留输入；`tests/test_rhythm_client.cjs`；保留旧client合同 |
| R08 | 新增今日一件事卡及设置；接入已有今日日期视图、选择已有行动/创建后选择 | R03、R07 | 刷新恢复；历史日期只读；创建成功选择失败提示准确；键盘焦点和空/错误态可操作 |
| R09 | 接入低状态/休息、运行中返回、次日自选承接；修改 `daily-agenda.js`、`action-plans.js` | R04、R08 | time/content/check三模式均不伪造完成；休息不删除事实；过去任务不自动滚入；`test_rhythm_flow.cjs` |
| R10 | 将结束弹窗接入一句总结；执行记录支持补填；按已有关联执行ID接通来源完成后的入口 | R05、R07、R08 | 文章、课程计划、固定模块适用入口均可验证；来源成功/行动同步失败时先核对；跳过总结仍保存行动 |
| R11 | 实现 `rhythm/metrics.py` 日/周统一聚合；今日、成长和试验共用同一判定函数 | R03–R06 | 同日多次去重、撤销排除、低状态计入、补总结不新增行动、旧记录不计试验；`test_rhythm_metrics.py` |
| R12 | 开关、capabilities和接管阶段限制；`action_link.py`新增迁移保护 | R02、R08–R11 | pending/active未支持时禁用新入口且不查旧表生成新卡；存在新节奏数据时拒绝当前旧格式接管并解释范围，保留数据；`test_rhythm_link_boundary.py` |

P0-B演示：真实页面完成标准/低状态各一次，刷新与跨页可找回；中断回来能从主任务继续；来源完成不被总结保存改变。

### P1：周卡、反馈和两周验证，完成首版交付

| ID | 开发任务 / 文件 | 依赖 | 完成标准与验证 |
|---|---|---|---|
| R13 | 新增 `rhythm/weekly.py`，跨行动事实汇总、周卡确认快照/历史版本、调整与行动引用 | R05、R11 | 无父计划也能回顾；GET不写确认；多于30条事实不因现有records分页漏算；快照过期409；`test_rhythm_weekly.py` |
| R14 | 新增 `static/weekly-rhythm.js`，接入成长周报与今日回顾入口 | R13、R07 | 当前周截至日期明确；可回看历史；只挑≤3条成果和一项调整；旧周报统计范围分别说明 |
| R15 | 统一即时反馈和每周进展文案，按行动日而非填写次数激励 | R09–R11、R14 | 未保存不庆祝；总结可跳过；minimum有认可但不写达标；同日不重复增加天数；反馈引用实际保存的本人内容 |
| R16 | 将节奏提醒整合进既有remind循环，日级原子认领；不新增轮询/推送 | R03、R12、R15 | 默认关闭、关闭网页无送达承诺、多标签页/设备同日节奏提醒至多一次；已有任务通知时让位；`test_rhythm_reminders.py` |
| R17 | 实现入组、D7/D14轻问卷、个人指标导出及匿名汇总脚本 `server/tools/rhythm_trial_report.py` | R06、R11、R13 | 生成固定D1–14窗；覆盖零活跃、未满14天、缺问卷、低模式分组；脚本只读导出文件；`test_rhythm_trial_report.py` |
| R18 | 完成新数据JSON导出及隔离PostgreSQL备份/恢复演练；更新说明 | R02、R05、R13、R17 | 导出含所有新增个人业务数据和版本；恢复后引用/统计一致；不使用旧SQLite备份入口宣称已覆盖PG；`test_rhythm_export.py` |
| R19 | 集成页面夹具、回归和上线门槛；新增 `tests/serve_rhythm_fixture.py`、`test_rhythm_browser.py`；更新 `tests/README.md`与功能说明 | R08–R18 | 全部关键路径与账号隔离通过，功能开关默认关闭；未验证项明确保留，不写“测试通过”代替证据 |

P1演示：用固定时钟生成两周合成数据，从周卡选择调整并关联下周行动，再验证报告分子/分母；完成后才开始真实14天观察。不能把14天观察期当作开发工期。

### P2：本轮之后

| ID | 任务 | 开放门槛 |
|---|---|---|
| R20 | LightTick/Zook节奏合同、字段透传、快照导入、单一写入方、原生消费者适配 | 独立仓库核查和跨端隔离验收；不得直接发送未知字段或忽略新表后宣称接管完整 |
| R21 | 可选将行动总结关联为独立日常复盘、AI周回顾、语音和成果链接 | 根据试用反馈另定正文归属/发送预览；不先堆加到本轮 |

推荐开发顺序：R01 → R02 → R03/R04 → R05 → R06 → R07–R10 → R11–R12 → R13–R16 → R17–R19。斜线表示接口边界清楚后可由团队分别处理，本轮规划不派发子代理或新聊天。

## 8. 必测路径与上线判定

沿用 `server/tests/README.md` 的专用 PostgreSQL 实例、临时schema、合成账号、GitHub/模型协议夹具和真实HTML/JS。新增测试命令沿用 `run_isolated_checks.py --pattern test_rhythm_*.py` 诊断，最终按现有 `--full` 门槛执行；不为文档规划运行数据库迁移或业务测试。

端到端至少覆盖：

1. 标准time：选主任务→开始→确认实际分钟→一句总结→刷新后同一事实。
2. minimum time/content/check：确认有推进但不误完成原目标/课程；无分钟时不能推算时长。
3. 来源完成：文章、课程计划及适用固定课程已确认→可补总结；未安排的来源保持独立；来源保存成功安排失败可核对。
4. 无行动退出、直接自由记录、休息：不强制补计划/总结，不增加行动日。
5. 网络中断、重复点击、多标签页冲突、账号切换：输入可找回，不串账号、不重复事实。
6. 跨午夜、补做过去安排、周末/周一切换、目标/时区下周生效：安排日期与统计日期各自准确。
7. 同日多个任务、多次执行、撤销check：行动天数去重，父级汇总不重复累计。
8. 周卡跨独立行动、超过30条事实、确认后补总结/撤销事实：新聚合可重算，确认历史不被改写，调整关联可验证。
9. 接管local/pending/active、远端不支持、新数据存在后申请旧接管：不双写、不读取旧快照冒充现状、不丢新数据。
10. 两周报告：零活跃仍在分母，未满窗不算流失，问卷缺失不当满意；测试数据不混入真实试验。

相关旧回归：`test_action_plans.py`、`test_daily_arrangements.py`、`test_action_reviews.py`、`test_action_link.py`、`test_action_plan_client.cjs`、来源完成/学习记录/轻量复盘的适用用例，以及页面导航与加载测试。

上线门槛：上述关键事实/账号/保存路径通过；P0和P1的未完成项为0；功能说明及数据导出可用；未支持的连接端入口确实关闭。灰度只开启具备资格的账号，既有功能不被强制替换。

回退：关闭新入口和提醒，保留已有执行note/新表/周卡/只读查看与导出；不删表、不恢复旧整库覆盖期间新数据，不回退成双写。PG恢复演练只在隔离环境进行，生产恢复另行评估。

## 9. 本轮规划交付检查

- [x] 核对现有导航、行动、日程、总结、独立复盘、旧周报和接管边界。
- [x] 明确新增页面组件、数据字段、接口、事件和两周指标分母。
- [x] 将实现拆成19项本轮任务、2项后续任务，列出依赖、验收与文件位置。
- [x] 区分当前已有实现、拟新增结构、历史文档描述和未运行的验证。
- [x] R01：新增严格请求合同、日期/事实判定与默认关闭边界，并记录与行动P0草案的重叠决议。
- [x] R02：新增五张私有业务表和迁移版本表，接入现有init_db初始化；验证并发、回滚、账号隔离及旧state保存兼容。
- [ ] 实施R03–R19并完成首版隔离验收，随后开始14天真实使用观察。

R01/R02实现合同和范围见 [数据基础交付说明](daily-rhythm-foundation.md)；其余页面、写接口、业务埋点及试验仍按后续任务推进。完整回归与本轮定向验证分别记录，不能把数据基础完成当作整个首版上线。
