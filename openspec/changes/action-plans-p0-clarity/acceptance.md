# P0 验收用例

状态：**规格已定义，以下业务用例全部待实施后执行；本文件不是测试通过报告。**

规范入口：[字段、状态和规则](design.md)、[规范要求](specs/action-plans-p0/spec.md)、[实施任务](tasks.md)。用例中的预期具有验收约束力。

## 1. 环境、样本和取证

- 使用隔离 PostgreSQL schema、合成账号 A/B、测试浏览器存储；不读取真实私人数据，不调用真实 AI、不配对真实 LightTick。
- 默认冻结时间为 `2026-10-19T12:00:00Z`，Asia/Shanghai 当地 `2026-10-19 20:00`。跨天用例单独推进时钟。这里的“今日/明日”是固定测试数据，不依赖实际执行当天。
- A 可读文章 `article-p0-a`，课程计划 `plan-p0` 的 lesson_no=1。另有归 B 的同标题内容，身份不同。
- 每例默认独立数据，所有行动/来源/事实 ID 由 fixture 生成；用符号 ArticleA、CourseA、Action1 引用，不拿名称当 ID。
- time 默认 T=20、minimum=5，check 不含来源/分钟，content 用具体来源；除专门测试外日行动无上级、无具体时间、不提醒。
- 每个行动写操作携带 `X-Grow-Action-Schema: 2`、独立 key 和最新 revision；幂等、并发、失联和版本头测试按用例指定复用。来源明确确认使用其原接口并记录 source_event_id。
- API 断言：HTTP、稳定错误 code、返回 ID/status/revision、服务端持久内容、有效完成项数、实际分钟、来源状态。只有页面提示不能证明写入成功。
- 浏览器断言：实际点击流程、字段可见性、刷新恢复、操作结果、焦点和键盘行为；保存当前运行截图。说明模拟失败点和是否真的走过服务端。
- 除表中明确指定，失败操作后断言行动字段、revision、事实数及来源保持不变。

## 2. 字段与创建（F）

| ID | Given / When | Then：必须满足的结果 | 层级 |
| --- | --- | --- | --- |
| F01 | 今日入口只填“整理一条建议”，默认 check，保存 | 200；一项 active/day；今日日期；at=null、reminder=false、target/target_minutes/minimum_minutes=null；零执行事实 | API+浏览器 |
| F02 | F01 改为暂不安排保存 | start/end/at/reminder_at=null；未安排可见，今日不可见；不是今天的隐藏副本 | API+浏览器 |
| F03 | title 为空、全空格、超过160；日期仅一端空或两端不同；非法日期；无效时区 | 每种 422/VALIDATION_ERROR；无新增数据；对应字段可读错误，输入保留 | API+浏览器 |
| F04 | time 模式输入 0、负数、1441、非整数分钟，或 minimum>T；合法关闭 minimum | 非法值全部422；关闭起步合法，minimum=null且无起步按钮；T=1时不得出现大于标准的起步 | API+浏览器 |
| F05 | content 无具体来源、通用 library/book、缺失来源、B的来源 | 无具体来源422；缺失或不可见具体引用404；不泄露B内容；未接入回执模块不提供content选择 | API+浏览器 |
| F06 | 从 ArticleA 加入明日，再主动切 time，最后切 check | 初始预填名称/来源/明日/content；time有标准分钟；check清理来源及条件分钟；隐藏字段不参与提交 | API+浏览器 |
| F07 | 开启提醒但不设日期或时间；然后设日期时间并保存 | 缺条件422且无暗填21:00；条件齐全合法；无提醒时设置时间不自动启用通知 | API+浏览器 |
| F08 | 创建成功但让列表刷新请求失败 | 只一项行动；显示已保存和刷新失败；可凭返回ID查看；成功草稿清除，不能引导再创建 | 浏览器 |
| F09 | 日行动关联合法/越界/异时区上级；未安排时关联有界上级 | 合法关系保存；后三种422，无偷偷修改父子日期或时区 | API |
| F10 | 从键盘打开、切换模式、触发校验、保存/关闭 | 首个可编辑字段获焦点；隐藏字段不进入Tab；错误可读；关闭返回原控件；无需鼠标可完成 | 浏览器 |

