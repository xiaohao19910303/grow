## Context

2026-10-19 的代码基线：`PlanFields` 已有三种 `completion_mode`，`/schedules` 已支持内容安排，operations 已有改期、取消和勾选撤销。前端创建/卡片仍主要使用计时路径；日期、时间、分钟普遍必填；创建草稿共用 `form.new`；历史 `business_date` 使用计划日期。来源完成后的安排同步采用异常提示，尚不能单靠来源的全局已读标志证明某次安排完成。

本变更只定义 P0 日行动闭环。规范要求见 [spec.md](specs/action-plans-p0/spec.md)，逐例验收见 [acceptance.md](acceptance.md)。本文件中的字段表、转换表和错误合同是该规格的组成部分。

## Goals / Non-Goals

**Goals:**

- 一个简单表单即可创建计时、内容或勾选行动，能保存未安排日期的行动。
- 所有入口共享完成规则、执行事实、版本控制和恢复规则。
- 文章/课程安排到日期、执行、改期、取消、完成确认和同步核对形成闭环。
- 统计真实完成项数与确认投入，不让页面停留、计时结束或来源旧状态制造完成。

**Non-Goals:**

- 不重构年/月/周目标模型，不修改自然周期层级，不增加成果指标体系。
- 不做场景模板库、自定义模板、长期重复规则、弹性周次数、AI 自动调整或五个主导航整体改版。
- 不迁移旧 todos 数据；旧待办保留原入口和完成逻辑，不合并计数、不重复展示为新行动。
- 不实现 LightTick 配对、原生通知、生产数据迁移或上线。既有同周重复和复盘功能须兼容，但不扩展。

## Decisions

### D1. 复用日行动，不增加平行任务模型

P0 继续使用 `period=day` 表示单次可执行行动。允许其日期为空以表达未安排；`period=year/month/week` 的日期、层级和人工完成方式保持原合同。`horizon` 对新日行动内部默认为 `short`，已有值保留，不作为快速创建问题。

未安排与过去待调整是视图条件，计时进行中是会话条件，都不增加到行动 `status`。这样避免同一事项在多个状态字段中互相矛盾。

### D2. 字段合同

`null` 表示明确没有设置，省略表示使用创建默认值或在局部操作中保持不变。不能用空字符串、0、今天或 21:00 代替 `null`。新记录写 `schema_version=2`；旧记录保留原始数据，用读适配层补齐语义。表中创建默认指新界面行为；新界面必须显式提交 completion_mode。兼容已有完整创建payload时，未传 completion_mode 的服务端默认仍为 time，不能把旧调用改成check。

#### 日行动字段

