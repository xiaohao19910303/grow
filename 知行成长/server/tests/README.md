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
export NODE_PATH=/tmp/grow-regression-node/node_modules
# macOS 使用已有 Chrome；其他系统设置为自己的 Chromium/Chrome 可执行文件。
export CHROME_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
/tmp/grow-regression-env/bin/python -B 知行成长/server/tests/run_isolated_checks.py --full
pg_ctl -D "$GROW_TEST_PGDATA" stop -m fast
```

`--full` 自动启用 Python Chromium 用例，并运行所有 `test_*.cjs`。缺少测试 DSN、测试跳过、浏览器/JavaScript 失败或隔离审计失败都会返回非零退出码。`TEST_PYTHON` 自动使用调用完整回归的 Python；可用 `TEST_NODE` 指定 Node 可执行文件。

单模块定位可运行 `--pattern test_copilot.py` 等；这些诊断运行不替代 `--full` 验收。

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
