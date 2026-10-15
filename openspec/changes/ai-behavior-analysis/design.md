# 技术设计：AI 行为分析报告

## 架构概览

```
server/
├── behavior_report/
│   ├── __init__.py
│   ├── store.py      # 数据层：报告存储
│   ├── analyzer.py   # AI 分析逻辑
│   └── api.py        # API 路由：/api/behavior-report
├── app.py            # 注册 behavior_report router
└── static/
    └── index.html    # 前端：AI 报告页面
```

## 数据模型

```sql
CREATE TABLE IF NOT EXISTS behavior_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    period_days INTEGER NOT NULL,
    content TEXT NOT NULL,  -- Markdown 格式的报告内容
    data_summary TEXT,      -- JSON 格式的数据摘要
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_report_date ON behavior_reports(date);
```

## AI Prompt 设计

### 数据收集

收集近 N 天的数据摘要：

```python
def collect_data_summary(period_days=30):
    return {
        "period": f"近{period_days}天",
        "checkins": {
            "total_days": ...,
            "module_stats": {"fupan": 15, "xiezuo": 10, ...},
            "completion_rate": 0.75,
        },
        "habits": {
            "total_minutes": ...,
            "avg_minutes_per_day": ...,
            "trend": "up" | "down" | "stable",
        },
        "behavior_applications": {
            "total": ...,
            "top_concepts": [...],
            "by_module": {...},
        },
        "errors": {
            "total": ...,
            "top_types": [...],
            "repeat_rate": ...,
        },
        "predictions": {
            "total": ...,
            "accuracy": ...,
            "brier_score": ...,
        },
        "reviews": {
            "total": ...,
            "themes": [...],  # 从 thought/action 中提取关键词
        },
    }
```

### AI Prompt

```
你是一个个人成长教练。根据以下用户行为数据，生成一份简洁的分析报告。

**数据摘要**：
{data_summary_json}

**要求**：
1. **行为模式总结**（2-3句）：哪些习惯在坚持，哪些在下滑？
2. **知识应用分析**（2-3句）：学到的概念应用得怎么样？有什么模式？
3. **错误模式分析**（2-3句）：哪些错误在重复？哪些在改善？
4. **预测校准**（1-2句）：预测准确度如何？是否过度自信或保守？
5. **个性化建议**（3-5条）：基于数据，给出具体可操作的改进建议。

**格式**：
- 使用 Markdown 格式
- 每个部分用 `##` 标题
- 建议用有序列表
- 总字数控制在 500-800 字
- 语气：鼓励但直接，指出问题但不批评
```

### AI API 调用

复用现有的 copilot 模块的 AI 调用逻辑：

```python
from copilot.core import call_ai

async def generate_report(data_summary: dict) -> str:
    prompt = build_prompt(data_summary)
    response = await call_ai(prompt)
    return response
```

## 前端设计

### 仪表盘"AI 报告"区域

位置：在 view-overview 中，紧跟"预测校准"区域之后。

```html
<div class="section">
  <h2>AI 行为分析报告</h2>
  <p class="desc">AI 分析你的行为数据，提供个性化洞察和建议。</p>
  <div id="aiReportLatest"></div>
  <button class="btn primary" onclick="generateNewReport()">生成新报告</button>
</div>
```

**最新报告摘要**
- 显示报告日期
- 显示报告前3行（摘要）
- 点击"查看详情"跳转到完整页面

### 独立"AI 报告"页面

位置：navGroups['成长'] 下新增 `['ai-report', 'AI 报告']`

```html
<section id="view-ai-report" class="view">
  <div class="section">
    <h2>AI 行为分析报告</h2>
    <p class="desc">AI 分析你的行为数据，提供个性化洞察和建议。</p>
    <button class="btn primary" onclick="generateNewReport()">生成新报告</button>
    <div style="height:14px"></div>
    <div id="aiReportList"></div>
  </div>
  
  <!-- 报告详情弹窗 -->
  <div id="aiReportModal" class="modal" style="display:none">
    ...
  </div>
</section>
```

**报告列表**
- 按日期倒序
- 每条显示：日期、周期、内容预览（前100字）
- 点击展开查看完整报告（Markdown 渲染）
- 支持删除

**Markdown 渲染**
- 使用简单的 Markdown 解析（标题、列表、加粗）
- 不引入外部库，用正则替换

## 错误处理

### AI API 调用失败
- 显示"生成失败，请稍后重试"
- 不保存失败的报告
- 记录错误日志

### 数据不足
- 如果 period_days 内数据太少（如打卡<5天），提示"数据不足，建议至少记录2周"

## 性能考虑

### AI 调用时间
- AI 生成可能需要 10-30 秒
- 前端显示加载动画
- 不阻塞其他操作

### 报告存储
- 报告内容可能较长（1-2KB）
- 定期清理旧报告（如保留最近12个月）

## 测试策略

### 单元测试
1. **数据收集**：验证各模块数据收集正确
2. **报告存储**：CRUD 测试
3. **Markdown 渲染**：验证基本格式正确

### 集成测试
1. 生成报告 → 保存 → 查询 → 渲染
2. AI API 调用失败时的错误处理

## 未来扩展

### 可能改进
1. **报告模板**：用户可以选择不同的分析角度
2. **定期自动生成**：每月1号自动生成并通知
3. **报告对比**：对比不同时期的报告，看进步
4. **AI 对话**：基于报告内容，与 AI 深入讨论

### 技术债务
1. 暂不支持报告导出（PDF/Markdown 文件）
2. 暂不支持报告分享
3. 暂不支持自定义 AI prompt
