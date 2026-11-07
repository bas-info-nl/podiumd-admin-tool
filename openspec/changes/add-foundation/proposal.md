## Why

Municipality admins have no safe, accountable way to operate their PodiumD Environments. Today, running a management command or diagnosing a misconfiguration means someone with cluster access runs `kubectl` by hand, and nothing records what was done. Before the tool can offer Script Runs, Diagnostic Runs or Effective Settings, it needs a deployable, secure base. That means knowing who the user is, what they are allowed to do, and recording every attempt. This is change 1 of 3 for v1. Script Runs and Diagnostics/Effective Settings follow in later changes.

## What Changes

- **Monorepo scaffold.** `backend/` (FastAPI, hexagonal layout), `frontend/` (React + TypeScript + Vite, NL Design System, Dutch UI with i18n), `charts/podiumd-admin/` (Helm chart), and `docs/`. Licensed EUPL-1.2, with a `publiccode.yml`.
- **One container image.** It runs as non-root with a read-only root filesystem. The backend serves the built frontend.
- **Sign-in.** Users sign in through the Environment's Keycloak (OIDC authorization code flow). The backend holds the session; the browser gets only an HTTP-only session cookie, never tokens. Sign-out ends both the local session and the Keycloak session.
- **Roles.** **Viewer** and **Operator** roles are taken from Keycloak. Every backend action is authorised against them. A signed-in user with neither role gets no access.
- **Audit Log.** Logins, logouts, and every allowed or denied action are recorded. Audit Entries are stored append-only in the tool's own PostgreSQL database and also written to stdout as structured JSON. Viewers and Operators can browse and filter the Audit Log in the UI.
- **Environment identity.** Every screen clearly shows which **Environment** (`test`/`accp`/`prod`) and **Municipality** the Admin Tool Instance belongs to, so admins never confuse prod with accp.
- **Helm chart.** It holds all configuration through values (Keycloak client, database, Environment identity, role names). It creates a ServiceAccount with a minimal RBAC skeleton limited to the PodiumD namespace, and runs Alembic migrations before the app starts.
- **Application shell.** A Dutch, accessible app shell (WCAG 2.2 AA) with error and status pages.
- **Developer experience.** GitHub Actions CI (lint, types, tests, chart tests, dependency scanning, image build). Local development on kind + Tilt with Keycloak and PostgreSQL. A Playwright BDD end-to-end scaffold with the first features.

## Capabilities

### New Capabilities

- `authentication`: signing in and out through the Environment's Keycloak, safe return URLs, server-held sessions, and session lifetime and expiry.
- `access-control`: the Viewer and Operator roles, how they are assigned, and the rule that every action is authorised and denied actions are refused and recorded.
- `audit-log`: what is recorded as Audit Entries (logins, logouts, allowed and denied actions), the guarantee that entries are append-only, the stdout copy, and browsing the Audit Log.
- `environment-context`: identifying the Environment and Municipality an Admin Tool Instance belongs to, and showing it to users at all times.
- `installation`: installing and configuring an Admin Tool Instance with its Helm chart, including access limited to the PodiumD namespace, the database and its users, encryption keys, trusted proxies, a hardened runtime and response headers, and health endpoints.
- `ui-shell`: the application shell, error and status pages, and the Dutch, accessible interface.

### Modified Capabilities

_None. This is the first change._

## Impact

- **New code.** `backend/`, `frontend/`, `charts/podiumd-admin/`, `.github/workflows/`, `Tiltfile`, `e2e/`. No existing code is affected.
- **External dependencies.** The Environment's Keycloak (a new confidential OIDC client with two client roles (`viewer`, `operator`) and back-channel logout configured), and the Environment's PostgreSQL server (a new database with an owner user and an application user).
- **Operational.** One Deployment, Service and Ingress or HTTPRoute (the host is provided by deploy-side values), a ServiceAccount with a namespace-scoped Role, and a pre-install/pre-upgrade migration Job.
- **Decisions relied on.** ADR 0001 (one instance per Environment), 0002 (no secrets shown), 0005 (Audit Log storage), 0006 (own chart), 0007 (compliance baseline), 0008 (stack), 0009 (hexagonal backend), 0010 (single replica), 0011 (namespace-scoped access).
