## ADDED Requirements

### Requirement: Read-only private factual projection
The system SHALL derive one fact from saved records in the authenticated tenant only, without model calls or database writes, and SHALL expose its date, timezone, source and evidence. Future or malformed record dates MUST NOT count.

#### Scenario: No records
- **WHEN** an initialized account has no relevant records
- **THEN** the response contains an explicit empty fact and makes no inference about effort or ability

#### Scenario: Unavailable database
- **WHEN** the projection cannot read its data
- **THEN** a sanitized 503 is returned instead of zero counts or old personal facts

#### Scenario: Different accounts
- **WHEN** accounts have different records or a stale page uses another account ID
- **THEN** facts remain isolated and existing authentication rejects unauthorized or stale requests

### Requirement: Deterministic rules with sample boundaries
The system SHALL prioritize a three-complete-day decrease in positive classification counts, then a course confirmation gap of at least14 days, then at least5 resolved predictions entered in the current week, then activity summaries. It MUST name records rather than claim actual decline, unobserved review absence, mastery or probability calibration.

#### Scenario: Decreasing daily records
- **WHEN** the last three completed Beijing dates have respectively3,2,1 classification records
- **THEN** the fact names those dates and values and states that it describes records only

#### Scenario: Missing samples
- **WHEN** any of those days has no record, or the prediction sample is below5
- **THEN** no decrease or prediction-performance fact is produced from that insufficient sample

#### Scenario: Course gap
- **WHEN** an eligible course has a latest completion-confirmation record at least14 days ago
- **THEN** the fact names its title, date, interval and threshold without claiming no review took place

### Requirement: Foreground reminder reuse
The client SHALL automatically display the fact on Today and Growth overview, reuse the existing foreground action reminder refresh loop, yield to due actions and allow per-account per-day dismissal. It MUST NOT create a new timer, notification permission request, push or AI generation.

#### Scenario: Navigation and reload
- **WHEN** the user opens Today or Growth without clicking generate
- **THEN** the same current-day fact and evidence appear, with no repeated concurrent fetch

#### Scenario: Due action
- **WHEN** an existing action reminder is due
- **THEN** the coach card yields until that reminder is no longer due

#### Scenario: Dismissal or account change
- **WHEN** the user dismisses the card today or the account changes while a response is pending
- **THEN** no stale fact is rendered; dismissal is scoped to the original account and day

#### Scenario: Failure and refresh
- **WHEN** a request fails, a record is saved or a Beijing day changes
- **THEN** the client provides retry, refreshes after confirmed saves or day change, and does not retain stale factual claims on error
