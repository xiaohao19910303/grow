#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
市场数据同步脚本

用于同步股票基础信息、日线数据、复权因子、财务数据等
"""

import sys
import os
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

# 添加 server 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '知行成长', 'server'))

import db
from investments.market_data import get_provider, MarketDataError
from investments.market_data_schema import TABLES


def initialize_tables():
    """初始化数据表"""
    print("初始化数据表...")
    with db.connect() as c:
        c.executescript(TABLES)
    print("✅ 数据表初始化完成")


def sync_stock_list(source: str = None, **kwargs):
    """同步股票基础信息"""
    print("\n同步股票基础信息...")

    try:
        provider = get_provider(source, **kwargs)
        stocks = provider.get_stock_list()

        print(f"获取到 {len(stocks)} 只股票")

        with db.connect() as c:
            c.execute("BEGIN")

            count = 0
            for stock in stocks:
                ts_code = stock.get('ts_code') or stock.get('code')
                if not ts_code:
                    continue

                # 确定市场
                if ts_code.endswith('.SH'):
                    market = 'SSE'
                elif ts_code.endswith('.SZ'):
                    market = 'SZSE'
                elif ts_code.endswith('.BJ'):
                    market = 'BSE'
                else:
                    market = 'SSE'  # 默认

                symbol = ts_code.split('.')[0]
                name = stock.get('name', '')
                area = stock.get('area')
                industry = stock.get('industry')
                list_date = stock.get('list_date')

                c.execute('''
                    INSERT INTO investment_stock_basic (ts_code, symbol, name, area, industry, list_date, market, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NOW())
                    ON CONFLICT (ts_code) DO UPDATE SET
                        name = EXCLUDED.name,
                        area = EXCLUDED.area,
                        industry = EXCLUDED.industry,
                        list_date = EXCLUDED.list_date,
                        market = EXCLUDED.market,
                        updated_at = NOW()
                ''', (ts_code, symbol, name, area, industry, list_date, market))
                count += 1

            c.execute("COMMIT")

            # 记录同步日志
            c.execute('''
                INSERT INTO investment_data_sync_log (data_type, record_count, status, source, started_at, completed_at)
                VALUES ('stock_basic', ?, 'success', ?, NOW(), NOW())
            ''', (count, provider.name))

        print(f"✅ 同步完成，共 {count} 只股票")
        return count

    except Exception as e:
        print(f"❌ 同步失败: {e}")

        # 记录失败日志
        try:
            with db.connect() as c:
                c.execute('''
                    INSERT INTO investment_data_sync_log (data_type, status, error_message, source, started_at)
                    VALUES ('stock_basic', 'failed', ?, ?, NOW())
                ''', (str(e), source or 'unknown'))
        except:
            pass

        return 0


def sync_daily_data(ts_code: str, start_date: date, end_date: date,
                   source: str = None, **kwargs):
    """同步日线数据"""
    print(f"\n同步日线数据: {ts_code} ({start_date} ~ {end_date})")

    try:
        provider = get_provider(source, **kwargs)
        data = provider.get_daily_data(ts_code, start_date, end_date)

        print(f"获取到 {len(data)} 条日线数据")

        with db.connect() as c:
            c.execute("BEGIN")

            count = 0
            for row in data:
                trade_date = row.get('trade_date')
                if isinstance(trade_date, str):
                    trade_date = datetime.strptime(trade_date, '%Y%m%d').date()
                elif isinstance(trade_date, datetime):
                    trade_date = trade_date.date()

                c.execute('''
                    INSERT INTO investment_daily_data
                    (ts_code, trade_date, open, high, low, close, pre_close, change_amount, change_pct, vol, amount, source, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        pre_close = EXCLUDED.pre_close,
                        change_amount = EXCLUDED.change_amount,
                        change_pct = EXCLUDED.change_pct,
                        vol = EXCLUDED.vol,
                        amount = EXCLUDED.amount,
                        source = EXCLUDED.source,
                        fetched_at = NOW()
                ''', (
                    ts_code,
                    trade_date,
                    row.get('open'),
                    row.get('high'),
                    row.get('low'),
                    row.get('close'),
                    row.get('pre_close'),
                    row.get('change'),
                    row.get('pct_chg'),
                    row.get('vol'),
                    row.get('amount'),
                    provider.name
                ))
                count += 1

            c.execute("COMMIT")

            # 记录同步日志
            c.execute('''
                INSERT INTO investment_data_sync_log (data_type, ts_code, start_date, end_date, record_count, status, source, started_at, completed_at)
                VALUES ('daily', ?, ?, ?, ?, 'success', ?, NOW(), NOW())
            ''', (ts_code, start_date, end_date, count, provider.name))

        print(f"✅ 同步完成，共 {count} 条记录")
        return count

    except Exception as e:
        print(f"❌ 同步失败: {e}")

        # 记录失败日志
        try:
            with db.connect() as c:
                c.execute('''
                    INSERT INTO investment_data_sync_log (data_type, ts_code, start_date, end_date, status, error_message, source, started_at)
                    VALUES ('daily', ?, ?, ?, 'failed', ?, ?, NOW())
                ''', (ts_code, start_date, end_date, str(e), source or 'unknown'))
        except:
            pass

        return 0


def sync_adj_factor(ts_code: str, start_date: date, end_date: date,
                   source: str = None, **kwargs):
    """同步复权因子"""
    print(f"\n同步复权因子: {ts_code} ({start_date} ~ {end_date})")

    try:
        provider = get_provider(source, **kwargs)
        data = provider.get_adj_factor(ts_code, start_date, end_date)

        print(f"获取到 {len(data)} 条复权因子数据")

        with db.connect() as c:
            c.execute("BEGIN")

            count = 0
            for row in data:
                trade_date = row.get('trade_date')
                if isinstance(trade_date, str):
                    trade_date = datetime.strptime(trade_date, '%Y%m%d').date()
                elif isinstance(trade_date, datetime):
                    trade_date = trade_date.date()

                c.execute('''
                    INSERT INTO investment_adj_factor (ts_code, trade_date, adj_factor, source, fetched_at)
                    VALUES (?, ?, ?, ?, NOW())
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                        adj_factor = EXCLUDED.adj_factor,
                        source = EXCLUDED.source,
                        fetched_at = NOW()
                ''', (ts_code, trade_date, row.get('adj_factor'), provider.name))
                count += 1

            c.execute("COMMIT")

            # 记录同步日志
            c.execute('''
                INSERT INTO investment_data_sync_log (data_type, ts_code, start_date, end_date, record_count, status, source, started_at, completed_at)
                VALUES ('adj_factor', ?, ?, ?, ?, 'success', ?, NOW(), NOW())
            ''', (ts_code, start_date, end_date, count, provider.name))

        print(f"✅ 同步完成，共 {count} 条记录")
        return count

    except Exception as e:
        print(f"❌ 同步失败: {e}")

        # 记录失败日志
        try:
            with db.connect() as c:
                c.execute('''
                    INSERT INTO investment_data_sync_log (data_type, ts_code, start_date, end_date, status, error_message, source, started_at)
                    VALUES ('adj_factor', ?, ?, ?, 'failed', ?, ?, NOW())
                ''', (ts_code, start_date, end_date, str(e), source or 'unknown'))
        except:
            pass

        return 0


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='市场数据同步脚本')
    parser.add_argument('--source', choices=['tushare', 'akshare'], default='akshare',
                       help='数据源（默认：akshare）')
    parser.add_argument('--token', help='Tushare Token（如果使用 tushare）')
    parser.add_argument('--action', choices=['init', 'stocks', 'daily', 'adj'],
                       default='init', help='执行动作（默认：init）')
    parser.add_argument('--code', help='股票代码（用于 daily/adj）')
    parser.add_argument('--start', help='开始日期 YYYY-MM-DD（用于 daily/adj）')
    parser.add_argument('--end', help='结束日期 YYYY-MM-DD（用于 daily/adj）')

    args = parser.parse_args()

    # 初始化表结构
    if args.action == 'init':
        initialize_tables()
        return

    # 准备参数
    kwargs = {}
    if args.token:
        kwargs['token'] = args.token

    # 执行动作
    if args.action == 'stocks':
        sync_stock_list(args.source, **kwargs)

    elif args.action == 'daily':
        if not args.code:
            print("❌ 需要指定股票代码（--code）")
            return

        start_date = datetime.strptime(args.start, '%Y-%m-%d').date() if args.start else date(2020, 1, 1)
        end_date = datetime.strptime(args.end, '%Y-%m-%d').date() if args.end else date.today()

        # 转换代码格式
        code = args.code
        if not code.endswith(('.SH', '.SZ', '.BJ')):
            # 自动添加后缀
            if code.startswith('6'):
                code += '.SH'
            elif code.startswith('0') or code.startswith('3'):
                code += '.SZ'
            elif code.startswith('8') or code.startswith('4'):
                code += '.BJ'

        sync_daily_data(code, start_date, end_date, args.source, **kwargs)

    elif args.action == 'adj':
        if not args.code:
            print("❌ 需要指定股票代码（--code）")
            return

        start_date = datetime.strptime(args.start, '%Y-%m-%d').date() if args.start else date(2020, 1, 1)
        end_date = datetime.strptime(args.end, '%Y-%m-%d').date() if args.end else date.today()

        # 转换代码格式
        code = args.code
        if not code.endswith(('.SH', '.SZ', '.BJ')):
            if code.startswith('6'):
                code += '.SH'
            elif code.startswith('0') or code.startswith('3'):
                code += '.SZ'
            elif code.startswith('8') or code.startswith('4'):
                code += '.BJ'

        sync_adj_factor(code, start_date, end_date, args.source, **kwargs)


if __name__ == '__main__':
    main()
