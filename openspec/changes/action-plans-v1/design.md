## Context

Grow already has tenant-scoped PostgreSQL, cookie authentication, course readers, independent study drafts and daily checklists. LightTick already has goals/plans/tasks/start/complete/defer/execution-facts in Zook; its identity is not currently bound to Grow. Other repositories contain unrelated active work and will not be modified.

## Goals / Non-Goals

**Goals:** A working browser action loop, hierarchical year/month/week/day plans, explicit execution, foreground reminders, calendar alarms and concrete LightTick handoff design.

**Non-Goals:** Native client implementation/release, automatic account binding, a second LightTick backend, automatic video tracking/blocking, automatic AI plan changes and unsupervised course completion. Closed-page mobile notifications use an exported calendar reminder in this slice; native notification delivery remains a separately verified LightTick integration.

## Decisions

- Add private `/api/action-plans` browser routes, tenant tables and lazy additive initialization. The transitional Grow domain is the only writer of these new web records. Zook LightTick remains the only owner of its existing tasks; no mirrored editable copies or new LightTick public contract here.
- Plans have immutable period, optional containing parent, business dates, IANA timezone, daily start time/reminder, target minutes/count, study reference, active/paused/completed/archived state and revision. Repeat creation is a bounded explicit batch of daily actions in a selected week. No automatic debt rolls forward.
- A transaction-level tenant advisory lock protects mutation, operation journal and one running execution. Client request keys survive retries. Finishing records user-confirmed minutes and completed/minimum/interrupted outcomes; opening content, timers and note saves never complete a course.
- Homepage shows active sessions first, due/upcoming daily actions and week progress before courses. The full workspace supports period/horizon/status filters, children, edit, pause/archive and execution history.
- Foreground reminders appear in a persistent accessible banner. Desktop notifications are opt-in, per-device claimed, suppressed in quiet hours and updated after snooze. Calendar ICS uses UTC event times derived from the plan timezone, with VALARM; the UI clearly distinguishes webpage-open reminders from calendar/native reminders.
- A stable typed study reference dispatches to existing readers, with explicit failure and a way back to plans. No external URL or untrusted HTML is executed.
- LightTick design maps these facts to existing Zook goal/plan/task/execution semantics, preserves original IDs and requires verified identity binding plus a one-writer cutover before native writes. No account is linked merely by username.

- Short/long classification is explicit (year defaults long, other periods short) and independent of hierarchy. Month ranges stay within one calendar month; child periods stay contained and can skip intermediate levels.
- Plan cards show confirmed execution minutes, success count and capped goal percentage. Home also recognizes completed daily actions. Manual reviews are append-only snapshots of the selected plan subtree and business-date range; drafts remain account-scoped.
- AI requires the user's configured HTTPS provider and explicit consent after preview. Scope changes clear consent; a content hash rejects changed facts after preview. Optional execution notes and up to five saved reviews must be separately selected. Aggregates cover all matching facts; the prompt contains at most thirty recent facts and visibly truncated notes/review excerpts, never study notes.
- AI generation journals only non-secret request metadata and a private context snapshot, runs outside the database transaction with a 90-second timeout and no automatic retry, persists ready/failed results, and recovers interrupted attempts after a server restart (single worker). Suggestions open the normal edit form and require user confirmation.

## Risks / Trade-offs

- Browser notifications do not imply background delivery → explicit capability text, foreground banner and calendar export.
- Long periods and incomplete days can create pressure → homepage prioritizes today and running work; past unfinished actions require deliberate rescheduling.
- Mutations may succeed with lost responses → durable idempotency keys and a refreshable active execution.
- Existing user data → additive tables only, no changes to old todos, completions or notes; isolated browser fixture for test writes.
- Client scope → native integration is delivered as a detailed design, not represented as an implemented or published App feature.

## Migration Plan

Install tables on first use for existing accounts. Keep prior data in place. Rollback removes UI registration while retaining private records. Later Zook takeover requires source-account mapping, idempotent import, a final-write barrier and read/write routing switch for the same object range.
