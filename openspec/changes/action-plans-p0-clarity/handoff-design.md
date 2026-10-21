# C3 内部接管基础设施与剩余切换门槛

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
- [x] 隔离 PostgreSQL 故障恢复、合同、门禁与回归；结果见 handoff-verification.md。

## 仍未完成，不能以内部导入通过代替

- [ ] 正式切换协调器：预检→重新核对源摘要→停止本地行动写入→原子封存不可变备份→远端提交→核对回执→启用唯一远端写入；公开入口仍阻止 P0 配对，旧 import 路径继续拒绝 v2。
- [ ] 跨切换时点的来源确认屏障：已在途的来源发布、快照之后的新确认、pending 期间确认必须有明确的暂停/可靠排队与恢复策略，不能导出后继续本地消费并声称完整接管。当前 snapshot_v2 只保证导出事务内的一致性；函数返回后源仍可继续变化。
- [ ] 原生 C4/C5：DTO/API/状态和事实/离线队列/错误恢复/提醒消费者；按此前边界未修改。
- [ ] 真实账号、跨进程切换、双端/设备通知/日历副本、生产迁移和发布验收。

## 合同与可信边界

唯一合同为 Zook api-contracts/openapi/lighttick/api.yaml 中 LightTickActionHandoffSnapshot/Event。公共 grow-bridge 的 v2 import 输入形状关联该 schema，但运行时路由仍先拒绝写入。内部 ActionHandoffService 不由公共路由创建；只有已验证来源身份的受信任调用方才可使用，不提供浏览器事件库存写入口。

导出事件保留 request_key/request_hash、时间/安排上下文与 consumed_by。Zook 转换 owner_id 为当前已绑定的 Zook 用户，保留 handoff_source 审计来源。已消费事件须和唯一零分钟完成事实双向一致；未消费事件导入不自动完成，后续仍按正常完成规则核对。直接原生 API 响应不暴露来源库存。

旧 Grow action_operations 的 hash 编码与新 Zook 请求域不同，因此保留原成功结果供查询，并拒绝用旧 key 执行新的 Zook 写入；不尝试把不同 hash 域自动重算成新请求。__proto__/constructor 等合法旧 key 作为自有属性保存，不能变成对象原型或伪造查询命中。
