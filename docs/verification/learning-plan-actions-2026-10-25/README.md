# C1/C2/C3：课程规划关联行动与阶段进度验收

2026-10-25，在当前项目 `/Volumes/肖豪/project/grow` 完成实现和本地隔离验收。代码提交 `81850f8`；15 个服务端、前端及测试文件的 SHA-256 见[来源快照](evidence/tested-source.json)。本报告不代表真实业务库已升级或线上已发布。

## 交付结果

- **C1 完成**：采用规划时默认勾选、允许取消关联；旧规划详情可关联／同步。只为已发布且未学完课程补入无日期、无提醒的内容行动。复用同课既有行动，保留本人日期、标题和状态；反复同步、不同请求并发不会重复创建。
- **C2 复用并验收**：原有课程本人完成确认和来源回执已支持内容行动，本轮继续复用。已安排今日的行动回写一条完成记录；未安排日期的行动不补造执行。课程学习状态和行动状态分别展示。
- **C3 完成**：「行动 → 目标与计划」及规划详情显示整体／阶段进度。分母为当前正式规划全部课次，分子为已发布且本人确认学完的课次；草稿、笔记和分钟不计学完。
- **恢复能力**：正式来源保存成功后，关联异常返回独立提示并保留成功结果，可在详情单独重试。支持停止／恢复自动补入；暂停或归档规划不新增行动，已有安排保留。

用户操作见[使用说明](../../../知行成长/docs/learning-plan-actions.md)。B 的真实使用观察、E1 配置引导、E2 全局完成语义说明、D3 自动 AI 报告仍保留待办；本说明仅覆盖本次课程规划闭环。

## 测试结果

采用四批定向回归，按「文件＋账号分组」保留最后结果，重跑不累加：**225 个 Python 用例、5 组 Node 检查，0 失败、0 跳过**。这不是全项目完整回归。账号浏览器类继承的用例按实际收集节点计数，不能理解为 225 个互不重叠的产品场景。明细见[汇总](evidence/results.json)、[逐模块日志](evidence/modules/)及[各批原始结果](evidence/runs/)。

| 范围 | 用例数 | 验证内容 |
|---|---:|---|
| C1/C3 API、PG | 19 | 无已发布课程、关联幂等与三请求并发、复用日期安排、取消不复活、停止／恢复、暂停、版本冲突、容量异常整笔回滚、跨端接管拒绝本地写入、GET 不改行动、部分成功重试、旧页面合同保护、两阶段最终 100% |
| C1/C3 Chrome | 2 | 键盘采用、发布自动补项、安排今日并开始、本人学完回写一次、刷新保留阶段进度、320px 窄屏、失败读取重试、保存部分成功后的关联重试、取消采用关联选项 |
| 真实登录与隔离 | 44 | 三组收集覆盖校验通过；含新增规划关联隔离、匿名拒绝、猜测他人规划拒绝、旧账号页面写入拒绝及既有账号功能回归 |
| 规划与改版 | 61 | 原规划 28、GitHub 规划 17、草稿修订 14、状态历史 2 |
| 行动／安排／来源回执 | 50 | 行动 10、日程 7、P0 来源 3、来源收尾 24、投递 6 |
| 事实／统计／提醒 | 25 | 教练事实 15、成长统计 8、节奏提醒 2 |
| 既有 Chrome 回归 | 19 | 行动 P0 8、GitHub 课程 1、导航 1、日常节奏 6、事实卡片 3 |
| 部署配置／隔离启动 | 5 | 配置预检 4、启动 1 |

五组 Node 分别检查既有行动客户端、P0 草稿恢复、学习完成刷新、教练事实，以及新增课程进度模块的安全文本、写入合同、错误重试、账号与导航竞态。最后一次合同保护改动后，新增账号隔离用例又单独通过，见[补充日志](evidence/account-final-supplement.log)，不重复加入总数。

