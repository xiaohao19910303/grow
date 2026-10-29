# 收口验证证据

软件版本与源码SHA256见`source-hashes.json`；最后软件提交`54ce203`，后续文档提交不改变软件。`full-final.log`及`summary.json`为最终1056项Python、39组JS检查结果，失败、错误、跳过均为0。使用一次性本机PostgreSQL、真实Chrome及现有Zook来源HTTP合同夹具，模型与报价为受控输入；未修改业务数据库。

`investment-final.log`为194项投资专项；`test_investment_research_browser.py.log`和`test_investment_research_tools.py.log`是独立审查末轮专项。后续并发首次读取反例已加入最终全量测试。`research-390.png`、`research-1440.png`来自最终真实Chrome界面。

保留失败证据：`full-checkpoint-race.log`对应过早读取IDB状态的测试竞态；`cold-lists-red.log`对应PG并发建表冲突，green为修复复验；`source-pending-red.log`对应读取来源中断后重复访问。没有删除断言或用跳过替代失败。

`akshare-live.log`记录本次真实来源读取不可用。`research-benchmark.json`仅为合成单进程基准。私人接口／真实模型质量与计费／系统通知横幅／生产部署单列，参见上级交付记录。

复验命令（需自行准备一次性localhost PG、Chrome、Playwright及真实Zook工作区）：

```sh
TEST_POSTGRES_DSN='host=127.0.0.1 port=YOUR_DISPOSABLE_PORT user=YOUR_TEST_ROLE dbname=postgres' \
TEST_ZOOK_WORKTREE='/Volumes/肖豪/project/Zook' \
NODE_PATH=/tmp/grow-goals-node/node_modules \
CHROME_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
.venv/bin/python -B 知行成长/server/tests/run_isolated_checks.py --full
```

应安装仓库锁定的测试／运行依赖。此次主环境缺少供应商依赖，使用一次性venv及隔离依赖目录；没有把临时绝对路径写进测试代码。临时PostgreSQL在测试结束后停止，日志和非私人截图已复制到本目录。
