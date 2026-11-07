## 1. Repository scaffold

- [ ] 1.1 Run `git init`. Add `.gitignore`, `.editorconfig`, the EUPL-1.2 `LICENSE`, `publiccode.yml`, a `README.md` (purpose, links to CONTEXT.md/ADRs), and `CLAUDE.md` (pointers to CONTEXT.md, ADRs, development-requirements; TDD rule).
- [ ] 1.2 Create `backend/` with uv: Python 3.12, a `pyproject.toml` with FastAPI, uvicorn, SQLAlchemy 2, Alembic, psycopg, Authlib, httpx, structlog, pydantic-settings and cryptography; dev deps pytest, pytest-asyncio, testcontainers, ruff, mypy, import-linter, pip-audit.
- [ ] 1.3 Create the hexagonal package layout `podiumd_admin/{domain,application,ports,adapters/{http,db,oidc,logging}}`, with an import-linter contract that the domain and application layers import no FastAPI, SQLAlchemy or Authlib (D1). Add a test that runs the contract.
- [ ] 1.4 Create `frontend/` with Vite, React and TypeScript: React Router, TanStack Query, react-i18next (`nl` default), `@utrecht/component-library-react`, eslint, vitest + Testing Library.
- [ ] 1.5 Create the `e2e/` package with `playwright-bdd`, `@axe-core/playwright` and an empty features folder. Add an npm script that generates and runs the tests.

## 2. Domain: roles, permissions, Environment identity (test-first)

- [ ] 2.1 Write failing tests for `EnvironmentIdentity`. A Municipality and a stage (`test|accp|prod`) are required, the label is optional, and invalid values are rejected. Then implement it.
- [ ] 2.2 Write failing tests for `Role` (Viewer, Operator) and for mapping token roles to Roles: a configurable claim path and names; both roles → Operator; a missing claim → no role. Then implement.
- [ ] 2.3 Write failing tests that cover every permission × role for the central `PERMISSIONS` mapping (`audit-log:read`, `session:sign-out`), plus an `authorise(user, permission)` policy returning allowed or denied with a reason. Then implement.

## 3. Domain: Audit Entries (test-first)

- [ ] 3.1 Write failing tests for `AuditEntry`. Required fields; outcome enum `allowed|denied|succeeded|failed|info`; a `ReasonCode` enum; text-length caps; secret-like parameters rejected. Then implement.
- [ ] 3.2 Write failing tests for the `record_then_act` application service. The action runs only after a successful insert, an insert failure prevents the action, and a denial still denies when the insert fails, logging to stdout. Use fake ports. Then implement.
- [ ] 3.3 Write failing tests for the unauthenticated-failure aggregator: at most one line per (client IP, reason) per minute, with a count, driven by a fake Clock. Then implement.

## 4. Persistence adapter

- [ ] 4.1 Add Alembic migrations for the `audit_entries` and `sessions` tables, with the D4 indexes and the grants for `podiumd_admin_app` (SELECT/INSERT only on `audit_entries`).
- [ ] 4.2 Write failing integration tests with testcontainers PostgreSQL, which creates the owner and app roles: inserting and querying Audit Entries; UPDATE, DELETE and TRUNCATE as the app user fail with a permission error. Then implement `SqlAuditRepository`.
- [ ] 4.3 Write failing integration tests for the Audit Log query: filters for time range (inclusive), username (case-insensitive substring), action and outcome; pagination of 50, newest first. Then implement it.
- [ ] 4.4 Write failing tests for `SqlSessionStore`: lookup by SHA-256 of the session id; tokens encrypted with MultiFernet, decryptable with rotated keys; an unknown id → none. Then implement.

## 5. Logging adapter

- [ ] 5.1 Configure structlog for JSON on stdout. Write failing tests showing that a stored Audit Entry is emitted exactly once with `log_type: "audit"` after commit, and that ordinary logs never carry that marker. Then implement `StdoutAuditSink`.

## 6. Configuration and app bootstrap

