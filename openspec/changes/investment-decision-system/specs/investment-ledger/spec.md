## ADDED Requirements

### Requirement: Exact private transaction facts
The system SHALL store account-scoped fills, fees, taxes, cash events and timestamps using exact decimal quantities and amounts. Orders, signals, simulated transactions and actual fills MUST remain distinct.

#### Scenario: Partial fill and cancellation
- **WHEN** an order partially fills and its remainder is cancelled
- **THEN** only confirmed executed quantities affect positions and cash, with the cancelled portion preserved as an order event if supplied

#### Scenario: Fractional fund units
- **WHEN** a confirmed fund transaction contains decimal units
- **THEN** the system retains the exact supplied precision rather than coercing the units to an integer

#### Scenario: ETF sub-cent prices
- **WHEN** 10000 units are acquired at 1.231 and sold at 1.234
- **THEN** the price-difference result before fees is exactly 30 currency units and the prices are not rounded to the same two-decimal value

#### Scenario: Unknown fees
- **WHEN** a confirmed fill has no verified fee amount
- **THEN** fee completeness remains unknown rather than defaulting to zero, and affected results cannot be presented as verified net P&L

### Requirement: Single active campaign boundary in the initial release
The initial release SHALL allow at most one active campaign per investment account and instrument, with multiple entry and exit fills within that campaign. Parallel strategy-specific cost accounting MUST require a separately defined allocation and reconciliation contract before being enabled.

#### Scenario: Second active campaign requested
- **WHEN** the user attempts to open another campaign for an instrument already active in the same account
- **THEN** the system explains the boundary and offers linking to the existing campaign or retaining a research draft without duplicating the position or discarding actual fills

### Requirement: Account reconciliation and campaign allocation
The system SHALL reconcile account positions and cash separately from strategy campaign allocation. Long-only economic P&L SHALL use moving weighted-average cost, including buy fees in acquisition cost and subtracting sell fees from sale proceeds, without claiming tax-reporting equivalence. Derived cash events MUST reference their originating fill to prevent double counting, and facts, balances and audit changes MUST commit transactionally. Unsupported corporate actions SHALL be flagged for reconciliation rather than silently retaining obsolete quantities.

#### Scenario: Partial sale
- **WHEN** part of a reconciled position is sold
- **THEN** realized P&L uses the applicable historical allocated cost and known costs, while the unsold balance retains its remaining cost basis

#### Scenario: Campaign allocation exceeds position
- **WHEN** a campaign allocation would exceed the actual available account quantity
- **THEN** the system rejects that allocation with a recoverable conflict without deleting the underlying imported fill

#### Scenario: Reconciled partial-sale example
- **WHEN** opening cash is 10000, two buys are 100 units at 10 and 12 with fees of 1 each, and 50 units are sold at 13 with a fee of 1
- **THEN** remaining cash is 8447, remaining quantity is 150 with cost 1651.50, and realized net P&L is 98.50; at a mark of 12, unrealized P&L is 148.50 and total equity is 10247

### Requirement: Provenance-aware opening balances
The system SHALL support verified opening cash and positions at a specified reconciliation date without fabricating earlier fills or performance.

#### Scenario: Incomplete historical brokerage data
- **WHEN** a user starts with an opening position and known cost but no earlier transactions
- **THEN** position accounting starts at that baseline and historical return periods before it are marked unavailable

### Requirement: Previewed idempotent imports and corrections
The system MUST preview imports, report invalid or duplicate rows and preserve source identifiers. Repeated imports SHALL not duplicate accepted facts. Corrections MUST preserve an audit trail and recompute affected balances.

#### Scenario: Same file imported twice
- **WHEN** the user submits an already accepted import again
- **THEN** no accepted transaction is duplicated and conflicting rows are explained

#### Scenario: Actual fill conflicts with reconstructed rule
- **WHEN** a broker-confirmed fill conflicts with the system's current rule interpretation
- **THEN** the fact remains recordable with a reconciliation warning and the rule mismatch is retained for investigation

### Requirement: Separate off-exchange fund lifecycle
The system SHALL model fund application, confirmation, NAV date, confirmed units, fees and settlement dates separately from exchange fills.

#### Scenario: Redemption pending confirmation
- **WHEN** a fund redemption has been requested but not confirmed or paid
- **THEN** the system shows pending state without inventing the redemption NAV or available cash

### Requirement: Legacy estimate compatibility
The system SHALL retain existing stock records and their original values. Legacy estimates MUST NOT be included as verified realized ledger P&L unless the user reconciles the required facts.

#### Scenario: Old sell record with later comparison price
- **WHEN** an old record contains a sale price and a later comparison price but no acquisition cost
- **THEN** its old result is labeled a historical estimate and is not interpreted as realized accounting profit

### Requirement: Private access and portable recovery
The system MUST enforce account isolation for transactions, reports, references, exports and cached results. New investment data MUST participate in full backup and recovery, with an explicit private export scope.

#### Scenario: Another account requests a fill or report
- **WHEN** a user requests an investment object belonging to another account
- **THEN** the system returns no private object or sensitive existence details

#### Scenario: Backup restored
- **WHEN** a verified full backup is restored in an isolated environment
- **THEN** investment facts, versions and source references reconcile to the manifest, without restoring AI plaintext secrets from job records
