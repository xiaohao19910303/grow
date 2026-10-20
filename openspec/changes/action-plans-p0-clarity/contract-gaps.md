# P0 连接合同缺口与最小改造清单

> 最新修复：8个工程行数失败已解除，见 [门禁修复验收](source-repair-verification.md)。C3接管与原生/生产验证边界保持原状。

> 2026-10-21 进度更新：Zook C0/C1 已在 `feature/lighttick-p0-v2-contract-runtime` 实施；本轮继续完成 C2 来源证明、签名事件收件、Grow 持久投递与核对，并完成隔离故障恢复验收。下文 2026-10-20 表格保留作缺口基线，不代表最新实现状态。当前仍阻塞的是 C3 接管/回执路由、C4 原生消费者、C5 真实双端与发布验收；普通连接写入、新配对与 v2 导入保持关闭。最新证据见 [C2 验证报告](source-delivery-verification.md)。

核对日期：2026-10-20。范围仅限本 P0 的共享行动语义、接管和原生消费者；本轮只修改 Grow，未修改 Zook/iOS/Android，未部署或配对真实账号。

## 证据基线

| 代码 | 检查版本与状态 | 观察 |
| --- | --- | --- |
| Grow | `codex/action-plans-p0`，本 change 的实施及收尾提交 | 本地 schema v2 与文章/课程来源确认已实现；连接端保持写屏障 |
| Zook | `0ae27a4a833de20b512651c67fc17a8ffba9fa3a`，检查时工作区干净 | 与上一轮检查的 `47d19fb` 相比仍没有 P0；当前明确拒绝非 time 模式，避免转换事实 |
| iOS | `30f551732ba9f689050525146fd4f63f0d7e9201` 加现有未提交改动 | 检查了当前工作区 API/DTO/队列；含进行中的 Timer/Coach 等改动，均未覆盖或修改 |
| Android | `19de8df06e3e3d606b0e85dcc56adc2ea775b48d` 加现有未提交改动 | 同样只读；没有共享 action-plans 的 DTO/API/队列命令 |

以上是本地源码证据，不代表线上版本。原生 `CONTRACT_SOURCE.md` 仍写旧 `320cee80...` 工作树来源，接入时必须更新为实际已验证的 Zook 提交，不能据此推定已对齐。

唯一公共合同源仍为 [Zook OpenAPI](/Users/hao/Documents/project/Zook/api-contracts/openapi/lighttick/api.yaml)。本文件是差异与任务清单，不是另一份可生成客户端的合同。

## 逐项缺口

| 编号 | Grow P0 必需语义 | 当前缺口与代码证据 | 最小改动 |
| --- | --- | --- | --- |
| G01 | 明确 `action_schema_version:2` 与 nullable/modes/receipts/date 能力；版本不符拒写 | Zook `action.projections.ts:listing` 无版本/能力；路由不消费 `X-Grow-Action-Schema`；`action.validation.ts:reject` 将409都折叠为版本冲突 | 在唯一合同与运行时定义能力、版本头和稳定领域错误；桥接请求也传递版本。能力只在全部语义实现且验收通过后声明 |
| G02 | day日期/at/reminder_at可空；time阈值有条件，check/content阈值null；estimated独立 | `ActionFields` 全部非空，`fields` 默认21:00，拒绝非time；OpenAPI `LightTickActionFields/Plan/Execution` 同样非空且 `additionalProperties:false` | 修改字段/输入验证/类型/生成资产；旧v1只读适配，不补造今日或新时间，不把check/content转time |
| G03 | 四状态、配置锁、三模式命令、累计确认和撤销审计 | `action.commands.ts:mutatePlan` 按单次分钟达标，缺reschedule/cancel/reopen/complete-time/reconcile-content；完成日行动不支持check；执行后仍可改配置 | 在现有事务和owner锁中实现P0矩阵；保留唯一running；session/completion/reversal及有效完成指针与回执共同提交 |
| G04 | 完成按行动去重；分钟仅session；实际/计划日期分开；旧快照保留 | `action.commands.ts` 将business_date设为计划日；`action.projections.ts:summary` 按completed记录数统计且将partial计minimum；review范围受计划日期约束 | 对齐P0字段、`recorded/reopened`、有效完成/撤销及日期；更新投影/复盘哈希/日历，历史v1不重写 |
| G05 | `/schedules` 归一化去重、null桶、改期冲突无副作用与来源可读性 | `ActionService.request` 无schedules；Zook仅检查target形状，不拥有Grow文章/课程资料 | 增加安排命令与相同身份校验；由已验证绑定的Grow提供最小来源可读性证明，拒绝客户端仅凭target任意关联；Zook不复制正文/私人笔记 |
| G06 | 来源成功后持久确认，断网/运行冲突可恢复；事件至多消费一次 | Zook workspace无source事件；Grow `confirm_source` 只在本地记事件，`content_completed` 在接管后受本地写屏障阻断；通用request桥接不能替代来源证据 | Grow来源事务保留确认与待投递记录；通过签名桥接投递最小来源事件，Zook验证绑定/账号/target/origin/确认时刻，入库、绑定、事实、命令回执原子提交；回放同event ID；重试不回滚来源 |
| G07 | v2接管保留所有事实、事件、消耗关系、旧key及提醒claim，失败不冻结或丢数据 | Grow `action_link.snapshot/counts` 仅6类对象、无events；Zook `ActionLinkService.import` 只收6类，要求reminder_at/阈值非空且不接受recorded/reopened；重建plan时丢v2元数据 | 引入明确快照版本/事件清单/计数/哈希，旧版接管拒绝v2；先校验全图再原子导入；中途失败保留原备份和唯一写入方；接管前核对key与接管后新key分开路由 |
| G08 | 原生安全读取/显示/执行P0且能恢复未知提交 | iOS `LightTickAPI.swift` 与 Android `LightTickApi.kt` 使用starter/tasks/today/goals；没有共享action-plans接口；两端pending结构没有P0操作/草稿上下文和明确账号字段 | 新增薄的共享行动API/模型/日行动界面；保留旧progressive模型边界。账号隔离草稿/pending，同key核对重试，409保留输入；版本不支持时关闭P0写入口 |

