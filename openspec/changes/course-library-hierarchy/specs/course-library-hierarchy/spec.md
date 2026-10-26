## ADDED Requirements

### Requirement: Course-first library
The system SHALL default to 学习中 and offer 待学习 and 已学完 filters. Outer cards SHALL omit lesson lists, showing course identity, goal, progress and a primary action instead.

#### Scenario: Browse courses
- **WHEN** the learner opens 我的课程
- **THEN** only cards for the selected state appear and individual lessons appear only after opening a course

### Requirement: Evidence-based course status
The system SHALL count only explicitly completed published lessons in the formal curriculum. Unpublished planned lessons SHALL remain in the denominator. Continuous modules SHALL use 已学至最新 rather than whole-course completion. Paused and archived plans SHALL remain accessible separately.

#### Scenario: Unpublished remainder
- **WHEN** one published lesson is complete in a two-lesson plan
- **THEN** progress is 1/2 and the course is not in 已学完

#### Scenario: Continuous course caught up
- **WHEN** all currently published lessons in a continuous module are completed
- **THEN** it remains in 学习中 with 已学至最新

### Requirement: Course detail and navigation
The system SHALL provide a course detail with goals, stage directory, lesson states and course tools. Only the current stage SHALL open by default. Existing reader, notes, actions and completion behavior SHALL remain available. Course routes SHALL support reload and browser back navigation.

#### Scenario: Return from reading
- **WHEN** the learner reads a lesson from a course detail and returns
- **THEN** the same course detail is restored with refreshed progress

### Requirement: Private persistent resume activity
The system SHALL persist successful course opens in the current account's private database, preserving the first start time and latest lesson. Opening SHALL NOT mark lessons completed. Writes SHALL require same-origin authorization. Failures SHALL show a retryable warning without blocking reading.

#### Scenario: Resume unfinished lesson
- **WHEN** a learner successfully opens lesson 3 and reloads without completing it
- **THEN** the course is 学习中 and 继续学习 opens lesson 3

#### Scenario: Tenant isolation
- **WHEN** another account reads course activity
- **THEN** it cannot see the first account's activity

#### Scenario: Failed reader
- **WHEN** a lesson fails to load
- **THEN** no successful-open activity is recorded

### Requirement: Responsive accessible states
The system SHALL provide keyboard-operable filters and navigation, labeled progress, explicit empty/loading/error states and layouts without horizontal overflow at 320, 768, 1024 and 1440 pixels.

#### Scenario: Mobile course detail
- **WHEN** a learner opens a course with a long title at 320 pixels
- **THEN** title and actions wrap and the page does not overflow horizontally
