# 投资工作台私有合同

当前代码合同：`server/investments/contracts.py`；启动后的 OpenAPI `/openapi.json` 展示已注册的类型和路由。本文件记录跨切片约定，未实现的操作不能由本说明推定可用。

## 通用边界

- `/api/investments` 由现有登录会话与服务端租户schema隔离。客户端不能选择schema；原页面账号通过既有 `X-Account-Id` 防止跨标签页写错账号。
- 所有投资响应 `Cache-Control: no-store`。写入要求 `X-Copilot-Request: 1`，创建/更新/状态动作还要求 `Idempotency-Key`（1–160字符）。同键同内容复用原响应，不同内容409。
- 金额、数量、价格为十进制字符串，非负、最多28位有效数字/10位小数；实际成交价格和数量必须大于零。JSON浮点、NaN、超精度拒绝422。Python使用Decimal，账本列NUMERIC(28,10)。未知费用是null，显式无费用填字符串`"0"`。
- 时间为带时区ISO时间，日期为ISO日期；界面显示Asia/Shanghai。成交/流水不得早于核对基准日。
- opaque ID，显式版本。PUT `{version,data}` 更新部分输入，省略保留，显式null遵循字段合同；旧版本409。所有版本保留，不覆盖事前记录。
- 错误响应含message及error；未找到或不属于本租户返回404。缺字段/无效值422，版本/重复内容冲突409，缺写标识403，模块不可用503。
- 列表 GET `/{resource}?page=1&page_size=50&account_id=...` 返回items/total/page/page_size，上限100。账户详情 `GET /accounts/{id}/balance`，交易链 `/campaigns`。客户端仅展示最近100条时必须注明；完整历史不能误称已载入。

## 领域映射与状态

| 规格 | 核心输入/对象 | 操作约定 |
| --- | --- | --- |
| investment-planning | AccountInput / PolicyInput / StrategyInput / PlanInput | 草稿→显式确认/放弃/过期/取消/暂停；修改追加草稿版本。缺规则、行情、策略/预算时不能确认成可执行交易计划 |
| investment-ledger | OpeningPosition / FillInput / CashInput / FundOrderInput | 期初经核对；委托/基金申请不当成交；成交事实不可通用PUT覆盖；更正需专用审计流程 |
| investment-research | InstrumentInput / ResearchInput | 证券市场和类型匹配，研究有来源定位和available_at；原文不可信，缺历史/实时权限不得假定可用 |
| investment-ai-assistance | AnalysisInput / 投资分析任务及结果 | 选定数据/金额发送范围→预览→提交→生成→ready/failed/cancelled/interrupted；采用生成计划草稿，另行确认，不改账本 |
| investment-review | ReviewInput / campaign投影 | 按日/周/月/季度/事件/交易/思考；过程/结果分别记录；无事前风险基数不算R |

`AnalysisInput` 是分析资料选择合同；后台分析、预览和采用已接入模拟验证，真实模型效果尚未验收。基金申请先pending，确认净值/份额/费用与到账通过专用动作登记。模块能力接口如实说明未验证的外部数据与实时能力。

示例创建账户（精确金额）：

```json
{"name":"交易账户","currency":"CNY","baseline_date":"2026-10-26","opening_cash":"10000","opening_positions":[]}
```

示例成交：

```json
{"account_id":"inv-ACCOUNT","instrument_id":"inv-INSTRUMENT","side":"buy","price":"1.231","quantity":"1000","fee":"1","tax":"0","executed_at":"2026-10-26T10:00:00+08:00","source":"manual"}
```

`GET /{resource}/{id}/history` 读取版本。策略/政策/计划通过 `POST /{resource}/{id}/state` 传 `{version,state}`；state值由状态合同限定。真实成交允许缺计划，不能伪称已按事前计划执行。未来引入规则/行情后仍须对照实际有效期与可卖数量，不能只依靠用户选择证券类型。

## 已接入的扩展操作（2026-10-28）

