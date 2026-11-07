## ADDED Requirements

### Requirement: Application shell

Every page shown to a signed-in user SHALL have a shell that contains:

- the Environment banner (see environment-context);
- the signed-in user's display name and role ("Viewer" or "Operator");
- an "Afmelden" control;
- navigation that shows only the sections the user's permissions allow.

In this change, the start page `/` SHALL show an overview of the sections available to the user, with Audit Log as the only section.

#### Scenario: Viewer's start page

- **WHEN** a Viewer signs in and lands on `/`
- **THEN** they see the shell with their name, role "Viewer" and "Afmelden", and a link to the Audit Log

### Requirement: Error and status pages

The Admin Tool Instance SHALL show these pages within the Environment banner:

- a sign-in error page with a generic message, a "probeer opnieuw" link and the correlation id;
- a "no access" page;
- a signed-out page with a link to sign in again;
- a "pagina niet gevonden" page for unknown routes;
- a generic error page with the correlation id for unexpected errors.

No page SHALL show stack traces or internal details. Unknown `/api/*` paths SHALL return a JSON 404, never the frontend page.

#### Scenario: Unknown route

- **WHEN** a signed-in user opens `/bestaat-niet`
- **THEN** the "pagina niet gevonden" page is shown inside the shell

#### Scenario: Unknown API path

- **WHEN** a client requests `/api/v1/bestaat-niet`
- **THEN** it receives a JSON 404 response

#### Scenario: Keycloak unavailable

- **WHEN** a user starts sign-in while the Environment's Keycloak cannot be reached
- **THEN** they see the sign-in error page with a correlation id

### Requirement: Dutch, accessible interface

All user-facing text SHALL be in Dutch, loaded from translation resources, with no hard-coded strings in components. Pages SHALL declare `lang="nl"`. Every page SHALL pass automated WCAG 2.2 AA checks (axe-core) in the end-to-end test suite. The main flows SHALL work by keyboard alone, with a visible focus indicator. These flows are signing in, browsing and filtering the Audit Log, and signing out.

#### Scenario: Automated accessibility check

- **WHEN** the end-to-end suite visits each page
- **THEN** axe-core reports no WCAG 2.2 A or AA violations

#### Scenario: Keyboard-only use

- **WHEN** a user filters the Audit Log and signs out using only the keyboard
- **THEN** every control can be reached and used, and the focus is always visible
