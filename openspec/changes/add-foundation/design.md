## Context

The repository currently contains only the domain glossary (`CONTEXT.md`), ADRs 0001–0011, the development requirements and the PodiumD research. This change creates the code base and everything later changes depend on: identity, authorisation, the Audit Log, Environment awareness, packaging and the developer loop.

Constraints:
- **One Admin Tool Instance per Environment**, inside the PodiumD namespace of a dedicated AKS cluster (ADR 0001, 0011).
- **Stack:** Python/FastAPI backend, React/TS frontend, one image (ADR 0008). Hexagonal backend (ADR 0009).
- **Audit Log:** in the tool's own PostgreSQL database plus stdout (ADR 0005).
- **Compliance baseline:** EUPL-1.2, NL Design System, WCAG 2.2 AA, Dutch UI, hardened image (ADR 0007).
- **Packaging:** own Helm chart now, PodiumD subchart later (ADR 0006). This means values style and naming should follow the PodiumD and Maykin charts.
- **Replicas:** a single backend replica in v1 (ADR 0010).

Stakeholders: municipality admins (users), the operators who install it per Environment, and Dimpact (future upstream maintainer).

## Goals / Non-Goals

**Goals:**
- A deployable Admin Tool Instance that signs users in through the Environment's Keycloak, applies the Viewer and Operator roles, and records every attempted action in the Audit Log.
- A backend structure where later changes add capabilities (Script Runs, Checks, Effective Settings) as new domain modules and adapters without touching the foundation.
- A complete developer loop: local kind + Tilt, CI, and a Playwright BDD scaffold with the first features green.

**Non-Goals:**
- Script Catalogue, Script Runs, Diagnostic Runs, Effective Settings and any Kubernetes access beyond the RBAC skeleton. These come in changes 2 and 3.
- Four-eyes approval, Audit Log retention and export, multiple replicas or HA.
- Provisioning the Keycloak client automatically. The client is documented and created by the installer for now (see Open Questions).

## Decisions

### D1. Repository and backend layout
```
backend/src/podiumd_admin/
  domain/          # pure: Role, Permission, AuditEntry, EnvironmentIdentity, policies
  application/     # use cases (sign-in completion, authorise, record audit, query audit)
  ports/           # Protocols: AuditRepository, AuditSink, SessionStore, IdentityProvider, Clock
  adapters/
    http/          # FastAPI routers, dependencies, SPA static serving
    db/            # SQLAlchemy models, repositories, Alembic migrations
    oidc/          # Authlib Keycloak client
    logging/       # structlog stdout AuditSink
  config.py        # pydantic-settings, fed by Helm values via env
frontend/          # Vite React app
charts/podiumd-admin/
e2e/               # playwright-bdd features + steps
```
The domain has no imports from FastAPI, SQLAlchemy or Authlib, and `import-linter` contracts enforce this (ADR 0009). Python tooling is **uv** (lockfile, fast CI). Considered: Poetry, which is slower and has no advantage here.

### D2. Authentication: backend-for-frontend with server-side sessions
The backend acts as a confidential OIDC client and uses the Authorization Code flow with PKCE via Authlib.

**Sign-in.**
- A pre-auth record holds `state`, `nonce`, the PKCE verifier and the validated return path (relative, starting with a single `/`).
- After a successful callback, that record is deleted and a brand-new session is created. This rotation prevents fixation.
- All absolute URLs are built from `publicHostname`, never from request headers.

**Session store.**
- A `sessions` table keyed by SHA-256(session id).
- Tokens are encrypted with `MultiFernet`, using keys from a referenced Secret (a primary key plus older keys, for rotation).
- The browser cookie is `__Host-podiumd_admin_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`).

**Lifetime.**
- **Idle timeout:** 30 min. **Absolute lifetime:** 8 h, with a maximum of 12 h. Both are configurable.
- **Refresh.** An expired access token is refreshed before the request is authorised, and the roles are re-read at that point. A refused refresh ends the session.
- **Back-channel logout.** A `POST /auth/backchannel-logout` endpoint validates the logout token and ends the sessions with matching `sid`.
- **Expiry sweep.** A background task in the single replica (ADR 0010) runs every minute. It ends sessions past their idle or absolute limit, writes one `session-expired`/`info` entry per session, and purges the tokens.

**Sign-out.** Sign-out is `POST /api/v1/session/sign-out`, using the CSRF header. The SPA then navigates to Keycloak's `end_session_endpoint` with `id_token_hint` and a `post_logout_redirect_uri` built from `publicHostname`.

Considered:
- **Tokens in the SPA** (public client): rejected, because of XSS exposure.
- **Signed-cookie sessions:** rejected. They are too large and can't be revoked server-side.
- **Redis:** rejected. It's an extra dependency for one replica.