| 字段 | 类型与范围 | 创建默认/必填 | 规则 |
| --- | --- | --- | --- |
| `id` | 服务端生成字符串 | 服务端 | 创建后稳定，改期不换 ID |
| `schema_version` | 整数 `2` | 服务端 | 新记录语义版本；旧记录缺省视为 1 |
| `title` | trim 后 1–160 字符 | 必填；内容入口预填来源标题 | 标题只用于显示，不作为内容身份 |
| `period` | `day` | 快速创建固定 | 年/月/周仍用原编辑器 |
| `completion_mode` | `time/content/check` | 普通入口 `check`；内容入口 `content` | 用户可在创建时切换，出现执行事实后锁定 |
| `start_date`、`end_date` | `YYYY-MM-DD` 或 `null` | 日期控件默认今日；可选择暂不安排 | 两者同空或同一日期；不接受只有一端为空 |
| `timezone` | 有效 IANA 时区 | 有效个人时区，否则 `Asia/Shanghai` | 创建时快照；隐藏在更多设置，不跟随设备自动变更 |
| `at` | 本地 `HH:mm` 或 `null` | `null` | 日期为空时必须为空；有日期时也可为空，表示当天做 |
| `reminder` | 布尔 | `false` | 为 true 必须同时有日期和具体时间；否则 422，不能暗填时间 |
| `reminder_at` | UTC 时间戳或 `null` | 服务端派生 | 有日期及时间才可生成；仅 reminder=true 时投递。未设具体时间不能导出假定时日历事件 |
| `target` | 来源引用对象或 `null` | `check/time` 默认 null；内容入口预填 | content 必须具体引用；time 可无来源或沿用 book/library；新 check 为 null |
| `target_minutes` | 整数 1–1440 或 `null` | time 默认 20；其余 null | 只定义 time 的达标阈值；content/check 不用它判断完成 |
| `minimum_minutes` | 整数 1–`target_minutes` 或 `null` | time 默认 min(5,标准分钟)；可关闭 | 只用于 time；小于标准分钟时才展示起步按钮；非 time 为 null |
| `estimated_minutes` | 整数 1–1440 或 `null` | `null` | content/check 的可选预计投入；不进入实际投入或完成阈值；time 为 null |
| `target_count` | 整数 `1` | 内部固定 | 一个日行动只贡献一项有效完成，不按会话数计 |
| `parent_id` | 上级计划 ID 或 `null` | `null` | 更多设置；非空时仍检查账号、周期、日期包含和相同时区。未安排日行动不允许关联有界上级 |
| `reason`、`if_then` | 字符串，各最多 1000 字符 | 空串；更多设置 | 可空，不影响创建和完成 |
| `status` | `active/paused/completed/archived` | 服务端设 active | 客户端不能直接覆盖，必须执行操作 |
| `completed_at` | UTC 时间戳或 null | 服务端 | 最新有效完成的发生时间；check 撤销后为空 |
| `completion_record_id` | 事实 ID 或 null | 服务端 | 指向最新有效完成事实；撤销后为空 |
| `revision` | 正整数 | 服务端从 1 开始 | 每个成功改变事项的命令加 1；重试、返回已有安排、拒绝操作不加 |
| `created_at/updated_at` | UTC 时间戳 | 服务端 | 不随页面渲染变化 |

内容引用沿用 `{kind,course,plan_id,lesson_no}`。身份归一化只保留该 kind 的有效键：article 用 course；plan 用 plan_id+lesson_no；renzhi 用 lesson_no；yingyu/biaoda 用 course；book/library 为旧通用执行入口。所有具体引用必须可由当前账号读取，服务端不信任标题或客户端传入的 URL。只有已接入明确完成确认及回执的来源才开放 content；P0 必须覆盖文章与课程计划课程，其他课程模块未接入时明确提供 time 方式，不伪装支持 content。

编辑约束：运行中拒绝编辑；已有任一执行事实后禁止修改 `completion_mode`、`target`、`target_minutes`、`minimum_minutes`，需要变更时复制新行动。标题、备注、提醒可在非运行状态修改；改期用专用操作。completed 和 archived 在 P0 只读（check 的 reopen 例外）。切换完成方式必须显式清理不适用的字段，不能让隐藏字段继续生效。

#### 执行事实字段

沿用 `action_executions`，不另建一套可编辑执行历史。

| 字段 | 含义与约束 |
| --- | --- |
| `id/plan_id/schema_version` | 稳定事实 ID、行动 ID、新事实版本 2 |
| `record_kind` | `session` 计时会话、`completion` 零分钟完成确认、`reversal` 勾选撤销 |
| `completion_mode` | 开始/确认时的模式快照 |
| `outcome` | session：running/completed/minimum/partial/interrupted/recorded；completion：completed；reversal：reopened |
| `actual_minutes` | 用户确认的本次实际整数分钟，0–1440；running 尚未确认记 0；completion/reversal 必须 0 |
| `completion_effect` | `none/complete/reopen`；一个行动至多有一个未撤销的 complete 效果 |
| `reverses_record_id` | reversal 必须引用该行动当前有效的 check 完成事实；其余 null |
| `source_event_id` | content 完成必须引用有效来源确认回执；不能仅使用来源 read=true |
| `started_at/ended_at` | session 真实开始与结束 UTC 时间；瞬时确认/撤销取同一发生时间 |
| `business_date` | version 2 会话按开始瞬间在快照时区的日期；瞬时确认/撤销按其发生日期 |
| `planned_date` | 开始或确认时原安排日期快照；不被之后改期覆盖 |
| `timezone` | 事实发生时行动时区快照 |
| `title/target/variant/planned_minutes/note` | 执行时快照；variant=standard/minimum；note 最多 2000 字符，选填 |

