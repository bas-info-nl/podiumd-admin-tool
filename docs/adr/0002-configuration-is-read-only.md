# The Admin Tool never writes configuration, and reads secrets only to compare them

The Admin Tool shows Deployment Configuration (as Effective Settings) and Runtime Configuration, but never changes either. Deployment Configuration changes still go through the Values Repository and its deployment pipeline. Runtime Configuration is still changed in each Component's own admin interface. The only way the tool can act on an Environment is by running a Script.

Secrets are never shown or edited. There is one narrow exception, added on 2026-11-05 because mismatched shared credentials between Components are a common real-world misconfiguration. A Check may read specific Kubernetes Secret keys that it explicitly declares, only to compare one Component's copy of a shared credential with another's. The values stay in backend memory for the comparison and never reach the frontend, the database, the Audit Log or any log output. A Finding reports only match or mismatch. RBAC grants `get` on named Secrets (`resourceNames`), never `list`.

## Consequences

- Credential pairs whose copy lives inside a Component's own database, such as Keycloak clients or Open Zaak JWT applicaties, cannot be checked this way. Covering them would need admin API access to those Components, which is deferred.
- Effective Settings leave out every value that comes from a Secret. Values written directly into a Deployment's env are shown only if the variable name is on an allowlist of known-safe settings (URLs, hosts, flags, ports). Everything else is masked, because some Deployments put secrets in env as literal values (e.g. the office add-in `JWT_SECRET`).
