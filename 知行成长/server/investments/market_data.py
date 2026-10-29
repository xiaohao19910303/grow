"""
投资工作台数据源模块

提供统一的行情数据获取接口，支持多种数据源（Tushare、AKShare 等）
"""

import os
from datetime import date, datetime
from decimal import Decimal
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
            return df.to_dict('records')
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
                ts_code=code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )
            return df.to_dict('records')
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
            return df.to_dict('records')
        except Exception as e:
            raise MarketDataError(f"获取股票列表失败: {e}")

    def get_daily_data(self, code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """获取日线数据"""
        try:
            # AKShare 的代码格式不带后缀
            pure_code = code.split('.')[0]
            df = self.ak.stock_zh_a_daily(symbol=pure_code)
            # 过滤日期范围
            df['date'] = df['date'].astype(str).str[:10]
            mask = (df['date'] >= start_date.strftime('%Y-%m-%d')) & \
                   (df['date'] <= end_date.strftime('%Y-%m-%d'))
            df = df[mask]
            return df.to_dict('records')
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
