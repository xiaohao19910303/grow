## ADDED Requirements

### Requirement: Unambiguous instrument and effective rules
The system SHALL identify each instrument by market, code and type and apply rules with effective dates and actual implementation status. It MUST NOT assume all ETFs share the same intraday selling mechanism.

#### Scenario: Unknown ETF trading mechanism
- **WHEN** a proposed same-day exit relies on an unverified ETF classification
- **THEN** the system marks executability unverified and does not claim the exit is available

#### Scenario: Historical rule change
- **WHEN** reviewing a trade before a rule changed
- **THEN** the review uses the rule effective and implemented at the historical decision time, or reports that the historical rule is unavailable

### Requirement: Point-in-time evidence
The system MUST preserve evidence identity, URL or private source, locator, data period, effective time, availability time, retrieval time and hash. Facts and later restatements SHALL remain distinguishable.

#### Scenario: Financial report published after trade
- **WHEN** a report period predates a trade but its publication follows the decision
- **THEN** the report is excluded from the information presented as knowable at that decision time

### Requirement: Explicit data freshness and capabilities
The system SHALL disclose source coverage, market timestamp and limitations. Daily, delayed, realtime, missing and stale data MUST NOT be conflated. Provider access and distribution permission MUST be checked before enabling a data-backed capability.

#### Scenario: Daily data used during the session
- **WHEN** a report uses the previous close during an open session
- **THEN** it may support historical or conditional research but cannot assert a current intraday breakout or immediately sellable quantity

#### Scenario: No record returned
- **WHEN** an expected daily record is absent
- **THEN** the system distinguishes pending ingestion, unknown coverage and verified suspension rather than setting price or volume to zero

#### Scenario: Realtime entitlement is absent
- **WHEN** the account has daily or historical data access but no verified realtime-minute entitlement
- **THEN** realtime features remain disabled, and repeated polling of the historical daily endpoint cannot be represented as a realtime feed

### Requirement: Source unit normalization
The system MUST preserve source units and normalize volume and turnover before combining endpoints. Instrument precision and adjusted/unadjusted price bases MUST remain explicit.

#### Scenario: Daily and minute units differ
- **WHEN** the daily provider describes volume in lots of 100 shares and turnover in thousands of currency units while minute data uses shares and currency units
- **THEN** the adapter converts daily units by the documented factors before comparison and retains the original values and unit metadata

### Requirement: Structured stock and ETF research
The system SHALL separate market context, price/volume, liquidity, events, company risks, valuation assumptions, instrument constraints and portfolio effects, with supporting and contrary evidence.

#### Scenario: ETF valuation timestamps differ
- **WHEN** market price and NAV/iNAV are from different relevant times
- **THEN** the system displays the mismatch and does not present the difference as a verified tradable arbitrage opportunity

#### Scenario: Unsupported company ratio
- **WHEN** a valuation ratio is undefined or inappropriate for the instrument
- **THEN** the report marks that ratio unavailable and explains the missing assumption instead of generating a precise substitute

### Requirement: Bounded secure source ingestion
The system MUST validate provider outputs and source fetches, enforce permitted targets and size limits, and treat retrieved text as untrusted evidence rather than instructions.

#### Scenario: Source contains trading commands or private-network URL
- **WHEN** ingested content attempts to instruct tools or redirects to a disallowed target
- **THEN** it cannot execute a trade, reveal credentials or access the target, and its ingestion failure is visible

### Requirement: Realistic historical testing gate
P2 backtesting and replay MUST use point-in-time inputs, historical instrument coverage, explicit fill rules and trading constraints, fees and slippage. Missing path order or fill evidence MUST be treated conservatively or left unresolved.

#### Scenario: Both target and stop touched within one bar
- **WHEN** the price path order inside a bar is unknown
- **THEN** the evaluator uses its disclosed conservative rule or marks the trade unresolved and never silently selects the profitable sequence

#### Scenario: Limit-locked or unavailable sell quantity
- **WHEN** a simulated exit cannot meet instrument selling rules or verifiable execution constraints
- **THEN** the evaluator does not invent an executable exit at the requested price

#### Scenario: Public reference expires or conflicts with a manual check
- **WHEN** a plan check opts into the bundled public reference but its version or maintenance window is no longer valid, or recorded fields contradict covered rules or holiday dates
- **THEN** confirmation is refused, the reference status and unknown fields remain explicit, and actual fills can still be recorded truthfully

#### Scenario: Public calendar avoids an unnecessary supplier entitlement
- **WHEN** the user explicitly selects the covered public calendar for daily data
- **THEN** only the selected daily endpoint is requested, supplier calendar access is not claimed as tested, and missing coverage stops without silently switching providers or endpoints

#### Scenario: Offline path is imported after the historical trade
- **WHEN** user-declared minute data is imported for retrospective review
- **THEN** the original text, units, import time and hash remain available, the result is labeled retrospective current-ledger review, and it does not claim those inputs were knowable for historical backtesting

### Requirement: Offline condition drills remain separate from live monitoring
The system SHALL permit explicitly declared offline price-threshold drills using completed minute closes and simulated arrival clocks. It MUST freeze the rule, data/check references and result, and MUST NOT interpret these drills as current tradability, historical point-in-time strategy backtests or delivered notifications.

#### Scenario: Delayed observations, session breaks and repeated threshold matches
- **WHEN** a completed minute arrives after its selected age limit, a check occurs outside a covered open session, or the same daily condition has already matched in the drill
- **THEN** the drill records stale, unavailable or suppressed status without generating another simulated page candidate, and explicit expiry remains visible

#### Scenario: Offline exit condition relies on a hypothetical position
- **WHEN** a drill selects exit intent and a declared purchase date
- **THEN** it counts covered trading sessions against the declared selling delay, treats unknown rules as unresolved, never assumes ETF T+0, and does not assert actual sellable quantity
