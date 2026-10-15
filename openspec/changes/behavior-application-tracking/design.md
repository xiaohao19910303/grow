# 技术设计：行为应用追踪

## Context

当前仪表盘已有 `reviews`（复盘四问）、`checkins`（模块打卡0-3级）、`predictions`（预测校准）等表。新增 `behavior_applications` 表记录用户在真实场景中应用学习概念的行为。

前端 `index.html` 947 行，所有逻辑在一个文件。本次新增约 200 行（复盘区入口 + 成长度量区域 + 应用记录页）。不引入前端框架，保持原生 JS。

## Goals / Non-Goals

**Goals:** 低摩擦记录应用行为；仪表盘可视化呈现"知行合一"度量；不破坏既有功能。

**Non-Goals:** AI 自动提取（后续阶段）、应用提醒推送、多用户支持、效果因果分析。

## Decisions

### 1. 记录入口：嵌入复盘流程

行为应用记录的最佳时机是用户写每日复盘时——复盘本身就是"回顾今天做了什么"，顺便记录"用了什么"成本最低。

```
复盘四问
  1. 今天做了什么？
  2. 哪里做得好？
  3. 哪里可以改进？
  4. 明天计划做什么？
  ─────────────────────
  [折叠区] 今天用了什么学到的？
    模块: [下拉选择]
    概念: [文本输入，自动补全]
    场景: [简述]
    效果: [★☆☆☆☆ ~ ★★★★★]
    [+ 再记一条]
    [保存]
```

自动补全来源：从 `behavior_applications` 表已有记录中提取 distinct concept 值，前端用 `<datalist>` 实现。

### 2. 数据模型

```sql
CREATE TABLE IF NOT EXISTS behavior_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    module_id TEXT NOT NULL,
    concept TEXT NOT NULL,
    scenario TEXT DEFAULT '',
    effectiveness INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 索引：按日期和模块查询
CREATE INDEX IF NOT EXISTS idx_behavior_date ON behavior_applications(date);
CREATE INDEX IF NOT EXISTS idx_behavior_module ON behavior_applications(module_id);
```

不修改现有表。迁移逻辑放在 `app.py` 启动时，与现有 `copilot_*` 和 `learning_*` 表的增量迁移方式一致。

### 3. API 设计

```
GET  /api/behavior/applications
     ?date_from=2026-10-01&date_to=2026-10-31&module_id=renzhi
     → [{id, date, module_id, concept, scenario, effectiveness, created_at}]

POST /api/behavior/applications
     body: {date, module_id, concept, scenario?, effectiveness?}
     → {id, ...}  (201)

PUT  /api/behavior/applications/{id}
     body: {date?, module_id?, concept?, scenario?, effectiveness?}
     → {id, ...}  (200)

DELETE /api/behavior/applications/{id}
     → 204

GET  /api/behavior/stats
     ?period=30  (默认30天)
     → {
         total: 12,
         by_module: {renzhi: 5, xiezuo: 3, biaoda: 2, ...},
         top_concepts: [{concept: "确认偏误", count: 4}, ...],
         trend: [{date: "2026-10-01", count: 1}, ...]
       }
```

### 4. 前端可视化

全部 SVG inline，不引入 chart library。

**近30天趋势图：** 简单折线图，横轴日期，纵轴应用次数。复用现有 `.chart-svg` 样式。

**Top 5 概念：** 水平柱状图，概念名在左，柱体在右，长度按 count 比例。

**按模块分布：** 与现有打卡热力图风格一致的颜色方块。

### 5. 文件结构

```
知行成长/server/
├── behavior/
│   ├── __init__.py
│   ├── api.py          # FastAPI router
│   └── store.py        # SQLite CRUD + stats
├── static/
│   └── index.html      # 新增 UI（~200行增量）
└── app.py              # 注册 behavior router
```

### 6. 迁移策略

在 `app.py` 启动时，与现有表一起创建 `behavior_applications` 表：

```python
# app.py startup
db.execute("""
    CREATE TABLE IF NOT EXISTS behavior_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        module_id TEXT NOT NULL,
        concept TEXT NOT NULL,
        scenario TEXT DEFAULT '',
        effectiveness INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )
""")
```

无数据迁移需求（全新表）。现有 `/api/data` 全量同步不包含此表（与 copilot_* 表一致）。

## Error Handling

| 场景 | 处理 |
|---|---|
| module_id 不在已知列表中 | 400 Bad Request |
| concept 为空 | 400 Bad Request |
| date 格式错误 | 400 Bad Request |
| 记录不存在（PUT/DELETE） | 404 Not Found |
| 数据库写入失败 | 500 + 日志 |

## Testing

- 单元测试：CRUD 操作、stats 计算、边界条件（空数据、单条记录）
- 隔离测试：临时 SQLite，不写真实数据库
- 前端验证：手动检查 SVG 渲染、自动补全、表单提交

## Security

- 沿用现有访问控制（本机无认证；局域网模式复用 COPILOT_ACCESS_TOKEN）
- 输入验证：module_id 白名单、concept 长度限制（100字）、scenario 长度限制（500字）
- 不暴露内部路径或数据库文件位置
