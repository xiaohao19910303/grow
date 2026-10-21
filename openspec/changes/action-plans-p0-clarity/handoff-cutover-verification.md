# C3 切换协调与来源确认屏障验收

2026-10-22（延续 10-21 夜间实施）。基线 Grow `ec8ca3a`、Zook `3af3048`，在既有隔离工作树继续。仅实施 C3 私有协调和 C2 衔接；没有修改原生端，没有开放新配对、公开 import 或普通连接写入，没有 P1/P2、真实账号迁移、推送、合并或部署。OpenSpec 仍为 **25/26，7.3 未完成**。

## 完成结果

Grow 私有协调器实现 local → pending → active。预检记录 preview_id、绑定/目标身份、八类数量、hash 和 target_version；stage 先等待共享来源发布锁释放，再取得行动写锁，重新导出核对。摘要变化时保持 local；核对通过才将完整不可变 backup 和 pending 写屏障同事务提交。这样不会遗漏在途来源，也不会在等待来源时反向持有行动锁造成死锁。

pending 新来源确认在发布前返回 503 SOURCE_DELIVERY_UNAVAILABLE（retryable=true、submitted=false）；调用方保留原 key，恢复 active 后再提交。崩溃留下未结束的 learning/cloud publication 或 reading export journal 时，以 409 STATE_CONFLICT / SOURCE_PUBLICATION_PENDING 阻止预检与冻结，原来源请求负责恢复，不能绕过日志直接接管。

网络失败、远端已提交后丢响应、错误回执或本地激活失败均保持 pending 和原备份。同 hash/binding 重试远端返回持久原回执；本地只在身份、hash、八类数量、target_version 和带时区 imported_at 全部核对后激活。预检 validated 和 imported_at 互斥，未知字段、错误类型及超长身份拒绝。目标版本变化以 REVISION_CONFLICT / HANDOFF_TARGET_VERSION_CHANGED 拒绝；revalidate 只更新同一冻结备份的 target_version，不解冻、不替换快照。

Zook 导入时将来源事件、C2 来源操作回执、全图和接管回执同事务提交。Grow 将对应 C2 outbox 和本地 active 同事务落库；已消费事件保持 completed，未消费事件为 delivered，之后仅 source-reconcile。running 先结算真实分钟，再核对唯一完成事实。迁移证明来自已核验身份的完整快照，不补造浏览器 origin token，不把来源正文或私人反馈发给 Zook。

唯一 OpenAPI 新增 LightTickActionHandoffReceipt 并同步生成资产；不新增生产 import-preflight 动作。实际跨仓 HTTP 验证只用测试 fixture：localhost、随机 PG schema、测试 token 与真实 Grow HMAC；它不是可用的生产接管端点。

## 最终验证

| 检查 | 最终结果 | 证据 |
| --- | --- | --- |
| C3 切换故障恢复 | **18通过 / 0失败 / 0跳过**，文章与课程各9个复合场景 | evidence/handoff-cutover/acceptance/grow-cutover-recovery.log |
| Grow 八类快照与请求路由 | **4通过 / 0失败 / 0跳过** | acceptance/grow-snapshot-and-routing.log |
| Zook C3/P0合同、公开门禁和生成专项 | **15通过 / 0失败 / 0跳过** | acceptance/zook-contracts-and-gates.log |
| C2 来源可靠投递回归 | **Grow12 + Zook4通过** | source-recovery/results.json |
| Grow 全量本地回归 | **140通过 / 0失败 / 0跳过**，含8项真实Chrome | regression/regression-results.json 与截图 |
| 两组 Node 客户端 | 通过 | client-plans.log、client-p0.log |
| Zook 完整 unit 回归 | **1508通过 / 0失败 / 0跳过** | Zook unit-full.log |
| 原有 PostgreSQL 集成 | **3通过 / 0失败 / 0跳过**：BodyLog、成长、LightTick actions | Zook postgres.log |
| 合同 generate / check / lint | 通过；**0 error，197条既有warning** | Zook contract-*.log |
| 行动领域严格类型 | 通过；13个领域源文件及传递依赖 | Zook actions-types.log |
| 行数门禁 | **670文件通过**，阈值和豁免未改 | Zook line-count.log |
| 后台 typecheck / build | 通过 | Zook admin-*.log |
| OpenSpec strict validate | 通过 | openspec.log |

[机器可读汇总](evidence/handoff-cutover/results.json)；Zook 日志位于其 `docs/verification/lighttick-handoff-cutover`。上述检查有重叠，不把各行相加当作独立用例总数。PostgreSQL 的三组既有集成不代表全部产品的所有数据库测试或线上验收。

### 故障场景矩阵（每项均覆盖文章与课程）

