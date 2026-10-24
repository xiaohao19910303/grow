# 剩余 P0 推进：C3 内部基础设施验收

> 历史阶段报告。C3 协调与来源屏障的后续实现、实际 HTTP/进程恢复和最新阻塞见 [handoff-cutover-verification.md](handoff-cutover-verification.md)。下文“未实施”描述保留当时状态。

2026-10-21。Grow 基线 e9c81f2，Zook 基线 3db81b9，在原隔离工作树继续实施。Zook 实现提交 `e2ae870`，证据收尾 `3af3048`。范围为 [handoff-design.md](handoff-design.md)，7.3 总任务仍未完成。

## 本轮完成

- 完整八类 v2 快照导出、全图只读预检和原子导入；v1 原始历史、nullable、运行会话、完成/撤销、来源事件及消费、操作回执和提醒 claim 保留。
- 摘要/账号/绑定/目标版本/容量与合并冲突检查；重复提交、回执存储失败回滚和重启后恢复，不把失败退回本地双写。
- 修复接管后新请求 key 一直查询本地的缺陷；旧 key 仍可本地确认，pending 未知结果返回 503，active 未知 key 去 Zook，非法远端回执不返回假未提交。
- 写入前能力检查补齐；版本号 2 不足以放行，当前公开连接写入仍关闭。
- 修复首次加载创建竞态：快速表单等待首个行动数据/能力请求完成；新增用例持住初始 GET，先点击创建，确认返回前没有表单、返回后焦点进入名称字段。
- Zook 明确 never 返回的拒绝函数与正确的公共类型来源，消除行动领域及其依赖的 8 条严格类型诊断；新增 `npm run check:lighttick-actions-types`（12 个领域源文件及传递依赖，使用后台锁定的 TypeScript 开发依赖）。不声称全后端类型检查通过。

## 验证

| 检查 | 本轮结果 |
| --- | --- |
| Grow 全量本地回归 | **140 项通过，0失败、0跳过**；含 8 项真实 Chrome，原基线139+新增首次加载用例1 |
| 两组 Node 客户端验收 | 通过 |
| Grow→Zook 来源可靠投递 | 12 项通过，0失败、0跳过 |
| Zook 来源合同/运行时/公开门禁 | 4 项通过 |
| 新增 C3 Grow 复合验收 | 4 项通过；包括真实 Grow PostgreSQL 导出→Zook 独立 PostgreSQL 导入、故障回滚、并发与新服务实例重放 |
| 最后一次服务端重点复核 | 19 项通过（C3四项+原P0十五项），含损坏回执与非法能力响应；grow-last-focused.log |
| 新增 C3 Zook 复合单测 | 6 项通过；混合历史、非法全图、事件归属/消费、回执 key/原型边界等 |
| Zook 全量回归 | 1506 项通过；最终日志见 Zook 对应报告 |
| PostgreSQL 原有集成 | BodyLog、小组成长、LightTick actions 3 组通过 |
| OpenAPI 生成/check/合同专项 | 通过；lint 0 error、197 条既有 warning，无新增警告 |
| source 行数门禁 | 669 文件通过，未调整阈值 |
| 行动领域严格类型、后台类型检查和构建 | 通过；全后端既有类型债未全量治理 |

证据位于 [evidence/handoff-v2/results.json](evidence/handoff-v2/results.json)，保留完整本地回归和浏览器截图。Zook 合同、全量回归和工程检查日志在其 `docs/verification/lighttick-handoff-v2`。

首轮完整回归确实失败：首个浏览器用例暴露初始化竞态，修复后新增确定性用例。一次并行负载下保存后关闭对话框的限时断言也超时；测试改为先等实际 POST 200，再判断关闭，不放宽超时或跳过用例；最终独立浏览器 8 项及完整140项均通过。首轮及中间失败日志保留在 before-fix，不把失败覆盖为从未发生。无法仅凭重跑证明所有机器都不存在负载相关超时。

C3 跨仓验证通过内部领域服务完成；没有开放 HTTP import，也没有测试真实账号切换或真实 Node 进程重启。重新创建服务/仓储实例验证持久回执；C2 的实际 HTTP/进程重启证据另保留，不能混称本轮正式接管端到端已通过。

## 剩余，不能宣称全部 P0 完成

1. **C3 正式切换协调与来源确认屏障**：事务内导出一致性已验证，但导出返回后仍可有新来源确认。尚未实现/验收跨切换的排队/暂停、源摘要再次核对、封存备份、冻结和切换恢复的完整协调。公开配对/v2 import 继续关闭。
2. **C4/C5 原生与双端**：iOS/Android DTO、操作/事实、离线队列、能力和错误恢复、提醒消费者、真实双端联调仍待实施；按此前限制未修改原生端。
3. **真实账号/设备及生产**：通知、日历副本、跨进程正式切换、生产迁移/发布未验证，未执行合并、推送或部署。
4. **历史工程债**：全合同197条警告仍存在；行动领域有正式严格类型检查，但全后端未建立并跑通统一严格类型门禁。前报告的709诊断不是本轮剩余数量，未再次全后端统计，不按本轮修复8条机械相减。

下一步应先完成 C3 切换协调/来源屏障的隔离故障验收，再在明确扩展原生端范围后实施 C4/C5；公开能力仍须等全部消费者验证通过后另行开放。

## 复现 C3 专项

从 Grow 隔离工作树执行（依赖本地 PostgreSQL 与 Zook 工作树锁定依赖；只创建和清理随机测试 schema）：

```sh
TEST_ZOOK_WORKTREE=/Users/hao/Documents/project/Zook/.worktrees/lighttick-p0-v2-backend \
TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=hao' \
LIGHTTICK_ACTION_TEST_DATABASE_URL='postgresql://hao@127.0.0.1/postgres' \
PYTHONPATH=知行成长/server:知行成长/server/tests \
/Users/hao/Documents/grow/知行成长/.venv/bin/python -m unittest test_action_handoff -v
```

Zook 工作树执行 `npm run check:lighttick-actions-types`、`node --experimental-transform-types --test test/unit/lighttick-action-handoff-v2.test.ts`。类型检查使用现有后台开发依赖，缺失时先按项目约定安装后台锁定依赖；不增加生产运行时对维护目录的依赖。
