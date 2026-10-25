# E2 完成语义与 E1 个人 AI 配置引导验收

2026-10-25，在 `/Volumes/肖豪/project/grow` 按 E2 → E1 顺序完成本地实现和隔离验收：

- `f370441`：完成语义说明、页面入口及浏览器验收。
- `204a1a8`：个人配置三步引导、校验及连接测试保护。

本轮不修改完成状态机、数据库结构或服务端 AI 凭证保存规则。未操作真实业务库、未补写业务密钥、未推送部署。

## E2 交付

[用户说明](../../../知行成长/docs/completion-semantics.md)对照现有状态机，解释计时达标、起步与中断投入、内容来源回执、勾选及撤销、课程本人学完、规划阶段分母、安排日期与实际业务日期、时间来源重叠等规则，并给出分钟及课次例子。

设置、行动目标与计划、课程规划均可打开同一份「完成与进度说明」。原生 dialog 支持键盘、Escape 关闭、恢复入口焦点及 320px 窄屏滚动。课程、行动和投入继续分开记录；内容／勾选的 0 分钟完成不被解释成没有学习。

E2 先通过 59 个 Python 用例和 1 组 Node 检查后提交，包括三态、来源回执、原课程完成循环、C1/C3 及 Chrome 说明入口。该阶段与后续回归重叠部分未重复计入最终总数。

## E1 交付

保留原配置字段与直接编辑，在「设置 → 课程生成配置」新增三步引导：服务地址 → 密钥与模型 → 核对并保存。课程规划、认知课程及自动导读的缺配置入口可进入引导；原有离开保护拒绝导航时停止跳转，不重放生成请求。

核对摘要使用文本节点，不显示 API Key。保存只写当前账号在当前浏览器的配置，不自动测试、不自动生成。服务地址、模型与密钥的类型、长度、控制字符及 HTTPS 地址校验与已有请求合同对齐；已有内容仍可在未配置时阅读。完整操作及失败恢复见[配置引导](../../../知行成长/docs/ai-setup-guide.md)。

连接测试复用 `/api/ai/test`，由本人明确点击，可能产生服务商费用，测试不保存配置。新增取消与等待上限，阻止同页重复并发测试；结果绑定请求代次、输入和账号，修改、读取、清除、离开设置或账号变化后旧结果不再适用。错误不回显提供商原始文本或凭证。存储失败明确报错并保留旧保存值。

另外修复账号尚未就绪时读取配置的时序：等待账号后恢复其配置；如果用户期间已编辑字段，旧读取不会覆盖新输入。连接成功仅说明这次收到完整简短响应，不保证后续额度或所有模型能力。

继续使用按账号、浏览器及站点地址保存的配置，换浏览器／设备／站点或清除站点数据后仍需重新填写。未增加平台共享密钥、环境兜底、云端同步或自动模型调用。

## 验收结果

**136 个 Python 用例、8 组 Node 检查通过，最终选择结果 0 失败、0 跳过。**按「文件＋账号分组」保留最后一次结果，重跑不累加；不是完整项目全量回归。账号浏览器类继承的用例按实际收集节点计数，不是互不重叠的产品场景数。见[汇总](evidence/results.json)、[逐模块日志](evidence/modules/)和[各批原始结果](evidence/runs/)。

| 范围 | Python 用例数 | 说明 |
|---|---:|---|
| E2 原完成规则 | 13 | 行动三态 10、原课程完成循环 3 |
| 来源完成及恢复 | 30 | 来源收尾 24、来源投递 6 |
| C1/C3 | 21 | 关联与阶段 API 19、Chrome 闭环 2 |
| 配置 API | 7 | 请求配置、无服务端兜底、临时凭证及无泄漏 5；独立连接入口 2 |
| 真实账号 | 44 | 密码、账号集成、浏览器三组收集覆盖校验通过，含配置隔离及既有账户功能 |
| 界面回归 | 21 | 新说明／引导 Chrome 5、原 GitHub 课程 1、行动 P0 8、导航 1、节奏 6 |

八组 Node：配置校验／账号／存储、连接测试竞态／超时、后台生成客户端、完成生产者、规划关联客户端、完成后刷新，以及实际 Chrome 的阅读启动和状态表单两组脚本。新测试覆盖无自动调用、长度／控制字符校验、安全错误、账号隔离、旧 owner 配置迁移、存储拒绝、输入及账号变化、超时、取消、同页重复测试和账号就绪前读取。

