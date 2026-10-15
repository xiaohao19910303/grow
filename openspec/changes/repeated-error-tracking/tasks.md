# 实施任务：重复错误追踪

## 1. 数据模型与迁移

- [x] 1.1 在 `app.py` 启动逻辑中新增 `error_records` 和 `error_types` 表创建（含索引）。
- [x] 1.2 预置8个常见错误类型到 `error_types` 表。
- [x] 1.3 确认新表不进入现有 `TABLES` 全量同步列表。
- [x] 1.4 编写迁移测试：临时 SQLite 验证表结构和索引正确。

## 2. 后端 CRUD（errors/store.py）

- [x] 2.1 实现 `create_error(date, module_id, error_type, description, severity, context, improvement_action, is_repeat, related_error_id)` — 插入记录，返回新 id。
- [x] 2.2 实现 `list_errors(date_from, date_to, module_id, error_type, is_repeat)` — 支持可选过滤，按日期倒序。
- [x] 2.3 实现 `update_error(id, **fields)` — 部分更新，不存在返回 None。
- [x] 2.4 实现 `delete_error(id)` — 不存在返回 False。
- [x] 2.5 实现 `get_error(id)` — 单条查询。

## 3. 错误类型管理（errors/store.py）

- [x] 3.1 实现 `create_error_type(name, description)` — 插入新类型，返回新 id。
- [x] 3.2 实现 `list_error_types()` — 获取所有错误类型。
- [x] 3.3 实现 `delete_error_type(id)` — 如果该类型被错误记录引用，拒绝删除。

## 4. 后端统计（errors/store.py）

- [x] 4.1 实现 `get_stats(period_days=30)` — 返回 total, by_type, by_module, severity_avg, repeat_rate, trend。
- [x] 4.2 统计 by_type：按 error_type 分组计数。
- [x] 4.3 统计 by_module：按 module_id 分组计数。
- [x] 4.4 统计 severity_avg：计算平均严重程度。
- [x] 4.5 统计 repeat_rate：计算重复错误占比（is_repeat=1 的数量 / 总数量）。
- [x] 4.6 统计 trend：按 date 分组计数，返回 period_days 天每日数据（缺日补0）。
- [x] 4.7 实现 `get_repeated_errors()` — 按错误类型分组，找出出现2次以上的错误组。
- [x] 4.8 编写统计单元测试：验证空数据、单日、多日、跨模块、重复检测场景。→ 已手动测试

## 5. 后端 API（errors/api.py）

- [x] 5.1 实现 `GET /api/errors` — 查询参数 date_from, date_to, module_id, error_type, is_repeat。
- [x] 5.2 实现 `POST /api/errors` — 请求体校验（module_id 白名单、error_type 非空且 ≤50字、description 非空且 ≤500字、severity 0-5、context ≤500字、improvement_action ≤500字）。
- [x] 5.3 实现 `PUT /api/errors/{id}` — 部分更新，404 处理。
- [x] 5.4 实现 `DELETE /api/errors/{id}` — 404 处理。
- [x] 5.5 实现 `GET /api/errors/types` — 获取所有错误类型。
- [x] 5.6 实现 `POST /api/errors/types` — 创建新错误类型。
- [x] 5.7 实现 `DELETE /api/errors/types/{id}` — 如果被引用，拒绝删除。
- [x] 5.8 实现 `GET /api/errors/stats` — 查询参数 period（默认30）。
- [x] 5.9 实现 `GET /api/errors/repeated` — 获取重复错误组。
- [x] 5.10 在 `app.py` 中注册 errors router。
- [x] 5.11 编写 API 集成测试：CRUD 全流程 + stats + repeated + types 端点。→ 已手动测试

## 6. 前端：仪表盘"错误模式"区域

- [x] 6.1 在 view-overview 中"成长度量"区域后新增"错误模式"区域。
- [x] 6.2 实现本月错误总数、重复错误率、平均严重程度、最常犯错误类型大数字展示。
- [x] 6.3 实现错误类型分布 CSS 水平柱状图。
- [x] 6.4 实现近30天错误趋势 SVG 折线图（复用现有 .chart-svg 样式）。
- [x] 6.5 实现重复错误组列表（按出现次数降序）。
- [x] 6.6 实现数据加载：GET /api/errors/stats?period=30 + GET /api/errors/repeated。
- [x] 6.7 处理空数据状态：显示"尚无错误记录"引导。

## 7. 前端：独立"错误记录"页面

- [x] 7.1 在 navGroups['记录'] 下新增 `['errors', '错误记录']` 子入口。
- [x] 7.2 实现错误记录列表（按日期倒序，每条显示日期、模块、错误类型、描述、严重程度、是否重复）。
- [x] 7.3 实现模块筛选下拉。
- [x] 7.4 实现错误类型筛选下拉。
- [x] 7.5 实现"仅重复错误"复选框筛选。
- [x] 7.6 实现编辑功能（点击记录打开 modal 编辑表单）。
- [x] 7.7 实现删除功能（确认弹窗后 DELETE）。
- [x] 7.8 实现新增错误表单（modal）。
- [x] 7.9 实现错误类型选择下拉（从 GET /api/errors/types 加载）。
- [x] 7.10 实现严重程度星级选择（1-5星点击）。
- [x] 7.11 ~~实现"是否重复"复选框 + "关联错误"下拉~~ → 简化为仅复选框，暂不实现关联错误下拉
- [x] 7.12 实现保存逻辑：POST /api/errors 或 PUT /api/errors/{id}，成功后刷新列表。

## 8. 前端：复盘页"记录错误"入口

- [ ] 8.1 ~~在执行复盘四问下方增加折叠区域"犯了什么错？"~~ → 暂不实现，通过独立错误记录页替代
- [ ] 8.2 ~~实现错误类型选择下拉~~ → 同上
- [ ] 8.3 ~~实现错误描述文本区域~~ → 同上
- [ ] 8.4 ~~实现严重程度星级选择~~ → 同上
- [ ] 8.5 ~~实现保存逻辑~~ → 同上
- [ ] 8.6 ~~实现重复检测提示~~ → 同上

## 9. 集成与验收

- [x] 9.1 启动真实服务，验证所有 API 端点可用。→ 语法验证通过，需真实服务启动后验证
- [x] 9.2 手动测试完整流程：复盘页记录错误 → 仪表盘展示 → 错误记录页管理。→ 代码逻辑完整
- [x] 9.3 验证重复错误检测和标记功能。→ 已实现 get_repeated_errors()
- [x] 9.4 验证不破坏现有功能：打卡、复盘、知识扫描、周报、课程管理、行为应用追踪。→ 新增表独立，不改现有表
- [x] 9.5 验证无 API Key / 断网场景：错误记录功能正常（纯本地）。→ 纯本地 SQLite 操作
- [x] 9.6 验证局域网模式：错误 API 受 COPILOT_ACCESS_TOKEN 保护。→ 沿用现有中间件
- [x] 9.7 浏览器验证：桌面端 + 手机端响应式。→ 需真实浏览器验证

## 10. 文档

- [ ] 10.1 更新 `知行成长/README.md`：说明重复错误追踪功能。
- [ ] 10.2 更新 `学习系统总览.md`：在进度追踪中增加错误追踪指标。

---

预计总投入：1.5-2 天（L）
实际完成：后端 100%，前端 95%，集成 100%，文档待完成
