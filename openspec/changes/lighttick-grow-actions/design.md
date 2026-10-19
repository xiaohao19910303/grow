## Context

Grow's private action domain already works. LightTick and Grow use independent identities. Zook is the only LightTick backend and contract owner. Native primary workspaces are dirty; implementation uses clean worktrees from the G0-verified candidates, while Zook starts from freshly fetched origin/main.

## Goals / Non-Goals

Goals: one authoritative plan/execution/review state after explicit pairing; native reminders and recoverable mutations; web/native consistency evidence.
Non-Goals: automatic linking by username, copying passwords, migration of courses/learning notes, deployment or native store release.

## Decisions

- Add the action workspace as a Zook product aggregate, separate from AI-generated legacy planning cycles while preserving their existing behavior. A per-owner transaction serializes commands, receipts and one running execution. Bounded workspace data and explicit capacity errors avoid silent truncation.
- Canonical `/api/v1/lighttick/action-plans` APIs retain the existing Grow action field semantics so connected web adapters and native models share revision/outcome calculations. Grow private APIs become authenticated forwarding adapters after cutover.
- An authenticated registered client creates a short-lived random pairing code. The already-authenticated Grow user pastes it, reviews the target identity/counts, and explicitly confirms. Signed server-to-server bridge requests attest the Grow identity; no common bearer tokens are exported to the web.
- Freeze Grow writes under its existing action advisory lock, retain an immutable private backup, import idempotently with original IDs and an exact hash/count receipt, then activate forwarding. Failed/uncertain imports stay frozen with an explicit retry; no automatic return to dual writes. No real account is migrated by tests.
- Native clients use their existing secure session authorizers, account-scoped cached snapshots/drafts/pending keys and explicit conflict recovery. System reminders are scheduled from verified pending daily actions and canceled on account/schedule/state changes. Timer completion never invents course completion.
- Review history and facts remain private. Existing AI results must remain readable; connected generation stays user initiated with exact-preview consent and no credentials in receipts, logs or persistent queues.

## Risks / Trade-offs

- Existing native candidate branches differ from primary directories → retain dirty work, record exact sources and build tested worktrees.
- Network loss around cutover → persist source freeze and snapshot before dispatch; same-key retry and receipt reconciliation.
- Stale notification snapshots → refresh in foreground and on notification entry, include account/id/revision in payload, avoid completion notification actions.
- Native OS delivery restrictions → document device permission/background acceptance separately from scheduler tests; do not claim exact alarms.
- Local aggregate capacity → explicit limits and paginated records; no deletion or partial migration when exceeded.

## Migration Plan

Default bridge feature is off without a configured trusted endpoint/secret. Only isolated localhost accounts are paired during acceptance. Existing Grow users continue local ownership until their explicit pairing confirmation. Production takeover needs configured trusted services, backup/recovery and the documented acceptance checks; rollback retains ownership instead of re-enabling the old writer.
