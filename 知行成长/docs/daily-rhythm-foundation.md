# 日常节奏 R01 / R02 合同与数据基础

日期：2026-10-21。范围：合同冻结、增量建表和现有应用初始化接入。尚未开放日常节奏页面、业务接口、埋点采集、试验入组或提醒。

本文件记录R01/R02交付时的状态。当前R03/R04后端接口与事实快照已实现，最新范围及验证见 [R03/R04交付说明](daily-rhythm-r03-r04.md)；本文件原运行结果保留作历史证据。

## R01：已落地合同

代码：`server/rhythm/contracts.py`。合同版本为 `1`；与行动 P0 的 `schema_version=2`、拟新增事实的 `fact_version=2` 分开，不能用版本号推断某项业务已实现。

| 合同 | 已实现约束 | 留给后续任务的业务检查 |
|---|---|---|
| `PreferencesInput` | 幂等key、非负严格整数revision；每周1–7天，默认3天；回顾星期1–7；有效时区；功能/提醒默认关闭；开启提醒须显式时间 | R03保存、生效版本查找；R16认领/送达 |
| `FocusInput` | 合法真实日期，拒绝时间戳、非法日期；plan_id非空；完成标准/第一步≤500字；拒绝user_id/schema注入 | R03校验账号可见、day类型、当日、状态以及并发版本 |
| `ModeInput` | standard/minimum/rest；已存在的正整数revision；minimum必须有具体一步 | R04/R09运行中约束、快照和原完成语义 |
| `RecapInput` | 非空note≤2000字；next_step≤500字；gain/blocker/result；独立总结revision；不接收分钟/活动日期/完成状态 | R05持久化、旧版本保存、冲突和恢复 |
| `rhythm_capability` | 默认关闭；pending/active/未知写入归属均拒绝，错误原因为CONTRACT_UPGRADE_REQUIRED | R12在真实路由、联动状态和页面接入；当前没有节奏路由 |
| 日期函数 | 只接受带时区确认时间；明确当地日；首次偏好当天生效，后续从下一周一生效 | R03以当前有效时区计算边界，保留旧版本 |
| `is_effective_activity` | 纯读取判定，拒绝旧事实、无确认、进行中、撤销、非法日期/时区；time/content确认有正数分钟可计推进；零分钟content必须有来源回执；check完成/明确最低步骤不造分钟 | R04产生真实服务端事实和来源回执；R11先解析撤销、再聚合去重，不能直接相信客户端 |

所有请求模型拒绝未知字段，revision/次数/布尔值不宽松转换。未来路由沿用当前认证、账号schema与同源检查，不能把合同模型当成认证或数据库引用校验。

错误码及HTTP状态已固定在 `ERROR_STATUS`：VALIDATION_ERROR/FUTURE_ACTION/UNSCHEDULED_ACTION为422；REVISION_CONFLICT/STATE_CONFLICT/RUNNING_CONFLICT/DUPLICATE_SCHEDULE/COMPLETION_EVIDENCE_MISSING/CONTRACT_UPGRADE_REQUIRED/SNAPSHOT_CONFLICT/FEATURE_DISABLED为409；NOT_FOUND为404，FORBIDDEN为403，RHYTHM_SCHEMA_INCOMPLETE为503。现有行动接口的返回格式本轮不变；新路由接入时再返回相应code/detail。

## 与现有 action-plans-p0-clarity 的重叠处理

依据：`openspec/changes/action-plans-p0-clarity/design.md` 的D2、D5、D7、D8。该草案的全部能力不能当作已交付。

| 重叠 | 当前日常节奏合同决议 |
|---|---|
| P0的business_date按开始日，旧实现按安排日 | 不改写任何旧business_date。新增activity_at/date单独代表确认时间/日期；跨午夜归确认日。两个视图须分别标注，不覆盖旧历史 |
| P0事实不可改；日常节奏要求后补总结 | 采用用户较新的日常节奏方案：分钟、日期、来源、完成/撤销关系继续不可因总结修改；note及next_step作为独立revision的附属总结元数据。R05必须保留初始note和后续版本，不能把旧note当空白覆盖。本轮没有改写执行数据；未来P0整合需保留这项明确例外 |
| content必须有来源确认回执 | 不能用全局read=true构造新的v2零分钟节奏事实。R04须补服务端来源证据；不支持回执的来源不开放此类事实；已有来源保存逻辑本轮不改变 |
| P0的check没有计时 | 低状态check只确认一个具体步骤，不能开始计时或完成完整待办；零分钟不推算时长。新partial写入留在R04 |
| P0未安排日期可以为null | 今日主任务请求必须有真实日期；引用未安排行动须先显式安排。不会把null填为今天 |
| P0错误码和唯一写入方 | 共用稳定错误含义，节奏合同另版本化。LightTick未支持时不回落Grow写第二份，不修改当前接管协议 |

这些规则防止R03–R05实现时重新定义已有行动完成语义。后续完整P0改造仍需执行其自己的接受用例，本轮没有勾选该OpenSpec清单。

## R02：迁移与初始化

代码：`server/rhythm/schema.py`、`store.py`；唯一现有运行代码改动在 `server/app.py:init_db()`。

业务表：

- `action_rhythm_preferences`：id、唯一effective_from、对象JSON data、正整数revision。
- `action_focus_days`：id、唯一local_date、对象JSON data、正整数revision；增加JSON内plan_id索引。
- `action_weekly_cards`：id、唯一周一week_start、对象JSON data、正整数revision。
- `action_rhythm_events`：id、唯一dedupe_key、白名单event_name、TIMESTAMPTZ occurred_at、对象JSON data；时间和事件+时间索引。
- `action_rhythm_enrollments`：id、唯一experiment_key、对象JSON data。

