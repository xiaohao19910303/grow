# 技术设计：重复错误追踪

## 架构概览

```
server/
├── errors/
│   ├── __init__.py
│   ├── store.py      # 数据层：CRUD + 统计 + 重复检测
│   └── api.py        # API 路由：/api/errors
├── app.py            # 注册 errors router
└── static/
    └── index.html    # 前端：错误记录页 + 仪表盘区域
```

## 数据模型

### 表结构

```sql
-- 错误记录表
CREATE TABLE IF NOT EXISTS error_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    module_id TEXT NOT NULL,
    error_type TEXT NOT NULL,
    description TEXT NOT NULL,
    severity INTEGER DEFAULT 3,
    context TEXT DEFAULT '',
    improvement_action TEXT DEFAULT '',
    is_repeat INTEGER DEFAULT 0,
    related_error_id INTEGER DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (related_error_id) REFERENCES error_records(id)
);

CREATE INDEX IF NOT EXISTS idx_error_date ON error_records(date);
CREATE INDEX IF NOT EXISTS idx_error_module ON error_records(module_id);
CREATE INDEX IF NOT EXISTS idx_error_type ON error_records(error_type);
CREATE INDEX IF NOT EXISTS idx_error_repeat ON error_records(is_repeat);

-- 错误类型表
CREATE TABLE IF NOT EXISTS error_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 预置错误类型
INSERT OR IGNORE INTO error_types(name, description) VALUES
    ('判断偏差', '高估或低估某事物的难度/重要性'),
    ('步骤遗漏', '执行过程中遗漏关键步骤'),
    ('概念混淆', '对某个概念的理解有偏差'),
    ('注意力分散', '执行时注意力不集中导致错误'),
    ('时间估算错误', '低估或高估所需时间'),
    ('沟通误解', '与他人沟通时产生误解'),
    ('过度自信', '认为自己掌握了但实际没有'),
    ('其他', '不属于以上类别的错误');
```

### 验证规则
- `date`: YYYY-MM-DD 格式
- `module_id`: 必须在 VALID_MODULES 白名单中
- `error_type`: 非空，≤50字
- `description`: 非空，≤500字
- `severity`: 0-5 整数
- `context`: ≤500字
- `improvement_action`: ≤500字

## API 设计

### 错误记录 CRUD

```
GET /api/errors
  查询参数:
    - date_from: YYYY-MM-DD
    - date_to: YYYY-MM-DD
    - module_id: string
    - error_type: string
    - is_repeat: 0|1
  响应: 200 OK, 错误记录列表（按日期倒序）

POST /api/errors
  请求体:
    {
      "date": "YYYY-MM-DD",
      "module_id": "string",
      "error_type": "string",
      "description": "string",
      "severity": 0-5,
      "context": "string (optional)",
      "improvement_action": "string (optional)",
      "is_repeat": 0|1,
      "related_error_id": int|null
    }
  响应: 201 Created, 新错误记录

GET /api/errors/{id}
  响应: 200 OK | 404 Not Found

PUT /api/errors/{id}
  请求体: 部分更新字段
  响应: 200 OK | 404 Not Found

DELETE /api/errors/{id}
  响应: 204 No Content | 404 Not Found
```

### 错误类型管理

```
GET /api/errors/types
  响应: 200 OK, 错误类型列表

POST /api/errors/types
  请求体:
    {
      "name": "string",
      "description": "string (optional)"
    }
  响应: 201 Created

DELETE /api/errors/types/{id}
  响应: 204 No Content | 404 Not Found
  注意: 如果该类型被错误记录引用，拒绝删除
```

### 统计与重复检测

```
GET /api/errors/stats
  查询参数:
    - period: int (1-365, 默认30)
  响应:
    {
      "total": int,
      "period_days": int,
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD",
      "by_type": {"判断偏差": 5, "步骤遗漏": 3, ...},
      "by_module": {"fupan": 8, "xiezuo": 2, ...},
      "severity_avg": 3.2,
      "repeat_rate": 0.35,  -- 重复错误占比
      "trend": [{"date": "YYYY-MM-DD", "count": 2}, ...]
    }

GET /api/errors/repeated
  响应: 重复错误组列表
    [
      {
        "error_type": "判断偏差",
        "count": 5,
        "first_occurrence": "2026-09-01",
        "last_occurrence": "2026-10-10",
        "errors": [
          {"id": 1, "date": "2026-09-01", "description": "...", "severity": 3},
          {"id": 15, "date": "2026-09-15", "description": "...", "severity": 4},
          ...
        ]
      },
      ...
    ]
```

## 前端设计

### 仪表盘"错误模式"区域

位置：在 view-overview 中，紧跟"成长度量"区域之后。

```html
<div class="section">
  <h2>错误模式 · 重复追踪</h2>
  <div id="errorStatsCards" class="cards"></div>
  <div id="errorTypeChart"></div>
  <div id="errorTrendChart"></div>
  <div id="errorRepeatedList"></div>
</div>
```

**统计卡片**
- 本月错误总数
- 重复错误率（百分比）
- 平均严重程度（1-5）
- 最常犯错误类型

**错误类型分布**
- CSS 水平柱状图（类似行为应用的 Top 概念）
- 显示每个错误类型的数量

**错误趋势**
- SVG 折线图（近30天）
- 与行为应用趋势图并列

**重复错误组**
- 列表展示，每组显示：
  - 错误类型 + 出现次数
  - 首次/最近出现日期
  - 展开可看每条记录

### 独立"错误记录"页面

位置：navGroups['记录'] 下新增 `['errors', '错误记录']`

