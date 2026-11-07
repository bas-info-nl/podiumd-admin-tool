## ADDED Requirements

### Requirement: Sign-in through the Environment's Keycloak
The Admin Tool Instance SHALL authenticate users only through the OIDC client configured for it in the Environment's Keycloak. It SHALL NOT offer local accounts or any other way to sign in.
- A completed sign-in by a user who holds the Viewer or Operator role SHALL produce exactly one Audit Entry: action `sign-in`, outcome `allowed`.
- A completed sign-in by a user without either role SHALL produce exactly one Audit Entry: action `sign-in`, outcome `denied`, reason `no-role` (see access-control).
- A sign-in callback that fails (an error response from Keycloak, a `state` that does not match or has expired, or a failed token exchange) SHALL NOT create a session. It SHALL be recorded as described in "Recording unauthenticated failures" in the audit-log spec.

#### Scenario: Unauthenticated user opens a page
- **WHEN** a user without a session opens a page of the Admin Tool Instance
- **THEN** they are redirected to the Environment's Keycloak sign-in page
- **AND** after a successful sign-in they are returned to the page they originally requested

#### Scenario: Sign-in by a user with a role
- **WHEN** a user with the Viewer role completes the Keycloak sign-in
- **THEN** a session is created
- **AND** exactly one Audit Entry is recorded with action `sign-in`, the user's identity and outcome `allowed`

#### Scenario: Failed sign-in callback
- **WHEN** the Admin Tool Instance receives a sign-in callback with an error or a `state` value that does not match
- **THEN** no session is created and the user sees the sign-in error page (see ui-shell)

#### Scenario: Audit Log unavailable during sign-in
- **WHEN** a user completes the Keycloak sign-in but the `sign-in` Audit Entry cannot be stored
- **THEN** no session is created and the user sees an error page saying sign-in is temporarily impossible

### Requirement: Safe return after sign-in and sign-out
The page a user is returned to after sign-in SHALL be stored server-side, bound to that sign-in attempt. It SHALL be accepted only as a relative path within the Admin Tool Instance, starting with a single `/`. Any other value SHALL be replaced by `/`. Every absolute URL the tool sends to Keycloak (redirect URI, post-sign-out redirect URI) SHALL be built from the configured public hostname, never from request headers.

#### Scenario: Return target pointing elsewhere
- **WHEN** a sign-in is started with a return target of `//evil.example/` or `https://evil.example/`
- **THEN** after signing in the user lands on `/` of the Admin Tool Instance

#### Scenario: Forged Host header
- **WHEN** a request arrives with a `Host` or `X-Forwarded-Host` header that differs from the configured hostname
- **THEN** the redirect URI sent to Keycloak still uses the configured hostname

### Requirement: Sessions are held by the server
The Admin Tool Instance SHALL keep all OIDC tokens server-side, encrypted at rest, and SHALL store only a hash of each session identifier. The browser SHALL hold only an opaque, random session identifier, in a cookie named with the `__Host-` prefix and marked `HttpOnly`, `Secure` and `SameSite=Lax`, with `Path=/` and no `Domain`. A new session identifier SHALL be issued at every successful sign-in. A session identifier the server does not know SHALL never be adopted.

#### Scenario: Browser storage holds no tokens
- **WHEN** a signed-in user inspects the browser's cookies, local storage and session storage
- **THEN** no access, ID or refresh token is present, only the `__Host-` session cookie

#### Scenario: Session fixation attempt
- **WHEN** a request presents a session identifier that the server never issued, and the user then signs in
- **THEN** the presented identifier is ignored, and the signed-in session gets a newly generated identifier

### Requirement: Session lifetime and expiry
A session SHALL end when any of the following happens, whichever comes first:
- the user is idle longer than the idle timeout (default 30 minutes);
- the absolute session lifetime is reached (default 8 hours, maximum 12 hours);
- Keycloak refuses to refresh the user's tokens (user disabled, Keycloak session ended);
- Keycloak notifies the tool that the user's Keycloak session ended (back-channel logout).

Once the access token has expired, the next request SHALL refresh it before that request is authorised. Expired sessions SHALL be found by the server even if the user never returns, within 5 minutes of expiry. Each expiry SHALL produce exactly one Audit Entry with action `session-expired`, outcome `info`, and the reason (`idle`, `max-lifetime`, `refresh-refused` or `backchannel-logout`). API requests on an ended session SHALL get a 401 response. The UI SHALL then start a new sign-in that returns to the current page.

#### Scenario: Idle session, user returns
- **WHEN** a signed-in user makes no request for longer than the idle timeout and then opens a page
- **THEN** they are sent to sign in again and return to that page afterwards
- **AND** exactly one Audit Entry with action `session-expired` and reason `idle` exists for that session

#### Scenario: Abandoned session
- **WHEN** a user closes the browser and never returns
- **THEN** within 5 minutes after the idle timeout an Audit Entry with action `session-expired` and reason `idle` is recorded

#### Scenario: User disabled in Keycloak
- **WHEN** a signed-in user is disabled in Keycloak and their access token expires
- **THEN** their next request fails with 401, the session ends with reason `refresh-refused`, and they cannot continue

#### Scenario: Absolute lifetime
- **WHEN** a user stays active past the absolute session lifetime
- **THEN** their next request requires signing in again, and an Audit Entry with reason `max-lifetime` is recorded

### Requirement: Sign-out
A signed-in user SHALL be able to sign out. Sign-out SHALL be a state-changing request protected like every other action (see access-control). Signing out SHALL:
- end the session in the Admin Tool Instance;
- end the user's Keycloak session (RP-initiated logout) and return to the tool's signed-out page;
- be recorded as an Audit Entry with action `sign-out` and outcome `allowed`.

#### Scenario: User signs out
- **WHEN** a signed-in user chooses "Afmelden"
- **THEN** their session is ended, they are signed out of Keycloak, and they see the signed-out page
- **AND** an Audit Entry with action `sign-out` and outcome `allowed` is recorded

#### Scenario: Cross-site sign-out attempt
- **WHEN** another website makes the user's browser request the sign-out endpoint
- **THEN** the request is refused and the user stays signed in
