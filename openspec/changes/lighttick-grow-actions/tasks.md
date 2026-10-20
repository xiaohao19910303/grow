## 1. Contract and authority
- [x] 1.1 Implement additive Zook action persistence, validations, revisions, execution, progress and scoped review facts; verify isolated PostgreSQL transactions and ownership.
- [x] 1.2 Add canonical API contracts, generated outputs, fixtures and docs for plans, records, reviews and linking.
- [x] 1.3 Implement pairing tickets, trusted bridge, frozen-source import/receipts and failure recovery.

## 2. Web handoff
- [x] 2.1 Add pairing preview/confirmation/retry UI and private backup/write barrier.
- [x] 2.2 Forward connected requests to Zook and preserve unconnected behavior, calendars, study navigation and AI history.
- [x] 2.3 Test lost responses, account isolation, conflicts and backup/cutover recovery.

## 3. Native clients
- [x] 3.1 Implement iOS action UI, authenticated transport, account-scoped cache/drafts/pending requests and reminders.
- [x] 3.2 Implement Android action UI, authenticated transport, account-scoped cache/drafts/pending requests and reminders.
- [x] 3.3 Synchronize contract snapshots, build both clients and run relevant client tests.

## 4. Integration verification
- [x] 4.1 Run an isolated real PostgreSQL and authenticated Zook/Grow fixture with synthetic accounts, no real migration/model calls.
- [ ] 4.2 Verify web/native changes in both directions, execution recovery, reminders and reviews; save evidence and resolve defects.
- [x] 4.3 Review and commit tested increments, update integration docs and report exact verified/unverified platform limits.

## Acceptance evidence / remaining checks

2026-10-20: real PostgreSQL + signed HTTP adapter checked 5 plans / 3 records / 27 minutes / 1 completed / 1 minimum / 1 interrupted. iOS and web UI verified pairing, execution in both directions, completion and manual reviews. Web screenshot in `.gstack/lighttick-actions-2026-10-20/`. Mac locked during remaining UI work: Android full UI, OS notification delivery/tap and kill/relaunch recovery remain open; see `知行成长/docs/lighttick-actions-integration.md`. No real account migrated.

Android follow-up: API 36 UI sign-in, action entry and ticket generation passed; web confirmed 4-plan handoff and HTTP snapshots match. Fixed keyboard-obscured login and verified IME Next/Done login. Android 104 unit tests and Debug build pass. Mac locked again before native refresh/execution/review and OS notification/recovery checks; 4.2 remains open. Current Android fixture has 4 plans and 0 records, separate from the previous iOS scenario.
