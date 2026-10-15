# 变更提案：知识图谱可视化

## 日期
2026-10-15

## 提案人
CEO Review (选择性扩展)

## 问题陈述
系统已有知识图谱功能（knowledge 表），通过扫描 Markdown 文件生成知识节点。但目前只展示为列表，缺乏真正的图谱可视化。

用户无法直观看到：
- 知识点之间的关联
- 知识的分类结构
- 哪些领域的知识更丰富
- 知识之间的连接关系

没有可视化，知识图谱的价值大打折扣。

## 建议方案
增加"知识图谱可视化"功能，将现有 knowledge 数据转化为交互式图谱。

### 核心功能
1. **力导向图**：使用 SVG 实现力导向图（force-directed graph），节点可拖拽。
2. **分类着色**：不同 category 使用不同颜色。
3. **节点大小**：根据连接数或重要性调整节点大小。
4. **悬停详情**：鼠标悬停显示节点详情（名称、分类、摘要）。
5. **点击跳转**：点击节点可跳转到来源文件。
6. **缩放平移**：支持鼠标滚轮缩放和拖拽平移。
7. **搜索过滤**：按关键词过滤节点，高亮匹配节点。

### 数据模型
复用现有 `knowledge` 表：
```sql
CREATE TABLE knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    category TEXT,
    summary TEXT,
    source TEXT,
    kind TEXT,
    date TEXT DEFAULT ''
);
```

需要新增关系表：
```sql
CREATE TABLE knowledge_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    target_id INTEGER,
    link_type TEXT DEFAULT 'related',
    FOREIGN KEY (source_id) REFERENCES knowledge(id),
    FOREIGN KEY (target_id) REFERENCES knowledge(id)
);
```

### 关系检测
自动检测知识节点之间的关系：
1. **同源关系**：来自同一个 Markdown 文件的节点自动关联。
2. **关键词共现**：summary 中包含相同关键词的节点关联。
3. **分类关系**：同一 category 的节点可以建立弱关联。

### API 端点
- `GET /api/knowledge/graph` — 获取图谱数据（nodes + links）
- `POST /api/knowledge/scan-links` — 重新扫描关系

### 前端界面
1. **仪表盘"知识图谱"区域**
   - 节点数 / 分类数 / 关系数统计
   - 简化版图谱预览

2. **独立"知识图谱"页面**（增强现有 view-knowledge）
   - 交互式力导向图（SVG）
   - 分类过滤
   - 搜索框
   - 节点详情面板

### 技术约束
- 单用户，纯本地 SQLite 存储
- 零外部依赖，纯前端 SVG 可视化
- 不修改现有 knowledge 表
- 力导向图使用简单的物理模拟（不引入 D3.js）
- 节点数限制（>500 时提示性能警告）

## 预期收益
1. **直观理解**：用户能看到知识点之间的关联
2. **发现联系**：发现没注意到的知识连接
3. **学习导航**：通过图谱探索相关知识
4. **知识管理**：可视化知识结构，发现空白领域

## 不在范围内
- 3D 可视化
- 复杂的语义分析
- 自动知识抽取（仍用 Markdown 扫描）
- 多用户协作

## 验收标准
1. 知识图谱页面显示交互式力导向图
2. 节点可按分类着色，大小可调
3. 支持拖拽、缩放、平移
4. 悬停显示详情，点击跳转来源
5. 支持搜索过滤
6. 不破坏现有知识扫描功能

## 依赖
- 现有 knowledge 表和数据
- 需要新增 knowledge_links 表
- 需要新增 API 端点
- 需要修改 index.html 添加可视化

## 风险评估
- **中等风险**：力导向图性能（节点数>500 时可能卡顿）
- **低风险**：关系检测逻辑简单，不影响现有数据
- **中等风险**：SVG 实现复杂（需要自己写物理模拟）
