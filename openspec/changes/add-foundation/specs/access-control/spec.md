## ADDED Requirements

### Requirement: Roles
The Admin Tool Instance SHALL recognise exactly two roles, **Viewer** and **Operator**. They are assigned as client roles of the Admin Tool's OIDC client in the Environment's Keycloak. The claim the roles are read from and the role names that map to Viewer and Operator SHALL be configurable. An Operator SHALL have every permission a Viewer has. A user holding both roles SHALL be treated as an Operator. Roles SHALL be re-evaluated every time the access token is refreshed.

#### Scenario: Viewer signs in
- **WHEN** a user whose token contains the configured Viewer role signs in
- **THEN** they can use every part of the Admin Tool Instance that requires only Viewer permissions

#### Scenario: Role removed during a session
- **WHEN** a Viewer's role is removed in Keycloak while they are signed in
- **THEN** after their access token has expired, their next request gets the "no access" response
- **AND** an Audit Entry with outcome `denied` and reason `no-role` is recorded

### Requirement: Users without a role are refused
A user who completes sign-in but holds neither role SHALL get no session that grants access. They SHALL see the "no access" page, which names the Environment. Exactly one Audit Entry SHALL be recorded, with action `sign-in`, outcome `denied` and reason `no-role`.

#### Scenario: Authenticated user without a role
- **WHEN** a user without the Viewer or Operator role completes the Keycloak sign-in
- **THEN** they see the "no access" page that names the Environment
- **AND** exactly one Audit Entry with action `sign-in`, outcome `denied` and reason `no-role` is recorded

### Requirement: Reads and actions
A **read** is a request that only retrieves data. It SHALL use HTTP GET and SHALL have no side effects. An **action** is any request that changes state, in the Admin Tool Instance or the Environment. It SHALL use a non-GET HTTP method. In this change, the only actions are sign-in completion and sign-out. Later changes add actions such as starting a Script Run.

#### Scenario: GET has no side effects
- **WHEN** the automated route test enumerates all GET routes
- **THEN** none of them is registered as an action

### Requirement: Every request is authorised on the server
Every read and every action SHALL be authorised by the backend against the user's permissions, whatever the UI shows. The only exceptions SHALL be these unauthenticated endpoints:
- the sign-in start and callback;
- the back-channel logout endpoint;
- the Environment identity endpoint;
- the health endpoints;
- the static frontend assets.

A request lacking the required permission SHALL be refused with an "access denied" response, SHALL have no effect, and SHALL be recorded as an Audit Entry with outcome `denied`, reason `missing-permission`, and the required permission. A permitted action SHALL be recorded with outcome `allowed` before it takes effect (see audit-log). Permitted reads are not recorded.

#### Scenario: User without a role calls the Audit Log API
- **WHEN** a request whose session holds no role calls the Audit Log API directly
- **THEN** it is refused with "access denied" and no data is returned
- **AND** an Audit Entry with outcome `denied` records the user, the endpoint and the required permission `audit-log:read`

#### Scenario: Request without a session
- **WHEN** an API request arrives without a valid session
- **THEN** it is refused with 401 and nothing changes
- **AND** it is handled as described in "Recording unauthenticated failures" in the audit-log spec

### Requirement: Actions are protected against cross-site requests
Every action SHALL require the custom request header `X-PodiumD-Admin: 1`, which only the tool's own frontend sends. An action without the header SHALL be refused, have no effect, and be recorded as denied with reason `csrf`. The Admin Tool Instance SHALL NOT send CORS headers that allow other origins.

#### Scenario: Action without the header
- **WHEN** a request to an action endpoint arrives with a valid session cookie but without the `X-PodiumD-Admin` header
- **THEN** it is refused with no effect, and an Audit Entry with outcome `denied` and reason `csrf` is recorded

### Requirement: Permission catalogue
The backend SHALL define one central, explicit mapping from each permission to the roles that hold it. In this change it SHALL contain `audit-log:read` (Viewer, Operator) and `session:sign-out` (Viewer, Operator). Later changes SHALL add their permissions, including Operator-only ones, to this same mapping instead of checking roles directly. Automated tests SHALL check every permission against every role.

#### Scenario: Audit Log permission
- **WHEN** a Viewer or an Operator opens the Audit Log
- **THEN** access is granted, because both roles hold `audit-log:read`