`recorded` 表示 content 的可选计时已记录，不代表内容完成。check 不提供计时入口；需要专注投入时创建 time 行动。已确认事实只追加，不修改；撤销通过 reversal 抵消完成效果，原事实仍可追溯。

同一次 time finish 可以同时是 session 和 complete 效果，不再插入另一条零分钟记录。content 计时结束与内容确认是两件事：可以一条 session 加一条 completion，界面必须区分，不把两条都计成完成。

#### 草稿字段

`{draft_id, account_id, flow, origin_key, parent_context, entry_date, updated_at, base_revision, values, pending_key}`。

- flow 为 create-day/edit；编辑按 action ID 隔离。
- origin_key 为 general 或归一化具体来源身份；parent_context 与 entry_date 也参与恢复候选筛选。
- 每份新建草稿独立 draft_id，存储键包含账号与 draft_id；上下文索引只负责列候选，不能覆盖旧草稿。
- 同一上下文只一份草稿时自动恢复，多份时显示名称/日期/保存时间供选择；显式“新建另一份”产生新 ID。
- entry_date 表示从哪个日期入口进入；不能拿草稿已填写日期替代它，导致从“明日”恢复“今日”草稿。
- 值中可以有 null、完成模式和内容引用；不能缓存 AI 凭据。已提交或查询确认成功后清除对应草稿，其他草稿保留。
- 修改关联未知pending的表单时，旧提交快照保持不可变，新输入复制到新draft_id；核对旧提交成功不能连带清除新输入。

### D3. 创建流程与入口默认

| 入口 | 默认日期 | 默认模式 | 默认内容 | 保存按钮 |
| --- | --- | --- | --- | --- |
| 今日的“新建行动” | 当前账号默认时区的今日 | check | null | 加入今日 |
| 明日预览/选定日期中新建 | 入口日期 | check | null | 加入明日/保存安排 |
| 行动工作区“新建行动” | 今日，可切换暂不安排 | check | null | 随日期变化 |
| 来源的加入今日/明日/选日期 | 用户选择日期 | content | 当前来源 | 确认安排 |
| 选择“投入一段时间” | 保留日期 | time | 可选来源 | 按日期命名 |
| 暂不安排 | null | 保留模式 | 保留合法引用 | 保存行动 |

普通表单首屏仅显示名称、日期、完成方式及对应条件。time 才展示标准分钟；content 才要求具体内容（来源进入时只展示已选内容，可更换）；check 无分钟字段。“更多设置”含时间、提醒、上级、起步、动机和分心约定。既有同周批量只保留在原高级入口，不成为 P0 快速创建必经步骤。

名称/时间等错误与字段关联，提交总错误使用可读状态提示；打开对话框焦点进入第一个可编辑字段，关闭返回来源控件；键盘可完成创建。隐藏条件字段不进入 Tab 顺序。

保存成功按服务端结果展示行动；服务端保存成功而列表刷新失败时提示“已保存，列表暂未刷新”，不要求再建一次。保存成功后可点“现在开始/打开内容”；不自动开始计时。本文不将“30 秒创建”等未测量指标作为已实现结果。

### D4. 行动状态机

“无运行会话”指该行动没有 running；用户同时最多运行一个会话的全局约束仍保留。

