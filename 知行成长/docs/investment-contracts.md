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
| investment-ai-assistance | AnalysisInput / 任务及结果（后续切片） | 选定数据/金额发送范围→预览→提交→生成→ready/failed/cancelled/interrupted；采用生成计划草稿，另行确认，不改账本 |
| investment-review | ReviewInput / campaign投影 | 按日/周/月/季度/事件/交易/思考；过程/结果分别记录；无事前风险基数不算R |

`AnalysisInput` 是已定义的请求选择合同，后台分析、预览和采用需按相应任务实现后开放。基金申请先pending，确认净值/份额/费用与到账须专用动作后续接入。模块能力接口应如实说明未验证的外部数据与实时能力。

示例创建账户（精确金额）：

```json
{"name":"交易账户","currency":"CNY","baseline_date":"2026-10-26","opening_cash":"10000","opening_positions":[]}
```

示例成交：

```json
{"account_id":"inv-ACCOUNT","instrument_id":"inv-INSTRUMENT","side":"buy","price":"1.231","quantity":"1000","fee":"1","tax":"0","executed_at":"2026-10-26T10:00:00+08:00","source":"manual"}
```

`GET /{resource}/{id}/history` 读取版本。策略/政策/计划通过 `POST /{resource}/{id}/state` 传 `{version,state}`；state值由状态合同限定。真实成交允许缺计划，不能伪称已按事前计划执行。未来引入规则/行情后仍须对照实际有效期与可卖数量，不能只依靠用户选择证券类型。
