## 1. Phase 1: User Experience Optimization

- [ ] 1.1 Start grow server and verify all P0/P1 endpoints are accessible
- [ ] 1.2 Test investment account creation workflow in browser (create, view, edit)
- [ ] 1.3 Test instrument management workflow (add stock/ETF/fund, view list)
- [ ] 1.4 Test trade recording workflow (buy/sell, CSV import, audit correction)
- [ ] 1.5 Test balance and position display accuracy (verify against hand-calculation example)
- [ ] 1.6 Test fund policy management (create, edit, state transitions)
- [ ] 1.7 Test strategy management (create, edit, versioning)
- [ ] 1.8 Test trade plan management (create, edit, confirm, expire)
- [ ] 1.9 Test review creation and management (daily, campaign, weekly, monthly)
- [ ] 1.10 Test AI analysis workflow (preview, submit, view report, handle suggestions)
- [ ] 1.11 Test CSV import with duplicate detection and idempotency
- [ ] 1.12 Test audit correction workflow and version history
- [ ] 1.13 Record all issues found during browser testing in a bug list
- [ ] 1.14 Fix critical bugs (data loss, calculation errors, security issues)
- [ ] 1.15 Fix major bugs (broken workflows, incorrect display, poor error messages)
- [ ] 1.16 Fix minor bugs (cosmetic issues, minor UX problems)
- [ ] 1.17 Optimize mobile layout for investment workspace main page
- [ ] 1.18 Optimize mobile layout for account and instrument forms
- [ ] 1.19 Optimize mobile layout for trade recording and balance display
- [ ] 1.20 Optimize mobile layout for AI analysis dialog and report display
- [ ] 1.21 Improve form validation error messages (specific field-level errors)
- [ ] 1.22 Improve network error messages (user-friendly, retry option)
- [ ] 1.23 Improve data conflict error messages (show conflict details, merge options)
- [ ] 1.24 Add empty state messages for all sections (no accounts, no trades, etc.)
- [ ] 1.25 Test edge cases: duplicate CSV import, missing fee/cost, empty states
- [ ] 1.26 Verify all fixes by re-running browser tests

## 2. Phase 2: P2 Feature Development - Market Screener

- [ ] 2.1 Design screener data model (ScreenerCondition, ScreenerPreset tables)
- [ ] 2.2 Implement screener backend API endpoints (POST /screener/run, GET /screener/presets)
- [ ] 2.3 Implement screening engine with support for price-based conditions (price change, MA relative, etc.)
- [ ] 2.4 Implement volume-based conditions (volume ratio, turnover rate, etc.)
- [ ] 2.5 Implement fundamental conditions (PE, PB, ROE, market cap, etc.)
- [ ] 2.6 Implement AND/OR logic for combining multiple conditions
- [ ] 2.7 Implement screening result pagination and sorting
- [ ] 2.8 Implement preset save/load/delete functionality
- [ ] 2.9 Integrate AI analysis for screening results (pattern identification, risk warnings)
- [ ] 2.10 Add data freshness indicator and manual refresh button
- [ ] 2.11 Implement frontend screener UI (condition builder, result display, preset management)
- [ ] 2.12 Test screener with various condition combinations and verify accuracy
- [ ] 2.13 Optimize screener performance for large result sets

## 3. Phase 2: P2 Feature Development - Price Alert

- [ ] 3.1 Design alert data model (PriceAlert, AlertHistory tables)
- [ ] 3.2 Implement alert backend API endpoints (CRUD for alerts, GET /alerts/history)
- [ ] 3.3 Implement alert monitoring service (periodic price checking)
- [ ] 3.4 Implement browser notification integration (Notification API)
- [ ] 3.5 Implement alert condition types (price above/below, daily change above/below)
- [ ] 3.6 Implement alert cooldown mechanism to prevent duplicate notifications
- [ ] 3.7 Implement trading hours awareness (pause monitoring outside trading hours)
- [ ] 3.8 Implement alert history tracking and display
- [ ] 3.9 Handle data source failures gracefully (use last known price, show warning)
- [ ] 3.10 Implement frontend alert UI (create/edit/delete alerts, view history)
- [ ] 3.11 Test alert triggering and notification delivery
- [ ] 3.12 Test alert behavior during different market conditions (trading hours, holidays, etc.)

