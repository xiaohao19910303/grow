## ADDED Requirements

### Requirement: Shared authoritative actions
Zook SHALL persist four-period plans, hierarchy, explicit horizons, execution outcomes, reminders and private review history and expose an app-scoped canonical API.

#### Scenario: Cross-client execution
- **WHEN** a registered client starts, interrupts or completes a shared action
- **THEN** the connected webpage and another client observe the same revision, running session, facts and aggregate progress without marking a course learned

### Requirement: Verified single-writer linking
Pairing SHALL require both authenticated accounts and an explicit short-lived connection code confirmation. Source writes SHALL freeze before import, original IDs and a verified receipt SHALL be preserved, and uncertain imports SHALL remain recoverable without two writers.

#### Scenario: Interrupted import
- **WHEN** import succeeds but its response is lost
- **THEN** retry imports once and the webpage activates only after the persisted receipt matches the frozen backup

#### Scenario: Invalid or foreign code
- **WHEN** a code is expired, used by another source, or supplied without trusted server authentication
- **THEN** linking is rejected and existing plans remain owned by their original account

### Requirement: Recoverable native actions and reminders
Both native clients SHALL show pending/current actions, progress and history, preserve account-scoped drafts and stable pending request keys, and schedule user-enabled reminders from verified state.

#### Scenario: Restart and account change
- **WHEN** the client restarts or the signed-in account changes
- **THEN** it restores only that account's pending inputs and server execution and cancels the previous account's reminders

### Requirement: Review consistency
Saved manual reviews and AI result history SHALL be visible to all connected surfaces. Suggestions SHALL not automatically mutate plans.

#### Scenario: Save review from a client
- **WHEN** the user saves a scoped review and refreshes the webpage
- **THEN** the same review content and recorded facts are shown once