- [ ] 6.1 Write failing tests for the pydantic-settings config. Required: the Environment identity, `publicHostname`, the Keycloak issuer and client, the role claim and names, the DB URLs, encryption keys, timeouts (defaults 30 min/8 h, max 12 h), and `trustedProxies` (default empty). Startup fails on missing values or a known development key. Then implement.
- [ ] 6.2 Create the FastAPI app factory with `/api/v1` routing, docs/redoc/openapi disabled at runtime, and a script that exports `openapi.json` at build time.
- [ ] 6.3 Write failing tests for the security-headers middleware (CSP, nosniff, Referrer-Policy, `Cache-Control: no-store` on the API, `/docs` and `/openapi.json` → 404). Then implement.
- [ ] 6.4 Write failing tests for client-IP resolution: honour `X-Forwarded-For` only from `trustedProxies` CIDRs; spoofed headers are ignored by default. Then implement.
- [ ] 6.5 Write failing tests for the `/healthz` (liveness) and `/readyz` (DB reachable) endpoints, revealing no configuration. Then implement.
- [ ] 6.6 Write failing tests for the unauthenticated `GET /api/v1/environment`. Then implement.

## 7. Authentication adapter

- [ ] 7.1 Write failing tests for the sign-in start: a pre-auth record with state, nonce, PKCE and the return path; a return path that isn't a single-`/` relative path becomes `/`; the redirect URI is built from `publicHostname` even with a forged Host or X-Forwarded-Host. Then implement with Authlib.
- [ ] 7.2 Write failing tests for the callback. On success: rotate to a new session, set the `__Host-` cookie, and write one `sign-in/allowed` entry. No role → one `sign-in/denied/no-role` entry and the "no access" page. A bad state or error → no session, and the stdout aggregator records it. An audit insert failure → no session and an error page. Then implement.
- [ ] 7.3 Write failing tests for the request-time session dependency: idle and absolute expiry; refresh of an expired access token before authorisation, with roles re-read; a refused refresh ends the session with `refresh-refused`; an ended session → 401. Then implement.
- [ ] 7.4 Write failing tests for the expiry sweep background task. Abandoned sessions get exactly one `session-expired/info` entry within one sweep interval, and their tokens are purged. Then implement it (every minute, single replica).
- [ ] 7.5 Write failing tests for `POST /auth/backchannel-logout`: validate the logout token against Keycloak's JWKS and end the sessions with matching `sid`, using reason `backchannel-logout`. Then implement.
- [ ] 7.6 Write failing tests for `POST /api/v1/session/sign-out`. It needs the CSRF header and `session:sign-out`, writes `sign-out/allowed` before ending the session, and returns the `end_session_endpoint` URL. An audit failure → the session is kept and an error is returned. Then implement.
- [ ] 7.7 Write integration tests against testcontainers Keycloak, with a realm import of the client, roles and users `viewer`, `operator` and `norole`, covering the full code flow, refresh and back-channel logout.

## 8. Authorisation in HTTP

- [ ] 8.1 Write failing tests for the `require(permission)` dependency: denied → 403 with no effect, plus an Audit Entry with `missing-permission` and the permission name; allowed reads aren't recorded. Then implement.
- [ ] 8.2 Write failing tests for the CSRF guard. A non-GET without `X-PodiumD-Admin: 1` → refused and audited as `csrf`. The OIDC callback and back-channel endpoints are exempt. No CORS headers are ever sent. Then implement.
- [ ] 8.3 Add a route-enumeration test. Every route is either in the explicit unauthenticated allowlist or protected by `require(...)`, and every GET route is registered as side-effect free.
- [ ] 8.4 Write failing tests for `GET /api/v1/audit-entries` (list with filters) and `GET /api/v1/audit-entries/{id}`, both protected by `audit-log:read`. Then implement.
- [ ] 8.5 Write failing tests for `GET /api/v1/me`: display name, role and permissions, used by the shell. Then implement.

## 9. Frontend

- [ ] 9.1 Add the `podiumd-admin` design-token theme, including tokens for the test, accp and prod banners (contrast ≥ 4.5:1, prod full-width red), plus thin wrapper components around the Utrecht components.
- [ ] 9.2 Generate the typed API client from the exported `openapi.json` (`openapi-typescript` + `openapi-fetch`). The client always sends `X-PodiumD-Admin: 1` on non-GET. On 401, it starts sign-in with the current path.
- [ ] 9.3 Build the Environment banner and the tab-title helper (`<page> · <stage name> · <Municipality> · PodiumD Admin`), with component tests for all three stages.
- [ ] 9.4 Build the app shell (banner, user name and role, "Afmelden", navigation filtered by permissions) and the start page listing the available sections. Write component tests first.
- [ ] 9.5 Build the Audit Log page: filters, pagination of 50, Europe/Amsterdam timestamps, a detail view, the "geen resultaten" state, and plain-text rendering only. Include a component test with a markup payload.
- [ ] 9.6 Build the error and status pages: sign-in error (with correlation id), no access, signed out, "pagina niet gevonden", and generic error. Each shows the Environment banner and no internal details.
- [ ] 9.7 Put all strings in `nl` translation files. Add a lint rule or test that fails on hard-coded JSX text. Set `lang="nl"`.
- [ ] 9.8 Configure the backend to serve the built SPA with an `index.html` fallback, except under `/api/*`, which returns JSON 404. Write a test first.