补充：Grow当前接管前的本地回执GET特例只查本地。接管启用前还须保证本地未命中的**接管后新请求**可以查Zook；不能把本地not found当作新key重建的依据。P0数据存在时的preview拦截也不能仅因Zook加了版本字段就移除。

## 最小实施顺序与完成标准

这些是连接P0所需的后续工作，本轮未执行，不自动扩展为P1/P2。

| 顺序 | 工作包与落点 | 依赖 | 可验收交付 |
| --- | --- | --- | --- |
| C0 | 在Zook唯一OpenAPI定义G01–G07；同步错误/头/事件/接管与fixture | 无 | 明确字段null/省略区别、记录类型/日期、操作枚举和capabilities；运行 `generate:public-contracts`、`check:api-contracts`、隔离合同lint，更新 `README_API.md` 和 `docs/public-lighttick-actions.md`；固定消费者SHA |
| C1 | Zook现有actions域、投影、PostgreSQL存储升级 | C0 | 以本地50例中API部分作双实现一致性用例；新增多会话累计、撤销、祖先阻断、nullable、来源去重、复盘/提醒回归；旧数据不重写。workspace目前为JSONB，不必另造第二套行动表，但持久形状及事件唯一性必须有版本和事务约束 |
| C2 | Zook签名来源事件收件与Grow可恢复投递 | C0、C1 | 来源提交后丢响应/服务重启/次日重试、来源失败回滚、running后核对、异账号/来源伪造、事件重复/多行动竞争均有真实HTTP+DB证据；只传来源身份和确认元数据，不传私人正文/笔记 |
| C3 | 双端快照与接管恢复、回执路由、能力检查 | C1、C2 | 包含v1/v2、未安排、running、完成撤销、已/未消费事件、旧key的新快照在隔离双端导入；校验计数与哈希；失败重试不多导入/不丢事实/不提前冻结；旧端仍拒绝写入 |
| C4 | iOS与Android共享行动消费者 | C0–C3 | 每端新增Action DTO/API、三模式/日期视图/必要操作、记录展示及账号隔离pending恢复；内容打开Grow来源的鉴权与origin上下文经过验证，不在原生凭本地已读位制造完成；不把共享行动冒充旧task或启用另一计时写入方 |
| C5 | 隔离真实双端合同与原生回归 | C3、C4 | Grow→Zook→两端读写与回执核对，断网/杀进程/旧revision/账号切换；旧客户端安全拒绝；跨午夜、撤销、提醒资格一致。设备通知/日历单独记录实机结果，未验证前不宣称支持 |

原生可复用的基础包括URLSession/HttpURLConnection认证、SwiftData/Room持久队列和冲突展示，但不能直接认定现有队列已支持共享行动。最小新增命令含create/schedules、edit/reschedule/cancel、pause/resume、start/finish、complete/complete-time/reopen、reconcile-content和只读requests/records；不加入模板、AI规划或长期重复。

原生文件落点：

- iOS：`LightTick/Domain/` 新增共享行动模型；`Data/LightTickAPI.swift` 或独立Action API adapter；`QueuedLightTickAPI.swift`、`SwiftDataPendingOperationStore.swift` 增加P0命令与账号隔离；新建必要行动视图并从当前导航接入，补 `LightTickTests` 解码/操作/恢复用例。
- Android：`domain/` 新增模型；`data/LightTickApi.kt` 或独立adapter、`QueuedLightTickApi.kt`、`PendingOperation.kt`、`RoomPendingOperationStore.kt`；`feature/` 新增对应视图与状态层，补JVM/仪器测试。
- 两端均更新 `CONTRACT_SOURCE.md`，从已验证的Zook SHA导出合同fixture，不维护另一份OpenAPI。

## 剩余阻塞与放行条件

| 阻塞 | 当前事实 | 解除条件 |
| --- | --- | --- |
| B1：服务合同与运行时缺口 | C0–C3未实现；不能安全导入v2或把来源完成同步到唯一写入方 | Zook/Grow桥接与数据库集成通过上述场景，生成合同/文档同步 |
| B2：原生消费者缺口 | 当前两端没有共享行动API接入；现有工作区另有未提交工作 | 在保留现有工作的独立客户端变更中实施C4，锁定合同SHA并通过平台测试 |
| B3：真实连接端验收 | 本轮没有隔离Zook实例和原生双端联调证据 | 执行C5并保存结果；本地模拟不能替代 |
| B4：设备与发布证据 | 没有真实系统通知权限/设备日历/生产迁移或部署验收 | 对声称支持的平台能力补实机证据；生产迁移/发布另行执行，不借本轮本地绿灯开启 |

因此 OpenSpec 7.3 保持未完成。Grow本地模式的回归/验收结果见 [verification.md](verification.md)；连接端的P0写入与带P0数据的新接管继续关闭。本轮没有为这些阻塞要求额外权限，也没有把“缺少实现”写成单纯的环境问题。
