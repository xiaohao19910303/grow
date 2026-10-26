## ADDED Requirements

### Requirement: Layered optional reviews
The system SHALL offer trading-day, campaign, weekly, monthly, quarterly and event-triggered reviews with optional prompts. It MUST support a one-sentence or no-trade review without requiring invented transactions or completed questionnaires.

#### Scenario: Intentional no-trade session
- **WHEN** the user records that no plan condition triggered
- **THEN** the record can be saved and reviewed without adding a zero-profit completed trade

### Requirement: Separate result and process
The system SHALL display original decision evidence, changes, actual fills and realized/floating outcomes side by side. Profitability, thesis validation and rule adherence MUST be independently expressible.

#### Scenario: Profitable rule violation
- **WHEN** a user profits after violating an agreed entry condition
- **THEN** the review records both the positive financial result and the violation without converting profitability into proof of sound process

### Requirement: Honest risk and performance metrics
The system MUST disclose metric formulas, period, sample, fee completeness and data prerequisites. Original R bases SHALL remain immutable; incomplete MAE/MFE, TWR, XIRR or cash-flow-adjusted drawdown MUST be unavailable or explicitly approximate.

#### Scenario: Intraday path is missing
- **WHEN** only daily high/low values exist for a position entered during that day
- **THEN** the system does not present those whole-day extremes as exact post-entry MAE/MFE

#### Scenario: Added risk in a campaign
- **WHEN** a user adds a position under a newly confirmed risk budget
- **THEN** campaign R uses the sum of frozen incremental risk budgets and does not improve by retroactively reducing the earlier denominator

#### Scenario: Insufficient performance observations
- **WHEN** a filtered strategy sample is small or excludes open campaigns
- **THEN** the display shows sample limits, selection and outstanding risk and does not describe the observed result as proof of an edge

### Requirement: Versioned principles and falsifiable experiments
The system SHALL preserve user thoughts and AI-organized versions separately. A proposed rule change MUST link supporting evidence, contrary cases, a defined validation scope and a versioned user decision before affecting later plans.

#### Scenario: One losing trade suggests a new rule
- **WHEN** AI proposes a rule from one loss
- **THEN** it remains a testable candidate with limited evidence rather than automatically changing existing strategy versions

### Requirement: Minimal authorized Grow integration
The system SHALL connect reviews to decisions, actions, errors and knowledge through account-checked stable references. General dashboards and AI growth reports MUST NOT automatically include private financial amounts or investment input snapshots.

#### Scenario: Review creates a next action
- **WHEN** the user explicitly converts a review improvement into an action
- **THEN** one linked action is created idempotently without duplicating the trade facts or marking a course completed

#### Scenario: Referenced object becomes unavailable
- **WHEN** a linked record is deleted or no longer accessible
- **THEN** the review preserves its own text and shows an unavailable reference without exposing another account's data