```html
<section id="view-errors" class="view">
  <div class="section">
    <div class="row" style="justify-content:space-between">
      <h2>错误记录</h2>
      <button class="btn" onclick="openErrorForm()">+ 记录错误</button>
    </div>
    
    <!-- 筛选 -->
    <div class="row">
      <select id="errorModuleFilter">
        <option value="">全部模块</option>
      </select>
      <select id="errorTypeFilter">
        <option value="">全部类型</option>
      </select>
      <label>
        <input type="checkbox" id="errorRepeatFilter"> 仅重复错误
      </label>
    </div>
    
    <!-- 错误列表 -->
    <div id="errorList" class="list"></div>
  </div>
  
  <!-- 编辑弹窗 -->
  <div id="errorFormModal" class="modal" style="display:none">
    ...
  </div>
</section>
```

**错误记录卡片**
```html
<div class="card">
  <div class="row" style="justify-content:space-between">
    <div>
      <strong>判断偏差</strong>
      <span class="badge">执行复盘</span>
      <span class="badge badge-warn">重复 #3</span>
    </div>
    <div class="stars">★★★☆☆</div>
  </div>
  <p>高估了任务难度，实际执行比预期快很多</p>
  <div class="meta">2026-10-10 · 改进：下次先估算再执行</div>
</div>
```

**编辑表单**
- 日期选择
- 模块选择（下拉）
- 错误类型选择（下拉，支持新增）
- 错误描述（文本区域）
- 严重程度（1-5星点击）
- 上下文（文本区域）
- 改进措施（文本区域）
- 是否重复（复选框）
- 关联错误（下拉，如果勾选"是否重复"）

### 复盘页"记录错误"入口

在执行复盘四问下方，增加折叠区域：

```html
<div class="section" id="review-error-section">
  <h3>犯了什么错？</h3>
  <button class="btn btn-sm" onclick="toggleReviewError()">+ 记录错误</button>
  <div id="reviewErrorForm" style="display:none">
    <select id="reviewErrorType">
      <option value="">选择错误类型</option>
    </select>
    <textarea id="reviewErrorDesc" placeholder="描述错误"></textarea>
    <div id="reviewErrorSeverity">
      <span onclick="setReviewErrorSev(1)">★</span>
      <span onclick="setReviewErrorSev(2)">★</span>
      ...
    </div>
    <button class="btn" onclick="saveReviewError()">保存</button>
  </div>
</div>
```

## 重复检测逻辑

### 简单匹配策略
1. **同类型重复**：相同 `error_type` 的错误自动标记为潜在重复
2. **相似度检测**：未来可加入描述文本的相似度匹配（暂不实现）

### 标记逻辑
- 当用户记录新错误时，检查过去30天内是否有相同类型的错误
- 如果有，提示"这是近30天内第N次犯此类错误"
- 用户可以勾选"这是重复错误"，并选择关联的历史错误

### 统计计算
```python
def get_repeated_errors(self):
    """按错误类型分组，找出出现2次以上的错误组"""
    groups = {}
    for row in self.list():
        key = row['error_type']
        if key not in groups:
            groups[key] = []
        groups[key].append(row)
    
    repeated = []
    for error_type, errors in groups.items():
        if len(errors) >= 2:
            repeated.append({
                'error_type': error_type,
                'count': len(errors),
                'first_occurrence': min(e['date'] for e in errors),
                'last_occurrence': max(e['date'] for e in errors),
                'errors': sorted(errors, key=lambda e: e['date'])
            })
    
    return sorted(repeated, key=lambda g: g['count'], reverse=True)
```

## 错误处理

### 后端
- 400: 参数校验失败（日期格式、字段长度、白名单）
- 404: 错误记录不存在
- 409: 错误类型名称重复
- 500: 服务器内部错误

### 前端
- 表单提交失败：显示错误信息
- 加载失败：显示"加载失败"提示
- 空数据：显示"尚无错误记录"引导

## 测试策略

### 单元测试
1. **store.py**
   - CRUD 全流程
   - 统计计算（空数据、单日、多日、跨模块）
   - 重复检测（无重复、有重复、多组重复）
   - 错误类型管理

2. **api.py**
   - 参数校验
   - 权限检查（局域网模式）
   - 响应格式

### 集成测试
1. 启动服务，调用所有 API 端点
2. 前端渲染验证（需真实浏览器）

### 验收测试
1. 记录错误 → 仪表盘展示 → 错误记录页管理
2. 重复错误标记 → 重复错误组展示
3. 现有功能不受影响

## 迁移策略

### 表创建
- 在 `app.py` 的 lifespan 中，调用 `error_store.initialize()`
- 预置8个常见错误类型

### 数据兼容性
- 新表不影响现有表
- 不修改 `TABLES` 列表（不参与全量同步）

## 性能考虑

### 查询优化
- 索引：date, module_id, error_type, is_repeat
- 统计查询使用 GROUP BY，避免全表扫描
- 重复检测在内存中计算（数据量小）

### 前端性能
- SVG 图表复用现有函数
- 错误列表分页（未来，如果数据量大）
- 缓存错误类型列表

## 安全考虑

### 输入校验
- 所有字符串字段限制长度
- 枚举值校验（module_id, severity）
- 日期格式校验

### 权限
- 沿用现有 COPILOT_ACCESS_TOKEN 中间件
- 无额外权限控制

## 未来扩展

### 可能改进
1. **语义相似度**：使用 embedding 检测描述文本的相似度
2. **AI 自动分类**：调用 AI 建议错误类型
3. **错误关联图谱**：可视化错误之间的关系
4. **改进措施追踪**：记录改进措施，追踪是否有效
5. **跨模块错误模式**：识别在多个模块中都出现的错误模式

### 技术债务
1. 暂不支持错误的软删除
2. 暂不支持错误记录的导入/导出
3. 暂不支持错误类型的批量编辑
