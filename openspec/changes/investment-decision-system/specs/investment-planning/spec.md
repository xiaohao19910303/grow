## ADDED Requirements

### Requirement: Purpose-based capital policy
The system SHALL separate planned contributions, actual deposits, buying commitments and estimated trade risk. A confirmed capital policy MUST record its effective period and user-provided constraints without inventing allocation percentages or automatically replenishing losses.

#### Scenario: Missing financial information
- **WHEN** the user requests a personal capital allocation without providing liquidity needs or loss capacity
- **THEN** the system provides scoped education and missing-input questions without presenting a precise allocation as suitable for that user

#### Scenario: Paused new risk
- **WHEN** a capital policy pauses new risk
- **THEN** the system flags conflicting proposed plans while still allowing truthful recording of actual fills and management of existing holdings

### Requirement: Trading-calendar-aware planning
The system SHALL distinguish natural-month budgets, trading-week plans, trading-day preparation and campaign holding periods using a verified market calendar and Asia/Shanghai timezone.

#### Scenario: Holiday or weekend
- **WHEN** a proposed next session falls on a market holiday or weekend
- **THEN** the system uses the next verified session and does not treat missing daily quotes on the closed day as stale intraday data

#### Scenario: Multiweek swing position
- **WHEN** a campaign remains open at the end of a week
- **THEN** its positions, original plan and risk history continue into the next week without forced closing or reset

### Requirement: Immutable confirmed plan versions
The system SHALL retain confirmed strategy and trade-plan versions, their confirmation time and whether they were recorded retrospectively. The first actual fill MUST bind the plan, strategy and initial risk snapshots used for evaluation.

#### Scenario: Stop widened after entry
- **WHEN** a user changes the invalidation price after entry
- **THEN** the system appends a new version and preserves the initial risk basis for historical R calculations

#### Scenario: Actual fill without prior plan
- **WHEN** a fill precedes any confirmed plan
- **THEN** the fill can be saved, its plan is marked retrospective or absent, and the system does not classify it as proven plan adherence

### Requirement: Conditional executable plans
The system MUST require instrument identity, valid data timing, entry and invalidation conditions, period and user constraints before classifying a plan as executable. Price-based sizing SHALL use deterministic calculations, verified instrument rules and disclosed assumptions.

#### Scenario: Unknown rule or missing budget
- **WHEN** an otherwise complete plan lacks verified selling rules or risk budget
- **THEN** it remains a research/watch draft and no executable share quantity is asserted

#### Scenario: Estimated stop risk
- **WHEN** the system displays stop-based planned loss
- **THEN** it identifies the exit-price assumption and displays possible excess loss from gaps, trading restrictions or failed execution

### Requirement: Non-trade decisions
The system SHALL preserve declined, expired, untriggered and intentionally skipped plans without treating them as fills or profitable trades.

#### Scenario: Conditions never occur
- **WHEN** a confirmed plan expires without its trigger occurring
- **THEN** the system records the expiration and its reason and excludes it from realized trade win-rate calculations
