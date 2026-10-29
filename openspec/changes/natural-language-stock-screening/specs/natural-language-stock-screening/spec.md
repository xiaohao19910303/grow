## ADDED Requirements

### Requirement: Deterministic personal screening
The system SHALL screen up to 20 selected Shanghai/Shenzhen stocks locally with explicit dates, units, calendar windows, three-valued results and immutable input versions.

#### Scenario: Missing required session
- **WHEN** a required session or turnover value is unavailable
- **THEN** the relevant condition is unknown, not zero or a silently shortened window

### Requirement: Natural language produces drafts only
The system SHALL generate bounded editable rules from user text and expose source mappings, suggestions and unsupported clauses without executing code.

#### Scenario: Suggested threshold
- **WHEN** a model fills a vague threshold
- **THEN** execution is blocked until the user accepts or edits that suggestion

### Requirement: Independent screening and optional analysis
The system SHALL allow screening without model credentials and later analysis of at most five matched candidates.

#### Scenario: Save retry
- **WHEN** uploading a computed result fails
- **THEN** the original result can be uploaded again without repeating model calls

### Requirement: Compatible private templates
The system SHALL retain template versions, original generation provenance and account boundaries while preserving v1 batches.

#### Scenario: Template edit
- **WHEN** a template is changed
- **THEN** an existing frozen run remains unchanged
