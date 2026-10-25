# 代码结构整理与回归验证 · 2026-10-25

本轮将应用入口里的知识扫描、知识节点持久化与成长报告组装移入对应模块。`app.py` 从 652 行减少到 518 行，继续负责应用组装、生命周期、路由和账号准备；原有调用入口保留。

| 文件 | 职责 |
| --- | --- |
| `知行成长/server/knowledge/scanning.py` | Markdown 索引、思维工具、学习足迹解析与扫描；显式接收当前账号资料根目录 |
| `知行成长/server/knowledge/catalog.py` | 扫描结果增量写入、分类读取；显式接收连接工厂 |
| `知行成长/server/growth_reports.py` | 连续活动天数与周月报组装；复用原成长统计 |
| `知行成长/server/app.py` | 保留原函数入口，调用上述模块；请求执行时解析账号与连接 |
| `知行成长/server/tests/test_knowledge_scanning.py` | 新增四项扫描行为测试，在迁移前运行通过，迁移后结果一致 |

## 等价性检查

- 30 项针对性测试迁移前后通过：扫描 4 项、稳定 ID 18 项、成长统计 8 项。对应 `baseline-*.log` 与 `after-*.log`。
- 提取的索引解析、知识 SQL、分类统计和报告计算函数体经过 AST 对比，保持原逻辑。扫描中的资料根目录改为显式传参。
- 固定 `PYTHONHASHSEED=0` 后，原始应用与重构应用的路由清单及完整 OpenAPI JSON 一致，包含 219 个 OpenAPI 路径。固定种子用于排除多 HTTP 方法集合顺序导致的 operation ID 随机差异。
- 数据表、SQL、字段、排序、去重、统计口径和公开接口保持原实现；部署配置、课程目录未因重构修改；浏览器主题模块的提取和兼容性修复另见下节。
- 接口摘要、源文件哈希与校验基线见 [manifest.json](manifest.json)。

## 首轮全量发现的测试问题

首轮完整执行了 738 项 Python 用例与 32 组 JavaScript 检查，发现 1 项 Python 断言失败、1 项 Python 夹具错误和 1 组 JavaScript 沙箱错误，0 跳过；原始结果保留在 [full-regression.log](full-regression.log)。三处涉及的业务实现均与重构前 HEAD 一致，均已单独复现并修正测试。

1. `test_action_p0.py` 旧断言不允许配对预览查询对方合同，与现有只读能力探测流程不一致。修正为返回明确的不兼容合同，断言只有一次只读预览调用、没有生成两种快照、没有写入接管状态；HTTP 409 断言保留。修正前后专项见 `action-p0-diagnostic.log`、`action-p0-corrected.log`，修正后 15 项通过。
2. `test_browser_ai_config.py` 的路由测试未提供日常记录联动中间件所需的数据库。仅将这项集成测试移到 PostgreSQL 夹具并初始化日常记录表；其余纯配置测试仍无数据库依赖。配置缺失必须返回 422、提示使用本人配置的断言保留。见 `browser-config-diagnostic.log`、`browser-config-corrected.log`，修正后 5 项通过。
3. `test_legacy_state_client.cjs` 的 VM 沙箱缺少 `window`，真实保存处理函数更新教练事实缓存时抛出 `ReferenceError`。补充空浏览器全局对象后，原有保存成功、编辑保留、冲突及失败恢复断言通过，前端代码不变。

## 工作区隔离

修正测试后的第一次复跑期间，共享目录被其他操作从 `codex/d0-rhythm-startup` 切换到 `main`。该轮立即中止，结果不作为验收。切换前的自动 checkpoint `31f631266662a5db2101fba6f4acac914c1e3f49` 已包含本轮代码、测试及文档。

随后从该 checkpoint 创建独立工作树 `code-structure-regression/grow`，在固定代码版本上重新执行完整回归，避免读取混合分支内容。没有覆盖共享目录的当前分支或其他修改，也没有合并 checkpoint 中的其他功能到主分支。

## 主题模块与浏览器存储降级

独立工作树首次回归发现 checkpoint 中并入的主题切换代码直接读取 `localStorage`。已有 `test_action_storage_recovery_ui.py` 的真实浏览器用例在 getter 抛出 `SecurityError` 时失败，页面随后出现未完成初始化错误；该错误已单独复现。

将主题逻辑从首页主脚本提取到 `static/theme.js`，保持 `toggleTheme()` 入口和正常存储时的偏好行为。主题读取与写入均捕获存储异常：存储不可用时仍允许页面内切换，不中断主脚本。新增 `test_theme_client.cjs` 覆盖已保存偏好、系统主题变化、拒绝读取和写入失败；原有行动编辑、导出、恢复浏览器用例继续执行。

这是一处回归检查发现的实际兼容性修复，区别于上述三项历史测试夹具修正。诊断及修复结果见 `storage-ui-diagnostic.log`、`storage-ui-corrected.log`。包含该错误的独立工作树首轮被中止，不作为最终验收。

## 完整回归

最终结果：**738 项 Python 用例、33 组 JavaScript 检查全部通过，0 失败、0 错误、0 跳过**。隔离审计三个 `blocked_*` 均为 0。

执行现有 `server/tests/run_isolated_checks.py --full`，启用真实 Chromium 用例、Zook 来源 HTTP 合同夹具和全部 `test_*.cjs`，不跳过失败用例。最终汇总见 [result.json](result.json)，完整输出见 [full-regression-verified.log](full-regression-verified.log)。

测试使用新建的独立 localhost PostgreSQL 实例、临时 schema、合成账号与内容，不读取服务端秘密配置，不连接业务数据库、真实 GitHub 或付费模型。最终核对时临时集群有 1 个残留测试 schema；临时实例已停止，整个专用集群目录已删除，所有临时 schema 随集群清理。业务数据库未参与。

环境与复现步骤沿用[测试手册](../../../知行成长/server/tests/README.md)。本轮验证不代表已部署至生产；未推送、合并或重启现有应用进程。
