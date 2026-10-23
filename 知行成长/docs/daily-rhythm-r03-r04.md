# 日常节奏 R03 / R04 交付说明

日期：2026-10-21。范围：偏好与每日主任务后端、执行元数据快照、低状态步骤确认、来源完成回执。页面、总结补写、业务埋点和周卡仍留给后续任务。

## 实现与入口

| 文件 | 本轮实现 |
|---|---|
| `server/rhythm/service.py` | 偏好版本与生效时间、每日主任务选择/模式、历史只读查询、当前执行及相关事实投影 |
| `server/rhythm/api.py` | 在现有action router中注册节奏接口；复用认证、账号隔离、同源和行动协议保护 |
| `server/rhythm/facts.py` | 开始/来源确认时冻结上下文，确认时记录当地日期，小步骤事实及按来源事件读取稳定执行回执 |
| `server/rhythm/contracts.py` | 新增严格StepInput，要求明确did_act=true，禁止用布尔/字符串冒充revision或分钟 |
| `server/rhythm/store.py` | 新节奏数据存在性检查，供旧接管快照保护使用 |
| `server/action_plans.py` | 最小接入start/finish/complete/reversal的元数据钩子；来源成功及核对结果增加执行回执 |
| `server/action_content.py` | 来源发布前捕获私有节奏上下文，随原来源提交日志持久化；不写入GitHub或远端outbox合同 |
| `server/action_link.py` | 未支持的连接端阻止节奏本地读写；新节奏数据阻止旧接管格式丢失数据 |

本轮没有数据库结构升级，继续使用R02的schema version 1。合同版本仍为rhythm 1；写请求沿用现有 `X-Grow-Action-Schema: 2` 和 `X-Copilot-Request: 1`，不能用rhythm合同号代替行动协议号。

## R03 接口与规则

共同前缀：`/api/action-plans/rhythm`。实际应用仍要求有效登录会话；接口不接收调用方指定的账号或schema。

| 方法/路径 | 合同 |
|---|---|
| `GET /capabilities` | 返回contract_version、supported、reason；首次默认FEATURE_DISABLED；连接端未支持时返回CONTRACT_UPGRADE_REQUIRED，不读取旧本地偏好 |
| `GET /today?date=YYYY-MM-DD` | 当前有效/待生效偏好、所选日期主任务、账号当前running、主任务相关执行及撤销记录、read_only；日期可省略；历史与未来日期只读 |
| `POST /preferences` | PreferencesInput：key、expected_revision及设置；保存后返回当前偏好和pending_preferences |
| `POST /focus` | FocusInput：key、expected_revision、date、plan_id、可选完成标准/第一步 |
| `POST /focus/{id}/mode` | ModeInput：key、expected_revision、standard/minimum/rest、minimum_step |

- 默认不创建偏好或主任务，不自动开启提醒；用户显式开启后才能写主任务/步骤。
- 首次设置立即生效，effective_from使用用户选择时区的本地日期。后续周目标、时区和回顾星期从下一周一生效，边界按更改前有效时区冻结为effective_at。
- 开关和提醒控制立即生效。比如已有下周目标，关闭功能仍立即生效；本轮不实际投递提醒。
- 保存使用账号内全局偏好revision。相同effective_from的再次修改保留旧版本到history；当前、未来和历史版本可区分。生效比较使用带时区的真实时间点，不能按ISO字符串排序。
- 同账号同日只有一条主任务；换任务沿用focus ID并递增revision。只允许选择当天已安排、可执行的day行动，未安排、错日期、已暂停/完成/归档、不可见或上级阻断的行动会拒绝。
- 新建行动沿用原API，然后再选择为主任务；选择失败不再创建一次行动。
- 模式变化不改写已开始执行的快照。休息要求先保存账号当前running；已有事实保留，不因休息被隐藏或删除。
- `GET /today`顶层偏好/时区为当前设置，历史主任务和执行各自保留原时区快照；不把当前设置写回历史。
- 业务写入、revision、幂等操作回执共享既有action账号事务锁。相同key/payload返回原回执；不同payload复用key或旧revision会拒绝。

## R04 事实、日期与模式

新执行增量字段包括：fact_version、activity_confirmed、activity_at/date/timezone、rhythm_variant、minimum_step_snapshot、focus_day_id、focus_plan_id_snapshot、focus_selected_at_snapshot。

