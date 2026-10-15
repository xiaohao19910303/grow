## ADDED Requirements

### Requirement: Previewed article collection
The system SHALL support public HTTPS URL collection and pasted text or Markdown imports with a durable preview before explicit adoption. Missing metadata MUST remain unknown. Preview and adoption MUST NOT invoke a language model.

#### Scenario: Import pasted content
- **WHEN** a user provides a title and multi-paragraph text without author or publication date
- **THEN** the preview retains paragraph boundaries and shows unknown metadata, and explicit adoption saves a locally readable article

#### Scenario: URL extraction fails
- **WHEN** the URL cannot yield supported readable content
- **THEN** offer retry, paste import or metadata-only saving, without creating a source document from an error message

### Requirement: Stable identity and explicit source updates
The system SHALL preserve existing article IDs and deduplicate verified canonical URLs and aliases. Source refreshes MUST create a preview for the existing article. Pasted imports without URLs MUST use stable per-operation identities and MUST NOT be silently merged by content similarity.

#### Scenario: Repeated collection
- **WHEN** equivalent verified URLs or the same adoption request are submitted repeatedly
- **THEN** the existing article is returned without duplicate directories, index entries or versions

#### Scenario: Similar independent pasted imports
- **WHEN** two distinct import operations contain identical text without a URL
- **THEN** a possible duplicate is shown but their records are not merged without a user decision

#### Scenario: Backfill an old article
- **WHEN** the user adopts a source preview for an existing summary-only article
- **THEN** preserve its ID, notes and personal states while adding a source version

### Requirement: Honest content scope
The system SHALL store extraction status separately from source scope. Source scope MUST distinguish summary-only, partial, unverified body and verified-complete body, including the completeness evidence. Network success alone MUST NOT establish completeness.

#### Scenario: Uncertain extraction
- **WHEN** readable text is extracted without reliable completeness evidence
- **THEN** show unverified body, and generated materials cannot claim to summarize the complete original article

#### Scenario: Failed refresh with an existing source
- **WHEN** extraction fails after a valid source was previously adopted
- **THEN** keep the adopted source and record the refresh error separately

### Requirement: Bounded structured extraction
The system SHALL preserve article structure and exclude navigation, recommendation blocks, scripts and styles where extraction succeeds. Unsupported content or uncertain extraction MUST have an explicit fallback. Default limits SHALL be a 10-second connection timeout, 30-second total fetch timeout, 2 MiB decompressed response and 200000-character source, without silent truncation.

#### Scenario: Oversized response
- **WHEN** streamed response data or imported text exceeds its limit
- **THEN** stop with a visible limit error and do not save a truncated source as successful content

#### Scenario: Unsupported PDF or inaccessible page
- **WHEN** a target is PDF, login-gated, paywalled or requires script execution
- **THEN** preserve a safe source reference and offer pasted import instead of claiming full extraction

### Requirement: Safe URL fetching and rendering
The system MUST reject credential-bearing or non-HTTPS fetch URLs and local, private, link-local or metadata targets, including DNS resolution and each redirect. The actual connection destination MUST remain validated. Redirects SHALL be limited to three. Source and generated text MUST NOT execute scripts or instructions.

#### Scenario: Redirect to private address
- **WHEN** an initially public URL redirects to a private address or its effective connection target resolves to a forbidden address
- **THEN** refuse that connection before fetching the forbidden target and preserve existing data

#### Scenario: Embedded instructions and markup
- **WHEN** a source contains executable markup or instructions to read other files
- **THEN** render it safely as source data without executing scripts, reading files or following those instructions

### Requirement: Versioned local persistence
The system SHALL keep immutable adopted source versions and adopted artifact versions, a current readable Markdown mirror, stable paragraph references and independent personal notes. SQLite SHALL maintain authoritative lifecycle state, paths, hashes, drafts and operation journals. Formal source bodies MUST NOT be repeatedly duplicated in article metadata.

#### Scenario: Adopt revised source
- **WHEN** a user confirms an edited source preview
- **THEN** create a new immutable source version, retain old referenced versions and mark prior artifacts as based on an older source

#### Scenario: External edits
- **WHEN** a managed source, artifact or note has an unexpected file hash
- **THEN** block the conflicting write and offer explicit comparison/import without overwriting the external content

### Requirement: Recoverable publication and independent updates
The system SHALL use request idempotency, record versions, expected file hashes, short writer locks and durable publication journals across database and file writes. A background operation MUST NOT overwrite newer personal fields with an old article snapshot.

#### Scenario: Interrupted publication
- **WHEN** a process stops between file replacement and database finalization
- **THEN** restart resumes only known before/after hashes to one consistent result, while unknown hashes block recovery

#### Scenario: Personal edit during generation
- **WHEN** a user saves a note or changes a bookmark during background generation
- **THEN** later artifact adoption preserves that personal edit or reports a specific conflict

### Requirement: Compatibility and complete backup
The system SHALL migrate old reading records without automatic fetching, model calls or learning-state changes, preserve existing paths, and include all adopted versions and personal reading data in complete backup and restore. Reading records MUST remain outside legacy whole-state overwrite tables.

#### Scenario: Old placeholder content
- **WHEN** migration encounters an error-placeholder full_content value
- **THEN** preserve migration evidence but do not adopt the placeholder as article text

#### Scenario: Restore in isolation
- **WHEN** a complete reading-inclusive backup is restored with all writers stopped
- **THEN** source and artifact hashes, active versions, notes, vocabulary and review events match the backup, with no API secrets included

### Requirement: Daily collection remains explicit in scope
The system SHALL preserve existing source discovery and daily collection preferences, while daily collection saves metadata and summary materials only. Full-source acquisition and model generation in this release MUST be explicitly initiated per article by the user.

#### Scenario: Scheduled collection
- **WHEN** the daily collection executes
- **THEN** it does not fetch article full text, translate articles or invoke a paid model, and it preserves existing deduplication and same-day scheduling rules

### Requirement: Archival without broken references
The system SHALL support archive and restore without deleting source versions, artifacts or referenced personal records. Permanent deletion SHALL be outside this release.

#### Scenario: Refer to an archived article
- **WHEN** a vocabulary entry or note refers to an archived article
- **THEN** its historical source can still be read and restoring the article makes it available in ordinary lists again
