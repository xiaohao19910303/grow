## Why

Grow's action plans are currently web-only. LightTick needs to display and mutate the same plans, reminders, execution facts and retrospectives without separate editable copies or accidental course completion.

## What Changes

- Add a Zook-owned action workspace API and durable PostgreSQL aggregate, preserving year/month/week/day, short/long classification, revisions, outcomes and private review history.
- Add registered-account one-time pairing tickets and an authenticated Grow bridge, with frozen-source import, exact receipts and recoverable single-writer cutover.
- Route connected Grow web requests to Zook; retain existing local plans until the user explicitly pairs and confirms import.
- Add native iOS/Android action workspaces, pending-request recovery, reminder scheduling, history and manual review editing using existing secure sessions.
- Verify isolated persistence, identity boundaries and matching web/client views; no automatic production migration or release.

## Capabilities

### New Capabilities
- `lighttick-grow-actions`: Shared action plans, verified linking and cross-platform execution/reviews.

### Modified Capabilities
None.

## Impact

Zook canonical LightTick OpenAPI, generated contracts, product services/repositories, additive migrations and API docs; Grow bridge and settings/navigation; isolated LightTick client worktrees and contract snapshots. Native primary workspaces and unrelated uncommitted edits are preserved.
