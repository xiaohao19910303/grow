## ADDED Requirements

### Requirement: Private hierarchical planning
The system SHALL support independently created year, month, week and day plans, optional containing parents, business timezone, explicit scheduling, bounded repeated daily creation and optimistic revisions.

#### Scenario: Weekly actions under a year goal
- **WHEN** a user creates a year goal, contained month and week plans and several daily actions
- **THEN** they can browse all levels and see confirmed execution progress without creating duplicate records

#### Scenario: Cross-account and stale changes
- **WHEN** another account or a stale editor addresses a plan
- **THEN** the server returns not-found or conflict and preserves the latest record

### Requirement: Visible and recoverable execution
The homepage SHALL prioritize running, due and upcoming actions before the learning list. Start SHALL persist one active execution and open the linked reader. Completion SHALL require explicit actual-minute confirmation, and minimum/interrupted outcomes SHALL remain distinct.

#### Scenario: Start and return after reload
- **WHEN** a user starts a linked action and reloads
- **THEN** the running execution is restored and can be finished or interrupted without changing course completion or note drafts

#### Scenario: Lost response and repeated finish
- **WHEN** a mutation is retried with the same request key and payload
- **THEN** it produces the original result once; changed payloads and overlapping active sessions are rejected

### Requirement: Honest reminders
The system SHALL support opt-in webpage-open reminders, due banners, bounded snooze, quiet hours and per-device notification deduplication. It SHALL export timezone-correct calendar events with alarms for use outside the webpage.

#### Scenario: Due action and snooze
- **WHEN** an active daily action becomes due and is snoozed
- **THEN** it stays visible, reminder time moves forward once, and completed/paused/archived actions do not notify

#### Scenario: Page is closed
- **WHEN** the user configures reminders
- **THEN** the interface explains the foreground limitation and offers calendar export without claiming mobile push delivery

### Requirement: LightTick design preserves one writer
The integration design SHALL reference existing canonical Zook contracts and require verified identity binding, immutable source mapping and a one-writer cutover before native writes.

#### Scenario: Existing independent accounts
- **WHEN** planning LightTick integration
- **THEN** neither matching usernames nor a course title creates an account or task association; native notification and offline-queue acceptance remain explicit future gates


### Requirement: Short and long planning progress
The system SHALL support an explicit short/long horizon independent of period and display actual minutes, distinct outcomes and target-count progress aggregated through all four hierarchy levels.

#### Scenario: Daily evidence rolls into broader goals
- **WHEN** a daily action records five minutes minimum, two minutes interrupted and twenty minutes completed
- **THEN** its containing week, month and year display twenty-seven actual minutes and one success; the course remains incomplete until explicitly marked learned

### Requirement: Private retrospectives and opt-in AI suggestions
The system SHALL save manual review history and account-scoped drafts for a user-selected plan subtree/date range. AI summaries SHALL require the user's own request-scoped provider configuration, an exact context preview and explicit consent. Study notes SHALL never enter these summaries. Optional execution notes and saved reviews require separate selections.

#### Scenario: Consent and context changes
- **WHEN** selected facts change after preview, configuration is missing, or consent is absent
- **THEN** generation is rejected without an external call and the user can refresh the preview or configure the provider

#### Scenario: Slow, failed or interrupted generation
- **WHEN** a generation runs slowly, fails, is retried with the same key, or the server restarts
- **THEN** the interface exposes generating/ready/failed status and saved history, repeated keys do not call the model again, credentials and raw provider errors are never stored, and only an explicit new attempt can regenerate

#### Scenario: Applying suggestions
- **WHEN** the user chooses to adjust a plan after reviewing AI advice
- **THEN** the existing editor opens and requires explicit saving; the model never alters the plan or marks a course completed
