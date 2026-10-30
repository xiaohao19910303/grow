## 1. Phase 1: User Experience Optimization

2026-10-29 续实施按 `delivery-closeout.md` 执行。既有能力按真实浏览器与HTTP/数据库专项复验勾选；真实服务验证和软件合同分别记录，不删除或缩小原验收要求。路由、存储及有限策略方案以收口合同和新API文档为准，不新增同义路由或重复表。1.21的逐字段提示、1.23的冲突合并选项仍保留为原UX清单未完成项；当前继续以固定安全校验提示、版本冲突及重新读取处理，不自动合并投资事实。3.11的桌面系统通知送达仍需真实桌面核验，已测试Chrome授权与网页触发链路。

- [x] 1.1 Start grow server and verify all P0/P1 endpoints are accessible
- [x] 1.2 Test investment account creation workflow in browser (create, view, edit)
- [x] 1.3 Test instrument management workflow (add stock/ETF/fund, view list)
- [x] 1.4 Test trade recording workflow (buy/sell, CSV import, audit correction)
- [x] 1.5 Test balance and position display accuracy (verify against hand-calculation example)
- [x] 1.6 Test fund policy management (create, edit, state transitions)
- [x] 1.7 Test strategy management (create, edit, versioning)
- [x] 1.8 Test trade plan management (create, edit, confirm, expire)
- [x] 1.9 Test review creation and management (daily, campaign, weekly, monthly)
- [x] 1.10 Test AI analysis workflow (preview, submit, view report, handle suggestions)
- [x] 1.11 Test CSV import with duplicate detection and idempotency
- [x] 1.12 Test audit correction workflow and version history
- [x] 1.13 Record all issues found during browser testing in a bug list
- [x] 1.14 Fix critical bugs (data loss, calculation errors, security issues)
- [x] 1.15 Fix major bugs (broken workflows, incorrect display, poor error messages)
- [x] 1.16 Fix minor bugs (cosmetic issues, minor UX problems)
- [x] 1.17 Optimize mobile layout for investment workspace main page
- [x] 1.18 Optimize mobile layout for account and instrument forms
- [x] 1.19 Optimize mobile layout for trade recording and balance display
- [x] 1.20 Optimize mobile layout for AI analysis dialog and report display
- [ ] 1.21 Improve form validation error messages (specific field-level errors)
- [x] 1.22 Improve network error messages (user-friendly, retry option)
- [ ] 1.23 Improve data conflict error messages (show conflict details, merge options)
- [x] 1.24 Add empty state messages for all sections (no accounts, no trades, etc.)
- [x] 1.25 Test edge cases: duplicate CSV import, missing fee/cost, empty states
- [x] 1.26 Verify all fixes by re-running browser tests

## 2. Phase 2: P2 Feature Development - Market Screener

- [x] 2.1 Design screener data model (ScreenerCondition, ScreenerPreset tables)
- [x] 2.2 Implement screener backend API endpoints (POST /screener/run, GET /screener/presets)
- [x] 2.3 Implement screening engine with support for price-based conditions (price change, MA relative, etc.)
- [x] 2.4 Implement volume-based conditions (volume ratio, turnover rate, etc.)
- [x] 2.5 Implement fundamental conditions (PE, PB, ROE, market cap, etc.)
- [x] 2.6 Implement AND/OR logic for combining multiple conditions
- [x] 2.7 Implement screening result pagination and sorting
- [x] 2.8 Implement preset save/load/delete functionality
- [x] 2.9 Integrate AI analysis for screening results (pattern identification, risk warnings)
- [x] 2.10 Add data freshness indicator and manual refresh button
- [x] 2.11 Implement frontend screener UI (condition builder, result display, preset management)
- [x] 2.12 Test screener with various condition combinations and verify accuracy
- [x] 2.13 Optimize screener performance for large result sets

## 3. Phase 2: P2 Feature Development - Price Alert

- [x] 3.1 Design alert data model (PriceAlert, AlertHistory tables)
- [x] 3.2 Implement alert backend API endpoints (CRUD for alerts, GET /alerts/history)
- [x] 3.3 Implement alert monitoring service (periodic price checking)
- [x] 3.4 Implement browser notification integration (Notification API)
- [x] 3.5 Implement alert condition types (price above/below, daily change above/below)
- [x] 3.6 Implement alert cooldown mechanism to prevent duplicate notifications
- [x] 3.7 Implement trading hours awareness (pause monitoring outside trading hours)
- [x] 3.8 Implement alert history tracking and display
- [x] 3.9 Handle data source failures gracefully (use last known price, show warning)
- [x] 3.10 Implement frontend alert UI (create/edit/delete alerts, view history)
- [ ] 3.11 Test alert triggering and notification delivery
- [x] 3.12 Test alert behavior during different market conditions (trading hours, holidays, etc.)

## 4. Phase 2: P2 Feature Development - Minute Replay

