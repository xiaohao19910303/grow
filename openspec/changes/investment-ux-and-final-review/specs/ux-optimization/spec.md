## ADDED Requirements

### Requirement: Browser end-to-end testing
The system SHALL provide comprehensive browser-based testing for all P0 and P1 features, covering account creation, trade recording, balance calculation, AI analysis, and review workflows.

#### Scenario: Complete P0 workflow in browser
- **WHEN** user creates an investment account, adds instruments, records buy/sell trades, and views balance
- **THEN** system displays correct cash balance, positions, realized P&L, and unrealized P&L matching the hand-calculation example

#### Scenario: Complete P1 AI workflow in browser
- **WHEN** user selects evidence, submits AI analysis request, and reviews the report
- **THEN** system displays AI-generated summary, facts, inferences, counterarguments, and actionable suggestions

#### Scenario: CSV import and audit correction
- **WHEN** user imports CSV trades and corrects a fill record
- **THEN** system validates CSV format, prevents duplicate imports, and maintains audit trail for corrections

### Requirement: Mobile responsive layout
The system SHALL provide a responsive layout that adapts to mobile devices (phones and tablets), ensuring all investment workspace features are usable on small screens.

#### Scenario: Mobile navigation
- **WHEN** user accesses investment workspace on a mobile device (screen width < 768px)
- **THEN** system displays a single-column layout with collapsible sections and touch-friendly buttons (minimum 44px height)

#### Scenario: Mobile form interaction
- **WHEN** user fills forms (create account, record trade, etc.) on mobile
- **THEN** system displays form fields in a single column with appropriate input types (date picker, number pad) and clear labels

#### Scenario: Mobile table display
- **WHEN** user views trade history or positions on mobile
- **THEN** system displays data in a card-based layout instead of tables, with key information prominent

### Requirement: Error message improvement
The system SHALL provide clear, actionable error messages for all error scenarios, including validation errors, network errors, and data conflicts.

#### Scenario: Form validation error
- **WHEN** user submits a form with invalid data (e.g., negative price, missing required field)
- **THEN** system displays specific error message next to the invalid field with guidance on how to fix it

#### Scenario: Network error
- **WHEN** a network request fails (timeout, server error, etc.)
- **THEN** system displays a user-friendly error message with retry option, avoiding technical jargon

#### Scenario: Data conflict error
- **WHEN** user attempts to update a record that has been modified by another process
- **THEN** system displays conflict details and offers options to reload, merge, or overwrite

### Requirement: Edge case handling
The system SHALL correctly handle edge cases including duplicate CSV imports, missing fee/cost data, and empty states.

#### Scenario: Duplicate CSV import idempotency
- **WHEN** user imports the same CSV file twice
- **THEN** system detects duplicate records by external_id and skips them, showing a message indicating how many records were skipped

#### Scenario: Missing fee or cost data
- **WHEN** a trade record has missing fee or cost fields
- **THEN** system displays "pending verification" status and excludes the record from P&L calculations until data is complete

#### Scenario: Empty state display
- **WHEN** user views a section with no data (no accounts, no trades, etc.)
- **THEN** system displays a helpful empty state message with guidance on how to get started
