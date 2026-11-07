# Open questions for the research phase

- **Sidecars in Component Deployments.** Find out which sidecars the PodiumD chart and its subcharts define (type c), and whether mesh injection (Istio or Linkerd, type b) is active on the AKS clusters. For each, decide whether to keep, drop or convert it to a native sidecar in Script Run Jobs.
- **Init containers.** List the init containers per Component Deployment and which ones a `manage.py` Script needs, such as wait-for-db.
- **Image layout.** Confirm the WORKDIR, the `src/manage.py` path, and the ENTRYPOINT/CMD for the Open Zaak, Objecten and Open Notificaties images.
- **Deployment choice.** Confirm which Deployment (web or Celery worker) of each Component is the right pod template for a Script Run.

Database access is direct to Azure Database for PostgreSQL, with no proxy sidecar (confirmed 2026-11-05).

## Diagnostics (pain points reported 2026-11-05)

- **External URLs.** Per Component, find which settings hold public hostnames (ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, CORS, OIDC redirect URIs, notification callback URLs, frontend base URLs) and how to check them against the Ingress hosts and DNS/TLS.
- **Connectivity between Components.** Map which Component calls which: the URL setting, the expected target Service, the health endpoint, and the auth method.
- **Mismatched secrets.** List the pairs of shared credentials, e.g. ZAC↔Keycloak client secret, Objecten↔Objecttypen token, Open Zaak↔Open Notificaties JWT client ID/secret, KISS↔OpenKlant, and where each side stores its copy.

## Design decisions raised by research (2026-11-05, see docs/research/podiumd.md). Resolved: ADR 0011, ADR 0002/0003 updates, and development-requirements, except runtime-only connectivity, which stays deferred.

- **Cross-namespace read.** Public hostnames are in Gateway API HTTPRoutes in namespace `ingress-basic`, not in the podiumd namespace. Should the tool get read access there?
- **Literal secrets in Deployment env.** For example, the office add-in has a literal `JWT_SECRET`. Effective Settings needs a rule for redacting env values that are written directly in the Deployment, not only those from `secretKeyRef`.
- **Job-based Checks.** Some useful read-only Checks are `manage.py` commands, such as `migrate --check`. May a Check start a Job?
- **NetworkPolicy allowlist.** On Cilium clusters, Script Run pods need a dedicated label allowlisted in PodiumD values (`networkPolicies.protectBackends.extraFrom.*`). This needs a per-Environment values change, or a change upstream in PodiumD.
- **Runtime-only connectivity.** Most connections between Components are rows in Component databases (zgw-consumers). Checking them needs reading through Component APIs, which ADR 0002 currently defers.
