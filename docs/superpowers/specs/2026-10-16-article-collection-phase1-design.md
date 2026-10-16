# 文章收藏与双语精读 — Phase 1 设计

日期：2026-10-16
状态：待用户审阅

## Context

Module 2 完整方案见 `openspec/changes/article-collection-bilingual-reading/design.md`（70+ 任务项）。本设计仅覆盖 Phase 1 核心功能，Phase 2（双语对照、词汇复习等）后续迭代。

现有 reading 模块已有：RSS 搜集、文章列表、收藏/稍后/读完筛选、AI 导读/摘要/英语学习生成、个人笔记、自定义来源管理。

## Phase 1 Scope

### 需要新增

| 功能 | 说明 |
|---|---|
| 手动导入文章（URL） | 输入链接 → 抓取正文 → 预览 → 确认保存 |
| 手动导入文章（粘贴） | 粘贴正文 → 填写元信息 → 保存 |
| 文章搜索 | 按标题/作者/来源/标签搜索 |
| 归档与恢复 | 归档不删除，可恢复；列表默认隐藏已归档 |
| 正文完整性标记 | 标记"完整正文"/"部分正文"/"待核对正文" |

### 已有不改

- RSS 每日搜集与去重
- 文章列表（全部/收藏/稍后/读完筛选）
- AI 导读、摘要、英语学习生成
- 个人笔记保存
- 自定义来源管理
- 阅读偏好设置

### Phase 1 不做（留给 Phase 2）

- 逐段双语对照翻译
- 语境词汇/短语/语法讲解
- 个人生词本与间隔复习（1/3/7/14/30 天）
- 分块生成与草稿采用流程
- 生词与复习页面

## 数据模型变更

在现有 `reading_records` 表中扩展文章字段（JSON data 内）：

```python
# 新增字段（加在现有 article data dict 中）
{
    "schema_version": 2,           # 标识新版结构
    "content_scope": "full|partial|unverified",  # 正文完整性
    "source_version": 1,           # 正文版本号
    "record_version": 1,           # 记录版本号（编辑递增）
    "archived": False,             # 归档标记
    "import_method": "rss|url|paste",  # 导入方式
    "tags": [],                    # 用户自定义标签
}
```

旧文章兼容：无 `schema_version` 字段视为 v1，`content_scope` 默认 `unverified`，`archived` 默认 `False`。

## API 变更

### 新增端点

```
POST /api/reading/import-url      # URL 导入：抓取正文 → 返回预览
POST /api/reading/import-paste    # 粘贴导入：保存正文 → 返回文章
POST /api/reading/articles/{aid}/archive   # 归档
POST /api/reading/articles/{aid}/restore   # 恢复
```

### 修改端点

```
GET /api/reading                  # 增加 search 查询参数
```

## 文件改动清单

| 文件 | 改动 |
|---|---|
| `server/reading/store.py` | 新增 import_url/import_paste/archive/restore 方法；扩展文章 schema |
| `server/reading/sources.py` | 新增 URL 抓取函数（受限 HTTPS、正文提取） |
| `server/reading/service.py` | 新增 import 任务类型处理 |
| `server/reading/api.py` | 新增 4 个端点；修改 listing 增加 search 参数 |
| `server/static/reading.js` | 新增"添加文章"表单（URL/粘贴）；搜索框；归档/恢复按钮 |
| `server/static/index.html` | 在 reading 视图增加"添加文章"入口 |

## 实施顺序

1. store.py — 扩展 schema + 新增方法
2. sources.py — URL 抓取实现
3. service.py — import 任务处理
4. api.py — 新端点注册
5. reading.js — 前端 UI
6. 验证 — 临时数据库隔离测试

## 验证边界

- 临时 SQLite + 自写中英文样例验证
- 不自动提交或推送
- 真实模型调用需用户单独授权
