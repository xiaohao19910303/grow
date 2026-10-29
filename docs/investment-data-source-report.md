# 投资模块 · 数据来源接入状态

更新：2026-10-28。此页替代原先未经逐项验收的“全部完成/100%”总结；原总结不能作为能力或测试证据。

日线 CSV 和本地条件筛选可在无付费权限下使用。已新增 AKShare / 东方财富沪深股票及ETF未复权盘后日线，CSV与Tushare入口保留；Tushare实际账号权限仍未验收，北交所自动日历路径禁用。BaoStock、iFinD仍是候选目录；巨潮资讯、问财及东方财富条件选股仍为外部查询链接，未接入全市场自然语言查询或自动公告抓取。

## AKShare本次接入与真实验证

新增 `/api/investments/provider/akshare/daily`，手工选定来源、证券和最多90个自然日。股票使用 `stock_zh_a_hist`、ETF使用 `fund_etf_hist_em`，固定 `adjust=''`，AKShare锁定1.20.1。名称/代码/市场/品种校验、有界公开日历、日期/OHLC/重复/非有限量额检查后，事务保存行情快照、确定性指标和AI研究证据。原始成交量为手、成交额为元，保存原值并将量转换为股/份；不套用Tushare的千元转换。

AKShare在独立进程按需加载，总超时45秒；同一实例同时只取一笔。失败、超时及空数据均不产生新快照、不覆盖已有行情、不自动换源或重试。不同来源和不同请求范围不拼接。上游公开接口的成功不构成来源许可、独立真实性或稳定性证明。[官方接口用途说明](https://akshare.akfamily.xyz/introduction.html)

实际验证通过新增HTTP路由连接真实上游，使用一次性localhost PostgreSQL及合成标的记录；没有读取个人业务库或发送私人财务资料。范围均为2026-09-01至2026-10-27，测试schema随后删除。

| 标的 | HTTP取数结果 | 校验与保存 |
| --- | --- | --- |
| 浦发银行 `600000`（沪市股票） | 第一轮HTTP 200，35条 | 最新日2026-10-27，行情及研究证据保存通过 |
| 平安银行 `000001`（深市股票） | 第二轮HTTP 502，上游断连 | 未保存行情或研究证据；未将失败解释为停牌 |
| 沪深300ETF `510300`（沪市ETF） | 第一轮HTTP 502；手动第二轮HTTP 200，35条 | 成功轮最新日2026-10-27，行情及研究证据保存通过 |
| 创业板ETF `159915`（深市ETF） | 第二轮HTTP 200，35条 | 最新日2026-10-27，行情及研究证据保存通过 |

[第一轮真实HTTP记录](verification/investment-akshare-20261028/live-http-first.json)、[第二轮真实HTTP记录](verification/investment-akshare-20261028/live-http-second.json)含耗时、返回状态、最新原始量额与归一值、临时库保存计数。另有[初次工作进程失败记录](verification/investment-akshare-20261028/live-worker-initial.json)。两种HTTP客户端对同一上游也观察到响应前断连；未改代理、未关闭证书验证、未切换来源或绕过访问限制。成功样例的成交额/归一成交量落在当日低高价之间，仅作为单位数量级核对，不是独立数据真实性审计。

**结论：股票及沪深ETF均已有真实取数/保存成功样例，但上游明显存在间歇断连；只能放行有失败提示、可人工重试的研究入口，不能宣称稳定的自动行情服务或全部标的验收通过。**

生产依赖从根 `requirements.in` 重新生成跨macOS/Linux锁，原48项锁定依赖版本保持；Linux专用依赖使用条件标记。当前仅在macOS实际安装，未构建Linux容器。无需API Key，但仍需核对本人用途及上游使用范围；实时、分钟、自动全市场更新均未交付。

## 本轮回归证据

- 投资隔离套件最终 **94项通过，0失败、0错误、0跳过**，用时105.309秒；覆盖新适配/工作进程、幂等、空数据、超时、异常数值、越权先于取数、账本/AI/CSV/Tushare、导出恢复及桌面/手机浏览器。[完整日志](verification/investment-akshare-20261028/final-tests.log)
- 新390px页面流程检查股票/ETF分别保存、刷新恢复、CSV/Tushare入口、失败保留旧数据及来源不自动切换，另检查1440px无横向溢出。截图使用合成资料，不是真实投资账户。[手机截图](verification/investment-akshare-20261028/source-selection-390.png)
- 首轮新增浏览器用例误用exact匹配包含选项文本的嵌套label，定位超时；修正测试定位后专项及最终94项通过。[首轮日志](verification/investment-akshare-20261028/initial-tests.log)、[页面专项复验](verification/investment-akshare-20261028/browser-recheck.log)
- 隔离套件的外部网络、个人业务库、工作区写入及SQLite连接违规计数均为0；真实行情验证另行执行，未把模拟回归当真实取数证据。
- 当前macOS环境65项生效生产锁依赖均与安装版本一致，`pip check`、两个修改JS的语法检查及`git diff --check`通过。[依赖核对](verification/investment-akshare-20261028/installed-runtime.json)、[相关源码哈希](verification/investment-akshare-20261028/source-hashes.json)

复现隔离回归：准备专用localhost临时PostgreSQL，安装根生产锁和既有 `server/requirements-test.txt`，再执行 `TEST_POSTGRES_DSN='<专用临时库DSN>' .venv/bin/python -B 知行成长/server/tests/run_isolated_checks.py --pattern 'test_investment_*.py'`；浏览器用例使用现有Chrome。真实取数需在页面显式选择来源和公开证券，结果受当前网络和上游状态影响。未调用真实AI、未部署、未提交或推送。

- [唯一实施清单](../openspec/changes/investment-decision-system/tasks.md)
- [本轮逐项验收与限制](investment-acceptance-20261028.md)
- [接口与数据合同](../知行成长/docs/investment-contracts.md)

完整首版仍待真实数据/模型及端到端放行验收；未部署。清单项数量不是工时或整体完成百分比。

同日后续已完成股票/ETF两组真实模型HTTP研究、反证和草稿样例；上面的94项仍是行情接入时的隔离回归，不改记为真实模型测试。详见[本次AI验证结果和质量限制](investment-p1-ai-summary.md)。
