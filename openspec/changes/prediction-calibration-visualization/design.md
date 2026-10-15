# 技术设计：预测校准可视化

## 架构概览

```
server/
├── predictions/
│   ├── __init__.py
│   ├── store.py      # 数据层：校准统计 + 分析查询
│   └── api.py        # API 路由：/api/predictions
├── app.py            # 注册 predictions router（增强现有）
└── static/
    └── index.html    # 前端：预测分析视图
```

注意：predictions 表已存在于 app.py 的 SCHEMA 中，这里只是增加分析 API，不修改表结构。

## API 设计

### 校准数据

```
GET /api/predictions/calibration
  响应:
    {
      "buckets": [
        {"range": "0-10", "min": 0, "max": 10, "count": 5, "correct": 1, "rate": 0.20},
        {"range": "10-20", "min": 10, "max": 20, "count": 3, "correct": 0, "rate": 0.00},
        ...
        {"range": "90-100", "min": 90, "max": 100, "count": 12, "correct": 10, "rate": 0.83}
      ],
      "total": 50,
      "resolved": 45,  -- 非 pending 的数量
      "pending": 5
    }
```

分桶逻辑：
- 10 个桶：0-10, 10-20, ..., 90-100
- 每个桶统计：总数、正确数、准确率
- 只统计 result 为 'correct' 或 'incorrect' 的记录（排除 'pending'）

### 准确度统计

```
GET /api/predictions/stats
  响应:
    {
      "total": 50,
      "resolved": 45,
      "correct": 32,
      "accuracy": 0.71,  -- correct / resolved
      "pending": 5,
      "brier_score": 0.18,  -- 均方误差，越小越好
      "avg_probability": 68,  -- 平均自报概率
      "calibration_error": 0.12  -- 校准误差（桶准确率与桶中位数的差的绝对值平均）
    }
```

Brier Score 计算：
```python
brier = sum((p/100 - outcome)**2 for p, outcome in predictions) / len(predictions)
# outcome: correct=1, incorrect=0
```

Calibration Error：
```python
calibration_error = mean(abs(bucket_rate - bucket_median_prob/100) for bucket in buckets if bucket.count > 0)
```

### 过度自信事件

```
GET /api/predictions/overconfident
  查询参数:
    - threshold: int (默认80)
  响应:
    [
      {"id": 1, "date": "2026-09-01", "statement": "...", "probability": 90, "result": "incorrect"},
      ...
    ]
```

筛选逻辑：
- probability >= threshold (默认 80%)
- result = 'incorrect'
- 按 probability 降序排列

### 时间趋势

```
GET /api/predictions/trend
  查询参数:
    - window: int (默认10，滚动窗口大小)
  响应:
    {
      "trend": [
        {"index": 1, "date": "2026-09-01", "accuracy": 0.67, "window_size": 10},
        {"index": 2, "date": "2026-09-05", "accuracy": 0.70, "window_size": 10},
        ...
      ],
      "total_windows": 35
    }
```

滚动准确率：
- 按日期排序所有 resolved predictions
- 每 window 条计算一次准确率
- 返回时间序列

## 前端设计

### 仪表盘"预测校准"区域

位置：在 view-overview 中，紧跟"错误模式"区域之后。

```html
<div class="section">
  <h2>预测校准</h2>
  <div id="predictionCalibrationCards" class="cards"></div>
  <div id="predictionCalibrationChart"></div>
</div>
```

**统计卡片**
- 总预测数
- 准确率（百分比）
- Brier Score（保留2位小数）
- 待判定数

**校准曲线**
- SVG 散点图 + 对角线
- X 轴：自报概率（0-100%）
- Y 轴：实际发生率（0-100%）
- 每个桶一个点（大小表示样本量）
- 45° 对角线（理想校准）

### 预测分析页面

位置：在 view-predictions 中，现有表格上方新增分析区域。

```html
<div id="view-predictions">
  <div class="section">
    <h2>预测校准分析</h2>
    <div id="predictionAnalysisCalibration"></div>
    <div id="predictionAnalysisDistribution" style="margin-top:20px"></div>
    <div id="predictionAnalysisOverconfident" style="margin-top:20px"></div>
    <div id="predictionAnalysisTrend" style="margin-top:20px"></div>
  </div>
  
  <!-- 现有的预测表格 -->
  <div class="section">
    <h2>预测校准</h2>
    ...
  </div>
</div>
```

**校准曲线（大图）**
- 同仪表盘，但更大
- 悬停显示桶详情

**置信度分布**
- 直方图：X 轴为概率桶（0-10, 10-20, ...），Y 轴为数量
- 显示用户倾向于给出什么概率

**过度自信事件列表**
- 表格：日期、预测内容、自报概率、结果
- 按概率降序

**时间趋势**
- 折线图：X 轴为时间（第 N 个窗口），Y 轴为滚动准确率
- 显示校准是否随时间改善

