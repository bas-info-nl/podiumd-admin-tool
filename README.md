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

## Development

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node.js with npm, in the
versions below. uv installs Python for the backend.

```sh
# Backend
cd backend
uv sync
uv run pytest

# Frontend
cd frontend
npm ci
npm run dev

# End-to-end tests (against a running Admin Tool Instance, E2E_BASE_URL)
cd e2e
npm ci
npx playwright install chromium
npm test
```

### Tool versions

Every tool version is set in exactly one file in this repository, and CI and
local development read that same file. Do not repeat a version in a workflow or
a doc; change the file in the table instead.

| Tool                                       | Single source                                            | Read by CI                            | Locally                                                                                             |
| ------------------------------------------ | -------------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| uv                                         | `[tool.uv] required-version` in `backend/pyproject.toml` | `setup-uv` `version-file`             | uv refuses to run the project with another version; `uv self update <version>` or `brew upgrade uv` |
| Python                                     | `backend/.python-version`                                | uv (`uv sync` in `backend/`)          | uv installs and uses it automatically                                                               |
| Node.js (and its bundled npm)              | `.nvmrc`                                                 | `setup-node` `node-version-file`      | `nvm use` (or fnm); `engine-strict` makes `npm ci` refuse another major version                     |
| pre-commit                                 | `backend/uv.lock` (backend dev dependency)               | `uv run --project backend pre-commit` | `uv run --project backend pre-commit ...`                                                           |
| gitleaks, actionlint, hadolint, shellcheck | hook `rev` in `.pre-commit-config.yaml`                  | through pre-commit                    | through pre-commit                                                                                  |
| ruff, mypy, eslint, prettier, ...          | `backend/uv.lock`, `frontend/package-lock.json`          | `uv sync --locked`, `npm ci`          | `uv sync`, `npm ci`                                                                                 |

`package.json` `engines` repeats the `.nvmrc` major version because npm cannot
read `.nvmrc`; a pre-commit hook (`.github/scripts/check-node-engines.sh`) fails
when the two disagree.

`requires-python`, ruff `target-version` and mypy `python_version` in
`backend/pyproject.toml` describe the Python language level, not the
interpreter; keep them in line with `backend/.python-version` (not checked
automatically; `requires-python` makes uv reject a `.python-version` outside it). One known gap: actionlint
runs shellcheck on `run:` scripts with whichever `shellcheck` is on `PATH`, so
that shellcheck version can differ between your machine and the CI runner.

After a version bump, update locally with `uv self update <version>` (or
`brew upgrade uv`), `nvm install` in the repository root, and `uv sync` and
`npm ci` again.

### Database and integration tests

The backend stores the Audit Log and sessions in PostgreSQL (ADR 0005, design
D2/D4). Two database roles are involved: `podiumd_admin_owner` owns the schema
and runs the Alembic migrations, and `podiumd_admin_app` is the role the
application runs with. The app role may only read and insert Audit Entries.

The persistence tests (marker `integration`, in `backend/tests/adapters/db/`)
start a real PostgreSQL with [testcontainers](https://testcontainers.com/), so
they need a running Docker. They are part of the default `uv run pytest` run and
of CI. Without Docker they fail rather than skip; to leave them out locally,
run `uv run pytest -m "not integration"`.

Run the migrations against a database as the owner role:

```sh
cd backend
PODIUMD_ADMIN_DATABASE_OWNER_URL=postgresql+psycopg://podiumd_admin_owner:...@localhost:5432/podiumd_admin \
  uv run alembic upgrade head
# Or print the SQL to review it first:
uv run alembic upgrade head --sql
```

### Pre-commit hooks

The hooks in [.pre-commit-config.yaml](.pre-commit-config.yaml) run ruff,
prettier, eslint, gitleaks, hadolint, actionlint, shellcheck and whitespace
fixers on every commit. pre-commit itself is a backend dev dependency, and the
ruff, prettier and eslint hooks use the versions locked in the backend and
frontend, so install those first. Then install the hooks once per clone:

```sh
(cd backend && uv sync) && (cd frontend && npm ci)
uv run --project backend pre-commit install
```

Run all hooks against the whole repository with
`uv run --project backend pre-commit run --all-files`. CI runs the same command
with the same pre-commit version, so a green local run means a green `hygiene`
job. The full-history gitleaks scan that CI also runs is
`uv run --project backend pre-commit run gitleaks-history --hook-stage manual`.

### Quality gates

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs these checks on
pull requests and on `main`; run them locally before you push.

| Area     | Commands                                                                                                                               |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Backend  | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run lint-imports`, `uv run pytest`, coverage gate, pip-audit |
| Frontend | `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run test:coverage`, `npm audit`                                      |
| Hygiene  | `uv run --project backend pre-commit run --all-files`, gitleaks over the full history, actionlint, hadolint, the path gate tests       |

CodeQL ([.github/workflows/codeql.yml](.github/workflows/codeql.yml)) analyses
Python and TypeScript on every pull request, on `main` and weekly. Dependabot
([.github/dependabot.yml](.github/dependabot.yml)) proposes dependency updates
weekly. All GitHub Actions are pinned to commit SHAs.

On pull requests the checks are gated by path: a job or CodeQL language only
runs when the PR touches its area, as decided by
[.github/scripts/changed-areas.sh](.github/scripts/changed-areas.sh). `hygiene`
always runs. A gated check still reports, as skipped (`backend`, `frontend`) or
as a quick pass (CodeQL), so the required checks on `main` never wait. Pushes to
`main`, the weekly CodeQL run and manual runs check everything.

| Area                           | Runs when a pull request changes                                                                                                    |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `backend`                      | `backend/`, `.gitignore`, `ci.yml`                                                                                                  |
| `frontend`                     | `frontend/`, `e2e/`, `.nvmrc`, `.prettierrc.json`, `.prettierignore`, `.editorconfig`, `.gitignore`, `ci.yml`                       |
| CodeQL (python)                | `backend/`, any `*.py` or `*.pyi` file, `codeql.yml`                                                                                |
| CodeQL (javascript-typescript) | `frontend/`, `e2e/`, any JavaScript, TypeScript or HTML file (CodeQL scans the whole repository, `.claude/` included), `codeql.yml` |
| `hygiene`                      | always                                                                                                                              |

Changing `changed-areas.sh` itself runs every gated check. `.pre-commit-config.yaml`
is only used by `hygiene`, which always runs. `hygiene` also runs
[.github/scripts/test-changed-areas.sh](.github/scripts/test-changed-areas.sh),
the tests for the gate itself; run it locally after changing the mapping.

### Coverage gate

The domain and application layers need at least 85% coverage (lines and branches
combined, design D9). The gate runs after pytest in `backend/`:

```sh
uv run pytest
uv run coverage report --include="src/podiumd_admin/domain/*,src/podiumd_admin/application/*" --fail-under=85
```

It is already enforced in CI. While `domain/` and `application/` hold only empty
packages it passes trivially (empty modules are skipped); the first domain or
application module without enough tests fails it, because coverage also reports
modules no test imports. Adapters are not part of the gate.

## Licence

Licensed under the [EUPL-1.2](LICENSE). See also [publiccode.yml](publiccode.yml).
