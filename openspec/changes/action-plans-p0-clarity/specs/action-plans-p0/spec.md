## ADDED Requirements

### Requirement: P0 field contract and compatibility

系统 SHALL 遵守 `../../design.md` D1–D2、D9 的字段与兼容合同：仅扩展日行动的可空日程，保留原年/月/周层级；创建区分 time/content/check，按模式校验和清理条件字段；服务端维护状态、事实、版本和能力标志。旧数据 SHALL 可读且不被新默认值覆盖。

#### Scenario: Create an undated check action
- **WHEN** 用户填写合法标题，选择 check 和暂不安排并保存
- **THEN** 服务端保存一项 active 日行动，日期、时间、来源、达标分钟为空，提醒为 false；不生成执行事实，也不写假定今日或 21:00

#### Scenario: Reject incompatible hidden fields
- **WHEN** content 缺少具体可读来源，或者开启提醒但缺日期或时间，或者日期只有一端为空
- **THEN** 服务端返回 422，原草稿保留，不创建部分记录；界面关联到具体错误字段

#### Scenario: Read historical data
- **WHEN** 读取缺少新字段的历史计时行动和已保存复盘
- **THEN** 原日期、时间、分钟、完成结论和复盘快照不变；读适配标识旧事实日期口径，不补造确认事件

### Requirement: Contextual quick creation

系统 SHALL 在快速创建首屏只要求名称、日期选择、完成方式和该方式必要条件；D3 入口默认值 SHALL 自动带入，时区/提醒/上级/起步/动机按需展开。页面 SHALL 支持键盘、条件字段焦点和保存后的明确反馈。

#### Scenario: Add an article to tomorrow
- **WHEN** 用户在文章页点击加入明日
- **THEN** 名称、具体来源、明日日期和 content 已预填，不要求填时长、时区或上级，确认后显示服务端已保存的安排

#### Scenario: Save succeeds but refresh fails
- **WHEN** 创建请求已提交成功而后续列表刷新失败
- **THEN** 页面显示已保存及刷新失败，保留返回的行动 ID，清除该成功草稿，不再次创建

#### Scenario: Keyboard and condition changes
- **WHEN** 用户仅用键盘切换 check/time/content 并尝试提交非法值
- **THEN** 隐藏字段不参与焦点和提交，错误可读且与对应字段关联，对话框关闭后焦点返回原入口

### Requirement: Separate action and session state

系统 SHALL 按 D4 转换表执行，行动仅有 active/paused/completed/archived；会话与派生视图不混入 status。每账号 SHALL 最多存在一个 running session，非法转换 SHALL 原子拒绝，不改事实或 revision。

#### Scenario: Reload during a session
- **WHEN** 用户开始 time 行动后刷新或重启服务
- **THEN** 恢复原 running session，不增加新会话或完成；可继续记录结束或中断

#### Scenario: Concurrent start and terminal editing
- **WHEN** 两项行动并发 start，或尝试编辑运行中/已完成/已归档行动
- **THEN** 并发 start 仅一项成功，其他冲突返回 409；编辑遵守 D2/D4 限制，不覆盖历史快照

#### Scenario: Blocked parent
- **WHEN** 上级非 active 时请求 start、check complete 或 content 完成
- **THEN** 返回 409 并解释上级阻断，子行动保留状态；暂停有运行后代的上级也被拒绝

### Requirement: Explicit cumulative time completion

time 行动 SHALL 仅以同一行动内用户确认的已结束 session 分钟累计判断达标；计时到点、页面停留和来源完成 SHALL 不代替确认。一次行动 SHALL 至多贡献一项有效完成，起步/部分/中断保持独立结果。

#### Scenario: Minimum followed by remaining minutes
- **WHEN** 20 分钟目标先记录 5 分钟起步，再正常结束并确认本次 15 分钟
- **THEN** 共两条 session、累计 20 分钟、有效完成一项，行动 completed；关联课程不被标记学完

#### Scenario: Interrupted accumulated target
- **WHEN** 目标累计分钟已达标但本次选择中断保存
- **THEN** 本次为 interrupted、行动仍 active；仅显式 complete-time 才产生零分钟完成效果，不要求虚构另一分钟

