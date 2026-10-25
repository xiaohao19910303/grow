## ADDED Requirements

### Requirement: Explicit recoverable learning-plan association
The system SHALL allow an adopted learning plan to be linked to existing action execution using a tenant-scoped ledger, an idempotency key and an expected formal version. It MUST create content actions only for published incomplete lessons, without dates or reminders, and MUST preserve matching existing actions and user changes.

#### Scenario: Adoption without published lessons
- **WHEN** a user adopts and links a formal plan that has no published courses
- **THEN** tracking exists with zero executable actions and no invalid lesson references

#### Scenario: Repeated or concurrent association
- **WHEN** the same account links the same plan more than once
- **THEN** each lesson maps to one existing or newly created action without duplicate creation

#### Scenario: Future lessons become available
- **WHEN** a linked active plan publishes another formal incomplete lesson
- **THEN** the lesson is added once without overwriting any earlier action's date, state or facts

#### Scenario: Partial success
- **WHEN** formal content saves successfully but action synchronization fails
- **THEN** the result reports saved content and a separate retryable synchronization warning, and retry does not regenerate or republish content

### Requirement: Honest live plan and stage progress
The action view SHALL project the current formal plan and stage completion from distinct published lessons with explicit completed feedback. It MUST distinguish publication, learning completion and action execution and MUST NOT write facts on read.

#### Scenario: Source completion
- **WHEN** a published lesson is explicitly marked learned
- **THEN** its plan and stage progress update once through existing completion semantics

#### Scenario: Notes or timed effort
- **WHEN** a user only generates content, saves notes or confirms action minutes
- **THEN** no additional lesson is counted as learned

### Requirement: Lifecycle and ownership preservation
The system SHALL stop supplementing inactive or disabled links without deleting existing actions. It MUST reject local link writes when external ownership is pending or active, and MUST enforce existing account and same-origin protections.

#### Scenario: Pause, cancellation or manual edit
- **WHEN** a learning plan is paused or a linked action is changed or archived
- **THEN** synchronization does not duplicate, reactivate, reschedule or erase existing records

#### Scenario: Account isolation and external handoff
- **WHEN** another account guesses a plan ID or action ownership is handed off
- **THEN** no source records leak and no fallback local action writes occur
