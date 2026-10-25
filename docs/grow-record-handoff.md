# Grow records handoff

2026-10-25. Records have their own explicit consent, separate from action-plan linking.

Configure server-only `LIGHTTICK_BRIDGE_URL`, `GROW_RECORDS_SOURCE_ID`, `GROW_RECORDS_BRIDGE_SECRET`; Zook uses the same source ID and secret and enables `LIGHTTICK_RECORD_HANDOFF_ENABLED=1`. Secrets never enter the browser or native app. The only canonical protocol is Zook `api-contracts/openapi/lighttick/api.yaml`.

The native registered account issues a five-minute records connection code. Grow's settings panel previews the target, record/version counts and source history gaps. Confirm rechecks the ticket and exact source snapshot before persisting a writer barrier. It claims and stages the complete private package, stores a signed frozen receipt, then activates it transactionally in Zook. The source identity always comes from the authenticated Grow tenancy context.

The source retains its exact immutable package and legacy tables. Response loss keeps it frozen. Retry uses the same operation, hash and receipt. An unactivated handoff may be cancelled only after the target confirms cancellation; a new confirmed operation can then claim a fresh code. Once active, web records read and write only through Zook. Network failure never falls back to a second local writer. AI history remains readable; new generation is outside this handoff release.

Old archive/restore/adopt operations did not persist every version. Missing versions are declared. Some old stored versions have adopted summaries without their basis. These bases are never inferred from a later summary. Canonical history may omit the unknown-basis summary, while the original summary and complete source versions remain in owner-only `source_history.private_history`, with `normalization.summary_basis_missing_versions` documenting the projection gaps.

After activation, recovery requires setting the target read-only and exporting its latest complete state. The old source stays frozen. Restoring its pre-handoff snapshot directly would lose newer native/web edits and is deliberately unsupported. Deleting LightTick data removes target records, histories, packages, tickets and bindings; retained Grow source backups remain subject to Grow account ownership and deletion.

Native apps now open a device workspace before login: records, manual goals/actions and factual reviews work locally. Session recovery runs in the background; an anonymous online trial starts only after a user request. Records transfer to a registered account only after preview and confirmation. Local manual goals/actions remain in the device workspace and can be exported; they are not implicitly uploaded by this records handoff.

Validation uses only synthetic identities and isolated localhost PostgreSQL. `test_record_handoff.py` covers real HTTP activation, source write barriers, response loss, newer target edits, cancellation/reclaim, cross-account isolation and multiple AI adoptions. No personal historical data was read or moved, and this candidate has not been deployed.
