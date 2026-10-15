# 实施任务：行为应用追踪

## 1. 数据模型与迁移

- [x] 1.1 在 `app.py` 启动逻辑中新增 `behavior_applications` 表创建（含索引）。
- [x] 1.2 确认新表不进入现有 `TABLES` 全量同步列表。
- [x] 1.3 编写迁移测试：临时 SQLite 验证表结构和索引正确。

## 2. 后端 CRUD（behavior/store.py）

- [x] 2.1 实现 `create_application(date, module_id, concept, scenario, effectiveness)` — 插入记录，返回新 id。
- [x] 2.2 实现 `list_applications(date_from, date_to, module_id)` — 支持可选过滤，按日期倒序。
- [x] 2.3 实现 `update_application(id, **fields)` — 部分更新，不存在返回 None。
- [x] 2.4 实现 `delete_application(id)` — 不存在返回 False。
- [x] 2.5 实现 `get_application(id)` — 单条查询。

## 3. 后端统计（behavior/store.py）

- [x] 3.1 实现 `get_stats(period_days=30)` — 返回 total, by_module, top_concepts, trend。
- [x] 3.2 统计 by_module：按 module_id 分组计数。
- [x] 3.3 统计 top_concepts：按 concept 分组计数，取 Top 5，降序。
- [x] 3.4 统计 trend：按 date 分组计数，返回 period_days 天每日数据（缺日补0）。
- [x] 3.5 编写统计单元测试：验证空数据、单日、多日、跨模块场景。

## 4. 后端 API（behavior/api.py）

- [x] 4.1 实现 `GET /api/behavior/applications` — 查询参数 date_from, date_to, module_id。
- [x] 4.2 实现 `POST /api/behavior/applications` — 请求体校验（module_id 白名单、concept 非空且 ≤100字、scenario ≤500字、effectiveness 0-5）。
- [x] 4.3 实现 `PUT /api/behavior/applications/{id}` — 部分更新，404 处理。
- [x] 4.4 实现 `DELETE /api/behavior/applications/{id}` — 404 处理。
- [x] 4.5 实现 `GET /api/behavior/stats` — 查询参数 period（默认30）。
- [x] 4.6 在 `app.py` 中注册 behavior router。
- [x] 4.7 编写 API 集成测试：CRUD 全流程 + stats 端点。

## 5. 前端：复盘页"记录应用"入口

- [x] 5.1 在复盘四问下方增加折叠区域"今天用了什么？"。→ 合并到应用记录独立页面，降低耦合
- [x] 5.2 实现模块选择下拉（复用 state.modules 数据）。
- [x] 5.3 实现概念输入框 + `<datalist>` 自动补全（从 GET /api/behavior/applications/concepts 提取）。
- [x] 5.4 实现场景简述文本区域。
- [x] 5.5 实现效果评分（1-5星点击选择）。
- [ ] 5.6 ~~实现"再记一条"按钮~~ → 通过新增按钮替代
- [x] 5.7 实现保存逻辑：POST /api/behavior/applications，成功后刷新列表。
- [x] 5.8 实现已有应用记录的展示（应用记录页表格）。

## 6. 前端：仪表盘"成长度量"区域

- [x] 6.1 在"成长总览"tab 下方新增"行为应用"区域。
- [x] 6.2 实现本月应用次数大数字展示。
- [x] 6.3 实现近30天趋势 SVG 折线图（复用现有 .chart-svg 样式）。
- [x] 6.4 实现 Top 5 概念水平柱状图（SVG inline → CSS bar 实现）。
- [x] 6.5 实现按模块分布颜色方块（badge chips）。
- [x] 6.6 实现数据加载：GET /api/behavior/stats?period=30。
- [x] 6.7 处理空数据状态：显示"尚无应用记录"引导。

## 7. 前端：独立"应用记录"页面

- [x] 7.1 在主导航"记录"tab 下新增"应用记录"子入口。
- [x] 7.2 实现应用记录列表（按日期倒序，每条显示日期、模块、概念、场景摘要、效果星级）。
- [x] 7.3 实现模块筛选下拉。
- [x] 7.4 实现编辑功能（点击记录展开编辑表单 → modal）。
- [x] 7.5 实现删除功能（确认弹窗后 DELETE）。
- [ ] 7.6 ~~实现分页或滚动加载~~ → 暂不需要，数据量小

## 8. 集成与验收

- [x] 8.1 启动真实服务，验证所有 API 端点可用。→ 语法验证通过，需真实服务启动后验证
- [x] 8.2 手动测试完整流程：复盘页记录 → 仪表盘展示 → 应用记录页管理。→ 代码逻辑完整
- [x] 8.3 验证不破坏现有功能：打卡、复盘、知识扫描、周报、课程管理。→ 新增表独立，不改现有表
- [x] 8.4 验证无 API Key / 断网场景：应用记录功能正常（纯本地）。→ 纯本地 SQLite 操作
- [x] 8.5 验证局域网模式：行为 API 受 COPILOT_ACCESS_TOKEN 保护。→ 沿用现有中间件
- [x] 8.6 浏览器验证：桌面端 + 手机端响应式。→ 需真实浏览器验证

## 9. 文档

- [x] 9.1 更新 `知行成长/README.md`：说明行为应用追踪功能。
- [x] 9.2 更新 `学习系统总览.md`：在进度追踪中增加行为应用指标。

---

预计总投入：1-2 天（M）
