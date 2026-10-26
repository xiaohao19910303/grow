## ADDED Requirements

### Requirement: Scoped personal AI requests
The system SHALL show the model destination and exact selected input scope before a personal analysis call, support withholding absolute amounts and keep AI credentials out of persisted requests, reports and logs.

#### Scenario: Amounts withheld
- **WHEN** the user sends only percentages and omits absolute capital
- **THEN** the model may compare proportional scenarios but no exact tradable quantity is presented as computed from unavailable capital

### Requirement: Verifiable analysis and counterevidence
The system MUST bind each report to evidence, deterministic calculation outputs, market/data cutoff, input versions, model and prompt versions. It SHALL label facts, assumptions and inferences and explicitly evaluate contrary evidence.

#### Scenario: Model invents an unsupported figure
- **WHEN** a generated factual figure has no matching evidence or calculation
- **THEN** it fails factual output validation and cannot appear as a verified recommendation input

#### Scenario: Same model reviews its analysis
- **WHEN** a second pass uses the same model for counterarguments
- **THEN** the UI identifies that process without representing it as independent expert agreement or a calibrated success probability

### Requirement: Conditional user-controlled recommendations
Recommendations SHALL include purpose, applicable constraints, rationale, evidence, contrary case, trigger, invalidation, expiry and missing inputs. Adoption or modification MUST be explicit and versioned; reports MUST NOT directly change plans, fills or funds.

#### Scenario: Missing current data
- **WHEN** a requested immediate-entry recommendation lacks sufficiently fresh quotes or instrument rules
- **THEN** the system limits its output to research or a future conditional draft and identifies the data needed before execution assessment

#### Scenario: User adopts a report
- **WHEN** the user chooses to adopt an eligible suggestion
- **THEN** the system creates an editable linked plan draft, and separately requires the plan confirmation action

### Requirement: Durable idempotent cancellable analysis
The system SHALL persist private task states and completed outputs, deduplicate identical request IDs and inputs, permit cancellation and mark interrupted work after restart. It MUST NOT automatically repeat paid generation.

#### Scenario: Refresh or duplicate submission
- **WHEN** the user refreshes or repeats the same active request
- **THEN** the system restores the existing task rather than issuing a second model call

#### Scenario: Server restarts during analysis
- **WHEN** a worker is interrupted by restart
- **THEN** saved progress is retained, state becomes interrupted and resubmission needs an explicit new attempt

#### Scenario: Browser-only credentials unavailable
- **WHEN** an unattended schedule has no authorized server-held AI credential
- **THEN** it cannot execute a model call or silently persist/retrieve the user's browser credential

### Requirement: Comprehensive recommendation evaluation
The system SHALL retain adopted, modified, rejected, expired and untriggered suggestions and separately evaluate prediction quality, plan quality, actual execution and net outcomes. It MUST distinguish shadow simulations from actual trading.

#### Scenario: Suggestion was not executed
- **WHEN** a recommendation was rejected or could not fill
- **THEN** any follow-up hypothetical result stays labeled simulated and is excluded from actual P&L and realized win rates

#### Scenario: Unresolved prediction
- **WHEN** a recommendation's event or deadline cannot be evaluated from available evidence
- **THEN** it remains unknown or unresolved rather than being scored as a failure

### Requirement: Preserved decision authority
The system MUST keep investment tools limited to research, calculations, records and editable drafts. It SHALL not promise returns, auto-increase risk after losses or expose order-placement and money-transfer tools to the model.

#### Scenario: External prompt requests automatic purchase
- **WHEN** model output or retrieved text asks the system to buy a security or transfer funds
- **THEN** no such transaction is executed and any proposed action remains a user-visible draft within the authorized capability set
