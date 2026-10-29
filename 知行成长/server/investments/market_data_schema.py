"""
投资工作台市场数据表结构
"""

TABLES = '''
-- 股票基础信息表（缓存）
CREATE TABLE IF NOT EXISTS investment_stock_basic (
    ts_code TEXT PRIMARY KEY,  -- 股票代码（如 600519.SH）
    symbol TEXT NOT NULL,  -- 纯代码（如 600519）
    name TEXT NOT NULL,  -- 股票名称
    area TEXT,  -- 地域
    industry TEXT,  -- 行业
    list_date DATE,  -- 上市日期
    market TEXT,  -- 市场（SSE/SZSE/BSE）
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stock_basic_industry ON investment_stock_basic(industry);

-- 日线数据表（缓存）
CREATE TABLE IF NOT EXISTS investment_daily_data (
    ts_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open NUMERIC(28,10),
    high NUMERIC(28,10),
    low NUMERIC(28,10),
    close NUMERIC(28,10),
    pre_close NUMERIC(28,10),
    change_amount NUMERIC(28,10),
    change_pct NUMERIC(28,10),
    vol NUMERIC(28,10),  -- 成交量（手）
    amount NUMERIC(28,10),  -- 成交额（千元）
    source TEXT NOT NULL,  -- 数据来源
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_data_date ON investment_daily_data(trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_data_code ON investment_daily_data(ts_code);

-- 复权因子表
CREATE TABLE IF NOT EXISTS investment_adj_factor (
    ts_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    adj_factor NUMERIC(28,10) NOT NULL,
    source TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_adj_factor_date ON investment_adj_factor(trade_date);

-- 财务指标表
CREATE TABLE IF NOT EXISTS investment_fina_indicator (
    ts_code TEXT NOT NULL,
    ann_date DATE,  -- 公告日期
    end_date DATE NOT NULL,  -- 报告期
    eps NUMERIC(28,10),  -- 每股收益
    dt_eps NUMERIC(28,10),  -- 稀释每股收益
    bps NUMERIC(28,10),  -- 每股净资产
    roe NUMERIC(28,10),  -- 净资产收益率
    roa NUMERIC(28,10),  -- 总资产收益率
    gross_profit_margin NUMERIC(28,10),  -- 毛利率
    net_profit_margin NUMERIC(28,10),  -- 净利率
    revenue NUMERIC(28,10),  -- 营业收入
    net_profit NUMERIC(28,10),  -- 净利润
    source TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts_code, end_date)
);
CREATE INDEX IF NOT EXISTS idx_fina_indicator_end_date ON investment_fina_indicator(end_date);

-- 公告数据表
CREATE TABLE IF NOT EXISTS investment_announcements (
    id TEXT PRIMARY KEY,
    ts_code TEXT NOT NULL,
    ann_date DATE NOT NULL,  -- 公告日期
    title TEXT NOT NULL,  -- 公告标题
    content TEXT,  -- 公告内容（可选）
    ann_type TEXT,  -- 公告类型
    source_url TEXT,  -- 来源链接
    source TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_announcements_code ON investment_announcements(ts_code);
CREATE INDEX IF NOT EXISTS idx_announcements_date ON investment_announcements(ann_date);

-- 数据同步日志表
CREATE TABLE IF NOT EXISTS investment_data_sync_log (
    id SERIAL PRIMARY KEY,
    data_type TEXT NOT NULL,  -- 数据类型（stock_basic/daily/adj/fina/announcements）
    ts_code TEXT,  -- 股票代码（可选，为空表示全市场）
    start_date DATE,
    end_date DATE,
    record_count INTEGER,  -- 同步记录数
    status TEXT NOT NULL,  -- 状态（success/failed）
    error_message TEXT,
    source TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sync_log_type ON investment_data_sync_log(data_type);
CREATE INDEX IF NOT EXISTS idx_sync_log_date ON investment_data_sync_log(started_at);
'''
