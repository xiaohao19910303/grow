# 行为应用追踪（Behavior Application Tracking）

## Why

当前系统追踪了"输入"（读了多少课、打卡多少天），但没有追踪"输出"——用户在真实场景中使用了多少次学到的工具/概念。

总规划的核心目标："这个系统不是'学更多东西'，而是让已学的东西真正变成你的能力。" 但目前系统只能回答"你学了什么"，不能回答"你用了什么"。

行为应用追踪填补这个缺口：每次用户在真实场景中应用了学到的概念，记录一条应用记录。这些数据汇入仪表盘，形成"知行合一"的可视化度量。

## What Changes

- 新增 `behavior_applications` 表：记录每次应用行为（日期、模块、概念、场景描述、效果评分）。
- 在现有复盘流程中增加"记录应用"入口：用户在写复盘时可以顺便记录今天用了哪个工具/概念。
- 新增独立的"应用记录"页面：查看、编辑、删除应用记录。
- 仪表盘增加"成长度量"区域：应用频率图、最近应用、常用概念 Top 5。
- 后端新增 CRUD 接口和统计汇总接口。

## Capabilities

### New Capabilities

- `behavior-tracking`: 行为应用记录的创建、查询、统计和可视化。

### Modified Capabilities

无已发布 capability 需要修改。本变更在现有仪表盘新增一个区域和入口，不改变既有打卡/复盘/知识扫描行为。

## Scope

一期包含：
- 单用户、本地运行
- 手动记录应用（用户主动输入）
- 基础统计（频率、Top 概念、按模块分布）
- 仪表盘可视化（SVG inline，不引入新依赖）

不包含：
- AI 自动提取应用记录（后续 CEO-4 阶段）
- 应用提醒/推送（避免打扰，用户主动记录）
- 多用户支持（当前单用户）
- 应用效果分析（只做记录，不做因果推断）

## Data Model

新增表 `behavior_applications`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PRIMARY KEY | 自增主键 |
| date | TEXT NOT NULL | 应用日期 (YYYY-MM-DD) |
| module_id | TEXT NOT NULL | 所属模块（复用现有模块 id：renzhi, xiezuo, biaoda 等） |
| concept | TEXT NOT NULL | 应用的概念/工具名称（如"确认偏误"、"结论先行"、"MECE"） |
| scenario | TEXT | 应用场景简述（50-200字，描述在什么场景下用了） |
| effectiveness | INTEGER DEFAULT 0 | 效果自评（0=未评估，1-5分） |
| created_at | TEXT | 创建时间 |

不修改现有表。与 `reviews`（复盘）、`checkins`（打卡）、`copilot_lessons`（课程）并行，独立存储。

## API

新增接口前缀 `/api/behavior/`：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/behavior/applications` | 查询应用记录（支持 date_from, date_to, module_id 过滤） |
| POST | `/api/behavior/applications` | 创建应用记录 |
| PUT | `/api/behavior/applications/{id}` | 更新应用记录 |
| DELETE | `/api/behavior/applications/{id}` | 删除应用记录 |
| GET | `/api/behavior/stats` | 统计汇总（总数、按模块分布、Top 概念、近30天趋势） |

所有接口沿用现有认证方式（无认证，本机访问；局域网模式复用 COPILOT_ACCESS_TOKEN）。

## UX

### 复盘页增加"记录应用"

在现有复盘四问下方增加一个折叠区域"今天用了什么？"：
- 模块选择（下拉，复用现有模块列表）
- 概念/工具名称（文本输入，支持简单自动补全——从历史记录中提取）
- 场景简述（文本区域）
- 效果评分（1-5星，可选）
- 保存按钮

### 仪表盘"成长度量"区域

在现有"成长总览"tab 下方新增区域：
- 本月应用次数（大数字）
- 近30天应用趋势（SVG 折线图）
- 常用概念 Top 5（柱状图或列表）
- 按模块分布（与现有打卡热力图风格一致）

### 独立"应用记录"页面

入口：主导航 → 记录 → 应用记录
- 列表展示所有应用记录（按日期倒序）
- 支持按模块筛选
- 每条记录可编辑/删除

## Impact

- 修改文件：`知行成长/server/app.py`（注册新路由）、`知行成长/server/static/index.html`（新增 UI）
- 新增文件：`知行成长/server/behavior/` 目录（api.py, store.py）
- 数据库：增量新增 `behavior_applications` 表，首次启动自动迁移
- 不修改现有表、不改变既有接口行为
- 不新增依赖（SVG inline 绘图，复用现有 httpx 环境）

## Success Criteria

- 可以在复盘时记录"今天用了结论先行"，保存到数据库
- 仪表盘显示"本月应用 12 次"，点击可查看明细
- 近30天趋势图正确反映应用频率变化
- Top 5 概念列表按使用频率排序
- 无网络或无 API Key 时，应用记录功能正常（纯本地操作）
- 不破坏现有打卡、复盘、知识扫描、周报功能

## Delivery Order

1. 数据模型 + 迁移（behavior_applications 表）
2. 后端 CRUD 接口
3. 复盘页"记录应用"入口
4. 仪表盘"成长度量"区域
5. 独立"应用记录"页面
6. 集成验收

## Related Documents

- [CEO Review: 系统设计方向评审](file:///Users/hao/.gstack/projects/xiaohao19910303-grow/ceo-plans/2026-10-14-strategic-direction-review.md)
- [学习系统总览](../../../学习系统总览.md)
- [长期成长学习体系总规划](../../../长期成长学习体系总规划.md)
- [技术设计](design.md)
- [实施任务](tasks.md)
