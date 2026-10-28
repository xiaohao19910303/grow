# 投资模块逐项实施与验收 · 2026-10-28

本轮已落实不依赖付费行情权限的记录、计划、研究与复盘切片。唯一状态源为[实施清单](../openspec/changes/investment-decision-system/tasks.md)：第一轮23/32项勾选（续实施后当前25/32，见下方更新），按项计数不代表工时完成率。完整首版尚未放行，未部署。

## 逐项交付

| 清单项 | 实际交付与边界 | 验收证据（测试文件省略共同前缀 test_investment_） |
| --- | --- | --- |
| 2.2 | 政策生效/草稿隔离、期间冲突、暂停新增风险、计划与实际入出金差额；暂停不阻止记事实 | policy.py 3项；browser.py政策确认/暂停/AI修改草稿保留生效版 |
| 2.4 | 本人核对连续开休市日历/规则/盘后价，入场数量估算、周日准备、未交易原因；确认冻结原计划/策略/计算 | plan_checks.py 5项、period_plans.py 1项；planning_browser.py手机确认计划/跨周日历 |
| 2.6 | 移动加权成本、分批进出、费用/未知处理；公司行动或账实差异先标记，不自动做送转调整 | accounting.py、store.py、flows.py；reconciliation.py 1项验证金额隐藏/解决留痕 |
| 2.8 | 分批净值/份额/实际结算净额/费用、累计上限、赎回应收及最终到账；不自动推定费率 | flows.py 5项；planning_browser.py录入两批实际净额；NAV乘份额的分位舍入手算 |
| 2.9 | 原计划/策略版本、实际成交与结果对照，合规评价和逻辑判断分开；未交易复盘保留 | review_metrics.py 3项；browser.py保存偏离评价并重新查看 |
| 2.10 | 旧值/历史估算不变，人工核对后幂等关联成交或复盘，不把旧估算当真实盈亏 | legacy_bridge.py 1项；browser.py旧记录关联 |
| 2.11 | 私有导出、版本/原文哈希/AI快照、数据库原生恢复及生产整站备份包装器恢复 | backup.py 1项、full_backup.py 1项；隔离空库核对记录/版本/引用/哈希/余额，manifest无私人正文 |
| 3.2 | 自选阶段、原文定位/可知时点/哈希、研究页和旧报告返回保留原文；仅本人录入/CSV | research_records.py 1项；analysis.py后发资料/矛盾重述；browser.py报告打开保留原文 |
| 3.3 | 本地MA/量比/简单TR14 ATR/20收益率样本标准差，做多入场数量取整与冻结实际初始风险 | calculations.py 1项；plan_checks.py手算数量/费用/部分入场R分母102，不用整笔预算250；缺输入拒绝计算 |
| 3.4 | 股票/ETF短线/波段研究页、净值时差/流动性/公司风险/估值假设与缺项；保存来源版本 | research_records.py；两条浏览器流程分别覆盖ETF波段、股票短线与零来源资料不足 |
| 3.6 | 至少两种理财情景、资料/金额边界、风险与现金缓冲限制；采用只形成原政策新草稿，保留本人数值约束 | analysis.py教育/个人/超额冲突；browser.py两种情景及政策草稿 |
| 3.7 | 选定原文摘录、精确程序计算引用、支持/反对理由、缺项、时点/版本追踪；不把模型数字当核验值 | analysis.py 11项的一部分：虚构值/矛盾重述/后发信息/精确计算引用/截止余额历史版本 |
| 3.8 | 触发/失效/有效期建议；采用生成可编辑草稿，输入变更/过期拒绝新采用；处理状态留痕 | analysis.py幂等/过期/账本变更/草稿采用；browser.py采用思考及重新打开 |
| 3.9 | 显式选完整交易链与原计划做AI复盘，金额可选，交易事实引用精确匹配；本人编辑候选，原则含反例/试验范围 | analysis.py交易链金额隐藏/引用拒绝；research_records.py一次亏损/缺反例不确认/确认不改策略；browser.py原则试验/暂停 |
| 3.10 | 自选日期周月统计、净已实现、开放仓位、策略版本组、胜率/R样本、全部AI建议与未知结果 | review_metrics.py 3项；browser.py周期统计和已采用建议；无路径不算回撤/TWR/XIRR |
| 3.11 | 今日仅计数、通用搜索/时间线中性入口、显式私有全文搜索、复盘转本地行动和引用 | integration.py 1项；双账号API、12项搜索回归、Node导航；browser.py今日/私有搜索/幂等行动/引用导航 |

2.1、2.3、2.5、2.7、3.5、3.13保留此前已完成状态，本轮同套回归覆盖账户、策略、成交/CSV、AI任务恢复与数据导入/筛选。1.1合同随本轮扩展更新。

## 最终验证结果