| 当前状态 | 命令 | 条件 | 结果 |
| --- | --- | --- | --- |
| 不存在 | create/schedules | 字段有效、引用可读 | active；无执行事实 |
| active | start | time/content；日期不晚于今日；有日期；上级可执行；账号无其他运行会话 | 仍 active；创建 running session |
| active | finish | 本行动 running、会话 ID 和 revision 匹配 | 按 D5 结算；清除 running；可保持 active 或转 completed |
| active | complete-time | 仅 time；有日期且不晚于今日；上级可执行；无本行动 running；累计确认分钟>=标准 | completed；写零分钟完成事实 |
| active | complete | 仅 check；有日期且不晚于今日；上级可执行；本行动无 running | completed；写零分钟完成事实 |
| active | confirm-content / reconcile-content | 仅 content；D5 的来源证据有效；本行动无 running | completed；写零分钟完成事实 |
| active | pause | 无本行动运行会话 | paused |
| paused | resume | 非归档；无非法引用变化 | active；日期保持原值，不自动顺延 |
| active/paused | reschedule | 无本行动运行会话；日期/上级/去重校验通过 | 状态不变；同 ID；更新日程 |
| active/paused | cancel/archive | 无本行动运行会话 | archived；关闭提醒；来源与事实保留 |
| completed | reopen | 仅 check；本行动无 running；引用当前完成事实 | active；写 reversal；撤销完成效果 |
| completed | 其他写操作 | 不满足上述 reopen | 409；需要再次执行时复制为新行动 |
| archived | 任意写操作 | 不含同 key 回执重放 | 409；需要重新安排时创建新行动 |

start、check complete、content complete 都校验全部祖先为 active；否则返回 409，不暗中解关联。暂停/归档/完成人工上级会阻断子行动；存在运行中的后代时拒绝该上级操作，并明确显示影响。层级本身不在 P0 重构。

表中 confirm-content 是来源确认后的服务端内部处理，不是允许客户端绕过来源直接提交的操作；客户端修复同步只能使用有证据校验的 reconcile-content。

未安排行动保存为 active，但不能直接 start/complete；界面提供“安排今日并开始/完成”，先显式保存日期，再用新 revision 执行。第二步失败必须显示已安排但尚未开始/完成，不能声称两步均成功。未来行动必须先改期才可执行。过去行动允许明确补做，保留原计划日期，实际发生日期另存。

### D5. 完成规则

#### time：确认的累计投入达到标准

令 `M` 为同一行动已结束 session 的确认分钟总和（含真实投入的 interrupted），`T` 为锁定的 target_minutes，`m` 为本次确认分钟。

- start、计时到点、切换页面、后台停留和刷新都不改变完成状态。
- 用户“结束并记录”提交 `outcome=completed` 时，m 必须 >0；M（含本次）>=T 时，本 session outcome=completed、completion_effect=complete，行动 completed。
- 未达 T 时，按本次 m 与起步阈值区分 minimum/partial；行动 active。关闭起步后，未达标统一 partial。
- 用户“中断并保存”可提交 m=0；结果 interrupted，行动保持 active，即便 M>=T。若已累计达标，展示“累计投入已达标，确认完成”；用户显式 complete-time 命令写零分钟完成事实，不要求伪造新会话。普通 complete 不得绕过 time 规则。
- 达标后不能再 start。同一天独立再次执行须创建另一行动；同一内容的 time 行动允许多个，不按来源去重。
- time 完成永不调用课程/文章完成接口。

#### content：来源明确确认，投入独立

