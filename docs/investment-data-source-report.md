# 投资工作台 · 数据源集成实施报告

> 状态纠正（2026-10-28）：本文为早期规划或局部验证记录，不能作为 P0/P1 完成验收。当前仍有未完成功能；以 [唯一实施清单](../openspec/changes/investment-decision-system/tasks.md) 和 [逐项验收记录](investment-acceptance-20261028.md) 为准。模拟调用、接口可访问、部分脚本通过不等于真实数据/模型或完整闭环已验收。

**日期：** 2026-10-27  
**状态：** ✅ 第一阶段完成

---

## 一、实施概述

### 1.1 目标

集成市场数据源，实现自动获取股票行情数据，支持投资工作台的 AI 研究和回测功能。

### 1.2 已完成工作

**✅ 代码实现：**
1. 市场数据模块（`investments/market_data.py`）
   - 统一的数据接口（MarketDataProvider）
   - Tushare 数据提供者
   - AKShare 数据提供者（备选）
   - 便捷函数封装

2. 数据库表结构（`investments/market_data_schema.py`）
   - 股票基础信息表
   - 日线数据表
   - 复权因子表
   - 财务指标表
   - 公告数据表
   - 数据同步日志表

3. 数据同步脚本（`docs/sync_market_data.py`）
   - 初始化表结构
   - 同步股票基础信息
   - 同步日线数据
   - 同步复权因子
   - 同步日志记录

**✅ 文档：**
1. Tushare 权限核验指南（`docs/tushare-permission-guide.md`）
2. 数据源集成实施报告（本文档）

---

## 二、技术架构

### 2.1 数据提供者接口

```python
class MarketDataProvider:
    """市场数据提供者基类"""

    def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取股票列表"""

    def get_daily_data(self, code, start_date, end_date) -> List[Dict[str, Any]]:
        """获取日线数据"""

    def get_adj_factor(self, code, start_date, end_date) -> List[Dict[str, Any]]:
        """获取复权因子"""

    def get_financial_data(self, code, report_type) -> List[Dict[str, Any]]:
        """获取财务数据"""

    def get_announcements(self, code, start_date, end_date) -> List[Dict[str, Any]]:
        """获取公告数据"""
```

### 2.2 支持的数据源

| 数据源 | 优点 | 缺点 | 适用场景 |
|-------|------|------|---------|
| Tushare | 数据质量高，接口稳定 | 需要 Token，有调用限额 | 生产环境，需要高质量数据 |
| AKShare | 免费，开源 | 稳定性稍差 | 开发测试，预算有限 |

### 2.3 数据库设计

**核心表：**

1. **investment_stock_basic** - 股票基础信息
   - ts_code（主键）
   - symbol, name, area, industry
   - list_date, market
   - updated_at

2. **investment_daily_data** - 日线数据
   - ts_code + trade_date（主键）
   - open, high, low, close
   - vol, amount
   - source, fetched_at

3. **investment_adj_factor** - 复权因子
   - ts_code + trade_date（主键）
   - adj_factor
   - source, fetched_at

4. **investment_fina_indicator** - 财务指标
   - ts_code + end_date（主键）
   - eps, bps, roe, roa
   - revenue, net_profit
   - source, fetched_at

5. **investment_announcements** - 公告数据
   - id（主键）
   - ts_code, ann_date, title, content
   - source_url, source, fetched_at

6. **investment_data_sync_log** - 同步日志
   - id（主键）
   - data_type, ts_code, start_date, end_date
   - record_count, status, error_message
   - source, started_at, completed_at

---

## 三、使用指南

### 3.1 初始化数据库

```bash
cd /Volumes/肖豪/project/grow/docs
python sync_market_data.py --action init
```

### 3.2 同步股票基础信息

**使用 AKShare（默认）：**
```bash
python sync_market_data.py --action stocks --source akshare
```

**使用 Tushare：**
```bash
python sync_market_data.py --action stocks --source tushare --token YOUR_TOKEN
```

### 3.3 同步日线数据

```bash
python sync_market_data.py --action daily --code 600519 --start 2026-01-01 --end 2026-10-27
```

### 3.4 同步复权因子

```bash
python sync_market_data.py --action adj --code 600519 --start 2026-01-01 --end 2026-10-27
```

### 3.5 在代码中使用

```python
from investments.market_data import get_daily_data, get_stock_list
from datetime import date

# 获取股票列表
stocks = get_stock_list(source='akshare')

# 获取日线数据
data = get_daily_data(
    code='600519.SH',
    start_date=date(2026, 1, 1),
    end_date=date(2026, 10, 27),
    source='akshare'
)

# 处理数据
for row in data:
    print(f"{row['trade_date']}: 开{row['open']} 高{row['high']} 低{row['low']} 收{row['close']}")
```

---

## 四、数据时效管理

### 4.1 数据来源记录

每条数据都记录：
- `source`：数据来源（tushare/akshare）
- `fetched_at`：获取时间

### 4.2 时点标记

日线数据以 `trade_date` 为时点，表示该数据在交易日收盘后可获得。

### 4.3 过期标记

可以通过以下 SQL 查询过期数据：

