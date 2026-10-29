"""Configuration requirements, never a claim that a secret or entitlement was tested."""

def requirements():
    from .rules import RULEBOOK_ID,REVIEW_UNTIL
    return {
        'automatic_reference':{'enabled':True,'rulebook_id':RULEBOOK_ID,'review_until':REVIEW_UNTIL,
            'credentials':[],'scope':'沪深2026日历及部分竞价限价买入规则；动态状态和ETF机制未知不补造'},
        'manual_csv':{'enabled':True,'credentials':[],'requires':['合法来源','量额单位','复权口径','资料时点']},
        'offline_replay':{'enabled':True,'credentials':[],'scope':'本人导入一分钟未复权路径的事后复盘；不含实时、模拟成交或历史当时可知承诺'},
        'forward_observation':{'enabled':True,'credentials':[],'scope':'事前冻结观察协议、保留全部相符策略版本样本和费用压力；非参数回测'},
        'condition_drill':{'enabled':True,'credentials':[],'scope':'本人分钟CSV与核对资料的离线价格阈值、延迟及去重演练；仅页面模拟，不发送通知'},
        'execution_study':{'enabled':True,'credentials':[],'scope':'声明分钟路径的一笔假设撮合及费用验证；非历史策略回测或样本外验证'},
        'backtest':{'enabled':True,'source_verified':False,'scope':'研究工具：本人声明完整的CSV/接口资料，收盘信号下一开盘、成本约束、样本外与有限参数试验；缺规则/时间表不输出绩效'},
        'intraday_alerts':{'enabled':True,'background':False,'source_verified':False,'scope':'本人配置报价接口并显式开启的网页内轮询；时效、交易时段及冷却校验；通知须浏览器授权，关闭页面即停止'},
        'akshare_daily':{'enabled':True,'verified':False,'adapter':'AKShare / 东方财富','credentials':[],
            'required_endpoints':['stock_zh_a_hist（股票）','fund_etf_hist_em（ETF）'],
            'requirements':['服务端安装锁定依赖','沪深标的身份与有效公开日历','本人用途与上游使用范围核对'],
            'limits':'未复权日线，最多90个自然日；45秒超时停止，空数据不覆盖旧快照，不自动换源',
            'not_included':['实时/分钟','场外基金净值','全市场自动更新','商业再分发许可']},
        'daily':{'verified':False,'adapter':'Tushare Pro','credentials':['token'],
            'required_endpoints':['daily（股票）','fund_daily（ETF，按需）'],
            'calendar_options':{'public_reference':'覆盖范围内无需trade_cal权限','provider':'需另有trade_cal权限'},
            'requirements':['账号具体接口权限与配额','本人用途和存储许可','真实成功/缺权限/空数据样例'],
            'not_included':['场外基金净值','公告','复权因子','历史证券状态','实时或分钟']},
        'ai':{'verified':False,'credentials':['api_base_url','api_key','model_name'],
            'protocol':'HTTPS OpenAI兼容 /chat/completions，流式返回并能输出要求的JSON',
            'requirements':['模型在本人账号可用','额度/账单预算','允许所选私人资料发送到该目的地'],
            'storage':'浏览器按账号配置；提交时内存使用，服务端不保存密钥',
            'cost':'一次分析含主分析与同模型反证两次请求；真实调用仅在本人显式发送后发生'},
        'realtime':{'enabled':False,'credentials':[],
            'requirements':['另选并授权分钟/实时供应商','历史分钟与逐笔时序覆盖','时区/延迟/断流阈值','存储与使用许可'],
            'reason':'未内置已验收的实时供应商；研究工具支持本人接口报价和历史分钟CSV，接口须另行核对时效与许可。'},
        'unneeded':['券商登录密码','交易密码','短信验证码','自动下单权限'],
        'release':{'full_v1_verified':False,'p2_enabled':True}}
