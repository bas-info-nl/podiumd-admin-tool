# Development requirements

This is input for the OpenSpec project config and CLAUDE.md. These are working practices, not architecture decisions (see `docs/adr/` for those).

## Testing
- Domain logic is developed test-first (TDD) with pytest.
- Integration tests run against a real Kubernetes cluster (**kind**) for building, running and reconciling Script Run Jobs and for RBAC.
- End-to-end tests use **Playwright BDD** (`playwright-bdd`): Gherkin `.feature` files describe user flows in domain language (see CONTEXT.md), backed by Playwright step definitions. Cover at least: login as Viewer/Operator, a denied action, running a Script, running a Dangerous Script with Confirmation, viewing Script Run Output, a Diagnostic Run, and viewing the Audit Log.
- Frontend unit and component tests use Vitest + Testing Library.

## CI (GitHub Actions)
- Backend: ruff, mypy --strict, pytest.
- Frontend: eslint, tsc, vitest.
- Chart: helm lint, `helm template` snapshot tests, and a check that the RBAC is namespace-scoped and grants no `pods/exec` or `secrets` list.
- Playwright BDD e2e tests against kind.
- Image build, signing and SBOM on tags. Dependency scanning on every PR.

## Local development
- kind + Tilt as the main loop. docker-compose as a fallback for working on the frontend and backend only.
- A minimal fake PodiumD for local work and tests: a stub Django image with a few `manage.py` commands, a Deployment with sidecars and init containers, Secrets and an Ingress.

## Agreed v1 behaviour (input for specs)
- **Concurrency.** Only one active Script Run per Script per Environment, unless the catalogue entry sets `allowConcurrent: true`. Different Scripts can run in parallel.
- **Cancellation.** An Operator can cancel an active Script Run. The tool deletes the Job and pod, sets the status to `cancelled`, writes an Audit Entry and keeps the output captured so far. The UI warns that cancelling may leave a partial result.
- **Live output.** Script Run Output streams to the UI while the run is active (server-sent events). The stored output is shown afterwards.
- **Checks in v1** use only the Kubernetes API (within the PodiumD namespace) and HTTP/DNS/TLS probes. A Check never starts a Job in v1. Job-based Checks such as `migrate --check` come later.
- **The first Script Catalogue and Check priorities** come from `docs/research/podiumd.md` ("Implications for the design").
