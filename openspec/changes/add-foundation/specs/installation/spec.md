## ADDED Requirements

### Requirement: Installed with a Helm chart, configured only through values

An Admin Tool Instance SHALL be installed into an Environment's PodiumD namespace with the `podiumd-admin` Helm chart. All configuration SHALL come from Helm values:

- the Environment identity;
- the public hostname (used for redirect URIs and cookies);
- the Keycloak issuer and client id;
- the role claim and role names;
- the database connection;
- the session timeouts;
- the trusted proxies.

Secret values (the client secret, the database credentials, the session encryption keys) SHALL be given only as references to existing Kubernetes Secrets. The chart SHALL NOT generate them. Values SHALL be validated by a JSON schema.

#### Scenario: Fresh installation

- **WHEN** an installer installs the chart with valid values and the referenced Secrets
- **THEN** the Admin Tool Instance becomes ready
- **AND** once the Environment's route to it is in place, the configured hostname serves the sign-in flow

#### Scenario: Invalid values

- **WHEN** required values are missing, such as the stage, the Keycloak issuer or the encryption-key Secret reference
- **THEN** `helm install` fails with a validation error naming the missing value

### Requirement: Session encryption keys

The keys that encrypt stored tokens SHALL come from a referenced Secret. The Secret SHALL support one primary key and older keys, so keys can be rotated without ending sessions. The Admin Tool Instance SHALL refuse to start if no key is configured, or if a key matches a known development key.

#### Scenario: Development key in prod

- **WHEN** an Admin Tool Instance is configured with the development encryption key shipped for local use
- **THEN** it refuses to start with an error

### Requirement: Trusted proxies

The Admin Tool Instance SHALL trust forwarded-for headers only from configured proxy address ranges. By default, no proxy is trusted. The client IP address recorded in Audit Entries SHALL be the address of the nearest client that is not a trusted proxy.

#### Scenario: Spoofed forwarded header

- **WHEN** no proxies are configured and a request carries `X-Forwarded-For: 1.2.3.4`
- **THEN** the Audit Entry records the connecting peer's address, not `1.2.3.4`

### Requirement: Cluster access limited to the PodiumD namespace

The chart SHALL create a dedicated ServiceAccount, and a Role and RoleBinding in the release namespace only. It SHALL create no ClusterRole or ClusterRoleBinding. In this change, the Role SHALL grant only what the tool needs to operate itself. It SHALL NOT grant `pods/exec`, nor `list` or `watch` on Secrets, now or in later changes.

#### Scenario: RBAC review

- **WHEN** the rendered chart is inspected by the chart tests
- **THEN** it contains no cluster-scoped RBAC, no `pods/exec`, and no `list` or `watch` on Secrets

### Requirement: Own database with managed schema

The Admin Tool Instance SHALL use its own PostgreSQL database with two database users:

- an owner user, which runs schema migrations;
- an application user, which the running tool uses.

Migrations SHALL run automatically on install and upgrade, before the new version serves traffic. A failed migration SHALL stop the upgrade, leaving the previous version in place.

#### Scenario: Upgrade with a new migration

- **WHEN** the chart is upgraded to a version with a new database migration
- **THEN** the migration is applied with the owner user before any new pod serves traffic

### Requirement: Hardened runtime and responses

The container SHALL:

- run as a non-root user;
- have a read-only root filesystem;
- not allow privilege escalation;
- drop all Linux capabilities.

Every HTTP response SHALL carry:

- a Content-Security-Policy of at least `default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'`;
- `X-Content-Type-Options: nosniff`;
- `Referrer-Policy: no-referrer`.

API responses SHALL also carry `Cache-Control: no-store`. Interactive API documentation SHALL NOT be served.

#### Scenario: Security context

- **WHEN** the rendered Deployment is inspected
- **THEN** `runAsNonRoot` and `readOnlyRootFilesystem` are true, `allowPrivilegeEscalation` is false, and capabilities drop `ALL`

#### Scenario: Response headers

- **WHEN** any page or API endpoint is requested
- **THEN** the response carries the required security headers
- **AND** `/docs` and `/openapi.json` return 404

### Requirement: Health endpoints

The Admin Tool Instance SHALL expose two unauthenticated health endpoints that reveal no configuration:

- a liveness endpoint, which reports whether the process is running;
- a readiness endpoint, which reports whether the database is reachable.

#### Scenario: Database unreachable

- **WHEN** the database becomes unreachable
- **THEN** the readiness endpoint reports not-ready while the liveness endpoint stays healthy