独立迁移元数据表 `action_rhythm_migrations(version, applied_at)`，当前schema版本为1。以后改变事件白名单等DDL须新增迁移，不能仅改常量期待已安装的约束自动改变。

初始化在现有账号schema的事务中执行，以current_schema派生的PostgreSQL事务咨询锁串行化并发初始化。迁移marker和DDL同时提交；任何失败同时回滚。不自动插入偏好、主任务、埋点或试验数据；不依赖action_plans旧两张表的存在性判定。

- 主人账号：应用lifespan启动调用init_db，完成迁移。
- 新账号：沿用prepare_user，首次认证访问时调用init_db；注册成功本身不生成业务数据。
- 既有普通账号：新进程首次认证访问同样调用init_db，即使已有action_plans/action_reviews，也会补迁移。
- 单独运行行动模块的fixture不自动启用节奏，可显式调用RhythmStore.initialize。
- 新表不加入旧全量state同步表；PUT /api/data不会清空它们。
- 发现高于当前版本的数据、无marker却已有同名节奏表、或marker存在但业务表缺失时拒绝继续，不静默重建、删除或降级。
- 本轮仅验证隔离数据库。没有重启实际服务，也没有执行业务库迁移；实际初始化将在之后正常启动/账号首次访问时发生。

R02只建立结构和基础数据库约束。计划引用、角色/状态、JSON业务字段、幂等业务操作和事件属性白名单由后续服务层实现，不将空表存在视为整套功能完成。

## 验证与回退

新增测试：`test_rhythm_contracts.py`、`test_rhythm_schema.py`、`test_rhythm_initialization.py`，通过仓库现有 `run_isolated_checks.py` 执行。测试实例由本轮单独initdb创建，绑定localhost随机端口；每项数据库用例另建临时schema，模型/GitHub由既有夹具模拟。

覆盖：严格字段和时区、保守事实判定、不修改输入、空库和旧库初始化、并发初始化、唯一键/周边界/JSON约束、失败DDL与marker同回滚、未知版本拒绝、主人启动与新旧账号首次访问、两账号相同ID隔离、旧全量HTTP保存不删五张表、默认无偏好/事件/试验和无节奏HTTP入口。

回退时移除init_db中的节奏初始化调用即可停用本阶段接入；保留新表和版本，不删表、不倒灌旧全库、不影响已有action数据。真实数据库备份/恢复及节奏JSON导出仍属于R18。

### 2026-10-21 运行结果

| 检查 | 结果 |
|---|---|
| 新增合同测试 | 13项通过 |
| 新增迁移/约束/并发测试 | 9项通过 |
| 新增真实应用初始化/账号/HTTP保存测试 | 4项通过 |
| 原行动计划/复盘/联动回归 `test_action*.py` | 31项通过 |
| 原日期安排 `test_daily_arrangements.py` | 7项通过 |
| 原state数据保存 `test_legacy_state.py` | 6项通过 |
| 原隔离防护 `test_isolation_boundary.py` | 6项通过 |
| 行动客户端和旧state客户端 | 两组Node检查通过；旧state脚本在server目录执行 |
| `run_isolated_checks.py --full` | 426项Python用例，2项失败、38项错误、0跳过；其中全部26项新增rhythm用例通过。Python失败使全量入口未启动后续JS阶段 |
| 隔离审计 | 上述运行的外部网络、真实数据库、工作区写入三个blocked计数均为0 |

完整回归当前不能作为全绿发布证据。范围外问题包括：旧课程用例未使用隔离PG夹具而读取空DATABASE_URL；PG路径执行SQLite PRAGMA；缺少pytest；浏览器用例旧定位超时；阅读搜集结果/请求次数断言不符。没有为通过回归而修改这些模块或放宽隔离。反馈初始化错误及账号浏览器旧定位错误均在禁用本轮节奏迁移的对照运行中重现：前者读取空DATABASE_URL，后者等待旧 `#todayTodos` 内的“添加”按钮超时（对照运行0跳过）。其余失败不在本轮逐项修复。

运行日志保留在本机：`/tmp/grow-rhythm-r01-r02-full.log`、`/tmp/grow-rhythm-action-regression.log`、`/tmp/grow-rhythm-arrangements-regression.log`、`/tmp/grow-rhythm-legacy-regression.log`、`/tmp/grow-rhythm-boundary-regression.log`、`/tmp/grow-rhythm-r01-contracts-final.log`。日志为临时验证证据，关键结果以本节记录为准。

禁用迁移的对照日志：`/tmp/grow-rhythm-existing-feedback-baseline.log`、`/tmp/grow-rhythm-existing-browser-baseline.log`。

本轮在已有运行文件中只替换init_db的四行连接管理并加入迁移调用。将此小块在内存中撤去后，app.py的SHA-256与开始快照一致，确认保留原先未提交内容。未执行stash/reset/清理工作树或合并提交，也未启动/重启业务服务。

验证结束后已停止本轮创建的临时PostgreSQL实例；业务数据库未连接、未迁移。日志与临时数据库目录留作本机故障核查，不作为应用运行依赖。

后续R19已关闭本节记录的全仓失败：2026-10-23完整隔离验收577项Python、23组JavaScript通过，0跳过，详见 [R19关闭记录](daily-rhythm-r19-followups.md)。本节前述失败保留为R01/R02阶段的历史诊断。
