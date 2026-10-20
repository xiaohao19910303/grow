## Why

Users can read courses and keep notes, but today's checklist cannot express annual/monthly direction, weekly commitments, reminders or recoverable execution. A visible next action should help users return from distractions to reading without manufacturing course completions.

## What Changes

- Private year/month/week/day action plans with optional parent, dates, timezone, target minutes and study references.
- Short/long-term classification, visual progress, private saved retrospectives and user-confirmed AI summaries from an exact preview.
- A pending-action panel before the homepage learning list, a plan workspace and execution history.
- Explicit start, minimum start, finish, interruption, snooze, pause and archive operations with optimistic versions and idempotency.
- Due reminders in-page and optional browser notifications, plus calendar export for device reminders outside the webpage.
- LightTick integration design grounded in its existing Zook contracts, without creating another LightTick backend or claiming native delivery.

## Capabilities

### New Capabilities
- `action-plans`: Private planning, execution, reminders, study navigation and client integration boundaries.

### Modified Capabilities
None.

## Impact

Grow PostgreSQL tenant schemas, FastAPI private browser APIs, homepage/navigation, standalone JavaScript/CSS and tests. Personal plans and records never go into GitHub. Only the user-confirmed review snapshot is sent to their configured AI service; keys are request-scoped and never persisted in operation journals. LightTick design lives in plan/docs; its runtime and canonical contracts remain owned by Zook. Existing unrelated local fixes remain intact.
