## ADDED Requirements

### Requirement: Unified next step
The system SHALL expose the same continuation panel in course details and after explicit completion, covering cognitive, English, expression and formal plans. Existing unread lessons SHALL take precedence over generation.

#### Scenario: Continue on the same day
- **WHEN** the learner completes currently published lessons
- **THEN** cloud generation can prepare the next lesson on the same day without changing completion facts

### Requirement: Advice and manual direction
The system SHALL offer three editable suggestions or allow manual direction without compulsory questions. Private notes SHALL be excluded unless selected for this request, and SHALL NOT enter formal plan or course prompts.

#### Scenario: Explicit private selection
- **WHEN** notes are selected for advice
- **THEN** only those notes are used for private advice and neither formal prompts nor publication files contain their raw content

### Requirement: Linked adoption and recovery
The system SHALL create a linked new course from an adopted next-stage plan and preserve the source course. Generation, adoption and publishing SHALL be recoverable and idempotent; restart SHALL NOT silently repeat model calls.

#### Scenario: First lesson fails
- **WHEN** adoption succeeds and first-lesson generation fails
- **THEN** retry reuses the new course identifier without creating another course

### Requirement: Safe single-lesson extension
The system SHALL allow a completed formal course to prepare one extra lesson without changing its formal curriculum before preview approval.

#### Scenario: Publish extension
- **WHEN** the learner approves the extra lesson draft
- **THEN** the formal curriculum extension and lesson publish together and prior completion records remain unchanged
