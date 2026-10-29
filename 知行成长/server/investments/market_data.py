"""
投资工作台数据源模块

提供统一的行情数据获取接口，支持多种数据源（Tushare、AKShare 等）
"""

import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo


class MarketDataError(Exception):
    """市场数据异常"""
    pass


class RateLimitError(MarketDataError):
    """限流异常"""
    pass


class DataNotFoundError(MarketDataError):
    """数据不存在异常"""
    pass


def canonical_code(value):
    """Keep exchange identity explicit; never default an unknown symbol to Shanghai."""
    if not isinstance(value, str):
        raise MarketDataError('证券代码须为保留前导零的字符串。')
    match = re.fullmatch(r'(?:(sh|sz|bj))?(\d{6})(?:\.(SH|SZ|BJ))?', value, re.I)
    if not match:
        raise MarketDataError('证券代码格式无效。')
    prefix, symbol, suffix = match.groups()
    exchange = 'SH' if symbol[0] in '56' else 'SZ' if symbol[0] in '013' else 'BJ' if symbol[0] in '489' else None
    if exchange is None or any(x and x.upper() != exchange for x in (prefix, suffix)):
        raise MarketDataError('证券代码与市场不一致或尚未覆盖。')
    return symbol + '.' + exchange


def stock_identity(row):
    code = canonical_code(row.get('ts_code') or row.get('code'))
    for field in ('code', 'symbol', 'ts_code'):
        if row.get(field) and canonical_code(row[field]) != code:
            raise MarketDataError('供应商返回的证券身份冲突。')
    market = {'SH':'SSE','SZ':'SZSE','BJ':'BSE'}[code[-2:]]
    if row.get('market') and row['market'] not in (market, code[-2:]):
        raise MarketDataError('供应商返回的市场身份冲突。')
    name = row.get('name')
    if not isinstance(name, str) or not name.strip():
        raise MarketDataError('证券名称缺失。')
    listed = row.get('list_date')
    if listed and str(listed).strip().lower() not in ('nan', 'nat', 'none'):
        try: listed = datetime.strptime(str(listed), '%Y%m%d').date() if len(str(listed)) == 8 else date.fromisoformat(str(listed))
        except ValueError as exc: raise MarketDataError('上市日期无效。') from exc
    else: listed = None
    return {**row, 'ts_code': code, 'symbol': code[:6], 'name': name.strip(),
            'market': market, 'list_date': listed}


def normalized_daily(rows, code, start, end, source):
    """Compatibility cache uses lots and thousands of CNY, for both suppliers."""
    code = canonical_code(code)
    if start > end or (end-start).days > 3660:
        raise MarketDataError('行情日期范围无效或超过十年。')
    output, seen = [], set()
    def number(value, *, positive=False):
        raw = str(value)
        if len(raw) > 100: raise MarketDataError('行情数值过长。')
        try: n = Decimal(raw)
        except (InvalidOperation, ValueError): raise MarketDataError('行情数值缺失或无效。')
        if not n.is_finite() or n < 0 or (positive and n == 0) or n >= Decimal('1e18'):
            raise MarketDataError('行情数值缺失、非有限或超出范围。')
        return n
    def stored(value):
        with localcontext() as ctx:
            ctx.prec = 80
            if value != value.quantize(Decimal('0.0000000001')):
                raise MarketDataError('数值超过缓存十位小数精度，未舍入保存。')
        return format(value,'f')
    for row in rows:
        if row.get('ts_code') and canonical_code(row['ts_code']) != code:
            raise MarketDataError('行情证券身份与请求不一致。')
        raw = row.get('date') if source == 'akshare' else row.get('trade_date')
        try:
            day = raw.date() if isinstance(raw,datetime) else raw if isinstance(raw,date) else datetime.strptime(str(raw),'%Y%m%d').date() if len(str(raw)) == 8 else date.fromisoformat(str(raw))
        except (TypeError,ValueError) as exc: raise MarketDataError('交易日期无效。') from exc
        if not start <= day <= end or day in seen:
            raise MarketDataError('交易日期重复或超出所选范围。')
        prices = {key:number(row.get(key),positive=True) for key in ('open','high','low','close')}
        if not prices['low'] <= min(prices['open'],prices['close']) <= max(prices['open'],prices['close']) <= prices['high']:
            raise MarketDataError('行情高低价与开收盘价冲突。')
        volume = number(row.get('volume') if source == 'akshare' else row.get('vol'))
        amount = number(row.get('amount'))
        if source == 'akshare':
            with localcontext() as ctx:
                ctx.prec = 80
                volume /= 100; amount /= 1000
        output.append({**{k:stored(v) for k,v in prices.items()},'ts_code':code,'trade_date':day,
            'vol':stored(volume),'amount':stored(amount),
            'pre_close':None if row.get('pre_close') is None else stored(number(row['pre_close'],positive=True)),
            'change':None,'pct_chg':None})
        seen.add(day)
    return sorted(output,key=lambda r:r['trade_date'])