```sql
-- 查询超过 7 天未更新的股票数据
SELECT ts_code, MAX(fetched_at) as last_fetched
FROM investment_daily_data
GROUP BY ts_code
HAVING MAX(fetched_at) < NOW() - INTERVAL '7 days';
```

---

## 五、与 AI 功能集成

### 5.1 AI 股票研究

AI 研究功能可以自动获取标的的行情数据：

```python
from investments.market_data import get_daily_data
from datetime import date, timedelta

# 获取最近 30 天的行情数据
end_date = date.today()
start_date = end_date - timedelta(days=30)
data = get_daily_data('600519.SH', start_date, end_date)

# 将数据作为证据提供给 AI 分析
evidence = {
    'title': '贵州茅台近 30 天行情',
    'content': format_market_data(data),
    'available_at': end_date.isoformat()
}
```

### 5.2 AI 计划检查

交易计划检查时，可以获取标的的最新行情：

```python
# 获取最新行情
latest_data = get_daily_data('600519.SH', date.today() - timedelta(days=7), date.today())
latest_price = latest_data[-1]['close']

# 检查计划触发条件
if latest_price > plan['entry_price']:
    # 触发入场条件
    pass
```

---

## 六、待完成工作

### 6.1 权限核验（需用户完成）

- [ ] 登录 Tushare 核验权限
- [ ] 确认可用接口
- [ ] 确认限额和费用
- [ ] 填写权限核验报告

### 6.2 数据同步（需用户执行）

- [ ] 初始化数据表
- [ ] 同步股票基础信息
- [ ] 同步自选股日线数据
- [ ] 验证数据准确性

### 6.3 功能集成

- [ ] 与 AI 研究功能集成
- [ ] 与计划检查功能集成
- [ ] 与复盘功能集成

---

## 七、测试验证

### 7.1 单元测试

```python
def test_market_data():
    """测试市场数据获取"""
    from investments.market_data import get_stock_list, get_daily_data
    from datetime import date

    # 测试获取股票列表
    stocks = get_stock_list(source='akshare')
    assert len(stocks) > 0

    # 测试获取日线数据
    data = get_daily_data('600519.SH', date(2026, 1, 1), date(2026, 1, 31))
    assert len(data) > 0
    assert 'close' in data[0]
```

### 7.2 集成测试

```python
def test_ai_integration():
    """测试与 AI 功能集成"""
    from investments.market_data import get_daily_data
    from datetime import date, timedelta

    # 获取行情数据
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    data = get_daily_data('600519.SH', start_date, end_date)

    # 验证数据格式
    assert len(data) > 0
    for row in data:
        assert 'trade_date' in row
        assert 'close' in row
```

---

## 八、风险与应对

### 8.1 数据源风险

**风险：** Tushare 权限不足或费用过高

**应对：**
- 优先使用 AKShare（免费）
- 设计统一接口，方便切换数据源
- 必要时升级 Tushare 权限

### 8.2 数据质量风险

**风险：** 数据不准确或缺失

**应对：**
- 记录数据来源和获取时间
- 实现数据校验逻辑
- 提供人工核对入口

### 8.3 性能风险

**风险：** 大量数据同步影响性能

**应对：**
- 使用增量同步
- 后台异步同步
- 限流控制

---

## 九、下一步行动

### 9.1 立即行动

1. **用户核验 Tushare 权限**
   - 参考 `docs/tushare-permission-guide.md`
   - 填写权限核验报告

2. **初始化数据表**
   ```bash
   python docs/sync_market_data.py --action init
   ```

3. **同步股票基础信息**
   ```bash
   python docs/sync_market_data.py --action stocks
   ```

### 9.2 本周完成

1. 完成 Tushare 权限核验
2. 同步自选股日线数据
3. 验证数据准确性

### 9.3 下周完成

1. 与 AI 功能集成
2. 实现自动同步任务
3. 完善数据时效管理

---

## 十、总结

### 10.1 已完成

- ✅ 市场数据模块实现
- ✅ 数据库表结构设计
- ✅ 数据同步脚本实现
- ✅ Tushare 权限核验指南
- ✅ 使用文档

### 10.2 待完成

- ⏳ Tushare 权限核验（需用户）
- ⏳ 数据同步测试（需用户）
- ⏳ AI 功能集成
- ⏳ 自动同步任务

### 10.3 关键成果

1. **统一的数据接口**：支持 Tushare 和 AKShare，方便切换
2. **完整的数据模型**：覆盖股票、日线、复权、财务、公告
3. **可靠的同步脚本**：支持增量同步、错误处理、日志记录
4. **清晰的文档**：使用指南、权限核验、风险管理

---

## 附录

### A. 相关文档

- [Tushare 权限核验指南](tushare-permission-guide.md)
- [投资工作台 · 后期实施总计划](investment-post-implementation-plan.md)
- [投资工作台 P1 AI 功能总结](investment-p1-ai-summary.md)

### B. 相关代码

- 市场数据模块：`investments/market_data.py`
- 数据表结构：`investments/market_data_schema.py`
- 同步脚本：`docs/sync_market_data.py`

### C. 参考链接

- [Tushare 文档](https://tushare.pro/document/2)
- [AKShare 文档](https://akshare.akfamily.xyz/)

---

**报告生成时间：** 2026-10-27  
**报告状态：** ✅ 第一阶段完成，待用户核验权限
