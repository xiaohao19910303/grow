## ADDED Requirements

### Requirement: Explicit offline checks cannot start an unchecked server
The system SHALL support an explicit offline check without opening a database connection, and SHALL reject offline serve.

#### Scenario: Check without a reachable database
- **WHEN** valid configuration uses an unreachable database and check --offline is requested
- **THEN** runtime and directory checks complete with database_checked false, without starting a server

#### Scenario: Attempt offline serve
- **WHEN** serve --offline is requested
- **THEN** the command fails before starting a server or skipping mandatory startup checks

### Requirement: Shared webpage tokens preserve existing behavior
The system SHALL load one webpage token source, retain old variable aliases, and preserve layout and business behavior.

#### Scenario: Keyboard and reduced motion
- **WHEN** a user navigates by keyboard or requests reduced motion
- **THEN** focused inputs have visible outlines and button press animations respect that preference

#### Scenario: Status text is legible
- **WHEN** connection and warning badges render
- **THEN** normal text foreground/background contrast is at least 4.5:1

### Requirement: Runtime acceptance distinguishes missing real configuration
The system SHALL report missing real configuration by field name without credentials, never invent an encryption key, and keep isolated boot success separate from real deployment status.

#### Scenario: Real credentials are missing
- **WHEN** the local installation lacks its original password or encryption key
- **THEN** missing fields are reported and isolated test credentials are not written into business configuration
