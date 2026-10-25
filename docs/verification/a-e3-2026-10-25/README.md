# A 文档收尾与 E3 稳定 ID 专项验收

日期：2026-10-25。范围：A1–A3 与 E3。代码和验收结果仅适用于本轮受测文件，不表示已发布或真实业务库已完成迁移。

实施基线：`0c3e46a`；源码修复提交：`60923b2`。测试运行于同一份修复内容，提交后再次比对受测文件哈希一致。

## 变更范围

- 在既有文档修订基础上完成四份入口文档的交叉链接与口径收尾：FastAPI + PostgreSQL、按账号 schema 隔离、GitHub 正式内容、浏览器按账号配置 AI、不设每日必学或补打卡要求。SQLite 只保留历史及离线迁移说明。
- Dashboard、AI 辅助分析、知识图谱及习惯追踪已有实现入口，区分入口存在、本轮专项通过和线上发布状态，不再作为未来才建设的能力。
- 补齐稳定 ID 查找、关联节点查找、幂等导入；保留数字 ID 和旧连线。重复导入或更新内容哈希保持身份，同一文件的不同节点可分别导入。
- 启动及账号初始化时增量升级，覆盖旧迁移已记账的账号；数据库默认生成 UUID，避免旧扫描／导入产生无 ID 节点。并发导入与 Markdown 扫描共用当前 schema 的写锁。
- 离线脚本支持显式 `--schema`、只读 `--verify` 与失败退出码；验证只检查当前所选 schema。重复已有稳定 ID 会使升级回滚，不自动合并或覆盖原记录。

接口与身份边界见[知识节点稳定 ID 说明](../../../知行成长/docs/knowledge-stable-ids.md)，事项状态见[待办清单](../../../知行成长/设计审查/2026-10-24-全系统评审/待办改造清单.md)。

## 验收结果

结论：**A1–A3 和 E3 的本地实现及专项验收通过。65 项受影响模块测试通过，0 失败、0 跳过；另有 4 次真实离线命令检查通过。**

| 验收组 | 用例数 | 结果 |
|---|---:|---|
| 稳定 ID 专项 | 18 | 查询、双向关联及排序去重、并发导入、内容更新、旧节点保留、扫描重跑、迁移回滚、只读核验、输入及故障处理通过 |
| 旧云端 schema 迁移 | 4 | 旧节点、关系和原始记录的迁移回归通过 |
| 旧 PostgreSQL 布局升级 | 4 | 重复初始化、原记录及兼容路径通过 |
| 登录账号集成 | 19 | 包含本轮新增的知识节点跨账号隔离、匿名拒绝及同源写入保护；原账号与课程路径回归通过 |
| 搜索与时间线 | 12 | 新增知识字段及迁移未破坏搜索与时间线 |
| 成长统计 | 8 | 原学习完成、活动统计和时长口径回归通过 |
| 合计 | **65** | **全部通过，无跳过** |

- 先以测试复现原接口 500 与缺失迁移列，再实施修复：[失败复现](evidence/red.log)。最终结果以[回归汇总](evidence/results.json)和逐模块日志为准；早期 `green.log` 仅为首轮 14 项通过的中间结果。
- 实际启动迁移 CLI 子进程：未迁移时 `--verify` 返回 1，迁移返回 0，再次只读验证返回 0，重复迁移返回 0；数字及稳定 ID 均未变化。见[命令验收](evidence/cli-smoke.json)。
- 检查四份入口文档、新说明、清单及本报告中的 71 个本地文件链接，均存在，见[链接检查](evidence/doc-links.json)。历史报告按各自日期保留，不作为本次源码验收。
- 8 份受测 Python 源码／测试通过 AST 解析，`git diff --check` 通过；受测文件 SHA-256、代码基线与测试环境见[元数据](evidence/metadata.json)。本轮沿用现有依赖，测试仅有既存 Starlette/httpx 弃用提示，无新增依赖。
- 每个测试进程使用现有隔离 runner：外部网络、真实数据库访问和工作区写入拦截计数均为 0。测试使用一次性 localhost PostgreSQL 15；专用实例的结束状态见[清理记录](evidence/test-database-cleanup.json)。

## 复现方式

按[部署手册](../../deployment/standalone-web.md#隔离验收)创建一次性 localhost PostgreSQL，配置 `TEST_POSTGRES_DSN` 后运行现有隔离 runner。解释器使用项目已有 `知行成长/.venv/bin/python`，也可替换为已安装测试依赖的环境。

```sh
TEST_POSTGRES_DSN='host=127.0.0.1 port=专用端口 user=测试角色 dbname=postgres' \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
知行成长/.venv/bin/python -B 知行成长/server/tests/run_web_regression.py \
  --match 'test_(knowledge_stable_ids|legacy_cloud_schema|postgres_legacy_migration|search_timeline|growth_statistics)\.py$' \
  --output /tmp/grow-a-e3-verification
```

账号集成组单独使用同一 runner 的 `--child test_accounts.py --case-group AccountIntegrationTests`。本轮为上述受影响模块专项回归，不称为全站完整回归；本轮未改前端界面，不以新增浏览器截图替代 HTTP、数据库或登录隔离测试。

## 交付边界

- 未连接真实业务库、运行真实账号迁移或调用外部 AI/GitHub；未修改个人记录、环境密钥或运行配置。
- A 的原有文档修订在共享工作区另行形成 `0c3e46a`，本轮在其基础上收尾；失败复现先于本轮源码修复。具体基线、受测文件与内容哈希见证据元数据。
- 本轮不开发 B、C、D、E1/E2；课程既有完成回执、行动定时提醒及日常节奏提醒保留。
- 真实环境发布后仍需按实际账号 schema 验证升级结果与权限；应用初始化只处理正在使用的账号，不将其他账号已经升级视为全部业务库通过。
