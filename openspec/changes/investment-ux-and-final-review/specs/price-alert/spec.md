## ADDED Requirements

### Requirement: Price alert creation
The system SHALL allow users to create price alerts for specific instruments with configurable conditions and thresholds.

#### Scenario: Create price above alert
- **WHEN** user creates an alert with condition "price above" and threshold 100.00 for instrument 600519
- **THEN** system saves the alert and monitors the instrument price

#### Scenario: Create price below alert
- **WHEN** user creates an alert with condition "price below" and threshold 90.00 for instrument 600519
- **THEN** system saves the alert and monitors the instrument price

#### Scenario: Create percentage change alert
- **WHEN** user creates an alert with condition "daily change above" and threshold 5% for instrument 600519
- **THEN** system saves the alert and monitors the instrument's daily price change

### Requirement: Alert monitoring and notification
The system SHALL monitor alert conditions at regular intervals and send browser notifications when conditions are met.

#### Scenario: Alert trigger and notification
- **WHEN** an instrument price meets an alert condition (e.g., price rises above 100.00)
- **THEN** system sends a browser notification with alert details and marks the alert as triggered

#### Scenario: Periodic monitoring
- **WHEN** alerts are enabled
- **THEN** system checks alert conditions every 5 minutes (configurable) during trading hours

#### Scenario: Notification permission
- **WHEN** user enables alerts but has not granted notification permission
- **THEN** system prompts user to grant browser notification permission

### Requirement: Alert management
The system SHALL allow users to view, edit, enable/disable, and delete their price alerts.

#### Scenario: View all alerts
- **WHEN** user opens the alerts page
- **THEN** system displays a list of all alerts with status (enabled/disabled), last triggered time, and condition details

#### Scenario: Edit alert
- **WHEN** user edits an existing alert's threshold or condition
- **THEN** system updates the alert configuration and resets the triggered status

#### Scenario: Disable alert
- **WHEN** user disables an alert
- **THEN** system stops monitoring the alert condition but preserves the alert configuration

#### Scenario: Delete alert
- **WHEN** user deletes an alert
- **THEN** system removes the alert after confirmation and stops monitoring

### Requirement: Alert history and tracking
The system SHALL maintain a history of triggered alerts for review and analysis.

#### Scenario: View alert history
- **WHEN** user opens the alert history page
- **THEN** system displays a chronological list of triggered alerts with timestamp, instrument, condition, and price at trigger

#### Scenario: Alert cooldown period
- **WHEN** an alert is triggered
- **THEN** system does not re-trigger the same alert for the same condition within 24 hours (configurable cooldown)

### Requirement: Alert data source
The system SHALL use the configured market data source (Tushare/AKShare) to fetch real-time or delayed prices for alert monitoring.

#### Scenario: Price data fetching
- **WHEN** monitoring alerts
- **THEN** system fetches the latest available price from the data source (real-time if available, otherwise delayed)

#### Scenario: Data source failure
- **WHEN** data source is unavailable or returns errors
- **THEN** system logs the error, continues monitoring with last known price, and displays a warning to the user

#### Scenario: Trading hours awareness
- **WHEN** monitoring alerts outside trading hours (weekends, holidays, after hours)
- **THEN** system pauses monitoring and resumes at the next trading session