- 成交 `POST /imports/preview` → `/imports/commit`：最多200行，先逐行检查，再整批事务写入；按来源/账户/外部编号防重。`POST /fills/{id}/corrections` 显式传版本、更正内容和原因；保留旧版并重新对账。基金确认衍生的成交不允许单独更正。
- 基金 `POST /fund-orders/{id}/confirm` 保存实际净值/份额/费用/日期。赎回形成应收款，`/settle` 核对到账后才增加现金。支持分批确认和最终确认标记，累计份额/金额受申请上限约束；本人填写每批实际结算金额、费用及净值日期。缺实际结算金额的历史确认仅作暂估，不确认现金或净结果。赎回全部确认后核对最终到账，不自动计算基金费率。
- AI `POST /analysis/preview` 保存发送范围和快照哈希，再 `POST /analysis/jobs` 传预览ID、哈希和本次AI配置。GET读取/恢复、POST `/analysis/jobs/{id}/cancel` 取消。后台两次同模型分析/反证；只校验引用属于选定原文，不独立证明原文真实性。建议处理记录通过 `/analysis/jobs/{id}/suggestions/{index}/decision`，采用仅生成草稿/投资思考，不发送委托。结构化金额默认不外发；自由文本中的金额须在预览里检查。密钥不写库、不进入任务中心存储。
- `GET /data-sources` 返回来源目录和接入状态；不是全市场行情接口。`POST /provider/daily` 提供Tushare股票/ETF日线适配，固定HTTPS目标、显式确认用途、凭证仅本次请求。实际账号权限未验证；缺权限不自动重试、降级明文或购买。日线不等同实时。
- `POST /market/import` 支持无付费接口权限的日线CSV。列：`date,open,high,low,close,volume,amount`（也支持对应中文列）；最多200行/250KB。必须声明来源、未复权口径、成交量股/份或手、成交额元或千元。校验OHLC/重复日期/非负量额后保留完整原始快照，另存最近20条研究摘要并显示省略数。导入不是独立核验或历史当时可知证明。
- `POST /screen` 接受 `as_of`、`conditions:[{field,op,value}]`、`combine`、`sort_by`。最多10条件/100结果，服务端字段/操作符白名单，禁止执行脚本/SQL。覆盖仅本账号已缓存标的，每个标的取最新一次保存的快照；不同导入范围不自动拼接。结果含覆盖数、无法判定数、数据日和来源。缺数据不视为满足条件；历史截止只截取日线，不是回测。无条件时显示有行情的本地标的。

示例本地筛选（成交额至少一亿元，收盘高于MA20）：

```json
{"as_of":"2026-10-26","combine":"all","conditions":[{"field":"turnover_cny","op":"gte","value":"100000000"},{"field":"price_above_ma20","op":"eq","value":"true"}],"sort_by":"turnover_cny","descending":true,"limit":50}
```

支持价格、相邻有效记录收盘变化%、成交额、最近成交量/前5条均量、MA20比较、名称/市场/品种。确定性行情摘要另含MA5/20、简单TR14 ATR与20个相邻记录收益率的样本标准差；样本不足为未知，不冒充年化波动率。指标为未复权有效记录口径，可能跨停牌日；缺少公司行动时不可将其解释为准确交易日涨幅。

## 数据来源取舍与当前验证边界

| 来源 | 当前交付 | 后续接入前提 |
| --- | --- | --- |
| Tushare Pro | 沪深日历/股票ETF日线适配、错误降级测试；实际权限待核验，北交所自动路径禁用 | 本人配置接口权限和用途；场外基金/公告/复权/历史规则分别验收 |
| AKShare | 来源目录 | 逐接口验证上游稳定性、单位、覆盖、用途；库开源不意味着上游数据任意使用 |
| BaoStock | 候选目录、支持本人导出CSV接入 | 依据新官方文档实测行情覆盖、更新时点和访问规则 |
| iFinD | 候选目录 | 授权账号、HTTP接口合同、额度与用途配置 |
| 巨潮资讯 | 公告/财报官网核对入口 | 若自动采集，另行完成官方授权、抓取与来源时点合同 |
| 问财/东方财富 | 官网条件查询链接 | 不调用未公开私有接口；不把官网展示承诺为本应用的服务 |