- content 完成必须有当前账号、相同归一化 target 的明确完成事件回执。来源接口保存正文/笔记、滚动、旧 read=true、AI 推断都不是事件。
- 回执至少含 `event_id, owner, normalized_target, confirmed_at, origin_action_id?, planned_date_at_confirmation?, timezone_at_confirmation?`，并在来源确认成功时持久化。相同来源提交的同 key 重试返回同 event_id。origin_action_id 须由服务端验证账号/target，不可跨来源指定。
- event.confirmed_at 不早于 action.created_at；有 origin_action_id 时只处理该行动，日期不得晚于事件发生时行动时区的今日；无明确行动上下文时只处理事件当日匹配的 content 安排。
- 过去未完成行动可从该行动进入来源再次明确确认；未安排和未来安排不随来源事件自动完成。一个事件只能完成一个行动，完成绑定必须持久且幂等；已取消行动不能消费事件。
- “核对完成”只重放已绑定或按上述规则可匹配的持久回执，不能仅检查来源布尔状态。没有证据时显示“未找到本次确认，请打开内容确认”。
- 来源成功但行动同步失败时保留来源成功，显示该行动待核对；重试不得撤销来源状态或重复创建完成事实。核对延迟到次日也使用 source_event.confirmed_at 作为内容完成的事实时间，另存写入时间 recorded_at；不能将核对日期冒充确认日期。有明确行动上下文时，回执保存确认时计划日期/时区快照；确认后改期到未来或撤销日期则不自动核对，须先处理安排冲突，不能用延迟核对绕过未来/未安排限制。
- 本行动有 running 时先结束/保存投入再确认来源完成；来源接口若已成功保存，回执保留待核对，不把运行分钟自动置 0，也不静默结束会话。
- content 可选计时 finish：正常结束为 recorded、中断为 interrupted，只记录投入，行动仍 active。之后 content 确认写零分钟 completion；完成数只加 1，分钟保持已有确认之和。
- 来源取消已读/已学不会自动撤销历史行动完成；再次学习应新建安排，使用新的明确确认事件。

来源保存与回执必须同事务成功（来源在相同 PostgreSQL 时），或有可恢复的持久提交记录保证来源成功不会丢失事件。事件绑定、行动完成、完成事实和该操作回执在行动事务中共同提交，不能先占用事件再失败。来源成功响应增加 source_event_id、completed_arrangements，未同步成功时返回可读 arrangement_sync_error；回执查询/核对仅当前账号可用。P0 不开放无法提供该保证的来源的 content 模式。先以文章与课程计划课程实现和验收。

#### check：明确勾选、明确撤销

- 点击完成写零分钟 completion；不要求启动计时，不更新任何来源状态。
- 勾选撤销只适用于 check，写 reversal 引用当前有效完成事实；不删除旧记录、不减历史真实投入。
- 再次勾选产生新的完成事实，但当前有效完成项数仍为 1。不同 key 并发重复勾选只能一条成功，另一条 409 并刷新当前状态。

### D6. 去重、改期与提醒

内容安排去重键为 `(账号, normalized_target, timezone, start_date)`，只作用于 `period=day && completion_mode=content && status!=archived`。未安排用单独 null 日期桶去重，不与已定日安排冲突。标题、请求 key、提醒设置不参与身份。

- 所有创建入口、完整编辑和改期共享该校验，并在账号写事务中原子处理。
- schedules 的重复加入返回 `{plan, existing:true}`，不覆盖已有的标题、时间、状态或版本；已完成也返回原安排。
- 通用 create 发生相同冲突返回 409 和 existing_plan_id（仅当前账号），界面提供“查看已有安排”，保留草稿。
- reschedule 冲突返回 409，原 ID、日期、提醒、事实、revision 都不变。check/time 不因同名或同来源而去重。
- reschedule 接受 date=null 表示撤销日期安排，保持事项 active/paused，同时清空 at、reminder、reminder_at；再次设日期也不自动恢复旧提醒。
- 暂停/取消停止网页提醒；恢复仍按原日期判断是否待调整；历史执行不改期。
- 无具体时间时不生成网页到点提醒，也不导出伪造的定时日历，界面提示“设置具体时间后可添加日历”。有时间而未开提醒可导出无 alarm 的事件。
- 既有前台提醒、免打扰、设备去重与日历副本说明继续有效；不新增后台推送承诺。

### D7. 视图、日期和统计

互斥的未完成视图：

- 未安排：active/paused，start_date=null。
- 今日/明日/选定日：start_date 等于所选日期；展示 active/paused/completed，取消项默认隐藏。
- 待调整：active/paused，start_date 早于该行动时区的今日，无本行动 running；标明暂停或上级阻断原因。
- 正在执行：账号唯一 running 优先展示，可与所属日期卡片共享同一 ID，不复制数据。过去的 running 不同时进入待调整。

首页今日预设日期按有效个人时区计算；切换日期是选择具体日期，不修改行动时区。每张异时区卡片显示其时区。未来执行判断和过去判断一律用行动时区，不用服务器本地日期。