## 4. Phase 2: P2 Feature Development - Minute Replay

- [ ] 4.1 Design minute data table structure (investment_minute_data)
- [ ] 4.2 Implement minute data fetching from data source (Tushare/AKShare)
- [ ] 4.3 Implement minute data caching in database
- [ ] 4.4 Implement minute replay backend API (GET /replay/{instrument_id})
- [ ] 4.5 Integrate chart library (ECharts or similar) for K-line display
- [ ] 4.6 Implement candlestick chart with volume bars
- [ ] 4.7 Implement playback controls (play/pause, step, speed adjustment)
- [ ] 4.8 Implement technical indicator calculations (MA, MACD, etc.)
- [ ] 4.9 Implement indicator overlay on chart
- [ ] 4.10 Implement chart interaction (zoom, pan, crosshair)
- [ ] 4.11 Implement frontend replay UI (date selector, controls, chart)
- [ ] 4.12 Test minute replay with historical data and verify accuracy
- [ ] 4.13 Handle missing data scenarios (weekends, holidays, data source limitations)

## 5. Phase 2: P2 Feature Development - Strategy Backtest

- [ ] 5.1 Design backtest data model (BacktestConfig, BacktestResult, BacktestTrade tables)
- [ ] 5.2 Implement event-driven backtesting engine (chronological data processing)
- [ ] 5.3 Implement trading constraint enforcement (T+1, price limits, suspension)
- [ ] 5.4 Implement fee and slippage simulation (commission, stamp duty, slippage)
- [ ] 5.5 Implement performance metrics calculation (return, drawdown, Sharpe ratio, etc.)
- [ ] 5.6 Implement trade statistics (win rate, avg profit/loss, holding period)
- [ ] 5.7 Implement backtest configuration API (strategy logic, initial capital, costs)
- [ ] 5.8 Implement backtest result API (metrics, trades, equity curve data)
- [ ] 5.9 Implement result visualization (equity curve, drawdown chart, trade markers)
- [ ] 5.10 Implement result export functionality (CSV download)
- [ ] 5.11 Implement frontend backtest UI (configuration form, result display, export)
- [ ] 5.12 Test backtest with known strategies and verify accuracy against manual calculation
- [ ] 5.13 Optimize backtest performance for long date ranges and large datasets

## 6. Phase 3: Code Review and Submission

- [ ] 6.1 Review core logic: cost calculation, Decimal precision, data model correctness
- [ ] 6.2 Review security: account isolation, input validation, SQL injection prevention
- [ ] 6.3 Review API design: endpoint consistency, error handling, authentication
- [ ] 6.4 Review frontend code: component structure, state management, error handling
- [ ] 6.5 Review performance: identify N+1 queries, large data transfers, optimization opportunities
- [ ] 6.6 Review code style: naming conventions, comments, file organization
- [ ] 6.7 Update user guide with new P2 features (screener, alerts, replay, backtest)
- [ ] 6.8 Update API documentation with new endpoints
- [ ] 6.9 Update deployment documentation with new dependencies and configuration
- [ ] 6.10 Create git commits for UX optimization (group related fixes)
- [ ] 6.11 Create git commits for market screener feature
- [ ] 6.12 Create git commits for price alert feature
- [ ] 6.13 Create git commits for minute replay feature
- [ ] 6.14 Create git commits for strategy backtest feature
- [ ] 6.15 Create git commits for documentation updates
- [ ] 6.16 Create pull request with comprehensive description and testing evidence
- [ ] 6.17 Perform pre-merge validation (run tests, resolve conflicts)
- [ ] 6.18 Merge pull request and perform post-merge actions (deployment, notification, cleanup)