官方依据：[BaoStock知识库](https://baostock.com/api/)、[iFinD接口文档下载](https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/download.html)、[AKShare文档](https://akshare.akfamily.xyz/)。用户明确目前没有购买Tushare权限，后期再配置；不将真实取数验收伪装成已完成。

## 本人核对的计划与账本约束

- `plan-checks` 保存证券、带时点盘后价格、连续开休市日历、规则有效期、价格/数量单位、最早可卖交易日延迟、交易状态、来源URL和本人确认。它是人工核对记录，不是实时接口；手工15点竞价收盘价不等于完整日线；全日日线接收改用15:30后的保守门槛，仍不代表供应商已入库。
- `GET /trade-plans/{id}/assessment` 仅估算做多入场，按价格差风险、进出费用预算、现金缓冲及数量单位取可用较小值。退出/观察保留草稿，不计算可卖数量。确认计划冻结核对、政策、策略及计算；跨周持有按核对日历算交易日。多计划不会预留总资金。
- `period-plans` 管理单日或周一至周日准备，可明确不交易；未触发、主动跳过需原因。政策草稿不替换此前生效版本，暂停新增风险不阻止录入实际成交。
- 成交可选择原计划版本；晚录入仍核对原版本确认时间、计划日期和期限。初始R分母按各批实际入场价格与事前失效价之差乘实际数量，加同计划版本一次进出费用预算；不直接使用整笔风险上限。事后改止损不重写初始风险；更正实际价格/数量或超计划数量后R未知。
- `ledger-notices` 标记公司行动、漏记、费用等账实差异；未解决时关联成本、净结果和可用现金无法确认，所录数量不代表券商已核验数量。解决必须写核对说明，不自动做复权或送转记账。
- 通用成交更正仅支持价格、数量、费用、税费、备注；不支持改证券、方向、时间或直接更正基金确认衍生成交。此类错误先标记账实差异，不能假装已自动修正。

## 研究、复盘与 Grow 引用

- `watchlist` 管理观察/研究/准备/持有/归档；`dossiers` 分股票/ETF、短线/波段结构化研究，保留选定资料快照和哈希。列表省略大正文快照，详情、历史、导出保留原值。资料采用本人粘贴或导入，不自动抓URL，因此没有自动抓取的安全/许可验收承诺。
- `principles` 保存规则、支持案例、反例、试验范围和来源复盘；本人确认只启动试验，不修改策略或增加风险。
- `GET /accounts/{id}/campaigns/{campaign_id}/review` 对照原计划/策略、实际成交、结果和过程评价。`GET /accounts/{id}/summary?start=...&end=...` 统计所选上海日期期间成交净已实现、开放仓位、策略版本组、胜率/R已知样本和全部建议处理；独立账户费用与入出金单列。没有有效价格路径时不计算回撤/TWR/XIRR，也不编造未采用建议的影子收益。
- `legacy-records` 只读保留旧stocks值和“历史估算”标签，`legacy-links` 需本人核对后关联真实成交或复盘，不把旧profit_loss记入新账。
- `GET /overview?as_of=...` 今日仅中性计数；通用搜索/时间线通过只含中性元数据的视图发现入口。投资正文仅在本人显式 `GET /search?account_id=...&q=...` 中查询。
- `POST /reviews/{id}/actions` 只复制本人输入的标题/日期及通用来源提示，保留私有引用、版本和哈希，幂等；不复制财务正文、不记课程完成。沿用现有本地行动写入和LightTick接管保护：外部接管模式下不绕过写保护，自动同步外部行动未交付。

## AI 快照与验收界限

- `AnalysisInput` 可选择政策、原文、结构化研究、计划、复盘及最多5条完整交易链。金额默认关闭；交易链仅发送方向/时间/文字，开启后才加入成交价格、数量、费用、冻结风险和结果。自由文本仍需本人在发送预览中核对。
- 决策截止排除后发资料/交易链更正，历史余额使用截至时点已知版本；原文真实性、手工规则和模型结论未获独立证明。
- 理财输出至少两种带假设、约束、缺项的情景。缺唯一有效政策不出个人金额草案；具体金额必须授权且在已知现金扣缓冲范围内。`POST /analysis/jobs/{id}/scenarios/{index}/policy-draft` 生成原政策的新草稿版本，保留本人数值约束，不应用模型建议分配或自动加风险。
- 报告支持原文摘录、精确程序计算引用与交易事实引用；第二次分析来自同模型，不称独立审计。条件建议须有触发、失效和有效期；采用仅生成可编辑草稿。输入版本/账本变动或建议过期时禁止新采用；拒绝/保留/未触发/未成交/已修改均留痕。
- 导出包含私有对象、版本、来源、关联和AI快照；整站数据库备份包装器在隔离空库恢复后核对清单、记录、哈希及引用。不得把局部JSON导出当整站可恢复备份。

本轮具体测试数量、命令、结果和未完成项见[2026-10-28验收记录](../../docs/investment-acceptance-20261028.md)。真实供应商权限、真实模型质量和线上部署均未验收。完整首版以[唯一任务清单](../../openspec/changes/investment-decision-system/tasks.md)为准。

## 公开参考与配置接口（2026-10-28续实施）

`GET /calendar`、`/instruments/{id}/rules?on=...`、`/instruments/{id}/data-status` 提供有界公开日历、规则与最新快照新鲜度；`GET /readiness` 只列配置要求，不读取密钥。当前参考版本 `cn-auction-20261028-v1`，覆盖沪深2026日历及2026-07-06起部分竞价限价买入规则，维护复核截至2026-11-27；维护期限不是交易所失效日。来源/未知字段/实施状态/哈希明确，北交所、场外基金、未覆盖历史和ETF具体机制仍未知，动态交易状态不冒充已验证。

`plan-checks.rulebook_id` 是可选自动依据标记，计划确认仍服务端重算，过期/版本不符拒绝自动采用，已覆盖字段或休市日历冲突阻止确认。策略/计划/初始风险与规则对照快照一并保留，实际已发生的成交仍允许如实记录。数量另外受对应限价单笔上限约束。

`POST /provider/daily` 支持 `calendar_mode=public_reference|provider`，HTTP默认公开参考；覆盖内不请求trade_cal，仅测试实际调用的日线接口。覆盖不足/过期直接停止；供应商模式须本人选择并核对trade_cal权限。内部函数缺省继续原供应商模式，旧幂等指纹保留。Token不入库；两种模式都不等于实时授权。

运行时不自动抓取任意规则URL，更新需重新核验并发布参考版本。完整配置要求与真实服务待验收表见[本人配置清单](../../docs/investment-configuration-checklist.md)，具体证据见[本轮记录](../../docs/investment-rules-and-e2e-20261028.md)。

## 本人分钟路径与前向观察（2026-10-28第三轮）

`POST /paths/import` 的PathInput要求account_id/instrument_id、UTF-8 CSV原文、source_label、volume_unit（shares/lots100）、amount_unit（cny/thousand_cny）、price_basis=unadjusted和本人use_confirmed。列固定start/open/high/low/close/volume/amount，带时区分钟起点，半开一分钟区间，最多2000条/250KB；不接收交叠、未来、午休/盘后，已知休市日拒绝。原文包括结尾换行保留，另存来源/快照哈希与原始/转换单位。详情/导出保留，列表省略大原文和分钟。

`GET /paths?account_id=...` 每页50；`GET /paths/{id}`读保留原文。`GET /accounts/{account_id}/campaigns/{campaign_id}/replay?path_id=...&cutoff=...` 核对账户/证券，最多62自然日和500笔成交；后续成交/分钟不进入截至投影。各完整分钟按实际剩余数量、移动成本和成交净已实现标记上下界；不含分红/利息/独立费用或未来假设退出费用。完整指标遇缺段、边界变动、来源冲突、未知费用或账实差异为空；已知真实净已实现不因路径坏数据变未知。回放不插值、不推断止损/目标顺序。retrospective/current-ledger不是时间点回测或独立行情验证。

`POST /experiments` 新建观察草稿；GET列表/详情/history、PUT当前草稿；`POST /experiments/{id}/register`在开始前显式登记（version+state=confirmed）。冻结策略版本、参数文本、假设/反例、成本、起止与样本目标；登记后参数不能PUT覆盖。`GET /experiments/{id}/evaluation`纳入窗口内入场的全部相符冻结策略版本交易，开放/未知/其他归属分开；额外成本敏感性不是实际费用。

`POST /experiments/{id}/finish`需当前version、decision（retain/reject/inconclusive/stopped）、reason及evaluation_hash。期间结束前只允许stopped；保存结项快照，后续更正标为outdated而非重写。观察/排除合计最多1000链。小样本、零分母与未知费用不补造绩效，不修改策略/风险。该观察切片不包含样本外撮合、参数重跑或优化器，4.4整项尚未完成。

新接口沿用租户隔离、no-store、写标识/幂等；原文和协议纳入完整恢复。readiness/capabilities显式区分offline_replay和forward_observation可用、backtest/realtime/intraday_alerts未开放；P2整体仍未放行。新功能不读取凭证、不联网拉行情、不调用模型。

### 离线条件演练（2026-10-28续）

`POST /api/investments/condition-drills`需要account_id/path_id/check_id/title、op(gte/lte)、十进制文本threshold、含时区valid_from/valid_until、acknowledged；可选intent(observe/entry/exit)、退出假设assumed_bought_on、max_age_seconds(1–300)、arrival_delay_seconds(0–3600)、notification_scope(none/page)、probe_at(最多10个)。仅记录至今已结束且不超过62天的声明场景；字段外内容拒绝。

保存原始rule_snapshot/check_snapshot/reference_snapshot/path_hash、逐事件status及result_hash，kind=condition-drills且无覆盖更新接口。GET同名列表须account_id、分页50并省略时序和核对正文；GET同名/{id}取完整已保存结果。校验/原文/备份/权限沿用投资私有边界。相同输入重复请求不建重复记录。完整规则、状态优先级与限制见根目录docs/investment-condition-drill-20261028.md。

所有结果realtime/executable/notification_sent均false；page_candidate只是明确选择的本页模拟提示计数。最长2011个事件，显示前100条但私有API保留完整结果；不改实际账本。新增condition_drill能力为true，实际intraday_alerts和P2仍false。不能以此证明4.5或4.6整体完成。