## 3. 状态与计时（T）

| ID | Given / When | Then：必须满足的结果 | 层级 |
| --- | --- | --- | --- |
| T01 | T=20；start→正常结束确认5；再次start→正常结束确认15 | 两条session，首条minimum，次条completed并有唯一complete效果；累计20分钟、有效完成1项、状态completed；来源仍未完成 | API+浏览器 |
| T02 | T=20；正常结束3分钟 | session partial，行动active、完成0、分钟3；关闭起步后正常结束5仍partial；界面区分本次与累计 | API |
| T03 | T=20；中断保存20分钟→complete-time | 中断后active/interrupted、分钟20/完成0；确认后新增零分钟completion、completed、分钟仍20/完成1；同key重试不增加事实 | API+浏览器 |
| T04 | start后墙钟推进120分钟，但确认本次实际3分钟；另测中断0分钟和正常结束0分钟 | 分别只计3分钟、中断0合法、正常结束0返回422；时间到点和刷新不完成 | API+浏览器 |
| T05 | start后刷新、重新注册服务；并发start另一行动 | 恢复同一个session ID；仅一个running；冲突409/RUNNING_CONFLICT，不能生成第二条会话 | API+浏览器 |
| T06 | running时编辑/改期/取消/暂停本行动；完成后再次start或编辑阈值 | 全部409；无事实丢失；已发生事实的模式/来源/阈值锁定；无事实的合法编辑可成功 | API |
| T07 | 上级paused；分别start、check complete、消费content事件；上级恢复后再试 | 三种执行均409；恢复不改子日期；存在运行后代时暂停/归档/人工完成上级409 | API |
| T08 | check start；content/time直接普通complete；time累计不足时complete-time | 模式非法返回422，状态冲突返回409；不创建任何无依据完成或会话 | API |

## 4. 内容完成与证据恢复（C）

每条必选内容路径用 ArticleA 和 CourseA 各执行一次；不以文章通过代替课程通过。

| ID | Given / When | Then：必须满足的结果 | 层级 |
| --- | --- | --- | --- |
| C01 | 今日content安排，来源明确确认完成 | 持久事件与一条零分钟completion；行动completed；完成1/分钟0；source_event_id指向当前账号有效事件 | API+浏览器 |
| C02 | content先start→finish确认20分钟，尚未确认内容；再确认内容 | 先recorded/active、完成0/分钟20；后completed、完成1/分钟20；会话和完成分开展示 | API+浏览器 |
| C03 | 来源早已read=true，在创建行动后只保存笔记、滚动、刷新，再核对 | 无新的明确事件；行动active、无完成事实；提示本次证据不足；笔记照常保存 | API+浏览器 |
| C04 | 今日、未来、过去、未安排各有同来源content安排；从无行动上下文确认今日来源 | 只完成今日适用安排；未来/过去/未安排不变；一个事件只能绑定一项行动 | API |
| C05 | 从过去安排打开来源并在今日再次明确确认 | 只完成明确origin_action_id；planned_date为原日，business_date为今日；不可借此完成同来源其他安排 | API+浏览器 |
| C06 | 来源事务成功、行动同步故意失败；随后刷新并核对同回执两次；再测延迟至次日核对 | 来源成功不回滚；待核对可见；核对只写一次完成；发生日期仍为原确认日；不存在事件时不得凭read=true补写；确认后改到未来/未安排的事项不能被延迟核对绕过限制 | API+浏览器 |
| C07 | content session运行中时来源确认成功；结束session确认8分钟，再核对 | 原session仍running且未被写0或静默结束；事件保留；结束后分钟8；核对完成1，分钟仍8 | API+浏览器 |
| C08 | 重放同key来源确认；提供B事件、其他来源事件、行动创建前事件、未来安排事件 | 同key返回同event ID；不合法事件拒绝或不匹配，无完成副作用；外账号404 | API |
| C09 | content完成后撤销来源已读，再新建另一日期安排 | 已完成行动及历史不撤销；新安排active，必须新明确事件，不能消费旧事件 | API |
| C10 | 来源确认事务故意失败，或支持模块无法持久留存回执 | 失败来源不产生完成事件/行动完成；不支持模块不开放content；文章/课程计划不可通过降级跳过必选验收 | API |