新 Chrome 的五个用例覆盖：三个完成说明入口与键盘／窄屏；保存不调用模型、换浏览器为空及清除；错误校验、失败重试与过期响应；存储拒绝保留旧值；缺配置入口尊重离开保护、直接编辑保留输入及不自动重放生成。模型传输和 GitHub 均为模拟，测试只用 `TEST_SETUP_` 假凭证。

截图与不含请求体的网络记录来自纯提交副本：

- [完成说明：桌面](evidence/screenshots/completion-help-desktop.png)／[320px](evidence/screenshots/completion-help-mobile.png)
- [配置核对：桌面](evidence/screenshots/ai-setup-review-desktop.png)／[320px](evidence/screenshots/ai-setup-review-mobile.png)
- [连接失败重试](evidence/screenshots/ai-setup-test-failure.png)
- [存储拒绝提示](evidence/screenshots/ai-setup-storage-denied.png)
- [各用例网络记录](evidence/screenshots/)

## 失败记录与复验

实现前，新增 Node 校验用例因缺少接口失败，两项引导 Chrome 用例因没有引导入口失败。扩展用例还复现了账号变化后残留“正在测试”和账号未就绪时配置读为空的情况，均修复后通过。历史日志保留在 [history](evidence/history/)。E2 初始检查已在说明接入后通过，不将其称为业务逻辑失败重现。

补充 Chrome 脚本曾出现“测试连接”按钮未限定到 AI 表单、取消步骤放错用例位置的问题，已修正脚本；错误记录未删除。宽范围回归与纯提交复验中的两组 `.cjs` 浏览器脚本最初因 Node 找不到 Playwright 而未执行成功；使用 Codex 本机已有 Node 包路径补跑，两组实际执行并通过。最终统计只取补跑结果，不把这些环境失败计为通过，也不将同一组累加。

## 提交边界与环境

工作中同一 `index.html` 并发加入了设计样式及 `design-tokens.css` 引用，最初一并进入 E1 本地提交，审查后已从该提交分离。工作区中的设计改动和未跟踪 CSS 原样保留，未纳入 E1/E2；原有 `.worktrees/` 也保留。

为避免以这些额外样式作为交付前提，使用 `git archive 204a1a8 知行成长/server` 建立临时副本，复验新说明／引导、原 GitHub 课程、规划关联、行动、导航、节奏及 Node 客户端；两个 Node 浏览器脚本也在该副本运行。12 个源码／测试文件的[SHA-256](evidence/tested-source.json)对应提交副本，包含页面及新增模块，不能直接拿并发设计中的工作区页面整体哈希代替。

使用根 `.venv/bin/python`、一次性 localhost PG15、真实 Chrome 和模拟服务。部分兼容性夹具使用测试 SQLite，不代表生产存储。隔离审计无真实数据库访问、业务工作区写入或外部网络请求；没有引入依赖升级。环境见[元数据](evidence/environment.json)。专用 PG 已停止，见[清理记录](evidence/cleanup.json)。

本轮未重新配置真实实例；上一批记录的 APP_PASSWORD、ACCOUNT_ENCRYPTION_KEY、有效 LEARN_ROOT 等实际启动条件仍须按目标环境核验，不能用本地通过代替上线验收。后续优先收集 B 的真实使用案例，D3 自动模型报告继续后置。

复验须使用自己的专用 localhost `TEST_POSTGRES_DSN`，不得指向业务库：

```sh
.venv/bin/python -B 知行成长/server/tests/run_web_regression.py \
  --match 'test_setup_help_browser|test_ai_config_client|test_ai_connection_client|test_browser_ai_config|test_settings_independence' \
  --output /tmp/grow-e2-e1-verification
```

两组 Node 浏览器脚本需要为 Node 提供已有 Playwright 的 `NODE_PATH`；本轮使用 Codex 内置包位置，未安装新依赖。完整模块选择与结果以 `evidence/runs/` 为准。OpenSpec `completion-help-ai-setup` 严格校验及本轮提交的 whitespace 检查通过。
