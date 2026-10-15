## ADDED Requirements

### Requirement: Unified reading views
The system SHALL provide original, bilingual, summary, English explanation and personal-note views for a saved article, retaining article identity, source version and reading position. Chinese articles SHALL default to the original view and unsupported English actions SHALL not initiate requests.

#### Scenario: Narrow screen bilingual reading
- **WHEN** an English article is opened on a 375px-wide screen
- **THEN** each source paragraph is followed by its translation without horizontal body overflow, and hiding translation changes display only

#### Scenario: Return to the library
- **WHEN** the reader returns from an article
- **THEN** the library filter and previous scroll position are restored

### Requirement: Validated generation context
The system SHALL create generation jobs only with validated article identity, source version and hash, selected block IDs, language, model configuration and request identity. Existing summary and English endpoints MUST follow the same validation and draft-adoption contract.

#### Scenario: Missing article body or model
- **WHEN** a user requests full-body generation without suitable source content or model configuration
- **THEN** reject before model invocation with an actionable explanation

#### Scenario: Old summary endpoint
- **WHEN** a compatible client invokes the existing summary endpoint
- **THEN** the job receives a valid context and produces a previewable draft instead of immediately overwriting adopted materials

### Requirement: Visible generation scope and cost
The system SHALL disclose selected article content, source version, block count, character count, model, sanitized service address and estimated request count before an explicit generation action. Personal notes and unrelated data MUST be excluded. Unknown prices or usage MUST be shown as unknown.

#### Scenario: Refresh after submitting
- **WHEN** the page refreshes, changes views or replays the same idempotent generation request
- **THEN** it reads the existing job without creating duplicate model calls

#### Scenario: Explicit retry
- **WHEN** the user retries failed blocks
- **THEN** show the selected remaining range and possible additional cost before creating a new attempt

### Requirement: Complete paragraph alignment
The system SHALL associate translations with immutable source block references and validate all requested block IDs. Complete translation MUST require 100 percent target coverage, with no missing, duplicate or unknown block IDs. Source completeness and generation coverage MUST remain separate claims.

#### Scenario: Missing translated paragraph
- **WHEN** model output omits one requested block
- **THEN** show partial completion and the missing block; any explicitly adopted partial translation remains visibly partial in the UI and local Markdown

#### Scenario: Complete translation of an excerpt
- **WHEN** every selected block of a partial source is translated
- **THEN** show complete coverage of the selection but continue labeling the source and result as an excerpt

### Requirement: Bounded long-article processing
The system SHALL chunk by paragraph, split oversized paragraphs by sentence with parent references, and preserve coverage across boundaries. Default source payload per request SHALL not exceed 6000 characters and MUST fit the configured model context. Each job SHALL default to at most 40 model requests and 900 seconds total, without automatic budget expansion.

#### Scenario: Long article summary
- **WHEN** an article longer than the former 15000-character capture limit is summarized
- **THEN** process the entire selected scope through cited intermediate results and a synthesis, and do not label it complete if a required chunk failed

#### Scenario: Request budget exceeded
- **WHEN** estimated calls exceed the budget or runtime reaches a budget limit
- **THEN** ask for a smaller scope before starting or stop the running job with preserved partial results and no automatic additional calls

### Requirement: Evidence-linked summaries and language explanations
The system SHALL attach valid source-version and paragraph references to summary claims, evidence and quoted language examples. It MUST distinguish author claims, source evidence and generated application suggestions, and MUST NOT invent original quotes or evidence. Vocabulary explanations SHALL prioritize contextual meaning.

#### Scenario: Sparse language material
- **WHEN** the source supports fewer vocabulary or grammar examples than the preferred maximum
- **THEN** return fewer examples instead of inventing sentences, and omit unverified pronunciation when no reliable basis is available

#### Scenario: Inspect an explanation
- **WHEN** the user opens a vocabulary item or complex-sentence explanation
- **THEN** show the original sentence, matching source reference, contextual meaning and relevant structure explanation

### Requirement: Draft editing and explicit adoption
The system SHALL persist generated materials as drafts before adoption, allow edits with structural validation, and preserve prior adopted versions. Independent successful artifact types MAY be adopted separately, but an unfinished whole-article summary MUST NOT be published as complete.

#### Scenario: Edit a translation draft
- **WHEN** the user removes a translated block during editing
- **THEN** coverage is recalculated and the result cannot be adopted as complete until missing targets are resolved

#### Scenario: Repeated adoption
- **WHEN** the same draft adoption request is repeated
- **THEN** return the existing adopted version without creating another version or index entry

#### Scenario: Source changed before adoption
- **WHEN** the draft source or target artifact version is no longer current
- **THEN** block adoption with a version conflict and preserve the draft and its historical source reference

### Requirement: Durable cancellation and partial recovery
The system SHALL persist per-chunk state, require complete end signals and validate output before marking chunks complete. Navigation MUST NOT restart work. Cancellation SHALL stop future local requests. Restarted running jobs SHALL become interrupted without automatic paid retries.

#### Scenario: Resume after failure
- **WHEN** the user explicitly retries an interrupted job with identical source hash, model, prompt version and parameters
- **THEN** reuse only fully validated completed chunks and retry the missing or failed chunks within the newly confirmed budget

#### Scenario: Provider already processing a cancelled call
- **WHEN** the user cancels during a provider request
- **THEN** stop the local connection and subsequent chunks while showing that already processed provider work may still be billed

### Requirement: Offline readability and visible provenance
The system SHALL make adopted original text, translations, summaries and explanations readable without internet when the local service runs, and as standalone local Markdown when it stops. Formal outputs MUST include source range, source version, generation provenance and missing-content notices.

#### Scenario: Read local files with no service
- **WHEN** the user opens an adopted Markdown file directly after stopping the service
- **THEN** its text and provenance remain readable and partial material cannot be mistaken for a complete article
