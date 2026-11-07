## ADDED Requirements

### Requirement: Environment identity is configured at installation
Every Admin Tool Instance SHALL be configured with the identity of its Environment:
- the Municipality name (required);
- the Environment's stage (required, one of `test`, `accp`, `prod`);
- an optional label, shown next to the stage, e.g. a hosting party name.

The Admin Tool Instance SHALL refuse to start if the Municipality or stage is missing or invalid.

#### Scenario: Missing stage
- **WHEN** an Admin Tool Instance starts without a valid stage configured
- **THEN** it fails to start with an error naming the missing setting

### Requirement: Environment is always visible
Every page SHALL show a persistent Environment banner with the Municipality and the stage name as text. This includes the sign-in error, "no access", signed-out and error pages. The stage names are `test` → "Test", `accp` → "Acceptatie" and `prod` → "Productie". Each stage SHALL have its own colour from design tokens, with text contrast of at least 4.5:1. The prod banner SHALL span the full width in red. The stage SHALL never be conveyed by colour alone.

#### Scenario: Working in prod
- **WHEN** a user opens any page of the prod Admin Tool Instance
- **THEN** a full-width red banner shows the Municipality name and "Productie"

#### Scenario: Working in accp
- **WHEN** a user opens any page of the accp Admin Tool Instance
- **THEN** the banner shows "Acceptatie" in the accp colour, which is different from prod

#### Scenario: Working in test
- **WHEN** a user opens any page of the test Admin Tool Instance
- **THEN** the banner shows "Test" in the test colour

### Requirement: Environment in records and titles
Every Audit Entry SHALL record the Environment it was created in. The browser tab title SHALL be `<page> · <stage name> · <Municipality> · PodiumD Admin`.

#### Scenario: Tab title
- **WHEN** a user has the accp and prod Admin Tool Instances of the same Municipality open in two tabs
- **THEN** one tab title contains "Acceptatie" and the other "Productie"