class MarketDataProvider:
    """市场数据提供者基类"""

    name: str = "base"

    def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取股票列表"""
        raise NotImplementedError

    def get_daily_data(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """获取日线数据"""
        raise NotImplementedError

    def get_adj_factor(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """获取复权因子"""
        raise NotImplementedError

    def get_financial_data(self, code: str, report_type: str) -> List[Dict[str, Any]]:
        """获取财务数据"""
        raise NotImplementedError

    def get_announcements(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """获取公告数据"""
        raise NotImplementedError


class TushareProvider(MarketDataProvider):
    """Tushare 数据提供者"""

    name = "tushare"

    def __init__(self, token: str):
        """
        初始化 Tushare 提供者

        Args:
            token: Tushare Pro Token
        """
        try:
            import tushare as ts
            self.api = ts.pro_api(token)
        except ImportError:
            raise MarketDataError("需要安装 tushare: pip install tushare")
        except Exception as e:
            raise MarketDataError(f"Tushare 初始化失败: {e}")

    def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取股票列表"""
        try:
            df = self.api.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,symbol,name,area,industry,list_date'
            )
            return [stock_identity(row) for row in df.to_dict('records')]
        except Exception as e:
            raise MarketDataError(f"获取股票列表失败: {e}")

    def get_daily_data(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """
        获取日线数据

        Args:
            code: 股票代码（如 600519.SH）
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            日线数据列表，每条包含：
            - ts_code: 股票代码
            - trade_date: 交易日期
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - close: 收盘价
            - vol: 成交量（手）
            - amount: 成交额（千元）
        """
        try:
            df = self.api.daily(
                ts_code=canonical_code(code),
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )
            return normalized_daily(df.to_dict('records'), code, start_date, end_date, 'tushare')
        except Exception as e:
            raise MarketDataError(f"获取日线数据失败: {e}")

    def get_adj_factor(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """获取复权因子"""
        try:
            df = self.api.adj_factor(
                ts_code=code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )
            return df.to_dict('records')
        except Exception as e:
            raise MarketDataError(f"获取复权因子失败: {e}")

    def get_financial_data(self, code: str, report_type: str) -> List[Dict[str, Any]]:
        """
        获取财务数据

        Args:
            code: 股票代码
            report_type: 报表类型（income/balancesheet/cashflow/fina_indicator）
        """
        try:
            if report_type == 'income':
                df = self.api.income(ts_code=code)
            elif report_type == 'balancesheet':
                df = self.api.balancesheet(ts_code=code)
            elif report_type == 'cashflow':
                df = self.api.cashflow(ts_code=code)
            elif report_type == 'fina_indicator':
                df = self.api.fina_indicator(ts_code=code)
            else:
                raise MarketDataError(f"不支持的报表类型: {report_type}")
            return df.to_dict('records')
        except Exception as e:
            raise MarketDataError(f"获取财务数据失败: {e}")

    def get_announcements(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """获取公告数据"""
        try:
            df = self.api.anns(
                ts_code=code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )
            return df.to_dict('records')
        except Exception as e:
            raise MarketDataError(f"获取公告数据失败: {e}")


class AKShareProvider(MarketDataProvider):
    """AKShare 数据提供者（备选方案）"""

    name = "akshare"

    def __init__(self):
        """初始化 AKShare 提供者"""
        try:
            import akshare as ak
            self.ak = ak
        except ImportError:
            raise MarketDataError("需要安装 akshare: pip install akshare")

    def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取股票列表"""
        try:
            df = self.ak.stock_info_a_code_name()
            return [stock_identity(row) for row in df.to_dict('records')]
        except Exception as e:
            raise MarketDataError(f"获取股票列表失败: {e}")

    def get_daily_data(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """获取日线数据"""
        try:
            canonical = canonical_code(code)
            if canonical.endswith('.BJ'):
                raise MarketDataError('当前新浪日线适配未覆盖北交所，请显式选择其他已授权来源。')
            df = self.ak.stock_zh_a_daily(symbol=canonical[-2:].lower()+canonical[:6],
                start_date=start_date.strftime('%Y%m%d'), end_date=end_date.strftime('%Y%m%d'), adjust='')
            return normalized_daily(df.to_dict('records'), canonical, start_date, end_date, 'akshare')
        except Exception as e:
            raise MarketDataError(f"获取日线数据失败: {e}")

    def get_adj_factor(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """AKShare 不直接提供复权因子，返回空列表"""
        return []

    def get_financial_data(self, code: str, report_type: str) -> List[Dict[str, Any]]:
        """AKShare 财务数据接口"""
        try:
            pure_code = code.split('.')[0]
            if report_type == 'income':
                df = self.ak.stock_financial_report_sina(stock=pure_code, symbol="利润表")
            elif report_type == 'balancesheet':
                df = self.ak.stock_financial_report_sina(stock=pure_code, symbol="资产负债表")
            elif report_type == 'cashflow':
                df = self.ak.stock_financial_report_sina(stock=pure_code, symbol="现金流量表")
            else:
                raise MarketDataError(f"不支持的报表类型: {report_type}")
            return df.to_dict('records')
        except Exception as e:
            raise MarketDataError(f"获取财务数据失败: {e}")

    def get_announcements(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """AKShare 公告数据接口"""
        # AKShare 公告接口较复杂，暂时返回空列表
        return []


def get_provider(source: str = None, **kwargs) -> MarketDataProvider:
    """
    获取数据提供者

    Args:
        source: 数据源名称（tushare/akshare），默认从环境变量读取
        **kwargs: 传递给提供者的参数

    Returns:
        MarketDataProvider 实例
    """
    if source is None:
        source = os.getenv('MARKET_DATA_SOURCE', 'akshare')

    if source == 'tushare':
        token = kwargs.get('token') or os.getenv('TUSHARE_TOKEN')
        if not token:
            raise MarketDataError("需要提供 TUSHARE_TOKEN")
        return TushareProvider(token)
    elif source == 'akshare':
        return AKShareProvider()
    else:
        raise MarketDataError(f"不支持的数据源: {source}")


# 便捷函数

def get_stock_list(source: str = None, **kwargs) -> List[Dict[str, Any]]:
    """获取股票列表"""
    provider = get_provider(source, **kwargs)
    return provider.get_stock_list()


def get_daily_data(code: str, start_date: date, end_date: date,
                   source: str = None, **kwargs) -> List[Dict[str, Any]]:
    """获取日线数据"""
    provider = get_provider(source, **kwargs)
    return provider.get_daily_data(code, start_date, end_date)


def get_adj_factor(code: str, start_date: date, end_date: date,
                   source: str = None, **kwargs) -> List[Dict[str, Any]]:
    """获取复权因子"""
    provider = get_provider(source, **kwargs)
    return provider.get_adj_factor(code, start_date, end_date)
