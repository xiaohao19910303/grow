## ADDED Requirements

### Requirement: Multi-dimensional stock screening
The system SHALL provide a stock screening engine that supports multiple filtering conditions across price, volume, technical indicators, and fundamental metrics.

#### Scenario: Single condition screening
- **WHEN** user applies a single filter condition (e.g., 7-day price change > 10%)
- **THEN** system returns all stocks matching the condition, sorted by the specified field

#### Scenario: Multiple AND conditions
- **WHEN** user applies multiple conditions with AND logic (e.g., 7-day change > 10% AND volume ratio > 1.5)
- **THEN** system returns only stocks matching ALL conditions

#### Scenario: Multiple OR conditions
- **WHEN** user applies multiple conditions with OR logic (e.g., 7-day change > 10% OR turnover rate > 5%)
- **THEN** system returns stocks matching ANY of the conditions

#### Scenario: Screening result pagination
- **WHEN** screening returns more than 50 results
- **THEN** system displays results in pages of 50 items, with navigation controls

### Requirement: Configurable screening conditions
The system SHALL support a predefined set of screening conditions that users can combine to create custom filters.

#### Scenario: Price-based conditions
- **WHEN** user selects price-based conditions
- **THEN** system offers conditions: current price, price change (1d/3d/7d/30d), price relative to MA (5/10/20/60), distance from high/low

#### Scenario: Volume-based conditions
- **WHEN** user selects volume-based conditions
- **THEN** system offers conditions: trading volume, volume ratio (vs 5-day average), turnover rate, turnover amount

#### Scenario: Fundamental conditions
- **WHEN** user selects fundamental conditions
- **THEN** system offers conditions: PE ratio, PB ratio, ROE, market cap, revenue growth

### Requirement: Screening preset management
The system SHALL allow users to save, load, and manage screening presets for reusable filtering strategies.

#### Scenario: Save screening preset
- **WHEN** user creates a screening configuration and clicks "Save Preset"
- **THEN** system saves the configuration with a user-provided name, storing conditions and logic

#### Scenario: Load screening preset
- **WHEN** user selects a saved preset from the list
- **THEN** system loads the preset configuration into the screening interface and executes the screening

#### Scenario: Delete screening preset
- **WHEN** user deletes a saved preset
- **THEN** system removes the preset from the list after confirmation

### Requirement: AI-assisted screening analysis
The system SHALL provide AI-powered analysis of screening results, identifying patterns and providing insights.

#### Scenario: AI pattern analysis
- **WHEN** screening returns results and user clicks "AI Analysis"
- **THEN** system analyzes the results using AI, identifying sector concentration, common characteristics, and potential risks

#### Scenario: AI risk warning
- **WHEN** screening results include stocks with high recent gains or unusual volume
- **THEN** system displays AI-generated risk warnings about potential chase-high risks or volume anomalies

### Requirement: Screening data freshness
The system SHALL indicate the data freshness of screening results and support manual refresh.

#### Scenario: Data freshness indicator
- **WHEN** screening results are displayed
- **THEN** system shows the timestamp of the underlying data (e.g., "Data as of 2026-10-27 15:00")

#### Scenario: Manual data refresh
- **WHEN** user clicks "Refresh Data"
- **THEN** system fetches the latest data from the data source and re-executes the screening
