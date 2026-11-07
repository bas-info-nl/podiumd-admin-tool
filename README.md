# PodiumD Admin Tool

A web app that lets a municipality's administrators manage, operate and diagnose
their own [PodiumD](https://github.com/Dimpact-Samenwerking/helm-charts)
Environment. One Admin Tool Instance is installed per Environment (`test`,
`accp` or `prod`). It shows Effective Settings, runs Scripts from a Script
Catalogue as one-off Kubernetes Jobs, runs Diagnostic Runs of read-only Checks,
and keeps an append-only Audit Log of every attempted action.

> Status: in development. Nothing is deployable yet.

## Documentation

- [CONTEXT.md](CONTEXT.md): the domain glossary. Code, specs and docs use these
  terms.
- [docs/adr/](docs/adr/): architecture decision records (ADR 0001–0011).
- [docs/development-requirements.md](docs/development-requirements.md): testing,
  quality gates and the local development loop.
- [docs/research/podiumd.md](docs/research/podiumd.md): facts about PodiumD the
  design relies on.
- [openspec/](openspec/): change proposals, designs, specs and task lists.

## Repository layout

| Path        | Contents                                                     |
| ----------- | ------------------------------------------------------------ |
| `backend/`  | Python 3.12 FastAPI backend, hexagonal layout, managed by uv |
| `frontend/` | React + TypeScript + Vite UI, NL Design System, Dutch UI     |
| `e2e/`      | Playwright BDD end-to-end tests                              |
| `docs/`     | ADRs, development requirements and research                  |

## Licence

Licensed under the [EUPL-1.2](LICENSE). See also [publiccode.yml](publiccode.yml).
