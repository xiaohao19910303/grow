# 技术设计：知识图谱可视化

## 架构概览

```
server/
├── knowledge/
│   ├── __init__.py
│   ├── store.py      # 数据层：关系存储
│   ├── graph.py      # 图谱构建：节点 + 关系
│   └── api.py        # API 路由：/api/knowledge
├── app.py            # 注册 knowledge router（增强现有）
└── static/
    └── index.html    # 前端：图谱可视化
```

注意：knowledge 表已存在于 app.py 的 SCHEMA 中，这里只是增加关系检测和可视化 API。

## 数据模型

### 新增关系表

```sql
CREATE TABLE IF NOT EXISTS knowledge_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    link_type TEXT DEFAULT 'related',  -- 'same_source', 'keyword', 'category'
    weight INTEGER DEFAULT 1,
    FOREIGN KEY (source_id) REFERENCES knowledge(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES knowledge(id) ON DELETE CASCADE,
    UNIQUE(source_id, target_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_link_source ON knowledge_links(source_id);
CREATE INDEX IF NOT EXISTS idx_link_target ON knowledge_links(target_id);
```

### 关系检测逻辑

```python
def detect_links():
    """检测知识节点之间的关系。"""
    # 1. 同源关系：来自同一个 source 的节点
    # 2. 关键词共现：summary 中包含相同关键词
    # 3. 分类关系：同一 category 的节点（弱关联）
    
    links = []
    
    # 同源关系
    nodes_by_source = group_by(knowledge_nodes, 'source')
    for source, nodes in nodes_by_source.items():
        if source and len(nodes) > 1:
            for i, n1 in enumerate(nodes):
                for n2 in nodes[i+1:]:
                    links.append((n1['id'], n2['id'], 'same_source', 3))
    
    # 关键词共现
    keywords = extract_keywords(summary)
    # ... 检测关键词共现
    
    # 分类关系（弱关联）
    nodes_by_category = group_by(knowledge_nodes, 'category')
    for category, nodes in nodes_by_category.items():
        if len(nodes) > 1:
            # 只连接前 N 个，避免过多边
            for i, n1 in enumerate(nodes[:20]):
                for n2 in nodes[i+1:20]:
                    links.append((n1['id'], n2['id'], 'category', 1))
    
    return links
```

## API 设计

### 图谱数据

```
GET /api/knowledge/graph
  查询参数:
    - category: string (可选，过滤分类)
    - limit: int (默认500，最大1000)
  响应:
    {
      "nodes": [
        {"id": 1, "name": "概念A", "category": "框架", "size": 10, "source": "..."},
        ...
      ],
      "links": [
        {"source": 1, "target": 2, "type": "same_source", "weight": 3},
        ...
      ],
      "stats": {
        "total_nodes": 150,
        "total_links": 320,
        "categories": {"框架": 25, "工具": 18, ...}
      }
    }
```

节点大小计算：
```python
size = base_size + len(connected_links) * 2
```

### 重新扫描关系

```
POST /api/knowledge/scan-links
  响应:
    {
      "ok": true,
      "links_created": 320,
      "time_ms": 1250
    }
```

## 前端设计

### 力导向图实现

使用简单的物理模拟（不引入 D3.js）：