**CSRF.** `SameSite=Lax`, plus a required `X-PodiumD-Admin: 1` header on every non-GET request, including auth endpoints other than the OIDC callback and the back-channel logout (which Keycloak calls). No CORS middleware is installed. A route test asserts that every GET handler is free of side effects.

**Proxy trust.** Forwarded headers are honoured only from the `trustedProxies` CIDRs (default: none). The client IP is the right-most address that isn't a trusted proxy.

**Response hardening.** A middleware adds the CSP, `nosniff`, `Referrer-Policy` and API `Cache-Control: no-store` headers. FastAPI's `docs_url`, `redoc_url` and `openapi_url` are disabled at runtime. The OpenAPI spec is exported at build time by a script, for client generation.

### D3. Roles from Keycloak client roles
Roles are read from a configurable claim path, by default `resource_access.<client_id>.roles`. Keycloak role names map to Viewer and Operator through values (`auth.roles.viewer`, `auth.roles.operator`, defaults `viewer` and `operator`). Considered: realm roles, which are shared across all PodiumD Components and invite accidental grants. Client roles keep the tool's access self-contained.

Roles are re-read at every token refresh, so removing a role takes effect within one access-token lifetime.

**Authorisation** is one domain policy, `PERMISSIONS: dict[Permission, frozenset[Role]]`, enforced by a FastAPI dependency `require(permission)`. The dependency records the denied Audit Entry and raises 403. Its counterpart `audited_action(...)` records the allowed entry for actions.

### D4. Audit Log: write first, append-only by privilege
**Write-first.**
- An allowed action runs inside a unit of work. The Audit Entry is inserted first, and the action runs only after that insert succeeds.
- For database-only actions, such as ending a session, both happen in the same transaction.
- For external side effects (Kubernetes Jobs, from change 2), the `allowed` entry is committed before the side effect. A later `succeeded`/`failed` entry records the result.
- **Denials** are refused even if their entry can't be stored. The audit failure is then logged to stdout.

**Outcome values.** `allowed | denied | succeeded | failed | info`. Reason codes come from a Python enum, so free text from requests or Keycloak `error_description` is never stored. Text fields are truncated to fixed limits.

**Unauthenticated failures** (no user identity, e.g. a bad callback `state` or a request without a session) go to stdout only. A per-(client IP, reason) aggregator emits at most one line per minute with a count. This stops anonymous traffic from flooding the append-only table, which would otherwise fail closed.

**stdout copy.** The structlog JSON line (`log_type: "audit"`) is emitted after the commit, so stdout never shows an entry that wasn't stored.

**Append-only by privilege.** Two database roles:
- `podiumd_admin_owner` owns the schema and runs migrations.
- `podiumd_admin_app` is used at runtime. It has `SELECT, INSERT` on `audit_entries`, the normal privileges on `sessions`, and no `UPDATE`/`DELETE`/`TRUNCATE` on `audit_entries`.

Alembic migrations set these grants.

Considered: a single user with a trigger that blocks UPDATE/DELETE. It's weaker, because the owner can drop the trigger.

**Indexes** on `(occurred_at desc)`, `user_subject`, `action` and `outcome`.

### D5. Environment identity
Values `environment.municipality`, `environment.stage` (enum `test|accp|prod`, enforced by `values.schema.json` and pydantic) and `environment.label`. Startup fails if the Municipality or stage is missing. The frontend gets them from an unauthenticated `/api/v1/environment` endpoint, so even the "no access" and error pages can show the banner. The banner colours come from design tokens per stage, with prod in a high-contrast red treatment that meets WCAG contrast requirements.

### D6. Frontend
- **Libraries.** React + TypeScript + Vite, React Router, TanStack Query.
- **NL Design System.** Components from `@utrecht/component-library-react`, with an own `podiumd-admin` token theme. Considered: the Dimpact or Denhaag themes. Those are municipality branding, and the tool must look neutral across municipalities.
- **i18n.** `react-i18next` with `nl` as default and `en` for development.
- **API client.** Generated from the backend OpenAPI spec with `openapi-typescript` + `openapi-fetch`. CI fails if the committed client is out of date.

### D7. Image and serving
A multi-stage Dockerfile: node build → uv build → `python:3.12-slim` runtime, uid 1000, with `/tmp` as the only writable path (an emptyDir in the chart). Uvicorn serves the FastAPI app, which serves the built SPA from `/` with a fallback to `index.html`. The API lives under `/api/v1`, health under `/healthz` and `/readyz`.

