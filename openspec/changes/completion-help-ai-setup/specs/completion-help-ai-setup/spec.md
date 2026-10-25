## ADDED Requirements

### Requirement: Completion rules are accessible
The system SHALL explain course learning completion, time/content/check actions, actual minutes, and stage progress using existing rules without changing facts.

#### Scenario: Open and close help with the keyboard
- **WHEN** a user opens help from settings, action plans or learning plans
- **THEN** the same accessible dialog explains all three action modes and course progress, closes with Escape and returns focus

### Requirement: Guide personal AI setup without automatic requests
The system SHALL guide address, credentials/model and review/save using the existing browser-owned fields, preserving direct editing.

#### Scenario: Save without testing
- **WHEN** a user enters valid configuration and saves
- **THEN** only the current account's browser storage changes and no model request starts

#### Scenario: Explicit connection test
- **WHEN** a user explicitly tests the entered configuration
- **THEN** the existing API tests only that configuration and no secret is shown in status or review

### Requirement: Configuration failures preserve user control
The system SHALL validate before writing or testing and reject stale test results.

#### Scenario: Inputs or account change during a test
- **WHEN** the test finishes after inputs, navigation or account identity change
- **THEN** its result is not presented as verification of the new configuration

#### Scenario: Browser storage is unavailable
- **WHEN** saving fails because storage is denied
- **THEN** a visible error is shown without claiming success or overwriting the prior saved configuration