| 场景 | 已验证结果 |
| --- | --- |
| 导入提交后丢响应，Node与Python实际进程重启 | 同一备份重试激活；单事件、单完成事实；pending来源不发布，active后原key可重试 |
| 预检后新增来源确认；远端接管回执写失败 | 摘要变化不冻结；远端全图/回执共同回滚；可恢复 |
| 在途来源发布与stage竞争 | PG锁等待可观察，发布及本地完成先结束，stage重核摘要且无死锁 |
| 未消费事件接管后遇running | C2持久队列保留事件，先结算12分钟，再恰好完成一次，本地冻结事实不改写 |
| 本地stage/激活存储失败 | stage事务失败仍local；激活失败仍pending，outbox与状态共同回滚 |
| 目标版本在stage后变化 | 拒绝并保持屏障；同一备份重预检后合并成功 |
| 错误阶段/字段/类型回执与损坏备份 | 不激活；损坏备份在传输前拒绝 |
| 模拟来源发布崩溃遗留journal | 阻止冻结；原请求恢复后事件/事实只导入一次 |
| 两个finish并发与公开写入 | 单次本地激活、单outbox、单目标事实；pending/active公开写入均拒绝 |

## 失败记录与修复

- 文章并发测试首次 patch 到 reader.publish，实际发布发生在 reader.documents.publish；修正测试钩子并直接观察 PG 等待锁。保留失败日志，不当作产品成功证据。
- 回执合同复核新增混合阶段/未知字段用例，先复现 ActionError 未抛出，再补齐 Grow 校验。最终整套 C3 18+4+15全部重跑通过；证据 `before-fix/receipt-shape-before-fix.log`。
- 低磁盘空间期间的前次完整回归未取得有效成功汇总，保留中断日志；涉及的7项单独诊断通过，空间恢复后的最终完整1508项通过。不能仅凭重跑断言前次所有失败都由磁盘引起，也没有把中断视作通过。

## 剩余阻塞与边界

1. **C4/C5原生消费者与真实双端**：iOS/Android DTO/API、三模式操作/事实、离线队列、账号隔离、错误恢复、提醒消费者和真实联调均待实施。按明确范围没有修改，7.3不能勾选。
2. **公开放行与真实账号**：私有协调器尚无生产预检/stage入口，默认桥接仍拒绝接管；没有真实账号迁移或线上切换验收。当前 connection_write_enabled=false，不能把内部 active 或测试端点当作公开可写。须全部消费者验收及另行放行后才能开放。
3. **设备和生产证据**：通知/日历副本、实机权限、生产数据/发布/运维切换尚未验证。隔离HTTP及双方进程重启已验证，不能替代这些证据。
4. **拒绝后的处理**：未结束来源journal须先以原请求恢复；目标来源库存、请求编号或图冲突须核对处理；本轮没有自动覆盖或强制迁移工具。
5. **历史工程债**：197条既有合同warning未清理；全后端统一严格类型门禁未建立并跑通，只能宣称本轮行动领域和后台类型检查通过。旧709条诊断未全量重测，不能机械减去修复项推算剩余量。

本轮授权范围内的 C3 收尾已通过；以上不作为环境借口继续打开原生或公开写入范围。

## 复现

Grow隔离工作树执行（仅随机测试schema，依赖本地PostgreSQL、Python环境及Zook锁定依赖）：

```sh
ACTION_HANDOFF_EVIDENCE_DIR=/tmp/c3-recheck \
TEST_ZOOK_WORKTREE=/Users/hao/Documents/project/Zook/.worktrees/lighttick-p0-v2-backend \
TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=hao' \
LIGHTTICK_ACTION_TEST_DATABASE_URL='postgresql://hao@127.0.0.1/postgres' \
PYTHONPATH=知行成长/server:知行成长/server/tests \
/Users/hao/Documents/grow/知行成长/.venv/bin/python -u 知行成长/server/tests/run_action_handoff_acceptance.py
```

同环境另设 `ACTION_SOURCE_EVIDENCE_DIR=/tmp/c3-source-recheck`，执行 `run_action_source_acceptance.py` 验证C2。Grow完整回归使用 `run_action_p0_regression.py`，另设 `ACTION_P0_EVIDENCE_DIR=/tmp/c3-grow-recheck`、`RUN_GITHUB_BROWSER=1`。两组客户端用 `node 知行成长/server/tests/test_action_plan_client.cjs` 和 `test_action_p0_client.cjs`。

Zook执行 `npm test`、`npm run generate:public-contracts`、`npm run check:api-contracts`、`npm run lint:api-contracts`、`npm run check:lighttick-actions-types`、`npm run check:line-count`、`npm run admin:typecheck`、`npm run admin:build`。合同lint使用 `api-contracts` 独立锁定依赖。三组PG集成显式设置 `BODYLOG_TEST_DATABASE_URL` 与 `LIGHTTICK_ACTION_TEST_DATABASE_URL` 为 `postgresql://hao@127.0.0.1/postgres`，运行 `node --experimental-transform-types --test test/integration/bodylog-postgres.test.ts test/integration/bodylog-growth.postgres.test.ts test/integration/lighttick-actions-postgres.test.ts`。这些测试自己创建并清理随机schema；不要据此对任意真实数据库执行其他迁移测试。
