## ADDED Requirements

### Requirement: Event-driven backtesting engine
The system SHALL provide an event-driven backtesting engine that processes historical data chronologically and simulates trade execution based on user-defined strategies.

#### Scenario: Load historical data
- **WHEN** user initiates a backtest for a specific instrument and date range
- **THEN** system loads historical data (daily or minute-level) for the specified period

#### Scenario: Process data chronologically
- **WHEN** backtest is running
- **THEN** system processes data points in chronological order, evaluating strategy logic at each time step

#### Scenario: Generate trade signals
- **WHEN** strategy conditions are met at a time step
- **THEN** system generates buy/sell signals and records them for execution

### Requirement: Trading constraint enforcement
The system SHALL enforce trading constraints including T+1 rules, price limits (涨跌停), and suspension status during backtesting.

#### Scenario: T+1 rule enforcement
- **WHEN** a buy trade is executed on day T
- **THEN** system prevents selling the same instrument until day T+1 or later

#### Scenario: Price limit enforcement
- **WHEN** an instrument hits the daily price limit (涨停 or 跌停)
- **THEN** system prevents buying at 涨停 or selling at 跌停, simulating real market constraints

#### Scenario: Suspension handling
- **WHEN** an instrument is suspended on a trading day
- **THEN** system skips that day for the instrument and does not generate trade signals

### Requirement: Fee and slippage simulation
The system SHALL simulate trading costs including commissions, stamp duty, and slippage to provide realistic backtesting results.

#### Scenario: Commission calculation
- **WHEN** a trade is executed
- **THEN** system calculates commission based on configurable rate (e.g., 0.03% with minimum 5 yuan)

#### Scenario: Stamp duty calculation
- **WHEN** a sell trade is executed
- **THEN** system calculates stamp duty (e.g., 0.1% on sell side only)

#### Scenario: Slippage simulation
- **WHEN** a trade is executed
- **THEN** system applies configurable slippage (e.g., 0.1% or 1 tick) to the execution price

### Requirement: Backtest performance metrics
The system SHALL calculate and display comprehensive performance metrics for backtest results.

#### Scenario: Return calculation
- **WHEN** backtest completes
- **THEN** system calculates total return, annualized return, and benchmark comparison (e.g., vs. CSI 300 index)

#### Scenario: Risk metrics
- **WHEN** backtest completes
- **THEN** system calculates maximum drawdown, Sharpe ratio, Sortino ratio, and volatility

#### Scenario: Trade statistics
- **WHEN** backtest completes
- **THEN** system displays total trades, win rate, average profit/loss, largest win/loss, and holding period statistics

### Requirement: Backtest configuration
The system SHALL allow users to configure backtest parameters including strategy logic, initial capital, and cost assumptions.

#### Scenario: Strategy configuration
- **WHEN** user defines a backtest strategy
- **THEN** system accepts strategy logic in a configurable format (e.g., condition-based rules or simple code)

#### Scenario: Initial capital and position sizing
- **WHEN** user sets initial capital (e.g., 100,000 yuan)
- **THEN** system uses this as the starting cash balance and enforces position sizing rules

#### Scenario: Cost configuration
- **WHEN** user configures commission rate, stamp duty, and slippage
- **THEN** system applies these costs to all simulated trades

### Requirement: Backtest result visualization
The system SHALL provide visual representation of backtest results including equity curve, drawdown chart, and trade markers.

#### Scenario: Equity curve display
- **WHEN** backtest completes
- **THEN** system displays an equity curve showing portfolio value over time

#### Scenario: Drawdown chart
- **WHEN** backtest completes
- **THEN** system displays a drawdown chart showing the percentage decline from peak equity

#### Scenario: Trade markers on chart
- **WHEN** backtest completes
- **THEN** system overlays buy/sell markers on the price chart at execution points

### Requirement: Backtest result export
The system SHALL allow users to export backtest results and trade logs for further analysis.

#### Scenario: Export results to CSV
- **WHEN** user clicks "Export Results"
- **THEN** system downloads a CSV file containing performance metrics and trade log

#### Scenario: Export trade log
- **WHEN** user clicks "Export Trade Log"
- **THEN** system downloads a detailed CSV file with all simulated trades including entry/exit prices, quantities, fees, and P&L