### D8. Helm chart
- **Structure** follows the Maykin chart conventions: `fullnameOverride`, `existingSecret` patterns, `extraEnv`, `podSecurityContext`, `values.schema.json`.
- **Migrations.** A `pre-install,pre-upgrade` hook Job runs `alembic upgrade head` with the owner credentials. The Deployment uses the app credentials.
- **Secrets.** All Secrets are referenced through `existingSecret` values: the Keycloak client secret, the owner and app database credentials, and the session encryption keys. The chart never generates them. Startup refuses known development keys.
- **Exposure.** A Service is always created. An Ingress is optional and off by default, because PodiumD Environments expose apps through HTTPRoutes created on the deploy side (research). An optional HTTPRoute template exists for clusters that want it.
- **RBAC skeleton.** A ServiceAccount plus a Role/RoleBinding with `get` on its own ConfigMap only. Changes 2 and 3 extend the rules. A `helm-unittest` test asserts that there is no cluster-scoped RBAC, no `pods/exec`, and no `list`/`watch` on Secrets.

### D9. Developer loop and tests
- **Local.** kind + Tilt. It brings up PostgreSQL, a Keycloak with a realm import (client `podiumd-admin`, users `viewer`, `operator` and `norole`) and the app, with live reload.
- **Unit tests.** pytest for the domain and application layers, written test-first.
- **Integration tests.** testcontainers for PostgreSQL (the grants and append-only guarantee) and Keycloak (the OIDC flow).
- **End-to-end tests.** `playwright-bdd` features written in English Gherkin using CONTEXT.md terms, while asserting the Dutch UI text. They run against the kind environment in CI, with axe-core checks on every page visited.
- **Quality gates from the first PR.** Pre-commit hooks locally. In CI, on every PR:
  - `backend`: ruff lint + format, mypy --strict, import-linter, pytest with a coverage gate of ≥ 85% on domain/application, pip-audit;
  - `frontend`: eslint with typescript-eslint strict, jsx-a11y and i18next; prettier; tsc; vitest with coverage; npm audit; a check that the generated client is up to date;
  - `hygiene`: gitleaks, actionlint, hadolint;
  - CodeQL for Python and TypeScript;
  - `chart`: helm lint, helm-unittest, kubeconform;
  - `image`: build, Trivy, smoke test;
  - `e2e`: kind + playwright-bdd.

  Each job becomes a required status check in the `protect-main` ruleset as soon as it exists. Dependabot runs weekly. Release: cosign signing and an SBOM on tags. SonarCloud was considered and rejected; the tools above cover lint, types, security static analysis and coverage without an external service.
- **Deferred.** The docker-compose fallback from the development requirements is deferred to a later change. kind + Tilt is the only supported loop for now.

## Risks / Trade-offs

- **[Two database roles add installation burden]** → The chart accepts two `existingSecret`s. The install docs give the SQL to create both roles. An optional bootstrap Job can create the app role when given owner credentials.
- **[A role change takes effect only at the next refresh]** → Keep the access-token lifespan for the client short (≤5 minutes). Back-channel logout ends sessions immediately when the user's Keycloak session ends.
- **[A single replica means downtime during upgrades]** → Accepted for an admin tool (ADR 0010). Use the `Recreate` strategy so two versions never run against the same schema.
- **[The append-only Audit Log grows without bound]** → Retention is out of scope for now (user decision, 2026-11-05). Unauthenticated noise is kept out of the table (D4). Revisit before large-scale prod use.
- **[NL Design System React components are still maturing]** → Wrap them in thin local components so a library swap stays local.
- **[A secret-encryption key in a Kubernetes Secret]** → If it rotates, all sessions are invalidated. That's acceptable: users sign in again.
- **[Keycloak client provisioning is manual]** → Document it, and add a realm-import snippet to propose upstream to the PodiumD Keycloak configuration.

## Migration Plan

This is a first installation, so nothing needs migrating. The rollout per Environment:
1. Create the Keycloak client and roles.
2. Create the database, the two roles and the Secrets.
3. Install the chart, starting with `test`/`accp`, then `prod`.

Rollback is `helm rollback`. Database migrations in this change only create objects, so rolling back leaves an unused schema.

## Open Questions

- **Keycloak realm and client.** Which realm hosts the client: the PodiumD realm (likely `podiumd`, per `keycloak-podiumd-realm-secrets`) or a separate admin realm? Can the client be added to PodiumD's keycloak-config-cli import, or must installers create it by hand?
- **Client IP.** Do Environments sit behind the Azure Application Gateway with `X-Forwarded-For`? Which CIDRs should installers set as `trustedProxies`? The default trusts none.
- **Database server.** Are the database server and its admin credentials available to installers, so they can create the second (app) role? If not, fall back to a trigger-based guard plus a documented weaker guarantee, recorded in a superseding ADR.