浏览器使用真实 Chrome、生产 HTML／JS 与隔离 API；课程草稿由合成数据创建，新增流程没有生成模型请求。[网络记录](evidence/screenshots/network.json)与截图保留如下：

- [桌面整体／阶段进度](evidence/screenshots/stage-progress-desktop.png)
- [320px 窄屏](evidence/screenshots/stage-progress-mobile.png)
- [正式保存成功但关联失败的恢复入口](evidence/screenshots/partial-success-retry.png)

先写的 15 个后端用例全部失败，记录于[初始失败日志](evidence/backend-red.log)，随后实现并扩展至 19 个通过。Chrome 首轮脚本在页面初始化期间直接进入 hash 草稿路由，未进入预期预览；改为等待账号／列表初始化后进入草稿，再跑完整流程通过。后续新增部分成功与取消选项后，两项均通过，无遗留失败。

## 数据与接口边界

新增账号内 `learning_action_links(id,data)`，通过已有 plans 初始化增量创建，引用该账号的正式规划。关联账本与新行动在同一事务内提交，按规划发布锁 → 行动写锁顺序串行，复用抽出的既有安排创建逻辑、目标校验、容量限制及请求幂等。不改写历史执行，不为旧账号自动关联。

| 接口 | 用途 |
|---|---|
| `GET /api/plan-actions` | 当前账号已关联规划的实时进度 |
| `GET /api/plans/{id}/actions` | 单个正式规划进度与关联状态 |
| `POST /api/plans/{id}/actions` | `data.key`、`expected_version`、`enabled` 驱动关联／同步／开关 |

写入受当前账号、同源标识与 `X-Grow-Action-Schema: 2` 约束；规划采用新增可选布尔字段 `link_actions`。正式来源保存之后才同步，异常用 `learning_action_sync_error` 返回，避免误报发布失败。旧客户端缺少行动合同标识时只保留来源保存成功，不隐式写行动。读取不补项、无新轮询；无个人反馈正文或 GitHub 哈希进入进度投影。

跨端接管处于 pending／active 时拒绝本地补项，并显示仅可读取的说明。未修改 LightTick／Zook 合同、接管开关或服务配置。本地旧存储不启用关联。回退代码时须保留新增表与已经产生的行动事实，不能清表回退。

## 目录迁移与运行环境

根 README 的四个跨仓链接已按新目录修复并检查目标存在。新根 `.venv` 使用 Python 3.13.9 重建，48 项锁定运行依赖版本全部匹配，`pip check` 通过，uvicorn 入口指向新卷目录。旧 `知行成长/.venv` 保留；现有启动脚本优先使用根环境。环境本身不纳入 Git。

只读取原环境的配置存在性并运行离线预检，没有连接业务库或改写配置。目前仍缺 **APP_PASSWORD、ACCOUNT_ENCRYPTION_KEY 和有效 LEARN_ROOT**；不得据此启动真实实例或声称迁移上线完成。安全结果见[目录／环境核对](evidence/relocation-check.json)。

测试使用新根 Python、一次性 localhost PostgreSQL 和模拟 GitHub；兼容性回归中保留历史 SQLite 测试夹具，不代表生产使用 SQLite。隔离审计未发现真实数据库访问、工作区业务数据写入或外部网络请求。专用 PG 已停止，见[清理记录](evidence/cleanup.json)。未推送、部署，保留原有 `.worktrees/`。

复验入口（须自行设置专用 localhost `TEST_POSTGRES_DSN`，不可使用业务库）：

```sh
.venv/bin/python -B 知行成长/server/tests/run_web_regression.py \
  --match 'test_learning_actions|test_action_p0_sources|test_action_p0_closeout_sources|test_action_source_delivery|test_rhythm_reminders' \
  --output /tmp/grow-learning-actions-verification
```

其余模块和三组账号回归的精确选择见 `evidence/runs/` 与汇总日志；OpenSpec `learning-plan-action-link` 严格校验及 `git diff --check` 均通过。