```javascript
class ForceGraph {
  constructor(container, nodes, links) {
    this.nodes = nodes;
    this.links = links;
    this.container = container;
    
    // 初始化节点位置
    this.nodes.forEach(n => {
      n.x = Math.random() * width;
      n.y = Math.random() * height;
      n.vx = 0;
      n.vy = 0;
    });
    
    // 物理参数
    this.repulsion = 1000;  // 节点间斥力
    this.attraction = 0.01; // 边的引力
    this.damping = 0.9;     // 速度衰减
    
    this.start();
  }
  
  start() {
    const tick = () => {
      this.applyForces();
      this.updatePositions();
      this.render();
      requestAnimationFrame(tick);
    };
    tick();
  }
  
  applyForces() {
    // 节点间斥力
    for (let i = 0; i < this.nodes.length; i++) {
      for (let j = i + 1; j < this.nodes.length; j++) {
        const n1 = this.nodes[i];
        const n2 = this.nodes[j];
        const dx = n2.x - n1.x;
        const dy = n2.y - n1.y;
        const dist = Math.sqrt(dx*dx + dy*dy) || 1;
        const force = this.repulsion / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        n1.vx -= fx;
        n1.vy -= fy;
        n2.vx += fx;
        n2.vy += fy;
      }
    }
    
    // 边的引力
    this.links.forEach(link => {
      const source = this.nodes.find(n => n.id === link.source);
      const target = this.nodes.find(n => n.id === link.target);
      if (!source || !target) return;
      
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dist = Math.sqrt(dx*dx + dy*dy) || 1;
      const force = dist * this.attraction * link.weight;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      source.vx += fx;
      source.vy += fy;
      target.vx -= fx;
      target.vy -= fy;
    });
  }
  
  updatePositions() {
    this.nodes.forEach(n => {
      if (n.dragging) return;
      n.vx *= this.damping;
      n.vy *= this.damping;
      n.x += n.vx;
      n.y += n.vy;
      // 边界约束
      n.x = Math.max(0, Math.min(width, n.x));
      n.y = Math.max(0, Math.min(height, n.y));
    });
  }
  
  render() {
    let svg = '<svg width="100%" height="600" viewBox="0 0 ' + width + ' ' + height + '">';
    
    // 绘制边
    this.links.forEach(link => {
      const source = this.nodes.find(n => n.id === link.source);
      const target = this.nodes.find(n => n.id === link.target);
      if (!source || !target) return;
      svg += `<line x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="#ddd" stroke-width="${link.weight}"/>`;
    });
    
    // 绘制节点
    this.nodes.forEach(n => {
      const color = categoryColors[n.category] || '#999';
      const r = n.size || 8;
      svg += `<circle cx="${n.x}" cy="${n.y}" r="${r}" fill="${color}" stroke="#fff" stroke-width="1.5" style="cursor:pointer">`;
      svg += `<title>${n.name}\n${n.category}\n${n.summary || ''}</title>`;
      svg += `</circle>`;
    });
    
    svg += '</svg>';
    this.container.innerHTML = svg;
  }
}
```

### 知识图谱页面

增强现有 view-knowledge：

```html
<div id="view-knowledge">
  <div class="section">
    <h2>知识图谱可视化</h2>
    <p class="desc">交互式力导向图，展示知识点之间的关联。</p>
    
    <!-- 控制栏 -->
    <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      <button class="btn primary" onclick="scanKnowledgeLinks()">重新扫描关系</button>
      <select id="graphCategoryFilter" onchange="renderKnowledgeGraph()">
        <option value="">全部分类</option>
      </select>
      <input id="graphSearch" placeholder="搜索节点..." oninput="filterGraphNodes()">
    </div>
    
    <!-- 统计 -->
    <div class="cards" id="graphStats"></div>
    
    <!-- 图谱容器 -->
    <div id="graphContainer" style="border:1px solid var(--border);border-radius:8px;background:#fafbfd;margin-top:16px"></div>
  </div>
  
  <!-- 现有的知识列表 -->
  <div class="section">
    <h2>知识节点列表</h2>
    ...
  </div>
</div>
```

### 分类颜色映射

```javascript
const categoryColors = {
  '框架': '#4F6EF7',
  '工具': '#00A6A6',
  '概念': '#E07B39',
  '方法': '#7C5CF0',
  '词汇': '#D64580',
  '句式': '#2FA84F',
};
```

## 性能优化

### 节点数限制
- 默认限制 500 个节点
- 超过 500 时提示"节点过多，显示前500个"
- 提供分类过滤减少节点数

### 渲染优化
- 使用 requestAnimationFrame 平滑动画
- 物理模拟 60fps，稳定后降低频率
- 拖拽时暂停物理模拟

### 关系数限制
- 每个节点最多连接 20 条边
- 超过时按 weight 排序，取前20

## 错误处理

### 后端
- 500: 关系扫描失败
- 400: 参数校验失败

### 前端
- 数据加载失败显示错误
- 空数据显示"暂无知识节点"

## 测试策略

### 单元测试
1. **关系检测**：验证同源、关键词、分类关系正确
2. **图谱构建**：验证 nodes + links 格式正确

### 集成测试
1. 扫描知识 → 扫描关系 → 获取图谱 → 渲染
2. 前端交互验证（需真实浏览器）

## 未来扩展

### 可能改进
1. **D3.js 集成**：使用成熟的力导向图库
2. **3D 可视化**：使用 Three.js
3. **知识路径**：显示两个节点之间的最短路径
4. **知识时间线**：按日期展示知识增长

### 技术债务
1. 暂不支持关系的编辑/删除
2. 暂不支持节点自定义位置
3. 暂不支持图谱导出（PNG/SVG）
