# 运行环境核验与设计样式收尾

2026-10-25，在 `/Volumes/肖豪/project/grow` 完成运行条件核对、离线预检入口、公共教材准备及待提交样式收尾。**隔离验收通过；真实实例预检仍未通过，未启动或部署业务服务。**

代码提交：`78b777b`（显式离线预检）、`ecfe80c`（设计变量及无障碍样式）。13 个相关文件的 SHA-256 见[源码快照](evidence/tested-source.json)。原有 `.worktrees/` 保留。

## 运行环境：已有配置与实际阻塞

根 `.venv` 为 Python 3.13.9；48 项锁定运行依赖版本全部匹配，`pip check` 通过。未更新依赖，未替换旧虚拟环境。[初始核验](evidence/initial-runtime-audit.json)保留导出教材前的状态。

现有配置并非空白。只读取允许的配置源并汇报字段状态，未输出密码、密钥、数据库 URL 或 token。

| 项目 | 本次确认状态 |
|---|---|
| DATABASE_URL | 当前启动环境能够加载；本轮未连接业务数据库 |
| GitHub 仓库／token | 两个字段能够加载；未访问真实 GitHub 核对权限 |
| APP_PASSWORD | 根 `.env.local` 中存在；启动器按原有存储白名单不导入该密码，`server/.env` 未设置对应项；尚未确认它是否是当前账号应使用的密码 |
| ACCOUNT_ENCRYPTION_KEY | 当前启动环境及本项目现有配置源未找到；不能用新生成的 key 冒充原值，避免既有账号密文失去可读性 |
| LEARN_ROOT | 当前启动环境未设置；已另行准备有效教材目录，未自动改写业务配置 |

来源与加载状态见[配置核对](evidence/config-sources.json)。之前“缺 APP_PASSWORD”的表述指有效启动环境没有加载到，不代表根配置文件没有密码。保留原加载规则的既有回归测试也通过：进程环境优先、服务端配置覆盖共享存储项、不导入共享旧初始化密码、不执行 `.env` 中的 shell 文本。

实际运行 `bash 知行成长/manage.sh check --offline` 返回 **2**，只提示这三个启动字段，见[实际预检日志](evidence/business-offline-final.log)和[退出状态](evidence/business-offline-result.json)。这是预期的配置阻塞，不属于“真实启动通过”。未改写上述文件，也未生成或替换真实管理密码／加密密钥。

后续真实启动需要从原安全来源恢复账号加密密钥、确认并配置当前实例的管理密码，并设置教材路径。数据库与 GitHub 的实际连通／权限检查须在配置有效后单独完成，不能以本轮模拟服务验收代替。

## 已完成的教材与预检入口

通过已有 `prepare_materials.py` 导出 13 份白名单公共教材到：

```text
/Volumes/肖豪/project/grow/.grow-public-materials
```

文件哈希全部匹配，不含学习记录、执行复盘或个人规划。源教材未修改，业务 `LEARN_ROOT` 未自动切换。导出目录由现有 gitignore 排除；[清单](evidence/materials-manifest.json)及[核对结果](evidence/materials-check.json)可复验。其他机器须按部署手册重新导出，不能依赖本机未跟踪目录。

新增命令：

```sh
# 项目根：检查配置、依赖及目录，不连接数据库、不启动服务
bash 知行成长/manage.sh check --offline

# 包含数据库连接检查；仍不启动服务
bash 知行成长/manage.sh check
```

离线模式仍要求有效必填配置，检查教材目录与运行目录可写性；会按配置创建运行目录并写入临时探测文件。`serve --offline` 明确拒绝，不能跳过启动所需的数据库检查。原 start／restart 行为保留。完整部署步骤见[部署手册](../../deployment/standalone-web.md)。

## 样式收尾

将前批保留的 `index.html` 设计改动与 `design-tokens.css` 完成接入并提交。主页面共享变量集中到 CSS 文件，删除内联重复定义，保留旧名称别名与现有品牌配色、布局；资源版本参数已更新。

正常、提醒、错误徽标的文字／底色对比度验收均达到 4.5:1。补齐表单键盘焦点轮廓；开启“减少动态效果”时禁用按钮按压缩放并缩短过渡／动画。原生端同步未作为本轮结论，相关注释已明确跨端需独立核验。[设计变量说明](../../../知行成长/docs/web-design-tokens.md)记录来源与使用约定。

