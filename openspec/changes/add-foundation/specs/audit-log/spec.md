## ADDED Requirements

### Requirement: What is recorded
The Admin Tool Instance SHALL record an Audit Entry for each of the following:
- sign-ins, both allowed and denied;
- sign-outs;
- session expiries;
- every attempted action, allowed or denied;
- every refused read by an authenticated user.

Permitted reads SHALL NOT be recorded. An Audit Entry SHALL contain:
- a unique id;
- a timestamp in UTC;
- the Environment;
- the user's identity (Keycloak subject and username), when known;
- the action and its target, if any;
- the parameters, never including secret values;
- the outcome;
- a reason code for denials and system events;
- a correlation id for the request;
- the client IP address (see installation, "Trusted proxies").

The outcome SHALL be one of:
- `allowed` or `denied`: the decision on an attempt;
- `succeeded` or `failed`: the result of an action whose effect completes later, used from change 2 onwards;
- `info`: system events such as session expiry.

Reason codes SHALL come from a fixed set; free text from requests or Keycloak SHALL NOT be stored. Every text field SHALL be capped in length. Audit Entries SHALL NOT contain Script Run Output.

#### Scenario: Refused read
- **WHEN** an authenticated user without the required permission requests the Audit Log
- **THEN** an Audit Entry is stored with their identity, the endpoint, outcome `denied` and reason `missing-permission`

#### Scenario: Permitted reads are not recorded
- **WHEN** a Viewer browses pages they are allowed to see
- **THEN** no Audit Entries are created for those page views

### Requirement: Recording unauthenticated failures
Failures without an authenticated user (failed sign-in callbacks and requests without a valid session) SHALL be written to stdout as structured JSON with `log_type: "audit"` and a fixed reason code. They SHALL NOT be stored in the database. Repeated identical failures from the same client IP SHALL be combined into at most one line per minute that includes a count. This prevents anonymous requests from flooding the Audit Log.

#### Scenario: Burst of invalid callbacks
- **WHEN** one client IP sends 500 sign-in callbacks with an invalid `state` within one minute
- **THEN** no Audit Entries are stored in the database
- **AND** stdout holds at most one combined line for that client IP and reason for that minute, with count 500

### Requirement: Audit Entries are append-only
Once stored, an Audit Entry SHALL never be changed or deleted by the Admin Tool Instance. The application SHALL offer no way to update or delete Audit Entries. The database user the application runs with SHALL lack UPDATE, DELETE and TRUNCATE privileges on Audit Entries.

#### Scenario: Attempting to modify an entry
- **WHEN** a statement updating or deleting an Audit Entry is executed with the application's database user
- **THEN** the database rejects it with a permission error

### Requirement: No action without an Audit Entry
An allowed action SHALL take effect only after its Audit Entry has been stored. If that Audit Entry cannot be stored, the action SHALL NOT take effect, and the user SHALL see an error saying the action could not be recorded. If the Audit Entry for a denial cannot be stored, the request SHALL still be denied, and the failure SHALL be written to stdout.

#### Scenario: Audit insert fails during an action
- **WHEN** storing Audit Entries fails (for example, the insert privilege is revoked in a test) and a user signs out
- **THEN** the session is not ended and the user sees an error saying the action could not be recorded

#### Scenario: Audit insert fails during a denial
- **WHEN** storing Audit Entries fails and a user without the required permission calls a protected endpoint
- **THEN** the request is still refused, and a stdout line reports the failed audit write

### Requirement: Structured copy on stdout
Every stored Audit Entry SHALL also be written to the container's stdout as one JSON line, after it has been stored. The line SHALL hold the same fields plus `log_type: "audit"`, so that a log scraper can collect it if one is present. Ordinary application log lines SHALL NOT use `log_type: "audit"`.

#### Scenario: Entry appears in container logs
- **WHEN** an Audit Entry is stored
- **THEN** exactly one JSON line with `"log_type": "audit"` and the same entry id appears in the container's stdout

### Requirement: Browsing the Audit Log
Users with `audit-log:read` SHALL be able to browse the Audit Log:
- newest first, 50 entries per page;
- with timestamps shown in Europe/Amsterdam time;
- filtered by time range (inclusive), username (case-insensitive substring), action and outcome;
- opening an Audit Entry to see all its fields.

Every field value SHALL be displayed as plain text, never interpreted as markup. When no entries match, a clear "geen resultaten" message SHALL be shown.

#### Scenario: Filter on denied attempts
- **WHEN** a Viewer filters the Audit Log on outcome `denied` for the last 7 days
- **THEN** only denied Audit Entries from that period are shown, newest first

#### Scenario: Markup in a field
- **WHEN** an Audit Entry's username contains `<img src=x onerror=alert(1)>`
- **THEN** it is displayed literally and no script runs

#### Scenario: No matches
- **WHEN** the filters match no Audit Entries
- **THEN** the "geen resultaten" message is shown
