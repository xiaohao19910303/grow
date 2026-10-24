# 云端存储完整回归

运行时合同：记录使用 PostgreSQL；正式课程、规划和采用的阅读资料使用 GitHub；AI 配置由浏览器随请求提供，不能回退使用服务端密钥。

## 环境与运行

需要 Python 3.11+、Node.js、PostgreSQL，以及 Chromium/Chrome。在仓库根目录安装测试依赖：

```sh
python3 -m venv /tmp/grow-regression-env
/tmp/grow-regression-env/bin/pip install -r requirements.txt -r 知行成长/server/requirements-test.txt
npm install --prefix /tmp/grow-regression-node playwright@1.62.1
```

创建专用的临时 PostgreSQL 实例，不使用业务数据库或指向业务数据库的转发端口。每项数据库测试还会创建独立 schema，并在结束或失败后删除它。

```sh
export GROW_TEST_PGDATA="$(mktemp -d)"
initdb -D "$GROW_TEST_PGDATA" -U grow_test -A trust
pg_ctl -D "$GROW_TEST_PGDATA" -l /tmp/grow-regression-pg.log -o '-p 55441 -h 127.0.0.1' start
export TEST_POSTGRES_DSN='host=127.0.0.1 port=55441 user=grow_test dbname=postgres'
# 使用支持 P0 来源投递合同的 Zook 检出，含 test/support/lighttick-source-http-fixture.ts。
# 本轮验证基线为 Zook 3db81b9；其 Node 依赖须按该仓库锁文件安装。
export TEST_ZOOK_WORKTREE='/absolute/path/to/zook-p0-checkout'
export NODE_PATH=/tmp/grow-regression-node/node_modules
# macOS 使用已有 Chrome；其他系统设置为自己的 Chromium/Chrome 可执行文件。
export CHROME_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
/tmp/grow-regression-env/bin/python -B 知行成长/server/tests/run_isolated_checks.py --full
# 等价的 Make 入口（可指定已有测试虚拟环境）：
make -C 知行成长 test PYTHON=/tmp/grow-regression-env/bin/python
pg_ctl -D "$GROW_TEST_PGDATA" stop -m fast
```

`--full` 自动启用 Python Chromium 用例，并运行所有 `test_*.cjs`，即使 Python 存在失败也收集 JavaScript 结果。缺少测试 DSN、真实 Zook 合同夹具、测试跳过、浏览器/JavaScript 失败或隔离审计失败都会返回非零退出码。`TEST_PYTHON` 自动使用调用完整回归的 Python；可用 `TEST_NODE` 指定 Node 可执行文件。

来源投递检查运行 Zook 的真实 HTTP 路由、行动服务和 PostgreSQL 仓储，不使用另写的合同替身。两个进程共用上述显式测试 DSN，并创建独立的临时 schema；不再回退到默认用户名或端口 5432。配置必须包含 `host=127.0.0.1`、非默认端口、用户和数据库名，测试不修改 Zook 源文件。

隔离入口自动向子进程传递服务端和测试模块的 Python 路径。P0 浏览器截图写入临时运行目录下的 `TEST_ARTIFACTS_DIR/action-p0`，运行结束清理，不覆写仓库中的历史验收证据。

单模块定位可运行 `--pattern test_copilot.py` 等；这些诊断运行不替代 `--full` 验收。

查找启动优化可用 `--pattern test_reading_startup.py` 验证：带条件的云端搜集仅使用一次数据库连接创建任务，仍检查并发与幂等；任务持久化并返回响应后再启动抓取，首次慢数据库读取不阻塞事件循环。`test_reading_startup_browser.cjs` 会挂起启动响应，验证点击后即刻进入进度页、失败后使用同一请求编号重试，以及离开页面后不重复提交或被旧响应拉回。

条件表单在首页列表和 `/api/reading/setup` 都未返回时即可操作；迟到的偏好不能覆盖输入，偏好失败也可继续查找。`test_reading_startup_browser.cjs` 同时验证这些情形以及阅读请求失败后的重试入口。`test_reading_reader_latency.py` 验证轻量设置接口不读文章和任务历史，云端阅读详情合并元数据读取，并保留私有笔记与最新正文任务。

## 夹具边界

| 范围 | 数据库 / 内容 |
|---|---|
| 课程、学习计划、阅读、复盘、全量同步、AI 请求保密性、跨页冲突 | 每项独立 PostgreSQL schema；GitHub 使用 HTTP 协议模拟器 |
| GitHub 超时、提交成功响应丢失、外部修改、数据库提交失败 | 注入协议/事务故障；验证原文保留、日志恢复、幂等结果及固定 SHA 读取 |
| 旧 SQLite 导入、旧配置清理、v1/v2 备份格式 | 明确的离线归档夹具；SQLite 不作为应用运行时替代品 |
| Chromium | 实际 HTML/JavaScript、实际 HTTP 接口、隔离 PostgreSQL；模型和 GitHub 使用模拟器 |

已移除 `SQLitePlans` 业务测试替身，同一套 GitHub 协议用例只在 PostgreSQL 上运行一次。早期本地发布格式仍通过 `offline_archive_fixture.py` 单独校验，支持读取原归档，不代表重新启用 SQLite 后端。

测试入口在导入应用前清空 `DATABASE_URL`、分配临时运行目录，阻止写入真实工作区、访问工作区 SQLite、连接非 localhost PostgreSQL 和外部网络。`test_isolation_boundary.py` 在子进程中验证这些拦截。GitHub 模拟器与合成正文避免访问真实仓库、网站或付费模型。

成功运行的 `ISOLATION_AUDIT` 中三个 `blocked_*` 值应为 0；允许的 `sqlite_connections` 来自离线归档、迁移来源和配置兼容测试。


## 日常节奏专项与发布门槛

专项使用同一个隔离入口；浏览器夹具读取实际首页及JS，使用临时PostgreSQL、合成文章与课程，不访问真实模型或GitHub。不要将TEST_POSTGRES_DSN设为业务库或业务转发端口。

```sh
RUN_GITHUB_BROWSER=1 python -B 知行成长/server/tests/run_isolated_checks.py --pattern 'test_rhythm_*.py'
```

`test_rhythm_export.py`需要本机pg_dump和pg_restore；只备份、删除并恢复测试自己创建的临时schema，核对完整个人JSON、总结历史、周卡、事件和统计。不能将此结果表述为旧SQLite备份已覆盖生产PG。

浏览器证据位于测试打印的 `RHYTHM_BROWSER_EVIDENCE` 临时目录。P0浏览器截图也改为独立临时目录，避免完整隔离入口拒绝向真实工作区写截图。

节奏专项通过不替代 `--full`。2026-10-23完整验收为577项Python、23组JavaScript全部通过，0失败、0跳过，R19已关闭；证据与保留项见 `知行成长/docs/daily-rhythm-v1-delivery.md`。不要跳过失败或连接默认本机数据库来获得绿色结果。

跨端来源HTTP回归还需要显式设置 `TEST_ZOOK_WORKTREE`，指向含 `test/support/lighttick-source-http-fixture.ts` 的独立测试工作树。测试节点现在从专用测试DSN构造连接地址，不再使用写死的默认本机数据库。该原协议回归不代表节奏R20跨端合同已经开放。

R19回归覆盖课程状态历史表的首次/旧账号初始化与历史保留、旧页面真实笔记依赖、认知课程计时回调、按课号继续学习、首次搜集偏好完整载入和编辑保护、账号切换保护。临时实例已停止，复现时请新建实例并使用自己的端口。