- 投资隔离套件：**69项通过，0失败、0错误、0跳过**，用时20.142秒。[完整日志](verification/investment-20261028/investment-tests.log)
- 已提交代码独立导出复验：**69项通过，0跳过**，用时22.387秒；排除并行目标/行动工作区的未提交改动。验证代码为 `3cd3a8c`（承接 `09789ad`、`19a8236`）。[独立导出日志](verification/investment-20261028/committed-tree-tests.log)
- 原生行动回归：**10项通过，0跳过**，验证事务创建函数提取不改变既有创建行为。[日志](verification/investment-20261028/action-regression.log)
- 搜索/时间线Python回归：**12项通过，0跳过**。[日志](verification/investment-20261028/search-tests.log)
- Node三个脚本：search_autofill、search_timeline_navigation、search_loading全部通过，覆盖投资入口注入、定位、加载和离开保护。[命令与输出](verification/investment-20261028/node-tests.log)
- 两条真实Chrome流程运行于390px，连接真实临时PostgreSQL与HTTP应用夹具；检查刷新恢复、表单、引用、来源原文、分页外引用保存和无横向溢出。这里是模块/入口组件验证，不能当作生产整站全流程或完整桌面适配放行。[计划页面截图](verification/investment-20261028/planning-390.png)、[本地筛选截图](verification/investment-20261028/screening-390.png)均为合成测试资料。
- 隔离审计：拦截违规网络、真实数据库和工作区写入尝试均为0，SQLite连接为0。模型/供应商使用模拟边界；未调用真实付费行情或真实模型。
- 首轮69项中有1项浏览器同步错误：搜索结果h4与详情h3同名，等待条件提前通过。已改为等待详情h3并断言关闭，单测重跑及最终69项整体通过。[首次失败](verification/investment-20261028/initial-run-modal-wait.log)、[单项复验](verification/investment-20261028/browser-recheck.log)。

独立导出的首次复验还发现备份测试隐式读取外层Git元数据，已改为显式使用测试夹具的合成版本号，随后独立导出69项全部通过。[修复前日志](verification/investment-20261028/archive-metadata-initial.log)。这不修改生产备份对可核对代码版本的要求。

代码复核覆盖金额精度/未知状态、事务/版本/幂等、账号授权、私有正文披露与HTML转义、来源时点和引用范围。无新增第三方依赖。JavaScript语法检查与 `openspec validate investment-decision-system --strict` 均通过；没有宣称独立外部审计。

复现（先启动专用临时PostgreSQL；DSN不得指向个人真实数据）：

```sh
TEST_POSTGRES_DSN='<专用测试库DSN>' .venv/bin/python -B 知行成长/server/tests/run_isolated_checks.py --pattern 'test_investment_*.py'
TEST_POSTGRES_DSN='<专用测试库DSN>' .venv/bin/python -B 知行成长/server/tests/run_isolated_checks.py --pattern 'test_search_timeline.py'
TEST_POSTGRES_DSN='<专用测试库DSN>' .venv/bin/python -B 知行成长/server/tests/run_isolated_checks.py --pattern 'test_action_plans.py'
node 知行成长/server/tests/test_search_autofill.cjs
node 知行成长/server/tests/test_search_timeline_navigation.cjs
node 知行成长/server/tests/test_search_loading.cjs
```

## 保持未完成与限制

- **1.2**：真实供应商账号权限、覆盖/单位/配额/许可矩阵未验收。Tushare适配不能当权限已开通，AKShare/BaoStock/iFinD目录不能当已接入。北交所自动日历禁用；不借用上交所日历。
- **3.1**：自动历史规则、交易状态、全品种新鲜度和来源单位全覆盖尚未交付。本人核对的规则/日历不是独立验证；15点门槛不替代交易所时段合同。日线不冒充盘中价格。
- **3.12**：真实模型/数据、生产整站移动及桌面、断网和试用质量的完整端到端放行未完成。模拟模型成功只证明程序合同和流程，不能证明实际建议质量或收益改善。
- **P2六项全部未完成**：分钟/实时、MAE/MFE与回放、受约束回测、样本外/前向评估、盘中提醒及其降级验收。
- 数量估算仅覆盖做多入场，退出/观察保留研究草稿；实际卖出须核对券商可卖数量。多个计划不自动占用/预留总现金。费用预算、跳空、停牌等仍可能造成超预算损失。
- 场外基金按实际确认记账，赎回最终到账为一次核对，不支持逐批到账；通用更正只支持成交价格/数量/费用/税费/备注，基金确认、证券/方向/时间的改错未交付，先标记账实差异。
- 原文仅本人录入/导入，不自动抓取URL；原文真实性和来源授权由本人核对。关闭结构化金额不自动删除自由文本内的金额。
- 复盘转行动沿用本地单写入及LightTick接管保护，未实现接管模式下的外部行动创建/同步。通用搜索和时间线不检索私人财务正文，私有全文查询需在投资工作台显式发起。

## 文档修正

已替换六份历史“已全部完成/100%”总结为当前状态入口，修正合同中“单次基金确认”“交易计划一律不能确认”等过期说明；设计背景明确区分最初规划与当前实施。此记录与唯一清单一致，不将OpenSpec工件齐全、模拟测试或历史盈利解释为能力全部完成。

## 同日续实施更新

公开规则/日历与数据新鲜度服务（3.1有界首版）已验收，第二轮清单24/32项。新增真实首页/登录会话的桌面与手机完整流程、断网恢复；3.12真实模型/数据与使用质量仍待验收，不因界面链通过而整体勾选。最新独立导出84项通过、0跳过，含完整首页桌面/手机链；新参考范围、日历权限解耦、测试证据和剩余8项见[本轮记录](investment-rules-and-e2e-20261028.md)。需要本人填写的行情/AI项目集中在[配置清单](investment-configuration-checklist.md)。前文69项为第一轮证据，不是最新套件数量。

## 第三轮离线续实施

4.2离线一分钟CSV路径复盘/手动回放验收完成，当前25/32项。4.4前向登记、冻结与成本压力观察可用，但参数敏感性重跑/样本外评估未交付，整项仍待办。4.6只补组件能力区分与禁用验证，未整体放行。最新96项全量通过及手机布局专项复验、公式与剩余7项见[离线验收记录](investment-offline-review-20261028.md)。前两轮69/84项是历史证据，不是当前套件数量。
