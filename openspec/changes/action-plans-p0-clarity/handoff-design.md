# C3 内部接管基础设施与切换协调

2026-10-21。继续 7.3；不修改原生端、不开放连接写入和新配对、不执行真实迁移，不扩展 P1/P2。

## 本轮可执行范围

- [x] 私有 snapshot_version=2 导出：plans、records、reviews、reports、operations、claims、content_sources、content_events 八类；4 MiB 上限、稳定排序与规范 JSON SHA-256。
- [x] 导出持有账号 actions-write advisory lock 和来源事件表 SHARE 锁，取得行动事实与来源发布的一致快照；不冻结账号。
- [x] 从当前服务端登录账号与租户 schema 核对事件归属；导出 owner 替换为来源账号，不发送租户 schema、source_result 或私人来源反馈。来源保存回执和原始数据仍保留 Grow。
- [x] Zook 内部只读预检：绑定/来源身份、对象和请求 key 唯一性、完整层级、引用、版本、日期、模式、运行会话唯一、完成指针、撤销、事件消费、目标容量和冲突。
- [x] 原子导入：账号事务锁；校验相同快照摘要、绑定和预检 target_version；行动/事实/旧回执/提醒 claim/事件归属转换/接管回执一起提交。
- [x] 丢失响应后重试：同 binding+hash 返回持久原回执，目标版本已前进仍可重放；不同快照禁止覆盖。失败回滚后保持 staged；不自行退回本地写入。
- [x] v1/v2 混合：保存原始历史行动、已结束事实和复盘/报告快照，不重算历史结论；允许已有归档上级的合法子行动关系；拒绝 generating 报告。
- [x] Grow 请求 key 路由：已存在本地回执优先；active 下未知 key 去 Zook；pending 下未知结果返回 503，不能声称未提交。远端错误/格式不合法不转为 found=false。
- [x] Grow 写入前能力检查：版本号之外检查 nullable_schedule、三种模式、actual_fact_dates、两类 content_receipts 和 connection_write_enabled=true；当前 Zook 仍返回关闭能力，不能放行。
- [x] 隔离 PostgreSQL 故障恢复、合同、门禁与回归；基础设施历史结果见 handoff-verification.md，切换协调最新结果见 handoff-cutover-verification.md。

## 切换协调与剩余门槛

- [x] 私有切换协调器：预检→重新核对源摘要→停止本地行动写入→原子封存不可变备份→远端提交→核对回执→启用唯一远端写入；公开入口仍阻止 P0 配对，pending v2 的恢复分派至同一协调器，公开 import 仍拒绝写入。
- [x] 跨切换来源确认屏障：来源发布持共享账号锁，stage 先取得排他来源锁、再取得行动写锁；等待在途发布及本地完成结束后重新核对摘要。pending 新确认在发布前返回可重试 503（submitted=false），调用方保留原请求；active 后使用原 key 恢复至 C2。崩溃遗留未完成 publication journal 时预检/stage 拒绝且不冻结，先由原来源请求恢复。
- [ ] 原生 C4/C5：DTO/API/状态和事实/离线队列/错误恢复/提醒消费者；按此前边界未修改。
- [ ] 真实账号、双端/设备通知/日历副本、生产迁移和发布验收。隔离 HTTP、Node 与 Python 跨进程恢复已覆盖，不等同于正式公开切换。

## 合同与可信边界

唯一合同为 Zook api-contracts/openapi/lighttick/api.yaml 中 LightTickActionHandoffSnapshot/Event。公共 grow-bridge 的 v2 import 输入形状关联该 schema，但运行时路由仍先拒绝写入。内部 ActionHandoffService 不由公共路由创建；只有已验证来源身份的受信任调用方才可使用，不提供浏览器事件库存写入口。

导出事件保留 request_key/request_hash、时间/安排上下文与 consumed_by。Zook 转换 owner_id 为当前已绑定的 Zook 用户，保留 handoff_source 审计来源。已消费事件须和唯一零分钟完成事实双向一致；未消费事件导入不自动完成，后续仍按正常完成规则核对。直接原生 API 响应不暴露来源库存。

旧 Grow action_operations 的 hash 编码与新 Zook 请求域不同，因此保留原成功结果供查询，并拒绝用旧 key 执行新的 Zook 写入；不尝试把不同 hash 域自动重算成新请求。__proto__/constructor 等合法旧 key 作为自有属性保存，不能变成对象原型或伪造查询命中。

## 私有协调状态与恢复规则

- local：preflight 保存 preview_id、binding_id、target_user_id、snapshot_hash、八类 source_counts、target_version；此时仍可本地写入。stage 等待在途来源完成后重导出；不一致拒绝且保持 local。
- pending：上述元数据加 snapshot_version=2、source_account_id 和完整不可变 backup，与本地写屏障同事务提交。网络失败、错误回执、远端已提交但丢响应、本地激活失败均保留 pending 与原备份，不回退本地双写。普通公开连接写入依旧关闭。
- active：仅在 binding/目标账号/hash/八类数量/目标版本/带时区导入时间全数核对后提交。已导入来源事件的 C2 outbox 与激活同事务落库；已消费事件为 completed，未消费事件为 delivered，只发 reconcile，不能冒充新来源确认。接管来源证明来自完整快照的身份与图校验，不补造浏览器 origin token。来源正文/私人反馈保留 Grow。
- 目标版本变化：返回 REVISION_CONFLICT / HANDOFF_TARGET_VERSION_CHANGED。revalidate 只预检已封存的同一备份、更新 target_version；不解冻、不改快照；并发修改时拒绝重写。目标来源库存、请求 key 或图冲突须核对处理，不能自动覆盖。
- 首次使用的 DDL 在来源发布前提交，避免独立发布连接等待未提交建表。锁由数据库事务管理，异常或进程断开后释放；已持久的 pending 屏障不会随锁释放而消失。

唯一合同新增 LightTickActionHandoffReceipt：预检 validated=true 与提交 imported_at 二选一；八类计数均为非负整数，target_version 为非负有界整数。生产 grow-bridge 没有 import-preflight 动作/路由；测试 HTTP fixture 同时要求本地随机 schema、测试 token 和真实 Grow HMAC，只用于隔离验收。