| 场景 | 行为 |
|---|---|
| 开始time/content | 开始时冻结当前主任务与实际请求variant。activity_confirmed=false，确认时间为空；不会因开始或计时自然流逝算行动 |
| time/content结束 | 保留原P0的business_date、planned_date、outcome和累计达标规则；新增activity_date按本人确认结束时的快照时区计算；有正数实际分钟才构成投入事实 |
| 跨午夜 | P0投入仍归开始日；节奏活动日期归确认日。两者分别保存，不搬动旧事实 |
| content最低版本 | 需要在当前主任务确认具体最小步骤；保留可选投入及步骤快照；保存投入不会标记内容完成 |
| check明确完成 | 保留原零分钟completion及complete效果，记录确认日期；不推算学习分钟 |
| check最低步骤 | 新增record_kind=step、outcome=partial、completion_effect=none、actual_minutes=0；属于真实尝试，原check仍active，不能假称完整待办完成 |
| check撤销 | 沿用追加reversal与reverses_record_id；原完成JSON不修改，撤销本身不构成新行动；主任务查询也带回关联撤销记录 |
| time累计后的零分钟complete-time | 保留目标完成效果，但不制造新的投入日 |
| 旧记录/先开始后选主任务 | 不回填旧确认日期，不把后选的主任务绑定到已经开始的执行；读取旧note不制造新的节奏事实 |

`POST /steps` 输入：key、plan_id、plan_revision、focus_day_id、minimum_step、严格布尔did_act=true，以及可选note/next_step。必须匹配当前最小步骤、主任务及可执行check行动，且账号无其他running；返回plan与execution。执行事实、plan revision、操作回执同事务提交，失败可用原key重试。

本轮只保存步骤的初始note/next_step，不提供总结修改或历史版本接口；后者仍属于R05。没有写入action_rhythm_events，也没有启动试验或提醒，R06/R16/R17仍未实施。

## 文章与课程来源回执

复用当前已实现的P0来源确认事件，不再用read=true等全局状态替代本次确认。

1. 真正的文章/课程确认在发布前，使用短action事务锁读取当时主任务，生成私有rhythm_snapshot，随来源确认日志保存。
2. 来源发布成功后按原机制完成或延迟核对行动；保存来源成功、同步失败的状态保持可恢复。
3. 行动完成事实使用原source confirmed_at及捕获的上下文。即使后来换主任务、切模式、关闭功能或跨天核对，都不会重新猜当前主任务。
4. 连接端接管中不读取旧本地主任务；不扩展已有远端outbox事件签名/负载合同。
5. 来源成功响应、成功核对响应新增 `action_completion_receipts: [{plan_id, execution_id, activity_date}]`。尚未匹配时为[]；重复来源确认和原key核对返回同一执行ID，不增加事实。
6. `GET /source-receipts/{event_id}` 可重复读取当前账号来源事件关联的执行回执；不可见事件404，读取不写入。核对继续沿用P0状态机，已完成后的回执恢复使用此只读入口，不改变既有已完成操作的409规则。

以上通过真实文章personal接口和课程feedback接口验证，私有focus ID和事件上下文没有进入GitHub教学内容。

## 接管与既有工作保护

R03开始产生私人数据，因此提前落实必要的后端单写入方保护：pending/active/未知接管状态下拒绝节奏数据接口，能力查询只返回不可用，不转发未知新接口，也不回落本地。旧接管预览/确认/快照遇到新节奏数据时拒绝，不能丢下新表后继续接管。

这不代表R12的页面开关与完整交付已经完成，也不代表LightTick已支持节奏合同。原生和远端合同仍属于后续工作。

实施前保存了文件及Git index快照。本轮没有执行git add、commit、stash、reset或清理工作树；保留原有暂存和未暂存内容。期间观察到其他页面/测试文件及index发生更新，没有恢复旧快照或覆盖这些并行改动。本轮只对上表后端文件和本计划文档做局部修改，并新增隔离测试。

## 验证结果

最终在同一隔离入口运行 **165项Python测试，0失败、0错误、0跳过**：

- 56项节奏测试：含R01/R02原26项与本轮新增30项，覆盖严格合同、偏好生效/版本/并发、真实账号隔离、开始快照、跨午夜、最低步骤、撤销保留、来源日志/回执和失败事务回滚。
- 109项相关回归：行动P0、课程和文章来源完成、P0收尾、日行动、行动复盘、日期安排、来源联动outbox恢复、旧state保存及隔离防护。
- 三组Node兼容检查通过：`test_action_plan_client.cjs`、`test_action_p0_client.cjs`、`test_legacy_state_client.cjs`。
- 隔离审计的外部网络、真实数据库和工作区写入三个blocked计数均为0；本轮测试未使用SQLite。

最终日志：`/tmp/grow-rhythm-r03-r04-verification.log`。首次失败用例证据：`/tmp/grow-rhythm-r03-red.log`、`/tmp/grow-rhythm-r04-red.log`。前序分阶段结果：`/tmp/grow-rhythm-r03-r04-expanded.log`、`/tmp/grow-rhythm-r03-r04-action-regression.log`。

所有数据库测试使用本轮单独创建的localhost PostgreSQL实例及临时schema；GitHub/模型/桥接调用使用隔离夹具。没有连接、迁移或重启业务数据库/实际服务，没有调用真实模型。本轮验收限于相关后端/客户端兼容用例，没有宣称全仓库或新页面浏览器验收已完成。

验证结束后已停止本轮临时PostgreSQL实例，日志与临时目录保留作本机核查。新增Python文件语法及本轮范围空白检查通过。