- [x] 4.1 Design minute data table structure (investment_minute_data)
- [x] 4.2 Implement minute data fetching from data source (Tushare/AKShare)
- [x] 4.3 Implement minute data caching in database
- [x] 4.4 Implement minute replay backend API (GET /replay/{instrument_id})
- [x] 4.5 Integrate chart library (ECharts or similar) for K-line display
- [x] 4.6 Implement candlestick chart with volume bars
- [x] 4.7 Implement playback controls (play/pause, step, speed adjustment)
- [x] 4.8 Implement technical indicator calculations (MA, MACD, etc.)
- [x] 4.9 Implement indicator overlay on chart
- [x] 4.10 Implement chart interaction (zoom, pan, crosshair)
- [x] 4.11 Implement frontend replay UI (date selector, controls, chart)
- [x] 4.12 Test minute replay with historical data and verify accuracy
- [x] 4.13 Handle missing data scenarios (weekends, holidays, data source limitations)

## 5. Phase 2: P2 Feature Development - Strategy Backtest

- [x] 5.1 Design backtest data model (BacktestConfig, BacktestResult, BacktestTrade tables)
- [x] 5.2 Implement event-driven backtesting engine (chronological data processing)
- [x] 5.3 Implement trading constraint enforcement (T+1, price limits, suspension)
- [x] 5.4 Implement fee and slippage simulation (commission, stamp duty, slippage)
- [x] 5.5 Implement performance metrics calculation (return, drawdown, Sharpe ratio, etc.)
- [x] 5.6 Implement trade statistics (win rate, avg profit/loss, holding period)
- [x] 5.7 Implement backtest configuration API (strategy logic, initial capital, costs)
- [x] 5.8 Implement backtest result API (metrics, trades, equity curve data)
- [x] 5.9 Implement result visualization (equity curve, drawdown chart, trade markers)
- [x] 5.10 Implement result export functionality (CSV download)
- [x] 5.11 Implement frontend backtest UI (configuration form, result display, export)
- [x] 5.12 Test backtest with known strategies and verify accuracy against manual calculation
- [x] 5.13 Optimize backtest performance for long date ranges and large datasets

## 6. Phase 3: Code Review and Submission

- [x] 6.1 Review core logic: cost calculation, Decimal precision, data model correctness
- [x] 6.2 Review security: account isolation, input validation, SQL injection prevention
- [x] 6.3 Review API design: endpoint consistency, error handling, authentication
- [x] 6.4 Review frontend code: component structure, state management, error handling
- [x] 6.5 Review performance: identify N+1 queries, large data transfers, optimization opportunities
- [x] 6.6 Review code style: naming conventions, comments, file organization
- [x] 6.7 Update user guide with new P2 features (screener, alerts, replay, backtest)
- [x] 6.8 Update API documentation with new endpoints
- [x] 6.9 Update deployment documentation with new dependencies and configuration
- [x] 6.10 Create git commits for UX optimization (group related fixes)
- [x] 6.11 Create git commits for market screener feature
- [x] 6.12 Create git commits for price alert feature
- [x] 6.13 Create git commits for minute replay feature
- [x] 6.14 Create git commits for strategy backtest feature
- [x] 6.15 Create git commits for documentation updates
- [ ] 6.16 Create pull request with comprehensive description and testing evidence
- [x] 6.17 Perform pre-merge validation (run tests, resolve conflicts)
- [ ] 6.18 Merge pull request and perform post-merge actions (deployment, notification, cleanup)

## 7. 2026-10-29 收口缺口

- [x] 7.1 修复本次发现的 11 项全站回归失败并保留安全、隔离、恢复断言。
- [x] 7.2 统一供应商代码、日期及单位，补数据库写入与非法输入反例。
- [x] 7.3 同源 AI 转发的明确选择、受控目的地、幂等、密钥内存边界和真实浏览器链路。
- [x] 7.4 私人数据集与全市场筛选入口、覆盖率、条件解释、方案及导出。
- [x] 7.5 价格监控、时效与交易时段门槛、冷却去重、通知授权和历史。
- [x] 7.6 历史数据接入、缓存、分钟图表及回放控制。
- [x] 7.7 多周期策略回测、约束成本、样本外与参数试验、图表和导出。
- [x] 7.8 Review、移动桌面流程、隔离备份恢复及单次完整回归。
- [x] 7.9 分别核验真实供应商、真实模型、通知及发布状态，记录尚待外部条件的项目。

## 8. 本地研究归档与跨批次对比（2026-10-30）

本轮按`docs/investment-research-archive-design.md`的归档及筛选／回测对比阶段实施；后续事前观察协议、模型报告语义对比及列式数据卸载仍按设计另行扩展，不替代本轮可复验的确定性比较。

- [x] 8.1 实现受控根目录、私有路径、不可变原子文件、清单哈希和损坏检测。
- [x] 8.2 接入归档状态、保存后归档、显式重试、旧数据及依赖归档；失败不改业务结果。
- [x] 8.3 实现筛选跨日期／跨参数对比，区分未知、覆盖变化与条件变化，保留完整数值解释。
- [x] 8.4 实现回测批次配置、绩效、成交／拒绝差异及可比较性检查。
- [x] 8.5 接入历史批次选择、归档／验证／下载、比较结果及CSV／JSON导出，支持分页和手机。
- [x] 8.6 扩展完整备份、校验与空库／新归档目录恢复，验证数据库和文件引用一致。
- [x] 8.7 验证账号隔离、路径／链接拒绝、断写恢复、磁盘失败、哈希篡改和精确数值往返。
- [ ] 8.8 配置本机独立归档目录，完成真实服务／浏览器流程及适当回归，更新文档并提交。