#### Scenario: Wall time is not actual time
- **WHEN** 会话经过很长时间但用户确认实际投入 3 分钟
- **THEN** 只记录 3 分钟并按累计值计算，不以墙钟、后台或视频播放时长代替

### Requirement: Content completion requires durable scoped evidence

content 行动 SHALL 仅消费 D5 的持久来源确认事件；事件 SHALL 归属于当前账号、相同来源、合法发生时间与行动上下文，并至多绑定一个行动。来源成功与行动失败 SHALL 能通过回执核对恢复，不回滚内容、不重复完成。文章与课程计划课程 SHALL 为 P0 必选支持范围。

#### Scenario: Time recorded before content confirmation
- **WHEN** 用户为 content 记录 20 分钟但未在来源确认读完或学完
- **THEN** 保存 recorded session、累计投入 20 分钟、有效完成零项；来源明确确认后再增加零分钟完成事实，有效完成为一项

#### Scenario: Historical read flag is insufficient
- **WHEN** 来源旧状态为已读，但没有不早于该行动创建且适用于该行动的确认回执
- **THEN** 核对不完成行动，提示打开内容再次明确确认；保存笔记、滚动或刷新不生成确认事件

#### Scenario: Completion sync fails or session is running
- **WHEN** 来源确认已保存，但行动同步失败或本行动仍有 running
- **THEN** 来源成功和回执保留，行动显示待核对；会话不静默结束或丢失投入，合法结束会话后核对只完成一次

#### Scenario: Do not complete future or unrelated occurrences
- **WHEN** 来源在今日被确认，另有未来、未安排、过去且无明确上下文、或另一账号的同来源行动
- **THEN** 只处理本次回执明确允许的一个行动，其余不变；未来/未安排不能被自动完成

### Requirement: Check completion and audited reversal

check SHALL 支持无计时的显式完成与撤销；完成/撤销事实分钟为零，撤销 SHALL 追加指向原完成的 reversal，不删除历史或虚构投入。普通 check SHALL 不调用来源完成接口。

#### Scenario: Complete reverse and complete again
- **WHEN** 用户勾选、撤销、再次勾选同一事项
- **THEN** 状态依次 completed/active/completed，保留完成/撤销/新完成事实，实时有效完成数依次 1/0/1，实际分钟始终 0

#### Scenario: Repeated concurrent completion
- **WHEN** 两个不同 key 同 revision 并发完成同一事项
- **THEN** 一次成功、另一次 409，事实只记一次；相同 key 重试返回原成功结果

### Requirement: Shared schedule deduplication and adjustment

系统 SHALL 对所有入口使用 D6 的归一化内容身份与日期桶去重；改期/取消 SHALL 保留原行动 ID、来源和历史事实，冲突时原安排完全不变。time/check SHALL 不因同名而错误去重。

#### Scenario: Multiple requests add the same content
- **WHEN** 不同 key 并发通过 schedules 把同一内容加入同一时区同一日期
- **THEN** 返回同一 plan ID，只有一项非归档安排；已完成安排也返回 existing:true，不覆盖既有字段

#### Scenario: Conflicting reschedule
- **WHEN** 将内容安排改到已有相同内容安排的日期
- **THEN** 返回 409 和当前账号的已有安排标识，原日期、提醒、revision、状态和事实不变

#### Scenario: Remove date or cancel
- **WHEN** 无运行会话时撤销日期或取消安排
- **THEN** 撤销日期清空日程与提醒但保留 active/paused；取消变为 archived；两种操作均保留内容、笔记和历史，取消后可新建另一安排

### Requirement: Explicit date views and safe execution

系统 SHALL 实现 D7 的日程、未安排、待调整与正在执行视图；过去事项 SHALL 不自动滚入今日。start/complete SHALL 使用行动时区判断未来/过去，未安排须先明确安排日期。

#### Scenario: Past and future actions
- **WHEN** 时间从 10 月 19 日推进到 20 日，19 日仍有 active 未完成事项
- **THEN** 原日期不变，事项进入待调整而非今日；20 日以后的行动不能直接执行，先改期才可开始

#### Scenario: Schedule then start partially succeeds
- **WHEN** “安排今日并开始”已保存日期，但账号另一会话导致 start 冲突
- **THEN** 页面显示已安排且尚未开始、提供处理现有执行的入口，不删除已保存日期、不声称计时已开始