原有四个最小浏览器夹具会抽取主页面内联样式，本轮同步让它们载入同一份 Token 源，避免变量集中后夹具失去样式。这是夹具接入修复，生产页面直接请求 CSS 文件；隔离启动测试也实际获取该资源并校验 200、CSS 类型与内容。

变更前后的截图见[之前](evidence/screenshots-before/)与[之后](evidence/screenshots-after/)。状态徽标截图中顶部三个徽标是合成对比度样本；夹具的首页辅助模块空态／占位不代表真实账号健康状态。实际功能流程由专项浏览器用例另行验证。

- [320px 页面](evidence/screenshots-after/tokens-page-320.png)
- [768px 页面](evidence/screenshots-after/tokens-page-768.png)
- [1440px 页面](evidence/screenshots-after/tokens-page-1440.png)
- [状态徽标](evidence/screenshots-after/status-contrast.png)
- [表单键盘焦点](evidence/screenshots-after/keyboard-input-focus.png)

## 测试与验收

最终按文件／分组保留最后结果，**46 个 Python 用例、8 组 Node 检查通过，0 失败、0 跳过**；重复批次不累加。这是与变更相关的定向回归，不是全项目全量回归。[汇总](evidence/results.json)、[模块日志](evidence/modules/)及[原始批次](evidence/runs/)均保留。

| 范围 | Python 用例数 | 验证内容 |
|---|---:|---|
| 运行／配置／教材 | 15 | 新 CLI 6、原配置 4、真实进程启动及重启 1、环境加载 2、教材白名单／链接拒绝 2 |
| 新样式边界 | 3 | 单一变量源、320/768/1440 无横向溢出、状态对比度、表单键盘焦点、减少动态效果 |
| 阅读／原课程／导航 | 6 | 原云端课程 1、导航 1、阅读成长 1、阅读站点 3 |
| E1/E2 | 5 | 配置引导、保存／测试／错误恢复、完成说明及键盘／窄屏 |
| 行动与课程规划 | 10 | 行动 P0 8、规划关联及阶段进度闭环 2 |
| 节奏及 GitHub 课程 | 7 | 日常节奏 6、原课程生成／保存／学习 1 |

八组 Node 覆盖 P0 草稿／请求恢复、行动客户端、个人配置校验、连接测试竞态、规划关联、完成后刷新，以及阅读启动和状态表单两组真实 Chrome 脚本。使用本机已有 Playwright 的 NODE_PATH，没有安装新依赖。

隔离启动使用实际部署入口、一次性 PG 数据库和合成账号：预检 → 启动 → 健康检查 → 登录 → 正式教材／静态 CSS 访问 → 写入合成记录 → 停止并重启 → 确认记录保留。数据库不可达仍安全失败，错误不带凭证；离线成功不生成 PID 或后台日志，离线 serve 被拒绝。

开发前新增运行用例 5 失败／1 通过；样式边界 3 失败，分别复现未支持离线参数／管理入口、重复变量源、焦点与状态文字问题。修复后均通过。[失败历史](evidence/history/)保留，仅规范化行尾空白，没有把失败记录改成通过记录。

全部测试使用 localhost 专用 PG、真实 Chrome、合成账号及模拟 GitHub／模型传输，未访问真实服务或业务数据库。隔离审计无被阻止的真实库访问、业务目录写入或外部请求。专用测试 PG 已停止，见[清理记录](evidence/cleanup.json)。本轮工作区仅保留原有未跟踪工作树；样式已正式纳入本地提交。

复验先设置专用 localhost `TEST_POSTGRES_DSN`，再运行：

```sh
.venv/bin/python -B 知行成长/server/tests/run_web_regression.py \
  --match 'test_runtime_check|test_deployment_config|test_deployment_boot|test_design_tokens_browser|test_setup_help_browser|test_packaged_materials|test_local_server_environment' \
  --output /tmp/grow-runtime-style-verification
```

OpenSpec `runtime-design-closeout` 严格校验、源码哈希核对和本轮提交的 whitespace 检查通过。真实账号的一周观察 B、实际部署与 D3 后置安排未因隔离验收而标为完成。