记录/成长按 version 2 `business_date` 展示实际事实；原计划日期单独显示。23:58 开始、次日 00:10 结束的 session 12 分钟全部归开始日，不在 P0 估算拆分。content 次日才确认时，完成归确认日，投入可归前日。修改设备时区、行动日程不移动历史事实。

统计公式：

- `minutes = sum(已结束 session.actual_minutes)`，completion/reversal 不贡献分钟。
- `completed = 有效完成行动的去重项数`，每个行动最多 1；check 的 reversal 抵消对应完成，不重复累计重新勾选。
- `minimum/partial/interrupted` 是会话次数，须分别命名，不能与完成项数混为同一单位。
- 上级累计执行进度按后代行动 ID 去重聚合；上级人工完成不额外制造日行动完成事实。
- 日期范围内完成按当前有效完成事实的发生日期计；投入按 session 发生日期计。check 撤销后实时统计重算，原已保存复盘/AI 快照保持原值并注明为当时快照。
- 复盘选区不再用计划 start/end 禁止查看明确补做产生的实际事实；未安排行动也可选明确日期范围复盘，最大范围仍 366 天。计划项数按计划日期单列，不能充当实际完成分母。

### D8. 操作合同与恢复

复用现有路径，所有修改仍带账号上下文、同源保护、幂等 key；针对已有行动必须带 revision。成功保存事实、更新行动和回执须同事务提交。P0启用后的行动写请求还须携带 `X-Grow-Action-Schema: 2`，缺少或不支持的合同版本返回409/CONTRACT_UPGRADE_REQUIRED；先按原规则执行同源和账号检查，不将版本头当认证。只读请求不要求该版本头，且该规则不拦截原来源保存接口。写版本头表示请求理解新语义，与所编辑旧记录的schema_version不同；旧记录的兼容完整payload仍可在版本2调用中提交。

| API/操作 | P0 语义 |
| --- | --- |
| GET /api/action-plans | 原计划/执行响应继续存在；新增 `action_schema_version:2` 与能力标志；null 排序稳定，不能因缺日期报错 |
| POST /api/action-plans | 原创建壳 `{plans:[...]}`；支持新日行动字段；所有入口共用校验 |
| POST /api/action-plans/schedules | 保留 `{title,target,date,timezone,target_minutes?,key}`；仅创建 content；新预计字段用 estimated_minutes，旧 target_minutes 作为预计兼容，不变为达标阈值；两者都给且不一致返回 422 |
| POST /{id}/operations: reschedule | date 为合法日期或 null；其余见 D6 |
| POST /{id}/operations: start/finish | start 仅 time/content；finish.actual_minutes 是本次，不是累计；time 累计由服务端计算 |
| POST /{id}/operations: complete | 仅日行动 check 或原长计划人工确认；不调用内容完成 |
| POST /{id}/operations: complete-time | 仅 time 累计已达标、无 running，显式确认中断后的达标 |
| POST /{id}/operations: reconcile-content | 提供 source_event_id；或由服务端按 D5 找唯一适用回执；仍带 revision/key，不读取全局 read 状态代替事件 |
| POST /{id}/operations: reopen | 仅 completed check；写 reversal |
| GET /records | 保持分页，新增事实字段；界面区分投入/完成/撤销，旧记录仍可读 |
| GET /requests/{key} | 查询已提交回执；不得因已开始接管而拒绝读取本地已存在回执；只允许当前账号 |

成功 200；字段/非法日期/未来执行为 422；状态、版本、运行冲突、改期去重冲突为 409；不可见行动/来源/事件为 404；同源拒绝 403。响应保留人可读 detail，增加稳定 `code` 和仅限当前账号的恢复信息：VALIDATION_ERROR、REVISION_CONFLICT、STATE_CONFLICT、RUNNING_CONFLICT、DUPLICATE_SCHEDULE、FUTURE_ACTION、UNSCHEDULED_ACTION、COMPLETION_EVIDENCE_MISSING、CONTRACT_UPGRADE_REQUIRED。后者用于不支持 P0 的接管方，409，不静默改本地写入方。