#### Scenario: Past running session
- **WHEN** 昨日开始的 session 仍 running
- **THEN** 优先显示正在执行，不另生成今日副本，也不同时进入待调整；结束后按事实和行动状态归位

### Requirement: Actual facts and distinct aggregation

系统 SHALL 使用 D7 的统计公式，区分计划日期与实际事实日期、投入会话与有效完成项数；修改日程 SHALL 不移动旧事实。新预览 SHALL 采用新统计规则，已保存复盘/AI 历史 SHALL 保持快照。

#### Scenario: Execute an overdue action
- **WHEN** 用户在 20 日补做原安排 19 日的行动
- **THEN** planned_date 保留 19 日，version 2 实际事实按 20 日保存并用于记录/成长；可在 20 日范围复盘，不被计划日期边界拒绝

#### Scenario: Cross midnight and distinct units
- **WHEN** time session 在 19 日 23:58 开始、20 日 00:10 结束，确认 12 分钟
- **THEN** 12 分钟全部归 19 日开始日期；内容在 20 日确认的完成则归 20 日，不估算跨日拆分

#### Scenario: Aggregate through the parent once
- **WHEN** 子行动有多个 session 和一条有效完成，或 check 完成后又撤销
- **THEN** 上级按后代行动 ID 去重统计完成与会话分钟；撤销后的实时完成回到零，已保存的旧复盘快照不变

### Requirement: Draft isolation and uncertain request recovery

系统 SHALL 按 D2 草稿合同保存账号、来源、日期入口、上级和独立草稿身份；输入与 pending 请求 SHALL 独立保存。未知提交结果 SHALL 先查询或重试原 key，不以新 key 猜测性重建。

#### Scenario: Switch creation contexts and accounts
- **WHEN** 用户填写通用今日草稿，再进入文章明日入口或切换账号
- **THEN** 原草稿保留但不覆盖新上下文；多份同上下文草稿可明确选择，另一账号不可见

#### Scenario: Lost successful response
- **WHEN** 创建已提交而响应丢失，用户刷新后恢复
- **THEN** 查询或重放原 key 取得同一结果，清除对应 pending/草稿，只存在一项行动，当前其他草稿不丢失

#### Scenario: Change input while request is unresolved
- **WHEN** 未确认请求存在而用户改变表单内容
- **THEN** 原 payload/key 保持不可变，新输入另存草稿；不得换 key 自动提交，界面提供原请求核对/重试与明确恢复反馈

### Requirement: Honest reminder eligibility

系统 SHALL 仅对合法日期和具体时间投递提醒；无时间 SHALL 不生成默认 21:00 或假定时日历。暂停、归档、完成、上级阻断和未安排 SHALL 不触发提醒，既有前台、免打扰与日历副本边界保留。

#### Scenario: Date without time
- **WHEN** 用户创建今日行动但不设时间
- **THEN** 今日列表可见，不产生到点提醒，日历入口解释需先设具体时间；设置时间不等于自动开启通知

#### Scenario: Pause and cancel remove eligibility
- **WHEN** 有提醒的行动被暂停、取消或撤销日期
- **THEN** 服务端 claim 不再投递，后续恢复不自动改期，历史事实和来源均保留

### Requirement: Tenant boundary transactional mutations and contract gate

系统 SHALL 保留账号隔离、同源保护、revision 与幂等回执；一次行动修改及其事实/回执 SHALL 同事务提交。P0 SHALL 仅向明确支持合同的写入方开放，不破坏 Zook 接管后的唯一写入方。

#### Scenario: Foreign references and stale edits
- **WHEN** 用户引用另一账号行动/来源/事件，或者旧 revision 提交
- **THEN** 外账号资源返回 404、旧版本返回 409；无部分写入，当前输入保留

#### Scenario: Unsupported connected backend
- **WHEN** 连接写入方不支持 nullable 日程或新事实语义
- **THEN** 对应功能不开启，提示待升级并保留草稿，不把空日期转成今天、不回退到本地双写

#### Scenario: Access old receipts during handoff
- **WHEN** 接管已开始而用户核对接管前的本账号 pending key
- **THEN** 可读取本地既存回执以确认历史结果，不发生新的本地行动写入，也不因写屏障拒绝纯回执查询
