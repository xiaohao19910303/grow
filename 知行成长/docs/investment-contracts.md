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

## 已接入的扩展操作（2026-10-27）

- 成交 `POST /imports/preview` → `/imports/commit`：最多200行，先逐行检查，再整批事务写入；按来源/账户/外部编号防重。`POST /fills/{id}/corrections` 显式传版本、更正内容和原因；保留旧版并重新对账。基金确认衍生的成交不允许单独更正。
- 基金 `POST /fund-orders/{id}/confirm` 保存实际净值/份额/费用/日期。赎回形成应收款，`/settle` 核对到账后才增加现金。当前单次申请只支持一次确认，不支持分批确认或自动计算基金费率；不能据此认为任务2.8全部完成。
- AI `POST /analysis/preview` 保存发送范围和快照哈希，再 `POST /analysis/jobs` 传预览ID、哈希和本次AI配置。GET读取/恢复、POST `/analysis/jobs/{id}/cancel` 取消。后台两次同模型分析/反证；只校验引用属于选定原文，不独立证明原文真实性。建议处理记录通过 `/analysis/jobs/{id}/suggestions/{index}/decision`，采用仅生成草稿/投资思考，不发送委托。结构化金额默认不外发；自由文本中的金额须在预览里检查。密钥不写库、不进入任务中心存储。
- `GET /data-sources` 返回来源目录和接入状态；不是全市场行情接口。`POST /provider/daily` 提供Tushare股票/ETF日线适配，固定HTTPS目标、显式确认用途、凭证仅本次请求。实际账号权限未验证；缺权限不自动重试、降级明文或购买。日线不等同实时。
- `POST /market/import` 支持无付费接口权限的日线CSV。列：`date,open,high,low,close,volume,amount`（也支持对应中文列）；最多200行/250KB。必须声明来源、未复权口径、成交量股/份或手、成交额元或千元。校验OHLC/重复日期/非负量额后保留完整原始快照，另存最近20条研究摘要并显示省略数。导入不是独立核验或历史当时可知证明。
- `POST /screen` 接受 `as_of`、`conditions:[{field,op,value}]`、`combine`、`sort_by`。最多10条件/100结果，服务端字段/操作符白名单，禁止执行脚本/SQL。覆盖仅本账号已缓存标的，每个标的取最新一次保存的快照；不同导入范围不自动拼接。结果含覆盖数、无法判定数、数据日和来源。缺数据不视为满足条件；历史截止只截取日线，不是回测。无条件时显示有行情的本地标的。

示例本地筛选（成交额至少一亿元，收盘高于MA20）：

```json
{"as_of":"2026-10-26","combine":"all","conditions":[{"field":"turnover_cny","op":"gte","value":"100000000"},{"field":"price_above_ma20","op":"eq","value":"true"}],"sort_by":"turnover_cny","descending":true,"limit":50}
```

支持价格、相邻有效记录收盘变化%、成交额、最近成交量/前5条均量、MA20比较、名称/市场/品种。指标为未复权有效记录口径，可能跨停牌日；缺少公司行动时不可将其解释为准确交易日涨幅。

## 数据来源取舍与当前验证边界

| 来源 | 当前交付 | 后续接入前提 |
| --- | --- | --- |
| Tushare Pro | 日历/股票ETF日线适配、错误降级测试；实际权限待核验 | 本人配置接口权限和用途；场外基金/公告/复权/历史规则分别验收 |
| AKShare | 来源目录 | 逐接口验证上游稳定性、单位、覆盖、用途；库开源不意味着上游数据任意使用 |
| BaoStock | 候选目录、支持本人导出CSV接入 | 依据新官方文档实测行情覆盖、更新时点和访问规则 |
| iFinD | 候选目录 | 授权账号、HTTP接口合同、额度与用途配置 |
| 巨潮资讯 | 公告/财报官网核对入口 | 若自动采集，另行完成官方授权、抓取与来源时点合同 |
| 问财/东方财富 | 官网条件查询链接 | 不调用未公开私有接口；不把官网展示承诺为本应用的服务 |

官方依据：[BaoStock知识库](https://baostock.com/api/)、[iFinD接口文档下载](https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/download.html)、[AKShare文档](https://akshare.akfamily.xyz/)。用户明确目前没有购买Tushare权限，后期再配置；不将真实取数验收伪装成已完成。

验证：2026-10-27专用临时PostgreSQL隔离环境，41项投资测试全部通过、无跳过，覆盖账号隔离、账本精度、CSV原子提交、基金应收、AI模拟两次调用/取消/采用、行情单位/拒绝权限、本地筛选、数据库原生备份恢复及390px真实Chromium流程。真实行情权限和真实模型质量尚未验收；当前交易计划因缺完整规则核验仍保留草稿。P0/P1完整交付以OpenSpec未完成项为准。