same key+相同语义 payload 返回原结果，即使 revision 已变化；same key+不同 payload 返回 409，不执行。不同 key 不具有请求幂等，但内容安排另有业务去重。已有 pending 的 payload 不可被新输入覆盖：先查回执，found 时只清理对应已提交草稿并刷新；not found 不证明在途请求未提交，须保留原请求并显式重试原key/payload，不自动换key重发或提供“放弃后重建”。仅收到明确未提交的校验/状态拒绝，或确认根本未发送时可释放pending；新输入继续另存草稿，旧请求核对成功后再显式编辑。

### D9. 旧数据与跨端合同

- 缺 completion_mode 的旧行动继续 time；保留原日程、21:00、提醒和长短期，不批量改成新默认。
- 旧 time 执行 outcome=completed 视为既有完成证据，历史分钟和当时达标结论不按新累计规则重算；尚 active 的旧 time 行动后续 finish 按新累计规则结算。
- 旧 content/check 的 target_minutes 只作历史预计值映射，不能作为新完成阈值；新字段写入清理不适用字段。
- 旧记录无 record_kind 时按历史模式/会话字段识别 session 或 completion，识别不确定的标为 legacy，不补造来源事件或拆分事实。
- version 1 business_date 保持原值，标记 date_basis=legacy_planned；version 2 为 actual_start/actual_confirmation。展示和导出说明旧记录采用历史日期口径，不能无提示混称实际发生日。
- 已存复盘/AI 结果不重算、不删除，生成新的预览按新事实规则；快照变更仍需重新预览与同意。
- 连接 Zook 时需同步完成 nullable 日程、完成方式、事实与错误合同，并通过双端回归后才开放 P0 写入。未支持时明确“服务端待升级”，保留草稿；不私自写回 Grow 本地、不自动解绑。
- 能力检查至少区分 nullable_schedule、completion_modes、content_receipts、actual_fact_dates；模块按能力开放，不把不支持的字段转换成假日期/假分钟。新 Web 不得在旧 backend 无能力标记时发送 P0 新语义命令。

## Risks / Trade-offs

- [日期可空影响排序、复盘、日历和原生解码] → 所有消费者进入任务清单；以无日期端到端用例作为交付门槛。
- [同一记录承担投入与完成效果可能重复计数] → 按 record_kind 与 completion_effect 计算，完成数按行动去重；界面不用“会话完成”代替“行动完成”。
- [来源确认与行动同步不是同一请求] → 持久确认回执、明确消费关系、幂等核对；无法留证的来源不开放 content。
- [累计分钟改变旧 time 行为] → 不重算历史完成结论；新结算在确认界面显示本次/累计/阈值，验收覆盖中断达标。
- [一个操作分安排和开始两步] → 明确展示中间成功状态与失败原因，不回滚已保存的日期，也不误报已开始。
- [连接端仍在独立 change 中开发] → 本文件是待对齐合同；本次只落规格，不替另一 change 声称已支持。

## Migration Plan

1. 实施前固定基线并生成隔离 schema 的旧记录样本；列出当前部署是否处于本地或 Zook 接管状态。
2. 先增加服务端读适配、校验、事实/回执和能力标志，再接创建、内容入口与各统计消费者；原服务暂不开放新 Web 入口。
3. 在隔离账号执行 acceptance.md 全部必选用例及原行动/复盘/来源回归；未运行用例必须列明，不以文档完成代替验收通过。
4. 双端合同同步后按账号/部署能力开放；迁移与发布由后续明确授权执行，不属于当前规格任务。
5. 若回退界面，先关闭新语义写入并保留新事实；不能把含 null 日程或新 outcome 的数据交给不支持的旧写入程序。维持新服务读适配或只读状态，按备份和前向修复处理，禁止删除真实记录完成回退。

## Open Questions

无阻塞产品决策。实现开始时仍需核对 Zook 当时合同版本与除文章/课程计划之外的来源确认能力；这属于能力清单和兼容检查，不能在未验证时扩大支持范围。
