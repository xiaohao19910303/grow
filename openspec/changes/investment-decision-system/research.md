# 投资工作台：市场研究与设计依据

研究日期：2026-10-25，用户时区 Asia/Shanghai。用户已确认：短线交易与波段复盘为主，A 股与国内基金/ETF 优先。

2026-10-26按审查补充复核：[Tushare A股实时分钟](https://tushare.pro/document/2?doc_id=374)需单独开通权限；其量额单位为股/元，与所核验日线文档的手/千元不同，适配器必须归一化。没有执行用户账号权限测试。产品流程同步收敛为三个主要页面，详见[修订后的产品设计](../../../docs/investment-review-module-design.md)。

本研究读取产品官方介绍、帮助中心、交易所规则与数据商文档，没有登录付费产品实测。产品能力是文档所述，不能据此证明其用户取得超额收益；以下 Grow 设计为本项目推导，不是来源的投资建议。

## 1. 可借鉴的工作方法

| 来源 | 核验到的方法 | Grow 采用方式 | 取舍 |
| --- | --- | --- | --- |
| [TradeZella 入门](https://help.tradezella.com/en/articles/5801077-welcome-to-tradezella) | 导入成交、日志、策略手册、回放与统计串联 | 用版本化策略挂接事前计划、实际成交与复盘 | 先建立可信流水与复盘，不直接照搬美股日内交易流程 |
| [TradeZella R 倍数](https://help.tradezella.com/en/articles/7190710-understanding-r-multiple) | 用初始风险比较计划与实际净结果 | 记录事前风险基数，按已知费用计算净 R | 不把其示例收益风险比作为通用交易门槛；风险价不能保证成交 |
| [Edgewonk MAE/MFE](https://edgewonk.zendesk.com/hc/en-us/articles/360010087660-MAE-MFE) | 回看持有期间最大不利/有利价格变化 | 研究止损、持有与退出偏差 | 入场前高低点不得计入；分钟区间不足时不显示精确值 |
| [Koyfin 自选列表](https://www.koyfin.com/features/watchlists/) | 可配置观察列、备注及事件提醒 | 自选分为待研究、条件未到、已计划、持有、暂不参与 | 提醒必须能回答什么条件变化，不默认推送全部价格波动 |
| [Simply Wall St 公司报告](https://support.simplywall.st/hc/en-us/categories/360000146555) | 将估值、成长、历史表现、健康度、分红分开组织 | 短线研究中保留财务与事件风险页，波段可展开估值情景 | 长期价值判断与短期价格判断分别陈述，不合成一个买入分数 |
| [Sharesight 组合页](https://help.sharesight.com/show_portfolio/) | 分解资本利得、收益、汇率，支持组合基准比较 | 成交账、现金、费用与基准分开，累计余额不直接当收益 | 首期人民币为主；不声称照搬国外税务口径即可用于中国 |
| [Portfolio Performance 收益口径](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/) | 区分时间加权与资金加权，说明外部现金流与估值要求 | 明确实得盈亏、资金体验、策略表现三个问题 | 数据不足不伪算精确 TWR；XIRR 无解、多解与短期年化另行说明 |

## 2. A 股与 ETF 的本地适配

- [上交所交易规则（2026 年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)公布了交易时间、交收前卖出限制及回转例外，并区分已实施与暂缓实施条文。Grow 必须同时记录生效时间、实际实施状态和适用品种；研究旧交易时读取当时规则，不能仅取最新正文。
- [深交所交易规则（2026 年修订，PDF）](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)是另一交易所规则源。不同市场/板块/状态、申报单位、价格限制与费用不能只用股票代码前缀粗略推断。
- [上交所 ETF 常见问题](https://www.sse.com.cn/assortment/fund/etf/question/)说明不同 ETF 存在交易机制差异。产品说明仅用于发现问题，最终应核对具体基金、现行规则与账户可卖数量；不把所有 ETF 视为可当日卖出。
- [巨潮资讯](https://www.cninfo.com.cn/)是公司公告与原文核验入口。公司公告、基金管理人文件、交易所信息优先；新闻和社区意见作为待核线索。
- [Tushare 日线文档](https://tushare.pro/document/1?doc_id=27)明确日线盘后更新且停牌期间不提供该接口数据。因此没有当日记录不等于零成交或价格为零；数据尚未到达也不能当作停牌。
- 数据商的[接口权限说明](https://tushare.pro/document/1?doc_id=108)显示不同频率与类别存在权限条件。只把它列为日线候选，尚未确认实时行情、分钟回放、公告、基金净值、规则全量覆盖与使用许可。上线前必须逐项实测和核验许可，不宣称已有可用免费全市场数据。
- 交易所对行情使用与传播有约束，个人研究接入和多用户产品分发须分别确认；技术上可访问不等于可以再分发。

## 3. 理财与 AI 的设计依据

[Investor.gov 资产配置说明](https://www.investor.gov/introduction-investing/getting-started/asset-allocation)将目标期限、风险承受意愿与能力联系起来，也讨论分散和再平衡。对 Grow 的启示是先区分生活资金、未来用途与可承受损失的交易资金；本来源不是中国用户的资产配置比例建议。

[SEC/NASAA/FINRA 的 AI 投资提示](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/artificial-intelligence-fraud)指出 AI 输出可能依赖错误、过时或虚构信息。设计响应是逐项绑定证据、区分事实与推断、显示时效与缺失项，保留用户决定与之后的结果；不能只在报告底部添加免责声明。

## 4. 本项目的独立结论

1. 最小有效产品是「资金边界 → 事前计划 → 实际成交 → 持有观察 → 复盘 → 一项规则调整」。只有记录表或只有 AI 聊天都不足以完成用户目标。
2. 对短线/波段，以单次完整交易、交易日、周为主轴；月度评估资金与策略，季度复核方法，年度复核生活目标。复盘频率和调整交易规则的频率应分开。
3. 第一种实用 AI 能力应是盘后研究、明日条件计划与复盘。盘中数据、提醒和可成交性未验证时，不包装为实时交易助手。
4. 衡量 AI 是否有用，要保留全部建议和采用情况，同时观察预测校准、计划执行、净结果及时间成本；不能用几笔盈利证明策略有效。
5. 观察名单和策略从少量用户自选开始。全市场筛选、复杂回测、分钟回放是后续能力，避免在数据质量未成立前生成大量看似精确的候选。
