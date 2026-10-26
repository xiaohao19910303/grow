## ADDED Requirements

### Requirement: Explicit lesson count
The system SHALL support self-paced plans with an explicit lesson_count, default four for continuation and editable from two to twelve. Original weekly plans SHALL preserve their existing behavior. A continuation plan SHALL end with review.

#### Scenario: Four-lesson plan
- **WHEN** a learner adopts a default continuation plan
- **THEN** its curriculum has four lessons and no weekly learning requirement or automatic schedule

### Requirement: Honest weekly budget
The system SHALL exclude unallocated self-paced plans from weekly minute totals and indicate their unallocated workload explicitly.

#### Scenario: Budget with both modes
- **WHEN** weekly and self-paced plans coexist
- **THEN** weekly totals include only weekly allocations and the self-paced plan count is shown separately
