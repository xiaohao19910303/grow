# 实施任务：预测校准可视化

## 1. 后端统计层（predictions/store.py）

- [x] 1.1 创建 `predictions/store.py`，实现 `PredictionStats` 类。
- [x] 1.2 实现 `get_calibration()` — 分桶统计（10 个桶：0-10, 10-20, ..., 90-100），返回 count, correct, rate。
- [x] 1.3 实现 `get_accuracy_stats()` — 计算 Brier Score, 准确率, 平均概率, 校准误差。
- [x] 1.4 实现 `get_overconfident(threshold=80)` — 获取 probability >= threshold 且 result = 'incorrect' 的记录。
- [x] 1.5 实现 `get_trend(window=10)` — 按日期排序，滑动窗口计算滚动准确率。
- [x] 1.6 编写单元测试：验证分桶边界、Brier Score 计算、过度自信筛选、滚动窗口。

## 2. 后端 API（predictions/api.py）

- [x] 2.1 创建 `predictions/api.py`，实现 FastAPI router，prefix `/api/predictions`。
- [x] 2.2 实现 `GET /api/predictions/calibration` — 返回校准数据。
- [x] 2.3 实现 `GET /api/predictions/stats` — 返回准确度统计。
- [x] 2.4 实现 `GET /api/predictions/overconfident` — 查询参数 threshold（默认80）。
- [x] 2.5 实现 `GET /api/predictions/trend` — 查询参数 window（默认10）。
- [x] 2.6 在 `app.py` 中注册 predictions router。
- [x] 2.7 编写 API 集成测试：验证所有端点响应格式。

## 3. 前端：仪表盘"预测校准"区域

- [x] 3.1 在 view-overview 中"错误模式"区域后新增"预测校准"区域。
- [x] 3.2 实现统计卡片：总预测数、准确率、Brier Score、待判定数。
- [x] 3.3 实现校准曲线 SVG 散点图（X 轴自报概率，Y 轴实际发生率，45° 对角线）。
- [x] 3.4 实现数据加载：GET /api/predictions/calibration + GET /api/predictions/stats。
- [x] 3.5 处理数据不足状态：显示"至少需要 10 条预测记录"引导。

## 4. 前端：预测分析视图

- [x] 4.1 在 view-predictions 中现有表格上方新增分析区域。
- [x] 4.2 实现大尺寸校准曲线（同 3.3，但更大）。
- [x] 4.3 实现置信度分布直方图（10 个桶的数量分布）。
- [x] 4.4 实现过度自信事件列表（表格：日期、预测内容、概率、结果）。
- [x] 4.5 实现时间趋势折线图（滚动准确率）。
- [x] 4.6 实现数据加载：调用所有预测分析 API。
- [x] 4.7 处理空数据状态。

## 5. 集成与验收

- [x] 5.1 启动真实服务，验证所有 API 端点可用。
- [x] 5.2 手动测试完整流程：录入预测 → 标记结果 → 查看校准分析。
- [x] 5.3 验证不破坏现有预测录入功能。
- [x] 5.4 验证数据不足时的提示信息。
- [x] 5.5 浏览器验证：桌面端 + 手机端响应式。

## 6. 文档

- [x] 6.1 更新 `知行成长/README.md`：说明预测校准可视化功能。
- [x] 6.2 更新 `学习系统总览.md`：在进度追踪中增加预测校准指标。

---

预计总投入：1 天（M）
