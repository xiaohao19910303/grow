## 1. Contract and authority
- [ ] 1.1 Implement additive Zook action persistence, validations, revisions, execution, progress and scoped review facts; verify isolated PostgreSQL transactions and ownership.
- [ ] 1.2 Add canonical API contracts, generated outputs, fixtures and docs for plans, records, reviews and linking.
- [ ] 1.3 Implement pairing tickets, trusted bridge, frozen-source import/receipts and failure recovery.

## 2. Web handoff
- [ ] 2.1 Add pairing preview/confirmation/retry UI and private backup/write barrier.
- [ ] 2.2 Forward connected requests to Zook and preserve unconnected behavior, calendars, study navigation and AI history.
- [ ] 2.3 Test lost responses, account isolation, conflicts and backup/cutover recovery.

## 3. Native clients
- [ ] 3.1 Implement iOS action UI, authenticated transport, account-scoped cache/drafts/pending requests and reminders.
- [ ] 3.2 Implement Android action UI, authenticated transport, account-scoped cache/drafts/pending requests and reminders.
- [ ] 3.3 Synchronize contract snapshots, build both clients and run relevant client tests.

## 4. Integration verification
- [ ] 4.1 Run an isolated real PostgreSQL and authenticated Zook/Grow fixture with synthetic accounts, no real migration/model calls.
- [ ] 4.2 Verify web/native changes in both directions, execution recovery, reminders and reviews; save evidence and resolve defects.
- [ ] 4.3 Review and commit tested increments, update integration docs and report exact verified/unverified platform limits.
