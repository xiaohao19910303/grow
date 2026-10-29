## ADDED Requirements
### Requirement: Flexible goal ownership
The system SHALL preserve existing IDs and support goals, standalone month/week/custom plans and undated actions with optional parents, without date containment requirements.
#### Scenario: Independent short plan
- **WHEN** a user creates a week plan without a goal and later links it
- **THEN** the plan and its actions retain their IDs and history.
#### Scenario: Flexible scheduling
- **WHEN** a linked action is undated or rescheduled outside its parent period
- **THEN** ownership is preserved and an informational warning is shown.
### Requirement: Trustworthy results
The system SHALL support manual values, milestone completion and fixed-target effective action counts, keeping effort separate and requiring explicit goal completion.
#### Scenario: Reversal
- **WHEN** an action completion is reversed
- **THEN** automatic counts recalculate without changing old review snapshots.
### Requirement: Unified creation and navigation
The system SHALL provide goal/cycle views, one create entry, contextual editors, responsive details and recoverable account-scoped drafts.
#### Scenario: Save response lost
- **WHEN** a submission response is lost
- **THEN** the original request can be resolved or retried without duplicating objects.
### Requirement: Weekly planning
The system SHALL save future weekly intentions separately from factual weekly reviews and deduplicate estimated workload.
#### Scenario: Incomplete estimates
- **WHEN** selected actions lack duration estimates
- **THEN** their count is visible and unspecified capacity is not treated as zero.
### Requirement: AI draft adoption
The system SHALL preview authorized AI input, validate at most 30 draft items, support edited partial adoption atomically and preserve idempotency and revision checks without storing credentials.
#### Scenario: Conflicting adoption
- **WHEN** a parent changes after generation
- **THEN** adoption is rejected with the editable draft retained.
#### Scenario: Interrupted generation
- **WHEN** generation times out or the worker restarts
- **THEN** the draft becomes failed and no paid retry occurs automatically.
