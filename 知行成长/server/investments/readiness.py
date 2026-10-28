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
        'backtest':{'enabled':False,'reason':'受约束撮合、样本外参数重跑和历史覆盖尚未交付。'},
        'intraday_alerts':{'enabled':False,'reason':'已提供独立离线演练；实时适配、自动调度与实际通知未验收，不产生盘中交易提醒。'},
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
            'reason':'当前无分钟/实时适配；提供Token本身不会开放此能力。'},
        'unneeded':['券商登录密码','交易密码','短信验证码','自动下单权限'],
        'release':{'full_v1_verified':False,'p2_enabled':False}}