## 5. 勾选与撤销（K）

| ID | Given / When | Then：必须满足的结果 | 层级 |
| --- | --- | --- | --- |
| K01 | check完成→reopen→再次完成 | completed→active→completed；三条瞬时事实；完成数1→0→1、分钟始终0；撤销引用原事实且不删历史 | API+浏览器 |
| K02 | 两个不同key、相同revision并发complete；随后同成功key重试 | 一次200、一次409；重试返回原结果；有效完成与事实各仅一次 | API |
| K03 | time/content尝试reopen；已active的check尝试reopen | 非法模式422、非法状态409；原记录不变；撤销入口只对completed check展示 | API+浏览器 |

## 6. 安排、去重、日期和提醒（S）

| ID | Given / When | Then：必须满足的结果 | 层级 |
| --- | --- | --- | --- |
| S01 | 不同key并发schedules加入同来源、同日、同时区；再从其他入口加入 | 返回同plan ID与existing；只一项；通用create冲突409并提供查看原安排；同日已完成也复用，字段/revision不被覆盖 | API+浏览器 |
| S02 | 不同标题但同来源；相同标题但不同来源；不同日期/时区；两个同名time/check | 同来源同日期桶去重不依赖标题；其余独立创建；两项未安排同来源content也去重，不与有日期桶冲突 | API |
| S03 | 明日content改到今日；再改到已有同来源安排日期 | 首次保留ID并更新revision/日程；冲突409，日期/提醒/状态/revision/事实完全不变 | API+浏览器 |
| S04 | 有已确认部分投入、无running的active安排reschedule(date=null)，再设日期 | 状态不变、同ID、日期时间提醒清空；旧session快照不改；重新设日期不复活旧提醒 | API+浏览器 |
| S05 | active/paused安排cancel，然后相同来源同日重新加入 | 原archived，提醒失效；来源正文/笔记和旧session保留；新安排新ID；原archived拒绝写入 | API+浏览器 |
| S06 | 今日未完成行动推进到明日；另有昨日running和paused过期行动 | 未完成不自动顺延，进入待调整；running仅在正在执行优先展示；paused过期仍在待调整并标暂停 | API+浏览器 |
| S07 | 未安排行动直接start/complete；未来行动直接start；“安排今日并开始”第二步冲突 | 前两者422；两步冲突保留已保存日期，显示未开始而非整体成功/回滚；处理现有会话后可继续 | API+浏览器 |
| S08 | 有日期无at，或撤销日期/暂停/完成/取消/上级阻断；请求claim或calendar | 不投递；无at不能生成21:00或假日历；有at但reminder=false可导出无alarm；保留免打扰/设备去重回归 | API+浏览器 |

## 7. 事实日期、统计和旧数据（A）

| ID | Given / When | Then：必须满足的结果 | 层级 |
| --- | --- | --- | --- |
| A01 | 19日安排，20日开始补做并正常结束20分钟 | planned_date=19日，business_date=20日；19日计划项仍可追溯；20日记录/成长及复盘显示投入20/完成1，不受原计划范围阻止 | API+浏览器 |
| A02 | 上海19日23:58开始，20日00:10结束，确认12分钟；content于20日另行确认 | session分钟归19日；content完成归20日；不估算按分钟拆分，不把两事实都算一次完成 | API |
| A03 | 周→日两段session达到20分钟；check完成后撤销；保存过旧复盘 | 周完成按日行动去重；分钟仅session；check撤销重算实时完成；旧复盘/AI内容和统计快照不变 | API |
| A04 | 读缺mode/record_kind等字段的v1样本；修改设备时区/改期；再生成预览 | 原完成结论和分钟保持；旧business_date及legacy_planned标识保持；新事实实际日期口径明确；新预览哈希按事实变化失效 | API+浏览器 |
| A05 | 编辑有事实行动的mode/target/阈值，或复制新行动 | 编辑409且旧事实不变；复制只带配置，不带完成状态/事实/旧key；内容去重仍有效 | API |

