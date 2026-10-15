# 实施任务：AI 行为分析报告

## 1. 数据模型与迁移

- [ ] 1.1 在 `app.py` 启动逻辑中新增 `behavior_reports` 表创建（含索引）。
- [ ] 1.2 确认新表不进入现有 `TABLES` 全量同步列表。
- [ ] 1.3 编写迁移测试：临时 SQLite 验证表结构正确。

## 2. 数据收集（behavior_report/analyzer.py）

- [ ] 2.1 实现 `collect_data_summary(period_days=30)` — 收集近 N 天数据摘要。
- [ ] 2.2 收集打卡数据：各模块完成天数、总完成率。
- [ ] 2.3 收集习惯数据：总时长、日均时长、趋势。
- [ ] 2.4 收集行为应用数据：总数、Top 概念、按模块分布。
- [ ] 2.5 收集错误数据：总数、Top 类型、重复率。
- [ ] 2.6 收集预测数据：总数、准确率、Brier Score。
- [ ] 2.7 收集复盘数据：总数、主题关键词。

## 3. AI 分析（behavior_report/analyzer.py）

- [ ] 3.1 实现 `build_prompt(data_summary)` — 构建 AI prompt。
- [ ] 3.2 实现 `generate_report(data_summary)` — 调用 AI API 生成报告。
- [ ] 3.3 复用 copilot 模块的 `call_ai()` 函数。
- [ ] 3.4 处理 AI API 调用失败（返回错误信息）。
- [ ] 3.5 验证报告格式（Markdown）。

## 4. 后端存储（behavior_report/store.py）

- [ ] 4.1 实现 `BehaviorReportStore` 类。
- [ ] 4.2 实现 `create_report(date, period_days, content, data_summary)` — 插入报告。
- [ ] 4.3 实现 `list_reports()` — 获取报告列表（按日期倒序）。
- [ ] 4.4 实现 `get_report(id)` — 获取单个报告。
- [ ] 4.5 实现 `delete_report(id)` — 删除报告。

## 5. 后端 API（behavior_report/api.py）

- [ ] 5.1 实现 `POST /api/behavior-report/generate` — 生成新报告（调用 AI）。
- [ ] 5.2 实现 `GET /api/behavior-report` — 获取报告列表。
- [ ] 5.3 实现 `GET /api/behavior-report/{id}` — 获取单个报告。
- [ ] 5.4 实现 `DELETE /api/behavior-report/{id}` — 删除报告。
- [ ] 5.5 在 `app.py` 中注册 behavior_report router。
- [ ] 5.6 编写 API 集成测试：生成 → 查询 → 删除流程。

## 6. 前端：仪表盘"AI 报告"区域

- [ ] 6.1 在 view-overview 中"预测校准"区域后新增"AI 报告"区域。
- [ ] 6.2 实现最新报告摘要展示（日期、前3行内容）。
- [ ] 6.3 实现"生成新报告"按钮（带加载状态）。
- [ ] 6.4 实现数据加载：GET /api/behavior-report（取最新1条）。
- [ ] 6.5 处理空数据状态：显示"尚无报告"引导。

## 7. 前端：独立"AI 报告"页面

- [ ] 7.1 在 navGroups['成长'] 下新增 `['ai-report', 'AI 报告']` 子入口。
- [ ] 7.2 实现报告列表（按日期倒序，每条显示日期、预览）。
- [ ] 7.3 实现报告详情弹窗（Markdown 渲染）。
- [ ] 7.4 实现 Markdown 简单渲染（标题、列表、加粗）。
- [ ] 7.5 实现删除功能（确认弹窗后 DELETE）。
- [ ] 7.6 实现生成新报告功能（POST /api/behavior-report/generate）。
- [ ] 7.7 实现加载状态（AI 生成时显示"正在生成..."）。
- [ ] 7.8 实现错误处理（AI 调用失败时显示错误信息）。

## 8. 集成与验收

- [ ] 8.1 启动真实服务，验证所有 API 端点可用。
- [ ] 8.2 手动测试完整流程：生成报告 → 查看报告 → 删除报告。
- [ ] 8.3 验证 AI API 调用失败时的错误处理。
- [ ] 8.4 验证不破坏现有功能。
- [ ] 8.5 浏览器验证：桌面端 + 手机端响应式。

## 9. 文档

- [ ] 9.1 更新 `知行成长/README.md`：说明 AI 行为分析报告功能。
- [ ] 9.2 更新 `学习系统总览.md`：在进度追踪中增加 AI 报告指标。

---

预计总投入：1-1.5 天（M-L）
