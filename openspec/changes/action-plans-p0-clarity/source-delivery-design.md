# C2：来源证明、持久投递与完成核对

日期：2026-10-21。依赖 Grow `fc19fa0`、Zook `71bb271`。本轮只实施 C2，不标记总任务 7.3 完成。

## 授权与边界

- 复用已生效的 Grow→Zook 绑定、签名桥接和活跃注册会员身份；不提供新配对或 v2 导入。
- 通用行动命令继续由 `rejectConnectionWrite` 拒绝。新增的来源基础设施只能投递来源确认、读取回执、再次匹配已有事件，不能创建/编辑/改期/开始/结束行动。
- 原生端、P1/P2、生产配置、迁移和发布均不在本轮范围。公共 `connection_write_enabled/source_delivery_enabled/v2_import_enabled` 仍为 false，`content_receipts` 仍为空；这些是消费者放行开关，私有已绑定来源通道不代表客户端已可放行。
- Zook 唯一 OpenAPI 增补四类签名消息及生成资产；本文件只记录设计，不成为第二份可生成合同。

## 来源证明与行动上下文

来源事件仅由 Grow 的文章明确已读或课程明确 completed 入口生成。来源保存通过既有 store 的存在性、权限与内容校验后，私有 journal 在同一数据库提交中保存来源结果、事件和 outbox；浏览器不能提交 event ID、owner、已消费关系或 source_proof。传输只保留归一化 target、服务端 event ID、确认时刻、确认种类和可选 origin，不传来源正文、标题、笔记、评论、AI 设置或本地 schema。

带 origin 的确认先向 Zook 取得 `source-context`：Zook 对已有 v2 content 行动的来源、原计划日期、时区、revision、绑定及签发/到期时刻签发 HMAC 上下文。Grow 私有缓存该证明。确认可在签发后七日内发生，合法确认的投递可无限期延后。事件接收时同时检查证明快照与当前行动资格；未来、未安排、暂停/终态、来源变化或运行中不能被上下文绕过。上下文证明无需证明行动仍可执行，执行资格始终由当前 Zook 状态检查。

如果离线且没有有效缓存，来源照常保存，outbox 为 `blocked/ORIGIN_CONTEXT_REQUIRED`，不补造历史快照。恢复连接后须用新的明确确认取得证明；原事件保留审计，不能修改原 event ID/payload。无 origin 的事件只能匹配确认日的同来源行动；不使用旧已读位。

## 持久状态与恢复

Grow 增加独立私表 `action_source_contexts`、`action_source_outbox`，沿用来源事件表和 publication journal，不增加本地行动写入方。

| 状态 | 含义 | 后续 |
| --- | --- | --- |
| pending | 已提交来源与事件，Zook 收件未核实 | 原 payload + 原 event ID 重试；传输时间戳/nonce 每次新签 |
| delivered | Zook 已持久收件，完成仍待匹配 | 只发 source-reconcile，不再创建新确认 |
| completed | 回执账号/绑定/事件/hash/完成对象/事实 ID 全部核实 | 终态；后续重放读取原结果 |
| blocked | 身份、绑定、证明或不可变载荷冲突 | 保留来源与事件；需纠正接入或重新明确确认，禁止换 key 猜测重建 |

重试先提交短租约和 attempt/next_attempt；15×2^attempt 秒退避，最大一小时。工作进程中断后租约自然到期；应用启动立即按服务器账号表扫描，之后每 30 秒扫描，每账号每轮最多十条。同源手动重试最多三条；可重试身份/配置恢复后的阻塞，但不会放行缺证明、换绑定、事件冲突或伪造证明。请求内来源返回只尝试当前事件。

Zook 在 owner 锁和数据库事务内保存 inbox、来源登记、消费关系、行动 revision、零分钟 completion 和操作回执。相同 event ID + canonical payload hash 返回当前回执；不同 payload 返回 `409 SOURCE_EVENT_CONFLICT`。传输签名不能代替绑定/活跃会员检查。`source-receipt` 为纯读，`source-reconcile` 更新已有事件并原子更新完成回执。

运行冲突不结束 session。先保存实际分钟，再由原事件核对完成。完成事实使用确认时刻和证明里的计划日期/时区；次日投递不移动实际日期。完成项最多一个，分钟只来自 session。

## 本轮任务

- [x] C2.1 明确最小源证明、签名上下文、事件/回执形状和稳定错误码。
- [x] C2.2 Zook 已绑定来源收件、重复冲突、完成核对及事务回执。
- [x] C2.3 Grow 来源 journal 原子 outbox、持久租约/退避、启动恢复和只读状态/同源重试入口。
- [x] C2.4 真实 HTTP + 双端 PostgreSQL 故障恢复、合同、原 P0 回归及证据归档。
- [x] C2.5 同步缺口、操作说明与剩余阻塞。

## 验收命令

在 Grow 实施工作树中执行：

```sh
TEST_ZOOK_WORKTREE=/Users/hao/Documents/project/Zook/.worktrees/lighttick-p0-v2-backend \
TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=hao' \
PYTHONPATH=知行成长/server:知行成长/server/tests \
/Users/hao/Documents/grow/知行成长/.venv/bin/python 知行成长/server/tests/run_action_source_acceptance.py
```

只创建随机、测试拥有的 schema，结束后删除；不读取真实账号。GitHub 使用 HTTP 级合成仓库，真实 Zook 桥接、签名、PostgreSQL 和跨进程重启不模拟。Zook fixture 中只有 localhost、测试随机令牌保护的内部播种/故障控制接口，它们不被生产代码引用。

回归和最终剩余阻塞见 `source-delivery-verification.md`。