## 8. 草稿、并发、隔离和合同（R）

| ID | Given / When | Then：必须满足的结果 | 层级 |
| --- | --- | --- | --- |
| R01 | 通用今日草稿→文章明日草稿→返回；同上下文再新建一份 | 两来源/日期上下文互不覆盖；多份可按标题/日期/保存时间选择；编辑草稿按行动隔离 | 客户端+浏览器 |
| R02 | A保存草稿/pending后切B再切回A | B看不到A内容、来源、pending或执行；切回A可恢复，存储异常也不抛出导致页面不可用 | 客户端+浏览器 |
| R03 | 创建已提交但丢响应；刷新→查原key；另测确实未提交后原key重试 | 前者找到同一plan后只清对应草稿/pending；后者原key只产生一项；同key改payload409；其他草稿保留 | API+客户端+浏览器 |
| R04 | pending结果未知时修改表单，查询暂时not found；或两个编辑器旧revision提交 | 原pending不可变，新输入保留；not found不等于可放弃，不自动换key重建，原key重试确定结果；旧revision409并提供核对恢复，不覆盖服务端新值 | API+客户端+浏览器 |
| R05 | A引用B行动/来源/事件/key回执，或缺同源头/跨站写入 | 外账号资源404，回执无结果；同源保护403；无任何跨账号数据和部分写入 | API |
| R06 | 接管端无P0能力、写版本头缺失或不支持；另测接管开始后读取已有本地key回执 | 不支持能力的入口关闭，版本不符409/CONTRACT_UPGRADE_REQUIRED；草稿保留、不本地双写；允许纯读本地旧回执，不绕过写屏障；纯读不要求版本头 | API+合同集成 |

## 9. 需求追踪

| 规范 Requirement | 用例 |
| --- | --- |
| P0 field contract and compatibility | F01–F05、F07、F09、A04–A05 |
| Contextual quick creation | F01–F02、F06、F08、F10 |
| Separate action and session state | T05–T08、K03、S05–S07 |
| Explicit cumulative time completion | T01–T04 |
| Content completion requires durable scoped evidence | C01–C10 |
| Check completion and audited reversal | K01–K03 |
| Shared schedule deduplication and adjustment | S01–S05 |
| Explicit date views and safe execution | S06–S07、A01–A02 |
| Actual facts and distinct aggregation | A01–A05、T01、C02、K01 |
| Draft isolation and uncertain request recovery | R01–R04 |
| Honest reminder eligibility | F07、S08 |
| Tenant boundary transactional mutations and contract gate | R05–R06、S01、T05、K02 |

## 10. 执行顺序与完成门槛

1. 先执行 API/数据用例，固定字段、状态与完成事实，再接客户端和浏览器；合同集成可在Zook能力实现后执行，但不能以未测合同开启连接账号写入。
2. 在当前已有行动计划、复盘、日安排、来源完成和客户端测试上扩展；不直接把表内文字复制成只测实现细节的测试。
3. 每例记录环境/提交版本、执行时间、实际结果、证据、失败处理；未执行标未执行，不能标通过。表中范围 F10+T8+C10+K3+S8+A5+R6 共 **50** 个用例。
4. 本地未连接模式上线必须通过除R06连接端场景以外全部必选用例；R06版本头和本地回执写屏障部分仍需隔离模拟验证。连接模式开放必须额外通过真实隔离双端合同验证。
5. 既有年/月/周层级、同周批量、幂等、来源笔记与完成、复盘快照、AI同意预览、提醒免打扰和账号隔离回归必须通过。不得因P0变更删除这些能力。
6. 浏览器至少覆盖：文章加入明日→改到今日→确认；课程同路径；time分段累计；check撤销；未安排→今日；过期待调整；草稿与失联恢复。记录当前截图、键盘检查和未验证的设备通知边界。

## 11. 规格阶段检查

仅检查 OpenSpec 格式、引用文件存在、需求到用例覆盖和任务未误标完成；不运行上述业务用例，不把创建这些规格称为已实现 P0。
