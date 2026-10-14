## ADDED Requirements

### Requirement: Traceable article discovery
The system SHALL discover Chinese and English articles from disclosed sources, distinguish recent and classic selections, deduplicate canonical URLs, and never claim unverified popularity or full-text access.

#### Scenario: Partial source failure
- **WHEN** one source fails and others return eligible articles
- **THEN** show successful candidates, failed sources and any shortfall without substituting unrelated articles

#### Scenario: Recent date is unknown
- **WHEN** an article has no reliable publication date
- **THEN** it is excluded from recent selections

### Requirement: Preview and durable local saving
The system SHALL preview manually collected candidates and save explicitly selected articles, readable source notes and indexes locally with stable IDs and recoverable writes.

#### Scenario: Save the same result twice
- **WHEN** the same confirmed collection is saved again
- **THEN** return the existing saved result without duplicate articles or index rows

#### Scenario: External edits
- **WHEN** a managed file changed outside the app
- **THEN** stop the conflicting write and preserve the external edit

### Requirement: Independent personal reading records
The system SHALL keep bookmark, read-later, user-confirmed read state and notes separate from generated material.

#### Scenario: Generate a guide
- **WHEN** a user explicitly requests an AI guide
- **THEN** disclose the article context sent, exclude personal notes, preserve previous material on failure, and do not mark the article read

### Requirement: Daily collection
The system SHALL run daily using saved Beijing-time preferences while the local service runs, with defaults of three mixed-language articles, and retain a durable per-date job.

#### Scenario: Restart after the scheduled time
- **WHEN** the service restarts after today's scheduled time and no daily job exists
- **THEN** collect for today once without backfilling prior dates

#### Scenario: Stop automatic collection
- **WHEN** the user disables the daily preference
- **THEN** do not start subsequent daily jobs and preserve existing articles

### Requirement: Safe bounded networking and compatibility
The system SHALL constrain fetching to configured public sources, reject unsafe XML and URLs, limit response sizes, include reading data in backups, and preserve legacy learning data.

#### Scenario: Unsafe returned link
- **WHEN** a feed contains a local-network or non-HTTPS link
- **THEN** exclude that entry without fetching it
