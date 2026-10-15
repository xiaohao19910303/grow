## ADDED Requirements

### Requirement: Independent reading and personal-note state
The system SHALL keep saved-to-library, bookmark, read-later, user-confirmed read state, generated material and personal notes separate. Only an explicit user operation SHALL mark or undo reading completion, recording the source version and time. Existing note paths and text MUST be preserved.

#### Scenario: Generate and scroll
- **WHEN** material is collected, generated, opened, scrolled to the end or displayed for a long time
- **THEN** it does not mark the article read, complete a course or infer mastery

#### Scenario: Updated source after reading
- **WHEN** the user read a prior version and later adopts a new source version
- **THEN** preserve the historical reading event and show that the read state belongs to the prior version

#### Scenario: Unsaved notes during navigation
- **WHEN** the user attempts to leave an article with unsaved notes
- **THEN** offer save or discard before navigation without silently losing the input

### Requirement: User-selected contextual vocabulary
The system SHALL add vocabulary only through a user action, preserve distinct contextual meanings and source references, and allow personal edits. Regeneration of article explanations MUST NOT overwrite saved personal vocabulary.

#### Scenario: Same word in another context
- **WHEN** the user adds a normalized word already in the vocabulary collection from another source
- **THEN** show the existing entry and preserve the additional context and source instead of silently replacing its meaning

#### Scenario: Return to old original sentence
- **WHEN** the article source has changed since a word was saved
- **THEN** its example can still open the referenced historical paragraph

### Requirement: Explainable local review schedule
The system SHALL provide in-platform due vocabulary reviews based on Beijing dates, with a default interval ladder of 1, 3, 7, 14 and 30 days. New entries SHALL be due the next day. Remembered feedback SHALL advance one step, uncertain feedback SHALL retain the step and schedule the next day, and forgotten feedback SHALL reset to the first step and schedule the next day. The maximum interval SHALL remain 30 days.

#### Scenario: Repeated feedback request
- **WHEN** the same review operation is submitted multiple times
- **THEN** create one review event and advance the schedule only once

#### Scenario: Overdue vocabulary
- **WHEN** a due date passes without user feedback
- **THEN** keep the item due without automatic completion or inferred mastery

#### Scenario: Pause a vocabulary entry
- **WHEN** the user pauses or archives a vocabulary entry
- **THEN** remove it from the active due list while retaining its content, references and review history

### Requirement: Stable references for future planning
The system SHALL expose stable article, source-version, paragraph and vocabulary IDs for later project or task associations. This release MUST NOT automatically create tasks, calendar entries, system notifications or external automations from notes or reviews.

#### Scenario: Write a proposed action in notes
- **WHEN** a user writes an application idea while reading
- **THEN** save it as personal note text without changing the existing Todo list, learning plan or schedule

### Requirement: Personal data persistence and export
The system SHALL save reading state events, vocabulary and review events independently with version checks and idempotency, and include readable vocabulary mirrors and structured personal records in full backup. Article generation MUST exclude personal notes and review feedback unless a separate future feature explicitly authorizes such scope.

#### Scenario: Restore learning records
- **WHEN** a complete backup is restored into an isolated workspace
- **THEN** reading timestamps, source-version references, vocabulary contexts and next review dates match the backup