## 实现细节

### 后端 store.py

```python
class PredictionStats:
    def get_calibration(self) -> dict:
        """分桶统计校准数据"""
        buckets = []
        for i in range(10):
            min_p = i * 10
            max_p = (i + 1) * 10
            # 查询该桶的 predictions
            # 统计 count, correct, rate
            buckets.append({...})
        return {"buckets": buckets, "total": ..., "resolved": ..., "pending": ...}
    
    def get_accuracy_stats(self) -> dict:
        """计算 Brier Score, 准确率等"""
        # 计算 Brier Score
        # 计算校准误差
        return {...}
    
    def get_overconfident(self, threshold=80) -> list:
        """获取过度自信事件"""
        # 查询 probability >= threshold AND result = 'incorrect'
        return [...]
    
    def get_trend(self, window=10) -> dict:
        """计算滚动准确率"""
        # 按日期排序
        # 滑动窗口计算准确率
        return {"trend": [...]}
```

### 前端可视化

**校准曲线 SVG**
```javascript
function renderCalibrationChart(data) {
  const W = 600, H = 400;
  const padL = 50, padR = 20, padT = 20, padB = 40;
  const xScale = p => padL + (p / 100) * (W - padL - padR);
  const yScale = r => H - padB - (r / 100) * (H - padT - padB);
  
  let svg = `<svg viewBox="0 0 ${W} ${H}">`;
  
  // 网格线
  for (let i = 0; i <= 10; i++) {
    const x = xScale(i * 10);
    const y = yScale(i * 10);
    svg += `<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="#eee"/>`;
    svg += `<line x1="${x}" y1="${padT}" x2="${x}" y2="${H-padB}" stroke="#eee"/>`;
  }
  
  // 45° 对角线（理想校准）
  svg += `<line x1="${xScale(0)}" y1="${yScale(0)}" x2="${xScale(100)}" y2="${yScale(100)}" stroke="#999" stroke-dasharray="5,5"/>`;
  
  // 数据点
  data.buckets.forEach(b => {
    if (b.count > 0) {
      const x = xScale((b.min + b.max) / 2);
      const y = yScale(b.rate * 100);
      const r = Math.max(4, Math.sqrt(b.count) * 2);
      svg += `<circle cx="${x}" cy="${y}" r="${r}" fill="#4F6EF7" opacity="0.6">`;
      svg += `<title>${b.range}%: ${b.correct}/${b.count} (${(b.rate*100).toFixed(0)}%)</title>`;
      svg += `</circle>`;
    }
  });
  
  // 轴标签
  svg += `<text x="${W/2}" y="${H-5}" text-anchor="middle">自报概率 (%)</text>`;
  svg += `<text x="15" y="${H/2}" text-anchor="middle" transform="rotate(-90 15 ${H/2})">实际发生率 (%)</text>`;
  
  svg += `</svg>`;
  return svg;
}
```

**置信度分布直方图**
```javascript
function renderDistributionChart(data) {
  // 复用现有 barChart 逻辑
  const labels = data.buckets.map(b => b.range + '%');
  const values = data.buckets.map(b => b.count);
  return barChart(labels, values);
}
```

**时间趋势折线图**
```javascript
function renderTrendChart(data) {
  // 复用现有 lineChart 逻辑
  const labels = data.trend.map(t => t.date);
  const values = data.trend.map(t => t.accuracy * 100);
  return lineChart(labels, values);
}
```

## 错误处理

### 后端
- 400: 参数校验失败（threshold 范围、window 大小）
- 404: 无预测数据（返回空结构，不报错）

### 前端
- 数据不足时显示提示："至少需要 10 条预测记录才能生成校准曲线"
- 加载失败显示错误信息

## 测试策略

### 单元测试
1. **校准分桶**：验证 10 个桶的边界条件
2. **Brier Score**：已知数据集验证计算正确性
3. **过度自信**：验证 threshold 筛选逻辑
4. **滚动准确率**：验证 window 滑动逻辑

### 集成测试
1. 创建预测记录 → 调用校准 API → 验证响应
2. 前端渲染验证（需真实浏览器）

## 性能考虑

### 查询优化
- 校准分桶：单次查询，内存中分桶
- Brier Score：单次查询，内存中计算
- 滚动准确率：按日期排序，滑动窗口

### 前端性能
- SVG 图表复用现有函数
- 数据量小（预计 <1000 条），无需分页

## 未来扩展

### 可能改进
1. **按关键词分析**：提取 statement 中的关键词，分析不同主题的准确率
2. **AI 辅助判定**：调用 AI 自动判定 pending 预测的结果
3. **预测模板**：常用预测类型快速录入
4. **多用户对比**：团队校准对比

### 技术债务
1. 暂不支持预测的软删除
2. 暂不支持预测的批量导入/导出
3. 暂不支持预测的编辑（只能删除重填）
