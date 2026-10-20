# C2 来源证明与可靠投递验收

2026-10-21。沿用 Grow `codex/action-plans-p0`（基线 fc19fa0）和 Zook `feature/lighttick-p0-v2-contract-runtime`（基线71bb271）两个隔离实施工作树。本轮实施提交：Grow `110d36d`、Zook `f6a6363`。未改原生端，未合并、推送、部署或配对真实账号。

## 已实施

- Grow 文章/课程明确确认由既有来源 store 校验后，在私有 publication journal 的来源提交中一并保存事件与 outbox，不传正文、标题、笔记、评论或凭证。
- 已生效绑定的签名 source-context 保存 Zook 原计划日期/时区；source-confirmation 入库、同 ID/hash 重试、source-receipt 纯读和 source-reconcile 完成核对已贯通。
- Grow pending/delivered/completed/blocked 持久状态、租约、退避、应用启动后台扫描及同源手动重试已实现。跨进程恢复不依赖内存队列，不写本地行动事实。
- Zook owner 事务覆盖事件、来源登记、消费关系、行动 revision、零分钟完成事实及操作回执。运行中的会话保留，保存分钟后再核对；次日投递仍使用原确认日期和计划快照。
- 唯一 Zook OpenAPI、生成资产、接口文档和稳定错误码已同步。新配对、v2 全图接管、通用行动连接写入和公共消费者能力继续关闭。

## 最终结果

| 验证 | 结果 |
| --- | --- |
| Grow 原 P0 完整回归 | 139 pass、0 fail、0 skip，含 7 项真实 Chrome 验收 |
| Grow 新 C2 故障/回执/权限验收 | 12 pass、0 fail、0 skip（6 项 outbox/首用/门禁 + 文章/课程各3项真实 HTTP 复合验收） |
| Node 客户端回归 | 原行动客户端、P0 客户端两组通过 |
| Zook 全量回归 | 1500 pass、0 fail、0 skip |
| Zook C2 合同/运行时/连接写屏障 | 4 pass、0 fail、0 skip |
| Zook 原 PostgreSQL 事务/重启/并发回归 | 1 复合测试通过 |
| 合同 generate/check、OpenSpec strict、diff whitespace | 通过 |
| 隔离 OpenAPI lint | 0 error、212 warning，警告原样保留 |
| Zook source 行数门禁 | **未通过：8 个原有文件**；全部与53cf8d3基线逐字节一致，本轮未修改 |

原139项逐套结果在 [evidence/regression-results.json](evidence/regression-results.json)；C2 可重放入口为 `知行成长/server/tests/run_action_source_acceptance.py`，命令见 [设计与任务](source-delivery-design.md)。C2 双端日志/返回码在 [evidence/source-delivery/results.json](evidence/source-delivery/results.json)。Zook 全量、合同lint、PG和门禁原始日志在 `/Users/hao/Documents/project/Zook/.worktrees/lighttick-p0-v2-backend/docs/verification/lighttick-source-delivery/`。

## 故障恢复与边界证据

| 情形 | 核对结果 |
| --- | --- |
| 文章/课程来源成功，Zook 提交成功后 HTTP 断开 | Grow 保留同 event ID/payload；Zook 真实进程重启后，由全新 Grow Python 进程执行实际 worker sweep，次日找回回执，仍一条完成 |
| 来源保存/SQL 提交失败 | 来源结果、事件、outbox 共同回滚，不产生来源成功后的孤立完成 |
| Zook workspace 保存后 receipt 存储故障 | inbox、登记、事实、revision、消费关系全部回滚；重试原事件成功 |
| 来源确认时仍 running | 收件为 pending，保留 session；确认 12 分钟投入后用原事件核对，分钟12、完成1项 |
| 缓存上下文后离线确认 | 来源成功、pending 持久；恢复 HTTP 后完成且不改原日期 |
| 离线且没有有效 origin 证明 | 来源成功、blocked/ORIGIN_CONTEXT_REQUIRED；不制造历史快照，提示联网后重新明确确认；手动 retry 也不能绕过 |
| 伪造上下文、错绑定、外账号、停用会员、同ID改payload | 403/404/409稳定拒绝，无新增完成；不向桥接传私人来源内容 |
| 无origin、多日期/未安排/多请求竞争 | 只匹配确认日的一个合格行动；未来/未安排/过去无origin均保持原状，同事件并发仅一条事实 |
| 仅有已读位/笔记、非法时间/origin/owner/consumed_by字段、错误回执 | 不能生成有效证明或把不完整/错行动回执标为完成 |

GitHub 来源使用 HTTP 合成仓库；Grow→Zook 请求、签名、两端 PostgreSQL、Zook 进程重启和 Grow 独立进程 worker 均真实执行。正常完成的 fixture 只删除自己创建的随机 schema，不接触真实账号。

## 回归中修复的问题

1. 首次来源确认会初始化行动表，旧事务尚未提交时又打开 bridge/cache 连接，等待自己持有的 DDL 锁。已将初始化读事务提交后再准备证明；带 statement_timeout 的失败复现与修复后验收在 first-schema-red/green.log。早期完整回归因此超时，最终完整回归已通过。
2. 原文章浏览器验收用按钮中已有的“本次读完”文字当作成功等待，尚未等 POST 回执就结束计时，随后找不到手动核对按钮。已等待真实确认 POST，并断言有 source_event_id 且仍未完成，再结束 session；不放宽业务断言。失败日志 browser-inflight-confirmation-before-fix.log 保留，修复后7项 Chrome与139项完整回归通过。

## 剩余阻塞与未验证

- **C3 未实施**：v1/v2 全图快照、事件/消费/回执迁移、接管前后请求key路由、计数/hash/失败恢复与唯一写入方切换。不得借私有事件通道绕过新接管门禁。
- **C4/C5 未实施**：iOS/Android 共享行动消费者与真实双端联调；本轮没有修改原生仓库。
- **公共写入仍关闭**：connection_write_enabled、source_delivery_enabled、v2_import_enabled 为 false，content_receipts 为空；这是消费者放行状态。私有已绑定来源基础设施的隔离验收不代表可对真实账号开放全部P0。
- **仓库门禁未全绿**：Zook既有8个超长文件仍失败；合同lint有212条警告。没有根独立TS静态类型检查脚本，不能把执行测试称为全量typecheck。
- **生产/设备未验证**：真实GitHub外部网络恢复、真实账号接管、生产数据库升级、设备通知/日历、发布/回滚均未执行。本轮无P1/P2扩展。

因此 C2 可交付，总任务7.3仍未完成；连接写入、新配对、v2接管和原生放行继续阻塞。