## 10. Container image

- [ ] 10.1 Write a multi-stage Dockerfile: node build → uv install → `python:3.12-slim`, uid 1000, no shell tools needed at runtime, `/tmp` the only writable path.
- [ ] 10.2 Add a container smoke test in CI: the image starts with a read-only root filesystem and `/healthz` responds.

## 11. Helm chart `charts/podiumd-admin`

- [ ] 11.1 Scaffold the chart following the Maykin/PodiumD conventions (`fullnameOverride`, `existingSecret`, `extraEnv`, `podSecurityContext`), with a `values.schema.json` that requires the stage, Municipality, `publicHostname`, Keycloak issuer and client, and all Secret references.
- [ ] 11.2 Add the Deployment: 1 replica, `Recreate` strategy, hardened securityContext, a `/tmp` emptyDir, liveness and readiness probes, and env from values and Secrets. Add the Service, an optional Ingress, and an optional HTTPRoute.
- [ ] 11.3 Add the pre-install and pre-upgrade migration hook Job (`alembic upgrade head` with the owner credentials).
- [ ] 11.4 Add the ServiceAccount, Role and RoleBinding skeleton (namespace-scoped, minimal).
- [ ] 11.5 Write helm-unittest tests: schema failures for missing required values; the security context; no ClusterRole or ClusterRoleBinding; no `pods/exec`; no `list`/`watch` on Secrets; the hook Job uses owner credentials and the Deployment uses app credentials.
- [ ] 11.6 Write `docs/install.md`. Cover creating the Keycloak client (confidential, exact redirect URIs, client roles, back-channel logout URL, access-token lifespan ≤5 min), creating the database with owner and app roles (SQL), Secrets and key generation, `trustedProxies`, and the expected deploy-side HTTPRoute.

## 12. Local development

- [ ] 12.1 Create a kind cluster config and a `Tiltfile`. They run PostgreSQL (creating the owner and app roles), Keycloak with a realm import (client `podiumd-admin`, client roles, users `viewer`, `operator` and `norole`), and the app, with live reload for backend and frontend.
- [ ] 12.2 Add development-only Secrets, including the development encryption key that the app rejects outside local development, and document `tilt up` in the README.

## 13. End-to-end (Playwright BDD)

- [ ] 13.1 Write feature `sign-in.feature`: a Viewer signs in and sees the shell and start page; a user without a role sees "no access"; the return to the originally requested page works.
- [ ] 13.2 Write feature `audit-log.feature`: an Operator filters on denied entries; the entry detail shows all fields; the empty state appears.
- [ ] 13.3 Write feature `environment.feature`: the banner text and the tab title show the configured stage and Municipality.
- [ ] 13.4 Write feature `sign-out.feature`: "Afmelden" ends the session and the Keycloak session; the signed-out page is shown; the `sign-out` entry is visible after signing in again.
- [ ] 13.5 Write feature `accessibility.feature`: run an axe-core WCAG 2.2 A/AA check on every page above, and a keyboard-only flow that filters the Audit Log and signs out.

## 14. CI and release

- [ ] 14.1 Add a GitHub Actions `ci.yml` with these jobs:
  - backend: ruff, mypy --strict, import-linter, pytest including testcontainers;
  - frontend: eslint, tsc, vitest, plus a check that the generated client is up to date;
  - chart: helm lint, helm-unittest.
- [ ] 14.2 Add the e2e job: kind, plus the chart installed with the dev values, Keycloak and PostgreSQL, then run playwright-bdd and upload the report.
- [ ] 14.3 Add dependency scanning on every PR (pip-audit, npm audit, Trivy image scan), and Dependabot config.
- [ ] 14.4 Add `release.yml` for tags: build and push the image, sign it with cosign, attach an SBOM, and package and publish the Helm chart.

## 15. Wrap-up

- [ ] 15.1 Verify that every spec scenario in this change is covered by at least one test (unit, integration, helm-unittest or e2e). Record the mapping in `docs/traceability.md`.
- [ ] 15.2 Update CONTEXT.md if implementation surfaced new domain terms. Write a superseding ADR if any decision in design.md changed.
